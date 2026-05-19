"""均匀性指标表格 + 九区数值表。"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.core.metrics import UniformityMetrics


_SECTION_STYLE = "QLabel { font-size: 13pt; font-weight: bold; padding-top: 4px; }"
_TABLE_STYLE = "QTableWidget { font-size: 12pt; }"


class MetricsPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        lbl1 = QLabel("均匀性指标")
        lbl1.setStyleSheet(_SECTION_STYLE)
        layout.addWidget(lbl1)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["指标", "数值"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.table)

        lbl2 = QLabel("九区 ROI 均值 (归一化平场)")
        lbl2.setStyleSheet(_SECTION_STYLE)
        layout.addWidget(lbl2)
        self.zone_table = QTableWidget(3, 3, self)
        self.zone_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.zone_table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.zone_table.horizontalHeader().setVisible(False)
        self.zone_table.verticalHeader().setVisible(False)
        self.zone_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.zone_table.setSelectionMode(QTableWidget.NoSelection)
        self.zone_table.setStyleSheet(_TABLE_STYLE)
        layout.addWidget(self.zone_table)

    def show_metrics(self, metrics: UniformityMetrics) -> None:
        rows: List[tuple] = metrics.as_table_rows()
        self.table.setRowCount(len(rows))
        for r, (name, value) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, item)

        zones = metrics.nine_zone_means
        for i in range(3):
            for j in range(3):
                val = zones[i * 3 + j] if i * 3 + j < len(zones) else float("nan")
                item = QTableWidgetItem(f"{val:.4f}")
                item.setTextAlignment(Qt.AlignCenter)
                self.zone_table.setItem(i, j, item)
