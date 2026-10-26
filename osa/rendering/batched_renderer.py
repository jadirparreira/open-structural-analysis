"""Batched geometry for large structural scenes.

The domain keeps one entity per node/member.  The renderer deliberately does
not mirror that with one VTK actor per entity: repeated geometry is merged into
small, GPU-friendly batches while a cell-data index preserves picking.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from math import cos, pi, sin
from types import SimpleNamespace

import numpy as np
import pyvista as pv
from vtk.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkFiltersGeometry import vtkDataSetSurfaceFilter

from osa.sections import section_shape

from .grid_renderer import GridRenderer
from .local_axes_renderer import LocalAxesRenderer
from .solid_member_renderer import SolidMemberRenderer, deform_extruded_points
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
    face_angles: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0),
) -> np.ndarray:
    """Transform section vertices without wrapping each member in PolyData."""
    length = float(np.linalg.norm(delta))
    local_points = deform_extruded_points(points, length, face_angles)
    return (
        start
        + local_points[:, 0, None] * delta
        + local_points[:, 1, None] * local_y
        + local_points[:, 2, None] * local_z
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
    section_offsets: np.ndarray
    indicators_with_section: bool
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

    def source(self, name: str) -> tuple[np.ndarray, np.ndarray] | None:
        """Return packed outline arrays without allocating a separate mesh."""
        return self._sources.get(name)

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
    glyphs: bool = False


@dataclass(slots=True)
class PreparedSceneGeometry:
    """CPU-built scene meshes ready for installation on the GUI thread."""

    member_batch: MemberBatch
    node_batch: NodeBatch
    rigid_names: tuple[str, ...]
    rigid_mesh: pv.PolyData
    member_key: tuple[object, ...]
    node_key: tuple[object, ...]
    rigid_key: tuple[object, ...]
    grid_renderer: GridRenderer
    visible_bars: dict[str, object]
    visible_nodes: dict[str, object]
    source_member_batch: MemberBatch
    source_member_key: tuple[object, ...]
    solid_positioning_enabled: bool


def prepare_scene_geometry(
    model,
    *,
    marker_radius: float = 0.05,
    solid_members_visible: bool = False,
    position_indicators_with_section: bool = False,
    solid_positioning_enabled: bool = True,
    reference_plane: str = "XY",
    preferred_plane_level: float = 0.0,
    progress: Callable[[str], None] | None = None,
    yield_control: Callable[[], None] | None = None,
) -> PreparedSceneGeometry:
    """Build large CPU-side meshes without accessing the Qt or VTK renderer."""
    hidden_members = set(model.scene_views.get(model.active_scene_view, ())).intersection(model.bars)
    hidden_rigid_bars = set(
        model.scene_view_hidden_rigid_bars.get(model.active_scene_view, ())
    ).intersection(model.rigid_bars)
    visible_bars = {
        name: member for name, member in model.bars.items() if name not in hidden_members
    }
    connected: set[str] = set()
    visible_connected: set[str] = set()
    for member in model.bars.values():
        endpoints = (member.start_node, member.end_node)
        connected.update(endpoints)
        if member.name not in hidden_members:
            visible_connected.update(endpoints)
    for name, rigid in model.rigid_bars.items():
        endpoints = (rigid.start_node, rigid.end_node)
        connected.update(endpoints)
        if name not in hidden_rigid_bars:
            visible_connected.update(endpoints)
    visible_node_names = set(model.nodes).difference(connected).union(visible_connected)
    visible_nodes = {
        name: node for name, node in model.nodes.items() if name in visible_node_names
    }

    member_renderer = BatchedMemberRenderer()
    member_renderer.position_indicators_with_section = position_indicators_with_section
    member_renderer.solid_positioning_enabled = solid_positioning_enabled
    if progress is not None:
        progress("Preparando a geometria das barras…")
    source_member_batch = member_renderer.build(model, marker_radius, yield_control=yield_control)
    member_batch = member_renderer.filter_members(source_member_batch, set(visible_bars))
    if progress is not None:
        progress("Preparando os nós e apoios…")
    node_batch = BatchedNodeRenderer(glyphs=True).build(SimpleNamespace(nodes=visible_nodes), marker_radius)
    rigid_names, rigid_mesh = BatchedRigidBarRenderer().build(model)

    source_member_key = (
        round(float(marker_radius), 12),
        bool(solid_members_visible),
        tuple(
            (
                member,
                (model.nodes[member.start_node].x, model.nodes[member.start_node].y,
                 model.nodes[member.start_node].z),
                (model.nodes[member.end_node].x, model.nodes[member.end_node].y,
                 model.nodes[member.end_node].z),
            )
            for member in model.bars.values()
        ),
    )
    member_key = (
        *source_member_key[:2],
        tuple(item for item in source_member_key[2] if item[0].name in visible_bars),
    )
    node_key = (round(float(marker_radius), 12), tuple(visible_nodes.values()))
    rigid_key = tuple(
        (
            rigid,
            (model.nodes[rigid.start_node].x, model.nodes[rigid.start_node].y,
             model.nodes[rigid.start_node].z),
            (model.nodes[rigid.end_node].x, model.nodes[rigid.end_node].y,
             model.nodes[rigid.end_node].z),
        )
        for rigid in model.rigid_bars.values()
    )
    axis_name = {"XY": "Z", "XZ": "X", "YZ": "Y"}.get(reference_plane, "Z")
    levels = tuple(sorted({float(axis.value) for axis in model.axes.get(axis_name, ())})) or (0.0,)
    plane_level = min(levels, key=lambda level: abs(level - preferred_plane_level))
    grid_renderer = GridRenderer()
    if progress is not None:
        progress("Preparando a grade da cena…")
    grid_renderer.update(model.nodes.values(), model.axes, reference_plane, plane_level)
    return PreparedSceneGeometry(
        member_batch, node_batch, rigid_names, rigid_mesh,
        member_key, node_key, rigid_key, grid_renderer, visible_bars, visible_nodes,
        source_member_batch, source_member_key, solid_positioning_enabled,
    )


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
        self.position_indicators_with_section = True
        self.solid_positioning_enabled = True

    def build(
        self, model, marker_radius: float, *, yield_control: Callable[[], None] | None = None,
    ) -> MemberBatch:
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
        section_offsets = np.empty((len(names), 3), dtype=float)
        colors: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        section_sources: dict[tuple[object, ...], tuple | None] = {}

        for element_index, member_name in enumerate(names):
            if yield_control is not None and element_index % 64 == 0:
                yield_control()
            member = model.bars[member_name]
            start_node = model.nodes[member.start_node]
            end_node = model.nodes[member.end_node]
            start = np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
            section_offset = (
                LocalAxesRenderer.section_offset(member, start_node, end_node)
                if self.solid_positioning_enabled else np.zeros(3, dtype=float)
            )
            section_offsets[element_index] = section_offset
            indicator_offset = section_offset if self.position_indicators_with_section else np.zeros(3)
            delta = end - start
            if member.color not in colors:
                colors[member.color] = (_rgb(member.color), _rgb(member.color, 0.65))
            color, edge_color = colors[member.color]
            line_segments.append((start, end, element_index, color))
            label_positions[element_index] = (
                (start + end) / 2.0 + indicator_offset + (0.0, 0.0, marker_radius * 2.2)
            )

            basis = LocalAxesRenderer.basis(start_node, end_node, rotation=member.rotation)
            if basis is None:
                fallback_segments.append((start, end, element_index, color))
                continue
            local_x, local_y, local_z = basis
            length = float(np.linalg.norm(delta))
            axis_scale = min(max(length * 0.2, 0.15), 1.0)
            midpoint = (start + end) / 2.0 + indicator_offset
            for axis_index, axis in enumerate((local_x, local_y, local_z)):
                axis_segments[axis_index].append(
                    (midpoint, midpoint + axis * axis_scale, element_index, np.zeros(3, dtype=np.uint8))
                )
            release_start = len(release_polylines)
            self._append_release_polylines(
                release_polylines, start + indicator_offset, end + indicator_offset,
                member.releases, marker_radius, basis,
            )
            release_indices.extend([element_index] * (len(release_polylines) - release_start))

            # Os deslocamentos das faces sólidas são exclusivamente visuais:
            # valores positivos aumentam o comprimento nas extremidades e
            # valores negativos o reduzem. As linhas continuam referenciando
            # os nós analíticos; os indicadores acompanham apenas Y/Z.
            # Member rotation is a general section-orientation property and
            # applies in every session; only positional offsets are scoped to
            # the detailing session.
            solid_x, solid_y, solid_z = basis
            solid_start = start.copy()
            solid_end = end.copy()
            offsets = getattr(member, "solid_face_offsets", (0.0, 0.0)) if self.solid_positioning_enabled else (0.0, 0.0)
            face_angles = (
                getattr(member, "solid_face_angles", (0.0, 0.0, 0.0, 0.0))
                if self.solid_positioning_enabled else (0.0, 0.0, 0.0, 0.0)
            )
            if len(offsets) == 2:
                candidate_start = start - solid_x * float(offsets[0])
                candidate_end = end + solid_x * float(offsets[1])
                if float(np.dot(candidate_end - candidate_start, solid_x)) > 1e-9:
                    solid_start, solid_end = candidate_start, candidate_end
            solid_origin = solid_start + section_offset
            solid_delta = solid_end - solid_start

            section_key = (member.section, member.section_geometry, member.section_mirrored)
            if section_key not in section_sources:
                try:
                    shape = section_shape(
                        member.section, member.geometry_dict(), arc_steps=12,
                        mirror_z=member.section_mirrored,
                    )
                    if shape is None:
                        raise ValueError("Seção incompleta.")
                    face_source = self.solids._mesh_for(shape)
                    edge_source = self.solids._edge_mesh_for(shape)
                    section_sources[section_key] = (
                        np.asarray(face_source.points), np.asarray(face_source.faces), face_source.n_cells,
                        np.asarray(edge_source.points), np.asarray(edge_source.lines), edge_source.n_cells,
                    )
                except (KeyError, TypeError, ValueError):
                    section_sources[section_key] = None
            source = section_sources[section_key]
            if source is None:
                fallback_segments.append((start, end, element_index, color))
                continue
            face_vertices, face_connectivity, face_count, edge_vertices, edge_connectivity, edge_count = source

            face_offset = face_point_count
            face_cell_offset = len(face_indices)
            transformed_face_points = _transformed_points(
                face_vertices, solid_origin, solid_delta, solid_y, solid_z, face_angles,
            )
            face_points.append(transformed_face_points)
            face_cells.append(_offset_cells(face_connectivity, face_offset))
            face_indices.extend([element_index] * face_count)
            face_colors.extend([color] * face_count)
            face_point_count += len(transformed_face_points)
            face_point_ranges[member_name] = (face_offset, face_point_count)
            face_cell_ranges[member_name] = (face_cell_offset, len(face_indices))

            edge_offset = edge_point_count
            edge_cell_offset = len(edge_indices)
            transformed_edge_points = _transformed_points(
                edge_vertices, solid_origin, solid_delta, solid_y, solid_z, face_angles,
            )
            edge_points.append(transformed_edge_points)
            edge_cells.append(_offset_cells(edge_connectivity, edge_offset))
            edge_indices.extend([element_index] * edge_count)
            edge_colors.extend([edge_color] * edge_count)
            edge_point_count += len(transformed_edge_points)
            edge_point_ranges[member_name] = (edge_offset, edge_point_count)
            edge_cell_ranges[member_name] = (edge_cell_offset, len(edge_indices))
            outline_sources[member_name] = (transformed_edge_points, edge_connectivity)
            if member.section in self._silhouette_sections:
                silhouette_sources[member_name] = pv.PolyData(
                    transformed_face_points, faces=face_connectivity,
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
            section_offsets=section_offsets,
            indicators_with_section=self.position_indicators_with_section,
            face_point_ranges=face_point_ranges,
            face_cell_ranges=face_cell_ranges,
            edge_point_ranges=edge_point_ranges,
            edge_cell_ranges=edge_cell_ranges,
        )

    @staticmethod
    def _filter_mesh(
        mesh: pv.PolyData, remap: np.ndarray, *, faces: bool = False,
    ) -> tuple[pv.PolyData, np.ndarray, np.ndarray]:
        """Compact existing cells, retaining normals and remapping picking IDs."""
        if not mesh.n_cells:
            return _empty_mesh(), np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
        indices = np.asarray(mesh.cell_data["element_index"])
        keep = remap[indices] >= 0
        cell_ids = np.flatnonzero(keep)
        if not len(cell_ids):
            return _empty_mesh(), np.empty(0, dtype=np.int64), cell_ids
        cells = mesh.GetPolys() if faces else mesh.GetLines()
        offsets = vtk_to_numpy(cells.GetOffsetsArray())
        connectivity = vtk_to_numpy(cells.GetConnectivityArray())
        widths = np.diff(offsets)
        selected = connectivity[np.repeat(keep, widths)]
        used_points = np.zeros(mesh.n_points, dtype=bool)
        used_points[selected] = True
        point_ids = np.flatnonzero(used_points)
        point_remap = np.empty(mesh.n_points, dtype=np.int64)
        point_remap[point_ids] = np.arange(len(point_ids), dtype=np.int64)
        compact = point_remap[selected]
        counts = widths[keep]
        starts = np.r_[0, np.cumsum(counts[:-1] + 1)]
        encoded = np.empty(len(compact) + len(counts), dtype=np.int64)
        encoded[starts] = counts
        is_point = np.ones(len(encoded), dtype=bool)
        is_point[starts] = False
        encoded[is_point] = compact
        points = np.asarray(mesh.points)[point_ids]
        result = pv.PolyData(points, faces=encoded) if faces else pv.PolyData(points, lines=encoded)
        for key, values in mesh.cell_data.items():
            result.cell_data[key] = remap[indices[keep]] if key == "element_index" else values[keep]
        if mesh.cell_data.active_normals_name is not None:
            result.cell_data.active_normals_name = mesh.cell_data.active_normals_name
        return result, point_ids, cell_ids

    def filter_members(self, batch: MemberBatch, visible: set[str]) -> MemberBatch:
        """Reuse section vertices, releases and normals when only a view changes.

        Keep at most the complete source batch and the displayed subset in the
        scene, rather than retaining a copy of the geometry for every view.
        """
        selected = np.asarray([name in visible for name in batch.names], dtype=bool)
        if np.all(selected):
            return batch
        names = tuple(name for name, keep in zip(batch.names, selected) if keep)
        remap = np.full(len(batch.names), -1, dtype=np.int32)
        remap[selected] = np.arange(len(names), dtype=np.int32)
        faces, face_points, face_cells = self._filter_mesh(batch.faces, remap, faces=True)
        edges, edge_points, edge_cells = self._filter_mesh(batch.edges, remap)

        def ranges(source, retained):
            present = tuple(name for name in names if name in source)
            if not present:
                return {}
            boundaries = np.searchsorted(retained, np.asarray([source[name] for name in present]))
            return {
                name: (int(start), int(end)) for name, (start, end) in zip(present, boundaries)
            }

        outlines = {}
        for name in names:
            if isinstance(batch.outlines, _LazyOutlineMap):
                source = batch.outlines.source(name)
                if source is not None:
                    outlines[name] = source
            elif name in batch.outlines:
                outline = batch.outlines[name]
                outlines[name] = (np.asarray(outline.points), np.asarray(outline.lines))
        silhouettes = {name: mesh for name, mesh in batch.silhouette_sources.items() if name in visible}
        colors = {name: batch.silhouette_member_colors[name] for name in silhouettes}
        return MemberBatch(
            names=names,
            lines=self._filter_mesh(batch.lines, remap)[0],
            fallback_lines=self._filter_mesh(batch.fallback_lines, remap)[0],
            faces=faces,
            edges=edges,
            silhouette_faces_by_color=self._build_silhouette_faces_by_color(silhouettes, colors),
            axes=tuple(self._filter_mesh(mesh, remap)[0] for mesh in batch.axes),
            releases=self._filter_mesh(batch.releases, remap)[0],
            outlines=_LazyOutlineMap(outlines),
            silhouette_sources=silhouettes,
            silhouette_member_colors=colors,
            label_positions=batch.label_positions[selected],
            section_offsets=batch.section_offsets[selected],
            indicators_with_section=batch.indicators_with_section,
            face_point_ranges=ranges(batch.face_point_ranges, face_points),
            face_cell_ranges=ranges(batch.face_cell_ranges, face_cells),
            edge_point_ranges=ranges(batch.edge_point_ranges, edge_points),
            edge_cell_ranges=ranges(batch.edge_cell_ranges, edge_cells),
        )

    @staticmethod
    def set_indicators_with_section(batch: MemberBatch, visible: bool) -> None:
        """Move only labels, local axes and releases when representation changes."""
        if batch.indicators_with_section == visible:
            return
        batch.indicators_with_section = visible
        if not np.any(batch.section_offsets):
            return
        shifts = batch.section_offsets if visible else -batch.section_offsets
        batch.label_positions += shifts
        for mesh in (*batch.axes, batch.releases):
            if not mesh.n_cells:
                continue
            cells = mesh.GetLines()
            connectivity = vtk_to_numpy(cells.GetConnectivityArray())
            widths = np.diff(vtk_to_numpy(cells.GetOffsetsArray()))
            indices = np.asarray(mesh.cell_data["element_index"])
            # Each line/polyline owns its vertices in these indicator batches.
            mesh.points[connectivity] += np.repeat(shifts[indices], widths, axis=0)
            mesh.GetPoints().Modified()
            mesh.Modified()

    def update_member_section_in_place(
        self, batch: MemberBatch, model, member_name: str, *,
        rebuild_silhouette: bool = True,
        face_connectivity: np.ndarray | None = None,
        edge_connectivity: np.ndarray | None = None,
    ) -> bool:
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
        if basis is None:
            return False
        local_x, local_y, local_z = basis
        section_offset = (
            LocalAxesRenderer.section_offset(member, start_node, end_node)
            if self.solid_positioning_enabled else np.zeros(3, dtype=float)
        )
        indicator_offset = section_offset if self.position_indicators_with_section else np.zeros(3)
        # Y/Z edits also move labels and end markers. Rebuild this member's
        # complete subset instead of updating only its section vertices.
        element_index = batch.names.index(member_name)
        axis_cells = np.flatnonzero(batch.axes[0].cell_data["element_index"] == element_index)
        if not len(axis_cells) or not np.allclose(
            batch.axes[0].points[2 * axis_cells[0]],
            (start + end) / 2.0 + indicator_offset, rtol=0.0, atol=1e-12,
        ):
            return False
        solid_x, solid_y, solid_z = basis
        solid_start, solid_end = start.copy(), end.copy()
        offsets = getattr(member, "solid_face_offsets", (0.0, 0.0)) if self.solid_positioning_enabled else (0.0, 0.0)
        face_angles = (
            getattr(member, "solid_face_angles", (0.0, 0.0, 0.0, 0.0))
            if self.solid_positioning_enabled else (0.0, 0.0, 0.0, 0.0)
        )
        if len(offsets) == 2:
            candidate_start = start - solid_x * float(offsets[0])
            candidate_end = end + solid_x * float(offsets[1])
            if float(np.dot(candidate_end - candidate_start, solid_x)) > 1e-9:
                solid_start, solid_end = candidate_start, candidate_end
        solid_origin = solid_start + section_offset
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
                (batch.faces.faces if face_connectivity is None else face_connectivity)[
                    face_cell_start * 4:face_cell_end * 4
                ],
                _offset_cells(face_source.faces, face_start),
            )
            or not np.array_equal(
                (batch.edges.lines if edge_connectivity is None else edge_connectivity)[
                    edge_cell_start * 3:edge_cell_end * 3
                ],
                _offset_cells(edge_source.lines, edge_start),
            )
        ):
            return False

        face_points = _transformed_points(
            face_source.points, solid_origin, solid_delta, solid_y, solid_z, face_angles,
        )
        edge_points = _transformed_points(
            edge_source.points, solid_origin, solid_delta, solid_y, solid_z, face_angles,
        )
        batch.faces.points[face_start:face_end] = face_points
        batch.edges.points[edge_start:edge_end] = edge_points
        batch.faces.GetPoints().Modified()
        batch.edges.GetPoints().Modified()
        batch.faces.Modified()
        batch.edges.Modified()

        source_normals = face_source.cell_data.get("Normals")
        if any(face_angles):
            deformed_source = pv.PolyData(
                deform_extruded_points(face_source.points, float(np.linalg.norm(solid_delta)), face_angles),
                faces=face_source.faces,
            ).compute_normals(
                cell_normals=True, point_normals=False, split_vertices=False,
                consistent_normals=True, auto_orient_normals=True, inplace=False,
            )
            source_normals = deformed_source.cell_data.get("Normals")
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
        if rebuild_silhouette and (had_silhouette or member.section in self._silhouette_sections):
            batch.silhouette_faces_by_color = self._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
        batch.section_offsets[element_index] = section_offset
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
        batch.section_offsets[element_index] = replacement.section_offsets[0]
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
        batch.section_offsets[element_index] = replacement.section_offsets[0]
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
        batch.section_offsets = np.concatenate((batch.section_offsets, tail.section_offsets))
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
        batch.section_offsets = np.delete(batch.section_offsets, element_index, axis=0)
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
        cells_by_color: dict[tuple[int, int, int], list[np.ndarray]] = {}
        point_counts: dict[tuple[int, int, int], int] = {}
        for member_name, source in sources.items():
            color = member_colors[member_name]
            points_by_color.setdefault(color, []).append(source.points)
            cells_by_color.setdefault(color, [])
            point_counts.setdefault(color, 0)
            cells_by_color[color].append(_offset_cells(source.faces, point_counts[color]))
            point_counts[color] += len(source.points)
        return {
            color: pv.PolyData(
                np.vstack(points_by_color[color]),
                faces=np.concatenate(cells_by_color[color]),
            )
            for color in points_by_color
        }

    def silhouette_mesh(self, batch: MemberBatch, camera) -> pv.PolyData:
        """Build the visible contour pass for the current camera."""
        if not batch.silhouette_faces_by_color:
            return _empty_mesh()
        points: list[np.ndarray] = []
        lines: list[np.ndarray] = []
        colors: list[np.ndarray] = []
        point_count = 0
        for color, faces in batch.silhouette_faces_by_color.items():
            silhouette = self.solids.silhouette_for(faces, camera)
            if not silhouette.n_lines:
                continue
            points.append(silhouette.points)
            lines.append(_offset_cells(silhouette.lines, point_count))
            edge_color = np.asarray(color, dtype=float) * 0.65
            colors.append(np.tile(edge_color.astype(np.uint8), (silhouette.n_lines, 1)))
            point_count += len(silhouette.points)

        if not points:
            return _empty_mesh()
        mesh = pv.PolyData(np.vstack(points), lines=np.concatenate(lines))
        mesh.cell_data["rgb"] = np.vstack(colors)
        return mesh

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
        offset = LocalAxesRenderer.end_indicator_offset(float(np.linalg.norm(end - start)), radius)
        for endpoint, inward, has_release in (
            (start, local_x, any(releases[index] for index in (0, 2, 4, 6, 8, 10))),
            (end, -local_x, any(releases[index] for index in (1, 3, 5, 7, 9, 11))),
        ):
            if not has_release:
                continue
            center = endpoint + inward * offset
            circle_radius = radius * 1.05
            angles = np.linspace(0.0, 2.0 * pi, 32)
            destination.append(np.asarray([
                center + local_y * cos(angle) * circle_radius + local_z * sin(angle) * circle_radius
                for angle in angles
            ]))


class BatchedNodeRenderer:
    """Merge node markers and supports while retaining per-cell node identity."""

    def __init__(self, *, glyphs: bool = False) -> None:
        self.glyphs = glyphs
        self._support_templates: dict[tuple[bool, ...], pv.PolyData | None] = {}

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
        tail = BatchedNodeRenderer(glyphs=batch.glyphs).build(tail_model, radius)
        old = batch.geometry
        new = tail.geometry
        points = np.concatenate((np.asarray(old.points), np.asarray(new.points)))
        if batch.glyphs:
            geometry = pv.PolyData(points)
        else:
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
        if self.glyphs:
            positions = np.asarray([
                (node.x, node.y, node.z) for node in model.nodes.values()
            ], dtype=float).reshape((-1, 3))
            geometry = pv.PolyData(positions)
            if names:
                geometry.cell_data["element_index"] = np.arange(len(names), dtype=np.int32)
                geometry.cell_data["rgb"] = np.zeros((len(names), 3), dtype=np.uint8)
            return NodeBatch(
                names, geometry, self.build_supports(model, radius),
                positions + (0.0, 0.0, radius * 2.2), glyphs=True,
            )
        sphere = pv.Sphere(
            radius=radius,
            center=(0.0, 0.0, 0.0),
            theta_resolution=20,
            phi_resolution=12,
        )
        positions = np.asarray(
            [(model.nodes[name].x, model.nodes[name].y, model.nodes[name].z) for name in names],
            dtype=float,
        ).reshape((-1, 3))
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
        """Reuse each support pattern and pack translated copies as arrays."""
        del radius
        groups: dict[tuple[bool, ...], list[tuple[float, float, float]]] = {}
        for node in model.nodes.values():
            if any(node.supports):
                groups.setdefault(tuple(node.supports), []).append((node.x, node.y, node.z))
        points = []
        faces = []
        point_offset = 0
        for pattern, positions in groups.items():
            if pattern not in self._support_templates:
                origin = SimpleNamespace(x=0.0, y=0.0, z=0.0, supports=pattern)
                template = self._support_mesh(origin, 0.0)
                if template is not None and not isinstance(template, pv.PolyData):
                    surface = vtkDataSetSurfaceFilter()
                    surface.SetInputData(template)
                    surface.Update()
                    template = pv.wrap(surface.GetOutput())
                self._support_templates[pattern] = template
            template = self._support_templates[pattern]
            if template is None:
                continue
            vertices = np.asarray(template.points, dtype=float)
            source_faces = np.asarray(template.faces, dtype=np.int64)
            id_mask = np.ones(len(source_faces), dtype=bool)
            cursor = 0
            while cursor < len(source_faces):
                id_mask[cursor] = False
                cursor += int(source_faces[cursor]) + 1
            offsets = point_offset + np.arange(len(positions), dtype=np.int64) * len(vertices)
            connectivity = np.tile(source_faces, (len(positions), 1))
            connectivity[:, id_mask] += offsets[:, None]
            points.append((vertices[None, :, :] + np.asarray(positions)[:, None, :]).reshape(-1, 3))
            faces.append(connectivity.ravel())
            point_offset += len(positions) * len(vertices)
        if not points:
            return _empty_mesh()
        return pv.PolyData(np.concatenate(points), faces=np.concatenate(faces))

    @staticmethod
    def _support_mesh(node, radius: float) -> pv.PolyData | None:
        del radius
        return build_support_mesh(node)
