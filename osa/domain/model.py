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

    def split_bar(
        self,
        name: str,
        node_names: tuple[str, ...],
        member_names: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Replace one bar with collinear segments and intermediate nodes.

        ``node_names`` contains only the new internal nodes.  The generated
        members inherit the source member's analytical properties; releases
        and solid-face offsets remain only at the original outer ends.
        """
        if name not in self.bars:
            raise EntityNotFoundError(f"Membro '{name}' não encontrado.")
        if len(member_names) != len(node_names) + 1:
            raise ValueError("A divisão deve criar exatamente uma parte a mais que o número de nós internos.")
        if not node_names or not member_names:
            raise ValueError("Informe pelo menos duas partes para dividir o membro.")
        if len(set(node_names)) != len(node_names) or any(node in self.nodes for node in node_names):
            raise ValueError("Não foi possível gerar nomes únicos para os nós da divisão.")
        if len(set(member_names)) != len(member_names):
            raise ValueError("Não foi possível gerar nomes únicos para os membros da divisão.")
        if any(member in self.bars and member != name for member in member_names):
            raise ValueError("Não foi possível gerar nomes únicos para os membros da divisão.")

        source = self.bars[name]
        start = self.nodes[source.start_node]
        end = self.nodes[source.end_node]
        coordinates = tuple(
            (
                start.x + (end.x - start.x) * index / len(member_names),
                start.y + (end.y - start.y) * index / len(member_names),
                start.z + (end.z - start.z) * index / len(member_names),
            )
            for index in range(1, len(member_names))
        )
        for coordinate in coordinates:
            self._ensure_unique_coordinates(coordinate)

        chain = (source.start_node, *node_names, source.end_node)
        pairs = tuple(frozenset((chain[index], chain[index + 1])) for index in range(len(member_names)))
        existing_pairs = {
            frozenset((member.start_node, member.end_node))
            for member in self.bars.values()
            if member.name != name
        }
        if any(pair in existing_pairs for pair in pairs):
            raise DuplicateMemberError("A divisão criaria um membro que já existe.")

        new_nodes = {
            node_name: Node(node_name, *coordinate)
            for node_name, coordinate in zip(node_names, coordinates)
        }
        new_bars = {}
        for index, member_name in enumerate(member_names):
            releases = source.releases
            if index > 0:
                releases = tuple(False for _ in source.releases[:6]) + releases[6:]
            if index < len(member_names) - 1:
                releases = releases[:6] + tuple(False for _ in source.releases[6:])
            offsets = (
                source.solid_face_offsets[0] if index == 0 else 0.0,
                source.solid_face_offsets[1] if index == len(member_names) - 1 else 0.0,
            )
            new_bars[member_name] = replace(
                source,
                name=member_name,
                start_node=chain[index],
                end_node=chain[index + 1],
                releases=releases,
                solid_face_offsets=offsets,
            )

        member_actions = tuple(
            action for action in self.actions.values()
            if action.target == name and action.kind.startswith("member_")
        )
        del self.bars[name]
        self.nodes.update(new_nodes)
        self.bars.update(new_bars)

        # Keep existing member actions valid after the source member is gone.
        # A distributed action is copied to every resulting segment, preserving
        # its intensity per unit length and load case.
        for action in member_actions:
            self.actions.pop(action.name, None)
            for index, member_name in enumerate(member_names):
                action_name = action.name if index == 0 else f"{action.name} ({member_name})"
                suffix = 2
                while action_name in self.actions:
                    action_name = f"{action.name} ({member_name}, {suffix})"
                    suffix += 1
                self.actions[action_name] = replace(action, name=action_name, target=member_name)
        self._touch()
        return tuple(node_names), tuple(member_names)

    def join_bars(self, first_name: str, second_name: str) -> Bar:
        """Merge two contiguous, collinear bars and remove their shared node."""
        if first_name == second_name:
            raise ValueError("Selecione dois membros diferentes para unir.")
        if first_name not in self.bars or second_name not in self.bars:
            raise EntityNotFoundError("Um dos membros selecionados não foi encontrado.")

        first = self.bars[first_name]
        second = self.bars[second_name]
        shared_nodes = {first.start_node, first.end_node}.intersection(
            (second.start_node, second.end_node),
        )
        if len(shared_nodes) != 1:
            raise ValueError("Os membros devem compartilhar exatamente um nó para serem unidos.")
        interface = next(iter(shared_nodes))
        first_outer = first.end_node if first.start_node == interface else first.start_node
        second_outer = second.end_node if second.start_node == interface else second.start_node

        connected_members = [
            member.name for member in self.bars.values()
            if member.name not in {first_name, second_name}
            and interface in (member.start_node, member.end_node)
        ]
        connected_rigids = [
            rigid.name for rigid in self.rigid_bars.values()
            if interface in (rigid.start_node, rigid.end_node)
        ]
        if connected_members or connected_rigids:
            connections = ", ".join((*connected_members, *connected_rigids))
            raise ValueError(
                f"O nó de interface pertence a outros elementos: {connections}."
            )
        interface_node = self.nodes[interface]
        if any(interface_node.supports):
            raise ValueError("O nó de interface possui apoios e não pode ser removido.")
        if any(
            action.target == interface and action.kind.startswith("node_")
            for action in self.actions.values()
        ):
            raise ValueError("O nó de interface possui ações nodais e não pode ser removido.")

        first_point = self.nodes[first_outer]
        second_point = self.nodes[second_outer]
        vector_a = (
            interface_node.x - first_point.x,
            interface_node.y - first_point.y,
            interface_node.z - first_point.z,
        )
        vector_b = (
            second_point.x - interface_node.x,
            second_point.y - interface_node.y,
            second_point.z - interface_node.z,
        )
        length_a = math.sqrt(sum(value * value for value in vector_a))
        length_b = math.sqrt(sum(value * value for value in vector_b))
        if length_a <= self.coordinate_tolerance or length_b <= self.coordinate_tolerance:
            raise ValueError("Os membros devem possuir comprimento positivo para serem unidos.")
        cross = (
            vector_a[1] * vector_b[2] - vector_a[2] * vector_b[1],
            vector_a[2] * vector_b[0] - vector_a[0] * vector_b[2],
            vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0],
        )
        cross_length = math.sqrt(sum(value * value for value in cross))
        direction = sum(a * b for a, b in zip(vector_a, vector_b)) / (length_a * length_b)
        if (
            cross_length > 1e-9 * length_a * length_b
            or direction < 1.0 - 1e-9
        ):
            raise ValueError("Os membros devem ser colineares e seguir na mesma direção.")

        if first.start_node == interface:
            start_node, end_node = second_outer, first_outer
        else:
            start_node, end_node = first_outer, second_outer
        pair = frozenset((start_node, end_node))
        if any(
            member.name not in {first_name, second_name}
            and frozenset((member.start_node, member.end_node)) == pair
            for member in self.bars.values()
        ):
            raise DuplicateMemberError("Já existe um membro entre as extremidades da união.")

        def endpoint_data(member: Bar, node_name: str) -> tuple[tuple[bool, ...], float]:
            if member.start_node == node_name:
                return member.releases[:6], member.solid_face_offsets[0]
            return member.releases[6:], member.solid_face_offsets[1]

        start_member = first if start_node == first_outer else second
        end_member = first if end_node == first_outer else second
        start_releases, start_offset = endpoint_data(start_member, start_node)
        end_releases, end_offset = endpoint_data(end_member, end_node)
        joined = replace(
            first,
            start_node=start_node,
            end_node=end_node,
            releases=start_releases + end_releases,
            solid_face_offsets=(start_offset, end_offset),
        )

        first_action_keys = {
            (action.kind, action.components, action.load_case)
            for action in self.actions.values()
            if action.target == first_name and action.kind.startswith("member_")
        }
        for action_name, action in tuple(self.actions.items()):
            if action.target != second_name or not action.kind.startswith("member_"):
                continue
            action_key = action.kind, action.components, action.load_case
            if action_key in first_action_keys:
                del self.actions[action_name]
            else:
                self.actions[action_name] = replace(action, target=first_name)
                first_action_keys.add(action_key)

        self.bars[first_name] = joined
        del self.bars[second_name]
        del self.nodes[interface]
        self._touch()
        return joined

    join_members = join_bars

    def copy_bar_properties(
        self,
        source_name: str,
        target_name: str,
        properties: frozenset[str],
    ) -> Bar:
        """Copy the selected member properties from one bar to another."""
        available = {
            "color", "material", "section", "rotation", "offsets", "releases",
        }
        if source_name == target_name:
            raise ValueError("Selecione membros de referência e destino diferentes.")
        if source_name not in self.bars or target_name not in self.bars:
            raise EntityNotFoundError("O membro de referência ou destino não foi encontrado.")
        if not properties:
            raise ValueError("Selecione pelo menos uma propriedade para copiar.")
        unknown = properties.difference(available)
        if unknown:
            raise ValueError("Foram solicitadas propriedades de membro desconhecidas.")

        source = self.bars[source_name]
        target = self.bars[target_name]
        changes = {}
        if "color" in properties:
            changes["color"] = source.color
        if "material" in properties:
            changes["material"] = source.material
            changes["material_values"] = source.material_values
        if "section" in properties:
            changes["section"] = source.section
            changes["profile"] = source.profile
            changes["section_geometry"] = source.section_geometry
        if "rotation" in properties:
            changes["rotation"] = source.rotation
        if "offsets" in properties:
            changes["solid_face_offsets"] = source.solid_face_offsets
        if "releases" in properties:
            changes["releases"] = source.releases
        copied = replace(target, **changes)
        self.bars[target_name] = copied
        self._touch()
        return copied

    copy_member_properties = copy_bar_properties

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
    def _member_solid_face_offsets(values: tuple[float, ...]) -> tuple[float, float]:
        if len(values) != 2:
            raise ValueError("Os deslocamentos das faces sólidas devem possuir dois valores.")
        offsets = tuple(float(value) for value in values)
        if not all(math.isfinite(value) for value in offsets):
            raise ValueError("Os deslocamentos das faces sólidas devem ser números finitos.")
        return offsets  # type: ignore[return-value]

    def update_member_solid_face_offsets(self, name: str, offsets: tuple[float, ...]) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Membro '{name}' não encontrado.")
        self.bars[name] = replace(
            self.bars[name], solid_face_offsets=self._member_solid_face_offsets(offsets),
        )
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
