from osa.domain import StructuralModel
from osa.persistence import ProjectRepository


class ProjectService:
    def __init__(self, model: StructuralModel, repository: ProjectRepository | None = None) -> None:
        self.model = model
        self.repository = repository or ProjectRepository()

    def save(self, path, thumbnail: str | None = None) -> None:
        self.repository.save(self.model, path, thumbnail)

    def load_thumbnail(self, path) -> str | None:
        return self.repository.load_thumbnail(path)

    def load(self, path) -> None:
        self.repository.load(self.model, path)
