"""主窗口：目录选择 → 5 通道 Tab → 开始/停止 → 日志面板。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PyQt5.QtCore import Qt, QThread
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from heidstar_flat.config import (
    AppConfig,
    ChannelConfig,
    load_config,
    save_config,
)
from heidstar_flat.ui.channel_tab import ChannelTab
from heidstar_flat.ui.settings_dialog import SettingsDialog
from heidstar_flat.worker import (
    ChannelResult,
    FlatfieldWorker,
    make_worker_thread,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Heidstar 多通道平场性检测")
        self.resize(1280, 820)

        self.cfg: AppConfig = load_config()
        self._thread: QThread | None = None
        self._worker: FlatfieldWorker | None = None
        self._tabs_by_wl: Dict[str, ChannelTab] = {}
        self._channel_checks: Dict[str, QCheckBox] = {}

        self._build_ui()
        self._refresh_channel_widgets()

    # ---------- UI 构建 ----------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # 顶部：输入/输出目录
        io_box = QGroupBox("输入 / 输出")
        io_layout = QVBoxLayout(io_box)

        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("输入目录"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("选择包含 *Fluorescence_<波长>_nm_Ex.tiff 的目录")
        in_row.addWidget(self.input_edit, 1)
        in_btn = QPushButton("浏览…")
        in_btn.clicked.connect(self._choose_input_dir)
        in_row.addWidget(in_btn)
        io_layout.addLayout(in_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认: <输入目录>/flatfield_results")
        out_row.addWidget(self.output_edit, 1)
        out_btn = QPushButton("浏览…")
        out_btn.clicked.connect(self._choose_output_dir)
        out_row.addWidget(out_btn)
        io_layout.addLayout(out_row)
        root_layout.addWidget(io_box)

        # 中部：通道勾选 + 控制按钮 + 结果 Tab + 日志
        mid_splitter = QSplitter(Qt.Horizontal)

        # 左侧通道列表 + 控制
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        ch_box = QGroupBox("通道")
        ch_layout = QVBoxLayout(ch_box)
        self.channel_list = QListWidget()
        ch_layout.addWidget(self.channel_list)
        left_layout.addWidget(ch_box, 1)

        ctrl_box = QGroupBox("控制")
        ctrl_layout = QVBoxLayout(ctrl_box)
        self.start_btn = QPushButton("开始")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.stop_btn)
        left_layout.addWidget(ctrl_box)

        mid_splitter.addWidget(left)

        # 右侧：上半结果 Tab，下半日志
        right_split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        right_split.addWidget(self.tabs)

        log_box = QGroupBox("日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        self.log_view.setFont(font)
        log_layout.addWidget(self.log_view)
        right_split.addWidget(log_box)
        right_split.setStretchFactor(0, 4)
        right_split.setStretchFactor(1, 1)

        mid_splitter.addWidget(right_split)
        mid_splitter.setStretchFactor(0, 1)
        mid_splitter.setStretchFactor(1, 5)
        root_layout.addWidget(mid_splitter, 1)

        # 底部：进度条 + 状态栏
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root_layout.addWidget(self.progress)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        # 顶部工具栏
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        act_settings = QAction("通道与阈值设置", self)
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        tb.addAction(act_about)

    def _refresh_channel_widgets(self) -> None:
        # 重置 Tab
        self.tabs.clear()
        self._tabs_by_wl.clear()
        # 重置勾选列表
        self.channel_list.clear()
        self._channel_checks.clear()

        for ch in self.cfg.channels:
            tab = ChannelTab(ch.wavelength, ch.uniformity_threshold)
            self.tabs.addTab(tab, f"{ch.wavelength} nm")
            self._tabs_by_wl[ch.wavelength] = tab

            item = QListWidgetItem(self.channel_list)
            cb = QCheckBox(f"{ch.wavelength} nm")
            cb.setChecked(True)
            self.channel_list.addItem(item)
            self.channel_list.setItemWidget(item, cb)
            item.setSizeHint(cb.sizeHint())
            self._channel_checks[ch.wavelength] = cb

    # ---------- 槽 ----------
    def _choose_input_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输入目录", self.input_edit.text())
        if d:
            self.input_edit.setText(d)

    def _choose_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_edit.text())
        if d:
            self.output_edit.setText(d)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec_() == dlg.Accepted:
            self.cfg = dlg.gather()
            try:
                save_config(self.cfg)
            except Exception as e:
                self._append_log(f"保存配置失败: {e}")
            self._refresh_channel_widgets()

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于",
            "Heidstar 多通道图像平场性检测\n\n"
            "基于 BaSiCPy + PyQt5，"
            "支持 Ubuntu 22.04 / Windows。\n\n"
            "源代码运行: python run.py",
        )

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _selected_channels(self) -> List[ChannelConfig]:
        return [
            ch for ch in self.cfg.channels
            if ch.wavelength in self._channel_checks
            and self._channel_checks[ch.wavelength].isChecked()
        ]

    def _on_start(self) -> None:
        input_dir = self.input_edit.text().strip()
        if not input_dir:
            QMessageBox.warning(self, "提示", "请先选择输入目录")
            return
        in_path = Path(input_dir)
        if not in_path.is_dir():
            QMessageBox.warning(self, "提示", f"输入目录不存在: {input_dir}")
            return

        output_dir = self.output_edit.text().strip()
        if not output_dir:
            output_dir = str(in_path / self.cfg.output_subdir)
            self.output_edit.setText(output_dir)

        channels = self._selected_channels()
        if not channels:
            QMessageBox.warning(self, "提示", "至少勾选一个通道")
            return

        # 重置 Tab 状态
        for ch in channels:
            if ch.wavelength in self._tabs_by_wl:
                self._tabs_by_wl[ch.wavelength].reset(ch.uniformity_threshold)

        self.log_view.clear()
        self._append_log(f"输入: {input_dir}")
        self._append_log(f"输出: {output_dir}")
        self._append_log(f"通道: {', '.join(c.wavelength for c in channels)}")

        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("运行中…")

        self._worker = FlatfieldWorker(
            input_dir=input_dir,
            output_root=output_dir,
            channels=channels,
            examples_per_channel=self.cfg.examples_per_channel,
        )
        self._thread = make_worker_thread(self._worker)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.log.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.channel_done.connect(self._on_channel_done)
        self._worker.channel_failed.connect(self._on_channel_failed)
        self._worker.finished.connect(self._on_all_finished)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self.statusBar().showMessage("已请求停止，等待当前通道结束…")
            self.stop_btn.setEnabled(False)

    def _on_stage(self, wavelength: str, stage: str) -> None:
        if wavelength in self._tabs_by_wl:
            self._tabs_by_wl[wavelength].on_stage(stage)
            idx = self.tabs.indexOf(self._tabs_by_wl[wavelength])
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        self.statusBar().showMessage(f"{wavelength} nm — {stage}")

    def _on_progress(self, wavelength: str, current: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        self.statusBar().showMessage(f"{wavelength} nm — 加载 {current}/{total}")

    def _on_channel_done(self, result: ChannelResult) -> None:
        if result.wavelength in self._tabs_by_wl:
            self._tabs_by_wl[result.wavelength].on_result(result)
        self.progress.setRange(0, 0)

    def _on_channel_failed(self, wavelength: str, msg: str) -> None:
        if wavelength in self._tabs_by_wl:
            self._tabs_by_wl[wavelength].on_error(msg)

    def _on_all_finished(self) -> None:
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("全部完成")
        self._append_log("====== 全部通道处理结束 ======")

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._on_stop()
            self._thread.wait(5000)
        event.accept()
