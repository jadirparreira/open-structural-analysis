"""Background model verification runner."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import StructuralModel

from .elements import verification_elements
from .restraints import AnalyticalRestraints
from .w_rolled import verify_w_element


class VerificationWorker(QObject):
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, model: StructuralModel) -> None:
        super().__init__()
        self.model = model

    @Slot()
    def run(self) -> None:
        elements = verification_elements(self.model)
        try:
            results = PyniteAdapter().run(self.model, AnalysisRequest())
        except Exception as error:  # noqa: BLE001
            message = " ".join(str(error).split())
            if "stiffness matrix is singular" in message.lower() or "unstable" in message.lower():
                message = "A estrutura está instável ou possui movimento de corpo rígido."
            evaluations = {}
            for element in elements:
                evaluation = {"status": "not_checked", "detail": f"análise indisponível: {message}"}
                evaluations[element.key] = evaluation
            self.finished.emit([], evaluations)
            return
        try:
            evaluations = {}
            restraints = AnalyticalRestraints(self.model)
            for element in elements:
                evaluation = verify_w_element(element, self.model, results, restraint_analyzer=restraints)
                evaluations[element.key] = evaluation
        except Exception as error:  # noqa: BLE001
            self.failed.emit("Falha interna durante a verificação: " + " ".join(str(error).split()))
            return
        self.finished.emit(results, evaluations)
