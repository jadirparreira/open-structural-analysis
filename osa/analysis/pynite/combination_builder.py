"""Tradução futura das combinações de carga para PyNite."""


class CombinationBuilder:
    def apply(self, target, model) -> None:
        for combination in model.load_combinations.values():
            target.add_load_combo(combination.name, dict(combination.factors))
