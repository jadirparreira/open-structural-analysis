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
from .support_renderer import build_support_mesh


def has_semirigid_member_end(member, endpoint: str) -> bool:
    """Return whether one member end has an active rotational semirigidity."""
    positions = (0, 2, 4) if endpoint == "start" else (1, 3, 5)
    return any(0 < member.rotation_flexibility_percent[index] < 100 for index in positions)


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
    silhouette_faces_by_color: dict[tuple[int, int, int], pv.PolyData]
    axes: tuple[pv.PolyData, pv.PolyData, pv.PolyData]
    releases: pv.PolyData
    outlines: dict[str, pv.PolyData]
    silhouette_sources: dict[str, pv.PolyData]
    silhouette_member_colors: dict[str, tuple[int, int, int]]
    label_positions: np.ndarray


@dataclass(slots=True)
class NodeBatch:
    names: tuple[str, ...]
    geometry: pv.PolyData
    supports: pv.PolyData
    label_positions: np.ndarray


class BatchedRigidBarRenderer:
    """Build the line-only representation used by idealized rigid bars."""

    COLOR = "#374151"

    def build(self, model) -> tuple[tuple[str, ...], pv.PolyData]:
        names = tuple(model.rigid_bars)
        segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]] = []
        color = _rgb(self.COLOR)
        for element_index, name in enumerate(names):
            rigid = model.rigid_bars[name]
            start_node = model.nodes[rigid.start_node]
            end_node = model.nodes[rigid.end_node]
            segments.append((
                np.asarray((start_node.x, start_node.y, start_node.z), dtype=float),
                np.asarray((end_node.x, end_node.y, end_node.z), dtype=float),
                element_index,
                color,
            ))
        return names, _line_mesh(segments)


class BatchedMemberRenderer:
    """Build a handful of meshes for any number of structural members."""

    _silhouette_sections = frozenset({
        "Tubular Circular",
        "Barra Circular",
        "Circular",
        "Circular Vazado",
    })

    def __init__(self, solid_renderer: SolidMemberRenderer | None = None) -> None:
        self.solids = solid_renderer or SolidMemberRenderer()

    def build(self, model, marker_radius: float) -> MemberBatch:
        names = tuple(model.bars)
        line_segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]] = []
        fallback_segments: list[tuple[np.ndarray, np.ndarray, int, np.ndarray]] = []
        face_points: list[np.ndarray] = []
        face_cells: list[int] = []
        face_indices: list[int] = []
        face_colors: list[np.ndarray] = []
        edge_points: list[np.ndarray] = []
        edge_cells: list[int] = []
        edge_indices: list[int] = []
        edge_colors: list[np.ndarray] = []
        face_point_count = 0
        edge_point_count = 0
        axis_segments: tuple[list, list, list] = ([], [], [])
        release_polylines: list[np.ndarray] = []
        outlines: dict[str, pv.PolyData] = {}
        silhouette_sources: dict[str, pv.PolyData] = {}
        silhouette_member_colors: dict[str, tuple[int, int, int]] = {}
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
            base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
            if base_basis is None:
                fallback_segments.append((start, end, element_index, color))
                continue
            _base_x, base_local_y, base_local_z = base_basis
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

            # Os deslocamentos das faces sólidas são exclusivamente visuais:
            # valores positivos aumentam o comprimento nas extremidades e
            # valores negativos o reduzem. Linhas, eixos locais e liberações
            # continuam referenciando os nós analíticos originais.
            solid_start = start.copy()
            solid_end = end.copy()
            offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
            if len(offsets) == 2:
                candidate_start = start - local_x * float(offsets[0])
                candidate_end = end + local_x * float(offsets[1])
                if float(np.dot(candidate_end - candidate_start, local_x)) > 1e-9:
                    solid_start, solid_end = candidate_start, candidate_end
            section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
            solid_origin = solid_start.copy()
            if len(section_offsets) == 2:
                solid_origin += (
                    base_local_y * float(section_offsets[0])
                    + base_local_z * float(section_offsets[1])
                )
            solid_delta = solid_end - solid_start

            try:
                shape = section_shape(member.section, member.geometry_dict(), arc_steps=12)
                if shape is None:
                    raise ValueError("Seção incompleta.")
                face_source = self.solids._mesh_for(shape)
                edge_source = self.solids._edge_mesh_for(shape)
                face = _transformed_mesh(face_source, solid_origin, solid_delta, local_y, local_z)
                edge = _transformed_mesh(edge_source, solid_origin, solid_delta, local_y, local_z)
            except (KeyError, TypeError, ValueError):
                fallback_segments.append((start, end, element_index, color))
                continue

            face_offset = face_point_count
            face_points.append(face.points)
            self._append_cells(face_cells, face.faces, face_offset)
            face_indices.extend([element_index] * face.n_cells)
            face_colors.extend([color] * face.n_cells)
            face_point_count += len(face.points)

            edge_offset = edge_point_count
            edge_points.append(edge.points)
            self._append_cells(edge_cells, edge.lines, edge_offset)
            edge_indices.extend([element_index] * edge.n_cells)
            edge_colors.extend([_rgb(member.color, 0.65)] * edge.n_cells)
            edge_point_count += len(edge.points)
            outlines[member_name] = edge
            if member.section in self._silhouette_sections:
                silhouette_sources[member_name] = face
                silhouette_member_colors[member_name] = tuple(int(channel) for channel in color)

        faces = (
            pv.PolyData(
                np.vstack(face_points),
                faces=np.asarray(face_cells, dtype=np.int64),
            )
            if face_points else _empty_mesh()
        )
        if faces.n_cells:
            faces.cell_data["element_index"] = np.asarray(face_indices, dtype=np.int32)
            faces.cell_data["rgb"] = np.asarray(face_colors, dtype=np.uint8)
        if faces.n_cells:
            faces = faces.compute_normals(
                cell_normals=True,
                point_normals=False,
                split_vertices=False,
                consistent_normals=True,
                auto_orient_normals=True,
                inplace=False,
            )
        edges = (
            pv.PolyData(
                np.vstack(edge_points),
                lines=np.asarray(edge_cells, dtype=np.int64),
            )
            if edge_points else _empty_mesh()
        )
        if edges.n_cells:
            edges.cell_data["element_index"] = np.asarray(edge_indices, dtype=np.int32)
            edges.cell_data["rgb"] = np.asarray(edge_colors, dtype=np.uint8)
        silhouette_faces_by_color = self._build_silhouette_faces_by_color(
            silhouette_sources, silhouette_member_colors,
        )
        return MemberBatch(
            names=names,
            lines=_line_mesh(line_segments),
            fallback_lines=_line_mesh(fallback_segments),
            faces=faces,
            edges=edges,
            silhouette_faces_by_color=silhouette_faces_by_color,
            axes=tuple(_line_mesh(segments) for segments in axis_segments),  # type: ignore[arg-type]
            releases=_polyline_mesh(release_polylines),
            outlines=outlines,
            silhouette_sources=silhouette_sources,
            silhouette_member_colors=silhouette_member_colors,
            label_positions=label_positions,
        )

    def update_silhouette_color(
        self, batch: MemberBatch, member_name: str, color: np.ndarray,
    ) -> None:
        """Rebuild only the color groups used by the silhouette pass."""
        if member_name not in batch.silhouette_sources:
            return
        batch.silhouette_member_colors[member_name] = tuple(
            int(channel) for channel in np.asarray(color, dtype=np.uint8)
        )
        batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
            batch.silhouette_sources, batch.silhouette_member_colors,
        )

    def _build_silhouette_faces_by_color(
        self,
        sources: dict[str, pv.PolyData],
        member_colors: dict[str, tuple[int, int, int]],
    ) -> dict[tuple[int, int, int], pv.PolyData]:
        points_by_color: dict[tuple[int, int, int], list[np.ndarray]] = {}
        cells_by_color: dict[tuple[int, int, int], list[int]] = {}
        point_counts: dict[tuple[int, int, int], int] = {}
        for member_name, source in sources.items():
            color = member_colors[member_name]
            points_by_color.setdefault(color, []).append(source.points)
            cells_by_color.setdefault(color, [])
            point_counts.setdefault(color, 0)
            self._append_cells(cells_by_color[color], source.faces, point_counts[color])
            point_counts[color] += len(source.points)
        return {
            color: pv.PolyData(
                np.vstack(points_by_color[color]),
                faces=np.asarray(cells_by_color[color], dtype=np.int64),
            )
            for color in points_by_color
        }

    def silhouette_mesh(self, batch: MemberBatch, camera) -> pv.PolyData:
        """Build the visible contour pass for the current camera."""
        if not batch.silhouette_faces_by_color:
            return _empty_mesh()
        points: list[np.ndarray] = []
        lines: list[int] = []
        colors: list[tuple[int, int, int]] = []
        point_count = 0
        for color, faces in batch.silhouette_faces_by_color.items():
            silhouette = self.solids.silhouette_for(faces, camera)
            if not silhouette.n_lines:
                continue
            points.append(silhouette.points)
            encoded = np.asarray(silhouette.lines, dtype=np.int64)
            cursor = 0
            while cursor < len(encoded):
                count = int(encoded[cursor])
                lines.append(count)
                lines.extend((encoded[cursor + 1:cursor + 1 + count] + point_count).tolist())
                colors.append(tuple(max(0, int(channel * 0.65)) for channel in color))
                cursor += count + 1
            point_count += len(silhouette.points)

        if not points:
            return _empty_mesh()
        mesh = pv.PolyData(np.vstack(points), lines=np.asarray(lines, dtype=np.int64))
        mesh.cell_data["rgb"] = np.asarray(colors, dtype=np.uint8)
        return mesh

    @staticmethod
    def _append_cells(destination: list[int], encoded: np.ndarray, offset: int) -> None:
        values = np.asarray(encoded, dtype=np.int64)
        cursor = 0
        while cursor < len(values):
            count = int(values[cursor])
            destination.append(count)
            destination.extend((values[cursor + 1:cursor + 1 + count] + offset).tolist())
            cursor += count + 1

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
        support_parts: list[pv.PolyData] = []
        positions = np.asarray(
            [(model.nodes[name].x, model.nodes[name].y, model.nodes[name].z) for name in names],
            dtype=float,
        )
        label_positions = positions + (0.0, 0.0, radius * 2.2)
        source_normals = sphere.point_data.get("Normals")

        if len(names):
            source_points = np.asarray(sphere.points, dtype=float)
            node_points = (source_points[None, :, :] + positions[:, None, :]).reshape(-1, 3)
            source_faces = np.asarray(sphere.faces, dtype=np.int64).reshape(-1, 4)
            face_count = len(source_faces)
            face_offsets = np.repeat(
                np.arange(len(names), dtype=np.int64) * len(source_points), face_count,
            )
            faces = np.tile(source_faces, (len(names), 1))
            faces[:, 1:] += face_offsets[:, None]
            geometry = pv.PolyData(node_points, faces=faces.ravel())
            geometry.cell_data["element_index"] = np.repeat(
                np.arange(len(names), dtype=np.int32), face_count,
            )
            if source_normals is not None:
                geometry.point_data["Normals"] = np.tile(source_normals, (len(names), 1))
        else:
            geometry = _empty_mesh()

        for node_name in names:
            node = model.nodes[node_name]
            support = self._support_mesh(node, radius)
            if support is not None:
                support_parts.append(support)

        if geometry.n_cells:
            geometry.cell_data["rgb"] = np.tile(
                _rgb("#000000"), (geometry.n_cells, 1),
            )
        return NodeBatch(
            names=names,
            geometry=geometry,
            supports=_merge(support_parts),
            label_positions=label_positions,
        )

    @staticmethod
    def _support_mesh(node, radius: float) -> pv.PolyData | None:
        del radius
        return build_support_mesh(node)
