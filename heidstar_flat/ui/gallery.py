"""示例三联画的画廊视图。"""

from __future__ import annotations

from typing import List

from PyQt5.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from heidstar_flat.core.metrics import ExampleTriplet
from heidstar_flat.ui.mpl_canvas import ExampleTripletCanvas


class GalleryView(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self.setWidget(self._inner)
        self._canvases: List[ExampleTripletCanvas] = []

    def show_examples(self, examples: List[ExampleTriplet]) -> None:
        # 清空旧 widget
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._canvases.clear()

        for ex in examples:
            canvas = ExampleTripletCanvas(self._inner)
            canvas.setMinimumHeight(260)
            canvas.show_triplet(ex.original, ex.corrected, ex.difference, ex.index)
            self._layout.addWidget(canvas)
            self._canvases.append(canvas)
        self._layout.addStretch(1)
