"""Construção e validação geométrica do contorno de uma futura placa.

As arestas de fechamento são apenas geométricas e não criam barras estruturais.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

Point = tuple[float, float, float]
Segment = tuple[Point, Point]


def plate_contour(
    segments: Iterable[tuple[Sequence[float], Sequence[float]]],
    *,
    close_automatically: bool = False,
    tolerance: float = 1e-8,
) -> tuple[Point, ...]:
    """Ordena as arestas em um único polígono plano simples.

    Quando solicitado, conecta sucessivamente os extremos mais próximos de
    componentes distintos e, por fim, fecha a cadeia resultante. Contornos
    ramificados, degenerados, não planos ou que se cruzam são recusados.
    """
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("A tolerância deve ser positiva e finita.")
    points: list[Point] = []
    neighbors: list[list[int]] = []

    def vertex(value: Sequence[float]) -> int:
        if len(value) != 3:
            raise ValueError("Cada extremidade deve possuir três coordenadas.")
        point = tuple(float(v) for v in value)
        if not all(math.isfinite(v) for v in point):
            raise ValueError("As coordenadas devem ser finitas.")
        for index, existing in enumerate(points):
            if math.dist(point, existing) <= tolerance:
                return index
        points.append(point)
        neighbors.append([])
        return len(points) - 1

    def connect(a: int, b: int) -> None:
        if a == b or b in neighbors[a]:
            raise ValueError("O contorno contém uma aresta nula ou repetida.")
        if len(neighbors[a]) >= 2 or len(neighbors[b]) >= 2:
            raise ValueError("O contorno possui uma ramificação.")
        neighbors[a].append(b)
        neighbors[b].append(a)

    for start, end in segments:
        connect(vertex(start), vertex(end))
    if len(points) < 3:
        raise ValueError("São necessárias ao menos três extremidades distintas.")

    def components() -> list[set[int]]:
        remaining = set(range(len(points)))
        groups = []
        while remaining:
            group, pending = set(), [next(iter(remaining))]
            while pending:
                current = pending.pop()
                if current in group:
                    continue
                group.add(current)
                pending.extend(neighbors[current])
            remaining.difference_update(group)
            groups.append(group)
        return groups

    groups = components()
    if close_automatically:
        while len(groups) > 1:
            choices = [
                (math.dist(points[a], points[b]), a, b)
                for i, group in enumerate(groups)
                for other in groups[i + 1:]
                for a in group if len(neighbors[a]) == 1
                for b in other if len(neighbors[b]) == 1
            ]
            if not choices:
                raise ValueError("Não é possível unir os contornos selecionados.")
            _, a, b = min(choices)
            connect(a, b)
            groups = components()
        ends = [i for i, adjacent in enumerate(neighbors) if len(adjacent) == 1]
        if len(ends) == 2:
            connect(*ends)
    if len(components()) != 1 or any(len(adjacent) != 2 for adjacent in neighbors):
        raise ValueError("As barras não formam um contorno fechado único.")

    ordered = [0]
    previous, current = -1, 0
    while True:
        next_vertex = next(n for n in neighbors[current] if n != previous)
        if next_vertex == ordered[0]:
            break
        if next_vertex in ordered:
            raise ValueError("O contorno não forma um polígono simples.")
        ordered.append(next_vertex)
        previous, current = current, next_vertex
    if len(ordered) != len(points):
        raise ValueError("O contorno deve formar um único polígono.")

    polygon = np.array([points[i] for i in ordered], dtype=float)
    centered = polygon - polygon[0]
    _, singular, basis = np.linalg.svd(centered, full_matrices=False)
    if len(singular) < 2 or singular[1] <= tolerance:
        raise ValueError("O contorno é degenerado.")
    if np.max(np.abs(centered @ basis[-1])) > tolerance:
        raise ValueError("As extremidades do contorno não são coplanares.")
    xy = centered @ basis[:2].T

    def cross(a, b, c):
        u, v = b - a, c - a
        return float(u[0] * v[1] - u[1] * v[0])

    def intersects(a, b, c, d):
        # Inclui contatos e sobreposições de arestas não adjacentes.
        scale = max(np.linalg.norm(b - a), np.linalg.norm(d - c), tolerance)
        eps = tolerance * scale
        def on_segment(p, q, r):
            return (abs(cross(p, q, r)) <= eps and
                    np.all(r >= np.minimum(p, q) - tolerance) and
                    np.all(r <= np.maximum(p, q) + tolerance))
        o1, o2, o3, o4 = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
        return ((o1 * o2 < -eps * eps and o3 * o4 < -eps * eps) or
                on_segment(a, b, c) or on_segment(a, b, d) or
                on_segment(c, d, a) or on_segment(c, d, b))

    count = len(xy)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if intersects(xy[i], xy[(i + 1) % count], xy[j], xy[(j + 1) % count]):
                raise ValueError("O contorno possui arestas que se cruzam.")
    return tuple(points[i] for i in ordered)
