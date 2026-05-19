"""QApplication 入口。"""

from __future__ import annotations

import os
import sys


def _configure_qt_env() -> None:
    # Ubuntu Wayland 上若 PyQt5 找不到平台插件，可在此回退；保留默认即可。
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


def main(argv: list[str] | None = None) -> int:
    _configure_qt_env()
    from PyQt5.QtWidgets import QApplication

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("HeidstarFlat")
    app.setOrganizationName("Heidstar")

    # 仅在 QApplication 之后导入主窗口（避免 matplotlib Qt 后端在没有 app 时报错）。
    from heidstar_flat.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()
