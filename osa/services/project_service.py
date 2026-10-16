from osa.domain import StructuralModel
from osa.persistence import ProjectRepository
from osa.transcriptions import ImportOptions
from datetime import datetime, timezone


class ProjectService:
    def __init__(self, model: StructuralModel, repository: ProjectRepository | None = None) -> None:
        self.model = model
        self.repository = repository or ProjectRepository()

    def save(self, path, thumbnail: str | None = None) -> None:
        self.repository.save(self.model, path, thumbnail)

    def load_thumbnail(self, path) -> str | None:
        return self.repository.load_thumbnail(path)

    def load(self, path, *, import_options: ImportOptions | None = None) -> dict | None:
        return self.repository.load(self.model, path, import_options=import_options)

    def confirm_import_review(self) -> None:
        """Registra a confirmação da revisão feita pelo usuário no editor."""
        if self.model.import_metadata.get("requires_review"):
            self.model.import_metadata["requires_review"] = False
            self.model.import_metadata["reviewed_at"] = datetime.now(timezone.utc).isoformat()
            self.model._touch()
