"""Startup must show only its splash until the application is ready."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from osa.app import create_application
from osa.startup_splash import StartupSplash


class WindowShowRecorder(QObject):
    def __init__(self):
        super().__init__()
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and (
            obj.objectName() == "unitValueBox"
            or isinstance(obj, QLabel) and obj.text() in {"d", "bf", "tw", "tf", "b", "t", "c", "D", "De", "Di", "h"}
        ):
            self.windows.append(obj)
        return False


def test_startup_never_exposes_section_fields_as_desktop_windows(monkeypatch):
    from osa.ui import home
    from osa.ui.section_panel import SECTION_PARAMETRIC_SPECS

    monkeypatch.setattr(home.RecentProjectStore, "items", lambda self: [])
    app = QApplication.instance() or QApplication([])
    recorder = WindowShowRecorder()
    app.installEventFilter(recorder)
    handover_windows = []

    def bootloader_close():
        handover_windows.extend(widget for widget in app.topLevelWidgets() if widget.isVisible())

    window = None
    try:
        app, window = create_application(show_splash=True, on_splash_shown=bootloader_close)
        geometry_widgets = [
            widget
            for label, box, _field in window.section_panel._geometry_widgets
            for widget in (label, box)
        ]
        assert not set(geometry_widgets).intersection(handover_windows)
        assert not recorder.windows
        assert not window.isVisible()

        # Newly used fields must also be parented before being shown when
        # changing section families after startup.
        for family in SECTION_PARAMETRIC_SPECS:
            window.section_panel._set_geometry_layout(family)
        assert not recorder.windows
    finally:
        app.removeEventFilter(recorder)
        if window is not None:
            window._startup_splash.close()
            window.close()


def test_splash_waits_two_seconds_before_showing_main_window():
    app = QApplication.instance() or QApplication([])
    splash = StartupSplash()
    window = QWidget()
    try:
        splash.show()
        app.processEvents()
        assert splash.isVisible()
        assert not window.isVisible()
        splash.finish(window)
        assert splash._visible_timer.elapsed() >= StartupSplash.MINIMUM_VISIBLE_MS
        assert window.isVisible()
        assert not splash.isVisible()
    finally:
        splash.close()
        window.close()
