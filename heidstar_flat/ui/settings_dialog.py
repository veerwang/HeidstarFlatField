"""通道/阈值/示例数设置对话框。"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from heidstar_flat.config import AppConfig, ChannelConfig, default_channels


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("通道与阈值设置")
        self.resize(640, 420)

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.examples_spin = QSpinBox()
        self.examples_spin.setRange(0, 20)
        self.examples_spin.setValue(cfg.examples_per_channel)
        form.addRow("每通道示例数", self.examples_spin)

        self.output_subdir_edit = QLineEdit(cfg.output_subdir)
        form.addRow("输出子目录名", self.output_subdir_edit)
        root.addLayout(form)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["波长 (nm)", "文件 glob", "阈值 (%)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)
        self._load_channels(cfg.channels)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增")
        add_btn.clicked.connect(self._add_row)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._del_selected)
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(lambda: self._load_channels(default_channels()))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_channels(self, channels: List[ChannelConfig]) -> None:
        self.table.setRowCount(0)
        for c in channels:
            self._append_channel(c)

    def _append_channel(self, c: ChannelConfig) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(c.wavelength))
        self.table.setItem(r, 1, QTableWidgetItem(c.pattern))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setDecimals(2)
        spin.setValue(c.uniformity_threshold)
        self.table.setCellWidget(r, 2, spin)

    def _add_row(self) -> None:
        self._append_channel(ChannelConfig("", "*.tiff", 85.0))

    def _del_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def gather(self) -> AppConfig:
        channels: List[ChannelConfig] = []
        for r in range(self.table.rowCount()):
            wl_item = self.table.item(r, 0)
            pat_item = self.table.item(r, 1)
            spin = self.table.cellWidget(r, 2)
            wl = (wl_item.text() if wl_item else "").strip()
            pat = (pat_item.text() if pat_item else "").strip()
            if not wl or not pat:
                continue
            thr = float(spin.value()) if spin else 85.0
            channels.append(ChannelConfig(wl, pat, thr))
        return AppConfig(
            channels=channels,
            examples_per_channel=int(self.examples_spin.value()),
            output_subdir=self.output_subdir_edit.text().strip() or "flatfield_results",
        )
