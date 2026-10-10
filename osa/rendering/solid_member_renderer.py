"""Renderização opcional dos membros como sólidos extrudados."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyvista as pv
import vtk

from osa.sections import SectionShape, section_shape

from .local_axes_renderer import LocalAxesRenderer


@dataclass(frozen=True, slots=True)
class SolidMemberVisual:
    """The face and contour-edge actors representing one solid member."""

    face_actor: object
    edge_actor: object


class SolidMemberRenderer:
    """Build and place cached section meshes along structural members."""

    _millimeters_to_model_units = 1e-3
    _arc_steps = 12
    _edge_feature_angle = 25.0

    def __init__(self) -> None:
        self._mesh_cache: dict[tuple[tuple[tuple[float, float], ...], ...], pv.PolyData] = {}
        self._edge_mesh_cache: dict[tuple[tuple[tuple[float, float], ...], ...], pv.PolyData] = {}
        self._longitudinal_edge_indices_cache: dict[
            tuple[tuple[tuple[float, float], ...], ...], tuple[tuple[int, ...], ...]
        ] = {}

    def render(self, plotter, member, start, end, *, visible: bool) -> SolidMemberVisual | None:
        try:
            shape = section_shape(
                member.section,
                member.geometry_dict(),
                arc_steps=self._arc_steps,
            )
            if shape is None:
                return None
            mesh = self._mesh_for(shape)
            edge_mesh = self._edge_mesh_for(shape)
        except (KeyError, TypeError, ValueError):
            # A member without a complete/valid section keeps the line
            # representation as a safe fallback.
            return None

        basis = LocalAxesRenderer.basis(start, end, rotation=member.rotation)
        if basis is None:
            return None
        face_actor = plotter.add_mesh(
            mesh,
            color=member.color,
            smooth_shading=False,
            lighting=True,
            pickable=False,
            reset_camera=False,
            render=False,
        )
        edge_actor = plotter.add_mesh(
            edge_mesh,
            color=self.edge_color(member.color),
            line_width=1.5,
            lighting=False,
            pickable=False,
            reset_camera=False,
            render=False,
        )
        face_actor.SetObjectName(f"bar:{member.name}")
        face_actor.SetPickable(False)
        face_actor.SetVisibility(visible)
        face_actor.GetProperty().SetEdgeVisibility(False)
        face_actor.GetProperty().SetInterpolationToFlat()
        face_actor.GetProperty().SetSpecular(0.12)
        edge_actor.SetObjectName(f"bar-edge:{member.name}")
        edge_actor.SetPickable(False)
        edge_actor.SetVisibility(visible)
        edge_mapper = edge_actor.GetMapper()
        edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()
        edge_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
        edge_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
        self.update_transform(face_actor, start, end, rotation=member.rotation, member=member)
        self.update_transform(edge_actor, start, end, rotation=member.rotation, member=member)
        return SolidMemberVisual(face_actor, edge_actor)

    def update_transform(self, actor, start, end, *, rotation: int = 0, member=None) -> bool:
        """Update an existing actor without rebuilding its shared mesh."""
        basis = LocalAxesRenderer.basis(start, end, rotation=rotation)
        if basis is None:
            return False
        x_axis, y_axis, z_axis = basis
        base_basis = LocalAxesRenderer.basis(start, end, rotation=0)
        if base_basis is None:
            return False
        _base_x, base_y_axis, base_z_axis = base_basis
        start_point = np.asarray((start.x, start.y, start.z), dtype=float)
        end_point = np.asarray((end.x, end.y, end.z), dtype=float)
        if member is not None:
            offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
            if len(offsets) == 2:
                candidate_start = start_point - x_axis * float(offsets[0])
                candidate_end = end_point + x_axis * float(offsets[1])
                if float(np.dot(candidate_end - candidate_start, x_axis)) > 1e-9:
                    start_point, end_point = candidate_start, candidate_end
            section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
            if len(section_offsets) == 2:
                start_point += (
                    base_y_axis * float(section_offsets[0])
                    + base_z_axis * float(section_offsets[1])
                )
        length = float(np.linalg.norm(end_point - start_point))
        matrix = vtk.vtkMatrix4x4()
        matrix.Identity()
        for row in range(3):
            matrix.SetElement(row, 0, float(x_axis[row] * length))
            matrix.SetElement(row, 1, float(y_axis[row]))
            matrix.SetElement(row, 2, float(z_axis[row]))
            matrix.SetElement(row, 3, float(start_point[row]))
        actor.SetUserMatrix(matrix)
        return True

    def _mesh_for(self, shape: SectionShape) -> pv.PolyData:
        cached = self._mesh_cache.get(shape.signature)
        if cached is not None:
            return cached
        mesh = self._build_mesh(shape)
        self._mesh_cache[shape.signature] = mesh
        return mesh

    def _edge_mesh_for(self, shape: SectionShape) -> pv.PolyData:
        cached = self._edge_mesh_cache.get(shape.signature)
        if cached is not None:
            return cached
        mesh = self._build_edge_mesh(shape)
        self._edge_mesh_cache[shape.signature] = mesh
        return mesh

    def longitudinal_edge_indices(self, shape: SectionShape) -> tuple[tuple[int, ...], ...]:
        """Return the profile vertices that need longitudinal edges.

        The deformed solid is assembled along a changing centerline, so its
        side faces cannot reuse the unit-length edge mesh directly. Mapping
        the selected longitudinal edges back to profile vertices lets that
        renderer use exactly the same feature and curve-transition rules.
        """
        cached = self._longitudinal_edge_indices_cache.get(shape.signature)
        if cached is not None:
            return cached

        indices_by_loop: list[list[int]] = [[] for _ in shape.loops]
        edge_mesh = self._edge_mesh_for(shape)
        raw_lines = edge_mesh.lines
        offset = 0
        scale = self._millimeters_to_model_units
        loop_arrays = [np.asarray(loop, dtype=float) for loop in shape.loops]
        while offset < len(raw_lines):
            count = int(raw_lines[offset])
            point_ids = raw_lines[offset + 1:offset + count + 1]
            offset += count + 1
            if count != 2:
                continue
            first, second = edge_mesh.points[point_ids]
            if abs(float(first[0] - second[0])) <= 0.5:
                continue
            profile_point = np.asarray(first[1:], dtype=float) / scale
            for loop_index, loop in enumerate(loop_arrays):
                distances = np.linalg.norm(loop - profile_point, axis=1)
                point_index = int(np.argmin(distances))
                if float(distances[point_index]) <= 1e-4:
                    if point_index not in indices_by_loop[loop_index]:
                        indices_by_loop[loop_index].append(point_index)
                    break

        result = tuple(tuple(indices) for indices in indices_by_loop)
        self._longitudinal_edge_indices_cache[shape.signature] = result
        return result

    @staticmethod
    def silhouette_for(mesh: pv.PolyData, camera) -> pv.PolyData:
        """Return the camera-facing outer contour of a solid mesh.

        Feature edges describe the geometry itself, while a silhouette
        describes what is visible from the current view. Keeping the passes
        separate avoids drawing tessellation seams along curved walls.
        """
        silhouette = vtk.vtkPolyDataSilhouette()
        silhouette.SetInputData(mesh)
        silhouette.SetCamera(camera)
        silhouette.Update()
        return pv.wrap(silhouette.GetOutput()).copy(deep=True)

    @staticmethod
    def edge_color(face_color: str) -> tuple[float, float, float]:
        return tuple(max(0.0, min(1.0, channel * 0.65)) for channel in pv.Color(face_color).float_rgb)

    def _build_edge_mesh(self, shape: SectionShape) -> pv.PolyData:
        surface = self._mesh_for(shape)
        feature_edges = vtk.vtkFeatureEdges()
        feature_edges.SetInputData(surface)
        feature_edges.BoundaryEdgesOn()
        feature_edges.FeatureEdgesOn()
        feature_edges.NonManifoldEdgesOn()
        feature_edges.ManifoldEdgesOff()
        feature_edges.SetFeatureAngle(self._edge_feature_angle)
        feature_edges.Update()
        feature_mesh = pv.wrap(feature_edges.GetOutput()).copy(deep=True)
        transition_mesh = self._build_curve_transition_mesh(shape)
        if not transition_mesh.n_lines:
            return feature_mesh
        append = vtk.vtkAppendPolyData()
        append.AddInputData(feature_mesh)
        append.AddInputData(transition_mesh)
        append.Update()
        return pv.wrap(append.GetOutput()).copy(deep=True)

    def _build_curve_transition_mesh(self, shape: SectionShape) -> pv.PolyData:
        """Add longitudinal edges at the ends of sampled curved runs."""
        if self._is_round_shape(shape):
            return pv.PolyData()

        transition_indices: list[tuple[tuple[float, float], ...]] = []
        for loop in shape.loops:
            indices = self._curve_transition_indices(loop)
            transition_indices.extend(
                tuple(loop[index] for index in indices),
            )
        if not transition_indices:
            return pv.PolyData()

        points = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        scale = self._millimeters_to_model_units
        for point in transition_indices:
            base = points.InsertNextPoint(0.0, point[0] * scale, point[1] * scale)
            end = points.InsertNextPoint(1.0, point[0] * scale, point[1] * scale)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(base)
            lines.InsertCellPoint(end)
        poly_data = vtk.vtkPolyData()
        poly_data.SetPoints(points)
        poly_data.SetLines(lines)
        return pv.wrap(poly_data).copy(deep=True)

    @staticmethod
    def _is_round_shape(shape: SectionShape) -> bool:
        for loop in shape.loops:
            points = np.asarray(loop, dtype=float) - np.asarray(shape.centroid, dtype=float)
            radii = np.linalg.norm(points, axis=1)
            if np.ptp(radii) > max(1e-6, float(np.max(radii)) * 1e-4):
                return False
        return bool(shape.loops)

    @staticmethod
    def _curve_transition_indices(loop: tuple[tuple[float, float], ...]) -> list[int]:
        count = len(loop)
        turns: list[float] = []
        for index, point in enumerate(loop):
            previous = np.asarray(point, dtype=float) - np.asarray(loop[index - 1], dtype=float)
            following = np.asarray(loop[(index + 1) % count], dtype=float) - np.asarray(point, dtype=float)
            denominator = float(np.linalg.norm(previous) * np.linalg.norm(following))
            cross = abs(float(previous[0] * following[1] - previous[1] * following[0]))
            turns.append(cross / denominator if denominator > 1e-12 else 0.0)

        smooth = [turn < 0.5 for turn in turns]
        if not any(smooth):
            return []

        # Adjacent fillets can belong to the same smooth run when the
        # straight segment between them is sampled with smooth end points.
        # In that case using only the first and last point of the run loses
        # the two transition edges in the middle. Keep every low-turn group
        # inside the run so each curved segment contributes both ends.
        if all(smooth):
            smooth_runs = [list(range(count))]
        else:
            smooth_runs: list[list[int]] = []
            for index, is_smooth in enumerate(smooth):
                if not is_smooth or smooth[index - 1]:
                    continue
                run = [index]
                cursor = (index + 1) % count
                while cursor != index and smooth[cursor]:
                    run.append(cursor)
                    cursor = (cursor + 1) % count
                smooth_runs.append(run)

        transitions: list[int] = []
        for run in smooth_runs:
            threshold = min(turns[index] for index in run) * 1.5
            transitions.extend(
                index for index in run if turns[index] <= threshold
            )
        return list(dict.fromkeys(transitions))

    def _build_mesh(self, shape: SectionShape) -> pv.PolyData:
        points = vtk.vtkPoints()
        contours = vtk.vtkCellArray()
        scale = self._millimeters_to_model_units
        for loop in shape.loops:
            ids = vtk.vtkIdList()
            for y, z in loop:
                ids.InsertNextId(points.InsertNextPoint(0.0, y * scale, z * scale))
            ids.InsertNextId(ids.GetId(0))
            contours.InsertNextCell(ids)

        contour_data = vtk.vtkPolyData()
        contour_data.SetPoints(points)
        contour_data.SetLines(contours)

        triangulator = vtk.vtkContourTriangulator()
        triangulator.SetInputData(contour_data)
        triangulator.Update()
        triangulated = triangulator.GetOutput()
        if triangulated.GetNumberOfCells() == 0:
            raise ValueError("Não foi possível triangular a seção transversal.")

        extrusion = vtk.vtkLinearExtrusionFilter()
        extrusion.SetInputData(triangulated)
        extrusion.SetVector(1.0, 0.0, 0.0)
        extrusion.SetScaleFactor(1.0)
        extrusion.CappingOn()
        extrusion.Update()
        mesh = pv.wrap(extrusion.GetOutput()).copy(deep=True)
        mesh = mesh.clean(tolerance=1e-12)
        return mesh.compute_normals(
            cell_normals=True,
            point_normals=False,
            split_vertices=True,
            consistent_normals=True,
            auto_orient_normals=True,
            inplace=False,
        )
