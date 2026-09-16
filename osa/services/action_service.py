from osa.domain import Action, LoadCase, LoadCombination, StructuralModel


class ActionService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def add_action(self, action: Action) -> None:
        if action.name in self.model.actions:
            raise ValueError(f"Já existe uma ação chamada '{action.name}'.")
        self.model.actions[action.name] = action
        self.model._touch()

    def set_load_case(self, load_case: LoadCase) -> None:
        self.model.load_cases[load_case.name] = load_case
        self.model._touch()

    def set_combination(self, combination: LoadCombination) -> None:
        self.model.load_combinations[combination.name] = combination
        self.model._touch()
