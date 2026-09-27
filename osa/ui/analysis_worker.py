"""Background worker for structural analysis.

The worker owns a private model snapshot and never touches Qt or the live
application model. Results are returned to the GUI thread through signals.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import StructuralModel


class AnalysisWorker(QObject):
    """Run PyNite without blocking the application event loop."""

    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, model: StructuralModel, request: AnalysisRequest) -> None:
        super().__init__()
        self.model = model
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            results = PyniteAdapter().run(
                self.model,
                self.request,
                progress=self.progress.emit,
            )
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
            return
        self.finished.emit(results)
