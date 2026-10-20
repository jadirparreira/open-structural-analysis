"""Create and draw vector LaTeX-style equations in Qt rich-text documents."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSizeF
from PySide6.QtGui import QPainter, QTextDocument, QTextFormat, QPyTextObject
from PySide6.QtSvg import QSvgRenderer

EQUATION_OBJECT_TYPE = int(QTextFormat.ObjectTypes.UserObject) + 1
EQUATION_SVG_PROPERTY = int(QTextFormat.Property.UserProperty) + 1


@lru_cache(maxsize=256)
def equation_svg(latex: str, color: str = "#57606a", font_size: float = 13.0) -> bytes | None:
    """Render MathText to cached SVG bytes without rasterizing the equation."""
    try:
        from io import BytesIO

        from matplotlib.font_manager import FontProperties
        from matplotlib.mathtext import math_to_image

        svg = BytesIO()
        math_to_image(
            f"${latex}$",
            svg,
            format="svg",
            dpi=120,
            color=color,
            prop=FontProperties(size=font_size),
        )
        return svg.getvalue()
    except Exception:
        # Keep the memorial readable if one MathText expression is unsupported.
        return None


@lru_cache(maxsize=256)
def _svg_renderer(svg_data: bytes) -> QSvgRenderer | None:
    renderer = QSvgRenderer(QByteArray(svg_data))
    return renderer if renderer.isValid() else None


class SvgEquationObject(QPyTextObject):
    """Paint SVG paths directly into a QTextDocument as vector content."""

    def intrinsicSize(self, document: QTextDocument, position: int, format: QTextFormat) -> QSizeF:
        renderer = _svg_renderer(bytes(format.property(EQUATION_SVG_PROPERTY)))
        if renderer is None:
            return QSizeF()
        size = renderer.defaultSize()
        return QSizeF(size.width(), size.height())

    def drawObject(
        self,
        painter: QPainter,
        rect: QRectF,
        document: QTextDocument,
        position: int,
        format: QTextFormat,
    ) -> None:
        renderer = _svg_renderer(bytes(format.property(EQUATION_SVG_PROPERTY)))
        if renderer is not None:
            renderer.render(painter, rect)
