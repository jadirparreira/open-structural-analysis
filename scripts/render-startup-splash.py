"""Rasterize vector artwork for the PNG-only PyInstaller bootloader."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> int:
    if len(sys.argv) != 3:
        print(f"uso: {Path(sys.argv[0]).name} ENTRADA.svg SAIDA.png", file=sys.stderr)
        return 2

    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    app = QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        print(f"SVG inválido: {source}", file=sys.stderr)
        return 1

    size = renderer.defaultSize()
    # Supersampling keeps thin strokes and text clean in the earliest frame.
    # The Qt splash paints the SVG directly once Qt is available.
    image = QImage(size * 4, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(destination), "PNG"):
        print(f"não foi possível salvar o splash: {destination}", file=sys.stderr)
        return 1
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
