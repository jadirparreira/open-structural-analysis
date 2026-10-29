"""Verification worker results must be applied on the GUI thread."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from osa.ui import main_window as main_window_module
from osa.ui.main_window import MainWindow


class _ImmediateVerificationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, _model, _member_names=None):
        super().__init__()

    @Slot()
    def run(self):
        self.finished.emit({
            "results": {},
            "summary": {
                "total": 0,
                "with_routine": 0,
                "without_routine": 0,
                "approved": 0,
                "rejected": 0,
                "unverified": 0,
            },
        })


def test_verification_worker_completion_updates_ui_on_gui_thread(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(main_window_module, "VerificationWorker", _ImmediateVerificationWorker)
    window = MainWindow()
    window.model.analysis_results = [SimpleNamespace(model_revision=window.model.revision)]
    callback_threads = []
    monkeypatch.setattr(
        window,
        "refresh_scene",
        lambda **_kwargs: callback_threads.append(QThread.currentThread()),
    )
    monkeypatch.setattr(
        window.scene,
        "refresh_utilization_thermometer",
        lambda: callback_threads.append(QThread.currentThread()),
    )
    monkeypatch.setattr(
        window,
        "refresh_selected_property_panel",
        lambda _section: callback_threads.append(QThread.currentThread()),
    )
    monkeypatch.setattr(
        window.history,
        "append",
        lambda _message: callback_threads.append(QThread.currentThread()),
    )
    original_succeed = window.verification_panel.succeed

    def record_succeed(summary):
        callback_threads.append(QThread.currentThread())
        original_succeed(summary)

    monkeypatch.setattr(window.verification_panel, "succeed", record_succeed)

    window._start_verification()

    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(
        lambda: loop.quit() if window._verification_thread is None else None
    )
    poll.start()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    poll.stop()
    timeout.stop()

    try:
        assert window._verification_thread is None
        assert callback_threads
        assert all(thread == app.thread() for thread in callback_threads)
    finally:
        window.close()
        app.processEvents()
