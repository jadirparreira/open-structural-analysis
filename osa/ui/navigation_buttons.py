"""Standalone controls placed beside the scene navigation cube."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolButton


class SlopedPlaneButton(QToolButton):
    """A border-only control whose clickable face is a sloped reference plane."""

    def __init__(
        self,
        parent=None,
        *,
        mirrored: bool = False,
        horizontal_chamfer: float = 8.0,
        vertical_chamfer: float = 8.0,
        icon_offset_x: int = 0,
        icon_offset_y: int = 0,
    ) -> None:
        super().__init__(parent)
        self._mirrored = mirrored
        self._horizontal_chamfer = horizontal_chamfer
        self._vertical_chamfer = vertical_chamfer
        self._icon_offset_x = icon_offset_x
        self._icon_offset_y = icon_offset_y
        self.setFixedSize(34, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def _shape(self) -> QPainterPath:
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        shoulder = self._horizontal_chamfer
        slope_bottom = bottom - self._vertical_chamfer
        if self._mirrored:
            points = (
                QPointF(right, top), QPointF(left + rect.width() - shoulder, top),
                QPointF(left, slope_bottom), QPointF(left, bottom), QPointF(right, bottom),
            )
        else:
            points = (
                QPointF(left, top), QPointF(left + shoulder, top),
                QPointF(right, slope_bottom), QPointF(right, bottom), QPointF(left, bottom),
            )
        radius = 5.0
        rounded: list[tuple[QPointF, QPointF]] = []
        for index, point in enumerate(points):
            previous = points[index - 1]
            following = points[(index + 1) % len(points)]
            before_length = max(((previous.x() - point.x()) ** 2 + (previous.y() - point.y()) ** 2) ** 0.5, 1e-9)
            after_length = max(((following.x() - point.x()) ** 2 + (following.y() - point.y()) ** 2) ** 0.5, 1e-9)
            corner_radius = min(radius, before_length / 3.0, after_length / 3.0)
            before = QPointF(
                point.x() + (previous.x() - point.x()) * corner_radius / before_length,
                point.y() + (previous.y() - point.y()) * corner_radius / before_length,
            )
            after = QPointF(
                point.x() + (following.x() - point.x()) * corner_radius / after_length,
                point.y() + (following.y() - point.y()) * corner_radius / after_length,
            )
            rounded.append((before, after))
        path = QPainterPath(rounded[0][1])
        for index, point in enumerate(points[1:], start=1):
            before, after = rounded[index]
            path.lineTo(before)
            path.quadTo(point, after)
        path.lineTo(rounded[0][0])
        path.quadTo(points[0], rounded[0][1])
        path.closeSubpath()
        return path

    def hitButton(self, position) -> bool:
        return self._shape().contains(QPointF(position))

    def paintEvent(self, event) -> None:
        del event
        background = "#d0d7de" if self.isDown() else "#eaeef2" if self.underMouse() else "#f6f8fa"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#d0d7de"), 1.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(background))
        painter.drawPath(self._shape())
        icon = self.icon()
        if not icon.isNull():
            size = self.iconSize()
            horizontal_padding = (self.width() - size.width()) // 2
            vertical_padding = (self.height() - size.height()) // 2
            icon.paint(
                painter,
                self.rect().adjusted(
                    horizontal_padding + self._icon_offset_x,
                    vertical_padding + self._icon_offset_y,
                    -horizontal_padding + self._icon_offset_x,
                    -vertical_padding + self._icon_offset_y,
                ),
            )
        painter.end()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()


class LeftArrowButton(QToolButton):
    """A compact arrow-shaped control for the viewport navigation cluster."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._point_right = False
        self.setFixedSize(30, 34)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def _shape(self) -> QPainterPath:
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        center_y = (top + bottom) / 2
        chamfer = 12.0
        tip_half_height = 3.0
        if self._point_right:
            points = (
                QPointF(left + 3.0, top),
                QPointF(right - chamfer, top),
                QPointF(right, center_y - tip_half_height),
                QPointF(right, center_y + tip_half_height),
                QPointF(right - chamfer, bottom),
                QPointF(left + 3.0, bottom),
                QPointF(left, bottom - 3.0),
                QPointF(left, top + 3.0),
            )
        else:
            points = (
                QPointF(left + chamfer, top),
                QPointF(right - 3.0, top),
                QPointF(right, top + 3.0),
                QPointF(right, bottom - 3.0),
                QPointF(right - 3.0, bottom),
                QPointF(left + chamfer, bottom),
                QPointF(left, center_y + tip_half_height),
                QPointF(left, center_y - tip_half_height),
            )
        radius = 3.0
        rounded: list[tuple[QPointF, QPointF]] = []
        for index, point in enumerate(points):
            previous = points[index - 1]
            following = points[(index + 1) % len(points)]
            before_length = max(
                ((previous.x() - point.x()) ** 2 + (previous.y() - point.y()) ** 2) ** 0.5,
                1e-9,
            )
            after_length = max(
                ((following.x() - point.x()) ** 2 + (following.y() - point.y()) ** 2) ** 0.5,
                1e-9,
            )
            corner_radius = min(radius, before_length / 3.0, after_length / 3.0)
            before = QPointF(
                point.x() + (previous.x() - point.x()) * corner_radius / before_length,
                point.y() + (previous.y() - point.y()) * corner_radius / before_length,
            )
            after = QPointF(
                point.x() + (following.x() - point.x()) * corner_radius / after_length,
                point.y() + (following.y() - point.y()) * corner_radius / after_length,
            )
            rounded.append((before, after))
        path = QPainterPath()
        path.moveTo(rounded[0][1])
        for index, point in enumerate(points[1:], start=1):
            before, after = rounded[index]
            path.lineTo(before)
            path.quadTo(point, after)
        path.lineTo(rounded[0][0])
        path.quadTo(points[0], rounded[0][1])
        path.closeSubpath()
        return path

    def hitButton(self, position) -> bool:
        return self._shape().contains(QPointF(position))

    def paintEvent(self, event) -> None:
        del event
        background = "#d0d7de" if self.isDown() else "#eaeef2" if self.underMouse() else "#f6f8fa"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#d0d7de"), 1.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(background))
        painter.drawPath(self._shape())
        icon = self.icon()
        if not icon.isNull():
            horizontal_adjustment = (4, -8) if self._point_right else (8, -4)
            icon.paint(painter, self.rect().adjusted(horizontal_adjustment[0], 7, horizontal_adjustment[1], -7))
        painter.end()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()


class RightArrowButton(LeftArrowButton):
    """Right-facing counterpart to :class:`LeftArrowButton`."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._point_right = True
