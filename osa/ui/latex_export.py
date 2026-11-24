"""Execução das exportações LaTeX/PDF sem travar a interface."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

PDF_FILTER = "PDF (LaTeX) (*.pdf)"
TEX_FILTER = "Projeto LaTeX (*.tex)"
DOCX_FILTER = "Documento Word (*.docx)"
_FILTER_SUFFIX = {PDF_FILTER: ".pdf", TEX_FILTER: ".tex", DOCX_FILTER: ".docx"}


def destination_with_suffix(filename: str, selected_filter: str, allowed: tuple[str, ...]) -> Path:
    """Respeita a extensão digitada; sem extensão válida, usa a do filtro escolhido."""
    path = Path(filename)
    if path.suffix.lower() in allowed:
        return path
    return path.with_name(path.name + _FILTER_SUFFIX.get(selected_filter, allowed[0]))


class _ExportWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, function: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self._function = function

    def run(self) -> None:
        try:
            self.finished.emit(self._function(self.progress.emit))
        except Exception as exc:  # noqa: BLE001 - a mensagem volta para a interface.
            self.failed.emit(str(exc) or exc.__class__.__name__)


def run_with_progress(parent: QWidget, title: str, function: Callable[[Callable[[str], None]], object]):
    """Roda ``function(progress)`` em outra thread, com diálogo de progresso.

    Retorna o resultado da função; exceções viram ``RuntimeError`` na thread da interface.
    """
    dialog = QProgressDialog(title, None, 0, 0, parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(300)
    dialog.setAutoClose(False)
    thread = QThread(parent)
    worker = _ExportWorker(function)
    worker.moveToThread(thread)
    outcome: dict[str, object] = {}
    loop = QEventLoop()
    worker.progress.connect(dialog.setLabelText)
    worker.finished.connect(lambda value: outcome.setdefault("value", value))
    worker.failed.connect(lambda message: outcome.setdefault("error", message))
    worker.finished.connect(loop.quit)
    worker.failed.connect(loop.quit)
    thread.started.connect(worker.run)
    thread.start()
    loop.exec()
    thread.quit()
    thread.wait()
    worker.deleteLater()
    thread.deleteLater()
    dialog.close()
    if "error" in outcome:
        raise RuntimeError(str(outcome["error"]))
    return outcome.get("value")


def warn_export_problem(parent: QWidget, title: str, export) -> None:
    """Explica por que o PDF não saiu e onde ficou o projeto LaTeX."""
    QMessageBox.warning(
        parent,
        title,
        "O projeto LaTeX foi salvo, mas o PDF não foi gerado.\n\n"
        f"Arquivo .tex: {export.tex_path}\n\n{export.error}",
    )
