"""Utilities for tests that load PDF pages through QtPdf."""

from PySide6.QtCore import QEventLoop, QTimer
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
