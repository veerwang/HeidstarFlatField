"""单个波段通道的结果页。包含状态徽章、热力图、指标表、示例画廊。"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.ui.gallery import GalleryView
from heidstar_flat.ui.metrics_table import MetricsPanel
from heidstar_flat.ui.mpl_canvas import HeatmapCanvas


class VerdictBadge(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__("等待中", parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(36)
        self.setMinimumWidth(120)
        self._apply_style("#888888", "#ffffff")

    def _apply_style(self, bg: str, fg: str) -> None:
        self.setStyleSheet(
            f"QLabel {{ background-color: {bg}; color: {fg}; "
            f"font-weight: bold; font-size: 14px; border-radius: 4px; "
            f"padding: 4px 12px; }}"
        )

    def set_pending(self) -> None:
        self.setText("等待中")
        self._apply_style("#888888", "#ffffff")

    def set_running(self, stage: str) -> None:
        self.setText(f"运行中 · {stage}")
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


class ChannelTab(QWidget):
    def __init__(self, wavelength: str, threshold: float, parent=None) -> None:
        super().__init__(parent)
        self.wavelength = wavelength

        root = QVBoxLayout(self)

        # 顶部头部信息
        header = QHBoxLayout()
        header.addWidget(QLabel(f"<b>{wavelength} nm</b>"))
        self.badge = VerdictBadge()
        header.addWidget(self.badge)
        header.addStretch(1)
        self.info_label = QLabel(f"阈值 (Michelson) ≥ {threshold:.2f}%")
        self.info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.info_label)
        root.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # 主体：左侧热力图，右侧指标 + 画廊
        splitter = QSplitter(Qt.Horizontal, self)
        self.heatmap = HeatmapCanvas(splitter)
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

    # —— 状态切换 ——
    def reset(self, threshold: float) -> None:
        self.info_label.setText(f"阈值 (Michelson) ≥ {threshold:.2f}%")
        self.badge.set_pending()
        self.heatmap.clear()
        self.metrics_panel.table.setRowCount(0)
        self.metrics_panel.zone_table.clearContents()
        self.gallery.show_examples([])

    def on_stage(self, stage: str) -> None:
        self.badge.set_running(stage)

    def on_result(self, result) -> None:
        self.heatmap.show_flatfield(
            result.flatfield_normalized,
            title=f"归一化平场 — {self.wavelength} nm ({result.num_images} 张)",
        )
        self.metrics_panel.show_metrics(result.metrics)
        self.gallery.show_examples(result.examples)
        if result.passed:
            self.badge.set_ok()
        else:
            self.badge.set_ng()

    def on_error(self, msg: str) -> None:
        self.badge.set_error(msg)
