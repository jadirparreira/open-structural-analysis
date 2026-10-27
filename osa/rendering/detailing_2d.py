"""Projection and hidden-line removal for vector detailing views."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from math import ceil, cos, floor, radians, sin, sqrt
from time import sleep

import numpy as np
import pyvista as pv


# Treat sub-micron depth differences as coincident surfaces. Endpoint
# alignment comes from picked VTK faces and can leave a few tenths of a
# micrometre of numerical drift; a smaller tolerance incorrectly hides the
# aligned member's contact edge in the vector drawing.
_DEPTH_TOLERANCE = 5e-7


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
    depth_tolerance: float = _DEPTH_TOLERANCE,
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
    *,
    feature_edge_meshes: Iterable[pv.PolyData] | None = None,
    ignored_interface_planes: Iterable[Iterable[tuple[np.ndarray, np.ndarray, float]]] | None = None,
    feature_edge_interface_planes: Iterable[Iterable[tuple[np.ndarray, np.ndarray, float]]] | None = None,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Create 2D visible edge segments from a set of clipped solid meshes.

    Coordinates are in model units in the drawing plane. Faces are used only
    to resolve occlusion; the returned data contains 2D linework only. When
    feature-edge meshes are provided, they supply the geometric creases and
    boundaries while the triangulated solids supply only view-dependent
    silhouettes.
    """
    meshes = tuple(meshes)
    if not meshes:
        return []
    use_feature_edges = feature_edge_meshes is not None
    feature_edge_meshes = tuple(feature_edge_meshes or ())
    ignored_interface_planes = tuple(ignored_interface_planes or ())
    feature_edge_interface_planes = tuple(feature_edge_interface_planes or ())
    camera_direction = _unit(np.asarray(tuple(camera_direction), dtype=float))
    view_direction = -camera_direction
    base_up = _unit(np.asarray(tuple(view_up), dtype=float))
    angle = radians(-float(rotation_degrees))
    rotated_up = _rotate_about_axis(base_up, view_direction, angle)
    right = _unit(np.cross(view_direction, rotated_up))
    rotated_up = _unit(rotated_up)

    triangles: list[_ProjectedTriangle] = []
    projected_edge_groups: dict[
        tuple[tuple[float, ...], tuple[float, ...]],
        list[tuple[np.ndarray, np.ndarray, float, float]],
    ] = {}
    unique_edges: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()

    for mesh_number, mesh in enumerate(meshes):
        interface_planes = (
            ignored_interface_planes[mesh_number]
            if mesh_number < len(ignored_interface_planes) else ()
        )
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
            if use_feature_edges:
                face_normals = np.asarray(surface.cell_data["Normals"], dtype=float)
                if len(face_normals) != len(triangle_indices):
                    face_normals = np.divide(
                        face_vectors,
                        face_lengths[:, None],
                        out=np.zeros_like(face_vectors),
                        where=face_lengths[:, None] > 1e-12,
                    )
            else:
                face_normals = np.divide(
                    face_vectors,
                    face_lengths[:, None],
                    out=np.zeros_like(face_vectors),
                    where=face_lengths[:, None] > 1e-12,
                )
            for triangle_number, indices in enumerate(triangle_indices):
                if triangle_number % 256 == 0:
                    sleep(0)
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
                silhouettes_only=use_feature_edges,
            )
            edge_projected = np.column_stack((projected[:, 0], projected[:, 1]))
            for a, b in edge_indices:
                if _edge_is_on_interface(surface_points[a], surface_points[b], interface_planes):
                    continue
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
                start, end = edge_projected[a], edge_projected[b]
                depth_start, depth_end = float(depths[a]), float(depths[b])
                start_key = tuple(np.round(start, 9))
                end_key = tuple(np.round(end, 9))
                if end_key < start_key:
                    start, end = end, start
                    start_key, end_key = end_key, start_key
                    depth_start, depth_end = depth_end, depth_start
                group_key = (start_key, end_key)
                depth_layers = projected_edge_groups.setdefault(group_key, [])
                if any(
                    other_start_depth >= depth_start - 1e-7
                    and other_end_depth >= depth_end - 1e-7
                    for _, _, other_start_depth, other_end_depth in depth_layers
                ):
                    continue
                depth_layers[:] = [
                    layer
                    for layer in depth_layers
                    if not (
                        depth_start >= layer[2] - 1e-7
                        and depth_end >= layer[3] - 1e-7
                    )
                ]
                depth_layers.append((start, end, depth_start, depth_end))

    for edge_number, edge_mesh in enumerate(feature_edge_meshes):
        interface_planes = (
            feature_edge_interface_planes[edge_number]
            if edge_number < len(feature_edge_interface_planes) else ()
        )
        points = np.asarray(edge_mesh.points, dtype=float)
        lines = np.asarray(edge_mesh.lines, dtype=np.int64)
        offset = 0
        while offset < len(lines):
            count = int(lines[offset])
            indices = lines[offset + 1 : offset + count + 1]
            for first, second in pairwise(indices):
                a, b = int(first), int(second)
                if _edge_is_on_interface(points[a], points[b], interface_planes):
                    continue
                key_points = sorted(
                    (tuple(np.round(points[a], 10)), tuple(np.round(points[b], 10)))
                )
                if key_points[0] == key_points[1]:
                    continue
                key = (key_points[0], key_points[1])
                if key in unique_edges:
                    continue
                unique_edges.add(key)
                start = np.asarray((np.dot(points[a], right), np.dot(points[a], rotated_up)))
                end = np.asarray((np.dot(points[b], right), np.dot(points[b], rotated_up)))
                depth_start = float(np.dot(points[a], camera_direction))
                depth_end = float(np.dot(points[b], camera_direction))
                start_key = tuple(np.round(start, 9))
                end_key = tuple(np.round(end, 9))
                if end_key < start_key:
                    start, end = end, start
                    start_key, end_key = end_key, start_key
                    depth_start, depth_end = depth_end, depth_start
                group_key = (start_key, end_key)
                depth_layers = projected_edge_groups.setdefault(group_key, [])
                if any(
                    other_start_depth >= depth_start - 1e-7
                    and other_end_depth >= depth_end - 1e-7
                    for _, _, other_start_depth, other_end_depth in depth_layers
                ):
                    continue
                depth_layers[:] = [
                    layer
                    for layer in depth_layers
                    if not (
                        depth_start >= layer[2] - 1e-7
                        and depth_end >= layer[3] - 1e-7
                    )
                ]
                depth_layers.append((start, end, depth_start, depth_end))
            offset += count + 1

    projected_edges = [
        edge for depth_layers in projected_edge_groups.values() for edge in depth_layers
    ]

    if not triangles or not projected_edges:
        return []
    index = _TriangleGrid(
        triangles,
        correct_crossing_intervals=use_feature_edges,
    )
    visible_segments = []
    unique_projected: set[tuple[tuple[float, ...], tuple[float, ...]]] = set()
    for edge_number, (start, end, depth_start, depth_end) in enumerate(projected_edges):
        if edge_number % 4 == 0:
            sleep(0)
        candidate_triangles = index.query_segment(
            start, end, depth_start=depth_start, depth_end=depth_end
        )
        if not candidate_triangles:
            intervals = [(0.0, 1.0)]
        else:
            intervals = index.visible_intervals(
                candidate_triangles, start, end, depth_start, depth_end
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


def _edge_is_on_interface(
    start: np.ndarray,
    end: np.ndarray,
    planes: Iterable[tuple[np.ndarray, np.ndarray, float]],
) -> bool:
    """Return whether a full edge lies on a grouped-member interface plane."""
    for origin, normal, tolerance in planes:
        if (
            abs(float(np.dot(start - origin, normal))) <= tolerance
            and abs(float(np.dot(end - origin, normal))) <= tolerance
        ):
            return True
    return False


def _visible_intervals_for_triangles(
    start: np.ndarray,
    end: np.ndarray,
    depth_start: float,
    depth_end: float,
    triangles: Iterable[_ProjectedTriangle],
    *,
    depth_tolerance: float = _DEPTH_TOLERANCE,
    correct_crossing_intervals: bool = True,
) -> list[tuple[float, float]]:
    triangles = tuple(triangles)
    if not triangles:
        return [(0.0, 1.0)]
    return _visible_intervals_for_arrays(
        start,
        end,
        depth_start,
        depth_end,
        np.asarray([triangle.points for triangle in triangles], dtype=float),
        np.asarray([triangle.depth_plane for triangle in triangles], dtype=float),
        np.asarray([triangle.bounds for triangle in triangles], dtype=float),
        depth_tolerance=depth_tolerance,
        correct_crossing_intervals=correct_crossing_intervals,
    )


def _visible_intervals_for_arrays(
    start: np.ndarray,
    end: np.ndarray,
    depth_start: float,
    depth_end: float,
    points: np.ndarray,
    planes: np.ndarray,
    bounds: np.ndarray | None = None,
    *,
    depth_tolerance: float = _DEPTH_TOLERANCE,
    correct_crossing_intervals: bool = True,
) -> list[tuple[float, float]]:
    if not len(points):
        return [(0.0, 1.0)]
    edge_min_x = min(float(start[0]), float(end[0]))
    edge_max_x = max(float(start[0]), float(end[0]))
    edge_min_y = min(float(start[1]), float(end[1]))
    edge_max_y = max(float(start[1]), float(end[1]))
    if bounds is not None:
        candidate_mask = (
            (bounds[:, 1] >= edge_min_x)
            & (bounds[:, 0] <= edge_max_x)
            & (bounds[:, 3] >= edge_min_y)
            & (bounds[:, 2] <= edge_max_y)
        )
        if not candidate_mask.any():
            return [(0.0, 1.0)]
        points = points[candidate_mask]
        planes = planes[candidate_mask]

    area = _cross2_batch(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    direction = np.where(area > 0.0, 1.0, -1.0)
    valid = np.abs(area) > 1e-12
    lower = np.zeros(len(points), dtype=float)
    upper = np.ones(len(points), dtype=float)
    segment = end - start
    for index in range(3):
        vertex = points[:, index]
        edge = points[:, (index + 1) % 3] - vertex
        at_start = direction * _cross2_batch(edge, start - vertex)
        slope = direction * _cross2_batch(edge, segment)
        parallel = np.abs(slope) <= 1e-14
        valid &= ~(parallel & (at_start < -1e-10))
        transition = np.divide(
            -at_start,
            slope,
            out=np.zeros_like(at_start),
            where=~parallel,
        )
        # Parallel boundaries have no crossing parameter. Tiny signed roundoff
        # must not turn the placeholder zero into an interval boundary: doing
        # so discards the occluding face for longitudinal edges parallel to it.
        lower = np.where(~parallel & (slope > 0.0), np.maximum(lower, transition), lower)
        upper = np.where(~parallel & (slope < 0.0), np.minimum(upper, transition), upper)
    valid &= lower <= upper + 1e-10
    valid &= (upper >= 0.0) & (lower <= 1.0)
    if not valid.any():
        return [(0.0, 1.0)]

    points = points[valid]
    planes = planes[valid]
    lower = np.clip(lower[valid], 0.0, 1.0)
    upper = np.clip(upper[valid], 0.0, 1.0)
    edge_delta = depth_end - depth_start
    at_lower = start + segment * lower[:, None]
    at_upper = start + segment * upper[:, None]
    difference_at_lower = (
        planes[:, 0] * at_lower[:, 0]
        + planes[:, 1] * at_lower[:, 1]
        + planes[:, 2]
        - (depth_start + edge_delta * lower)
        - depth_tolerance
    )
    difference_at_upper = (
        planes[:, 0] * at_upper[:, 0]
        + planes[:, 1] * at_upper[:, 1]
        + planes[:, 2]
        - (depth_start + edge_delta * upper)
        - depth_tolerance
    )
    lower_hidden = difference_at_lower > 0.0
    upper_hidden = difference_at_upper > 0.0
    blocked_mask = lower_hidden | upper_hidden
    if not blocked_mask.any():
        return [(0.0, 1.0)]

    roots = np.divide(
        lower * difference_at_upper - upper * difference_at_lower,
        difference_at_upper - difference_at_lower,
        out=(lower + upper) / 2.0,
        where=np.abs(difference_at_upper - difference_at_lower) > 1e-14,
    )
    if correct_crossing_intervals:
        # If the lower endpoint is hidden, the occluded part runs from
        # ``lower`` to the crossing. If the upper endpoint is hidden, it runs
        # from the crossing to ``upper``.
        blocked_lower = np.where(upper_hidden & ~lower_hidden, roots, lower)
        blocked_upper = np.where(lower_hidden & ~upper_hidden, roots, upper)
    else:
        # Retain the original planar-view behavior while the revised
        # crossing rule is limited to isometric drawings.
        blocked_lower = np.where(lower_hidden & ~upper_hidden, roots, lower)
        blocked_upper = np.where(upper_hidden & ~lower_hidden, roots, upper)
    blocked = zip(
        blocked_lower[blocked_mask].tolist(), blocked_upper[blocked_mask].tolist()
    )
    return _complement_intervals(list(blocked))


class _TriangleGrid:
    """Uniform projected grid for limiting visibility checks to nearby faces."""

    def __init__(
        self,
        triangles: list[_ProjectedTriangle],
        *,
        correct_crossing_intervals: bool = False,
    ) -> None:
        self._triangles = triangles
        self._correct_crossing_intervals = correct_crossing_intervals
        bounds = np.asarray([triangle.bounds for triangle in triangles], dtype=float)
        self._bounds = bounds
        self._points = np.asarray([triangle.points for triangle in triangles], dtype=float)
        self._planes = np.asarray(
            [triangle.depth_plane for triangle in triangles], dtype=float
        )
        self._max_depths = np.asarray(
            [float(triangle.depths.max()) for triangle in triangles], dtype=float
        )
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

    def query_segment(
        self,
        start: np.ndarray,
        end: np.ndarray,
        *,
        depth_start: float | None = None,
        depth_end: float | None = None,
    ) -> list[int]:
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
        if not candidates:
            return []
        candidate_indices = np.fromiter(candidates, dtype=np.intp)
        candidate_bounds = self._bounds[candidate_indices]
        overlaps = (
            (candidate_bounds[:, 1] >= min(start[0], end[0]))
            & (candidate_bounds[:, 0] <= max(start[0], end[0]))
            & (candidate_bounds[:, 3] >= min(start[1], end[1]))
            & (candidate_bounds[:, 2] <= max(start[1], end[1]))
        )
        if depth_start is not None and depth_end is not None:
            minimum_edge_depth = min(depth_start, depth_end) - 1e-7
            overlaps &= self._max_depths[candidate_indices] > minimum_edge_depth
        return candidate_indices[overlaps].tolist()

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (
            floor((x - self._min_x) / self._cell_size),
            floor((y - self._min_y) / self._cell_size),
        )

    def visible_intervals(
        self,
        indices: list[int],
        start: np.ndarray,
        end: np.ndarray,
        depth_start: float,
        depth_end: float,
    ) -> list[tuple[float, float]]:
        selected = np.asarray(indices, dtype=np.intp)
        return _visible_intervals_for_arrays(
            start,
            end,
            depth_start,
            depth_end,
            self._points[selected],
            self._planes[selected],
            correct_crossing_intervals=self._correct_crossing_intervals,
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
    *,
    silhouettes_only: bool = False,
) -> list[tuple[int, int]]:
    """Keep mesh boundaries, sharp creases, and view-dependent silhouettes."""
    adjacent_faces: dict[tuple[int, int], list[int]] = {}
    for face_index, (first, second, third) in enumerate(triangle_indices):
        if face_index % 256 == 0:
            sleep(0)
        for start, end in ((first, second), (second, third), (third, first)):
            edge = (int(min(start, end)), int(max(start, end)))
            adjacent_faces.setdefault(edge, []).append(face_index)

    crease_cosine = cos(radians(25.0))
    grazing_tolerance = 1e-8
    result = []
    for edge, faces in adjacent_faces.items():
        if len(faces) == 1 or len(faces) > 2:
            if not silhouettes_only:
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
        if silhouette or (sharp_crease and not silhouettes_only):
            result.append(edge)
    return result


def _point_at(start: np.ndarray, end: np.ndarray, parameter: float) -> np.ndarray:
    return start + (end - start) * parameter


def _cross2(first: np.ndarray, second: np.ndarray) -> float:
    return float(first[0] * second[1] - first[1] * second[0])


def _cross2_batch(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return first[..., 0] * second[..., 1] - first[..., 1] * second[..., 0]


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
