"""单个通道结果页：头部元数据 / 状态徽章 / 热力图 / 指标 + 画廊。

状态机：
  - idle       —— 程序未开始；徽章显示「待开始」，热力图区显示预览缩略图
  - queued     —— 用户已点开始，但本通道在排队；徽章显示「排队 N/M」
  - running    —— 处理中；徽章带阶段名 + 秒表，例如「运行中 · BaSiC 拟合 (0:42)」
  - pass/fail  —— 完成；徽章 PASS / FAIL
  - error      —— 失败；徽章显示错误摘要
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.core.loader import DiscoveredChannel
from heidstar_flat.ui.gallery import GalleryView
from heidstar_flat.ui.metrics_table import MetricsPanel
from heidstar_flat.ui.mpl_canvas import HeatmapCanvas


class VerdictBadge(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__("待开始", parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(36)
        self.setMinimumWidth(160)
        self._apply_style("#888888", "#ffffff")

    def _apply_style(self, bg: str, fg: str) -> None:
        self.setStyleSheet(
            f"QLabel {{ background-color: {bg}; color: {fg}; "
            f"font-weight: bold; font-size: 14px; border-radius: 4px; "
            f"padding: 4px 12px; }}"
        )

    def set_idle(self) -> None:
        self.setText("待开始 — 点击「开始」运行")
        self._apply_style("#6b6b6b", "#ffffff")

    def set_queued(self, position: int, total: int) -> None:
        self.setText(f"排队 {position}/{total}")
        self._apply_style("#888888", "#ffffff")

    def set_running(self, text: str) -> None:
        self.setText(f"运行中 · {text}")
        self._apply_style("#1f6feb", "#ffffff")

    def set_ok(self) -> None:
        self.setText("PASS")
        self._apply_style("#2ea043", "#ffffff")

    def set_ng(self) -> None:
        self.setText("FAIL")
        self._apply_style("#cf222e", "#ffffff")

    def set_error(self, msg: str) -> None:
        self.setText(f"错误: {msg[:40]}")
        self._apply_style("#bf4b00", "#ffffff")


class ColorSwatch(QLabel):
    def __init__(self, hex_color: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.set_color(hex_color)

    def set_color(self, hex_color: Optional[str]) -> None:
        if hex_color and QColor(hex_color).isValid():
            self.setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #222; border-radius: 3px;"
            )
        else:
            self.setStyleSheet(
                "background-color: #bbbbbb; border: 1px solid #222; border-radius: 3px;"
            )


def _fmt_exposure(us: Optional[float]) -> str:
    if us is None:
        return "—"
    if us >= 1000:
        return f"{us/1000:.2f} ms"
    return f"{us:.0f} µs"


def _fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    mm, ss = divmod(s, 60)
    return f"{mm}:{ss:02d}"


class ChannelTab(QWidget):
    def __init__(self, suffix: str, display_name: str, threshold: float, parent=None) -> None:
        super().__init__(parent)
        self.suffix = suffix
        self.display_name = display_name

        # 状态机字段
        self._active_stage: Optional[str] = None
        self._stage_start: Optional[float] = None
        self._loading_cur: int = 0
        self._loading_total: int = 0

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self.swatch = ColorSwatch(None)
        header.addWidget(self.swatch)
        self.name_label = QLabel(f"<b>{display_name}</b>")
        header.addWidget(self.name_label)
        header.addSpacing(12)
        self.badge = VerdictBadge()
        header.addWidget(self.badge)
        header.addStretch(1)
        self.threshold_label = QLabel(f"阈值 (Min/Max) ≥ {threshold:.2f}%")
        self.threshold_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.threshold_label)
        root.addLayout(header)

        meta = QFrame()
        meta.setFrameShape(QFrame.StyledPanel)
        meta_grid = QGridLayout(meta)
        meta_grid.setContentsMargins(8, 6, 8, 6)
        meta_grid.setHorizontalSpacing(18)
        self._meta_value_labels: dict[str, QLabel] = {}
        for col, key in enumerate(["荧光", "曝光", "增益", "瓦片", "网格", "位深"]):
            k = QLabel(f"<span style='color:#666'>{key}</span>")
            v = QLabel("—")
            v.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            meta_grid.addWidget(k, 0, col * 2)
            meta_grid.addWidget(v, 0, col * 2 + 1)
            self._meta_value_labels[key] = v
        meta_grid.setColumnStretch(meta_grid.columnCount(), 1)
        root.addWidget(meta)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        splitter = QSplitter(Qt.Horizontal, self)
        self.heatmap = HeatmapCanvas(splitter)
        # 默认显示"待运行"提示，避免空白看着像挂了
        self.heatmap.show_placeholder(
            "尚未运行\n\n点击下方「开始」后，这里会显示该通道的归一化平场热力图、\n"
            "中心十字断面与强度直方图。"
        )
        splitter.addWidget(self.heatmap)

        right = QTabWidget(splitter)
        self.metrics_panel = MetricsPanel(right)
        self.gallery = GalleryView(right)
        right.addTab(self.metrics_panel, "指标")
        right.addTab(self.gallery, "示例画廊")
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        root.addWidget(splitter, 1)

    # —— 通道元数据 / 预览 ——
    def update_from_discovery(self, ch: DiscoveredChannel) -> None:
        self.swatch.set_color(ch.color_hex)
        grid = (
            f"{ch.grid_rows}×{ch.grid_cols}"
            if ch.grid_rows and ch.grid_cols
            else "—"
        )
        self._meta_value_labels["荧光"].setText(ch.fluo_name or "—")
        self._meta_value_labels["曝光"].setText(_fmt_exposure(ch.exposure_us))
        self._meta_value_labels["增益"].setText(
            str(ch.gain) if ch.gain is not None else "—"
        )
        self._meta_value_labels["瓦片"].setText(str(ch.num_tiles))
        self._meta_value_labels["网格"].setText(grid)
        self._meta_value_labels["位深"].setText(
            f"{ch.pixel_bits}-bit" if ch.pixel_bits else "—"
        )

        if ch.preview_path is not None:
            caption = (
                f"扫描预览（{ch.preview_path.name}）— "
                f"运行后这里会替换为归一化平场热力图"
            )
            self.heatmap.show_preview(ch.preview_path, caption)
        else:
            self.heatmap.show_placeholder(
                "尚未运行（无预览图可显示）\n\n点击「开始」运行 BaSiC 平场拟合。"
            )

    # —— 状态切换 ——
    def reset(self, threshold: float) -> None:
        self.threshold_label.setText(f"阈值 (Min/Max) ≥ {threshold:.2f}%")
        self._active_stage = None
        self._stage_start = None
        self._loading_cur = 0
        self._loading_total = 0
        self.metrics_panel.table.setRowCount(0)
        self.metrics_panel.zone_table.clearContents()
        self.gallery.show_examples([])

    def set_queue_position(self, position: int, total: int) -> None:
        self._active_stage = None
        self._stage_start = None
        self.badge.set_queued(position, total)

    def on_stage(self, stage: str) -> None:
        self._active_stage = stage
        self._stage_start = time.monotonic()
        self._loading_cur = 0
        self._loading_total = 0
        self._refresh_running_badge()

    def on_progress(self, current: int, total: int) -> None:
        self._loading_cur = current
        self._loading_total = total
        self._refresh_running_badge()

    def tick(self) -> None:
        """由主窗口的 QTimer 每秒触发，更新运行中徽章的秒表。"""
        if self._active_stage is not None:
            self._refresh_running_badge()

    def _refresh_running_badge(self) -> None:
        if self._active_stage is None or self._stage_start is None:
            return
        elapsed = _fmt_elapsed(time.monotonic() - self._stage_start)
        if self._active_stage == "加载瓦片" and self._loading_total > 0:
            text = f"加载 {self._loading_cur}/{self._loading_total} ({elapsed})"
        else:
            text = f"{self._active_stage} ({elapsed})"
        self.badge.set_running(text)

    def on_result(self, result) -> None:
        self._active_stage = None
        self._stage_start = None
        self.heatmap.show_flatfield(
            result.flatfield_normalized,
            title=f"归一化平场 — {self.display_name} ({result.num_images} 张)",
        )
        self.metrics_panel.show_metrics(result.metrics)
        self.gallery.show_examples(result.examples)
        if result.passed:
            self.badge.set_ok()
        else:
            self.badge.set_ng()

    def on_error(self, msg: str) -> None:
        self._active_stage = None
        self._stage_start = None
        self.badge.set_error(msg)
