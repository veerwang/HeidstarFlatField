"""单个杂散光通道结果页。

与 ChannelTab 结构相似但更小：只有 2 项判定（DC1 + DC2），无示例三联画。
状态机：idle / queued / running / pass/fail / error / cancelled（沿用
ChannelTab 的 VerdictBadge）。
"""

from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.core.loader import DiscoveredChannel
from heidstar_flat.core.stray_light import StrayLightThresholds
from heidstar_flat.ui.channel_tab import ColorSwatch, VerdictBadge
from heidstar_flat.ui.mpl_canvas import HeatmapCanvas


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


def _fmt_threshold_label(_thr: StrayLightThresholds) -> str:
    return (
        "<span style='font-size:13pt'>"
        "判定: 5 项 AND  "
        "<span style='color:#666'>(详见下方)</span>"
        "</span>"
    )


def _threshold_tooltip(thr: StrayLightThresholds) -> str:
    return (
        "杂散光 5 项 AND 判定阈值：\n"
        f"① DC1 本底强度        ≤ {thr.dc_pct_of_max:.4f}%\n"
        f"② DC2 本底均匀性       ≥ {thr.zone_dc_uniformity_pct:.2f}%\n"
        f"③ DC3 DSNU 像素级     ≤ {thr.dsnu_pct_of_max:.4f}%\n"
        f"④ DC4 时间噪声底      ≤ {thr.temporal_noise_pct:.4f}%\n"
        f"⑤ DC5 热像素密度      ≤ {thr.hot_pixel_pct:.4f}%"
    )


class StrayChannelTab(QWidget):
    def __init__(
        self,
        suffix: str,
        display_name: str,
        thresholds: StrayLightThresholds,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.suffix = suffix
        self.display_name = display_name
        self._thresholds = thresholds

        self._active_stage: Optional[str] = None
        self._stage_start: Optional[float] = None
        self._loading_cur: int = 0
        self._loading_total: int = 0

        root = QVBoxLayout(self)

        # —— 头部 ——
        header = QHBoxLayout()
        self.swatch = ColorSwatch(None)
        header.addWidget(self.swatch)
        self.name_label = QLabel(
            f"<span style='font-size:18pt; font-weight:bold'>{display_name}</span>"
        )
        header.addWidget(self.name_label)
        header.addSpacing(12)
        self.badge = VerdictBadge()
        header.addWidget(self.badge)
        header.addStretch(1)
        self.threshold_label = QLabel(_fmt_threshold_label(thresholds))
        self.threshold_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.threshold_label.setToolTip(_threshold_tooltip(thresholds))
        header.addWidget(self.threshold_label)
        root.addLayout(header)

        # —— 判定原因（2 项 check） ——
        self.reason_label = QLabel("")
        self.reason_label.setTextFormat(Qt.RichText)
        self.reason_label.setWordWrap(True)
        self.reason_label.setStyleSheet("QLabel { padding: 4px 6px; }")
        self.reason_label.setVisible(False)
        root.addWidget(self.reason_label)

        # —— 元数据栏 ——
        meta = QFrame()
        meta.setFrameShape(QFrame.StyledPanel)
        meta_grid = QGridLayout(meta)
        meta_grid.setContentsMargins(8, 6, 8, 6)
        meta_grid.setHorizontalSpacing(18)
        self._meta_value_labels: dict[str, QLabel] = {}
        for col, key in enumerate(["荧光", "曝光", "增益", "瓦片", "网格", "位深"]):
            k = QLabel(f"<span style='color:#666; font-size:12pt'>{key}</span>")
            v = QLabel("<span style='font-size:12pt'>—</span>")
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

        # —— 主体：左侧暗场热力图 + 右侧指标表 ——
        splitter = QSplitter(Qt.Horizontal, self)
        self.heatmap = HeatmapCanvas(splitter)
        self.heatmap.show_placeholder(
            "尚未运行\n\n点击「开始」后，这里会显示暗场均值热力图、灰度分布、\n"
            "9 区均值与最亮像素位置标注。"
        )
        splitter.addWidget(self.heatmap)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        right_layout.addWidget(QLabel("<b>杂散光指标</b>"))
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["指标", "数值"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.metrics_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setEditTriggers(QTableWidget.NoEditTriggers)
        right_layout.addWidget(self.metrics_table, 1)

        right_layout.addWidget(QLabel("<b>9 区暗本底均值</b>"))
        self.zone_table = QTableWidget(3, 3)
        self.zone_table.horizontalHeader().setVisible(False)
        self.zone_table.verticalHeader().setVisible(False)
        self.zone_table.setEditTriggers(QTableWidget.NoEditTriggers)
        for i in range(3):
            self.zone_table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.Stretch
            )
        right_layout.addWidget(self.zone_table)

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

        def _v(text: str) -> str:
            return f"<span style='font-size:12pt'>{text}</span>"

        self._meta_value_labels["荧光"].setText(_v(ch.fluo_name or "—"))
        self._meta_value_labels["曝光"].setText(_v(_fmt_exposure(ch.exposure_us)))
        self._meta_value_labels["增益"].setText(
            _v(str(ch.gain) if ch.gain is not None else "—")
        )
        self._meta_value_labels["瓦片"].setText(_v(str(ch.num_tiles)))
        self._meta_value_labels["网格"].setText(_v(grid))
        self._meta_value_labels["位深"].setText(
            _v(f"{ch.pixel_bits}-bit" if ch.pixel_bits else "—")
        )

        if ch.preview_path is not None:
            caption = (
                f"暗场扫描预览（{ch.preview_path.name}）— "
                f"运行后此处替换为暗场均值热力图"
            )
            self.heatmap.show_preview(ch.preview_path, caption)
        else:
            self.heatmap.show_placeholder(
                "尚未运行（无预览图可显示）\n\n点击「开始」运行杂散光评估。"
            )

    # —— 状态切换 ——
    def reset(self, thresholds: StrayLightThresholds) -> None:
        self._thresholds = thresholds
        self.threshold_label.setText(_fmt_threshold_label(thresholds))
        self.threshold_label.setToolTip(_threshold_tooltip(thresholds))
        self.reason_label.setVisible(False)
        self.reason_label.setText("")
        self._active_stage = None
        self._stage_start = None
        self._loading_cur = 0
        self._loading_total = 0
        self.metrics_table.setRowCount(0)
        self.zone_table.clearContents()

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
        if self._active_stage is not None:
            self._refresh_running_badge()

    def _refresh_running_badge(self) -> None:
        if self._active_stage is None or self._stage_start is None:
            return
        elapsed = _fmt_elapsed(time.monotonic() - self._stage_start)
        if self._active_stage == "加载暗场瓦片" and self._loading_total > 0:
            text = f"加载 {self._loading_cur}/{self._loading_total} ({elapsed})"
        else:
            text = f"{self._active_stage} ({elapsed})"
        self.badge.set_running(text)

    def on_result(self, result) -> None:
        self._active_stage = None
        self._stage_start = None

        # 暗场热力图
        self.heatmap.show_dark_mean(
            result.dark_mean_image,
            sensor_max=result.metrics.sensor_max,
            title=f"暗场均值 — {self.display_name} ({result.num_images} 张)",
            max_pos=result.metrics.max_pixel_position,
        )

        # 指标表
        rows = result.metrics.as_table_rows()
        self.metrics_table.setRowCount(len(rows))
        for r, (name, value) in enumerate(rows):
            item_n = QTableWidgetItem(name)
            item_v = QTableWidgetItem(value)
            # 判定相关行加粗
            if name.startswith("★"):
                f = item_n.font()
                f.setBold(True)
                item_n.setFont(f)
                f2 = item_v.font()
                f2.setBold(True)
                item_v.setFont(f2)
            self.metrics_table.setItem(r, 0, item_n)
            self.metrics_table.setItem(r, 1, item_v)

        # 9 区 mini 表
        zones = result.metrics.zone_dc
        for i in range(3):
            for j in range(3):
                idx = i * 3 + j
                v = zones[idx] if idx < len(zones) else 0.0
                item = QTableWidgetItem(f"{v:.2f}")
                item.setTextAlignment(Qt.AlignCenter)
                # 中心格加粗
                if i == 1 and j == 1:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.zone_table.setItem(i, j, item)

        # 渲染 verdict 原因（绿 ✓ / 红 ✗）
        checks = getattr(result.verdict, "checks", None)
        if checks:
            parts = []
            for c in checks:
                color = "#2ea043" if c.passed else "#cf222e"
                glyph = "✓" if c.passed else "✗"
                direction = getattr(c, "direction", "<=")
                if direction == ">=":
                    op = "≥" if c.passed else "&lt;"
                else:
                    op = "≤" if c.passed else "&gt;"
                parts.append(
                    f"<span style='color:{color}; font-weight:bold'>{glyph} {c.name}</span> "
                    f"<span style='color:#333'>{c.value_pct:.4f}% {op} {c.threshold_pct:.4f}%</span>"
                )
            verdict_color = "#2ea043" if result.passed else "#cf222e"
            head = (
                f"<span style='color:{verdict_color}; font-size:12pt; font-weight:bold'>"
                f"{'PASS' if result.passed else 'FAIL'}</span> &nbsp; "
            )
            self.reason_label.setText(head + " &nbsp;·&nbsp; ".join(parts))
            self.reason_label.setVisible(True)

        if result.passed:
            self.badge.set_ok()
        else:
            self.badge.set_ng()

    def on_error(self, msg: str) -> None:
        self._active_stage = None
        self._stage_start = None
        self.badge.set_error(msg)

    def mark_cancelled_if_pending(self) -> None:
        """与 ChannelTab.mark_cancelled_if_pending 同语义。"""
        if self._active_stage is not None or self.badge.text().startswith("排队"):
            self._active_stage = None
            self._stage_start = None
            self.badge.set_cancelled()
