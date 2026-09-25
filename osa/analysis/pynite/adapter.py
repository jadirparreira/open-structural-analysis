"""Fachada única para a API do PyNite."""

from collections.abc import Callable

from osa.analysis.contracts import AnalysisRequest
from osa.domain import StructuralModel

from .combination_builder import CombinationBuilder
from .load_case_builder import LoadCaseBuilder
from .model_builder import ModelBuilder
from .result_mapper import ResultMapper


class PyniteAdapter:
    def __init__(
        self,
        builder: ModelBuilder | None = None,
        mapper: ResultMapper | None = None,
        load_cases: LoadCaseBuilder | None = None,
        combinations: CombinationBuilder | None = None,
    ) -> None:
        self.builder = builder or ModelBuilder()
        self.mapper = mapper or ResultMapper()
        self.load_cases = load_cases or LoadCaseBuilder()
        self.combinations = combinations or CombinationBuilder()

    def run(
        self,
        model: StructuralModel,
        request: AnalysisRequest,
        progress: Callable[[str], None] | None = None,
    ):
        self._notify(progress, "model")
        target = self.builder.build(model)
        self._notify(progress, "loads")
        load_cases = self.load_cases.apply(target, model)
        self._notify(progress, "combinations")
        available_references = self.combinations.apply(target, model, load_cases)
        self._notify(progress, "solve")
        target.analyze()
        references = request.load_combinations or available_references
        unknown = set(references) - set(available_references)
        if unknown:
            raise ValueError(f"Combinações não encontradas para análise: {', '.join(sorted(unknown))}.")
        self._notify(progress, "results")
        return [self.mapper.map(target, model.revision, reference) for reference in references]

    @staticmethod
    def _notify(progress: Callable[[str], None] | None, stage: str) -> None:
        if progress is not None:
            progress(stage)
