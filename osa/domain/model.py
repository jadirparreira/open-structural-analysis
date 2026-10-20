"""Agregado principal do modelo estrutural."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace

from .drawing_reference import DrawingReference
from .entities import (
    Action,
    ActionDefinition,
    ActionGroup,
    AnalysisResult,
    Bar,
    LoadCase,
    LoadCombination,
    Node,
    ReferenceAxis,
    RigidBar,
)
from .errors import DuplicateMemberError, DuplicateNodeCoordinatesError, EntityNotFoundError


class StructuralModel:
    """Mantém as entidades e garante invariantes em qualquer fluxo de entrada."""

    coordinate_tolerance = 1e-9
    # Maximum displacement when each coordinate rounds by half a millimetre.
    node_rounding_tolerance = math.sqrt(3) * 0.0005

    def __init__(self, *, materials=None, material_types=None, sections=None) -> None:
        self.nodes: dict[str, Node] = {}
        self.bars: dict[str, Bar] = {}
        self.rigid_bars: dict[str, RigidBar] = {}
        self.axes: dict[str, tuple[ReferenceAxis, ...]] = {axis: () for axis in ("X", "Y", "Z")}
        self.references: dict[str, DrawingReference] = {}
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
        self.scene_views: dict[str, set[str]] = {"Completo": set()}
        self.scene_view_hidden_rigid_bars: dict[str, set[str]] = {"Completo": set()}
        self.active_scene_view = "Completo"
        self.view_revision = 0

    @property
    def members(self) -> dict[str, Bar]:
        return self.bars

    def _touch(self) -> None:
        self.revision += 1
        self.analysis_results.clear()
        for hidden in self.scene_views.values():
            hidden.intersection_update(self.bars)
        for hidden in self.scene_view_hidden_rigid_bars.values():
            hidden.intersection_update(self.rigid_bars)

    def add_scene_view(self, name: str) -> None:
        name = name.strip()
        if not name or name in self.scene_views:
            raise ValueError("Informe um nome de vista único.")
        self.scene_views[name] = set()
        self.scene_view_hidden_rigid_bars[name] = set()
        self.active_scene_view = name
        self.view_revision += 1

    def add_reference(self, reference: DrawingReference) -> None:
        if reference.id in self.references:
            raise ValueError("A referência já está no projeto.")
        self.references[reference.id] = reference
        self.view_revision += 1

    def update_reference(self, reference_id: str, *, origin=None, plane=None, visible=None) -> None:
        current = self.references[reference_id]
        updated = replace(
            current,
            origin=current.origin if origin is None else self._coordinates(*origin),
            plane=current.plane if plane is None else plane,
            visible=current.visible if visible is None else bool(visible),
        )
        if updated != current:
            self.references[reference_id] = updated
            self.view_revision += 1

    def remove_reference(self, reference_id: str) -> None:
        if reference_id in self.references:
            del self.references[reference_id]
            self.view_revision += 1

    def remove_scene_view(self, name: str) -> None:
        if name == "Completo" or name not in self.scene_views:
            return
        del self.scene_views[name]
        self.scene_view_hidden_rigid_bars.pop(name, None)
        if self.active_scene_view == name:
            self.active_scene_view = "Completo"
        self.view_revision += 1

    def rename_scene_view(self, old_name: str, new_name: str) -> None:
        new_name = new_name.strip()
        if old_name == "Completo" or old_name not in self.scene_views:
            return
        if not new_name or (new_name != old_name and new_name in self.scene_views):
            raise ValueError("Informe um nome de vista único.")
        if new_name == old_name:
            return
        self.scene_views = {
            (new_name if name == old_name else name): hidden
            for name, hidden in self.scene_views.items()
        }
        self.scene_view_hidden_rigid_bars = {
            (new_name if name == old_name else name): hidden
            for name, hidden in self.scene_view_hidden_rigid_bars.items()
        }
        if self.active_scene_view == old_name:
            self.active_scene_view = new_name
        self.view_revision += 1

    def select_scene_view(self, name: str) -> None:
        if name not in self.scene_views or name == self.active_scene_view:
            return
        self.active_scene_view = name
        self.view_revision += 1

    def set_scene_members_hidden(self, names: set[str], hidden: bool) -> None:
        if self.active_scene_view == "Completo":
            return
        current = self.scene_views[self.active_scene_view]
        before = current.copy()
        if hidden:
            current.update(names.intersection(self.bars))
        else:
            current.difference_update(names)
        if current != before:
            self.view_revision += 1

    def set_scene_rigid_bars_hidden(self, names: set[str], hidden: bool) -> None:
        if self.active_scene_view == "Completo":
            return
        current = self.scene_view_hidden_rigid_bars[self.active_scene_view]
        before = current.copy()
        if hidden:
            current.update(names.intersection(self.rigid_bars))
        else:
            current.difference_update(names)
        if current != before:
            self.view_revision += 1

    def show_all_scene_members(self) -> None:
        if self.active_scene_view != "Completo":
            members = self.scene_views[self.active_scene_view]
            rigid_bars = self.scene_view_hidden_rigid_bars[self.active_scene_view]
            if members or rigid_bars:
                members.clear()
                rigid_bars.clear()
                self.view_revision += 1

    @staticmethod
    def _coordinates(x: float, y: float, z: float) -> tuple[float, float, float]:
        values = float(x), float(y), float(z)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("As coordenadas devem ser números finitos.")
        return values

    @classmethod
    def node_coordinates(cls, x: float, y: float, z: float) -> tuple[float, float, float]:
        """Snap node coordinates in metres to the nearest millimetre.

        Keep file loading at its original precision so opening a legacy model
        cannot silently merge nodes or collapse members.
        """
        return tuple(round(value, 3) or 0.0 for value in cls._coordinates(x, y, z))

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
        coordinates = self.node_coordinates(x, y, z)
        self._ensure_unique_coordinates(coordinates)
        node = Node(name, *coordinates)
        self.nodes[name] = node
        self._touch()
        return node

    def update_node(self, name: str, x: float, y: float, z: float) -> Node:
        if name not in self.nodes:
            raise EntityNotFoundError(f"Nó '{name}' não encontrado.")
        coordinates = self.node_coordinates(x, y, z)
        self._ensure_unique_coordinates(coordinates, ignore=name)
        node = replace(self.nodes[name], x=coordinates[0], y=coordinates[1], z=coordinates[2])
        self.nodes[name] = node
        self._touch()
        return node

    def update_nodes_coordinates(
        self, changes: dict[str, tuple[float, float, float]],
    ) -> None:
        """Apply a coordinate edit to several nodes as one validated change."""
        if not changes:
            return
        for name in changes:
            if name not in self.nodes:
                raise EntityNotFoundError(f"Nó '{name}' não encontrado.")
        final = {
            name: self.node_coordinates(*changes[name]) if name in changes
            else (node.x, node.y, node.z)
            for name, node in self.nodes.items()
        }
        for name in changes:
            coordinates = final[name]
            for other_name, other in final.items():
                if other_name != name and all(
                    math.isclose(a, b, abs_tol=self.coordinate_tolerance, rel_tol=0.0)
                    for a, b in zip(coordinates, other)
                ):
                    raise DuplicateNodeCoordinatesError("Já existe um nó nessa coordenada.")
        for name in changes:
            self.nodes[name] = replace(self.nodes[name], x=final[name][0],
                                       y=final[name][1], z=final[name][2])
        self._touch()

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
        self._remove_actions_for_target(name)
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

    def update_node_support_stiffness(self, name: str, stiffness: tuple[float, ...]) -> Node:
        if name not in self.nodes:
            raise EntityNotFoundError(f"Nó '{name}' não encontrado.")
        if len(stiffness) != 6:
            raise ValueError("Informe seis rigidezes de mola para o nó.")
        values = tuple(float(value) for value in stiffness)
        if any(not math.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("As rigidezes de mola devem ser números não negativos.")
        node = replace(self.nodes[name], support_stiffness=values)
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

    def _validate_member_nodes(
        self, start_node: str, end_node: str, ignore: str = "",
        *, existing_pairs: set[frozenset[str]] | None = None,
    ) -> None:
        if start_node.casefold() == end_node.casefold():
            raise ValueError("Uma barra deve conectar dois nós diferentes.")
        if start_node not in self.nodes or end_node not in self.nodes:
            raise ValueError("Selecione dois nós válidos.")
        pair = frozenset((start_node, end_node))
        duplicate = pair in existing_pairs if existing_pairs is not None else any(
            bar.name != ignore and frozenset((bar.start_node, bar.end_node)) == pair
            for bar in self.bars.values()
        )
        if duplicate:
            raise DuplicateMemberError("Já existe uma barra entre esses nós.")

    def add_bar(self, name: str, start_node: str, end_node: str, *, template: Bar | None = None) -> Bar:
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome da barra.")
        if name in self.bars:
            raise ValueError(f"Já existe uma barra chamada '{name}'.")
        self._validate_member_nodes(start_node, end_node)
        bar = (
            replace(template, name=name, start_node=start_node, end_node=end_node)
            if template is not None else Bar(name, start_node, end_node)
        )
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
        if name not in self.bars:
            return
        member = self.bars[name]
        del self.bars[name]
        self._remove_actions_for_target(name)
        self._delete_orphan_nodes((member.start_node, member.end_node))
        self._touch()

    remove_member = remove_bar

    def split_bar(
        self,
        name: str,
        node_names: tuple[str, ...],
        member_names: tuple[str, ...],
        *,
        segment_lengths: tuple[float, ...] | None = None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Replace one bar with collinear segments and intermediate nodes.

        ``node_names`` contains only the new internal nodes.  The generated
        members inherit the source member's analytical properties; releases
        and solid-face offsets remain only at the original outer ends.
        """
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        if len(member_names) != len(node_names) + 1:
            raise ValueError("A divisão deve criar exatamente uma parte a mais que o número de nós internos.")
        if not node_names or not member_names:
            raise ValueError("Informe pelo menos duas partes para dividir a barra.")
        if len(set(node_names)) != len(node_names) or any(node in self.nodes for node in node_names):
            raise ValueError("Não foi possível gerar nomes únicos para os nós da divisão.")
        if len(set(member_names)) != len(member_names):
            raise ValueError("Não foi possível gerar nomes únicos para as barras da divisão.")
        if any(member in self.bars and member != name for member in member_names):
            raise ValueError("Não foi possível gerar nomes únicos para as barras da divisão.")

        source = self.bars[name]
        start = self.nodes[source.start_node]
        end = self.nodes[source.end_node]
        start_coordinates = (start.x, start.y, start.z)
        direction = (end.x - start.x, end.y - start.y, end.z - start.z)
        member_length = math.hypot(*direction)
        if segment_lengths is None:
            positions = tuple(index / len(member_names) for index in range(1, len(member_names)))
        else:
            if len(segment_lengths) != len(member_names):
                raise ValueError("Informe um comprimento para cada segmento.")
            if any(not math.isfinite(value) or value <= self.coordinate_tolerance for value in segment_lengths):
                raise ValueError("Os comprimentos dos segmentos devem ser positivos.")
            total_length = math.fsum(segment_lengths)
            tolerance = max(
                self.coordinate_tolerance,
                member_length * 1e-9,
                0.0000005 * len(segment_lengths),
            )
            if not math.isclose(total_length, member_length, rel_tol=1e-9, abs_tol=tolerance):
                raise ValueError("A soma dos segmentos deve corresponder ao comprimento da barra.")
            cumulative_lengths = tuple(math.fsum(segment_lengths[:index]) for index in range(1, len(segment_lengths)))
            positions = tuple(distance / total_length for distance in cumulative_lengths)
        coordinates = tuple(
            self.node_coordinates(*(start_coordinates[axis] + direction[axis] * ratio for axis in range(3)))
            for ratio in positions
        )
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("A divisão criaria nós coincidentes na precisão de um milímetro.")
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
            raise DuplicateMemberError("A divisão criaria uma barra que já existe.")

        new_nodes = {
            node_name: Node(node_name, *coordinate)
            for node_name, coordinate in zip(node_names, coordinates)
        }
        new_bars = {}
        for index, member_name in enumerate(member_names):
            releases = source.releases
            rotation_percent = source.rotation_flexibility_percent
            if index > 0:
                releases = tuple(False for _ in source.releases[:6]) + releases[6:]
                rotation_percent = tuple(
                    0 if position in (0, 2, 4) else value
                    for position, value in enumerate(rotation_percent)
                )
            if index < len(member_names) - 1:
                releases = releases[:6] + tuple(False for _ in source.releases[6:])
                rotation_percent = tuple(
                    0 if position in (1, 3, 5) else value
                    for position, value in enumerate(rotation_percent)
                )
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
                rotation_flexibility_percent=rotation_percent,
            )

        member_actions = tuple(
            action for action in self.actions.values()
            if action.target == name and action.kind.startswith("member_")
        )
        del self.bars[name]
        self.nodes.update(new_nodes)
        self.bars.update(new_bars)
        for hidden in self.scene_views.values():
            if name in hidden:
                hidden.remove(name)
                hidden.update(member_names)

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
            raise ValueError("Selecione dois barras diferentes para unir.")
        if first_name not in self.bars or second_name not in self.bars:
            raise EntityNotFoundError("Uma das barras selecionadas não foi encontrada.")

        first = self.bars[first_name]
        second = self.bars[second_name]
        shared_nodes = {first.start_node, first.end_node}.intersection(
            (second.start_node, second.end_node),
        )
        if len(shared_nodes) != 1:
            raise ValueError("As barras devem compartilhar exatamente um nó para serem unidos.")
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
            raise ValueError("As barras devem possuir comprimento positivo para serem unidos.")
        cross = (
            vector_a[1] * vector_b[2] - vector_a[2] * vector_b[1],
            vector_a[2] * vector_b[0] - vector_a[0] * vector_b[2],
            vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0],
        )
        cross_length = math.sqrt(sum(value * value for value in cross))
        direction = sum(a * b for a, b in zip(vector_a, vector_b)) / (length_a * length_b)
        outer_length = math.hypot(*(a + b for a, b in zip(vector_a, vector_b)))
        # A split diagonal can move its interface slightly off the original
        # line when rounded. Allow only the displacement of one grid snap.
        if (
            cross_length > max(1e-9 * length_a * length_b, self.node_rounding_tolerance * outer_length)
            or direction <= 0.0
        ):
            raise ValueError("As barras devem ser colineares e seguir na mesma direção.")

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
            raise DuplicateMemberError("Já existe uma barra entre as extremidades da união.")

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

    def join_selected_members(self, member_names: tuple[str, ...]) -> Bar:
        """Merge a connected collinear chain, committing only after all checks pass."""
        names = tuple(dict.fromkeys(member_names))
        if len(names) < 2:
            raise ValueError("Selecione pelo menos dois barras diferentes para unir.")
        if any(name not in self.bars for name in names):
            raise EntityNotFoundError("Uma das barras selecionadas não foi encontrada.")

        # Join in an isolated model so a failure at the last interface cannot
        # leave the earlier members merged or discard loads/results/views.
        candidate = StructuralModel()
        candidate.nodes = self.nodes.copy()
        candidate.bars = self.bars.copy()
        candidate.rigid_bars = self.rigid_bars.copy()
        candidate.actions = self.actions.copy()
        first_name = names[0]
        remaining = list(names[1:])
        while remaining:
            first = candidate.bars[first_name]
            endpoints = {first.start_node, first.end_node}
            next_name = next((
                name for name in remaining
                if endpoints.intersection((candidate.bars[name].start_node, candidate.bars[name].end_node))
            ), None)
            if next_name is None:
                raise ValueError("As barras devem formar uma sequência conectada na mesma reta.")
            candidate.join_bars(first_name, next_name)
            remaining.remove(next_name)

        self.nodes.clear()
        self.nodes.update(candidate.nodes)
        self.bars.clear()
        self.bars.update(candidate.bars)
        self.actions.clear()
        self.actions.update(candidate.actions)
        self._touch()
        return self.bars[first_name]

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
            raise ValueError("Selecione barras de referência e destino diferentes.")
        if source_name not in self.bars or target_name not in self.bars:
            raise EntityNotFoundError("A barra de referência ou destino não foi encontrada.")
        if not properties:
            raise ValueError("Selecione pelo menos uma propriedade para copiar.")
        unknown = properties.difference(available)
        if unknown:
            raise ValueError("Foram solicitadas propriedades de barra desconhecidas.")

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
            changes["section_mirrored"] = source.section_mirrored
        if "rotation" in properties:
            changes["rotation"] = source.rotation
        if "offsets" in properties:
            changes["solid_face_offsets"] = source.solid_face_offsets
            changes["solid_section_offsets"] = source.solid_section_offsets
        if "releases" in properties:
            changes["releases"] = source.releases
            changes["rotation_flexibility_percent"] = source.rotation_flexibility_percent
        copied = replace(target, **changes)
        self.bars[target_name] = copied
        self._touch()
        return copied

    copy_member_properties = copy_bar_properties

    def copy_elements(
        self,
        node_names: tuple[str, ...],
        member_names: tuple[str, ...],
        offset: tuple[float, float, float],
        rigid_bar_names: tuple[str, ...] = (),
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Copy selected nodes, members, and rigid bars by translating them.

        Existing nodes at the destination coordinates are reused.  Members
        whose endpoint pair already exists are skipped, which makes copying
        onto an existing position idempotent.
        """
        selected_nodes = tuple(dict.fromkeys(node_names))
        selected_members = tuple(dict.fromkeys(member_names))
        selected_rigid_bars = tuple(dict.fromkeys(rigid_bar_names))
        if not selected_nodes and not selected_members and not selected_rigid_bars:
            raise ValueError("Selecione pelo menos um nó ou elemento para copiar.")
        if any(name not in self.nodes for name in selected_nodes):
            raise EntityNotFoundError("Um dos nós selecionados não foi encontrado.")
        if any(name not in self.bars for name in selected_members):
            raise EntityNotFoundError("Uma das barras selecionadas não foi encontrada.")
        if any(name not in self.rigid_bars for name in selected_rigid_bars):
            raise EntityNotFoundError("Uma das barras rígidas selecionadas não foi encontrada.")

        try:
            translation = tuple(float(value) for value in offset)
        except (TypeError, ValueError) as error:
            raise ValueError("O deslocamento da cópia é inválido.") from error
        if len(translation) != 3 or not all(math.isfinite(value) for value in translation):
            raise ValueError("O deslocamento da cópia deve possuir três números finitos.")
        dx, dy, dz = translation

        source_node_names = list(selected_nodes)
        for member_name in selected_members:
            member = self.bars[member_name]
            for node_name in (member.start_node, member.end_node):
                if node_name not in source_node_names:
                    source_node_names.append(node_name)
        for rigid_name in selected_rigid_bars:
            rigid = self.rigid_bars[rigid_name]
            for node_name in (rigid.start_node, rigid.end_node):
                if node_name not in source_node_names:
                    source_node_names.append(node_name)

        def translated_coordinates(node: Node) -> tuple[float, float, float]:
            return self.node_coordinates(node.x + dx, node.y + dy, node.z + dz)

        def same_coordinates(first: tuple[float, float, float], second: tuple[float, float, float]) -> bool:
            return all(
                math.isclose(a, b, abs_tol=self.coordinate_tolerance, rel_tol=0.0)
                for a, b in zip(first, second)
            )

        new_nodes: dict[str, Node] = {}
        node_map: dict[str, str] = {}
        next_node_index = 1
        for source_name in source_node_names:
            source = self.nodes[source_name]
            coordinates = translated_coordinates(source)
            existing_name = next(
                (
                    name for name, node in self.nodes.items()
                    if same_coordinates(coordinates, (node.x, node.y, node.z))
                ),
                None,
            )
            if existing_name is None:
                existing_name = next(
                    (
                        name for name, node in new_nodes.items()
                        if same_coordinates(coordinates, (node.x, node.y, node.z))
                    ),
                    None,
                )
            if existing_name is None:
                while f"N{next_node_index}" in self.nodes or f"N{next_node_index}" in new_nodes:
                    next_node_index += 1
                existing_name = f"N{next_node_index}"
                next_node_index += 1
                new_nodes[existing_name] = replace(
                    source if source_name in selected_nodes else Node(existing_name, *coordinates),
                    name=existing_name,
                    x=coordinates[0],
                    y=coordinates[1],
                    z=coordinates[2],
                )
            node_map[source_name] = existing_name

        existing_pairs = {
            frozenset((member.start_node, member.end_node))
            for member in self.bars.values()
        }
        new_bars: dict[str, Bar] = {}
        next_member_index = 1
        for source_name in selected_members:
            source = self.bars[source_name]
            start_node = node_map[source.start_node]
            end_node = node_map[source.end_node]
            if start_node == end_node:
                raise ValueError("A cópia criaria uma barra de comprimento zero na precisão de um milímetro.")
            pair = frozenset((start_node, end_node))
            if pair in existing_pairs:
                continue
            while f"B{next_member_index}" in self.bars or f"B{next_member_index}" in new_bars:
                next_member_index += 1
            member_name = f"B{next_member_index}"
            next_member_index += 1
            new_bars[member_name] = replace(
                source,
                name=member_name,
                start_node=start_node,
                end_node=end_node,
            )
            existing_pairs.add(pair)

        existing_rigid_pairs = {
            frozenset((rigid.start_node, rigid.end_node))
            for rigid in self.rigid_bars.values()
        }
        new_rigid_bars: dict[str, RigidBar] = {}
        for source_name in selected_rigid_bars:
            source = self.rigid_bars[source_name]
            start_node = node_map[source.start_node]
            end_node = node_map[source.end_node]
            if start_node == end_node:
                raise ValueError("A cópia criaria uma barra rígida de comprimento zero.")
            pair = frozenset((start_node, end_node))
            if pair in existing_rigid_pairs:
                continue
            rigid_name = f"{start_node}-{end_node}"
            if rigid_name in self.rigid_bars or rigid_name in new_rigid_bars:
                raise ValueError(f"Já existe uma barra rígida chamada '{rigid_name}'.")
            new_rigid_bars[rigid_name] = RigidBar(rigid_name, start_node, end_node)
            existing_rigid_pairs.add(pair)

        if new_nodes or new_bars or new_rigid_bars:
            self.nodes.update(new_nodes)
            self.bars.update(new_bars)
            self.rigid_bars.update(new_rigid_bars)
            self._touch()
        return tuple(new_nodes), tuple(new_bars)

    def _validate_rigid_bar_nodes(
        self, start_node: str, end_node: str, ignore: str = "",
        *, existing_pairs: set[frozenset[str]] | None = None,
    ) -> None:
        if start_node.casefold() == end_node.casefold():
            raise ValueError("Uma barra rígida deve conectar dois nós diferentes.")
        if start_node not in self.nodes or end_node not in self.nodes:
            raise ValueError("Selecione dois nós válidos.")
        pair = frozenset((start_node, end_node))
        duplicate = pair in existing_pairs if existing_pairs is not None else any(
            rigid.name != ignore
            and frozenset((rigid.start_node, rigid.end_node)) == pair
            for rigid in self.rigid_bars.values()
        )
        if duplicate:
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
        if name not in self.rigid_bars:
            return
        rigid = self.rigid_bars[name]
        del self.rigid_bars[name]
        self._remove_actions_for_target(name)
        self._delete_orphan_nodes((rigid.start_node, rigid.end_node))
        self._touch()

    def _orphan_node_names(
        self,
        candidates: Iterable[str],
        *,
        removing_bars: set[str] | None = None,
        removing_rigid_bars: set[str] | None = None,
    ) -> tuple[str, ...]:
        """Find candidate nodes with no remaining structural or rigid members."""
        removed_bars = removing_bars or set()
        removed_rigid_bars = removing_rigid_bars or set()
        connected = {
            node_name
            for name, member in self.bars.items()
            if name not in removed_bars
            for node_name in (member.start_node, member.end_node)
        }
        connected.update(
            node_name
            for name, rigid in self.rigid_bars.items()
            if name not in removed_rigid_bars
            for node_name in (rigid.start_node, rigid.end_node)
        )
        return tuple(
            name for name in dict.fromkeys(candidates)
            if name in self.nodes and name not in connected
        )

    def _delete_orphan_nodes(self, candidates: Iterable[str]) -> tuple[str, ...]:
        """Delete unconnected candidate nodes and any actions targeting them."""
        orphaned = self._orphan_node_names(candidates)
        for name in orphaned:
            del self.nodes[name]
            self._remove_actions_for_target(name)
        return orphaned

    def remove_orphaned_actions(self) -> tuple[str, ...]:
        """Remove actions whose target no longer exists in the model."""
        valid_targets = set(self.nodes) | set(self.bars) | set(self.rigid_bars)
        orphaned = tuple(
            name for name, action in self.actions.items()
            if action.target not in valid_targets
        )
        if not orphaned:
            return ()
        for name in orphaned:
            del self.actions[name]
        self._touch()
        return orphaned

    def _remove_actions_for_target(self, target: str) -> None:
        for name, action in tuple(self.actions.items()):
            if action.target == target:
                del self.actions[name]

    def update_bar_material(self, name: str, material: str, values: tuple[float, float, float, float]) -> Bar:
        self.bars[name] = replace(self.bars[name], material=material, material_values=tuple(values))
        self._touch()
        return self.bars[name]

    def update_bar_section(self, name: str, section: str) -> Bar:
        self.bars[name] = replace(
            self.bars[name], section=section, profile="", section_geometry=(),
            section_mirrored=False,
        )
        self._touch()
        return self.bars[name]

    def update_member_profile(self, name: str, profile: str, geometry: dict[str, float]) -> Bar:
        self.bars[name] = replace(
            self.bars[name], profile=profile, section_geometry=tuple((key, float(value)) for key, value in geometry.items())
        )
        self._touch()
        return self.bars[name]

    def update_member_section_mirrored(self, name: str, mirrored: bool) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        self.bars[name] = replace(self.bars[name], section_mirrored=bool(mirrored))
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_rotation(value: int | float) -> int | float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("A rotação da barra deve ser um número em graus.")  # noqa: TRY004
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("A rotação da barra deve ser um número finito.")
        normalized = round(value % 360.0, 2)
        if normalized >= 360.0 or normalized == 0.0:
            return 0
        if normalized.is_integer():
            return int(normalized)
        return normalized

    def update_member_rotation(self, name: str, rotation: int | float) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        rotation = self._member_rotation(rotation)
        self.bars[name] = replace(self.bars[name], rotation=rotation)
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_releases(values: tuple[bool, ...]) -> tuple[bool, ...]:
        if len(values) != 12:
            raise ValueError("As vinculações da barra devem possuir doze graus de liberdade.")
        return tuple(bool(value) for value in values)

    def update_member_releases(self, name: str, releases: tuple[bool, ...]) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        normalized = self._member_releases(releases)
        current_percent = self.bars[name].rotation_flexibility_percent
        rotation_percent = tuple(
            0 if normalized[index] else min(99, current_percent[position])
            for position, index in enumerate((6, 7, 8, 9, 10, 11))
        )
        self.bars[name] = replace(
            self.bars[name],
            releases=normalized,
            rotation_flexibility_percent=rotation_percent,
        )
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_rotation_flexibility_percent(values: tuple[int, ...]) -> tuple[int, ...]:
        if len(values) != 6:
            raise ValueError("Os percentuais de flexibilização devem possuir seis valores.")
        normalized = tuple(values)
        if any(isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 99
               for value in normalized):
            raise ValueError("Os percentuais de flexibilização devem ser inteiros entre 0 e 99.")
        return normalized

    def update_member_rotation_flexibility_percent(self, name: str, percent: tuple[int, ...]) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        values = self._member_rotation_flexibility_percent(percent)
        self.bars[name] = replace(self.bars[name], rotation_flexibility_percent=values)
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
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        self.bars[name] = replace(
            self.bars[name], solid_face_offsets=self._member_solid_face_offsets(offsets),
        )
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_solid_section_offsets(values: tuple[float, ...]) -> tuple[float, float]:
        if len(values) != 2:
            raise ValueError("Os deslocamentos da seção sólida devem possuir dois valores.")
        offsets = tuple(float(value) for value in values)
        if not all(math.isfinite(value) for value in offsets):
            raise ValueError("Os deslocamentos da seção sólida devem ser números finitos.")
        return offsets  # type: ignore[return-value]

    def update_member_solid_section_offsets(
        self, name: str, offsets: tuple[float, ...],
    ) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
        self.bars[name] = replace(
            self.bars[name],
            solid_section_offsets=self._member_solid_section_offsets(offsets),
        )
        self._touch()
        return self.bars[name]

    @staticmethod
    def _member_color(value: str) -> str:
        if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
            raise ValueError("A cor da barra deve estar no formato hexadecimal #RRGGBB.")
        try:
            int(value[1:], 16)
        except ValueError as error:
            raise ValueError("A cor da barra deve estar no formato hexadecimal #RRGGBB.") from error
        return value.lower()

    def update_member_color(self, name: str, color: str) -> Bar:
        if name not in self.bars:
            raise EntityNotFoundError(f"Barra '{name}' não encontrado.")
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
        self.references.clear()
        self.nodes.clear(); self.bars.clear(); self.rigid_bars.clear(); self.axes = {axis: () for axis in ("X", "Y", "Z")}
        self.actions.clear(); self.action_groups.clear()
        self.action_group_aliases.clear()
        self.load_cases.clear(); self.load_combinations.clear(); self.combination_groups_initialized.clear(); self.analysis_results.clear()
        self.selected_action_group = "PP+AP+AV"
        self.scene_views = {"Completo": set()}
        self.scene_view_hidden_rigid_bars = {"Completo": set()}
        self.active_scene_view = "Completo"
        self.view_revision += 1
        self._touch()
