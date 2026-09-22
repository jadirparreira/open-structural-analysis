"""Batched geometry for large structural scenes.

The domain keeps one entity per node/member.  The renderer deliberately does
not mirror that with one VTK actor per entity: repeated geometry is merged into
small, GPU-friendly batches while a cell-data index preserves picking.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, sin

import numpy as np
import pyvista as pv

from osa.sections import section_shape

from .local_axes_renderer import LocalAxesRenderer
from .solid_member_renderer import SolidMemberRenderer


def _empty_mesh() -> pv.PolyData:
    return pv.PolyData()


def _merge(parts: list[pv.PolyData]) -> pv.PolyData:
    return pv.merge(parts, merge_points=False) if parts else _empty_mesh()


def _rgb(color: str, factor: float = 1.0) -> np.ndarray:
    values = np.asarray(pv.Color(color).int_rgb, dtype=float) * factor
    return np.clip(values, 0, 255).astype(np.uint8)


def _line_mesh(
    segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]],
) -> pv.PolyData:
    if not segments:
        return _empty_mesh()
    points = np.empty((len(segments) * 2, 3), dtype=float)
    lines = np.empty((len(segments), 3), dtype=np.int64)
    element_indices = np.empty(len(segments), dtype=np.int32)
    colors = np.empty((len(segments), 3), dtype=np.uint8)
    for index, (start, end, element_index, color) in enumerate(segments):
        points[index * 2] = start
        points[index * 2 + 1] = end
        lines[index] = (2, index * 2, index * 2 + 1)
        element_indices[index] = element_index
        colors[index] = color
    mesh = pv.PolyData(points, lines=lines.ravel())
    mesh.cell_data["element_index"] = element_indices
    mesh.cell_data["rgb"] = colors
    return mesh


def _polyline_mesh(polylines: list[np.ndarray]) -> pv.PolyData:
    if not polylines:
        return _empty_mesh()
    points: list[np.ndarray] = []
    connectivity: list[int] = []
    offset = 0
    for polyline in polylines:
        points.append(polyline)
        connectivity.extend((len(polyline), *range(offset, offset + len(polyline))))
        offset += len(polyline)
    return pv.PolyData(np.vstack(points), lines=np.asarray(connectivity, dtype=np.int64))


def _transformed_mesh(
    source: pv.PolyData,
    start: np.ndarray,
    delta: np.ndarray,
    local_y: np.ndarray,
    local_z: np.ndarray,
) -> pv.PolyData:
    points = source.points
    world = (
        start
        + points[:, 0, None] * delta
        + points[:, 1, None] * local_y
        + points[:, 2, None] * local_z
    )
    arguments: dict[str, np.ndarray] = {}
    if source.n_faces:
        arguments["faces"] = source.faces
    if source.n_lines:
        arguments["lines"] = source.lines
    return pv.PolyData(world, **arguments)


@dataclass(slots=True)
class MemberBatch:
    names: tuple[str, ...]
    lines: pv.PolyData
    fallback_lines: pv.PolyData
    faces: pv.PolyData
    edges: pv.PolyData
    axes: tuple[pv.PolyData, pv.PolyData, pv.PolyData]
    releases: pv.PolyData
    outlines: dict[str, pv.PolyData]
    label_positions: np.ndarray


@dataclass(slots=True)
class NodeBatch:
    names: tuple[str, ...]
    geometry: pv.PolyData
    supports: pv.PolyData
    label_positions: np.ndarray


class BatchedMemberRenderer:
    """Build a handful of meshes for any number of structural members."""

    def __init__(self, solid_renderer: SolidMemberRenderer | None = None) -> None:
        self.solids = solid_renderer or SolidMemberRenderer()

    def build(self, model, marker_radius: float) -> MemberBatch:
        names = tuple(model.bars)
        line_segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]] = []
        fallback_segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]] = []
        face_parts: list[pv.PolyData] = []
        edge_parts: list[pv.PolyData] = []
        axis_segments: tuple[list, list, list] = ([], [], [])
        release_polylines: list[np.ndarray] = []
        outlines: dict[str, pv.PolyData] = {}
        label_positions = np.empty((len(names), 3), dtype=float)

        for element_index, member_name in enumerate(names):
            member = model.bars[member_name]
            start_node = model.nodes[member.start_node]
            end_node = model.nodes[member.end_node]
            start = np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
            delta = end - start
            color = _rgb(member.color)
            line_segments.append((start, end, element_index, color))
            label_positions[element_index] = (start + end) / 2.0 + (0.0, 0.0, marker_radius * 2.2)

            basis = LocalAxesRenderer.basis(start_node, end_node, rotation=member.rotation)
            if basis is None:
                fallback_segments.append((start, end, element_index, color))
                continue
            local_x, local_y, local_z = basis
            length = float(np.linalg.norm(delta))
            axis_scale = min(max(length * 0.2, 0.15), 1.0)
            midpoint = (start + end) / 2.0
            for axis_index, axis in enumerate((local_x, local_y, local_z)):
                axis_segments[axis_index].append(
                    (midpoint, midpoint + axis * axis_scale, element_index, np.zeros(3, dtype=np.uint8))
                )
            self._append_release_polylines(
                release_polylines, start, end, member.releases, marker_radius, basis,
            )

            try:
                shape = section_shape(member.section, member.geometry_dict(), arc_steps=12)
                if shape is None:
                    raise ValueError("Seção incompleta.")
                face_source = self.solids._mesh_for(shape)
                edge_source = self.solids._edge_mesh_for(shape)
                face = _transformed_mesh(face_source, start, delta, local_y, local_z)
                edge = _transformed_mesh(edge_source, start, delta, local_y, local_z)
            except (KeyError, TypeError, ValueError):
                fallback_segments.append((start, end, element_index, color))
                continue

            face.cell_data["element_index"] = np.full(face.n_cells, element_index, dtype=np.int32)
            face.cell_data["rgb"] = np.tile(color, (face.n_cells, 1))
            edge.cell_data["element_index"] = np.full(edge.n_cells, element_index, dtype=np.int32)
            edge.cell_data["rgb"] = np.tile(_rgb(member.color, 0.65), (edge.n_cells, 1))
            face_parts.append(face)
            edge_parts.append(edge)
            outlines[member_name] = edge

        faces = _merge(face_parts)
        if faces.n_cells:
            faces = faces.compute_normals(
                cell_normals=True,
                point_normals=False,
                split_vertices=False,
                consistent_normals=True,
                auto_orient_normals=True,
                inplace=False,
            )
        return MemberBatch(
            names=names,
            lines=_line_mesh(line_segments),
            fallback_lines=_line_mesh(fallback_segments),
            faces=faces,
            edges=_merge(edge_parts),
            axes=tuple(_line_mesh(segments) for segments in axis_segments),  # type: ignore[arg-type]
            releases=_polyline_mesh(release_polylines),
            outlines=outlines,
            label_positions=label_positions,
        )

    @staticmethod
    def _append_release_polylines(
        destination: list[np.ndarray],
        start: np.ndarray,
        end: np.ndarray,
        releases: tuple[bool, ...],
        radius: float,
        basis: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        if len(releases) != 12 or not any(releases):
            return
        local_x, local_y, local_z = basis
        for endpoint, inward, has_release in (
            (start, local_x, any(releases[index] for index in (0, 2, 4, 6, 8, 10))),
            (end, -local_x, any(releases[index] for index in (1, 3, 5, 7, 9, 11))),
        ):
            if not has_release:
                continue
            center = endpoint + inward * radius * 4.0
            circle_radius = radius * 1.05
            angles = np.linspace(0.0, 2.0 * pi, 32)
            destination.append(np.asarray([
                center + local_y * cos(angle) * circle_radius + local_z * sin(angle) * circle_radius
                for angle in angles
            ]))


class BatchedNodeRenderer:
    """Merge node markers and supports while retaining per-cell node identity."""

    def build(self, model, radius: float) -> NodeBatch:
        names = tuple(model.nodes)
        sphere = pv.Sphere(
            radius=radius,
            center=(0.0, 0.0, 0.0),
            theta_resolution=20,
            phi_resolution=12,
        )
        node_parts: list[pv.PolyData] = []
        support_parts: list[pv.PolyData] = []
        label_positions = np.empty((len(names), 3), dtype=float)
        source_normals = sphere.point_data.get("Normals")

        for element_index, node_name in enumerate(names):
            node = model.nodes[node_name]
            position = np.asarray((node.x, node.y, node.z), dtype=float)
            geometry = pv.PolyData(sphere.points + position, faces=sphere.faces)
            if source_normals is not None:
                geometry.point_data["Normals"] = source_normals
            geometry.cell_data["element_index"] = np.full(
                geometry.n_cells, element_index, dtype=np.int32,
            )
            node_parts.append(geometry)
            label_positions[element_index] = position + (0.0, 0.0, radius * 2.2)
            support = self._support_mesh(node, radius)
            if support is not None:
                support_parts.append(support)

        return NodeBatch(
            names=names,
            geometry=_merge(node_parts),
            supports=_merge(support_parts),
            label_positions=label_positions,
        )

    @staticmethod
    def _support_mesh(node, radius: float) -> pv.PolyData | None:
        if node.supports == (True, True, True, True, True, True):
            side = radius * 2.4
            return pv.Cube(
                center=(node.x, node.y, node.z - side / 2.0),
                x_length=side,
                y_length=side,
                z_length=side,
            )
        if node.supports == (True, True, True, False, False, False):
            height, half = radius * 4.0, radius * 1.5
            return pv.Pyramid(points=[
                (node.x - half, node.y - half, node.z - height),
                (node.x + half, node.y - half, node.z - height),
                (node.x + half, node.y + half, node.z - height),
                (node.x - half, node.y + half, node.z - height),
                (node.x, node.y, node.z),
            ])
        return None
