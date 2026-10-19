"""Composition root da aplicação desktop."""

from __future__ import annotations

import os
import sys
from time import monotonic
from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from osa.startup_splash import StartupSplash

_STARTUP_STARTED_AT = monotonic()
_MINIMUM_SPLASH_MS = 2000


def create_application(argv: list[str] | None = None, *, show_splash: bool = False):
    # O OSA usa os diálogos e widgets nativos do Qt e não precisa do XDG
    # Desktop Portal. Em algumas sessões KDE/Wayland o registro do app no
    # portal falha com "Connection already associated with an application ID".
    if sys.platform.startswith("linux"):
        _remove_legacy_gtk_accessibility_module()
        os.environ.setdefault("QT_NO_XDG_DESKTOP_PORTAL", "1")
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

    splash = StartupSplash() if show_splash else None
    if splash is not None:
        splash.show()
        app.processEvents()
    try:
        if sys.platform.startswith("linux"):
            # VTK 9.7 can emit four benign framebuffer WARNs when Qt/Wayland
            # exposes the generic OpenGL window before its color attachments
            # are available. Keep actual VTK errors visible.
            from vtkmodules.vtkCommonCore import vtkLogger

            vtkLogger.SetStderrVerbosity(vtkLogger.VERBOSITY_ERROR)

        # Delay the heavyweight UI imports until after the splash is painted.
        from osa.ui.main_window import APP_STYLESHEET, MainWindow

        app.setStyleSheet(APP_STYLESHEET)
        window = MainWindow()
        window.setWindowIcon(application_icon)
        if splash is not None:
            window._startup_splash = splash
        return app, window
    except Exception as error:
        if splash is not None:
            splash.close()
            QMessageBox.critical(
                None,
                "Falha ao iniciar o Open Structural Analysis",
                str(error),
            )
        raise


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
    bootloader_splash = _get_bootloader_splash()
    try:
        app, window = create_application(show_splash=bootloader_splash is None)
    except Exception as error:
        if bootloader_splash is not None:
            bootloader_splash.close()
            QMessageBox.critical(
                None,
                "Falha ao iniciar o Open Structural Analysis",
                str(error),
            )
        raise

    if bootloader_splash is not None:
        window.show()
        app.processEvents()
        remaining_ms = max(
            0,
            _MINIMUM_SPLASH_MS - int((monotonic() - _STARTUP_STARTED_AT) * 1000),
        )
        if remaining_ms:
            wait_loop = QEventLoop()
            QTimer.singleShot(remaining_ms, wait_loop.quit)
            wait_loop.exec()
        bootloader_splash.close()
        window.raise_()
        window.activateWindow()
        return app.exec()

    splash = getattr(window, "_startup_splash", None)
    if splash is None:
        window.show()
    else:
        splash.finish(window)
    return app.exec()


def _get_bootloader_splash():
    """Return PyInstaller's pre-Python splash controller when bundled."""
    try:
        import pyi_splash
    except ImportError:
        return None
    return pyi_splash
