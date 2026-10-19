"""Render the startup splash SVG at its native size for the PyInstaller bootloader."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> int:
    if len(sys.argv) != 3:
        print(f"uso: {Path(sys.argv[0]).name} ENTRADA.svg SAIDA.png", file=sys.stderr)
        return 2

    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        print(f"SVG inválido: {source}", file=sys.stderr)
        return 1

    app = QGuiApplication(sys.argv[:1])
    size = renderer.defaultSize()
    image = QImage(size, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(destination), "PNG"):
        print(f"não foi possível salvar o splash: {destination}", file=sys.stderr)
        return 1
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
