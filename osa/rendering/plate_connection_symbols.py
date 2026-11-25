"""Repeated plate edge connection marks in world coordinates."""
from __future__ import annotations

import numpy as np
import pyvista as pv


def plate_connection_symbols(model, plate, *, radius=0.06, display_contour=None, solid=False):
    points = np.asarray(plate.contour if display_contour is None else display_contour, dtype=float)
    if len(points) < 3:
        return pv.PolyData()
    _, _, basis = np.linalg.svd(points - points[0], full_matrices=False)
    normal = basis[-1]
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    area_vector = sum((np.cross(a - points[0], b - points[0])
                       for a, b in zip(points, np.roll(points, -1, axis=0))), np.zeros(3))
    winding = 1 if area_vector @ normal >= 0 else -1
    radius = max(float(radius), 0.005)
    lift = (plate.thickness_mm / 2000 if solid else 0) + radius * 0.15
    paths = []
    for index, start in enumerate(points):
        state = dict(plate.edge_connections).get(index, "fixed")
        if state == "free":
            continue
        bars = model.plate_edge_bars(plate.name, index, include_rigid=True)
        if not bars:
            continue
        vector = points[(index + 1) % len(points)] - start
        length = float(np.linalg.norm(vector))
        if length <= radius * 2:
            continue
        tangent = vector / length
        inward = np.cross(normal, tangent) * winding
        # Mark only the portion actually overlapping a boundary bar.
        analytical_start = np.asarray(plate.contour[index])
        spans = []
        for name in bars:
            member = model.bars.get(name) or model.rigid_bars[name]
            distances = [
                (np.array((node.x, node.y, node.z)) - analytical_start) @ tangent
                for node in (model.nodes[member.start_node], model.nodes[member.end_node])
            ]
            spans.append((max(0, min(distances)), min(length, max(distances))))
        merged = []
        for a, b in sorted(spans):
            if merged and a <= merged[-1][1] + 1e-7:
                merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
            else:
                merged.append((a, b))
        for a, b in merged:
            margin = min(radius * 2.5, (b - a) * 0.15)
            a, b = a + margin, b - margin
            origin = start + inward * radius * 2.5 + normal * lift
            if state == "fixed":
                paths.append(np.array((origin + tangent * a, origin + tangent * b)))
            else:
                count = max(1, min(100, int((b - a) / (radius * 4))))
                step = (b - a) / count
                for dash in range(count):
                    paths.append(np.array((origin + tangent * (a + dash * step),
                                           origin + tangent * (a + (dash + 0.6) * step))))
    if not paths:
        return pv.PolyData()
    vertices, lines, offset = [], [], 0
    for path in paths:
        vertices.extend(path)
        lines.extend((len(path), *range(offset, offset + len(path))))
        offset += len(path)
    return pv.PolyData(np.asarray(vertices), lines=np.asarray(lines, dtype=np.int64))
