from osa.analysis import AnalysisEngine, AnalysisRequest
from osa.domain import StructuralModel


class AnalysisService:
    def __init__(self, model: StructuralModel, engine: AnalysisEngine) -> None:
        self.model = model
        self.engine = engine

    def run(self, request: AnalysisRequest):
        results = self.engine.run(self.model, request)
        self.model.analysis_results = list(results)
        return results
