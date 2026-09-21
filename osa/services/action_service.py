from osa.domain import (
    Action,
    ActionDefinition,
    ActionGroup,
    LoadCase,
    LoadCombination,
    StructuralModel,
)

ACTION_GROUP_TEMPLATES = {
    "PP+AP+AV": ActionGroup(
        "PP+AP+AV",
        (ActionDefinition("Peso próprio", "PP"), ActionDefinition("Ação permanente", "AP"), ActionDefinition("Ação variável", "AV")),
    ),
    "PP+AP+AV+4V": ActionGroup(
        "PP+AP+AV+4V",
        (
            ActionDefinition("Peso próprio", "PP"), ActionDefinition("Ação permanente", "AP"), ActionDefinition("Ação variável", "AV"),
            ActionDefinition("Vento 0°", "V0"), ActionDefinition("Vento 90°", "V90"),
            ActionDefinition("Vento 180°", "V180"), ActionDefinition("Vento 270°", "V270"),
        ),
    ),
}


def _template_group(template: ActionGroup) -> ActionGroup:
    return ActionGroup(template.name, tuple(template.actions))


class ActionService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def add_action(self, action: Action) -> None:
        if action.name in self.model.actions:
            raise ValueError(f"Já existe uma ação chamada '{action.name}'.")
        self.model.actions[action.name] = action
        self.model._touch()

    @staticmethod
    def templates() -> dict[str, ActionGroup]:
        return {name: _template_group(group) for name, group in ACTION_GROUP_TEMPLATES.items()}

    def add_action_group(self, group: ActionGroup) -> None:
        self.model.add_action_group(group)

    def select_action_group(self, name: str) -> None:
        self.model.set_selected_action_group(name)

    def set_action_group_alias(self, template_name: str, group_name: str) -> None:
        self.model.set_action_group_alias(template_name, group_name)

    def update_action_group(self, old_name: str, group: ActionGroup) -> None:
        self.model.update_action_group(old_name, group)

    def remove_action_group(self, name: str) -> None:
        self.model.remove_action_group(name)

    def set_load_case(self, load_case: LoadCase) -> None:
        self.model.load_cases[load_case.name] = load_case
        self.model._touch()

    def set_combination(self, combination: LoadCombination) -> None:
        self.model.load_combinations[combination.name] = combination
        self.model._touch()
