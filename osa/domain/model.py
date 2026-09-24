"""Agregado principal do modelo estrutural."""

from __future__ import annotations

import math
from dataclasses import replace

from .entities import (
    Action, ActionDefinition, ActionGroup, AnalysisResult, Bar, LoadCase, LoadCombination, Node, ReferenceAxis,
    RigidBar,
)
from .errors import DuplicateMemberError, DuplicateNodeCoordinatesError, EntityNotFoundError


class StructuralModel:
    """Mantém as entidades e garante invariantes em qualquer fluxo de entrada."""

    coordinate_tolerance = 1e-9

    def __init__(self, *, materials=None, material_types=None, sections=None) -> None:
        self.nodes: dict[str, Node] = {}
        self.bars: dict[str, Bar] = {}
        self.rigid_bars: dict[str, RigidBar] = {}
        self.axes: dict[str, tuple[ReferenceAxis, ...]] = {axis: () for axis in ("X", "Y", "Z")}
        self.materials = {name: tuple(values) for name, values in (materials or {}).items()}
        self.material_types = dict(material_types or {})
        self.sections = {kind: list(items) for kind, items in (sections or {}).items()}
        self.actions: dict[str, Action] = {}
        self.action_groups: dict[str, ActionGroup] = {}
        self.action_group_aliases: dict[str, str] = {}
        self.selected_action_group = "PP+AP+AV"
        self.load_cases: dict[str, LoadCase] = {}
        self.load_combinations: dict[str, LoadCombination] = {}
        self.combination_groups_initialized: set[str] = set()
        self.analysis_results: list[AnalysisResult] = []
        self.revision = 0

    @property
    def members(self) -> dict[str, Bar]:
        return self.bars

    def _touch(self) -> None:
        self.revision += 1
        self.analysis_results.clear()

    @staticmethod
    def _coordinates(x: float, y: float, z: float) -> tuple[float, float, float]:
        values = float(x), float(y), float(z)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("As coordenadas devem ser números finitos.")
        return values

    def _ensure_unique_coordinates(self, coordinates: tuple[float, float, float], ignore: str = "") -> None:
        for node in self.nodes.values():
            if node.name != ignore and all(
                math.isclose(a, b, abs_tol=self.coordinate_tolerance, rel_tol=0.0)
                for a, b in zip(coordinates, (node.x, node.y, node.z))
            ):
                raise DuplicateNodeCoordinatesError("Já existe um nó nessa coordenada.")

    def add_node(self, name: str, x: float, y: float, z: float) -> Node:
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome do nó.")
        if name in self.nodes:
            raise ValueError(f"Já existe um nó chamado '{name}'.")
        coordinates = self._coordinates(x, y, z)
        self._ensure_unique_coordinates(coordinates)
        node = Node(name, *coordinates)
        self.nodes[name] = node
        self._touch()
        return node

    def update_node(self, name: str, x: float, y: float, z: float) -> Node:
        if name not in self.nodes:
            raise EntityNotFoundError(f"Nó '{name}' não encontrado.")
        coordinates = self._coordinates(x, y, z)
        self._ensure_unique_coordinates(coordinates, ignore=name)
        node = replace(self.nodes[name], x=coordinates[0], y=coordinates[1], z=coordinates[2])
        self.nodes[name] = node
        self._touch()
        return node

    def remove_node(self, name: str) -> None:
        if name not in self.nodes:
            return
        connected = [bar.name for bar in self.bars.values() if name in (bar.start_node, bar.end_node)]
        connected.extend(
            rigid.name for rigid in self.rigid_bars.values()
            if name in (rigid.start_node, rigid.end_node)
        )
        if connected:
            raise ValueError(f"O nó '{name}' pertence às barras: {', '.join(connected)}. Remova-as primeiro.")
        del self.nodes[name]
        self._touch()

    def update_node_supports(self, name: str, supports: tuple[bool, ...]) -> Node:
        if name not in self.nodes:
            raise EntityNotFoundError(f"Nó '{name}' não encontrado.")
        if len(supports) != 6:
            raise ValueError("Informe seis restrições para o nó.")
        node = replace(self.nodes[name], supports=tuple(bool(value) for value in supports))
        self.nodes[name] = node
        self._touch()
        return node

    def set_reference_axes(self, axes: dict[str, tuple[ReferenceAxis, ...]]) -> None:
        """Replace the named reference axes after validating their per-direction identity."""
        normalized: dict[str, tuple[ReferenceAxis, ...]] = {}
        for direction in ("X", "Y", "Z"):
            labels: set[str] = set()
            values: set[float] = set()
            entries: list[ReferenceAxis] = []
            for axis in axes.get(direction, ()):
                label = str(axis.label).strip().upper()
                value = round(float(axis.value), 3)
                if not label or not label.isascii() or not label.isalnum():
                    raise ValueError("O rótulo do eixo deve conter somente letras e números.")
                if not math.isfinite(value):
                    raise ValueError("O valor do eixo deve ser um número finito.")
                if label in labels or value in values:
                    raise ValueError("Não pode haver rótulos ou valores repetidos no mesmo eixo.")
                labels.add(label)
                values.add(value)
                entries.append(ReferenceAxis(label, value))
            normalized[direction] = tuple(entries)
        if normalized != self.axes:
            self.axes = normalized
            self._touch()

    def _validate_member_nodes(self, start_node: str, end_node: str, ignore: str = "") -> None:
        if start_node.casefold() == end_node.casefold():
            raise ValueError("Uma barra deve conectar dois nós diferentes.")
        if start_node not in self.nodes or end_node not in self.nodes:
            raise ValueError("Selecione dois nós válidos.")
        pair = frozenset((start_node, end_node))
        if any(bar.name != ignore and frozenset((bar.start_node, bar.end_node)) == pair for bar in self.bars.values()):
            raise DuplicateMemberError("Já existe um membro entre esses nós.")

    def add_bar(self, name: str, start_node: str, end_node: str) -> Bar:
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome da barra.")
        if name in self.bars:
            raise ValueError(f"Já existe uma barra chamada '{name}'.")
        self._validate_member_nodes(start_node, end_node)
        bar = Bar(name, start_node, end_node)
        self.bars[name] = bar
        self._touch()
        return bar

    add_member = add_bar

    def update_bar(self, name: str, start_node: str, end_node: str) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrada.")
        self._validate_member_nodes(start_node, end_node, ignore=name)
        bar = replace(self.bars[name], start_node=start_node, end_node=end_node)
        self.bars[name] = bar
        self._touch()
        return bar

    update_member = update_bar

    def remove_bar(self, name: str) -> None:
        if self.bars.pop(name, None) is not None:
            self._touch()

    remove_member = remove_bar

    def _validate_rigid_bar_nodes(self, start_node: str, end_node: str, ignore: str = "") -> None:
        if start_node.casefold() == end_node.casefold():
            raise ValueError("Uma barra rígida deve conectar dois nós diferentes.")
        if start_node not in self.nodes or end_node not in self.nodes:
            raise ValueError("Selecione dois nós válidos.")
        pair = frozenset((start_node, end_node))
        if any(
            rigid.name != ignore
            and frozenset((rigid.start_node, rigid.end_node)) == pair
            for rigid in self.rigid_bars.values()
        ):
            raise ValueError("Já existe uma barra rígida entre esses nós.")

    def add_rigid_bar(self, start_node: str, end_node: str) -> RigidBar:
        self._validate_rigid_bar_nodes(start_node, end_node)
        name = f"{start_node}-{end_node}"
        if name in self.rigid_bars:
            raise ValueError(f"Já existe uma barra rígida chamada '{name}'.")
        rigid = RigidBar(name, start_node, end_node)
        self.rigid_bars[name] = rigid
        self._touch()
        return rigid

    def update_rigid_bar(self, name: str, start_node: str, end_node: str) -> RigidBar:
        if name not in self.rigid_bars:
            raise EntityNotFoundError(f"Barra rígida '{name}' não encontrada.")
        self._validate_rigid_bar_nodes(start_node, end_node, ignore=name)
        new_name = f"{start_node}-{end_node}"
        if new_name != name and new_name in self.rigid_bars:
            raise ValueError(f"Já existe uma barra rígida chamada '{new_name}'.")
        rigid = RigidBar(new_name, start_node, end_node)
        del self.rigid_bars[name]
        self.rigid_bars[new_name] = rigid
        self._touch()
        return rigid

    def remove_rigid_bar(self, name: str) -> None:
        if self.rigid_bars.pop(name, None) is not None:
            self._touch()

    def update_bar_material(self, name: str, material: str, values: tuple[float, float, float, float]) -> Bar:
        self.bars[name] = replace(self.bars[name], material=material, material_values=tuple(values))
        self._touch()
        return self.bars[name]

    def update_bar_section(self, name: str, section: str) -> Bar:
        self.bars[name] = replace(self.bars[name], section=section, profile="", section_geometry=())
        self._touch()
        return self.bars[name]

    def update_member_profile(self, name: str, profile: str, geometry: dict[str, float]) -> Bar:
        self.bars[name] = replace(
            self.bars[name], profile=profile, section_geometry=tuple((key, float(value)) for key, value in geometry.items())
        )
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_rotation(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("A rotação do membro deve ser um número inteiro.")  # noqa: TRY004
        return value % 360

    def update_member_rotation(self, name: str, rotation: int) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Membro '{name}' não encontrado.")
        rotation = self._member_rotation(rotation)
        self.bars[name] = replace(self.bars[name], rotation=rotation)
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_releases(values: tuple[bool, ...]) -> tuple[bool, ...]:
        if len(values) != 12:
            raise ValueError("As vinculações do membro devem possuir doze graus de liberdade.")
        return tuple(bool(value) for value in values)

    def update_member_releases(self, name: str, releases: tuple[bool, ...]) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Membro '{name}' não encontrado.")
        self.bars[name] = replace(self.bars[name], releases=self._member_releases(releases))
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_color(value: str) -> str:
        if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
            raise ValueError("A cor do membro deve estar no formato hexadecimal #RRGGBB.")
        try:
            int(value[1:], 16)
        except ValueError as error:
            raise ValueError("A cor do membro deve estar no formato hexadecimal #RRGGBB.") from error
        return value.lower()

    def update_member_color(self, name: str, color: str) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Membro '{name}' não encontrado.")
        self.bars[name] = replace(self.bars[name], color=self._member_color(color))
        self._touch()
        return self.bars[name]

    @staticmethod
    def _action_group_data(group: ActionGroup) -> ActionGroup:
        name = group.name.strip()
        if not name:
            raise ValueError("Informe o nome do grupo de ações.")
        actions: list[ActionDefinition] = []
        names: set[str] = set()
        abbreviations: set[str] = set()
        for action in group.actions:
            action_name = action.name.strip()
            abbreviation = action.abbreviation.strip()
            if not action_name:
                raise ValueError("Informe o nome de todas as ações.")
            if not abbreviation:
                raise ValueError("Informe a sigla de todas as ações.")
            name_key = action_name.casefold()
            abbreviation_key = abbreviation.casefold()
            if name_key in names:
                raise ValueError(f"Já existe uma ação chamada '{action_name}' neste grupo.")
            if abbreviation_key in abbreviations:
                raise ValueError(f"Já existe uma ação com a sigla '{abbreviation}'.")
            names.add(name_key)
            abbreviations.add(abbreviation_key)
            actions.append(ActionDefinition(action_name, abbreviation))
        return ActionGroup(name, tuple(actions))

    def add_action_group(self, group: ActionGroup) -> ActionGroup:
        group = self._action_group_data(group)
        if group.name in self.action_groups:
            raise ValueError(f"Já existe um grupo de ações chamado '{group.name}'.")
        self.action_groups[group.name] = group
        self._touch()
        return group

    def set_selected_action_group(self, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Informe o grupo de ações selecionado.")
        self.selected_action_group = name
        self._touch()
        return name

    def set_action_group_alias(self, template_name: str, group_name: str) -> None:
        template_name = template_name.strip()
        group_name = group_name.strip()
        if not template_name or not group_name:
            raise ValueError("Informe os nomes do template e do grupo de ações.")
        self.action_group_aliases[template_name] = group_name
        self._touch()

    def update_action_group(self, old_name: str, group: ActionGroup) -> ActionGroup:
        if old_name not in self.action_groups:
            raise ValueError(f"Grupo de ações '{old_name}' não encontrado.")
        group = self._action_group_data(group)
        if group.name != old_name and group.name in self.action_groups:
            raise ValueError(f"Já existe um grupo de ações chamado '{group.name}'.")
        del self.action_groups[old_name]
        self.action_groups[group.name] = group
        self.action_group_aliases = {
            template: group.name if group_name == old_name else group_name
            for template, group_name in self.action_group_aliases.items()
        }
        if self.selected_action_group == old_name:
            self.selected_action_group = group.name
        self._touch()
        return group

    def remove_action_group(self, name: str) -> None:
        if self.action_groups.pop(name, None) is not None:
            self.action_group_aliases = {
                template: group
                for template, group in self.action_group_aliases.items()
                if group != name
            }
            if self.selected_action_group == name:
                self.selected_action_group = "PP+AP+AV"
            self._touch()

    def clear(self) -> None:
        self.nodes.clear(); self.bars.clear(); self.rigid_bars.clear(); self.axes = {axis: () for axis in ("X", "Y", "Z")}
        self.actions.clear(); self.action_groups.clear()
        self.action_group_aliases.clear()
        self.load_cases.clear(); self.load_combinations.clear(); self.combination_groups_initialized.clear(); self.analysis_results.clear()
        self.selected_action_group = "PP+AP+AV"
        self._touch()
