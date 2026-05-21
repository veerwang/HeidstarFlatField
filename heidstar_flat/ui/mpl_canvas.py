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

# 全局放大画布内字号（标题/坐标/刻度/图例/figure 标题）
matplotlib.rcParams.update(
    {
        "font.size": 12,
        "axes.titlesize": 14,
        "axes.labelsize": 13,
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "legend.fontsize": 11,
        "figure.titlesize": 15,
    }
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

    # 主线程同步读 TIFF 的大小阈值；超过的预览图直接跳过显示占位文字，
    # 避免在「扫描完成 → 自动刷预览」的瞬间因为大文件 I/O 把 UI 卡住几秒。
    _PREVIEW_MAX_BYTES = 20 * 1024 * 1024

    def show_preview(self, image_path: Path, caption: str) -> None:
        """加载并展示一张轻量预览图（如 Thumbs/Preview-*.tif）。"""
        try:
            size = image_path.stat().st_size
        except OSError:
            size = 0
        if size > self._PREVIEW_MAX_BYTES:
            self.show_placeholder(
                f"预览图过大已跳过 ({size / 1024 / 1024:.1f} MB)\n\n"
                f"{image_path.name}\n\n"
                f"运行通道后此处会显示归一化平场热力图。"
            )
            return

        try:
            import tifffile

            img = tifffile.imread(str(image_path))
        except Exception as e:
            msg = str(e)
            hint = ""
            if "imagecodecs" in msg.lower() or "lzw" in msg.lower():
                hint = (
                    "\n\n该 TIFF 使用 LZW 压缩，需要安装可选依赖：\n"
                    "    pip install imagecodecs"
                )
            self.show_placeholder(f"预览加载失败: {msg}{hint}")
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

    def show_flatfield(
        self,
        normalized: np.ndarray,
        title: str = "",
        min_pos: tuple | None = None,
        max_pos: tuple | None = None,
    ) -> None:
        self.figure.clear()
        # 布局：热力图独占整列左侧（更大更接近原始正方形），
        #       直方图 + 中心十字断面在右侧上下堆叠。
        gs = self.figure.add_gridspec(2, 2, width_ratios=[3, 2], height_ratios=[1, 1])

        ax_img = self.figure.add_subplot(gs[:, 0])
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

        # 标注 Min/Max 像素位置（辨别"暗角"vs"中心异常"）
        if min_pos is not None:
            r, c = min_pos
            ax_img.plot(
                c, r, "x",
                color="red", markersize=16, markeredgewidth=2.5,
                label=f"Min @ ({r},{c})",
            )
        if max_pos is not None:
            r, c = max_pos
            ax_img.plot(
                c, r, "o",
                color="#ffd166", markersize=12, markeredgewidth=2.0,
                markerfacecolor="none",
                label=f"Max @ ({r},{c})",
            )
        if min_pos is not None or max_pos is not None:
            ax_img.legend(loc="upper right", framealpha=0.85, fontsize=9)

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
        ax_cs = self.figure.add_subplot(gs[1, 1])
        ax_cs.plot(normalized[cr, :], label=f"行 {cr}", color="#1f77b4")
        ax_cs.plot(normalized[:, cc], label=f"列 {cc}", color="#d62728")
        ax_cs.set_ylim(0, 1.05)
        ax_cs.set_xlabel("像素位置")
        ax_cs.set_ylabel("归一化强度")
        ax_cs.set_title("中心十字断面")
        ax_cs.legend(loc="lower right", fontsize=9)
        ax_cs.grid(True, alpha=0.3)

        self.canvas.draw_idle()

    def show_dark_mean(
        self,
        dark_mean: np.ndarray,
        sensor_max: float,
        title: str = "",
        max_pos: tuple | None = None,
    ) -> None:
        """暗场均值图 + 灰度分布 + 9 区均值 mini 热力图。

        与 show_flatfield 的区别：
        - vmin/vmax 用 dark_mean 实际范围（暗场总体很暗、绝对值小），
          否则按 [0,1] 整图一团黑色看不出空间结构
        - 标注最亮像素位置（疑似杂光斑）
        - 右下用 9 区 mini 热力图替代中心十字断面（暗场断面没信息）
        """
        self.figure.clear()
        gs = self.figure.add_gridspec(2, 2, width_ratios=[3, 2], height_ratios=[1, 1])

        ax_img = self.figure.add_subplot(gs[:, 0])
        vmin = float(dark_mean.min())
        vmax = float(max(dark_mean.max(), vmin + 1e-6))  # 防止 vmin == vmax
        im = ax_img.imshow(
            dark_mean, cmap="viridis", vmin=vmin, vmax=vmax,
            origin="upper", aspect="equal",
        )
        ax_img.set_title(title or "暗场均值图")
        ax_img.set_xlabel("X (pixels)")
        ax_img.set_ylabel("Y (pixels)")
        self.figure.colorbar(im, ax=ax_img, fraction=0.046, pad=0.04, label="灰度值")

        if max_pos is not None:
            r, c = max_pos
            ax_img.plot(
                c, r, "o",
                color="red", markersize=14, markeredgewidth=2.2,
                markerfacecolor="none",
                label=f"Max @ ({r},{c})",
            )
            ax_img.legend(loc="upper right", framealpha=0.85, fontsize=9)

        # 右上：灰度分布
        ax_hist = self.figure.add_subplot(gs[0, 1])
        ax_hist.hist(
            dark_mean.ravel(), bins=50,
            color="#3a6ea5", edgecolor="black", alpha=0.8,
        )
        ax_hist.set_title("灰度分布")
        ax_hist.set_xlabel("灰度值")
        ax_hist.set_ylabel("像素数")
        ax_hist.grid(True, alpha=0.3)

        # 右下：9 区 mini 热力图（直观看暗本底空间分布）
        h, w = dark_mean.shape
        rs = np.linspace(0, h, 4, dtype=int)
        cs = np.linspace(0, w, 4, dtype=int)
        zone_grid = np.zeros((3, 3))
        for i in range(3):
            for j in range(3):
                zone_grid[i, j] = float(
                    dark_mean[rs[i]:rs[i + 1], cs[j]:cs[j + 1]].mean()
                )
        ax_zone = self.figure.add_subplot(gs[1, 1])
        ax_zone.imshow(zone_grid, cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")
        ax_zone.set_title(
            f"9 区均值（占满量程 {dark_mean.mean()/sensor_max*100:.3f}%）",
            fontsize=10,
        )
        ax_zone.set_xticks([0, 1, 2])
        ax_zone.set_yticks([0, 1, 2])
        midpoint = (vmin + vmax) / 2
        for i in range(3):
            for j in range(3):
                ax_zone.text(
                    j, i, f"{zone_grid[i, j]:.1f}",
                    ha="center", va="center",
                    color="white" if zone_grid[i, j] < midpoint else "black",
                    fontsize=9,
                )

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
