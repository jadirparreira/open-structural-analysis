"""Agregado principal do modelo estrutural."""

from __future__ import annotations

import math
from dataclasses import replace

from .entities import Action, AnalysisResult, Bar, LoadCase, LoadCombination, Node
from .errors import DuplicateMemberError, DuplicateNodeCoordinatesError, EntityNotFoundError


class StructuralModel:
    """Mantém as entidades e garante invariantes em qualquer fluxo de entrada."""

    coordinate_tolerance = 1e-9

    def __init__(self, *, materials=None, material_types=None, sections=None) -> None:
        self.nodes: dict[str, Node] = {}
        self.bars: dict[str, Bar] = {}
        self.materials = {name: tuple(values) for name, values in (materials or {}).items()}
        self.material_types = dict(material_types or {})
        self.sections = {kind: list(items) for kind, items in (sections or {}).items()}
        self.actions: dict[str, Action] = {}
        self.load_cases: dict[str, LoadCase] = {}
        self.load_combinations: dict[str, LoadCombination] = {}
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
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 179:
            raise ValueError("A rotação do membro deve ser um número inteiro entre 0 e 179 graus.")
        return value

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

    def clear(self) -> None:
        self.nodes.clear(); self.bars.clear(); self.actions.clear()
        self.load_cases.clear(); self.load_combinations.clear(); self.analysis_results.clear()
        self._touch()
