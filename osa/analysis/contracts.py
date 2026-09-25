"""Contratos que impedem o restante da aplicação de depender do PyNite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from osa.domain import AnalysisResult, StructuralModel


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    load_combinations: tuple[str, ...] = ()


class AnalysisEngine(Protocol):
    def run(
        self,
        model: StructuralModel,
        request: AnalysisRequest,
        progress: Callable[[str], None] | None = None,
    ) -> list[AnalysisResult]: ...
