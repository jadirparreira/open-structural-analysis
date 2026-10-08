"""Operações coordenadas sobre o modelo estrutural."""

from __future__ import annotations

from osa.domain import StructuralModel

from .section_property_service import SectionPropertyService


class ModelService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def next_node_name(self) -> str:
        index = 1
        while f"N{index}" in self.model.nodes:
            index += 1
        return f"N{index}"

    def next_member_name(self) -> str:
        index = 1
        while f"B{index}" in self.model.bars:
            index += 1
        return f"B{index}"

    def create_node(self, x: float, y: float, z: float, *, name: str | None = None):
        return self.model.add_node(name or self.next_node_name(), x, y, z)

    def create_member(self, start_node: str, end_node: str, *, name: str | None = None):
        return self.model.add_bar(name or self.next_member_name(), start_node, end_node)

    def split_member(self, name: str, parts: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Divide a member into equally sized collinear members."""
        if isinstance(parts, bool) or not isinstance(parts, int) or parts <= 1:
            raise ValueError("Informe um número inteiro maior que 1.")
        member = self.model.bars.get(name)
        if member is None:
            raise ValueError(f"Membro '{name}' não encontrado.")

        node_names: list[str] = []
        node_index = 1
        while len(node_names) < parts - 1:
            candidate = f"N{node_index}"
            node_index += 1
            if candidate not in self.model.nodes:
                node_names.append(candidate)

        member_names: list[str] = []
        member_index = 1
        while len(member_names) < parts:
            candidate = f"B{member_index}"
            member_index += 1
            if candidate not in self.model.bars or candidate == name:
                member_names.append(candidate)
        return self.model.split_bar(name, tuple(node_names), tuple(member_names))

    def reverse_member(self, name: str):
        """Swap a member's start and end nodes without changing its identity."""
        member = self.model.bars.get(name)
        if member is None:
            raise ValueError(f"Membro '{name}' não encontrado.")
        return self.model.update_bar(name, member.end_node, member.start_node)

    def normalize_member_directions(self) -> tuple[str, ...]:
        """Orient members toward the positive global coordinate direction.

        The first coordinate that differs between the member's endpoints
        (X, then Y, then Z) defines its canonical direction.  This keeps the
        local x axis deterministic even when members were created in different
        click orders.
        """
        reversed_members: list[str] = []
        tolerance = self.model.coordinate_tolerance
        for name, member in tuple(self.model.bars.items()):
            start = self.model.nodes[member.start_node]
            end = self.model.nodes[member.end_node]
            start_coordinates = (start.x, start.y, start.z)
            end_coordinates = (end.x, end.y, end.z)
            should_reverse = False
            for start_value, end_value in zip(start_coordinates, end_coordinates):
                difference = end_value - start_value
                if abs(difference) > tolerance:
                    should_reverse = difference < 0.0
                    break
            if should_reverse:
                self.reverse_member(name)
                reversed_members.append(name)
        return tuple(reversed_members)

    def join_members(self, first_name: str, second_name: str):
        """Merge two adjacent collinear members into the first selected one."""
        return self.model.join_bars(first_name, second_name)

    def copy_member_properties(
        self,
        source_name: str,
        target_name: str,
        properties: frozenset[str],
    ):
        """Copy a selectable subset of properties between two members."""
        return self.model.copy_bar_properties(source_name, target_name, properties)

    def copy_elements(
        self,
        node_names: tuple[str, ...],
        member_names: tuple[str, ...],
        offset: tuple[float, float, float],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Copy selected nodes and members to a translated position."""
        return self.model.copy_elements(node_names, member_names, offset)

    def create_rigid_bar(self, start_node: str, end_node: str):
        return self.model.add_rigid_bar(start_node, end_node)

    def set_reference_axes(self, axes) -> None:
        self.model.set_reference_axes(axes)

    def update_node(self, name: str, x: float, y: float, z: float):
        return self.model.update_node(name, x, y, z)

    def update_supports(self, name: str, supports: tuple[bool, ...]):
        return self.model.update_node_supports(name, supports)

    def update_support_stiffness(self, name: str, stiffness: tuple[float, ...]):
        return self.model.update_node_support_stiffness(name, stiffness)

    def update_member_nodes(self, name: str, start_node: str, end_node: str):
        return self.model.update_bar(name, start_node, end_node)

    def update_rigid_bar_nodes(self, name: str, start_node: str, end_node: str):
        return self.model.update_rigid_bar(name, start_node, end_node)

    def assign_material(self, name: str, material: str):
        return self.model.update_bar_material(name, material, self.model.materials[material])

    def assign_section(self, name: str, section: str):
        return self.model.update_bar_section(name, section)

    def assign_profile(self, name: str, profile: str, geometry: dict[str, float]):
        return self.model.update_member_profile(name, profile, geometry)

    def update_member_rotation(self, name: str, rotation: int):
        return self.model.update_member_rotation(name, rotation)

    def update_member_releases(self, name: str, releases: tuple[bool, ...]):
        return self.model.update_member_releases(name, releases)

    def update_member_rotation_flexibility_percent(self, name: str, percent: tuple[int, ...]):
        return self.model.update_member_rotation_flexibility_percent(name, percent)

    def update_member_solid_face_offsets(self, name: str, offsets: tuple[float, ...]):
        return self.model.update_member_solid_face_offsets(name, offsets)

    def update_member_solid_section_offsets(self, name: str, offsets: tuple[float, ...]):
        return self.model.update_member_solid_section_offsets(name, offsets)

    def update_member_color(self, name: str, color: str):
        return self.model.update_member_color(name, color)

    def member_selfweights(self, material: str | None = None) -> tuple[tuple[str, float], ...]:
        """Retorna pesos lineares em kN/m, opcionalmente filtrados por material."""
        properties_service = SectionPropertyService()
        weights: list[tuple[str, float]] = []
        missing: list[str] = []
        material_key = material.casefold() if material is not None else None
        members = tuple(
            member for member in self.model.bars.values()
            if material_key is None or member.material.casefold() == material_key
        )
        for member in members:
            if not member.section or not member.section_geometry:
                missing.append(member.name)
                continue
            try:
                properties = properties_service.calculate(
                    member.section,
                    member.geometry_dict(),
                    member.material_values[3] / 9.80665e-3,
                )
            except (KeyError, TypeError, ValueError):
                missing.append(member.name)
                continue
            # kg/m * 10 N/kg / 1000 = kg/m / 100 kN/m.
            weights.append((member.name, -properties.mass_kg_m / 100.0))
        if missing:
            names = ", ".join(missing)
            raise ValueError(f"Não foi possível obter o peso linear dos membros: {names}.")
        return tuple(weights)

    def remove_node(self, name: str) -> None:
        self.model.remove_node(name)

    def remove_member(self, name: str) -> None:
        self.model.remove_bar(name)

    def remove_rigid_bar(self, name: str) -> None:
        self.model.remove_rigid_bar(name)

    def remove_elements(
        self,
        *,
        node_names: tuple[str, ...] = (),
        member_names: tuple[str, ...] = (),
        rigid_bar_names: tuple[str, ...] = (),
        cascade: bool = False,
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Remove elementos estruturais em lote após validar dependências."""
        nodes = self._unique_names(node_names)
        members = self._unique_names(member_names)
        rigid_bars = self._unique_names(rigid_bar_names)
        if not nodes and not members and not rigid_bars:
            raise ValueError("Informe pelo menos um nó, membro ou barra rígida.")

        self._validate_existing_names(nodes, self.model.nodes, "nó")
        self._validate_existing_names(members, self.model.bars, "membro")
        self._validate_existing_names(rigid_bars, self.model.rigid_bars, "barra rígida")

        requested_members = set(members)
        requested_rigid_bars = set(rigid_bars)
        cascade_members: list[str] = []
        cascade_rigid_bars: list[str] = []
        if cascade:
            for node_name in nodes:
                cascade_members.extend(
                    member.name
                    for member in self.model.bars.values()
                    if node_name in (member.start_node, member.end_node)
                    and member.name not in requested_members
                )
                cascade_rigid_bars.extend(
                    rigid.name
                    for rigid in self.model.rigid_bars.values()
                    if node_name in (rigid.start_node, rigid.end_node)
                    and rigid.name not in requested_rigid_bars
                )
        members = self._unique_names((*members, *cascade_members))
        rigid_bars = self._unique_names((*rigid_bars, *cascade_rigid_bars))
        member_set = set(members)
        rigid_bar_set = set(rigid_bars)
        requested_node_set = set(nodes)

        blockers = [
            {
                "node": node_name,
                "members": [
                    member.name for member in self.model.bars.values()
                    if node_name in (member.start_node, member.end_node)
                    and member.name not in member_set
                ],
                "rigid_bars": [
                    rigid.name for rigid in self.model.rigid_bars.values()
                    if node_name in (rigid.start_node, rigid.end_node)
                    and rigid.name not in rigid_bar_set
                ],
            }
            for node_name in nodes
            if any(
                node_name in (member.start_node, member.end_node)
                and member.name not in member_set
                for member in self.model.bars.values()
            ) or any(
                node_name in (rigid.start_node, rigid.end_node)
                and rigid.name not in rigid_bar_set
                for rigid in self.model.rigid_bars.values()
            )
        ]
        deleted_actions = tuple(
            name for name, action in self.model.actions.items()
            if action.target in requested_node_set | member_set | rigid_bar_set
        )
        result: dict[str, object] = {
            "status": "preview" if dry_run else "blocked" if blockers else "deleted",
            "nodes": list(nodes),
            "members": list(members),
            "rigid_bars": list(rigid_bars),
            "actions": list(deleted_actions),
            "cascade_added": {
                "members": [name for name in members if name not in set(member_names)],
                "rigid_bars": [name for name in rigid_bars if name not in set(rigid_bar_names)],
            },
            "blocked": blockers,
        }
        if dry_run or blockers:
            return result

        for name in members:
            del self.model.bars[name]
        for name in rigid_bars:
            del self.model.rigid_bars[name]
        for name in nodes:
            del self.model.nodes[name]
        for name in deleted_actions:
            del self.model.actions[name]
        self.model._touch()
        return result

    @staticmethod
    def _unique_names(names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(name) for name in names))

    @staticmethod
    def _validate_existing_names(names, collection, label: str) -> None:
        missing = next((name for name in names if name not in collection), None)
        if missing is not None:
            raise ValueError(f"{label.capitalize()} '{missing}' não encontrado.")

    def resolve_node_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.nodes if name.casefold() == folded), None)

    def resolve_member_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.bars if name.casefold() == folded), None)

    def resolve_rigid_bar_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.rigid_bars if name.casefold() == folded), None)
