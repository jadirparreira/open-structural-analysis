"""Batched geometry for large structural scenes.

The domain keeps one entity per node/member.  The renderer deliberately does
not mirror that with one VTK actor per entity: repeated geometry is merged into
small, GPU-friendly batches while a cell-data index preserves picking.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from math import cos, pi, sin
from types import SimpleNamespace

import numpy as np
import pyvista as pv
from vtk.util.numpy_support import vtk_to_numpy

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


def _polyline_mesh(
    polylines: list[np.ndarray], element_indices: list[int] | None = None,
) -> pv.PolyData:
    if not polylines:
        return _empty_mesh()
    points: list[np.ndarray] = []
    connectivity: list[int] = []
    offset = 0
    for polyline in polylines:
        points.append(polyline)
        connectivity.extend((len(polyline), *range(offset, offset + len(polyline))))
        offset += len(polyline)
    mesh = pv.PolyData(np.vstack(points), lines=np.asarray(connectivity, dtype=np.int64))
    if element_indices is not None:
        mesh.cell_data["element_index"] = np.asarray(element_indices, dtype=np.int32)
    return mesh


def _transformed_points(
    points: np.ndarray,
    start: np.ndarray,
    delta: np.ndarray,
    local_y: np.ndarray,
    local_z: np.ndarray,
) -> np.ndarray:
    """Transform section vertices without wrapping each member in PolyData."""
    return (
        start
        + points[:, 0, None] * delta
        + points[:, 1, None] * local_y
        + points[:, 2, None] * local_z
    )


def _offset_cells(encoded: np.ndarray, offset: int) -> np.ndarray:
    """Copy VTK connectivity and shift point IDs using a packed fast path."""
    values = np.asarray(encoded, dtype=np.int64)
    if not len(values) or offset == 0:
        return values.copy()

    # Section faces are triangulated and feature edges are line segments.
    # Their packed VTK cell arrays have fixed widths, so shift IDs in bulk.
    if len(values) % 4 == 0 and np.all(values[::4] == 3):
        shifted = values.copy().reshape(-1, 4)
        shifted[:, 1:] += offset
        return shifted.ravel()
    if len(values) % 3 == 0 and np.all(values[::3] == 2):
        shifted = values.copy().reshape(-1, 3)
        shifted[:, 1:] += offset
        return shifted.ravel()

    # Retain support for polyline and polygon cells supplied by other shapes.
    shifted = values.copy()
    cursor = 0
    while cursor < len(shifted):
        count = int(shifted[cursor])
        shifted[cursor + 1:cursor + count + 1] += offset
        cursor += count + 1
    return shifted


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
    outlines: Mapping[str, pv.PolyData]
    silhouette_sources: dict[str, pv.PolyData]
    silhouette_member_colors: dict[str, tuple[int, int, int]]
    label_positions: np.ndarray
    face_point_ranges: dict[str, tuple[int, int]]
    face_cell_ranges: dict[str, tuple[int, int]]
    edge_point_ranges: dict[str, tuple[int, int]]
    edge_cell_ranges: dict[str, tuple[int, int]]


class _LazyOutlineMap(Mapping[str, pv.PolyData]):
    """Keep member outlines as arrays until selection needs a separate mesh."""

    def __init__(self, sources: dict[str, tuple[np.ndarray, np.ndarray]]) -> None:
        self._sources = sources
        self._meshes: dict[str, pv.PolyData] = {}

    def __getitem__(self, name: str) -> pv.PolyData:
        if name not in self._sources:
            raise KeyError(name)
        mesh = self._meshes.get(name)
        if mesh is None:
            points, lines = self._sources[name]
            mesh = pv.PolyData(points, lines=lines)
            self._meshes[name] = mesh
        return mesh

    def __iter__(self) -> Iterator[str]:
        return iter(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    def replace_source(
        self, name: str, points: np.ndarray | None, lines: np.ndarray | None,
    ) -> None:
        if points is None or lines is None:
            self._sources.pop(name, None)
        else:
            self._sources[name] = points, lines
        self._meshes.pop(name, None)


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
        face_cells: list[np.ndarray] = []
        face_indices: list[int] = []
        face_colors: list[np.ndarray] = []
        edge_points: list[np.ndarray] = []
        edge_cells: list[np.ndarray] = []
        edge_indices: list[int] = []
        edge_colors: list[np.ndarray] = []
        face_point_count = 0
        edge_point_count = 0
        axis_segments: tuple[list, list, list] = ([], [], [])
        release_polylines: list[np.ndarray] = []
        release_indices: list[int] = []
        outline_sources: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        silhouette_sources: dict[str, pv.PolyData] = {}
        silhouette_member_colors: dict[str, tuple[int, int, int]] = {}
        face_point_ranges: dict[str, tuple[int, int]] = {}
        face_cell_ranges: dict[str, tuple[int, int]] = {}
        edge_point_ranges: dict[str, tuple[int, int]] = {}
        edge_cell_ranges: dict[str, tuple[int, int]] = {}
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
            release_start = len(release_polylines)
            self._append_release_polylines(
                release_polylines, start, end, member.releases, marker_radius, basis,
            )
            release_indices.extend([element_index] * (len(release_polylines) - release_start))

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
                shape = section_shape(
                    member.section, member.geometry_dict(), arc_steps=12,
                    mirror_z=member.section_mirrored,
                )
                if shape is None:
                    raise ValueError("Seção incompleta.")
                face_source = self.solids._mesh_for(shape)
                edge_source = self.solids._edge_mesh_for(shape)
            except (KeyError, TypeError, ValueError):
                fallback_segments.append((start, end, element_index, color))
                continue

            face_offset = face_point_count
            face_cell_offset = len(face_indices)
            transformed_face_points = _transformed_points(
                face_source.points, solid_origin, solid_delta, local_y, local_z,
            )
            face_points.append(transformed_face_points)
            face_cells.append(_offset_cells(face_source.faces, face_offset))
            face_indices.extend([element_index] * face_source.n_cells)
            face_colors.extend([color] * face_source.n_cells)
            face_point_count += len(transformed_face_points)
            face_point_ranges[member_name] = (face_offset, face_point_count)
            face_cell_ranges[member_name] = (face_cell_offset, len(face_indices))

            edge_offset = edge_point_count
            edge_cell_offset = len(edge_indices)
            transformed_edge_points = _transformed_points(
                edge_source.points, solid_origin, solid_delta, local_y, local_z,
            )
            edge_points.append(transformed_edge_points)
            edge_cells.append(_offset_cells(edge_source.lines, edge_offset))
            edge_indices.extend([element_index] * edge_source.n_cells)
            edge_colors.extend([_rgb(member.color, 0.65)] * edge_source.n_cells)
            edge_point_count += len(transformed_edge_points)
            edge_point_ranges[member_name] = (edge_offset, edge_point_count)
            edge_cell_ranges[member_name] = (edge_cell_offset, len(edge_indices))
            outline_sources[member_name] = (transformed_edge_points, edge_source.lines)
            if member.section in self._silhouette_sections:
                silhouette_sources[member_name] = pv.PolyData(
                    transformed_face_points, faces=face_source.faces,
                )
                silhouette_member_colors[member_name] = tuple(int(channel) for channel in color)

        faces = (
            pv.PolyData(
                np.vstack(face_points),
                np.concatenate(face_cells),
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
                lines=np.concatenate(edge_cells),
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
            releases=_polyline_mesh(release_polylines, release_indices),
            outlines=_LazyOutlineMap(outline_sources),
            silhouette_sources=silhouette_sources,
            silhouette_member_colors=silhouette_member_colors,
            label_positions=label_positions,
            face_point_ranges=face_point_ranges,
            face_cell_ranges=face_cell_ranges,
            edge_point_ranges=edge_point_ranges,
            edge_cell_ranges=edge_cell_ranges,
        )

    def update_member_section_in_place(self, batch: MemberBatch, model, member_name: str) -> bool:
        """Update one section when its topology still fits the packed ranges.

        Structural sizes usually change the coordinates but keep the same
        profile topology. In that common case, retain every VTK cell and update
        only the selected member's vertices and normals. Return ``False`` when
        the section family changes topology so the caller can use its full
        rebuild path.
        """
        member = model.bars.get(member_name)
        if (
            member is None
            or member_name not in batch.face_point_ranges
            or member_name not in batch.edge_point_ranges
        ):
            return False

        start_node = model.nodes[member.start_node]
        end_node = model.nodes[member.end_node]
        start = np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
        end = np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
        basis = LocalAxesRenderer.basis(start_node, end_node, rotation=member.rotation)
        base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
        if basis is None or base_basis is None:
            return False
        local_x, local_y, local_z = basis
        _base_x, base_local_y, base_local_z = base_basis
        solid_start, solid_end = start.copy(), end.copy()
        offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
        if len(offsets) == 2:
            candidate_start = start - local_x * float(offsets[0])
            candidate_end = end + local_x * float(offsets[1])
            if float(np.dot(candidate_end - candidate_start, local_x)) > 1e-9:
                solid_start, solid_end = candidate_start, candidate_end
        solid_origin = solid_start.copy()
        section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
        if len(section_offsets) == 2:
            solid_origin += (
                base_local_y * float(section_offsets[0])
                + base_local_z * float(section_offsets[1])
            )
        solid_delta = solid_end - solid_start

        try:
            shape = section_shape(
                member.section, member.geometry_dict(), arc_steps=12,
                mirror_z=member.section_mirrored,
            )
            if shape is None:
                return False
            face_source = self.solids._mesh_for(shape)
            edge_source = self.solids._edge_mesh_for(shape)
        except (KeyError, TypeError, ValueError):
            return False

        face_start, face_end = batch.face_point_ranges[member_name]
        face_cell_start, face_cell_end = batch.face_cell_ranges[member_name]
        edge_start, edge_end = batch.edge_point_ranges[member_name]
        edge_cell_start, edge_cell_end = batch.edge_cell_ranges[member_name]
        if (
            len(face_source.points) != face_end - face_start
            or face_source.n_cells != face_cell_end - face_cell_start
            or len(edge_source.points) != edge_end - edge_start
            or edge_source.n_cells != edge_cell_end - edge_cell_start
            or not np.array_equal(
                batch.faces.faces[face_cell_start * 4:face_cell_end * 4],
                _offset_cells(face_source.faces, face_start),
            )
            or not np.array_equal(
                batch.edges.lines[edge_cell_start * 3:edge_cell_end * 3],
                _offset_cells(edge_source.lines, edge_start),
            )
        ):
            return False

        face_points = _transformed_points(
            face_source.points, solid_origin, solid_delta, local_y, local_z,
        )
        edge_points = _transformed_points(
            edge_source.points, solid_origin, solid_delta, local_y, local_z,
        )
        batch.faces.points[face_start:face_end] = face_points
        batch.edges.points[edge_start:edge_end] = edge_points
        batch.faces.GetPoints().Modified()
        batch.edges.GetPoints().Modified()
        batch.faces.Modified()
        batch.edges.Modified()

        source_normals = face_source.cell_data.get("Normals")
        target_normals = batch.faces.cell_data.get("Normals")
        if source_normals is not None and target_normals is not None:
            rotation = np.column_stack((local_x, local_y, local_z))
            target_normals[face_cell_start:face_cell_end] = np.asarray(source_normals) @ rotation.T
            batch.faces.cell_data["Normals"] = target_normals
            batch.faces.GetCellData().Modified()

        outline_map = batch.outlines
        if isinstance(outline_map, _LazyOutlineMap):
            outline_map.replace_source(member_name, edge_points, edge_source.lines)

        had_silhouette = member_name in batch.silhouette_sources
        if member.section in self._silhouette_sections:
            batch.silhouette_sources[member_name] = pv.PolyData(
                face_points, faces=face_source.faces,
            )
            batch.silhouette_member_colors[member_name] = tuple(
                int(channel) for channel in _rgb(member.color)
            )
        else:
            batch.silhouette_sources.pop(member_name, None)
            batch.silhouette_member_colors.pop(member_name, None)
        if had_silhouette or member.section in self._silhouette_sections:
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        return True

    @staticmethod
    def _splice_member_mesh(
        mesh: pv.PolyData,
        replacement: pv.PolyData,
        element_index: int,
        *,
        faces: bool = False,
        point_range: tuple[int, int] | None = None,
    ) -> pv.PolyData:
        """Replace one member's cells without regenerating the other members."""
        if mesh.n_cells:
            indices = np.asarray(mesh.cell_data["element_index"])
            cell_start = int(np.searchsorted(indices, element_index, side="left"))
            cell_end = int(np.searchsorted(indices, element_index, side="right"))
            cells = mesh.GetPolys() if faces else mesh.GetLines()
            offsets = vtk_to_numpy(cells.GetOffsetsArray())
            encoded_start = int(offsets[cell_start] + cell_start)
            encoded_end = int(offsets[cell_end] + cell_end)
        else:
            cell_start = cell_end = encoded_start = encoded_end = 0
            offsets = np.array([0], dtype=np.int64)

        if point_range is None:
            point_start = int(offsets[cell_start])
            point_end = int(offsets[cell_end])
        else:
            point_start, point_end = point_range
        old_encoded = np.asarray(mesh.faces if faces else mesh.lines, dtype=np.int64)
        new_encoded = np.asarray(replacement.faces if faces else replacement.lines, dtype=np.int64)
        point_delta = replacement.n_points - (point_end - point_start)
        encoded = np.concatenate((
            old_encoded[:encoded_start],
            _offset_cells(new_encoded, point_start),
            _offset_cells(old_encoded[encoded_end:], point_delta),
        ))
        points = np.concatenate((
            np.asarray(mesh.points[:point_start]),
            np.asarray(replacement.points),
            np.asarray(mesh.points[point_end:]),
        ))
        if not len(encoded):
            return _empty_mesh()
        updated = pv.PolyData(points, faces=encoded) if faces else pv.PolyData(points, lines=encoded)
        for key in set(mesh.cell_data) | set(replacement.cell_data):
            old_values = np.asarray(mesh.cell_data[key]) if key in mesh.cell_data else None
            new_values = np.asarray(replacement.cell_data[key]) if key in replacement.cell_data else None
            if old_values is None:
                old_values = np.empty((0, *new_values.shape[1:]), dtype=new_values.dtype)
            if new_values is None:
                new_values = np.empty((0, *old_values.shape[1:]), dtype=old_values.dtype)
            if key == "element_index":
                new_values = np.asarray(new_values, dtype=np.int32) + element_index
            updated.cell_data[key] = np.concatenate((
                old_values[:cell_start], new_values, old_values[cell_end:],
            ))
        return updated

    @staticmethod
    def _updated_member_ranges(
        names: tuple[str, ...],
        old_ranges: dict[str, tuple[int, int]],
        member_name: str,
        new_count: int,
    ) -> tuple[dict[str, tuple[int, int]], tuple[int, int]]:
        ranges: dict[str, tuple[int, int]] = {}
        cursor = 0
        replaced_range = (0, 0)
        for name in names:
            count = new_count if name == member_name else (
                old_ranges[name][1] - old_ranges[name][0] if name in old_ranges else 0
            )
            if name == member_name:
                replaced_range = cursor, cursor + (
                    old_ranges[name][1] - old_ranges[name][0] if name in old_ranges else 0
                )
            if count:
                ranges[name] = cursor, cursor + count
            cursor += count
        return ranges, replaced_range

    @staticmethod
    def _member_mesh_segment(
        mesh: pv.PolyData, element_index: int, *,
        faces: bool = False, point_range: tuple[int, int] | None = None,
    ) -> tuple[int, int, int, int, int, int]:
        if not mesh.n_cells:
            return (0, 0, 0, 0, 0, 0)
        indices = np.asarray(mesh.cell_data["element_index"])
        first = int(np.searchsorted(indices, element_index, side="left"))
        last = int(np.searchsorted(indices, element_index, side="right"))
        cells = mesh.GetPolys() if faces else mesh.GetLines()
        offsets = vtk_to_numpy(cells.GetOffsetsArray())
        point_first, point_last = (
            point_range if point_range is not None
            else (int(offsets[first]), int(offsets[last]))
        )
        return (
            first, last, point_first, point_last,
            int(offsets[first] + first), int(offsets[last] + last),
        )

    def update_member_in_place(
        self, batch: MemberBatch, model, member_name: str, marker_radius: float,
    ) -> bool:
        """Patch all visual layers when one member keeps the same cell topology."""
        member = model.bars.get(member_name)
        if member is None or member_name not in batch.names:
            return False
        element_index = batch.names.index(member_name)
        small_model = SimpleNamespace(bars={member_name: member}, nodes=model.nodes)
        replacement = self.build(small_model, marker_radius)
        layers = (
            (batch.lines, replacement.lines, False, None),
            (batch.fallback_lines, replacement.fallback_lines, False, None),
            (batch.faces, replacement.faces, True, batch.face_point_ranges.get(member_name)),
            (batch.edges, replacement.edges, False, batch.edge_point_ranges.get(member_name)),
            *((old, new, False, None) for old, new in zip(batch.axes, replacement.axes)),
            (batch.releases, replacement.releases, False, None),
        )
        patches = []
        for old, new, is_faces, point_range in layers:
            segment = self._member_mesh_segment(
                old, element_index, faces=is_faces, point_range=point_range,
            )
            cell_first, cell_last, point_first, point_last, encoded_first, encoded_last = segment
            old_encoded = np.asarray(old.faces if is_faces else old.lines, dtype=np.int64)
            new_encoded = np.asarray(new.faces if is_faces else new.lines, dtype=np.int64)
            if (
                cell_last - cell_first != new.n_cells
                or point_last - point_first != new.n_points
                or set(old.cell_data) != set(new.cell_data)
                or not np.array_equal(
                    old_encoded[encoded_first:encoded_last],
                    _offset_cells(new_encoded, point_first),
                )
            ):
                return False
            patches.append((old, new, segment))

        for old, new, segment in patches:
            cell_first, cell_last, point_first, point_last, _, _ = segment
            if new.n_points:
                old.points[point_first:point_last] = new.points
                old.GetPoints().Modified()
            for key in new.cell_data:
                if key == "element_index":
                    continue
                old.cell_data[key][cell_first:cell_last] = new.cell_data[key]
            old.GetCellData().Modified()
            old.Modified()
        batch.label_positions[element_index] = replacement.label_positions[0]
        if isinstance(batch.outlines, _LazyOutlineMap):
            outline = replacement.outlines.get(member_name)
            batch.outlines.replace_source(
                member_name,
                None if outline is None else np.asarray(outline.points),
                None if outline is None else np.asarray(outline.lines),
            )
        had_silhouette = member_name in batch.silhouette_sources
        if member_name in replacement.silhouette_sources:
            batch.silhouette_sources[member_name] = replacement.silhouette_sources[member_name]
            batch.silhouette_member_colors[member_name] = replacement.silhouette_member_colors[member_name]
        else:
            batch.silhouette_sources.pop(member_name, None)
            batch.silhouette_member_colors.pop(member_name, None)
        if had_silhouette or member_name in replacement.silhouette_sources:
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        return True

    def update_member_in_batch(
        self, batch: MemberBatch, model, member_name: str, marker_radius: float,
    ) -> bool:
        """Rebuild one member, including section, axes, releases and fallback."""
        member = model.bars.get(member_name)
        if member is None or member_name not in batch.names:
            return False
        element_index = batch.names.index(member_name)
        small_model = SimpleNamespace(bars={member_name: member}, nodes=model.nodes)
        replacement = self.build(small_model, marker_radius)

        face_ranges, face_point_range = self._updated_member_ranges(
            batch.names, batch.face_point_ranges, member_name, replacement.faces.n_points,
        )
        face_cell_ranges, _ = self._updated_member_ranges(
            batch.names, batch.face_cell_ranges, member_name, replacement.faces.n_cells,
        )
        edge_ranges, edge_point_range = self._updated_member_ranges(
            batch.names, batch.edge_point_ranges, member_name, replacement.edges.n_points,
        )
        edge_cell_ranges, _ = self._updated_member_ranges(
            batch.names, batch.edge_cell_ranges, member_name, replacement.edges.n_cells,
        )
        lines = self._splice_member_mesh(batch.lines, replacement.lines, element_index)
        fallback = self._splice_member_mesh(
            batch.fallback_lines, replacement.fallback_lines, element_index,
        )
        faces = self._splice_member_mesh(
            batch.faces, replacement.faces, element_index, faces=True,
            point_range=face_point_range,
        )
        edges = self._splice_member_mesh(
            batch.edges, replacement.edges, element_index, point_range=edge_point_range,
        )
        axes = tuple(
            self._splice_member_mesh(old, new, element_index)
            for old, new in zip(batch.axes, replacement.axes)
        )
        releases = self._splice_member_mesh(
            batch.releases, replacement.releases, element_index,
        )

        batch.lines = lines
        batch.fallback_lines = fallback
        batch.faces = faces
        batch.edges = edges
        batch.axes = axes
        batch.releases = releases
        batch.face_point_ranges = face_ranges
        batch.face_cell_ranges = face_cell_ranges
        batch.edge_point_ranges = edge_ranges
        batch.edge_cell_ranges = edge_cell_ranges
        batch.label_positions[element_index] = replacement.label_positions[0]
        outline_map = batch.outlines
        if isinstance(outline_map, _LazyOutlineMap):
            outline = replacement.outlines.get(member_name)
            outline_map.replace_source(
                member_name,
                None if outline is None else np.asarray(outline.points),
                None if outline is None else np.asarray(outline.lines),
            )
        had_silhouette = member_name in batch.silhouette_sources
        if member_name in replacement.silhouette_sources:
            batch.silhouette_sources[member_name] = replacement.silhouette_sources[member_name]
            batch.silhouette_member_colors[member_name] = replacement.silhouette_member_colors[member_name]
        else:
            batch.silhouette_sources.pop(member_name, None)
            batch.silhouette_member_colors.pop(member_name, None)
        if had_silhouette or member_name in replacement.silhouette_sources:
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        return True

    def append_members(
        self, batch: MemberBatch, model, names: tuple[str, ...], marker_radius: float,
    ) -> bool:
        """Build an appended group once and concatenate it with existing batches."""
        if not names or tuple(model.bars) != batch.names + names:
            return False
        tail_model = SimpleNamespace(
            bars={name: model.bars[name] for name in names}, nodes=model.nodes,
        )
        tail = self.build(tail_model, marker_radius)
        first_index = len(batch.names)
        old_face_points, old_face_cells = batch.faces.n_points, batch.faces.n_cells
        old_edge_points, old_edge_cells = batch.edges.n_points, batch.edges.n_cells
        batch.lines = self._splice_member_mesh(batch.lines, tail.lines, first_index)
        batch.fallback_lines = self._splice_member_mesh(
            batch.fallback_lines, tail.fallback_lines, first_index,
        )
        batch.faces = self._splice_member_mesh(
            batch.faces, tail.faces, first_index, faces=True,
            point_range=(old_face_points, old_face_points),
        )
        batch.edges = self._splice_member_mesh(
            batch.edges, tail.edges, first_index,
            point_range=(old_edge_points, old_edge_points),
        )
        batch.axes = tuple(
            self._splice_member_mesh(old, new, first_index)
            for old, new in zip(batch.axes, tail.axes)
        )
        batch.releases = self._splice_member_mesh(batch.releases, tail.releases, first_index)
        batch.label_positions = np.concatenate((batch.label_positions, tail.label_positions))
        batch.names += names
        for name, (start, end) in tail.face_point_ranges.items():
            batch.face_point_ranges[name] = old_face_points + start, old_face_points + end
        for name, (start, end) in tail.face_cell_ranges.items():
            batch.face_cell_ranges[name] = old_face_cells + start, old_face_cells + end
        for name, (start, end) in tail.edge_point_ranges.items():
            batch.edge_point_ranges[name] = old_edge_points + start, old_edge_points + end
        for name, (start, end) in tail.edge_cell_ranges.items():
            batch.edge_cell_ranges[name] = old_edge_cells + start, old_edge_cells + end
        if isinstance(batch.outlines, _LazyOutlineMap):
            for name in tail.outlines:
                outline = tail.outlines[name]
                batch.outlines.replace_source(name, np.asarray(outline.points), np.asarray(outline.lines))
        batch.silhouette_sources.update(tail.silhouette_sources)
        batch.silhouette_member_colors.update(tail.silhouette_member_colors)
        if tail.silhouette_sources:
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        return True

    def remove_member(self, batch: MemberBatch, member_name: str) -> bool:
        """Remove one member and renumber later picking indices."""
        if member_name not in batch.names:
            return False
        element_index = batch.names.index(member_name)
        empty = _empty_mesh()
        face_ranges, face_point_range = self._updated_member_ranges(
            batch.names, batch.face_point_ranges, member_name, 0,
        )
        face_cell_ranges, _ = self._updated_member_ranges(
            batch.names, batch.face_cell_ranges, member_name, 0,
        )
        edge_ranges, edge_point_range = self._updated_member_ranges(
            batch.names, batch.edge_point_ranges, member_name, 0,
        )
        edge_cell_ranges, _ = self._updated_member_ranges(
            batch.names, batch.edge_cell_ranges, member_name, 0,
        )
        batch.lines = self._splice_member_mesh(batch.lines, empty, element_index)
        batch.fallback_lines = self._splice_member_mesh(
            batch.fallback_lines, empty, element_index,
        )
        batch.faces = self._splice_member_mesh(
            batch.faces, empty, element_index, faces=True,
            point_range=face_point_range,
        )
        batch.edges = self._splice_member_mesh(
            batch.edges, empty, element_index, point_range=edge_point_range,
        )
        batch.axes = tuple(
            self._splice_member_mesh(mesh, empty, element_index) for mesh in batch.axes
        )
        batch.releases = self._splice_member_mesh(batch.releases, empty, element_index)
        for mesh in (
            batch.lines, batch.fallback_lines, batch.faces, batch.edges,
            *batch.axes, batch.releases,
        ):
            if mesh.n_cells:
                indices = mesh.cell_data["element_index"]
                indices[indices > element_index] -= 1
                mesh.GetCellData().Modified()
        batch.names = tuple(name for name in batch.names if name != member_name)
        batch.label_positions = np.delete(batch.label_positions, element_index, axis=0)
        batch.face_point_ranges = face_ranges
        batch.face_cell_ranges = face_cell_ranges
        batch.edge_point_ranges = edge_ranges
        batch.edge_cell_ranges = edge_cell_ranges
        if isinstance(batch.outlines, _LazyOutlineMap):
            batch.outlines.replace_source(member_name, None, None)
        had_silhouette = member_name in batch.silhouette_sources
        batch.silhouette_sources.pop(member_name, None)
        batch.silhouette_member_colors.pop(member_name, None)
        if had_silhouette:
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        return True

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

    def __init__(self) -> None:
        self._support_cache: dict[str, tuple[object, pv.DataSet | None]] = {}

    @staticmethod
    def update_node_positions_in_place(
        batch: NodeBatch, old_nodes, model, names: tuple[str, ...], radius: float,
    ) -> bool:
        """Move existing sphere vertices and labels for a small node edit."""
        if not batch.names or batch.names != tuple(model.nodes):
            return False
        points_per_node = batch.geometry.n_points // len(batch.names)
        if points_per_node * len(batch.names) != batch.geometry.n_points:
            return False
        indices = {name: index for index, name in enumerate(batch.names)}
        if any(
            name not in indices or name not in old_nodes or name not in model.nodes
            for name in names
        ):
            return False
        points = batch.geometry.points
        for name in names:
            index = indices[name]
            old = old_nodes[name]
            node = model.nodes[name]
            delta = np.asarray((node.x - old.x, node.y - old.y, node.z - old.z))
            first = index * points_per_node
            points[first:first + points_per_node] += delta
            batch.label_positions[index] = (node.x, node.y, node.z + radius * 2.2)
        batch.geometry.GetPoints().Modified()
        batch.geometry.Modified()
        return True

    @staticmethod
    def append_nodes(
        batch: NodeBatch, model, names: tuple[str, ...], radius: float,
    ) -> bool:
        """Append marker spheres for newly created nodes in one array operation."""
        if not names or tuple(model.nodes) != batch.names + names:
            return False
        tail_model = SimpleNamespace(nodes={name: model.nodes[name] for name in names})
        tail = BatchedNodeRenderer().build(tail_model, radius)
        old = batch.geometry
        new = tail.geometry
        points = np.concatenate((np.asarray(old.points), np.asarray(new.points)))
        faces = np.concatenate((
            np.asarray(old.faces, dtype=np.int64),
            _offset_cells(new.faces, old.n_points),
        ))
        geometry = pv.PolyData(points, faces=faces)
        geometry.cell_data["element_index"] = np.concatenate((
            np.asarray(old.cell_data["element_index"]),
            np.asarray(new.cell_data["element_index"]) + len(batch.names),
        ))
        geometry.cell_data["rgb"] = np.concatenate((
            np.asarray(old.cell_data["rgb"]), np.asarray(new.cell_data["rgb"]),
        ))
        if "Normals" in old.point_data and "Normals" in new.point_data:
            geometry.point_data["Normals"] = np.concatenate((
                np.asarray(old.point_data["Normals"]),
                np.asarray(new.point_data["Normals"]),
            ))
        batch.geometry = geometry
        batch.label_positions = np.concatenate((batch.label_positions, tail.label_positions))
        batch.names += names
        return True

    def build(self, model, radius: float) -> NodeBatch:
        names = tuple(model.nodes)
        sphere = pv.Sphere(
            radius=radius,
            center=(0.0, 0.0, 0.0),
            theta_resolution=20,
            phi_resolution=12,
        )
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

        if geometry.n_cells:
            geometry.cell_data["rgb"] = np.tile(
                _rgb("#000000"), (geometry.n_cells, 1),
            )
        return NodeBatch(
            names=names,
            geometry=geometry,
            supports=self.build_supports(model, radius),
            label_positions=label_positions,
        )

    def build_supports(self, model, radius: float) -> pv.PolyData:
        """Build just the support symbols for edits that leave nodes in place."""
        del radius
        support_parts = []
        cache = {}
        for node in model.nodes.values():
            entry = self._support_cache.get(node.name)
            if entry is not None and entry[0] == node:
                support = entry[1]
            else:
                support = self._support_mesh(node, 0.0)
            cache[node.name] = node, support
            if support is not None:
                support_parts.append(support)
        self._support_cache = cache
        return _merge(support_parts)

    @staticmethod
    def _support_mesh(node, radius: float) -> pv.PolyData | None:
        del radius
        return build_support_mesh(node)
