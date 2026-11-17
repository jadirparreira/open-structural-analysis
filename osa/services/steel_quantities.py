"""Steel plate quantities from model contours and node components."""
from __future__ import annotations

import math
from itertools import pairwise

import numpy as np


def _plate_width_and_area(contour) -> tuple[float, float]:
    """Return long-side width (m) and contour area (m²)."""
    points = np.asarray(contour, dtype=float)
    relative = points - points[0]
    area_vector = np.cross(relative, np.roll(relative, -1, axis=0)).sum(axis=0)
    magnitude = float(np.linalg.norm(area_vector))
    if magnitude < 1e-12:
        return 0.0, 0.0
    edges = np.roll(relative, -1, axis=0) - relative
    u = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    u = u / np.linalg.norm(u)
    v = np.cross(area_vector / magnitude, u)
    local = np.column_stack((relative @ u, relative @ v))
    vertices = sorted(set(map(tuple, local)))

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower, upper = [], []
    for point in vertices:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(vertices):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    best_area, width = math.inf, 0.0
    for first, last in pairwise([*hull, hull[0]]):
        axis = np.asarray(last) - first
        axis /= np.linalg.norm(axis)
        transverse = (-axis[1], axis[0])
        a = float(np.ptp(local @ axis))
        b = float(np.ptp(local @ transverse))
        if a * b < best_area * (1.0 - 1e-10):
            best_area, width = a * b, max(a, b)
    return width, magnitude / 2.0


def steel_plate_rows(model) -> list[dict]:
    """Aggregate steel plates by long dimension, thickness and material.

    Nonrectangular contours use area/width as their equivalent strip length,
    so linear mass times length always matches their actual contour mass.
    Fasteners, wood and other nonplate component parts are excluded.
    """
    grouped = {}

    def add(width_m, area_m2, thickness_mm, material):
        if model.material_types.get(material) != "Aço" or min(width_m, area_m2, thickness_mm) <= 0:
            return
        width_mm = round(width_m * 1000.0, 6)
        thickness_mm = round(float(thickness_mm), 6)
        key = width_mm, thickness_mm, material
        if key not in grouped:
            try:
                density = float(model.materials[material][3]) / 9.80665e-3
                linear_mass = width_mm * thickness_mm * 1e-6 * density
                if not math.isfinite(linear_mass) or linear_mass <= 0:
                    linear_mass = None
            except (KeyError, IndexError, TypeError, ValueError):
                linear_mass = None
            width_text = f"{width_mm:.6f}".rstrip("0").rstrip(".")
            thickness_text = f"{thickness_mm:.6f}".rstrip("0").rstrip(".")
            grouped[key] = {"plate": f"CH {width_text} x {thickness_text}",
                            "material": material, "linear_mass": linear_mass, "length": 0.0}
        grouped[key]["length"] += area_m2 / (width_mm / 1000.0)

    for plate in model.plates.values():
        if model.material_types.get(plate.material) != "Aço":
            continue
        width, area = _plate_width_and_area(plate.contour)
        add(width, area, plate.thickness_mm, plate.material)
    for node in model.nodes.values():
        component = node.component
        if component is None or component.component_id not in {"base_plate", "stair_plate"}:
            continue
        parameters = dict(component.parameters)
        base = component.component_id == "base_plate"
        width = float(parameters.get("largura_mm", 300.0 if base else 200.0)) / 1000.0
        length = float(parameters.get("comprimento_mm", 300.0)) / 1000.0
        add(max(width, length), width * length,
            float(parameters.get("espessura_mm", 20.0 if base else 6.3)),
            str(parameters.get("material_chapa", "ASTM A36")))
    rows = [grouped[key] for key in sorted(grouped)]
    for row in rows:
        row["total_mass"] = row["linear_mass"] * row["length"] if row["linear_mass"] is not None else None
    return rows
