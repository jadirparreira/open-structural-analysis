"""Projection and hidden-line removal for vector detailing views."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil, cos, floor, radians, sin, sqrt

import numpy as np
import pyvista as pv


@dataclass(frozen=True)
class _ProjectedTriangle:
    points: np.ndarray
    depths: np.ndarray
    depth_plane: np.ndarray
    bounds: tuple[float, float, float, float]


def projected_visible_intervals(
    start: tuple[float, float],
    end: tuple[float, float],
    edge_depth_start: float,
    edge_depth_end: float,
    triangles: Iterable[tuple[np.ndarray, np.ndarray]],
    *,
    depth_tolerance: float = 1e-7,
) -> list[tuple[float, float]]:
    """Return visible parameter intervals for one projected vector edge."""
    start_point = np.asarray(start, dtype=float)
    end_point = np.asarray(end, dtype=float)
    projected_triangles: list[_ProjectedTriangle] = []
    for triangle_points, triangle_depths in triangles:
        triangle_points = np.asarray(triangle_points, dtype=float)
        triangle_depths = np.asarray(triangle_depths, dtype=float)
        area = _cross2(
            triangle_points[1] - triangle_points[0],
            triangle_points[2] - triangle_points[0],
        )
        if abs(area) <= 1e-12:
            continue
        if _segment_triangle_interval(start_point, end_point, triangle_points, area) is None:
            continue
        augmented = np.column_stack((triangle_points, np.ones(3, dtype=float)))
        try:
            depth_plane = np.linalg.solve(augmented, triangle_depths)
        except np.linalg.LinAlgError:
            continue
        projected_triangles.append(
            _ProjectedTriangle(
                points=triangle_points,
                depths=triangle_depths,
                depth_plane=depth_plane,
                bounds=(
                    float(triangle_points[:, 0].min()),
                    float(triangle_points[:, 0].max()),
                    float(triangle_points[:, 1].min()),
                    float(triangle_points[:, 1].max()),
                ),
            )
        )
    return _visible_intervals_for_triangles(
        start_point,
        end_point,
        float(edge_depth_start),
        float(edge_depth_end),
        projected_triangles,
        depth_tolerance=depth_tolerance,
    )


def visible_segments_from_meshes(
    meshes: Iterable[pv.PolyData],
    camera_direction: Iterable[float],
    view_up: Iterable[float],
    rotation_degrees: float = 0.0,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Create 2D visible edge segments from a set of clipped solid meshes.

    Coordinates are in model units in the drawing plane. Faces are used only
    to resolve occlusion; the returned data contains 2D linework only.
    """
    meshes = tuple(meshes)
    if not meshes:
        return []
    camera_direction = _unit(np.asarray(tuple(camera_direction), dtype=float))
    view_direction = -camera_direction
    base_up = _unit(np.asarray(tuple(view_up), dtype=float))
    angle = radians(-float(rotation_degrees))
    rotated_up = _rotate_about_axis(base_up, view_direction, angle)
    right = _unit(np.cross(view_direction, rotated_up))
    rotated_up = _unit(rotated_up)

    triangles: list[_ProjectedTriangle] = []
    projected_edges: list[tuple[np.ndarray, np.ndarray, float, float]] = []
    unique_edges: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()

    for mesh in meshes:
        surface = mesh.triangulate().compute_normals(
            cell_normals=True,
            point_normals=False,
            consistent_normals=True,
            auto_orient_normals=True,
        )
        surface_points = np.asarray(surface.points, dtype=float)
        projected = np.column_stack((surface_points @ right, surface_points @ rotated_up))
        depths = surface_points @ camera_direction
        faces = np.asarray(surface.faces, dtype=np.int64)
        if faces.size:
            cells = faces.reshape((-1, 4))
            triangle_indices = cells[cells[:, 0] == 3, 1:4]
            face_vectors = np.cross(
                surface_points[triangle_indices[:, 1]] - surface_points[triangle_indices[:, 0]],
                surface_points[triangle_indices[:, 2]] - surface_points[triangle_indices[:, 0]],
            )
            face_lengths = np.linalg.norm(face_vectors, axis=1)
            face_normals = np.divide(
                face_vectors,
                face_lengths[:, None],
                out=np.zeros_like(face_vectors),
                where=face_lengths[:, None] > 1e-12,
            )
            for indices in triangle_indices:
                tri_points = projected[indices]
                area = _cross2(tri_points[1] - tri_points[0], tri_points[2] - tri_points[0])
                if abs(area) <= 1e-12:
                    continue
                augmented = np.column_stack((tri_points, np.ones(3, dtype=float)))
                try:
                    depth_plane = np.linalg.solve(augmented, depths[indices])
                except np.linalg.LinAlgError:
                    continue
                triangles.append(
                    _ProjectedTriangle(
                        points=tri_points,
                        depths=depths[indices],
                        depth_plane=depth_plane,
                        bounds=(
                            float(tri_points[:, 0].min()),
                            float(tri_points[:, 0].max()),
                            float(tri_points[:, 1].min()),
                            float(tri_points[:, 1].max()),
                        ),
                    )
                )

            edge_indices = _view_dependent_surface_edges(
                triangle_indices,
                face_normals,
                camera_direction,
            )
            edge_projected = np.column_stack((projected[:, 0], projected[:, 1]))
            for a, b in edge_indices:
                # Exact duplicate 3D edges from coincident solid surfaces need
                # only one stroke. Distinct nearby edges remain independent.
                key_points = sorted(
                    (
                        tuple(np.round(surface_points[a], 10)),
                        tuple(np.round(surface_points[b], 10)),
                    )
                )
                if key_points[0] == key_points[1]:
                    continue
                key = (key_points[0], key_points[1])
                if key in unique_edges:
                    continue
                unique_edges.add(key)
                projected_edges.append(
                    (
                        edge_projected[a],
                        edge_projected[b],
                        float(depths[a]),
                        float(depths[b]),
                    )
                )

    if not triangles or not projected_edges:
        return []
    index = _TriangleGrid(triangles)
    visible_segments = []
    unique_projected: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()
    for start, end, depth_start, depth_end in projected_edges:
        candidate_triangles = index.query_segment(start, end)
        if not candidate_triangles:
            intervals = [(0.0, 1.0)]
        else:
            intervals = _visible_intervals_for_triangles(
                start,
                end,
                depth_start,
                depth_end,
                (triangles[i] for i in candidate_triangles),
            )
        for lower, upper in intervals:
            if upper - lower <= 1e-8:
                continue
            point_a = start + (end - start) * lower
            point_b = start + (end - start) * upper
            key_points = sorted(
                (tuple(np.round(point_a, 9)), tuple(np.round(point_b, 9)))
            )
            key = (key_points[0], key_points[1])
            if key_points[0] != key_points[1] and key not in unique_projected:
                unique_projected.add(key)
                visible_segments.append((key_points[0], key_points[1]))
    return visible_segments


def _visible_intervals_for_triangles(
    start: np.ndarray,
    end: np.ndarray,
    depth_start: float,
    depth_end: float,
    triangles: Iterable[_ProjectedTriangle],
    *,
    depth_tolerance: float = 1e-7,
) -> list[tuple[float, float]]:
    blocked: list[tuple[float, float]] = []
    for triangle in triangles:
        interval = _segment_triangle_interval(start, end, triangle.points)
        if interval is None:
            continue
        lower, upper = interval
        edge_delta = depth_end - depth_start
        difference_at_lower = (
            float(triangle.depth_plane @ (*_point_at(start, end, lower), 1.0))
            - (depth_start + edge_delta * lower)
            - depth_tolerance
        )
        difference_at_upper = (
            float(triangle.depth_plane @ (*_point_at(start, end, upper), 1.0))
            - (depth_start + edge_delta * upper)
            - depth_tolerance
        )
        if difference_at_lower > 0.0 and difference_at_upper > 0.0:
            blocked.append((lower, upper))
        elif difference_at_lower > 0.0:
            blocked.append(
                (_root_between(lower, upper, difference_at_lower, difference_at_upper), upper)
            )
        elif difference_at_upper > 0.0:
            blocked.append(
                (lower, _root_between(lower, upper, difference_at_lower, difference_at_upper))
            )
    return _complement_intervals(blocked)


class _TriangleGrid:
    """Uniform projected grid for limiting visibility checks to nearby faces."""

    def __init__(self, triangles: list[_ProjectedTriangle]) -> None:
        self._triangles = triangles
        bounds = np.asarray([triangle.bounds for triangle in triangles], dtype=float)
        self._min_x = float(bounds[:, 0].min())
        self._max_x = float(bounds[:, 1].max())
        self._min_y = float(bounds[:, 2].min())
        self._max_y = float(bounds[:, 3].max())
        longest_span = max(self._max_x - self._min_x, self._max_y - self._min_y, 1e-6)
        self._cell_size = longest_span / min(96, max(16, int(sqrt(len(triangles)))))
        self._cells: dict[tuple[int, int], list[int]] = {}
        self._large: list[int] = []
        for index, (min_x, max_x, min_y, max_y) in enumerate(bounds):
            x0, y0 = self._cell(min_x, min_y)
            x1, y1 = self._cell(max_x, max_y)
            cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
            if cell_count > 256:
                self._large.append(index)
                continue
            for grid_x in range(x0, x1 + 1):
                for grid_y in range(y0, y1 + 1):
                    self._cells.setdefault((grid_x, grid_y), []).append(index)

    def query_segment(self, start: np.ndarray, end: np.ndarray) -> set[int]:
        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        distance_in_cells = max(abs(dx), abs(dy)) / max(self._cell_size, 1e-12)
        steps = max(1, ceil(distance_in_cells * 2.0))
        candidates = set(self._large)
        for step in range(steps + 1):
            point = start + (end - start) * (step / steps)
            grid_x, grid_y = self._cell(float(point[0]), float(point[1]))
            for offset_x in (-1, 0, 1):
                for offset_y in (-1, 0, 1):
                    candidates.update(self._cells.get((grid_x + offset_x, grid_y + offset_y), ()))
        return candidates

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            floor((x - self._min_x) / self._cell_size),
            floor((y - self._min_y) / self._cell_size),
        )


def _segment_triangle_interval(
    start: np.ndarray,
    end: np.ndarray,
    triangle: np.ndarray,
    signed_area: float | None = None,
) -> tuple[float, float] | None:
    area = signed_area
    if area is None:
        area = _cross2(triangle[1] - triangle[0], triangle[2] - triangle[0])
    if abs(area) <= 1e-12:
        return None
    direction = 1.0 if area > 0.0 else -1.0
    lower, upper = 0.0, 1.0
    segment = end - start
    for index in range(3):
        vertex = triangle[index]
        edge = triangle[(index + 1) % 3] - vertex
        at_start = direction * _cross2(edge, start - vertex)
        slope = direction * _cross2(edge, segment)
        if abs(slope) <= 1e-14:
            if at_start < -1e-10:
                return None
            continue
        transition = -at_start / slope
        if slope > 0.0:
            lower = max(lower, transition)
        else:
            upper = min(upper, transition)
        if lower > upper + 1e-10:
            return None
    return max(0.0, lower), min(1.0, upper)


def _complement_intervals(blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not blocked:
        return [(0.0, 1.0)]
    blocked.sort()
    merged: list[list[float]] = []
    for lower, upper in blocked:
        lower = max(0.0, lower)
        upper = min(1.0, upper)
        if upper - lower <= 1e-10:
            continue
        if merged and lower <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], upper)
        else:
            merged.append([lower, upper])
    visible: list[tuple[float, float]] = []
    cursor = 0.0
    for lower, upper in merged:
        if lower > cursor + 1e-9:
            visible.append((cursor, lower))
        cursor = max(cursor, upper)
    if cursor < 1.0 - 1e-9:
        visible.append((cursor, 1.0))
    return visible


def _root_between(lower: float, upper: float, value_lower: float, value_upper: float) -> float:
    denominator = value_lower - value_upper
    if abs(denominator) <= 1e-14:
        return (lower + upper) / 2.0
    return lower + (upper - lower) * value_lower / denominator


def _view_dependent_surface_edges(
    triangle_indices: np.ndarray,
    face_normals: np.ndarray,
    camera_direction: np.ndarray,
) -> list[tuple[int, int]]:
    """Keep mesh boundaries, sharp creases, and view-dependent silhouettes."""
    adjacent_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, (first, second, third) in enumerate(triangle_indices):
        for start, end in ((first, second), (second, third), (third, first)):
            edge = (int(min(start, end)), int(max(start, end)))
            adjacent_faces.setdefault(edge, []).append(face_index)

    crease_cosine = cos(radians(25.0))
    grazing_tolerance = 1e-8
    result = []
    for edge, faces in adjacent_faces.items():
        if len(faces) == 1 or len(faces) > 2:
            result.append(edge)
            continue

        normals = face_normals[faces]
        facing = normals @ camera_direction
        silhouette = (
            float(facing.min()) <= grazing_tolerance
            and float(facing.max()) >= -grazing_tolerance
            and (float(facing.max()) > grazing_tolerance or float(facing.min()) < -grazing_tolerance)
        )
        sharp_crease = float(np.dot(normals[0], normals[1])) < crease_cosine
        if silhouette or sharp_crease:
            result.append(edge)
    return result


def _point_at(start: np.ndarray, end: np.ndarray, parameter: float) -> np.ndarray:
    return start + (end - start) * parameter


def _cross2(first: np.ndarray, second: np.ndarray) -> float:
    return float(first[0] * second[1] - first[1] * second[0])


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        raise ValueError("A orientação da vista deve definir vetores não nulos.")
    return vector / length


def _rotate_about_axis(vector: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    axis = _unit(axis)
    return (
        vector * cos(angle)
        + np.cross(axis, vector) * sin(angle)
        + axis * np.dot(axis, vector) * (1.0 - cos(angle))
    )
