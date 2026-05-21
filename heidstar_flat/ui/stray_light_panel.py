"""杂散光检测面板。

结构与 FlatfieldPanel 镜像（输入栏 / 通道列表 / 控制按钮 / 通道 Tab 区），
但接的是 StrayLightWorker，每通道用 StrayChannelTab，无示例三联画。

PDF 导出（B4）：当前按钮 disable，B4 实现 stray_report.py 后接入。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List, Optional

from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from datetime import datetime

from heidstar_flat.config import AppConfig
from heidstar_flat.core.loader import DiscoveredChannel, discover_channels
from heidstar_flat.core.stray_light import StrayLightThresholds
from heidstar_flat.core.stray_report import generate_stray_pdf_report
from heidstar_flat.stray_worker import (
    StrayChannelJob,
    StrayChannelResult,
    StrayLightWorker,
    make_stray_worker_thread,
)
from heidstar_flat.ui.stray_channel_tab import StrayChannelTab


class _ScanWorker(QObject):
    """后台扫描暗场根目录 → 发现通道（与 flatfield_panel._ScanWorker 同语义）。"""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, root: str, image_subdir: str, image_glob: str) -> None:
        super().__init__()
        self._root = root
        self._image_subdir = image_subdir
        self._image_glob = image_glob

    def run(self) -> None:
        try:
            channels = discover_channels(
                self._root,
                image_subdir=self._image_subdir,
                image_glob=self._image_glob,
            )
            self.finished.emit(channels)
        except Exception as e:
            self.failed.emit(str(e))


def _build_thresholds(cfg: AppConfig) -> StrayLightThresholds:
    return StrayLightThresholds(
        dc_pct_of_max=cfg.stray_dc_threshold,
        zone_dc_uniformity_pct=cfg.stray_zone_dc_uniformity_threshold,
        dsnu_pct_of_max=cfg.stray_dsnu_threshold,
        temporal_noise_pct=cfg.stray_temporal_noise_threshold,
        hot_pixel_pct=cfg.stray_hot_pixel_threshold,
    )


class StrayLightPanel(QWidget):
    """杂散光检测主面板。"""

    log_emitted = pyqtSignal(str)
    log_cleared = pyqtSignal()
    status_changed = pyqtSignal(str)
    running_changed = pyqtSignal(bool)

    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._thread: QThread | None = None
        self._worker: StrayLightWorker | None = None

        self._discovered: List[DiscoveredChannel] = []
        self._tabs_by_suffix: Dict[str, StrayChannelTab] = {}
        self._channel_checks: Dict[str, QCheckBox] = {}
        self._channel_items: Dict[str, QListWidgetItem] = {}  # suffix → list item
        self._results: List[StrayChannelResult] = []
        self._last_output_dir: str = ""

        # 本轮 worker 运行的元数据（用于 ETA 计算）
        self._worker_start_time: Optional[float] = None
        self._total_jobs_in_run: int = 0

        self._scan_thread: QThread | None = None
        self._scan_worker: _ScanWorker | None = None

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._build_ui()

    # ---------- UI 构建 ----------
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)

        io_box = QGroupBox("输入 / 输出（关激发暗场图）")
        io_layout = QVBoxLayout(io_box)

        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("暗场扫描根目录"))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "选择含 *_<Color>/Images/IMG*.tif 的暗场目录（关激发拍摄）"
        )
        self.input_edit.editingFinished.connect(self._maybe_rescan)
        in_row.addWidget(self.input_edit, 1)
        self.browse_btn = QPushButton("浏览…")
        self.browse_btn.clicked.connect(self._choose_input_dir)
        in_row.addWidget(self.browse_btn)
        self.scan_btn = QPushButton("扫描")
        self.scan_btn.clicked.connect(self._rescan)
        in_row.addWidget(self.scan_btn)
        io_layout.addLayout(in_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("默认: <暗场根目录>/stray_results")
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
            "尚未扫描到通道。请先在上方选择暗场扫描根目录并点击「扫描」。"
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

    # ---------- 扫描 / 通道发现 ----------
    def _choose_input_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择暗场扫描根目录", self.input_edit.text()
        )
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
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        if self._thread is not None and self._thread.isRunning():
            self.log_emitted.emit("通道处理进行中，扫描请求被忽略")
            return

        self._set_scan_controls_enabled(False)
        self.status_changed.emit(f"扫描中: {root} …")
        self.log_emitted.emit(f"[杂散光] 开始扫描: {root}")

        self._scan_worker = _ScanWorker(
            root, self.cfg.image_subdir, self.cfg.image_glob
        )
        self._scan_thread = QThread()
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._cleanup_scan_thread)
        self._scan_thread.start()

    def _set_scan_controls_enabled(self, enabled: bool) -> None:
        self.input_edit.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.scan_btn.setEnabled(enabled)

    def _on_scan_finished(self, channels: list) -> None:
        self._discovered = channels
        self._rebuild_channel_widgets()
        root = self.input_edit.text().strip()
        if not channels:
            self.status_changed.emit(
                "未在该目录发现通道：需要形如 *_<Color>/Images/IMG*.tif 的结构"
            )
            self.log_emitted.emit(f"[杂散光] 扫描 {root}：未发现通道")
        else:
            self.status_changed.emit(f"发现 {len(channels)} 个通道")
            self.log_emitted.emit(
                f"[杂散光] 扫描 {root}：发现 {len(channels)} 个通道 — "
                + ", ".join(c.suffix for c in channels)
            )

    def _on_scan_failed(self, err: str) -> None:
        QMessageBox.warning(self, "扫描失败", err)
        self.log_emitted.emit(f"[杂散光] 扫描失败: {err}")
        self.status_changed.emit("扫描失败")

    def _cleanup_scan_thread(self) -> None:
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
            self._scan_thread = None
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None
        self._set_scan_controls_enabled(True)

    def _rebuild_channel_widgets(self) -> None:
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            if w is not self._empty_hint:
                w.deleteLater()
        self._tabs_by_suffix.clear()
        self.channel_list.clear()
        self._channel_checks.clear()
        self._channel_items.clear()

        # 旧结果与新扫描的通道集合无关，必须清掉
        self._results.clear()
        self._last_output_dir = ""
        self.export_btn.setEnabled(False)

        if not self._discovered:
            self.tabs.addTab(self._empty_hint, "提示")
            return

        thresholds = _build_thresholds(self.cfg)
        for ch in self._discovered:
            pref = self.cfg.pref_for(ch.suffix)
            display = pref.display_name or ch.display_name
            tab = StrayChannelTab(ch.suffix, display, thresholds)
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
            self._channel_items[ch.suffix] = item

    # ---------- 槽 ----------
    def _choose_output_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择输出目录", self.output_edit.text()
        )
        if d:
            self.output_edit.setText(d)

    def _set_all_channels_checked(self, checked: bool) -> None:
        for cb in self._channel_checks.values():
            cb.setChecked(checked)

    def _build_jobs(self) -> List[StrayChannelJob]:
        jobs: List[StrayChannelJob] = []
        thresholds = _build_thresholds(self.cfg)
        for ch in self._discovered:
            cb = self._channel_checks.get(ch.suffix)
            if cb is None or not cb.isChecked():
                continue
            pref = self.cfg.pref_for(ch.suffix)
            display = pref.display_name or ch.display_name
            jobs.append(
                StrayChannelJob(
                    discovered=ch, display_name=display, thresholds=thresholds,
                )
            )
        return jobs

    def _on_start(self) -> None:
        root = self.input_edit.text().strip()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(self, "提示", "请先选择并扫描有效的暗场根目录")
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
            output_dir = str(Path(root) / "stray_results")
            self.output_edit.setText(output_dir)

        self._results.clear()
        self._last_output_dir = output_dir
        self.export_btn.setEnabled(False)

        # 记录本轮 worker 元数据（用于 ETA）
        self._worker_start_time = time.monotonic()
        self._total_jobs_in_run = len(jobs)

        total = len(jobs)
        for i, j in enumerate(jobs, 1):
            tab = self._tabs_by_suffix.get(j.suffix)
            if tab is not None:
                tab.reset(j.thresholds)
                tab.set_queue_position(i, total)

        self.log_cleared.emit()
        self.log_emitted.emit(f"[杂散光] 暗场根目录: {root}")
        self.log_emitted.emit(f"[杂散光] 输出目录: {output_dir}")
        self.log_emitted.emit(
            f"[杂散光] 队列 ({total} 个通道): "
            + " → ".join(j.suffix for j in jobs)
        )

        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._set_scan_controls_enabled(False)
        self.status_changed.emit("杂散光评估运行中…")

        self._worker = StrayLightWorker(
            jobs=jobs, output_root=output_dir, image_glob=self.cfg.image_glob,
        )
        self._thread = make_stray_worker_thread(self._worker)
        self._worker.stage_changed.connect(self._on_stage)
        self._worker.log.connect(self.log_emitted)
        self._worker.progress.connect(self._on_progress)
        self._worker.channel_done.connect(self._on_channel_done)
        self._worker.channel_failed.connect(self._on_channel_failed)
        self._worker.finished.connect(self._on_all_finished)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()
        self._tick_timer.start()
        self.running_changed.emit(True)

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self.status_changed.emit("已请求停止，等待当前通道结束…")
            self.stop_btn.setEnabled(False)

    def _on_stage(self, suffix: str, stage: str) -> None:
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_stage(stage)
            idx = self.tabs.indexOf(tab)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        self._highlight_running_channel(suffix)
        self.status_changed.emit(f"{suffix} — {stage}")

    def _highlight_running_channel(self, suffix: Optional[str]) -> None:
        """高亮 list 里当前在跑的通道；suffix=None 清除所有高亮。"""
        highlight = QColor("#fff3b0")
        normal = QColor()
        for sfx, item in self._channel_items.items():
            item.setBackground(highlight if sfx == suffix else normal)

    def _emit_eta_update(self) -> None:
        """根据已完成通道的平均耗时估算剩余时间，往 status_changed 发一行。"""
        if self._worker_start_time is None or self._total_jobs_in_run <= 0:
            return
        completed = len(self._results)
        if completed == 0:
            return
        elapsed = time.monotonic() - self._worker_start_time
        avg_per = elapsed / completed
        remaining = self._total_jobs_in_run - completed
        if remaining <= 0:
            return
        eta_sec = int(avg_per * remaining)
        mm, ss = divmod(eta_sec, 60)
        self.status_changed.emit(
            f"完成 {completed}/{self._total_jobs_in_run} 通道  ·  预计剩余 {mm:02d}:{ss:02d}"
        )

    def _on_progress(self, suffix: str, current: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(current)
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_progress(current, total)
        self.status_changed.emit(f"{suffix} — 加载 {current}/{total}")

    def _tick(self) -> None:
        for tab in self._tabs_by_suffix.values():
            tab.tick()

    def _on_channel_done(self, result: StrayChannelResult) -> None:
        tab = self._tabs_by_suffix.get(result.suffix)
        if tab is not None:
            tab.on_result(result)
        self._results.append(result)
        self.export_btn.setEnabled(True)
        self.progress.setRange(0, 0)
        self._emit_eta_update()

    def _on_channel_failed(self, suffix: str, msg: str) -> None:
        tab = self._tabs_by_suffix.get(suffix)
        if tab is not None:
            tab.on_error(msg)

    def _on_all_finished(self) -> None:
        self._tick_timer.stop()
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_scan_controls_enabled(True)
        for tab in self._tabs_by_suffix.values():
            tab.mark_cancelled_if_pending()
        self._highlight_running_channel(None)
        self._worker_start_time = None
        self._total_jobs_in_run = 0
        self.status_changed.emit("杂散光评估完成")
        self.log_emitted.emit("====== [杂散光] 全部通道处理结束 ======")
        self.running_changed.emit(False)

    # ---------- PDF 导出 ----------
    def _on_export_pdf(self) -> None:
        if not self._results:
            QMessageBox.information(
                self, "提示", "尚无已完成的通道结果，无法导出。"
            )
            return

        default_dir = (
            self._last_output_dir or self.output_edit.text().strip() or "."
        )
        default_name = (
            f"stray_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        default_path = str(Path(default_dir) / default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "导出杂散光 PDF 报告", default_path, "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        self.export_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.log_emitted.emit(f"[杂散光] 开始导出 PDF 报告 → {path}")

        def on_progress(label: str, cur: int, total: int) -> None:
            self.status_changed.emit(f"导出杂散光 PDF — {label} ({cur}/{total})")
            QApplication.processEvents()

        try:
            scan_root = self.input_edit.text().strip()
            generate_stray_pdf_report(
                results=self._results,
                output_path=path,
                scan_root=scan_root,
                output_dir=self._last_output_dir or "",
                progress_fn=on_progress,
            )
        except Exception as e:
            self.log_emitted.emit(f"[杂散光] 导出失败: {e}")
            QMessageBox.warning(self, "导出失败", f"PDF 导出过程中出错:\n{e}")
            self.status_changed.emit("导出失败")
        else:
            self.log_emitted.emit(f"[杂散光] PDF 报告已生成: {path}")
            self.status_changed.emit(f"PDF 已生成: {path}")
            QMessageBox.information(
                self, "导出完成", f"杂散光 PDF 报告已保存到:\n{path}"
            )
        finally:
            self.export_btn.setEnabled(True)
            # 仅当 worker 不在跑才重开开始按钮，避免双 worker
            if self._thread is None or not self._thread.isRunning():
                self.start_btn.setEnabled(True)

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # ---------- 公共 API（供 MainWindow 调用） ----------
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def block_pending_signals(self) -> None:
        for w in (self._worker, self._scan_worker):
            if w is None:
                continue
            try:
                w.blockSignals(True)
            except Exception:
                pass

    def request_stop_and_wait(self, timeout_ms: int) -> bool:
        if not self.is_running():
            return True
        self._on_stop()
        ticks = 0
        max_ticks = max(1, timeout_ms // 100)
        while self._thread.isRunning() and ticks < max_ticks:
            self._thread.wait(100)
            QApplication.processEvents()
            ticks += 1
        if self._thread.isRunning():
            self._thread.wait(3000)
        return not self._thread.isRunning()

    def stop_timers(self) -> None:
        self._tick_timer.stop()

    def on_config_changed(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._rebuild_channel_widgets()
