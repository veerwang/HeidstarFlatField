"""PDF 导出 QThread Worker。

把 core/report.py 或 core/stray_report.py 的同步 PDF 生成函数包到 QThread 里。

原来 _on_export_pdf 在主线程里跑 generate_pdf_report，靠在 progress 回调里
调 QApplication.processEvents() 顶住界面响应——这导致：
  - 界面虽然不冻结但用户能触发其他动作（重入隐患）
  - 改了设置 / 关窗 等行为发生在 PDF 生成中途，行为不可预期

异步化后：
  - generate_*_pdf_report 在 worker 线程独立跑
  - 主线程的 QFileDialog → 启动 worker → finished/failed 回主线程触发
    QMessageBox 提示
  - PdfExportWorker 持有 results 列表的浅拷贝快照（panel 给 list(...) 传入），
    哪怕 panel 的 _results 被 _rebuild 清空也不影响在跑的导出
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from PyQt5.QtCore import QObject, QThread, pyqtSignal


class PdfExportWorker(QObject):
    """通用 PDF 导出 worker；report_fn 可以是 generate_pdf_report 或
    generate_stray_pdf_report。

    report_fn(**kwargs) 必须接受 `progress_fn=callable(label, cur, total)`
    并返回生成的 PDF 路径。
    """

    progress = pyqtSignal(str, int, int)   # (label, current_page, total_pages)
    finished = pyqtSignal(str)             # output_path
    failed = pyqtSignal(str)               # error message

    def __init__(
        self,
        report_fn: Callable[..., Any],
        kwargs: Dict[str, Any],
    ) -> None:
        super().__init__()
        self._report_fn = report_fn
        # 浅拷贝调用方传入的 kwargs，避免后续调用方修改影响本线程
        self._kwargs = dict(kwargs)
        # 注入 progress 回调
        self._kwargs["progress_fn"] = self._emit_progress

    def _emit_progress(self, label: str, current: int, total: int) -> None:
        self.progress.emit(label, current, total)

    def run(self) -> None:
        try:
            result_path = self._report_fn(**self._kwargs)
            self.finished.emit(str(result_path))
        except Exception as e:
            self.failed.emit(str(e))


def make_pdf_export_thread(worker: PdfExportWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    return thread
