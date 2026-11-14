"""Registry for node-component types supplied by the application."""

from __future__ import annotations

import math

from .entities import NodeComponentDefinition

BASE_PLATE_PLANES = ("XY+", "XY-", "XZ+", "XZ-", "YZ+", "YZ-")
STAIR_WOOD_THICKNESS_MM = 20.0


def base_plate_anchor_offsets(parameters: dict[str, object]) -> tuple[tuple[float, float], ...]:
    """Return perimeter bolt locations, preserving the four corners first."""
    width = float(parameters.get("largura_mm", 300.0))
    length = float(parameters.get("comprimento_mm", 300.0))
    distance = float(parameters.get("distancia_a_mm", 50.0))
    count_a = max(2, int(float(parameters.get("fixadores_lado_a", 2))))
    count_b = max(2, int(float(parameters.get("fixadores_lado_b", 2))))
    xs = tuple(
        -width / 2.0 + distance
        + (width - 2.0 * distance) * index / (count_a - 1)
        for index in range(count_a)
    )
    ys = tuple(
        -length / 2.0 + distance
        + (length - 2.0 * distance) * index / (count_b - 1)
        for index in range(count_b)
    )
    corners = ((xs[0], ys[0]), (xs[-1], ys[0]), (xs[-1], ys[-1]), (xs[0], ys[-1]))
    perimeter = (
        tuple((x, ys[0]) for x in xs[1:-1])
        + tuple((xs[-1], y) for y in ys[1:-1])
        + tuple((x, ys[-1]) for x in reversed(xs[1:-1]))
        + tuple((xs[0], y) for y in reversed(ys[1:-1]))
    )
    return corners + perimeter


def default_hook_headings(parameters: dict[str, object]) -> tuple[float, ...]:
    """Return outward-facing global headings for the bolt locations."""
    headings = []
    for x, y in base_plate_anchor_offsets(parameters):
        heading = math.degrees(math.atan2(y, x)) % 360.0 if math.hypot(x, y) > 1e-12 else 0.0
        headings.append(heading)
    return tuple(headings)


# Component implementations register their definitions here.
NODE_COMPONENTS: tuple[NodeComponentDefinition, ...] = (
    NodeComponentDefinition(
        component_id="base_plate",
        name="Chapa de base/topo",
        interacts_with_model=False,
        has_3d_representation=True,
        parametric=True,
        parameters=(
            ("largura_mm", 300.0),
            ("comprimento_mm", 300.0),
            ("deslocamento_a_mm", 0.0),
            ("deslocamento_b_mm", 0.0),
            ("espessura_mm", 20.0),
            ("rotacao_deg", 0.0),
            ("fixador", "Reto"),
            ("diametro_mm", 16.0),
            ("comprimento_fixador_mm", 300.0),
            ("embutimento_mm", 150.0),
            ("perna_mm", 200.0),
            ("rotacao_gancho_deg", 0.0),
            ("fixadores_lado_a", 2),
            ("fixadores_lado_b", 2),
            ("distancia_a_mm", 50.0),
            ("plano", "XY+"),
        ),
    ),
    NodeComponentDefinition(
        component_id="stair_plate",
        name="Chapa degrau",
        interacts_with_model=False,
        has_3d_representation=True,
        parametric=True,
        parameters=(
            ("largura_mm", 200.0),
            ("comprimento_mm", 300.0),
            ("deslocamento_a_mm", 0.0),
            ("deslocamento_b_mm", 0.0),
            ("espessura_mm", 6.3),
            ("rotacao_deg", 0.0),
            ("madeira_largura_mm", 280.0),
            ("madeira_comprimento_mm", 800.0),
            ("madeira_deslocamento_a_mm", 0.0),
            ("madeira_deslocamento_b_mm", 0.0),
            ("madeira_espessura_mm", 20.0),
        ),
    ),
)


def node_components() -> tuple[NodeComponentDefinition, ...]:
    return NODE_COMPONENTS


def node_component_definition(component_id: str) -> NodeComponentDefinition | None:
    return next(
        (item for item in NODE_COMPONENTS if item.component_id == component_id), None,
    )
