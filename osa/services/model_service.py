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

    def create_rigid_bar(self, start_node: str, end_node: str):
        return self.model.add_rigid_bar(start_node, end_node)

    def set_reference_axes(self, axes) -> None:
        self.model.set_reference_axes(axes)

    def update_node(self, name: str, x: float, y: float, z: float):
        return self.model.update_node(name, x, y, z)

    def update_supports(self, name: str, supports: tuple[bool, ...]):
        return self.model.update_node_supports(name, supports)

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
                    member.material_values[3],
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

    def resolve_node_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.nodes if name.casefold() == folded), None)

    def resolve_member_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.bars if name.casefold() == folded), None)

    def resolve_rigid_bar_name(self, value: str) -> str | None:
        folded = value.strip().casefold()
        return next((name for name in self.model.rigid_bars if name.casefold() == folded), None)
