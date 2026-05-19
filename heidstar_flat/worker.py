"""QThread worker：依次处理多个通道，结果通过 Qt 信号传给主线程。

设计要点：
- 单 QThread 顺序跑，所有重计算在子线程内进行；
- 每个通道完成后释放图像栈和 BaSiC/JAX 资源，缓解长时间内存累积；
- numpy 数组等通过信号传引用即可（PyQt5 信号本身在跨线程时会做必要的封装）。
"""

from __future__ import annotations

import gc
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from heidstar_flat.config import ChannelConfig
from heidstar_flat.core.flatfield import calculate_flatfield, clear_jax_caches
from heidstar_flat.core.loader import load_image_stack
from heidstar_flat.core.metrics import (
    ExampleTriplet,
    UniformityMetrics,
    build_examples,
    compute_metrics,
    passes_threshold,
)


@dataclass
class ChannelResult:
    wavelength: str
    pattern: str
    threshold: float
    num_images: int
    flatfield_normalized: np.ndarray
    metrics: UniformityMetrics
    examples: List[ExampleTriplet]
    passed: bool
    output_dir: Path


class FlatfieldWorker(QObject):
    """跑在 QThread 内的工作对象。"""

    stage_changed = pyqtSignal(str, str)            # (wavelength, stage_text)
    log = pyqtSignal(str)                           # 任意日志
    channel_done = pyqtSignal(object)               # ChannelResult
    channel_failed = pyqtSignal(str, str)           # (wavelength, error_text)
    progress = pyqtSignal(str, int, int)            # (wavelength, current, total)
    finished = pyqtSignal()

    def __init__(
        self,
        input_dir: str,
        output_root: str,
        channels: List[ChannelConfig],
        examples_per_channel: int,
    ) -> None:
        super().__init__()
        self._input_dir = input_dir
        self._output_root = Path(output_root)
        self._channels = channels
        self._examples_per_channel = examples_per_channel
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            for ch in self._channels:
                if self._stop:
                    self.log.emit(f"用户终止，跳过 {ch.wavelength} nm 之后的通道")
                    break
                self._process_channel(ch)
        finally:
            self.finished.emit()

    def _process_channel(self, ch: ChannelConfig) -> None:
        wl = ch.wavelength
        out_dir = self._output_root / f"flatfield_results_{wl}nm"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)

            self.stage_changed.emit(wl, "加载图像")
            self.log.emit(f"[{wl} nm] 扫描目录 {self._input_dir} (pattern={ch.pattern})")

            def on_load(cur: int, total: int) -> None:
                self.progress.emit(wl, cur, total)

            stack, filenames = load_image_stack(
                self._input_dir, ch.pattern, progress=on_load
            )
            self.log.emit(f"[{wl} nm] 加载 {len(filenames)} 张，形状 {stack.shape}")

            if self._stop:
                self.log.emit(f"[{wl} nm] 加载完毕后收到终止信号")
                return

            self.stage_changed.emit(wl, "BaSiC 拟合平场")
            flatfield = calculate_flatfield(stack)
            self.log.emit(f"[{wl} nm] 平场拟合完成，shape={flatfield.shape}")

            self.stage_changed.emit(wl, "计算均匀性指标")
            normalized, metrics = compute_metrics(flatfield)
            ok = passes_threshold(metrics, ch.uniformity_threshold)
            self.log.emit(
                f"[{wl} nm] Michelson={metrics.michelson_uniformity_pct:.2f}% "
                f"阈值={ch.uniformity_threshold:.2f}% -> {'OK' if ok else 'NG'}"
            )

            self.stage_changed.emit(wl, "生成示例对比")
            examples = build_examples(stack, flatfield, self._examples_per_channel)

            # 落盘：原始平场、归一化平场
            try:
                import tifffile

                tifffile.imwrite(out_dir / "flatfield.tiff", flatfield.astype(np.float32))
                np.save(out_dir / "flatfield.npy", flatfield)
                tifffile.imwrite(
                    out_dir / "flatfield_normalized.tiff",
                    normalized.astype(np.float32),
                )
            except Exception as e:
                self.log.emit(f"[{wl} nm] 落盘失败 (不影响 UI 展示): {e}")

            result = ChannelResult(
                wavelength=wl,
                pattern=ch.pattern,
                threshold=ch.uniformity_threshold,
                num_images=len(filenames),
                flatfield_normalized=normalized,
                metrics=metrics,
                examples=examples,
                passed=ok,
                output_dir=out_dir,
            )
            self.channel_done.emit(result)

        except Exception as e:
            tb = traceback.format_exc()
            self.log.emit(f"[{wl} nm] 失败: {e}\n{tb}")
            self.channel_failed.emit(wl, f"{e}")
        finally:
            # 主动释放：避免下一通道 OOM
            try:
                del stack  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                del flatfield  # type: ignore[name-defined]
            except Exception:
                pass
            clear_jax_caches()
            gc.collect()


def make_worker_thread(worker: FlatfieldWorker) -> QThread:
    """把 worker move 到一个独立 QThread。调用方负责 start/wait/quit。"""
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return thread
