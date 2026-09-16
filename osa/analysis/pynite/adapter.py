"""Fachada única para a API do PyNite."""

from osa.analysis.contracts import AnalysisRequest
from osa.domain import StructuralModel

from .model_builder import ModelBuilder
from .result_mapper import ResultMapper


class PyniteAdapter:
    def __init__(self, builder: ModelBuilder | None = None, mapper: ResultMapper | None = None) -> None:
        self.builder = builder or ModelBuilder()
        self.mapper = mapper or ResultMapper()

    def run(self, model: StructuralModel, request: AnalysisRequest):
        target = self.builder.build(model)
        target.analyze()
        references = request.load_combinations or ("Combo 1",)
        return [self.mapper.map(target, model.revision, reference) for reference in references]
