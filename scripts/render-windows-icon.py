"""Renderiza o SVG oficial em um ICO multi-resolução para o Windows."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer, "PNG"):
            raise RuntimeError(f"Não foi possível renderizar o ícone em {size}px.")
        return bytes(buffer.data())
    finally:
        buffer.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(args.source))
    if not renderer.isValid():
        raise SystemExit(f"SVG inválido: {args.source}")

    rendered = [
        Image.open(BytesIO(render_png(renderer, size))).convert("RGBA")
        for size in ICON_SIZES
    ]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    rendered[-1].save(
        args.destination,
        format="ICO",
        sizes=[(size, size) for size in ICON_SIZES],
    )


if __name__ == "__main__":
    main()
