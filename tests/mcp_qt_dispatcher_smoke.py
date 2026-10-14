"""Run GUI-thread MCP checks in a fresh process to isolate VTK's Qt state."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from osa.mcp import McpApplication
from osa.model import StructuralModel
from osa.services import ModelService
from osa.ui.mcp_dispatcher import McpQtDispatcher


def pump_events(app: QApplication, worker: threading.Thread) -> None:
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    worker.join(timeout=0.1)
    assert not worker.is_alive()


def run() -> None:
    app = QApplication([])

    dispatcher = McpQtDispatcher()
    model = StructuralModel()
    observed_threads = []
    application = McpApplication(
        model, ModelService(model),
        on_model_changed=lambda: observed_threads.append(QThread.currentThread()),
        execute_on_model_thread=dispatcher.call,
    )
    worker = threading.Thread(target=lambda: application.create_node(1, 2, 3))
    worker.start()
    pump_events(app, worker)
    assert list(model.nodes) == ["N1"]
    assert observed_threads == [app.thread()]

    errors = []

    def queued_edit():
        try:
            application.create_node(4, 5, 6)
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=queued_edit)
    worker.start()
    deadline = time.monotonic() + 2
    while not dispatcher._pending and time.monotonic() < deadline:
        time.sleep(0.002)
    assert dispatcher._pending
    dispatcher.suspend()
    pump_events(app, worker)
    assert errors == ["O servidor MCP foi desativado."]
    assert list(model.nodes) == ["N1"]

    dispatcher.resume()
    entered = threading.Event()
    release = threading.Event()
    analysis_errors = []

    class SlowEngine:
        def run(self, snapshot, request):
            entered.set()
            assert release.wait(timeout=5)
            return []

    application._analysis_engine = SlowEngine()

    def analyze():
        try:
            application.run_analysis()
        except ValueError as error:
            analysis_errors.append(str(error))

    worker = threading.Thread(target=analyze)
    worker.start()
    deadline = time.monotonic() + 5
    while not entered.is_set() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert entered.is_set()
    application.create_node(7, 8, 9)
    release.set()
    pump_events(app, worker)
    assert analysis_errors == ["O modelo foi alterado durante a análise. Execute o processamento novamente."]
    assert not model.analysis_results


if __name__ == "__main__":
    run()
