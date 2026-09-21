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

    def __init__(self) -> None:
        self._mesh_cache: dict[tuple[tuple[tuple[float, float], ...], ...], pv.PolyData] = {}
        self._edge_mesh_cache: dict[tuple[tuple[tuple[float, float], ...], ...], pv.PolyData] = {}

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
        self.update_transform(face_actor, start, end, rotation=member.rotation)
        self.update_transform(edge_actor, start, end, rotation=member.rotation)
        return SolidMemberVisual(face_actor, edge_actor)

    def update_transform(self, actor, start, end, *, rotation: int = 0) -> bool:
        """Update an existing actor without rebuilding its shared mesh."""
        basis = LocalAxesRenderer.basis(start, end, rotation=rotation)
        if basis is None:
            return False
        x_axis, y_axis, z_axis = basis
        start_point = np.asarray((start.x, start.y, start.z), dtype=float)
        end_point = np.asarray((end.x, end.y, end.z), dtype=float)
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

    @staticmethod
    def edge_color(face_color: str) -> tuple[float, float, float]:
        return tuple(max(0.0, min(1.0, channel * 0.65)) for channel in pv.Color(face_color).float_rgb)

    def _build_edge_mesh(self, shape: SectionShape) -> pv.PolyData:
        points = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        scale = self._millimeters_to_model_units
        for loop in shape.loops:
            base_ids = [points.InsertNextPoint(0.0, y * scale, z * scale) for y, z in loop]
            end_ids = [points.InsertNextPoint(1.0, y * scale, z * scale) for y, z in loop]
            for index, next_index in enumerate((*range(1, len(loop)), 0)):
                for first, second in (
                    (base_ids[index], base_ids[next_index]),
                    (end_ids[index], end_ids[next_index]),
                    (base_ids[index], end_ids[index]),
                ):
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(first)
                    lines.InsertCellPoint(second)
        poly_data = vtk.vtkPolyData()
        poly_data.SetPoints(points)
        poly_data.SetLines(lines)
        return pv.wrap(poly_data).copy(deep=True)

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
