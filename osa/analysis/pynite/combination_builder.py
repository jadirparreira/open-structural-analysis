"""Tradução das combinações de carga para PyNite."""

from __future__ import annotations

from osa.domain import StructuralModel
from osa.services.action_service import ActionService


class CombinationBuilder:
    def apply(self, target, model: StructuralModel, load_cases: tuple[str, ...]) -> tuple[str, ...]:
        if not model.load_combinations:
            # O comando pode criar as ações antes de a interface inicializar
            # as combinações padrão. Nesse caso, mantém-se uma combinação
            # explícita e rastreável com todos os casos unitários.
            target.add_load_combo("Combo 1", {name: 1.0 for name in load_cases})
            return ("Combo 1",)

        for combination in model.load_combinations.values():
            target.add_load_combo(combination.name, self._factors_for(combination, model))
        return tuple(model.load_combinations)

    @staticmethod
    def _factors_for(combination, model: StructuralModel) -> dict[str, float]:
        group = model.action_groups.get(combination.action_group or "")
        if group is None:
            group = ActionService(model).selected_group()
        names_by_abbreviation = {
            action.abbreviation: action.name
            for action in (group.actions if group is not None else ())
        }
        active = set(combination.active_actions or names_by_abbreviation)
        gamma = dict(combination.factors)
        psi_0 = dict(combination.factors_2)
        psi_service = dict(combination.factors_3)
        factors: dict[str, float] = {}
        for abbreviation in active:
            load_case = names_by_abbreviation.get(abbreviation, abbreviation)
            factors[load_case] = (
                gamma.get(abbreviation, 1.0)
                * psi_0.get(abbreviation, 1.0)
                * psi_service.get(abbreviation, 1.0)
            )
        return factors
