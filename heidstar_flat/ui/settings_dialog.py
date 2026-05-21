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
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.config import AppConfig, ChannelPref, default_channel_prefs


def _section_label(text: str) -> QLabel:
    """分节标题（在 QFormLayout 中 addRow 单参时跨整行显示）。"""
    lbl = QLabel(f"<b style='color:#1a4d8f; font-size:11pt'>{text}</b>")
    lbl.setContentsMargins(0, 6, 0, 2)
    return lbl


def _make_spin(value: float, decimals: int = 2, vmax: float = 100.0,
               tooltip: str | None = None) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(0.0, vmax)
    s.setDecimals(decimals)
    s.setValue(value)
    if tooltip:
        s.setToolTip(tooltip)
    return s


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("通道偏好与全局设置")
        self.resize(720, 720)

        root = QVBoxLayout(self)

        # ---- 表单内容包在 QScrollArea 里，避免高分屏过满或低分屏被裁 ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        form = QFormLayout(inner)

        # ===== 全局参数 =====
        form.addRow(_section_label("全局参数"))
        self.examples_spin = QSpinBox()
        self.examples_spin.setRange(0, 20)
        self.examples_spin.setValue(cfg.examples_per_channel)
        form.addRow("每通道示例数", self.examples_spin)

        self.output_subdir_edit = QLineEdit(cfg.output_subdir)
        form.addRow("输出子目录名", self.output_subdir_edit)

        self.image_subdir_edit = QLineEdit(cfg.image_subdir)
        form.addRow("通道下瓦片目录", self.image_subdir_edit)

        self.image_glob_edit = QLineEdit(cfg.image_glob)
        form.addRow("瓦片 glob 模式", self.image_glob_edit)

        # ===== 平场判据阈值（7 项 AND）=====
        form.addRow(_section_label("平场判据阈值（7 项 AND）"))

        self.default_thr_spin = _make_spin(cfg.default_threshold)
        form.addRow("默认 robust Min/Max 阈值 (%, ≥)", self.default_thr_spin)

        self.cv_thr_spin = _make_spin(cfg.cv_threshold)
        form.addRow("CV 均匀性阈值 (%, ≥)", self.cv_thr_spin)

        self.corner_sym_spin = _make_spin(cfg.corner_symmetry_threshold)
        form.addRow("九区 四角对称阈值 (%, ≥)", self.corner_sym_spin)

        self.center_max_spin = _make_spin(cfg.center_to_max_threshold)
        form.addRow("九区 中心最亮阈值 (%, ≥)", self.center_max_spin)

        self.min_zone_spin = _make_spin(cfg.min_zone_to_max_threshold)
        form.addRow("九区 最暗格阈值 (%, ≥)", self.min_zone_spin)

        self.nz_unif_spin = _make_spin(cfg.nine_zone_uniformity_threshold)
        form.addRow("九区 粗糙度阈值 (%, ≥)", self.nz_unif_spin)

        self.top_sat_spin = _make_spin(
            cfg.top_saturation_threshold,
            tooltip="顶端饱和率上限 (% pixels ≥ 0.99)：超过则判 FAIL，提示 BaSiC 过拟合或中心平台",
        )
        form.addRow("顶端饱和率上限 (%, ≤)", self.top_sat_spin)

        # ===== 杂散光判据阈值（5 项 AND）=====
        form.addRow(_section_label("杂散光判据阈值（5 项 AND）"))

        self.stray_dc_spin = _make_spin(
            cfg.stray_dc_threshold, decimals=4,
            tooltip="DC1: dark_mean / sensor_max ≤ 阈值；典型 sCMOS << 1%",
        )
        form.addRow("DC1 本底强度 (%, ≤)", self.stray_dc_spin)

        self.stray_zone_spin = _make_spin(
            cfg.stray_zone_dc_uniformity_threshold,
            tooltip="DC2: 9 区暗本底均匀性 (1−σ/μ) ≥ 阈值；局部杂光斑会拉低",
        )
        form.addRow("DC2 本底均匀性 (%, ≥)", self.stray_zone_spin)

        self.stray_dsnu_spin = _make_spin(
            cfg.stray_dsnu_threshold, decimals=4,
            tooltip="DC3: DSNU 像素级 std(mean_image)/sensor_max ≤ 阈值；EMVA 1288 DSNU 粗版",
        )
        form.addRow("DC3 DSNU 像素级 (%, ≤)", self.stray_dsnu_spin)

        self.stray_temporal_spin = _make_spin(
            cfg.stray_temporal_noise_threshold, decimals=4,
            tooltip="DC4: median(per-pixel std over frames)/sensor_max ≤ 阈值；σ_temporal",
        )
        form.addRow("DC4 时间噪声底 (%, ≤)", self.stray_temporal_spin)

        self.stray_hot_spin = _make_spin(
            cfg.stray_hot_pixel_threshold, decimals=4,
            tooltip="DC5: 热像素 (mean_pixel > μ+10σ_DSNU) 占总像素的比例上限；0.01% ≈ 100 ppm",
        )
        form.addRow("DC5 热像素密度 (%, ≤)", self.stray_hot_spin)

        # ===== 通道偏好（per-channel 显示名 / robust Min/Max 阈值）=====
        form.addRow(_section_label("通道偏好（per-channel 显示名与 Min/Max 阈值）"))

        root.addWidget(scroll, 1)

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
            cv_threshold=float(self.cv_thr_spin.value()),
            corner_symmetry_threshold=float(self.corner_sym_spin.value()),
            center_to_max_threshold=float(self.center_max_spin.value()),
            min_zone_to_max_threshold=float(self.min_zone_spin.value()),
            nine_zone_uniformity_threshold=float(self.nz_unif_spin.value()),
            top_saturation_threshold=float(self.top_sat_spin.value()),
            stray_dc_threshold=float(self.stray_dc_spin.value()),
            stray_zone_dc_uniformity_threshold=float(self.stray_zone_spin.value()),
            stray_dsnu_threshold=float(self.stray_dsnu_spin.value()),
            stray_temporal_noise_threshold=float(self.stray_temporal_spin.value()),
            stray_hot_pixel_threshold=float(self.stray_hot_spin.value()),
            image_subdir=self.image_subdir_edit.text().strip() or "Images",
            image_glob=self.image_glob_edit.text().strip() or "IMG*.tif",
        )
