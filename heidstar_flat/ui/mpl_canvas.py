"""matplotlib 嵌入 Qt 的画布封装。

启动时尝试为 matplotlib 选一个中文字体，避免标题/坐标轴/图例渲染成方块。
找不到时打一行警告，但程序仍可运行（中文文字会渲染为方块）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

# 确保 matplotlib 使用 Qt 后端 + 中文字体
import matplotlib

matplotlib.use("Qt5Agg", force=True)

from matplotlib import font_manager as _fm  # noqa: E402

_CJK_CANDIDATES = (
    "Noto Sans CJK SC",
    "Noto Sans CJK TC",
    "Noto Sans CJK JP",
    "Noto Sans CJK HK",
    "Noto Sans CJK",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "PingFang SC",
    "Microsoft YaHei",
    "SimHei",
    "Heiti SC",
    "AR PL UMing CN",
)


def _pick_cjk_font() -> Optional[str]:
    available = {f.name for f in _fm.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in available:
            return name
    return None


_cjk = _pick_cjk_font()
if _cjk:
    matplotlib.rcParams["font.family"] = ["sans-serif"]
    # 把中文字体放第一位，DejaVu Sans 兜底（处理少数 ASCII 拉丁符号）
    matplotlib.rcParams["font.sans-serif"] = [_cjk, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
else:
    import sys

    print(
        "[heidstar_flat] 未找到中文字体（Noto Sans CJK / WenQuanYi 等），"
        "matplotlib 中文将渲染为方块。Ubuntu 上可执行: "
        "sudo apt install fonts-noto-cjk",
        file=sys.stderr,
    )


from matplotlib.backends.backend_qt5agg import (  # noqa: E402
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.figure import Figure  # noqa: E402

from PyQt5.QtWidgets import QVBoxLayout, QWidget  # noqa: E402


class _CanvasBase(QWidget):
    def __init__(self, parent=None, with_toolbar: bool = False) -> None:
        super().__init__(parent)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if with_toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def clear(self) -> None:
        self.figure.clear()
        self.canvas.draw_idle()


class HeatmapCanvas(_CanvasBase):
    """归一化平场热力图 + 中心十字断面。

    亦提供 `show_placeholder()` / `show_preview()` 用于空闲态展示。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent, with_toolbar=True)

    def show_placeholder(self, text: str) -> None:
        """画一段居中提示文字（运行前的空闲态）。"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            fontsize=12,
            color="#666666",
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        self.canvas.draw_idle()

    def show_preview(self, image_path: Path, caption: str) -> None:
        """加载并展示一张轻量预览图（如 Thumbs/Preview-*.tif）。"""
        try:
            import tifffile

            img = tifffile.imread(str(image_path))
        except Exception as e:
            self.show_placeholder(f"预览加载失败: {e}")
            return

        self.figure.clear()
        ax = self.figure.add_subplot(111)
        if img.ndim == 3 and img.shape[-1] in (3, 4):
            ax.imshow(img, origin="upper")
        else:
            ax.imshow(img, cmap="gray", origin="upper")
        ax.set_title(caption, fontsize=10, color="#444")
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw_idle()

    def show_flatfield(self, normalized: np.ndarray, title: str = "") -> None:
        self.figure.clear()
        gs = self.figure.add_gridspec(2, 2, width_ratios=[3, 2], height_ratios=[3, 1])

        ax_img = self.figure.add_subplot(gs[0, 0])
        im = ax_img.imshow(
            normalized,
            cmap="viridis",
            vmin=0.0,
            vmax=1.0,
            origin="upper",
            aspect="equal",
        )
        ax_img.set_title(title or "归一化平场")
        ax_img.set_xlabel("X (pixels)")
        ax_img.set_ylabel("Y (pixels)")
        self.figure.colorbar(im, ax=ax_img, fraction=0.046, pad=0.04, label="强度")

        ax_hist = self.figure.add_subplot(gs[0, 1])
        ax_hist.hist(
            normalized.ravel(), bins=50, color="#3a6ea5", edgecolor="black", alpha=0.8
        )
        ax_hist.set_xlim(0, 1)
        ax_hist.set_title("强度分布")
        ax_hist.set_xlabel("归一化强度")
        ax_hist.set_ylabel("像素数")
        ax_hist.grid(True, alpha=0.3)

        h, w = normalized.shape
        cr, cc = h // 2, w // 2
        ax_cs = self.figure.add_subplot(gs[1, :])
        ax_cs.plot(normalized[cr, :], label=f"行 {cr}", color="#1f77b4")
        ax_cs.plot(normalized[:, cc], label=f"列 {cc}", color="#d62728")
        ax_cs.set_ylim(0, 1.05)
        ax_cs.set_xlabel("像素位置")
        ax_cs.set_ylabel("归一化强度")
        ax_cs.set_title("中心十字断面")
        ax_cs.legend(loc="lower right")
        ax_cs.grid(True, alpha=0.3)

        self.canvas.draw_idle()


class ExampleTripletCanvas(_CanvasBase):
    """一张原图 / 校正后 / 差异的三联画。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, with_toolbar=False)

    def show_triplet(
        self,
        original: np.ndarray,
        corrected: np.ndarray,
        difference: np.ndarray,
        index: int,
    ) -> None:
        self.figure.clear()
        axes = self.figure.subplots(1, 3)

        for ax, img, title, cmap in zip(
            axes,
            [original, corrected, difference],
            [f"原图 #{index}", f"校正后 #{index}", "差异 (校正后 - 原图)"],
            ["gray", "gray", "RdBu_r"],
        ):
            if cmap == "RdBu_r":
                vmax = float(np.max(np.abs(img))) if np.any(img) else 1.0
                im = ax.imshow(img, cmap=cmap, vmin=-vmax, vmax=vmax, origin="upper")
            else:
                im = ax.imshow(img, cmap=cmap, origin="upper")
            ax.set_title(title, fontsize=10)
            ax.set_xticks([])
            ax.set_yticks([])
            self.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        self.canvas.draw_idle()
