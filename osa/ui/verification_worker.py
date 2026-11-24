"""Background worker for steel member verifications."""
from PySide6.QtCore import QObject, Signal, Slot

from osa.verification.runner import verify_model


class VerificationWorker(QObject):
    """Run member checks without blocking Qt's application thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, model, member_names: tuple[str, ...] | None = None) -> None:
        super().__init__()
        self.model = model
        self.member_names = member_names

    @Slot()
    def run(self) -> None:
        try:
            result = verify_model(self.model, self.member_names)
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "erro inesperado durante as verificações")
            return
        self.finished.emit(result)
