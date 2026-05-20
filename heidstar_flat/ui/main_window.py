"""主窗口：扫描根目录 → 自动发现通道 → 启动 Worker。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from PyQt5.QtCore import Qt, QThread, QTimer
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
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from datetime import datetime

from heidstar_flat import __version__
from heidstar_flat.config import AppConfig, load_config, save_config
from heidstar_flat.core.loader import DiscoveredChannel, discover_channels
from heidstar_flat.core.metrics import VerdictThresholds
from heidstar_flat.core.report import generate_pdf_report
from heidstar_flat.ui.channel_tab import ChannelTab
from heidstar_flat.ui.log_dialog import LogDialog
from heidstar_flat.ui.settings_dialog import SettingsDialog
from heidstar_flat.worker import (
    ChannelJob,
    ChannelResult,
    FlatfieldWorker,
    make_worker_thread,
)


def _build_thresholds(cfg: AppConfig, per_channel_threshold: float) -> VerdictThresholds:
    return VerdictThresholds(
        robust_min_max_pct=per_channel_threshold,
        cv_pct=cfg.cv_threshold,
        corner_symmetry_pct=cfg.corner_symmetry_threshold,
        center_to_max_pct=cfg.center_to_max_threshold,
        min_zone_to_max_pct=cfg.min_zone_to_max_threshold,
        nine_zone_uniformity_pct=cfg.nine_zone_uniformity_threshold,
        top_saturation_pct=cfg.top_saturation_threshold,
    )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Heidstar 多通道平场性检测  v{__version__}")
        self.resize(1280, 860)

        self.cfg: AppConfig = load_config()
        self._thread: QThread | None = None
        self._worker: FlatfieldWorker | None = None

        self._discovered: List[DiscoveredChannel] = []
        self._tabs_by_suffix: Dict[str, ChannelTab] = {}
        self._channel_checks: Dict[str, QCheckBox] = {}
        # 已完成通道的结果，按通道发现顺序累积；用于 PDF 导出
        self._results: List[ChannelResult] = []
        self._last_output_dir: str = ""

        # 日志：缓存全部历史，按需在 LogDialog 中显示
        self._log_buffer: List[str] = []
        self._log_dialog: LogDialog | None = None

        # 秒表：运行中每秒刷新一次 badge 的 elapsed
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._build_ui()

    # ---------- UI 构建 ----------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)

        io_box = QGroupBox("输入 / 输出")
        io_layout = QVBoxLayout(io_box)

        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("扫描根目录"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "选择含 *_<Color>/Images/IMG*.tif 的目录，例如 data/0519"
        )
        self.input_edit.editingFinished.connect(self._maybe_rescan)
        in_row.addWidget(self.input_edit, 1)
        in_btn = QPushButton("浏览…")
        in_btn.clicked.connect(self._choose_input_dir)
        in_row.addWidget(in_btn)
        scan_btn = QPushButton("扫描")
        scan_btn.clicked.connect(self._rescan)
        in_row.addWidget(scan_btn)
        io_layout.addLayout(in_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认: <扫描根目录>/flatfield_results")
        out_row.addWidget(self.output_edit, 1)
        out_btn = QPushButton("浏览…")
        out_btn.clicked.connect(self._choose_output_dir)
        out_row.addWidget(out_btn)
        io_layout.addLayout(out_row)
        root_layout.addWidget(io_box)

        mid_splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        ch_box = QGroupBox("发现的通道")
        ch_layout = QVBoxLayout(ch_box)
        select_row = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self._set_all_channels_checked(True))
        select_none_btn = QPushButton("全不选")
        select_none_btn.clicked.connect(lambda: self._set_all_channels_checked(False))
        select_row.addWidget(select_all_btn)
        select_row.addWidget(select_none_btn)
        select_row.addStretch(1)
        ch_layout.addLayout(select_row)
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
        self.export_btn = QPushButton("导出 PDF 报告")
        self.export_btn.clicked.connect(self._on_export_pdf)
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("至少需要完成一个通道才能导出。")
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addWidget(self.export_btn)
        left_layout.addWidget(ctrl_box)

        mid_splitter.addWidget(left)

        self.tabs = QTabWidget()
        self._empty_hint = QLabel(
            "尚未扫描到通道。请先在上方选择扫描根目录并点击「扫描」。"
        )
        self._empty_hint.setAlignment(Qt.AlignCenter)
        self.tabs.addTab(self._empty_hint, "提示")

        mid_splitter.addWidget(self.tabs)
        mid_splitter.setStretchFactor(0, 1)
        mid_splitter.setStretchFactor(1, 5)
        root_layout.addWidget(mid_splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root_layout.addWidget(self.progress)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪。请选择扫描根目录。")

        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        act_settings = QAction("通道偏好与设置", self)
        act_settings.triggered.connect(self._open_settings)
        tb.addAction(act_settings)
        act_log = QAction("查看日志", self)
        act_log.setShortcut("Ctrl+L")
        act_log.triggered.connect(self._show_log_dialog)
        tb.addAction(act_log)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        tb.addAction(act_about)

    # ---------- 扫描 / 通道发现 ----------
    def _choose_input_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择扫描根目录", self.input_edit.text())
        if d:
            self.input_edit.setText(d)
            self._rescan()

    def _maybe_rescan(self) -> None:
        text = self.input_edit.text().strip()
        if text and Path(text).is_dir():
            self._rescan()

    def _rescan(self) -> None:
        root = self.input_edit.text().strip()
        if not root:
            return
        try:
            channels = discover_channels(
                root,
                image_subdir=self.cfg.image_subdir,
                image_glob=self.cfg.image_glob,
            )
        except Exception as e:
            QMessageBox.warning(self, "扫描失败", f"{e}")
            return

        self._discovered = channels
        self._rebuild_channel_widgets()

        if not channels:
            self.statusBar().showMessage(
                "未在该目录发现通道：需要形如 *_<Color>/Images/IMG*.tif 的结构"
            )
            self._append_log(f"扫描 {root}：未发现通道")
        else:
            self.statusBar().showMessage(f"发现 {len(channels)} 个通道")
            self._append_log(
                f"扫描 {root}：发现 {len(channels)} 个通道 — "
                + ", ".join(c.suffix for c in channels)
            )

    def _rebuild_channel_widgets(self) -> None:
        # 清空 Tabs（包括 hint）
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if w is not self._empty_hint:
                w.deleteLater()
        self._tabs_by_suffix.clear()

        self.channel_list.clear()
        self._channel_checks.clear()

        if not self._discovered:
            self.tabs.addTab(self._empty_hint, "提示")
            return

        for ch in self._discovered:
            pref = self.cfg.pref_for(ch.suffix)
            display = pref.display_name or ch.display_name
            thresholds = _build_thresholds(self.cfg, pref.uniformity_threshold)
            tab = ChannelTab(ch.suffix, display, thresholds)
            tab.update_from_discovery(ch)
            self.tabs.addTab(tab, display)
            self._tabs_by_suffix[ch.suffix] = tab

            item = QListWidgetItem(self.channel_list)
            cb = QCheckBox(display)
            cb.setChecked(True)
            self.channel_list.addItem(item)
            self.channel_list.setItemWidget(item, cb)
            item.setSizeHint(cb.sizeHint())
            self._channel_checks[ch.suffix] = cb

    # ---------- 槽 ----------
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
            self._rebuild_channel_widgets()

    def _show_about(self) -> None:
        QMessageBox.information(
            self,
            "关于",
            f"Heidstar 多通道图像平场性检测\n"
            f"版本 v{__version__}\n\n"
            "基于 BaSiCPy + PyQt5，"
            "支持 Ubuntu 22.04 / Windows。\n\n"
            "源代码运行: python run.py",
        )

    def _set_all_channels_checked(self, checked: bool) -> None:
        for cb in self._channel_checks.values():
            cb.setChecked(checked)

    def _append_log(self, line: str) -> None:
        self._log_buffer.append(line)
        # 控制内存，保留最近 5000 行（每行通常 < 200B，整体上限 ~1MB）
        if len(self._log_buffer) > 5000:
            self._log_buffer = self._log_buffer[-5000:]
        if self._log_dialog is not None and self._log_dialog.isVisible():
            self._log_dialog.append(line)

    def _show_log_dialog(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = LogDialog(self)
        # 每次打开都用全量 buffer 重新填充，避免遗漏关闭期间累积的日志
        self._log_dialog.set_lines(self._log_buffer)
        self._log_dialog.show()
        self._log_dialog.raise_()
        self._log_dialog.activateWindow()

    def _build_jobs(self) -> List[ChannelJob]:
        jobs: List[ChannelJob] = []
        for ch in self._discovered:
            cb = self._channel_checks.get(ch.suffix)
            if cb is None or not cb.isChecked():
                continue
            pref = self.cfg.pref_for(ch.suffix)
            display = pref.display_name or ch.display_name
            jobs.append(
                ChannelJob(
                    discovered=ch,
                    display_name=display,
                    thresholds=_build_thresholds(
                        self.cfg, pref.uniformity_threshold
                    ),
                )
            )
        return jobs

    def _on_start(self) -> None:
        root = self.input_edit.text().strip()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(self, "提示", "请先选择并扫描有效的根目录")
            return
        if not self._discovered:
            QMessageBox.warning(self, "提示", "未发现通道，请先点击「扫描」")
            return

        jobs = self._build_jobs()
        if not jobs:
            QMessageBox.warning(self, "提示", "至少勾选一个通道")
            return

        output_dir = self.output_edit.text().strip()
        if not output_dir:
            output_dir = str(Path(root) / self.cfg.output_subdir)
            self.output_edit.setText(output_dir)

        # 清空上一轮结果，开始新一轮收集；新一轮跑完前禁用导出
        self._results.clear()
        self._last_output_dir = output_dir
        self.export_btn.setEnabled(False)

        total = len(jobs)
        for i, j in enumerate(jobs, 1):
            tab = self._tabs_by_suffix.get(j.suffix)
            if tab is not None:
                tab.reset(j.thresholds)
                tab.set_queue_position(i, total)

        self._log_buffer.clear()
        if self._log_dialog is not None and self._log_dialog.isVisible():
            self._log_dialog.set_lines([])
        self._append_log(f"扫描根目录: {root}")
        self._append_log(f"输出目录: {output_dir}")
        self._append_log(
            f"队列 ({total} 个通道): "
            + " → ".join(j.suffix for j in jobs)
        )

        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.statusBar().showMessage("运行中…")

        self._worker = FlatfieldWorker(
            jobs=jobs,
            output_root=output_dir,
            examples_per_channel=self.cfg.examples_per_channel,
            image_glob=self.cfg.image_glob,
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
        self._tick_timer.start()

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self.statusBar().showMessage("已请求停止，等待当前通道结束…")
            self.stop_btn.setEnabled(False)

    def _on_stage(self, suffix: str, stage: str) -> None:
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_stage(stage)
            idx = self.tabs.indexOf(tab)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        self.statusBar().showMessage(f"{suffix} — {stage}")

    def _on_progress(self, suffix: str, current: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_progress(current, total)
        self.statusBar().showMessage(f"{suffix} — 加载 {current}/{total}")

    def _tick(self) -> None:
        """每秒更新一次运行中通道的徽章 (秒表)。"""
        for tab in self._tabs_by_suffix.values():
            tab.tick()

    def _on_channel_done(self, result: ChannelResult) -> None:
        tab = self._tabs_by_suffix.get(result.suffix)
        if tab is not None:
            tab.on_result(result)
        self._results.append(result)
        self.export_btn.setEnabled(True)
        self.progress.setRange(0, 0)

    def _on_channel_failed(self, suffix: str, msg: str) -> None:
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_error(msg)

    def _on_all_finished(self) -> None:
        self._tick_timer.stop()
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.statusBar().showMessage("全部完成")
        self._append_log("====== 全部通道处理结束 ======")

    # ---------- PDF 导出 ----------
    def _on_export_pdf(self) -> None:
        if not self._results:
            QMessageBox.information(self, "提示", "尚无已完成的通道结果，无法导出。")
            return

        default_dir = self._last_output_dir or self.output_edit.text().strip() or "."
        default_name = (
            f"flatfield_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        default_path = str(Path(default_dir) / default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "导出 PDF 报告", default_path, "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        # 禁用按钮，避免重复点击；状态栏进度
        self.export_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._append_log(f"开始导出 PDF 报告 → {path}")

        from PyQt5.QtWidgets import QApplication

        def on_progress(label: str, cur: int, total: int) -> None:
            self.statusBar().showMessage(f"导出 PDF — {label} ({cur}/{total})")
            # 把控制权让回事件循环，避免界面"假死"
            QApplication.processEvents()

        try:
            scan_root = self.input_edit.text().strip()
            generate_pdf_report(
                results=self._results,
                output_path=path,
                scan_root=scan_root,
                output_dir=self._last_output_dir or "",
                progress_fn=on_progress,
            )
        except Exception as e:
            self._append_log(f"导出失败: {e}")
            QMessageBox.warning(self, "导出失败", f"PDF 导出过程中出错:\n{e}")
            self.statusBar().showMessage("导出失败")
        else:
            self._append_log(f"PDF 报告已生成: {path}")
            self.statusBar().showMessage(f"PDF 已生成: {path}")
            QMessageBox.information(self, "导出完成", f"PDF 报告已保存到:\n{path}")
        finally:
            self.export_btn.setEnabled(True)
            self.start_btn.setEnabled(True)

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
