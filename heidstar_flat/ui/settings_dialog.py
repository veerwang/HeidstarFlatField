"""通道偏好（suffix / 显示名 / 阈值）和全局选项设置。"""

from __future__ import annotations

from typing import List

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

from heidstar_flat.config import AppConfig, ChannelPref, default_channel_prefs


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("通道偏好与全局设置")
        self.resize(680, 460)

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.examples_spin = QSpinBox()
        self.examples_spin.setRange(0, 20)
        self.examples_spin.setValue(cfg.examples_per_channel)
        form.addRow("每通道示例数", self.examples_spin)

        self.default_thr_spin = QDoubleSpinBox()
        self.default_thr_spin.setRange(0.0, 100.0)
        self.default_thr_spin.setDecimals(2)
        self.default_thr_spin.setValue(cfg.default_threshold)
        form.addRow("默认 Min/Max 阈值 (%)", self.default_thr_spin)

        self.output_subdir_edit = QLineEdit(cfg.output_subdir)
        form.addRow("输出子目录名", self.output_subdir_edit)

        self.image_subdir_edit = QLineEdit(cfg.image_subdir)
        form.addRow("通道下瓦片目录", self.image_subdir_edit)

        self.image_glob_edit = QLineEdit(cfg.image_glob)
        form.addRow("瓦片 glob 模式", self.image_glob_edit)

        root.addLayout(form)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            ["目录后缀 (suffix)", "显示名 (可空)", "Min/Max 阈值 (%)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)
        self._load_prefs(cfg.channel_prefs)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("新增")
        add_btn.clicked.connect(self._add_row)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._del_selected)
        reset_btn = QPushButton("恢复默认")
        reset_btn.clicked.connect(lambda: self._load_prefs(default_channel_prefs()))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_prefs(self, prefs: List[ChannelPref]) -> None:
        self.table.setRowCount(0)
        for p in prefs:
            self._append_pref(p)

    def _append_pref(self, p: ChannelPref) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(p.suffix))
        self.table.setItem(r, 1, QTableWidgetItem(p.display_name or ""))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setDecimals(2)
        spin.setValue(p.uniformity_threshold)
        self.table.setCellWidget(r, 2, spin)

    def _add_row(self) -> None:
        self._append_pref(ChannelPref("", None, 85.0))

    def _del_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def gather(self) -> AppConfig:
        prefs: List[ChannelPref] = []
        for r in range(self.table.rowCount()):
            suf_item = self.table.item(r, 0)
            name_item = self.table.item(r, 1)
            spin = self.table.cellWidget(r, 2)
            suffix = (suf_item.text() if suf_item else "").strip()
            display = (name_item.text() if name_item else "").strip() or None
            if not suffix:
                continue
            thr = float(spin.value()) if spin else 85.0
            prefs.append(ChannelPref(suffix, display, thr))
        return AppConfig(
            channel_prefs=prefs,
            examples_per_channel=int(self.examples_spin.value()),
            output_subdir=self.output_subdir_edit.text().strip() or "flatfield_results",
            default_threshold=float(self.default_thr_spin.value()),
            image_subdir=self.image_subdir_edit.text().strip() or "Images",
            image_glob=self.image_glob_edit.text().strip() or "IMG*.tif",
        )
