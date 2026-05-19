"""QThread Worker：依次跑给定通道列表。

入参由调用方负责合并：`DiscoveredChannel`（来自扫盘）+ 用户阈值偏好。
"""

from __future__ import annotations

import gc
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from heidstar_flat.core.flatfield import calculate_flatfield, clear_jax_caches
from heidstar_flat.core.loader import DiscoveredChannel, load_channel_tiles
from heidstar_flat.core.metrics import (
    ExampleTriplet,
    UniformityMetrics,
    VerdictResult,
    VerdictThresholds,
    build_examples,
    compute_metrics,
    evaluate_verdict,
)


@dataclass
class ChannelJob:
    """一个待处理通道：发现结果 + 全部阈值 + 显示名。"""

    discovered: DiscoveredChannel
    display_name: str
    thresholds: VerdictThresholds

    @property
    def suffix(self) -> str:
        return self.discovered.suffix


@dataclass
class ChannelResult:
    job: ChannelJob
    num_images: int
    flatfield_normalized: np.ndarray
    metrics: UniformityMetrics
    examples: List[ExampleTriplet]
    verdict: VerdictResult
    output_dir: Path

    @property
    def suffix(self) -> str:
        return self.job.suffix

    # 向后兼容（PDF/老代码可能还用 .passed / .verdict_reason）
    @property
    def passed(self) -> bool:
        return self.verdict.passed

    @property
    def verdict_reason(self) -> str:
        return self.verdict.reason


class FlatfieldWorker(QObject):
    stage_changed = pyqtSignal(str, str)       # (suffix, stage_text)
    log = pyqtSignal(str)
    channel_done = pyqtSignal(object)          # ChannelResult
    channel_failed = pyqtSignal(str, str)      # (suffix, error_text)
    progress = pyqtSignal(str, int, int)       # (suffix, current, total)
    finished = pyqtSignal()

    def __init__(
        self,
        jobs: List[ChannelJob],
        output_root: str | Path,
        examples_per_channel: int,
        image_glob: str = "IMG*.tif",
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._output_root = Path(output_root)
        self._examples_per_channel = examples_per_channel
        self._image_glob = image_glob
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            for job in self._jobs:
                if self._stop:
                    self.log.emit(f"用户终止，跳过 {job.suffix} 之后的通道")
                    break
                self._process_channel(job)
        finally:
            self.finished.emit()

    def _process_channel(self, job: ChannelJob) -> None:
        suffix = job.suffix
        out_dir = self._output_root / f"flatfield_results_{suffix}"
        stack = None
        flatfield = None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)

            self.stage_changed.emit(suffix, "加载瓦片")
            self.log.emit(
                f"[{suffix}] 扫描 {job.discovered.image_dir} "
                f"(共 {job.discovered.num_tiles} 张)"
            )

            def on_load(cur: int, total: int) -> None:
                self.progress.emit(suffix, cur, total)

            t = time.monotonic()
            stack, filenames = load_channel_tiles(
                job.discovered, image_glob=self._image_glob, progress=on_load
            )
            self.log.emit(
                f"[{suffix}] 加载 {len(filenames)} 张完成 ({time.monotonic()-t:.1f}s)，"
                f"形状 {stack.shape} dtype={stack.dtype}"
            )

            if self._stop:
                self.log.emit(f"[{suffix}] 加载完毕后收到终止信号")
                return

            self.stage_changed.emit(suffix, "BaSiC 拟合平场")
            self.log.emit(
                f"[{suffix}] BaSiC 开始拟合 {stack.shape} {stack.dtype}。"
                f"首次运行需 JAX/JIT 编译，可能 10-60s；后续通道会快很多。"
            )
            t = time.monotonic()
            flatfield = calculate_flatfield(stack)
            self.log.emit(
                f"[{suffix}] BaSiC 拟合完成 ({time.monotonic()-t:.1f}s)，shape={flatfield.shape}"
            )

            self.stage_changed.emit(suffix, "计算均匀性指标")
            normalized, metrics = compute_metrics(flatfield)
            verdict = evaluate_verdict(metrics, job.thresholds)
            self.log.emit(
                f"[{suffix}] robust Min/Max={metrics.robust_min_max_ratio_pct:.2f}% "
                f"(原始 {metrics.min_max_ratio_pct:.2f}%), "
                f"CV={metrics.cv_uniformity_pct:.2f}%, "
                f"Michelson={metrics.michelson_uniformity_pct:.2f}%"
            )
            self.log.emit(
                f"[{suffix}] 九区: 四角对称={metrics.nine_zone_corner_symmetry_pct:.2f}%, "
                f"中心最亮={metrics.nine_zone_center_to_max_pct:.2f}%, "
                f"最暗格={metrics.nine_zone_min_to_max_pct:.2f}%, "
                f"粗糙度={metrics.nine_zone_uniformity_pct:.2f}%"
            )
            self.log.emit(
                f"[{suffix}] Min 位置 (row,col)={metrics.min_position}, "
                f"Max 位置={metrics.max_position}"
            )
            self.log.emit(f"[{suffix}] 判定: {verdict.reason}")

            self.stage_changed.emit(suffix, "生成示例对比")
            examples = build_examples(stack, flatfield, self._examples_per_channel)

            try:
                import tifffile

                tifffile.imwrite(out_dir / "flatfield.tiff", flatfield.astype(np.float32))
                np.save(out_dir / "flatfield.npy", flatfield)
                tifffile.imwrite(
                    out_dir / "flatfield_normalized.tiff",
                    normalized.astype(np.float32),
                )
            except Exception as e:
                self.log.emit(f"[{suffix}] 落盘失败 (不影响 UI 展示): {e}")

            result = ChannelResult(
                job=job,
                num_images=len(filenames),
                flatfield_normalized=normalized,
                metrics=metrics,
                examples=examples,
                verdict=verdict,
                output_dir=out_dir,
            )
            self.channel_done.emit(result)

        except Exception as e:
            tb = traceback.format_exc()
            self.log.emit(f"[{suffix}] 失败: {e}\n{tb}")
            self.channel_failed.emit(suffix, f"{e}")
        finally:
            del stack
            del flatfield
            clear_jax_caches()
            gc.collect()


def make_worker_thread(worker: FlatfieldWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread
