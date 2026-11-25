"""Portable sheet images using the existing text frame storage and handles."""
import base64

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImageReader


def image_annotation(filename):
    reader = QImageReader(str(filename))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString() or "Não foi possível abrir a imagem.")
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("Não foi possível preparar a imagem.")
    # Embed the pixels so moving/deleting the original file cannot break a
    # saved project or its PDF. PNG also preserves logo transparency.
    width = min(80., max(20., image.width() * 25.4 / 96))
    return dict(kind="image", image_data=base64.b64encode(bytes(buffer.data())).decode("ascii"),
                width_mm=width, height_mm=width*image.height()/image.width())
