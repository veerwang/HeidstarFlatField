"""QApplication 入口。"""

from __future__ import annotations

import os
import sys


def _configure_qt_env() -> None:
    # Ubuntu Wayland 上若 PyQt5 找不到平台插件，可在此回退；保留默认即可。
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")


# 全局基础字号 (pt)。Linux 默认 ~9pt 偏小，统一抬到 11pt；
# 子控件可在 stylesheet 里继续单独放大（如徽章、表格、通道名）。
GLOBAL_FONT_POINT_SIZE = 11


def _apply_global_font(app) -> None:
    from PyQt5.QtGui import QFont

    font = app.font()
    font.setPointSize(GLOBAL_FONT_POINT_SIZE)
    app.setFont(font)


def main(argv: list[str] | None = None) -> int:
    _configure_qt_env()
    from PyQt5.QtWidgets import QApplication

    from heidstar_flat import __version__

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("HeidstarFlat")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Heidstar")
    _apply_global_font(app)

    # 仅在 QApplication 之后导入主窗口（避免 matplotlib Qt 后端在没有 app 时报错）。
    from heidstar_flat.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec_()
