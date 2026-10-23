"""Orthographic, hidden-line previews of a bounded solid-model view."""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QVBoxLayout
from pyvistaqt import QtInteractor

from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.solid_member_renderer import SolidMemberRenderer
from osa.sections import section_shape


class DetailingViewPreview(QFrame):
    """Render visible solid edges inside the selected plane's depth range."""

    _plane_data = {
        "XY": ((0.0, 0.0, 1.0), (0, 1), 2, (0.0, 1.0, 0.0)),
        "XZ": ((0.0, 1.0, 0.0), (0, 2), 1, (0.0, 0.0, 1.0)),
        "YZ": ((1.0, 0.0, 0.0), (1, 2), 0, (0.0, 0.0, 1.0)),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailingViewPreview")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#detailingViewPreview { background: #ffffff; "
            "border: 1px solid #d0d7de; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._plotter = QtInteractor(
            self,
            off_screen=False,
            multi_samples=0,
            auto_update=False,
        )
        self._plotter.set_background("white")
        self._plotter.enable_parallel_projection()
        layout.addWidget(self._plotter)
        self._renderer = SolidMemberRenderer()
        self._model_cache_key = None
        self._solid_meshes: list[pv.PolyData] = []
        self._pending_render = False
        self._pending_view_render = None

    def set_view(
        self,
        model,
        plane: str,
        coordinate: float | tuple[tuple[float, float, float], ...],
        *,
        upper_offset_cm: float = 50.0,
        lower_offset_cm: float = 50.0,
        orientation: str = "Superior para inferior",
        rotation_degrees: float = 0.0,
    ) -> None:
        """Render the slab around a view plane, looking from its selected side."""
        plane_data = self._plane_data.get(plane)
        if model is None or (plane != "custom" and plane_data is None):
            self._clear_preview()
            return

        self._ensure_model_meshes(model)
        if plane == "custom":
            points = np.asarray(coordinate, dtype=float)
            if points.shape != (3, 3):
                self._clear_preview()
                return
            origin = points[0]
            u_axis = points[1] - origin
            u_length = float(np.linalg.norm(u_axis))
            if u_length <= 1e-9:
                self._clear_preview()
                return
            u_axis /= u_length
            normal = np.cross(u_axis, points[2] - origin)
            normal_length = float(np.linalg.norm(normal))
            if normal_length <= 1e-9:
                self._clear_preview()
                return
            normal /= normal_length
            v_axis = np.cross(normal, u_axis)
            basis = np.vstack((u_axis, v_axis, normal))
            transform = np.eye(4, dtype=float)
            transform[:3, :3] = basis
            transform[:3, 3] = -basis @ origin
            solid_meshes = []
            for solid in self._solid_meshes:
                local_mesh = solid.copy(deep=True)
                local_mesh.transform(transform, inplace=True)
                solid_meshes.append(local_mesh)
            normal = (0.0, 0.0, 1.0)
            display_axes = (0, 1)
            normal_axis = 2
            view_up = (0.0, 1.0, 0.0)
            coordinate_value = 0.0
        else:
            normal, display_axes, normal_axis, view_up = plane_data
            solid_meshes = self._solid_meshes
            coordinate_value = float(coordinate)
        upper = coordinate_value + max(0.0, float(upper_offset_cm)) / 100.0
        lower = coordinate_value - max(0.0, float(lower_offset_cm)) / 100.0
        if upper < lower:
            upper, lower = lower, upper

        clipped_meshes: list[pv.PolyData] = []
        for solid in solid_meshes:
            clipped = self._clip_to_depth_range(
                solid, normal, normal_axis, lower, upper
            )
            if clipped is not None and clipped.n_points and clipped.n_cells:
                clipped_meshes.append(clipped)

        if not clipped_meshes:
            self._clear_preview()
            return

        render_args = (
            clipped_meshes,
            display_axes,
            normal,
            normal_axis,
            lower,
            upper,
            view_up,
            orientation,
            float(rotation_degrees),
        )
        if not self._plotter.isVisible():
            self._pending_view_render = render_args
            self._pending_render = True
            return
        try:
            self._render_visible_lines(*render_args)
        except Exception:
            self._clear_preview()

    def _clear_preview(self) -> None:
        self._pending_view_render = None
        self._pending_render = False
        self._plotter.clear()
        self._plotter.set_background("white")
        if self._plotter.isVisible():
            self._plotter.render()

    def _ensure_model_meshes(self, model) -> None:
        cache_key = (id(model), getattr(model, "revision", None))
        if cache_key == self._model_cache_key:
            return

        meshes: list[pv.PolyData] = []
        for member in model.bars.values():
            start = model.nodes.get(member.start_node)
            end = model.nodes.get(member.end_node)
            if start is None or end is None:
                continue
            try:
                shape = section_shape(
                    member.section,
                    member.geometry_dict(),
                    arc_steps=self._renderer._arc_steps,
                    mirror_z=member.section_mirrored,
                )
                if shape is None:
                    continue
                basis = LocalAxesRenderer.basis(start, end, rotation=member.rotation)
                base_basis = LocalAxesRenderer.basis(start, end, rotation=0)
                if basis is None or base_basis is None:
                    continue

                x_axis, y_axis, z_axis = basis
                base_y_axis, base_z_axis = base_basis[1], base_basis[2]
                start_point = np.asarray((start.x, start.y, start.z), dtype=float)
                end_point = np.asarray((end.x, end.y, end.z), dtype=float)
                face_offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
                if len(face_offsets) == 2:
                    candidate_start = start_point - x_axis * float(face_offsets[0])
                    candidate_end = end_point + x_axis * float(face_offsets[1])
                    if float(np.dot(candidate_end - candidate_start, x_axis)) > 1e-9:
                        start_point, end_point = candidate_start, candidate_end
                section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
                if len(section_offsets) == 2:
                    start_point += (
                        base_y_axis * float(section_offsets[0])
                        + base_z_axis * float(section_offsets[1])
                    )

                length = float(np.linalg.norm(end_point - start_point))
                transform = np.eye(4, dtype=float)
                transform[:3, 0] = x_axis * length
                transform[:3, 1] = y_axis
                transform[:3, 2] = z_axis
                transform[:3, 3] = start_point
                mesh = self._renderer._mesh_for(shape).copy(deep=True)
                mesh.transform(transform, inplace=True)
                meshes.append(mesh)
            except (KeyError, TypeError, ValueError, RuntimeError):
                continue

        self._solid_meshes = meshes
        self._model_cache_key = cache_key

    @staticmethod
    def _clip_to_depth_range(
        mesh: pv.PolyData,
        normal: tuple[float, float, float],
        normal_axis: int,
        lower: float,
        upper: float,
    ) -> pv.PolyData | None:
        planes = vtk.vtkPlaneCollection()
        for value, sign in ((lower, 1.0), (upper, -1.0)):
            plane = vtk.vtkPlane()
            origin = [0.0, 0.0, 0.0]
            origin[normal_axis] = value
            plane.SetOrigin(origin)
            plane.SetNormal(*(sign * component for component in normal))
            planes.AddItem(plane)

        clipper = vtk.vtkClipClosedSurface()
        clipper.SetInputData(mesh)
        clipper.SetClippingPlanes(planes)
        clipper.GenerateFacesOn()
        clipper.GenerateOutlineOn()
        clipper.Update()
        output = pv.wrap(clipper.GetOutput()).copy(deep=True)
        return output if output.n_points and output.n_cells else None

    def _render_visible_lines(
        self,
        meshes: list[pv.PolyData],
        display_axes: tuple[int, int],
        normal: tuple[float, float, float],
        normal_axis: int,
        lower: float,
        upper: float,
        view_up: tuple[float, float, float],
        orientation: str,
        rotation_degrees: float,
    ) -> None:
        """Render the clipped solids as depth-tested, uniform-weight edges."""
        points = np.concatenate([mesh.points for mesh in meshes], axis=0)
        min_u, max_u = points[:, display_axes[0]].min(), points[:, display_axes[0]].max()
        min_v, max_v = points[:, display_axes[1]].min(), points[:, display_axes[1]].max()
        span_u = max(float(max_u - min_u), 1e-3)
        span_v = max(float(max_v - min_v), 1e-3)
        center = [0.0, 0.0, 0.0]
        center[display_axes[0]] = float((min_u + max_u) / 2.0)
        center[display_axes[1]] = float((min_v + max_v) / 2.0)
        center[normal_axis] = (lower + upper) / 2.0

        camera_direction = np.asarray(normal, dtype=float)
        if orientation == "Inferior para superior":
            camera_direction = -camera_direction
        # Roll the camera around its viewing axis so the orthographic drawing
        # rotates in the sheet without changing the clipping plane.
        view_direction = -camera_direction
        base_up = np.asarray(view_up, dtype=float)
        angle = -np.deg2rad(float(rotation_degrees))
        view_up = (
            base_up * np.cos(angle)
            + np.cross(view_direction, base_up) * np.sin(angle)
            + view_direction * np.dot(view_direction, base_up) * (1.0 - np.cos(angle))
        ).tolist()
        depth = max(upper - lower, 1e-3)
        distance = max(span_u, span_v, depth) * 2.0 + 1.0
        camera_position = np.asarray(center) + camera_direction * distance

        plotter = self._plotter
        plotter.clear()
        plotter.set_background("white")
        plotter.enable_parallel_projection()
        aspect = max(plotter.width(), 1) / max(plotter.height(), 1)
        rotated_span_u = abs(np.cos(angle)) * span_u + abs(np.sin(angle)) * span_v
        rotated_span_v = abs(np.sin(angle)) * span_u + abs(np.cos(angle)) * span_v
        parallel_scale = max(rotated_span_v * 0.56, rotated_span_u / aspect * 0.56)
        # Opaque white faces write to the depth buffer while blending into the
        # sheet background, hiding rear lines without drawing shaded surfaces.
        for mesh in meshes:
            plotter.add_mesh(
                mesh,
                color="#ffffff",
                lighting=False,
                show_edges=False,
                pickable=False,
                reset_camera=False,
                render=False,
            )
        for mesh in meshes:
            edges = mesh.extract_feature_edges(
                boundary_edges=True,
                feature_edges=True,
                manifold_edges=False,
                non_manifold_edges=True,
                feature_angle=25.0,
            )
            if not edges.n_lines:
                continue
            actor = plotter.add_mesh(
                edges,
                color="#24292f",
                line_width=1.35,
                lighting=False,
                pickable=False,
                reset_camera=False,
                render=False,
            )
            mapper = actor.GetMapper()
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        plotter.camera_position = (
            camera_position.tolist(),
            center,
            view_up,
        )
        plotter.camera.parallel_projection = True
        plotter.camera.parallel_scale = parallel_scale
        plotter.reset_camera_clipping_range()
        plotter.render()
        self._pending_view_render = None
        self._pending_render = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending_render:
            QTimer.singleShot(0, self._render_pending_preview)

    def _render_pending_preview(self) -> None:
        render_args = self._pending_view_render
        if not self._pending_render or render_args is None or not self._plotter.isVisible():
            return
        try:
            self._render_visible_lines(*render_args)
        except Exception:
            self._clear_preview()
