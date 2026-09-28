"""Background worker for structural analysis.

The worker owns a private model snapshot and never touches Qt or the live
application model. Results are returned to the GUI thread through signals.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QObject, Signal, Slot

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import StructuralModel


def translate_analysis_error(message: str) -> str:
    """Converte mensagens conhecidas do PyNite para o idioma da aplicação."""
    normalized = " ".join(message.split())
    translations = {
        "The stiffness matrix is singular, which implies rigid body motion. The structure is unstable. Aborting analysis.":
            "A matriz de rigidez é singular, o que indica movimento de corpo rígido. "
            "A estrutura está instável e o processamento foi interrompido.",
        "The stiffness matrix is singular, which indicates that the structure is unstable.":
            "A matriz de rigidez é singular, o que indica que a estrutura está instável.",
        "The structure is unstable. Unable to proceed any further with analysis.":
            "A estrutura está instável. Não é possível continuar o processamento.",
        "Unstable node(s). See console output for details.":
            "Foram identificados nós instáveis. Verifique os apoios, molas e liberações.",
    }
    if normalized in translations:
        return translations[normalized]

    node_match = re.fullmatch(r"Node '([^']+)' does not exist in the model", normalized)
    if node_match:
        return f"O nó '{node_match.group(1)}' não existe no modelo."
    member_match = re.fullmatch(r"Member '([^']+)' does not exist in the model", normalized)
    if member_match:
        return f"O membro '{member_match.group(1)}' não existe no modelo."
    return message


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
            self.failed.emit(translate_analysis_error(str(error)))
            return
        self.finished.emit(results)
