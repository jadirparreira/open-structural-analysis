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

    def add_action(self, action: Action) -> Action:
        """Cria ou substitui uma ação do mesmo tipo, alvo e ação ativa."""
        existing = next(
            (
                candidate for candidate in self.model.actions.values()
                if (
                    candidate.kind == action.kind
                    and candidate.target == action.target
                    and candidate.load_case == action.load_case
                )
            ),
            None,
        )
        if existing is not None:
            action = Action(existing.name, action.kind, action.target, action.components, action.load_case)
        elif action.name in self.model.actions:
            raise ValueError(f"Já existe uma ação chamada '{action.name}'.")
        self.model.actions[action.name] = action
        self.model._touch()
        return action

    def add_member_distributed_force(
        self, target: str, direction: str, initial: float, final: float, load_case: str,
        reference: str = "global",
    ) -> Action:
        normalized_reference = reference.casefold()
        if normalized_reference not in {"global", "local"}:
            raise ValueError("O sistema de direção deve ser Global ou Local.")
        if normalized_reference == "global" and direction.upper() == "Z":
            self._remove_member_action(target, "member_distributed_force_selfweight_Z", load_case)
        suffix = f"{normalized_reference}_" if normalized_reference == "local" else ""
        kind = f"member_distributed_force_{suffix}{direction.upper()}"
        index = 1
        while f"Carga {index}" in self.model.actions:
            index += 1
        action = Action(
            f"Carga {index}", kind, target,
            (float(initial), float(final)), load_case,
        )
        return self.add_action(action)

    def add_member_selfweight(self, target: str, value: float, load_case: str) -> Action:
        self._remove_member_action(target, "member_distributed_force_Z", load_case)
        self._remove_member_action(target, "member_distributed_force_global_Z", load_case)
        index = 1
        while f"Carga {index}" in self.model.actions:
            index += 1
        return self.add_action(Action(
            f"Carga {index}", "member_distributed_force_selfweight_Z", target,
            (float(value), float(value)), load_case,
        ))

    def replace_action_with_selfweight(
        self, load_case: str, weights: tuple[tuple[str, float], ...],
    ) -> tuple[Action, ...]:
        """Apaga todas as cargas da ação e recria somente os pesos próprios."""
        for name, action in tuple(self.model.actions.items()):
            if action.load_case == load_case:
                del self.model.actions[name]
        created: list[Action] = []
        for target, value in weights:
            index = 1
            while f"Carga {index}" in self.model.actions:
                index += 1
            action = Action(
                f"Carga {index}", "member_distributed_force_selfweight_Z", target,
                (float(value), float(value)), load_case,
            )
            self.model.actions[action.name] = action
            created.append(action)
        self.model._touch()
        return tuple(created)

    def _remove_member_action(self, target: str, kind: str, load_case: str) -> None:
        for name, action in tuple(self.model.actions.items()):
            if action.target == target and action.kind == kind and action.load_case == load_case:
                del self.model.actions[name]

    def add_member_moment(self, target: str, direction: str, value: float, load_case: str) -> Action:
        index = 1
        while f"Carga {index}" in self.model.actions:
            index += 1
        return self.add_action(Action(
            f"Carga {index}", f"member_moment_{direction.upper()}", target, (float(value),), load_case,
        ))

    def add_node_force(self, target: str, direction: str, value: float, load_case: str) -> Action:
        index = 1
        while f"Carga {index}" in self.model.actions:
            index += 1
        return self.add_action(Action(
            f"Carga {index}", f"node_force_{direction.upper()}", target, (float(value),), load_case,
        ))

    def add_node_moment(self, target: str, direction: str, value: float, load_case: str) -> Action:
        index = 1
        while f"Carga {index}" in self.model.actions:
            index += 1
        return self.add_action(Action(
            f"Carga {index}", f"node_moment_{direction.upper()}", target, (float(value),), load_case,
        ))

    @staticmethod
    def templates() -> dict[str, ActionGroup]:
        return {name: _template_group(group) for name, group in ACTION_GROUP_TEMPLATES.items()}

    def selected_group(self) -> ActionGroup | None:
        """Retorna o grupo ativo, incluindo os templates ainda não salvos."""
        name = self.model.selected_action_group
        return self.model.action_groups.get(name) or self.templates().get(name)

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
