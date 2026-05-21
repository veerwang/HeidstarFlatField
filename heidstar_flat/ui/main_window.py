"""主窗口：顶级 Tab 容器（平场检测 / 杂散光检测）。

历史上所有平场流程都直接挂在 MainWindow 上；为加入杂散光后保持两套
流程独立，重构为：
- MainWindow 只做容器（顶级 Tab + 工具栏 + 状态栏 + 日志对话框）
- FlatfieldPanel 自包含平场流程
- StrayLightPanel 自包含杂散光流程（B3 待实现，当前占位）
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAction,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
)

from heidstar_flat import __version__
from heidstar_flat.config import AppConfig, load_config, save_config
from heidstar_flat.ui.flatfield_panel import FlatfieldPanel
from heidstar_flat.ui.log_dialog import LogDialog
from heidstar_flat.ui.settings_dialog import SettingsDialog
from heidstar_flat.ui.stray_light_panel import StrayLightPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Heidstar 多通道平场性检测  v{__version__}")
        self.resize(1280, 860)

        self.cfg: AppConfig = load_config()

        # 日志缓存与对话框（跨面板共享，按需打开）
        self._log_buffer: List[str] = []
        self._log_dialog: LogDialog | None = None

        self._build_ui()

    # ---------- UI 构建 ----------
    def _build_ui(self) -> None:
        self.top_tabs = QTabWidget(self)
        self.setCentralWidget(self.top_tabs)

        # 平场检测面板：原 MainWindow 所有平场流程
        self.flatfield_panel = FlatfieldPanel(self.cfg, self)
        self.flatfield_panel.log_emitted.connect(self._append_log)
        self.flatfield_panel.log_cleared.connect(self._clear_log_buffer)
        self.flatfield_panel.status_changed.connect(self._on_panel_status)
        self.top_tabs.addTab(self.flatfield_panel, "平场检测")

        # 杂散光检测面板
        self.stray_panel = StrayLightPanel(self.cfg, self)
        self.stray_panel.log_emitted.connect(self._append_log)
        self.stray_panel.log_cleared.connect(self._clear_log_buffer)
        self.stray_panel.status_changed.connect(self._on_panel_status)
        self.top_tabs.addTab(self.stray_panel, "杂散光检测")

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
        act_criteria = QAction("判据说明", self)
        act_criteria.setShortcut("F1")
        act_criteria.setToolTip("打开 docs/CRITERIA.pdf — 平场 + 杂散光所有判据详解")
        act_criteria.triggered.connect(self._open_criteria_doc)
        tb.addAction(act_criteria)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._show_about)
        tb.addAction(act_about)

    # ---------- 设置 / 关于 ----------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec_() == dlg.Accepted:
            self.cfg = dlg.gather()
            try:
                save_config(self.cfg)
            except Exception as e:
                self._append_log(f"保存配置失败: {e}")
            # 通知所有面板配置变了，刷新阈值/显示名等
            self.flatfield_panel.on_config_changed(self.cfg)
            self.stray_panel.on_config_changed(self.cfg)

    def _open_criteria_doc(self) -> None:
        """用系统默认 PDF 阅读器打开 docs/CRITERIA.pdf。"""
        # main_window.py 在 heidstar_flat/ui/，向上回到仓库根，再进 docs/
        pdf_path = (
            Path(__file__).resolve().parent.parent.parent / "docs" / "CRITERIA.pdf"
        )
        if not pdf_path.is_file():
            QMessageBox.warning(
                self,
                "判据说明 PDF 未找到",
                f"找不到 {pdf_path}\n\n"
                f"该 PDF 需要从 CRITERIA.md 构建生成：\n"
                f"    python scripts/build_criteria_pdf.py\n\n"
                f"作为备选，可直接打开仓库根的 CRITERIA.md 阅读。",
            )
            return
        url = QUrl.fromLocalFile(str(pdf_path))
        if not QDesktopServices.openUrl(url):
            QMessageBox.warning(
                self,
                "打开失败",
                f"系统无法打开 PDF 文件：\n{pdf_path}\n\n"
                f"请检查是否安装了 PDF 阅读器。",
            )

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

    # ---------- 状态栏 / 日志 ----------
    def _on_panel_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def _append_log(self, line: str) -> None:
        self._log_buffer.append(line)
        # 控制内存，保留最近 5000 行（每行通常 < 200B，整体上限 ~1MB）
        if len(self._log_buffer) > 5000:
            self._log_buffer = self._log_buffer[-5000:]
        if self._log_dialog is not None and self._log_dialog.isVisible():
            self._log_dialog.append(line)

    def _clear_log_buffer(self) -> None:
        """新一轮运行开始时由 panel 触发，清空全局日志缓存。"""
        self._log_buffer.clear()
        if self._log_dialog is not None and self._log_dialog.isVisible():
            self._log_dialog.set_lines([])

    def _show_log_dialog(self) -> None:
        if self._log_dialog is None:
            self._log_dialog = LogDialog(self)
        # 每次打开都用全量 buffer 重新填充，避免遗漏关闭期间累积的日志
        self._log_dialog.set_lines(self._log_buffer)
        self._log_dialog.show()
        self._log_dialog.raise_()
        self._log_dialog.activateWindow()

    # ---------- 关窗 ----------
    def _all_panels(self):
        return (self.flatfield_panel, self.stray_panel)

    def closeEvent(self, event) -> None:
        running_panels = [p for p in self._all_panels() if p.is_running()]

        # 没有计算线程在跑，直接关
        if not running_panels:
            for p in self._all_panels():
                p.block_pending_signals()
                p.stop_timers()
            event.accept()
            return

        # 有计算线程在跑，让用户决定：等待 / 强退 / 取消
        reply = QMessageBox.question(
            self,
            "处理中",
            "当前正在处理通道。\n\n"
            "[Yes] 等待当前通道结束后退出（推荐）\n"
            "[No] 强制退出（可能不稳定）\n"
            "[Cancel] 不退出，继续运行",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Cancel:
            event.ignore()
            return

        # 在 wait/accept 前先切断信号，避免回调进入将被销毁的 UI 对象
        for p in running_panels:
            p.block_pending_signals()

        if reply == QMessageBox.Yes:
            self.statusBar().showMessage("等待当前通道结束（最多 10 分钟）…")
            for p in running_panels:
                p.request_stop_and_wait(10 * 60 * 1000)  # 6000 × 100ms = 10 min

        for p in self._all_panels():
            p.stop_timers()
        event.accept()
