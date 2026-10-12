"""Composition root da aplicação desktop."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def create_application(argv: list[str] | None = None):
    # O OSA usa os diálogos e widgets nativos do Qt e não precisa do XDG
    # Desktop Portal. Em algumas sessões KDE/Wayland o registro do app no
    # portal falha com "Connection already associated with an application ID".
    if sys.platform.startswith("linux"):
        _remove_legacy_gtk_accessibility_module()
        os.environ.setdefault("QT_NO_XDG_DESKTOP_PORTAL", "1")
        # VTK 9.7 can emit four benign framebuffer WARNs when Qt/Wayland
        # exposes the generic OpenGL window before its color attachments are
        # available. Keep actual VTK errors visible, but avoid polluting the
        # terminal with this integration warning.
        from vtkmodules.vtkCommonCore import vtkLogger

        vtkLogger.SetStderrVerbosity(vtkLogger.VERBOSITY_ERROR)

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


def _remove_legacy_gtk_accessibility_module() -> None:
    """Avoid GTK's warning for the obsolete atk-bridge module."""
    modules = [
        module
        for module in os.environ.get("GTK_MODULES", "").split(":")
        if module and module != "atk-bridge"
    ]
    if modules:
        os.environ["GTK_MODULES"] = ":".join(modules)
    else:
        os.environ.pop("GTK_MODULES", None)


def run() -> int:
    app, window = create_application()
    window.show()
    return app.exec()
