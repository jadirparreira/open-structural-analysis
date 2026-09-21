"""Geometria normalizada das seções transversais.

Este módulo mantém a representação da seção independente do PyVista. Os
contornos são definidos em milímetros e centrados no centroide geométrico;
o renderizador converte essa forma para a unidade espacial do modelo antes
de criar a malha 3D.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from math import atan2, ceil, cos, pi, radians, sin, sqrt

from .contours import (
    c_formed_svg_path,
    cartola_formed_svg_path,
    concrete_i_svg_path,
    concrete_l_svg_path,
    concrete_plus_svg_path,
    concrete_rectangular_hollow_svg_path,
    concrete_rectangular_svg_path,
    concrete_t_svg_path,
    concrete_u_svg_path,
    contour_points,
    l_formed_svg_path,
    rounded_rect_svg_path,
    t_svg_path,
    u_formed_svg_path,
    z_formed_svg_path,
)

Point = tuple[float, float]
Loop = tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class SectionShape:
    """Closed loops describing one section in its local ``y-z`` plane."""

    loops: tuple[Loop, ...]
    centroid: Point
    bounds: tuple[float, float, float, float]

    @property
    def signature(self) -> tuple[Loop, ...]:
        """Stable cache key for an equivalent normalized geometry."""
        return self.loops


_PATH_TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")


def _append_point(points: list[Point], point: Point) -> None:
    if not points or not _same_point(points[-1], point):
        points.append(point)


def _same_point(first: Point, second: Point, tolerance: float = 1e-9) -> bool:
    return abs(first[0] - second[0]) <= tolerance and abs(first[1] - second[1]) <= tolerance


def _line_points(current: Point, endpoint: Point) -> list[Point]:
    del current
    return [endpoint]


def _quadratic_points(current: Point, control: Point, endpoint: Point, steps: int) -> list[Point]:
    return [
        (
            (1.0 - t) ** 2 * current[0] + 2.0 * (1.0 - t) * t * control[0] + t**2 * endpoint[0],
            (1.0 - t) ** 2 * current[1] + 2.0 * (1.0 - t) * t * control[1] + t**2 * endpoint[1],
        )
        for index in range(1, steps + 1)
        for t in (index / steps,)
    ]


def _arc_points(
    start: Point,
    radii: Point,
    rotation_deg: float,
    large_arc: int,
    sweep: int,
    endpoint: Point,
    steps: int,
) -> list[Point]:
    """Sample an SVG elliptical arc using the SVG endpoint parameterization."""
    rx, ry = abs(radii[0]), abs(radii[1])
    if rx <= 1e-12 or ry <= 1e-12 or _same_point(start, endpoint):
        return _line_points(start, endpoint)

    phi = radians(rotation_deg % 360.0)
    cos_phi, sin_phi = cos(phi), sin(phi)
    dx = (start[0] - endpoint[0]) / 2.0
    dy = (start[1] - endpoint[1]) / 2.0
    x_prime = cos_phi * dx + sin_phi * dy
    y_prime = -sin_phi * dx + cos_phi * dy

    radius_scale = (x_prime * x_prime) / (rx * rx) + (y_prime * y_prime) / (ry * ry)
    if radius_scale > 1.0:
        scale = sqrt(radius_scale)
        rx *= scale
        ry *= scale

    numerator = max(
        0.0,
        (rx * rx * ry * ry) - (rx * rx * y_prime * y_prime) - (ry * ry * x_prime * x_prime),
    )
    denominator = rx * rx * y_prime * y_prime + ry * ry * x_prime * x_prime
    coefficient = sqrt(numerator / denominator) if denominator > 1e-20 else 0.0
    if bool(large_arc) == bool(sweep):
        coefficient = -coefficient

    center_prime_x = coefficient * (rx * y_prime / ry)
    center_prime_y = coefficient * (-ry * x_prime / rx)
    center = (
        cos_phi * center_prime_x - sin_phi * center_prime_y + (start[0] + endpoint[0]) / 2.0,
        sin_phi * center_prime_x + cos_phi * center_prime_y + (start[1] + endpoint[1]) / 2.0,
    )

    def unit_angle(ux: float, uy: float, vx: float, vy: float) -> float:
        return atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    ux = (x_prime - center_prime_x) / rx
    uy = (y_prime - center_prime_y) / ry
    vx = (-x_prime - center_prime_x) / rx
    vy = (-y_prime - center_prime_y) / ry
    start_angle = unit_angle(1.0, 0.0, ux, uy)
    delta_angle = unit_angle(ux, uy, vx, vy)
    if not sweep and delta_angle > 0.0:
        delta_angle -= 2.0 * pi
    elif sweep and delta_angle < 0.0:
        delta_angle += 2.0 * pi

    samples = max(2, ceil(abs(delta_angle) / (pi / 2.0) * steps))
    return [
        (
            center[0] + rx * cos_phi * cos(angle) - ry * sin_phi * sin(angle),
            center[1] + rx * sin_phi * cos(angle) + ry * cos_phi * sin(angle),
        )
        for index in range(1, samples + 1)
        for angle in (start_angle + delta_angle * index / samples,)
    ]


def _svg_loops(path: str, arc_steps: int = 12) -> tuple[Loop, ...]:
    """Parse the limited absolute SVG path dialect emitted by ``contours``."""
    tokens = _PATH_TOKEN.findall(path)
    index = 0
    command: str | None = None
    current = (0.0, 0.0)
    subpath_start = current
    active: list[Point] = []
    loops: list[Loop] = []

    def number() -> float:
        nonlocal index
        if index >= len(tokens) or tokens[index].isalpha():
            raise ValueError("Caminho SVG incompleto.")
        value = float(tokens[index])
        index += 1
        return value

    def finish_loop() -> None:
        nonlocal active
        if active and _same_point(active[0], active[-1]):
            active.pop()
        if len(active) >= 3:
            loops.append(tuple(active))
        active = []

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index].upper()
            index += 1
        if command is None:
            raise ValueError("Caminho SVG sem comando inicial.")
        if command == "Z":
            _append_point(active, subpath_start)
            current = subpath_start
            finish_loop()
            command = None
            continue
        if command == "M":
            if active:
                finish_loop()
            current = (number(), number())
            subpath_start = current
            active = [current]
            command = "L"
            continue
        if command == "H":
            endpoint = (number(), current[1])
            _append_point(active, endpoint)
            current = endpoint
        elif command == "V":
            endpoint = (current[0], number())
            _append_point(active, endpoint)
            current = endpoint
        elif command == "L":
            endpoint = (number(), number())
            _append_point(active, endpoint)
            current = endpoint
        elif command == "Q":
            control = (number(), number())
            endpoint = (number(), number())
            for point in _quadratic_points(current, control, endpoint, max(4, arc_steps // 2)):
                _append_point(active, point)
            current = endpoint
        elif command == "A":
            radii = (number(), number())
            rotation = number()
            large_arc = int(number())
            sweep = int(number())
            endpoint = (number(), number())
            for point in _arc_points(
                current, radii, rotation, large_arc, sweep, endpoint, max(4, arc_steps // 2)
            ):
                _append_point(active, point)
            current = endpoint
        else:
            raise ValueError(f"Comando SVG não suportado: {command}.")

    if active:
        finish_loop()
    return tuple(loops)


def _rectangle(width: float, height: float) -> Loop:
    half_width, half_height = float(width) / 2.0, float(height) / 2.0
    return ((-half_width, -half_height), (half_width, -half_height),
            (half_width, half_height), (-half_width, half_height))


def _circle(diameter: float, steps: int = 32) -> Loop:
    radius = float(diameter) / 2.0
    return tuple(
        (radius * cos(2.0 * pi * index / steps), radius * sin(2.0 * pi * index / steps))
        for index in range(steps)
    )


def _raw_loops(family: str, geometry: dict[str, float], arc_steps: int) -> tuple[Loop, ...] | None:
    if family in {"W Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "I Laminado"}:
        points = contour_points(family, geometry, arc_steps=arc_steps)
        return (points,) if points else None
    if family == "T Laminado":
        return _svg_loops(
            t_svg_path(
                float(geometry["d"]), float(geometry["bf"]), float(geometry["tw"]),
                float(geometry["tf"]), geometry.get("r1"), geometry.get("r2"),
            ),
            arc_steps,
        )
    if family == "U Formado":
        return _svg_loops(u_formed_svg_path(float(geometry["d"]), float(geometry["bf"]), float(geometry["t"])), arc_steps)
    if family == "C Formado":
        return _svg_loops(c_formed_svg_path(float(geometry["d"]), float(geometry["bf"]), float(geometry["c"]), float(geometry["t"])), arc_steps)
    if family == "Z Formado":
        return _svg_loops(z_formed_svg_path(float(geometry["d"]), float(geometry["bf"]), float(geometry["t"])), arc_steps)
    if family == "L Formado":
        return _svg_loops(l_formed_svg_path(float(geometry["d"]), float(geometry["bf"]), float(geometry["t"])), arc_steps)
    if family == "Cartola Formado":
        return _svg_loops(cartola_formed_svg_path(float(geometry["d"]), float(geometry["bf"]), float(geometry["c"]), float(geometry["t"])), arc_steps)
    if family in {"Tubular Circular"}:
        outer = float(geometry["D"])
        inner = outer - 2.0 * float(geometry["t"])
        return (_circle(outer), _circle(inner)) if inner > 0.0 else None
    if family in {"Barra Circular", "Barra Redonda"}:
        return (_circle(float(geometry["d"])),)
    if family in {"Tubular Quadrado"}:
        side, thickness = float(geometry["b"]), float(geometry["t"])
        if side <= 4.0 * thickness:
            raise ValueError("O lado externo deve ser maior que quatro vezes a espessura.")
        outer = rounded_rect_svg_path(-side / 2.0, -side / 2.0, side, side, 2.0 * thickness)
        inner_side = side - 2.0 * thickness
        inner = rounded_rect_svg_path(
            -inner_side / 2.0, -inner_side / 2.0, inner_side, inner_side, thickness,
        )
        return _svg_loops(outer, arc_steps) + _svg_loops(inner, arc_steps)
    if family in {"Tubular Retangular"}:
        width, height, thickness = float(geometry["b"]), float(geometry["h"]), float(geometry["t"])
        if width <= 4.0 * thickness or height <= 4.0 * thickness:
            raise ValueError("As dimensões externas devem ser maiores que quatro vezes a espessura.")
        outer = rounded_rect_svg_path(-width / 2.0, -height / 2.0, width, height, 2.0 * thickness)
        inner_width, inner_height = width - 2.0 * thickness, height - 2.0 * thickness
        inner = rounded_rect_svg_path(
            -inner_width / 2.0, -inner_height / 2.0,
            inner_width, inner_height, thickness,
        )
        return _svg_loops(outer, arc_steps) + _svg_loops(inner, arc_steps)
    if family in {"Barra Quadrada", "Quadrada"}:
        side = float(geometry["b"])
        return (_rectangle(side, side),)
    if family == "Barra Retangular":
        return (_rectangle(float(geometry["b"]), float(geometry["h"])),)
    if family == "Retangular":
        return _svg_loops(concrete_rectangular_svg_path(float(geometry["b"]), float(geometry["h"])), arc_steps)
    if family == "Circular":
        return (_circle(float(geometry["d"])),)
    if family == "Tipo L":
        return _svg_loops(concrete_l_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])), arc_steps)
    if family == "Tipo T":
        return _svg_loops(concrete_t_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])), arc_steps)
    if family == "Tipo I":
        return _svg_loops(concrete_i_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])), arc_steps)
    if family == "Tipo U":
        return _svg_loops(concrete_u_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])), arc_steps)
    if family == "Tipo +":
        return _svg_loops(concrete_plus_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])), arc_steps)
    if family == "Retangular Vazado":
        return _svg_loops(
            concrete_rectangular_hollow_svg_path(float(geometry["b"]), float(geometry["h"]), float(geometry["t"])),
            arc_steps,
        )
    if family == "Circular Vazado":
        outer = float(geometry["d"])
        inner = outer - 2.0 * float(geometry["t"])
        return (_circle(outer), _circle(inner)) if inner > 0.0 else None
    return None


def _loop_area_centroid(loop: Iterable[Point]) -> tuple[float, Point]:
    points = tuple(loop)
    twice_area = sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, points[1:] + points[:1])
    )
    if abs(twice_area) <= 1e-12:
        raise ValueError("O contorno possui área nula.")
    centroid = (
        sum((first[0] + second[0]) * cross for cross, (first, second) in zip(
            (first[0] * second[1] - second[0] * first[1] for first, second in zip(points, points[1:] + points[:1])),
            zip(points, points[1:] + points[:1]),
        )) / (3.0 * twice_area),
        sum((first[1] + second[1]) * cross for cross, (first, second) in zip(
            (first[0] * second[1] - second[0] * first[1] for first, second in zip(points, points[1:] + points[:1])),
            zip(points, points[1:] + points[:1]),
        )) / (3.0 * twice_area),
    )
    return twice_area / 2.0, centroid


def _normalize_loop(loop: Loop) -> Loop:
    points: list[Point] = []
    for point in loop:
        _append_point(points, point)
    if len(points) > 1 and _same_point(points[0], points[-1]):
        points.pop()
    return tuple(points)


def section_shape(
    family: str,
    geometry: dict[str, float],
    *,
    arc_steps: int = 12,
) -> SectionShape | None:
    """Resolve a member section into centered, closed 2D loops."""
    loops = _raw_loops(family, geometry, arc_steps)
    if not loops:
        return None
    clean_loops = tuple(_normalize_loop(loop) for loop in loops)
    if any(len(loop) < 3 for loop in clean_loops):
        raise ValueError("O contorno da seção precisa possuir pelo menos três pontos.")

    areas_and_centroids = tuple(_loop_area_centroid(loop) for loop in clean_loops)
    outer_area = abs(areas_and_centroids[0][0])
    total_area = outer_area - sum(abs(area) for area, _centroid in areas_and_centroids[1:])
    if total_area <= 1e-12:
        raise ValueError("A seção possui área útil nula.")
    outer_centroid = areas_and_centroids[0][1]
    inner_centroids = areas_and_centroids[1:]
    centroid = (
        (outer_area * outer_centroid[0] - sum(abs(area) * center[0] for area, center in inner_centroids))
        / total_area,
        (outer_area * outer_centroid[1] - sum(abs(area) * center[1] for area, center in inner_centroids))
        / total_area,
    )
    centered_loops = tuple(
        tuple((point[0] - centroid[0], point[1] - centroid[1]) for point in loop)
        for loop in clean_loops
    )
    all_points = tuple(point for loop in centered_loops for point in loop)
    bounds = (
        min(point[0] for point in all_points),
        max(point[0] for point in all_points),
        min(point[1] for point in all_points),
        max(point[1] for point in all_points),
    )
    return SectionShape(centered_loops, centroid, bounds)
