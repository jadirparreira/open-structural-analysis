"""Contratos que impedem o restante da aplicação de depender do PyNite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from osa.domain import AnalysisResult, StructuralModel


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    load_combinations: tuple[str, ...] = ()
    second_order: bool | None = None
    stiffness_factor: float | None = None
    warping: bool | None = None

    def __post_init__(self):
        if self.warping is not None and type(self.warping) is not bool:
            raise ValueError("A opção de empenamento deve ser booleana.")
        if self.second_order is not None and type(self.second_order) is not bool:
            raise ValueError("A opção de segunda ordem deve ser booleana.")
        if self.stiffness_factor is not None and (not isfinite(self.stiffness_factor) or not 0 < self.stiffness_factor <= 1):
            raise ValueError("O fator de rigidez EA/EI deve ser positivo e no máximo 1.")


class AnalysisEngine(Protocol):
    def run(
        self,
        model: StructuralModel,
        request: AnalysisRequest,
        progress: Callable[[str], None] | None = None,
    ) -> list[AnalysisResult]: ...
