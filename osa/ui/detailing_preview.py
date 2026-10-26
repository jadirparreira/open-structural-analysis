"""2D vector drawings projected from bounded solid-model views."""

from __future__ import annotations

from collections import OrderedDict
from time import sleep
from typing import ClassVar
from weakref import WeakKeyDictionary

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame

from osa.rendering.detailing_2d import visible_segments_from_meshes
from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.solid_member_renderer import SolidMemberRenderer, deform_extruded_points
from osa.sections import section_shape


class DetailingViewPreview(QFrame):
    """Paint a 2D vector drawing of the visible solid edges in a view."""

    view_ready = Signal(bool)

    _shared_model_meshes: ClassVar[WeakKeyDictionary] = WeakKeyDictionary()
    _view_cache_limit: ClassVar[int] = 24

    _plane_data: ClassVar[dict] = {
        "XY": ((0.0, 0.0, 1.0), 2, (0.0, 1.0, 0.0)),
        "XZ": ((0.0, 1.0, 0.0), 1, (0.0, 0.0, 1.0)),
        "YZ": ((1.0, 0.0, 0.0), 0, (0.0, 0.0, 1.0)),
    }
    _isometric_directions: ClassVar[dict[str, tuple[float, float, float]]] = {
        "ISO-SE": (1.0, -1.0, 1.0),
        "ISO-NE": (1.0, 1.0, 1.0),
        "ISO-NW": (-1.0, 1.0, 1.0),
        "ISO-SW": (-1.0, -1.0, 1.0),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("detailingViewPreview")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#detailingViewPreview { background: #ffffff; "
            "border: 1px solid #d0d7de; border-radius: 6px; }"
        )
        self._renderer = SolidMemberRenderer()
        self._model_cache_key = None
        self._solid_meshes: list[pv.PolyData] = []
        self._solid_shapes = []
        self._solid_transforms: list[np.ndarray] = []
        self._solid_face_angles: list[tuple[float, ...]] = []
        self._solid_edge_meshes: list[pv.PolyData] | None = None
        self._view_cache: OrderedDict[tuple, tuple] = OrderedDict()
        self._segments_2d: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._line_path = QPainterPath()
        self._bounds_2d: tuple[float, float, float, float] | None = None
        self._zoom = 1.0
        self._pan = QPointF()
        self._drag_position: QPointF | None = None
        self._render_generation = 0
        self._render_pending = False
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._render_signals = _ViewRenderSignals(self)
        self._render_signals.finished.connect(self._accept_render_result)
        self.setMouseTracking(True)

    @property
    def segments_2d(self) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
        """Visible vector linework in model units, suitable for a DXF writer."""
        return (
            self._segments_2d
            if isinstance(self._segments_2d, tuple)
            else tuple(self._segments_2d)
        )

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
        isometric = plane in self._isometric_directions
        if model is None or (plane != "custom" and plane_data is None and not isometric):
            self._clear_preview()
            return

        coordinate_key = (
            tuple(tuple(float(value) for value in point) for point in coordinate)
            if plane == "custom"
            else float(coordinate)
        )
        cache_key = (
            id(model),
            getattr(model, "revision", None),
            plane,
            coordinate_key,
            float(upper_offset_cm),
            float(lower_offset_cm),
            orientation,
            float(rotation_degrees),
        )
        cached = self._view_cache.get(cache_key)
        if cached is not None:
            self._view_cache.move_to_end(cache_key)
            segments, self._bounds_2d, self._line_path = cached
            self._segments_2d = segments
            self._zoom = 1.0
            self._pan = QPointF()
            self.update()
            return

        self._ensure_model_meshes(model)
        feature_edge_meshes = None
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
            normal_axis = 2
            view_up = (0.0, 1.0, 0.0)
            coordinate_value = 0.0
        elif isometric:
            self._ensure_model_edge_meshes(model)
            feature_edge_meshes = self._solid_edge_meshes
            normal_array = np.asarray(self._isometric_directions[plane], dtype=float)
            normal_array /= np.linalg.norm(normal_array)
            view_up_array = np.asarray((0.0, 0.0, 1.0), dtype=float)
            view_up_array -= np.dot(view_up_array, normal_array) * normal_array
            view_up_array /= np.linalg.norm(view_up_array)
            normal = tuple(float(value) for value in normal_array)
            view_up = tuple(float(value) for value in view_up_array)
            solid_meshes = self._solid_meshes
            coordinate_value = 0.0
        else:
            normal, normal_axis, view_up = plane_data
            solid_meshes = self._solid_meshes
            coordinate_value = float(coordinate)
        upper = coordinate_value + max(0.0, float(upper_offset_cm)) / 100.0
        lower = coordinate_value - max(0.0, float(lower_offset_cm)) / 100.0
        if upper < lower:
            upper, lower = lower, upper

        if isometric:
            clipped_meshes = list(solid_meshes)
        else:
            clipped_meshes: list[pv.PolyData] = []
            for solid_number, solid in enumerate(solid_meshes):
                if solid_number % 16 == 0:
                    sleep(0)
                clipped = self._clip_to_depth_range(
                    solid, normal, normal_axis, lower, upper
                )
                if clipped is not None and clipped.n_points and clipped.n_cells:
                    clipped_meshes.append(clipped)

        if not clipped_meshes:
            self._clear_preview()
            return

        if len(clipped_meshes) > 1:
            append = vtk.vtkAppendPolyData()
            for clipped in clipped_meshes:
                append.AddInputData(clipped)
            append.Update()
            combined = pv.wrap(append.GetOutput()).copy(deep=True)
            clipped_meshes = [combined] if combined.n_points and combined.n_cells else []
        if not clipped_meshes:
            self._clear_preview()
            return

        try:
            self._render_visible_lines(
                clipped_meshes,
                normal,
                view_up,
                "Superior para inferior" if isometric else orientation,
                float(rotation_degrees),
                feature_edge_meshes,
            )
        except (IndexError, RuntimeError, TypeError, ValueError):
            self._clear_preview()
            return
        self._view_cache[cache_key] = (
            tuple(self._segments_2d), self._bounds_2d, self._line_path
        )
        self._view_cache.move_to_end(cache_key)
        while len(self._view_cache) > self._view_cache_limit:
            self._view_cache.popitem(last=False)

    def request_view(self, model, plane: str, coordinate, **settings) -> None:
        """Queue view generation so navigation and dialog painting stay responsive."""
        self._render_generation += 1
        generation = self._render_generation
        if model is None:
            self._segments_2d = []
            self._bounds_2d = None
            self._render_pending = False
            self.view_ready.emit(False)
            self.update()
            return
        self._render_pending = True
        coordinate_key = (
            tuple(tuple(float(value) for value in point) for point in coordinate)
            if plane == "custom"
            else float(coordinate)
        )
        cache_key = (
            id(model),
            getattr(model, "revision", None),
            plane,
            coordinate_key,
            float(settings.get("upper_offset_cm", 50.0)),
            float(settings.get("lower_offset_cm", 50.0)),
            settings.get("orientation", "Superior para inferior"),
            float(settings.get("rotation_degrees", 0.0)),
        )
        cached = self._view_cache.get(cache_key)
        if cached is not None:
            self._view_cache.move_to_end(cache_key)
            segments, self._bounds_2d, self._line_path = cached
            self._segments_2d = segments
            self._render_pending = False
            self._zoom = 1.0
            self._pan = QPointF()
            self.view_ready.emit(bool(segments))
            self.update()
            return

        self._clear_preview()
        self.view_ready.emit(False)
        self._render_pool.clear()
        model_snapshot = _ModelSnapshot(model)
        self._render_pool.start(
            _ViewRenderTask(
                self._render_signals,
                generation,
                cache_key,
                model_snapshot,
                model,
                plane,
                coordinate,
                settings,
            )
        )

    @Slot(int, object, object, object, object)
    def _accept_render_result(
        self, generation, cache_key, segments, bounds, line_path
    ) -> None:
        if generation != self._render_generation:
            return
        self._render_pending = False
        self._segments_2d = segments
        self._bounds_2d = bounds
        self._line_path = line_path
        self._zoom = 1.0
        self._pan = QPointF()
        self._view_cache[cache_key] = (self.segments_2d, self._bounds_2d, self._line_path)
        self._view_cache.move_to_end(cache_key)
        while len(self._view_cache) > self._view_cache_limit:
            self._view_cache.popitem(last=False)
        self.view_ready.emit(bool(self._segments_2d))
        self.update()

    def _clear_preview(self) -> None:
        self._segments_2d = []
        self._line_path = QPainterPath()
        self._bounds_2d = None
        self._zoom = 1.0
        self._pan = QPointF()
        if hasattr(self, "_line_path"):
            self._update_line_path()
        self.update()

    def _update_line_path(self) -> None:
        path = QPainterPath()
        for start, end in self._segments_2d:
            path.moveTo(start[0], start[1])
            path.lineTo(end[0], end[1])
        self._line_path = path

    def _ensure_model_meshes(self, model) -> None:
        cache_owner = getattr(self, "_mesh_cache_owner", model)
        cache_key = (id(cache_owner), getattr(model, "revision", None))
        if cache_key == self._model_cache_key:
            return
        shared = self._shared_model_meshes.get(cache_owner)
        if shared is not None and shared[0] == cache_key[1]:
            self._solid_meshes = shared[1]
            self._solid_shapes = shared[2]
            self._solid_transforms = shared[3]
            self._solid_face_angles = shared[4]
            self._solid_edge_meshes = None
            self._model_cache_key = cache_key
            return

        meshes: list[pv.PolyData] = []
        shapes = []
        transforms: list[np.ndarray] = []
        face_angles: list[tuple[float, ...]] = []
        for member_number, member in enumerate(model.bars.values()):
            if member_number % 16 == 0:
                sleep(0)
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
                angles = getattr(member, "solid_face_angles", (0.0, 0.0, 0.0, 0.0))
                mesh.points = deform_extruded_points(mesh.points, length, angles)
                mesh.transform(transform, inplace=True)
                meshes.append(mesh)
                shapes.append(shape)
                transforms.append(transform)
                face_angles.append(tuple(angles))
            except (KeyError, TypeError, ValueError, RuntimeError):
                continue

        self._solid_meshes = meshes
        self._solid_shapes = shapes
        self._solid_transforms = transforms
        self._solid_face_angles = face_angles
        self._solid_edge_meshes = None
        self._model_cache_key = cache_key
        self._shared_model_meshes[cache_owner] = (
            cache_key[1], meshes, shapes, transforms, face_angles
        )

    def _ensure_model_edge_meshes(self, model) -> None:
        if self._solid_edge_meshes is not None:
            return
        self._ensure_model_meshes(model)
        edge_meshes: list[pv.PolyData] = []
        for shape, transform, angles in zip(
            self._solid_shapes, self._solid_transforms, self._solid_face_angles,
        ):
            edge_mesh = self._renderer._edge_mesh_for(shape).copy(deep=True)
            edge_mesh.points = deform_extruded_points(
                edge_mesh.points, float(np.linalg.norm(transform[:3, 0])), angles,
            )
            edge_mesh.transform(transform, inplace=True)
            edge_meshes.append(edge_mesh)
        self._solid_edge_meshes = edge_meshes

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
        normal: tuple[float, float, float],
        view_up: tuple[float, float, float],
        orientation: str,
        rotation_degrees: float,
        feature_edge_meshes: list[pv.PolyData] | None = None,
    ) -> None:
        """Resolve solid-face occlusion, then retain only the 2D vector lines."""
        camera_direction = np.asarray(normal, dtype=float)
        if orientation == "Inferior para superior":
            camera_direction = -camera_direction
        self._segments_2d = visible_segments_from_meshes(
            meshes,
            camera_direction,
            view_up,
            rotation_degrees,
            feature_edge_meshes=feature_edge_meshes,
        )
        if self._segments_2d:
            points_2d = np.asarray(
                [point for segment in self._segments_2d for point in segment],
                dtype=float,
            )
            self._bounds_2d = (
                float(points_2d[:, 0].min()),
                float(points_2d[:, 0].max()),
                float(points_2d[:, 1].min()),
                float(points_2d[:, 1].max()),
            )
        else:
            self._bounds_2d = None
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.contentsRect(), QColor("#ffffff"))
        if self._bounds_2d is None:
            if self._render_pending:
                painter.setPen(QPen(QColor("#57606a"), 1.0))
                painter.drawText(
                    self.contentsRect().adjusted(12, 8, -12, -8),
                    Qt.AlignmentFlag.AlignCenter,
                    "Gerando vista…",
                )
            painter.end()
            return
        if self._segments_2d and self._line_path.isEmpty():
            self._update_line_path()
        line_pen = QPen(QColor("#24292f"), 1.0)
        line_pen.setCosmetic(True)
        painter.setPen(line_pen)
        painter.setTransform(self._drawing_transform())
        painter.drawPath(self._line_path)
        painter.resetTransform()
        painter.end()

    def _drawing_transform(self) -> QTransform:
        center_x, center_y = self._drawing_center()
        rect = self.contentsRect()
        scale = self._fit_scale() * self._zoom
        return QTransform(
            scale,
            0.0,
            0.0,
            0.0,
            -scale,
            0.0,
            rect.center().x() + self._pan.x() - center_x * scale,
            rect.center().y() + self._pan.y() + center_y * scale,
            1.0,
        )

    def _fit_scale(self) -> float:
        if self._bounds_2d is None:
            return 1.0
        min_x, max_x, min_y, max_y = self._bounds_2d
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        rect = self.contentsRect().adjusted(24, 24, -24, -24)
        return min(max(rect.width(), 1) / span_x, max(rect.height(), 1) / span_y)

    def _drawing_center(self) -> tuple[float, float]:
        if self._bounds_2d is None:
            return 0.0, 0.0
        min_x, max_x, min_y, max_y = self._bounds_2d
        return (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

    def _to_screen(self, point: tuple[float, float]) -> QPointF:
        center_x, center_y = self._drawing_center()
        rect = self.contentsRect()
        scale = self._fit_scale() * self._zoom
        return QPointF(
            rect.center().x() + self._pan.x() + (point[0] - center_x) * scale,
            rect.center().y() + self._pan.y() - (point[1] - center_y) * scale,
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._bounds_2d is None:
            event.ignore()
            return
        cursor = event.position()
        old_scale = self._fit_scale() * self._zoom
        center_x, center_y = self._drawing_center()
        rect_center = self.contentsRect().center()
        world_x = center_x + (cursor.x() - rect_center.x() - self._pan.x()) / old_scale
        world_y = center_y - (cursor.y() - rect_center.y() - self._pan.y()) / old_scale
        steps = event.angleDelta().y() / 120.0
        self._zoom = min(100.0, max(0.05, self._zoom * (1.15**steps)))
        new_scale = self._fit_scale() * self._zoom
        self._pan = QPointF(
            cursor.x() - rect_center.x() - (world_x - center_x) * new_scale,
            cursor.y() - rect_center.y() + (world_y - center_y) * new_scale,
        )
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._drag_position = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_position is not None:
            position = event.position()
            self._pan += position - self._drag_position
            self._drag_position = position
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._drag_position = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._bounds_2d is not None:
            self._zoom = 1.0
            self._pan = QPointF()
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ViewRenderSignals(QObject):
    finished = Signal(int, object, object, object, object)


class _ModelSnapshot:
    def __init__(self, model) -> None:
        self.revision = getattr(model, "revision", None)
        self.nodes = dict(model.nodes)
        self.bars = dict(model.bars)


class _ViewGeometryCalculator:
    """Non-widget receiver for the existing projection pipeline in a worker."""

    _plane_data = DetailingViewPreview._plane_data
    _isometric_directions = DetailingViewPreview._isometric_directions
    _shared_model_meshes = DetailingViewPreview._shared_model_meshes
    _view_cache_limit = DetailingViewPreview._view_cache_limit
    _ensure_model_meshes = DetailingViewPreview._ensure_model_meshes
    _ensure_model_edge_meshes = DetailingViewPreview._ensure_model_edge_meshes
    _clip_to_depth_range = staticmethod(DetailingViewPreview._clip_to_depth_range)
    _render_visible_lines = DetailingViewPreview._render_visible_lines
    _clear_preview = DetailingViewPreview._clear_preview
    _update_line_path = DetailingViewPreview._update_line_path

    def __init__(self) -> None:
        self._renderer = SolidMemberRenderer()
        self._model_cache_key = None
        self._solid_meshes = []
        self._solid_shapes = []
        self._solid_transforms = []
        self._solid_face_angles = []
        self._solid_edge_meshes = None
        self._segments_2d = []
        self._bounds_2d = None
        self._line_path = QPainterPath()
        self._view_cache = OrderedDict()
        self._zoom = 1.0
        self._pan = QPointF()

    def update(self) -> None:
        pass


class _ViewRenderTask(QRunnable):
    def __init__(
        self, signals, generation, cache_key, model, cache_owner, plane, coordinate, settings
    ) -> None:
        super().__init__()
        self.signals = signals
        self.generation = generation
        self.cache_key = cache_key
        self.model = model
        self.cache_owner = cache_owner
        self.plane = plane
        self.coordinate = coordinate
        self.settings = settings

    def run(self) -> None:
        calculator = _ViewGeometryCalculator()
        calculator._mesh_cache_owner = self.cache_owner
        try:
            DetailingViewPreview.set_view(
                calculator,
                self.model,
                self.plane,
                self.coordinate,
                **self.settings,
            )
            segments = tuple(calculator._segments_2d)
            bounds = calculator._bounds_2d
        except (IndexError, KeyError, OverflowError, RuntimeError, TypeError, ValueError):
            segments, bounds = (), None
        line_path = QPainterPath()
        for segment_number, (start, end) in enumerate(segments):
            if segment_number % 256 == 0:
                sleep(0)
            line_path.moveTo(start[0], start[1])
            line_path.lineTo(end[0], end[1])
        self.signals.finished.emit(
            self.generation, self.cache_key, segments, bounds, line_path
        )
