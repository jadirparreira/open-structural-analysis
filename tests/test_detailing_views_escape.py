"""Escape in the detailing view manager must leave the main window alive."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from osa.ui.detailing_viewport import DetailingViewViewport
from osa.ui.dialogs import DetailingViewsDialog
from osa.ui.main_window import MainWindow


def test_escape_after_cancelling_custom_plane_only_closes_view_manager(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    quit_requested = []
    viewports_shutdown = []
    on_about_to_quit = lambda: quit_requested.append(True)
    app.aboutToQuit.connect(on_about_to_quit)
    original_shutdown = DetailingViewViewport.shutdown

    def track_shutdown(viewport):
        original_shutdown(viewport)
        viewports_shutdown.append(viewport._is_shutdown)

    monkeypatch.setattr(DetailingViewViewport, "shutdown", track_shutdown)

    def add_plane_from_manager():
        dialog = window.findChild(DetailingViewsDialog)
        assert dialog is not None and dialog.isVisible()
        QTest.mouseClick(dialog.add_detail_plane_button, Qt.MouseButton.LeftButton)

    def escape_from_reopened_manager():
        dialog = window.findChild(DetailingViewsDialog)
        assert dialog is not None and dialog.isVisible()
        assert not window._cancel_placement_action.isEnabled()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)

    try:
        QTimer.singleShot(0, add_plane_from_manager)
        window.open_detailing_views()
        assert window._command_mode == "detail_plane_placement"
        assert window._cancel_placement_action.isEnabled()

        QTimer.singleShot(50, escape_from_reopened_manager)
        window.cancel_member_placement()
        app.processEvents()

        assert window.isVisible()
        assert not quit_requested
        assert not window._detailing_views_dialog_open
        assert window._detailing_views_dialog is None
        assert viewports_shutdown == [True, True]
    finally:
        app.aboutToQuit.disconnect(on_about_to_quit)
        window.scene.plotter.close()
        window.close()
        app.processEvents()
