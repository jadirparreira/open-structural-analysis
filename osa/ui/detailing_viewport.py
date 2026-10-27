"""Interactive, fixed-camera viewport for detailing drawings."""

from __future__ import annotations

from collections import OrderedDict
from math import cos, radians, sin

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QVBoxLayout
from pyvistaqt import QtInteractor

from osa.ui.detailing_preview import DetailingViewPreview, _ViewGeometryCalculator


class DetailingViewViewport(QFrame):
    """Display solid geometry in a locked orthographic camera with pan and zoom."""

    view_ready = Signal(bool)

    _plane_data = DetailingViewPreview._plane_data
    _isometric_directions = DetailingViewPreview._isometric_directions
    _scene_cache_limit = 8
    _dxf_cache_limit = 8

    def __init__(self, parent=None, *, antialiasing_samples: int = 4) -> None:
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
            multi_samples=int(antialiasing_samples),
            auto_update=False,
        )
        self._plotter.set_background("white")
        self._plotter.enable_parallel_projection()
        self._plotter.iren.interactor.SetInteractorStyle(vtk.vtkInteractorStyleUser())
        layout.addWidget(self._plotter)
        self._plotter.installEventFilter(self)
        self._plotter.interactor.installEventFilter(self)

        self._render_generation = 0
        self._render_pending = False
        self._drag_position: QPointF | None = None
        self._current_model = None
        self._current_view: tuple | None = None
        self._scene_cache: OrderedDict[tuple, tuple[pv.PolyData, pv.PolyData]] = OrderedDict()
        self._dxf_cache: OrderedDict[tuple, tuple] = OrderedDict()
        self._fit_spans: tuple[float, float] | None = None
        self._fit_parallel_scale = 1.0
        self._zoom_factor = 1.0
        self._is_shutdown = False

    def shutdown(self) -> None:
        """Release the VTK render window before its owning dialog is destroyed."""
        if self._is_shutdown:
            return
        self._is_shutdown = True
        self._render_generation += 1
        self._render_pending = False
        self._plotter.close()

    @staticmethod
    def _coordinate_key(plane: str, coordinate) -> tuple:
        if plane == "custom":
            return tuple(tuple(float(value) for value in point) for point in coordinate)
        return (float(coordinate),)

    @classmethod
    def _view_key(cls, model, plane, coordinate, settings) -> tuple:
        return (
            id(model),
            getattr(model, "revision", None),
            plane,
            cls._coordinate_key(plane, coordinate),
            float(settings.get("upper_offset_cm", 50.0)),
            float(settings.get("lower_offset_cm", 50.0)),
            settings.get("orientation", "Superior para inferior"),
            float(settings.get("rotation_degrees", 0.0)),
        )

    def request_view(self, model, plane: str, coordinate, **settings) -> None:
        """Prepare and show a view without constructing export linework."""
        self._render_generation += 1
        self._render_pending = True
        self._current_model = model
        self._current_view = (plane, coordinate, dict(settings))
        if model is None:
            self._clear_view()
            self.view_ready.emit(False)
            return

        cache_key = self._view_key(model, plane, coordinate, settings)
        cached = self._scene_cache.get(cache_key)
        if cached is None:
            try:
                surfaces, edges = self._build_scene_meshes(model, plane, coordinate, settings)
            except (IndexError, KeyError, RuntimeError, TypeError, ValueError):
                self._clear_view()
                self.view_ready.emit(False)
                return
            if surfaces is None or edges is None:
                self._clear_view()
                self.view_ready.emit(False)
                return
            cached = (surfaces, edges)
            self._scene_cache[cache_key] = cached
            self._scene_cache.move_to_end(cache_key)
            while len(self._scene_cache) > self._scene_cache_limit:
                self._scene_cache.popitem(last=False)
        else:
            self._scene_cache.move_to_end(cache_key)

        try:
            self._show_scene(cached[0], cached[1], plane, coordinate, settings)
        except (IndexError, KeyError, RuntimeError, TypeError, ValueError):
            self._clear_view()
            self.view_ready.emit(False)
            return
        self._render_pending = False
        self.view_ready.emit(True)

    def _build_scene_meshes(self, model, plane: str, coordinate, settings):
        calculator = _ViewGeometryCalculator()
        calculator._mesh_cache_owner = model
        DetailingViewPreview._ensure_model_meshes(calculator, model)
        if not calculator._solid_meshes:
            return None, None

        isometric = plane in self._isometric_directions
        custom_transform = None
        if isometric:
            DetailingViewPreview._ensure_model_edge_meshes(calculator, model)
            surfaces = calculator._solid_meshes
            edge_meshes = calculator._solid_edge_meshes or []
            surface_member_names = list(calculator._solid_member_names)
        else:
            plane_data = self._plane_data.get(plane)
            if plane == "custom":
                points = np.asarray(coordinate, dtype=float)
                if points.shape != (3, 3):
                    return None, None
                origin = points[0]
                u_axis = points[1] - origin
                u_length = float(np.linalg.norm(u_axis))
                if u_length <= 1e-9:
                    return None, None
                u_axis /= u_length
                normal = np.cross(u_axis, points[2] - origin)
                normal_length = float(np.linalg.norm(normal))
                if normal_length <= 1e-9:
                    return None, None
                normal /= normal_length
                v_axis = np.cross(normal, u_axis)
                basis = np.vstack((u_axis, v_axis, normal))
                transform = np.eye(4, dtype=float)
                transform[:3, :3] = basis
                transform[:3, 3] = -basis @ origin
                custom_transform = transform
                solids = []
                for solid in calculator._solid_meshes:
                    local_mesh = solid.copy(deep=True)
                    local_mesh.transform(transform, inplace=True)
                    solids.append(local_mesh)
                normal_axis, coordinate_value = 2, 0.0
            elif plane_data is not None:
                normal, normal_axis, _view_up = plane_data
                solids = calculator._solid_meshes
                coordinate_value = float(coordinate)
            else:
                return None, None

            upper = coordinate_value + max(
                0.0, float(settings.get("upper_offset_cm", 50.0))
            ) / 100.0
            lower = coordinate_value - max(
                0.0, float(settings.get("lower_offset_cm", 50.0))
            ) / 100.0
            if upper < lower:
                lower, upper = upper, lower
            surfaces = []
            surface_member_names = []
            for member_name, solid in zip(calculator._solid_member_names, solids):
                clipped = DetailingViewPreview._clip_to_depth_range(
                    solid, normal, normal_axis, lower, upper
                )
                if clipped is not None and clipped.n_points and clipped.n_cells:
                    surfaces.append(clipped)
                    surface_member_names.append(member_name)
            edge_meshes = [
                mesh.extract_feature_edges(
                    boundary_edges=True,
                    feature_edges=True,
                    manifold_edges=False,
                    non_manifold_edges=True,
                    feature_angle=25.0,
                )
                for mesh in surfaces
            ]

        interfaces_by_member = DetailingViewPreview._group_interface_planes(model)
        if plane == "custom" and custom_transform is not None:
            interfaces_by_member = {
                member_name: tuple(
                    (
                        custom_transform[:3, :3] @ point + custom_transform[:3, 3],
                        custom_transform[:3, :3] @ direction,
                        tolerance,
                    )
                    for point, direction, tolerance in planes
                )
                for member_name, planes in interfaces_by_member.items()
            }
        filtered_edge_meshes = []
        for member_name, edge_mesh in zip(surface_member_names, edge_meshes):
            interface_planes = interfaces_by_member.get(member_name, ())
            if interface_planes:
                edge_mesh = self._without_group_interface_edges(
                    edge_mesh, interface_planes
                )
            filtered_edge_meshes.append(edge_mesh)
        edge_meshes = filtered_edge_meshes

        surfaces = [mesh for mesh in surfaces if mesh.n_points and mesh.n_cells]
        edge_meshes = [mesh for mesh in edge_meshes if mesh.n_points and mesh.n_lines]
        if not surfaces or not edge_meshes:
            return None, None
        surface_scene = pv.merge(surfaces, merge_points=False)
        edge_scene = pv.merge(edge_meshes, merge_points=False)
        return surface_scene, edge_scene

    @staticmethod
    def _without_group_interface_edges(edge_mesh, interface_planes):
        """Drop section edges that the grouped 2D drawing treats as internal."""
        points = np.asarray(edge_mesh.points, dtype=float)
        encoded_lines = np.asarray(edge_mesh.lines, dtype=np.int64)
        visible_lines = []
        offset = 0
        while offset < len(encoded_lines):
            count = int(encoded_lines[offset])
            point_ids = encoded_lines[offset + 1 : offset + count + 1]
            for first, second in zip(point_ids, point_ids[1:]):
                start = points[int(first)]
                end = points[int(second)]
                on_interface = any(
                    abs(float(np.dot(start - origin, normal))) <= tolerance
                    and abs(float(np.dot(end - origin, normal))) <= tolerance
                    for origin, normal, tolerance in interface_planes
                )
                if not on_interface:
                    visible_lines.extend((2, int(first), int(second)))
            offset += count + 1

        filtered = edge_mesh.copy(deep=True)
        filtered.lines = np.asarray(visible_lines, dtype=np.int64)
        return filtered

    def _show_scene(self, surfaces, edges, plane: str, coordinate, settings) -> None:
        self._plotter.clear()
        self._plotter.set_background("white")
        self._plotter.enable_parallel_projection()
        self._plotter.add_mesh(
            surfaces,
            color="#ffffff",
            lighting=False,
            show_edges=False,
            pickable=False,
            reset_camera=False,
            render=False,
        )
        edge_actor = self._plotter.add_mesh(
            edges,
            color="#24292f",
            line_width=1.35,
            lighting=False,
            pickable=False,
            reset_camera=False,
            render=False,
        )
        mapper = edge_actor.GetMapper()
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
        mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        isometric = plane in self._isometric_directions
        if isometric:
            camera_direction = np.asarray(self._isometric_directions[plane], dtype=float)
            camera_direction /= np.linalg.norm(camera_direction)
            view_up = np.asarray((0.0, 0.0, 1.0), dtype=float)
            view_up -= np.dot(view_up, camera_direction) * camera_direction
            view_up /= np.linalg.norm(view_up)
        elif plane == "custom":
            points = np.asarray(coordinate, dtype=float)
            u_axis = points[1] - points[0]
            u_axis /= np.linalg.norm(u_axis)
            camera_direction = np.cross(u_axis, points[2] - points[0])
            camera_direction /= np.linalg.norm(camera_direction)
            view_up = np.cross(camera_direction, u_axis)
        else:
            camera_direction = np.asarray(self._plane_data[plane][0], dtype=float)
            view_up = np.asarray(self._plane_data[plane][2], dtype=float)
        if (
            not isometric
            and settings.get("orientation", "Superior para inferior") == "Inferior para superior"
        ):
            camera_direction *= -1.0

        view_direction = -camera_direction
        angle = radians(-float(settings.get("rotation_degrees", 0.0)))
        view_up = (
            view_up * cos(angle)
            + np.cross(view_direction, view_up) * sin(angle)
            + view_direction * np.dot(view_direction, view_up) * (1.0 - cos(angle))
        )
        view_up /= np.linalg.norm(view_up)
        right = np.cross(view_direction, view_up)
        right /= np.linalg.norm(right)

        points = np.asarray(surfaces.points, dtype=float)
        projected_x = points @ right
        projected_y = points @ view_up
        projected_depth = points @ camera_direction
        center = (
            right * ((float(projected_x.min()) + float(projected_x.max())) / 2.0)
            + view_up * ((float(projected_y.min()) + float(projected_y.max())) / 2.0)
            + camera_direction
            * ((float(projected_depth.min()) + float(projected_depth.max())) / 2.0)
        )
        span_x = max(float(projected_x.max() - projected_x.min()), 1e-3)
        span_y = max(float(projected_y.max() - projected_y.min()), 1e-3)
        self._fit_spans = (span_x, span_y)
        self._zoom_factor = 1.0
        aspect = max(self._plotter.width(), 1) / max(self._plotter.height(), 1)
        parallel_scale = max(span_y * 0.56, span_x / aspect * 0.56)
        distance = max(span_x, span_y, float(np.ptp(projected_depth))) * 2.0 + 1.0
        self._plotter.camera_position = (
            tuple(center + camera_direction * distance),
            tuple(center),
            tuple(view_up),
        )
        self._plotter.camera.parallel_projection = True
        self._plotter.camera.parallel_scale = parallel_scale
        self._plotter.reset_camera_clipping_range()
        self._plotter.render()

    def generate_dxf_segments(self, model, plane: str, coordinate, **settings):
        """Run the exact vector hidden-line pipeline only when DXF is requested."""
        cache_key = self._view_key(model, plane, coordinate, settings)
        cached = self._dxf_cache.get(cache_key)
        if cached is not None:
            self._dxf_cache.move_to_end(cache_key)
            return cached
        calculator = _ViewGeometryCalculator()
        calculator._mesh_cache_owner = model
        DetailingViewPreview.set_view(
            calculator, model, plane, coordinate, **settings
        )
        segments = tuple(calculator._segments_2d)
        if segments:
            self._dxf_cache[cache_key] = segments
            self._dxf_cache.move_to_end(cache_key)
            while len(self._dxf_cache) > self._dxf_cache_limit:
                self._dxf_cache.popitem(last=False)
        return segments

    def _clear_view(self) -> None:
        self._plotter.clear()
        self._plotter.set_background("white")
        if self.isVisible():
            self._plotter.render()
        self._render_pending = False

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                self._drag_position = event.position()
                self._plotter.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
        elif event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            if self._drag_position is not None:
                position = event.position()
                delta = position - self._drag_position
                self._drag_position = position
                camera = self._plotter.camera
                view_direction = np.asarray(camera.direction, dtype=float)
                view_up = np.asarray(camera.up, dtype=float)
                right = np.cross(view_direction, view_up)
                right /= max(float(np.linalg.norm(right)), 1e-12)
                pixels_to_model = 2.0 * camera.parallel_scale / max(self._plotter.height(), 1)
                shift = (
                    -right * delta.x() + view_up * delta.y()
                ) * pixels_to_model
                camera.position = np.asarray(camera.position) + shift
                camera.focal_point = np.asarray(camera.focal_point) + shift
                self._plotter.render()
                return True
        elif event.type() == QEvent.Type.MouseButtonRelease and isinstance(event, QMouseEvent):
            if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
                self._drag_position = None
                self._plotter.setCursor(Qt.CursorShape.ArrowCursor)
                return True
        elif event.type() == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            steps = event.angleDelta().y() / 120.0
            camera = self._plotter.camera
            old_scale = camera.parallel_scale
            camera.parallel_scale = min(
                1e6, max(1e-6, old_scale / (1.15**steps))
            )
            new_scale = camera.parallel_scale
            self._zoom_factor = new_scale / max(self._fit_parallel_scale, 1e-12)
            position = event.position()
            offset_x = position.x() - self._plotter.width() / 2.0
            offset_y = position.y() - self._plotter.height() / 2.0
            view_direction = np.asarray(camera.direction, dtype=float)
            view_up = np.asarray(camera.up, dtype=float)
            right = np.cross(view_direction, view_up)
            right /= max(float(np.linalg.norm(right)), 1e-12)
            scale_delta = 2.0 * (old_scale - new_scale) / max(self._plotter.height(), 1)
            shift = (right * offset_x - view_up * offset_y) * scale_delta
            camera.position = np.asarray(camera.position) + shift
            camera.focal_point = np.asarray(camera.focal_point) + shift
            self._plotter.render()
            return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_spans is None:
            return
        aspect = max(self._plotter.width(), 1) / max(self._plotter.height(), 1)
        span_x, span_y = self._fit_spans
        self._fit_parallel_scale = max(span_y * 0.56, span_x / aspect * 0.56)
        self._plotter.camera.parallel_scale = self._fit_parallel_scale * self._zoom_factor
        self._plotter.render()

    def closeEvent(self, event) -> None:
        self._plotter.close()
        super().closeEvent(event)
