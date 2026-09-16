from osa.domain import StructuralModel


class ResultService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def current(self):
        return [result for result in self.model.analysis_results if result.model_revision == self.model.revision]
