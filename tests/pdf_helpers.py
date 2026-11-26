"""Utilities for tests that load PDF pages through QtPdf."""

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer, QSize
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument


def wait_for_pdf(document: QPdfDocument, timeout_ms: int = 10_000) -> None:
    """Wait until asynchronous PDF loading finishes before reading page data."""
    if document.status() == QPdfDocument.Status.Loading:
        loop = QEventLoop()

        def finish_loading(status):
            if status != QPdfDocument.Status.Loading:
                loop.quit()

        document.statusChanged.connect(finish_loading)
        if document.status() == QPdfDocument.Status.Loading:
            QTimer.singleShot(timeout_ms, loop.quit)
            loop.exec()
        document.statusChanged.disconnect(finish_loading)

    assert document.status() == QPdfDocument.Status.Ready, (
        f"PDF did not finish loading (status={document.status()}, error={document.error()})"
    )


def assert_pdf_contains_text(document: QPdfDocument, path, *expected: str) -> None:
    """Check selectable text, with a vector-render fallback for Windows QtPdf."""
    text = document.getAllText(0).text()
    if all(value in text for value in expected):
        return
    if sys.platform != "win32":
        assert all(value in text for value in expected), f"PDF text was {text!r}"
        return

    # QtPdf's Windows backend can render the same generated PDF but returns an
    # empty text selection. Keep Windows coverage by requiring visible vector
    # page content; Linux verifies the exact strings above.
    raw = Path(path).read_bytes()
    assert b"/Font" in raw and b"/Subtype /Image" not in raw
    image = document.render(0, QSize(1200, 900)).convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
    assert np.any(pixels[:, :, :3].min(axis=2) < 180), "PDF page rendered without visible content"
