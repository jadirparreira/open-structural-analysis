from osa.domain import StructuralModel
from osa.persistence import ProjectRepository


class ProjectService:
    def __init__(self, model: StructuralModel, repository: ProjectRepository | None = None) -> None:
        self.model = model
        self.repository = repository or ProjectRepository()

    def save(self, path) -> None:
        self.repository.save(self.model, path)

    def load(self, path) -> None:
        self.repository.load(self.model, path)
