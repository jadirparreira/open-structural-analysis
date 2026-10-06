"""Composition root da aplicação desktop."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def create_application(argv: list[str] | None = None):
    # Import tardio mantém a inspeção do domínio independente do OpenGL/Qt.
    from osa.ui.main_window import APP_STYLESHEET, MainWindow

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    resource_root = Path(__file__).resolve().parent / "resources" / "icons"
    application_icon = QIcon(str(resource_root / "openstructuralanalysis.svg"))

    # O nome interno identifica a aplicação para o ambiente Linux; o nome de
    # exibição permanece legível na janela, no menu e na barra de tarefas.
    app.setApplicationName("openstructuralanalysis")
    app.setApplicationDisplayName("Open Structural Analysis")
    app.setDesktopFileName("openstructuralanalysis")
    app.setWindowIcon(application_icon)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.setWindowIcon(application_icon)
    return app, window


def run() -> int:
    app, window = create_application()
    window.show()
    return app.exec()
