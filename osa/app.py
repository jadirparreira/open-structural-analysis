"""Composition root da aplicação desktop."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication


def create_application(argv: list[str] | None = None):
    # Import tardio mantém a inspeção do domínio independente do OpenGL/Qt.
    from osa.ui.main_window import APP_STYLESHEET, MainWindow

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Open Structural Analysis")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    return app, window


def run() -> int:
    app, window = create_application()
    window.show()
    return app.exec()
