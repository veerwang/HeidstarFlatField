"""杂散光评估 QThread Worker：依次跑给定通道列表的暗场指标计算。

与 FlatfieldWorker 的差异：
- 不做平场拟合（无 BaSiC/JAX 调用）
- 不生成示例三联画
- 只算 StrayLightMetrics + verdict
- 落盘内容更轻量（仅暗场均值图 + JSON 指标可选）
"""

from __future__ import annotations

import gc
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List

import numpy as np
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from heidstar_flat.core.loader import DiscoveredChannel, load_channel_tiles
from heidstar_flat.core.stray_light import (
    StrayLightMetrics,
    StrayLightThresholds,
    StrayLightVerdict,
    compute_stray_metrics,
    evaluate_stray,
)


@dataclass
class StrayChannelJob:
    """一个待处理通道：发现结果 + 阈值 + 显示名。"""

    discovered: DiscoveredChannel
    display_name: str
    thresholds: StrayLightThresholds

    @property
    def suffix(self) -> str:
        return self.discovered.suffix


@dataclass
class StrayChannelResult:
    job: StrayChannelJob
    num_images: int
    metrics: StrayLightMetrics
    verdict: StrayLightVerdict
    dark_mean_image: np.ndarray   # H×W float32，用于 UI 热力图与 PDF
    output_dir: Path

    @property
    def suffix(self) -> str:
        return self.job.suffix

    @property
    def passed(self) -> bool:
        return self.verdict.passed


class StrayLightWorker(QObject):
    stage_changed = pyqtSignal(str, str)       # (suffix, stage_text)
    log = pyqtSignal(str)
    channel_done = pyqtSignal(object)          # StrayChannelResult
    channel_failed = pyqtSignal(str, str)      # (suffix, error_text)
    progress = pyqtSignal(str, int, int)       # (suffix, current, total)
    finished = pyqtSignal()

    def __init__(
        self,
        jobs: List[StrayChannelJob],
        output_root: str | Path,
        image_glob: str = "IMG*.tif",
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._output_root = Path(output_root)
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

    def _process_channel(self, job: StrayChannelJob) -> None:
        suffix = job.suffix
        out_dir = self._output_root / f"stray_results_{suffix}"
        stack = None
        dark_mean_img = None
        try:
            out_dir.mkdir(parents=True, exist_ok=True)

            self.stage_changed.emit(suffix, "加载暗场瓦片")
            self.log.emit(
                f"[{suffix}] 扫描 {job.discovered.image_dir} "
                f"(共 {job.discovered.num_tiles} 张暗场)"
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

            self.stage_changed.emit(suffix, "计算杂散光指标")
            t = time.monotonic()
            metrics = compute_stray_metrics(stack)
            verdict = evaluate_stray(metrics, job.thresholds)
            self.log.emit(
                f"[{suffix}] DC1={metrics.dc_pct_of_max:.4f}% "
                f"(mean={metrics.dark_mean:.2f}/{metrics.sensor_max:.0f}), "
                f"DC2={metrics.zone_dc_uniformity_pct:.2f}% "
                f"({time.monotonic()-t:.1f}s)"
            )
            self.log.emit(
                f"[{suffix}] 暗场最亮像素位置={metrics.max_pixel_position}, "
                f"极值范围 [{metrics.dark_min:.2f}, {metrics.dark_max:.2f}]"
            )
            self.log.emit(f"[{suffix}] 判定: {verdict.reason}")

            # 暗场均值图（用于 UI 热力图与 PDF）
            dark_mean_img = stack.astype(np.float32).mean(axis=0)

            try:
                import tifffile

                tifffile.imwrite(
                    out_dir / "dark_mean.tiff",
                    dark_mean_img.astype(np.float32),
                )
            except Exception as e:
                self.log.emit(f"[{suffix}] 暗场均值图落盘失败 (不影响 UI 展示): {e}")

            result = StrayChannelResult(
                job=job,
                num_images=len(filenames),
                metrics=metrics,
                verdict=verdict,
                dark_mean_image=dark_mean_img,
                output_dir=out_dir,
            )
            self.channel_done.emit(result)

        except Exception as e:
            tb = traceback.format_exc()
            self.log.emit(f"[{suffix}] 失败: {e}\n{tb}")
            self.channel_failed.emit(suffix, f"{e}")
        finally:
            del stack
            del dark_mean_img
            gc.collect()


def make_stray_worker_thread(worker: StrayLightWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread
