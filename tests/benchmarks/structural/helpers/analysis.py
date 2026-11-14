"""Analysis execution helpers."""

from __future__ import annotations

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import AnalysisResult
from osa.model import StructuralModel


def analyze(model: StructuralModel) -> AnalysisResult:
    """Run one implicit unit-factor combination and return its result."""
    results = PyniteAdapter().run(model, AnalysisRequest())
    assert len(results) == 1
    return results[0]
