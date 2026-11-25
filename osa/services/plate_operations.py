"""Geometric operations on planar plate contours."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .plate_contour import plate_contour

Point = tuple[float, float, float]


def _project_to_edge(point: Sequence[float], start: Point, end: Point) -> tuple[Point, float, float]:
    vector = tuple(b - a for a, b in zip(start, end))
    length_squared = sum(value * value for value in vector)
    if length_squared <= 1e-24:
        return start, 0.0, math.dist(point, start)
    fraction = sum((value - a) * direction for value, a, direction in zip(point, start, vector)) / length_squared
    fraction = min(1.0, max(0.0, fraction))
    projected = tuple(a + fraction * direction for a, direction in zip(start, vector))
    return projected, fraction, math.dist(point, projected)


def split_plate_contour(
    contour: Sequence[Point], first: Sequence[float], second: Sequence[float], *, tolerance: float = 0.002,
) -> tuple[tuple[Point, ...], tuple[Point, ...]]:
    """Split a plate contour along a chord whose endpoints lie on its boundary."""
    points = tuple(tuple(float(value) for value in point) for point in contour)
    if len(points) < 3:
        raise ValueError("A placa não possui um contorno válido para dividir.")

    def locate(point: Sequence[float]):
        candidates = []
        for index, (start, end) in enumerate(zip(points, (*points[1:], points[0]))):
            projected, fraction, distance = _project_to_edge(point, start, end)
            candidates.append((distance, index, fraction, projected))
        distance, edge_index, fraction, projected = min(candidates)
        if distance > tolerance:
            raise ValueError("Cada extremidade da linha deve capturar uma borda da placa.")
        for index, vertex in enumerate(points):
            if math.dist(projected, vertex) <= tolerance:
                return ("vertex", index, vertex)
        return ("edge", edge_index, fraction, projected)

    locations = (locate(first), locate(second))
    snapped = (locations[0][-1], locations[1][-1])
    if math.dist(*snapped) <= tolerance:
        raise ValueError("As extremidades da linha devem ser diferentes.")

    expanded: list[Point] = []
    for edge_index, start in enumerate(points):
        expanded.append(start)
        inserted = [
            (location[2], location[3])
            for location in locations
            if location[0] == "edge" and location[1] == edge_index
            and tolerance < location[2] < 1.0 - tolerance
        ]
        expanded.extend(point for _fraction, point in sorted(inserted))

    def expanded_index(location) -> int:
        point = location[-1]
        return min(range(len(expanded)), key=lambda index: math.dist(point, expanded[index]))

    first_index, second_index = (expanded_index(location) for location in locations)
    if first_index == second_index:
        raise ValueError("As extremidades da linha devem capturar pontos diferentes da borda.")

    def path(start_index: int, end_index: int) -> tuple[Point, ...]:
        result = [expanded[start_index]]
        current = start_index
        while current != end_index:
            current = (current + 1) % len(expanded)
            result.append(expanded[current])
        return tuple(result)

    first_path = path(first_index, second_index)
    second_path = path(second_index, first_index)
    first_contour = plate_contour(zip(first_path, (*first_path[1:], first_path[0])))
    second_contour = plate_contour(zip(second_path, (*second_path[1:], second_path[0])))
    return first_contour, second_contour


def merge_plate_contours(
    first: Sequence[Point], second: Sequence[Point], *, tolerance: float = 1e-8,
) -> tuple[tuple[Point, ...], tuple[tuple[Point, Point], ...]]:
    """Return the boundary union, including partial collinear edge overlaps."""
    first_points = tuple(tuple(float(value) for value in point) for point in first)
    second_points = tuple(tuple(float(value) for value in point) for point in second)
    first_edges = tuple(zip(first_points, (*first_points[1:], first_points[0])))
    second_edges = tuple(zip(second_points, (*second_points[1:], second_points[0])))
    first_overlaps: list[list[tuple[float, float]]] = [[] for _ in first_edges]
    second_overlaps: list[list[tuple[float, float]]] = [[] for _ in second_edges]
    shared_edges: list[tuple[Point, Point]] = []

    def projection_fraction(point: Point, start: Point, vector: Point) -> float:
        length_squared = sum(value * value for value in vector)
        return sum((value - origin) * direction for value, origin, direction in zip(
            point, start, vector,
        )) / length_squared

    def point_at(start: Point, vector: Point, fraction: float) -> Point:
        return tuple(origin + fraction * direction for origin, direction in zip(start, vector))

    for first_index, (a, b) in enumerate(first_edges):
        first_vector = tuple(y - x for x, y in zip(a, b))
        first_length = math.sqrt(sum(value * value for value in first_vector))
        if first_length <= tolerance:
            continue
        for second_index, (c, d) in enumerate(second_edges):
            second_vector = tuple(y - x for x, y in zip(c, d))
            second_length = math.sqrt(sum(value * value for value in second_vector))
            if second_length <= tolerance:
                continue
            # Shared boundaries must be collinear and directed oppositely;
            # equal direction means the plates overlap on the same side.
            cross = (
                first_vector[1] * second_vector[2] - first_vector[2] * second_vector[1],
                first_vector[2] * second_vector[0] - first_vector[0] * second_vector[2],
                first_vector[0] * second_vector[1] - first_vector[1] * second_vector[0],
            )
            if math.sqrt(sum(value * value for value in cross)) > tolerance * first_length * second_length:
                continue
            if sum(x * y for x, y in zip(first_vector, second_vector)) >= 0:
                continue
            if any(
                math.dist(point, point_at(a, first_vector, projection_fraction(point, a, first_vector))) > tolerance
                for point in (c, d)
            ):
                continue

            first_c = projection_fraction(c, a, first_vector)
            first_d = projection_fraction(d, a, first_vector)
            low, high = max(0.0, min(first_c, first_d)), min(1.0, max(first_c, first_d))
            if (high - low) * first_length <= tolerance:
                continue
            overlap_start = point_at(a, first_vector, low)
            overlap_end = point_at(a, first_vector, high)
            second_start_fraction = projection_fraction(overlap_start, c, second_vector)
            second_end_fraction = projection_fraction(overlap_end, c, second_vector)
            first_overlaps[first_index].append((low, high))
            second_overlaps[second_index].append((
                min(second_start_fraction, second_end_fraction),
                max(second_start_fraction, second_end_fraction),
            ))
            shared_edges.append((overlap_start, overlap_end))

    if not shared_edges:
        raise ValueError("As placas precisam compartilhar uma borda colinear para serem unidas.")

    def remaining_segments(edges, overlaps):
        segments = []
        for (start, end), intervals in zip(edges, overlaps):
            vector = tuple(b - a for a, b in zip(start, end))
            cuts = sorted({0.0, 1.0, *(value for interval in intervals for value in interval)})
            for low, high in zip(cuts, cuts[1:]):
                if (high - low) * math.sqrt(sum(value * value for value in vector)) <= tolerance:
                    continue
                midpoint = (low + high) * 0.5
                if any(begin - 1e-10 <= midpoint <= finish + 1e-10 for begin, finish in intervals):
                    continue
                segments.append((point_at(start, vector, low), point_at(start, vector, high)))
        return segments

    segments = remaining_segments(first_edges, first_overlaps)
    segments.extend(remaining_segments(second_edges, second_overlaps))
    if len(segments) < 3:
        raise ValueError("As placas selecionadas não formam uma união válida.")
    unique_shared = []
    for edge in shared_edges:
        if not any(
            (math.dist(edge[0], existing[0]) <= tolerance and math.dist(edge[1], existing[1]) <= tolerance)
            or (math.dist(edge[0], existing[1]) <= tolerance and math.dist(edge[1], existing[0]) <= tolerance)
            for existing in unique_shared
        ):
            unique_shared.append(edge)
    return plate_contour(segments), tuple(unique_shared)
