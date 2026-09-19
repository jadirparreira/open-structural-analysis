"""Compact, text-free honeycomb palette used to choose member colors."""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QFrame


# The colors are sampled from the reference palette. The repeated purple is
# intentional: the upper swatch is magenta-based and the lower one is green-based.
MEMBER_COLOR_CELLS = (
    ("#f000be", 2, 0),
    ("#f50068", 1, 1), ("#8d00c5", 3, 1),
    ("#f40000", 0, 2), ("#9b005f", 2, 2), ("#0712b8", 4, 2),
    ("#8d0000", 1, 3), ("#071783", 3, 3),
    ("#f99b00", 0, 4), ("#6e7781", 2, 4), ("#0878df", 4, 4),
    ("#9b8700", 1, 5), ("#006b78", 3, 5),
    ("#fff900", 0, 6), ("#008b18", 2, 6), ("#08c8ef", 4, 6),
    ("#72d900", 1, 7), ("#00cba0", 3, 7),
    ("#00cc08", 2, 8),
)


class HoneycombColorPalette(QFrame):
    """Popup palette whose cells are clickable regular hexagons."""

    # Half-scale cells make the picker compact while the wider horizontal
    # spacing keeps the 19-cell silhouette close to the reference image.
    _radius = 19.0
    _column_step = 37.5
    _row_step = 24.5
    _origin = QPointF(19.5, 17.5)

    def __init__(self, parent, on_color_selected: Callable[[str], None]) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("memberColorPalette")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(190, 234)
        self.setStyleSheet(
            "QFrame#memberColorPalette { background: transparent; border: 0; }"
        )
        self._on_color_selected = on_color_selected
        self._selected = "#6e7781"

    def set_selected(self, color: str) -> None:
        self._selected = color.lower()
        self.update()

    def _center(self, column: int, row: int) -> QPointF:
        return QPointF(
            self._origin.x() + column * self._column_step,
            self._origin.y() + row * self._row_step,
        )

    def _polygon(self, center: QPointF) -> QPolygonF:
        points = []
        for index in range(6):
            angle = math.radians(index * 60)
            points.append(QPointF(
                center.x() + self._radius * math.cos(angle),
                center.y() + self._radius * math.sin(angle),
            ))
        return QPolygonF(points)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"), 2.0))
        for color, column, row in MEMBER_COLOR_CELLS:
            polygon = self._polygon(self._center(column, row))
            painter.setBrush(QColor(color))
            painter.drawPolygon(polygon)
            if color == self._selected:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#24292f"), 2.0))
                painter.drawPolygon(polygon)
                painter.setPen(QPen(QColor("#ffffff"), 2.0))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = event.position()
            for color, column, row in MEMBER_COLOR_CELLS:
                if self._polygon(self._center(column, row)).containsPoint(
                    position, Qt.FillRule.OddEvenFill
                ):
                    self._selected = color
                    self._on_color_selected(color)
                    self.hide()
                    event.accept()
                    return
        super().mousePressEvent(event)
