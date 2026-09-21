"""Entidades puras do domínio estrutural.

Este módulo não depende de Qt, VTK, PyVista ou PyNite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Support:
    dx: bool = False
    dy: bool = False
    dz: bool = False
    rx: bool = False
    ry: bool = False
    rz: bool = False

    @classmethod
    def from_tuple(cls, values: tuple[bool, ...]) -> Support:
        if len(values) != 6:
            raise ValueError("Uma restrição deve possuir seis graus de liberdade.")
        return cls(*(bool(value) for value in values))

    def as_tuple(self) -> tuple[bool, bool, bool, bool, bool, bool]:
        return self.dx, self.dy, self.dz, self.rx, self.ry, self.rz


@dataclass(frozen=True, slots=True)
class Node:
    name: str
    x: float
    y: float
    z: float
    supports: tuple[bool, bool, bool, bool, bool, bool] = (False,) * 6

    @property
    def support(self) -> Support:
        return Support.from_tuple(self.supports)


@dataclass(frozen=True, slots=True)
class Member:
    name: str
    start_node: str
    end_node: str
    material: str = "Indefinido"
    material_values: tuple[float, float, float, float] = (200.0, 76.9, 0.30, 7850.0)
    section: str = ""
    profile: str = ""
    section_geometry: tuple[tuple[str, float], ...] = ()
    rotation: int = 0
    releases: tuple[bool, ...] = (False,) * 12
    color: str = "#6e7781"

    def geometry_dict(self) -> dict[str, float]:
        return dict(self.section_geometry)


# Compatibilidade pública com o nome utilizado até agora.
Bar = Member


@dataclass(frozen=True, slots=True)
class Material:
    name: str
    kind: str
    elastic_modulus: float
    shear_modulus: float
    poisson_ratio: float
    density: float


@dataclass(frozen=True, slots=True)
class Section:
    name: str
    material_kind: str
    family: str
    parameters: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class Action:
    name: str
    kind: str
    target: str
    components: tuple[float, ...]
    load_case: str


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """Nome legível e sigla usada nas combinações de ações."""

    name: str
    abbreviation: str


@dataclass(frozen=True, slots=True)
class ActionGroup:
    """Conjunto nomeado de ações disponíveis para um modelo."""

    name: str
    actions: tuple[ActionDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadCase:
    name: str
    actions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoadCombination:
    name: str
    factors: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    model_revision: int
    load_reference: str
    node_results: dict[str, Any] = field(default_factory=dict)
    member_results: dict[str, Any] = field(default_factory=dict)
