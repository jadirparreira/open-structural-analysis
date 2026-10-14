"""Geração de prévias leves da geometria de um modelo estrutural."""

from __future__ import annotations

import base64
import math

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from osa.domain import StructuralModel


class ThumbnailService:
    """Cria uma miniatura determinística sem inicializar a cena VTK."""

    DEFAULT_SIZE = QSize(320, 180)
    _margin = 18.0
    _view_direction = (-1.0, -1.0, 1.0)
    _world_up = (0.0, 0.0, 1.0)

    @classmethod
    def generate(cls, model: StructuralModel, size: QSize | None = None) -> str:
        size = size or cls.DEFAULT_SIZE
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#ffffff"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            points = {
                name: (float(node.x), float(node.y), float(node.z))
                for name, node in model.nodes.items()
            }
            segments = []
            for member in model.bars.values():
                start = points.get(member.start_node)
                end = points.get(member.end_node)
                if start is not None and end is not None:
                    segments.append((start, end, "#6e7781", 2.2))
            for rigid in model.rigid_bars.values():
                start = points.get(rigid.start_node)
                end = points.get(rigid.end_node)
                if start is not None and end is not None:
                    segments.append((start, end, "#6e7781", 2.2))

            projected = [cls._project(point) for point in points.values()]
            projected.extend(cls._project(point) for segment in segments for point in segment[:2])
            if not projected:
                cls._draw_empty_state(painter, image.size())
            else:
                transform = cls._fit_transform(projected, image.width(), image.height())
                for start, end, color, width in segments:
                    painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawLine(cls._to_screen(cls._project(start), transform), cls._to_screen(cls._project(end), transform))
        finally:
            painter.end()

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return base64.b64encode(bytes(buffer.data())).decode("ascii")

    @staticmethod
    def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(sum(value * value for value in vector))
        return tuple(value / length for value in vector)

    @classmethod
    def _project(cls, point: tuple[float, float, float]) -> tuple[float, float]:
        view = cls._normalize(cls._view_direction)
        right = cls._normalize((view[1], -view[0], 0.0))
        up = cls._normalize((
            right[1] * view[2] - right[2] * view[1],
            right[2] * view[0] - right[0] * view[2],
            right[0] * view[1] - right[1] * view[0],
        ))
        return (
            sum(point[index] * right[index] for index in range(3)),
            sum(point[index] * up[index] for index in range(3)),
        )

    @classmethod
    def _fit_transform(cls, projected, width: int, height: int) -> tuple[float, float, float, int, int]:
        min_x = min(point[0] for point in projected)
        max_x = max(point[0] for point in projected)
        min_y = min(point[1] for point in projected)
        max_y = max(point[1] for point in projected)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        scale = min((width - 2 * cls._margin) / span_x, (height - 2 * cls._margin) / span_y)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        return scale, center_x, center_y, width, height

    @staticmethod
    def _to_screen(point: tuple[float, float], transform: tuple[float, float, float, int, int]) -> QPointF:
        scale, center_x, center_y, width, height = transform
        return QPointF(
            (point[0] - center_x) * scale + width / 2.0,
            height / 2.0 - (point[1] - center_y) * scale,
        )

    @staticmethod
    def _draw_empty_state(painter: QPainter, size: QSize) -> None:
        painter.setPen(QPen(QColor("#d0d7de"), 1.0))
        painter.drawRect(0, 0, size.width() - 1, size.height() - 1)


def thumbnail_to_bytes(value: str | None) -> bytes | None:
    if not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
