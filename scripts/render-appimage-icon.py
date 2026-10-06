from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main() -> int:
    if len(sys.argv) != 3:
        print(f"uso: {Path(sys.argv[0]).name} ENTRADA.svg SAIDA.png", file=sys.stderr)
        return 2

    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    app = QGuiApplication(sys.argv[:1])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        print(f"SVG inválido: {source}", file=sys.stderr)
        return 1

    image = QImage(QSize(256, 256), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    if not image.save(str(destination), "PNG"):
        print(f"não foi possível salvar o ícone: {destination}", file=sys.stderr)
        return 1

    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
