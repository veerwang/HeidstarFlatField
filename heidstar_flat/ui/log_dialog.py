"""独立日志查看对话框。

主窗口不再常驻日志面板；用户从工具栏「查看日志」按需打开。
对话框为非模态（用户打开后仍可继续操作主窗口）。
"""

from __future__ import annotations

from typing import Iterable

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class LogDialog(QDialog):
    """非模态日志查看对话框。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行日志")
        # 去掉标题栏右上角的 "?" 帮助按钮
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(960, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        font.setPointSize(10)
        self.log_view.setFont(font)
        layout.addWidget(self.log_view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.log_view.clear)
        btn_row.addWidget(clear_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def append(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def set_lines(self, lines: Iterable[str]) -> None:
        """用给定的全部历史日志重置显示。"""
        self.log_view.clear()
        for line in lines:
            self.log_view.appendPlainText(line)
