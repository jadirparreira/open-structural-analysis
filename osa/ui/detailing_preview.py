"""2D vector drawings projected from bounded solid-model views."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QFrame

from osa.rendering.detailing_2d import visible_segments_from_meshes
from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.solid_member_renderer import SolidMemberRenderer
from osa.sections import section_shape


class DetailingViewPreview(QFrame):
    """Paint a 2D vector drawing of the visible solid edges in a view."""

    _plane_data: ClassVar[dict] = {
        "XY": ((0.0, 0.0, 1.0), 2, (0.0, 1.0, 0.0)),
        "XZ": ((0.0, 1.0, 0.0), 1, (0.0, 0.0, 1.0)),
        "YZ": ((1.0, 0.0, 0.0), 0, (0.0, 0.0, 1.0)),
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
        self._segments_2d: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._bounds_2d: tuple[float, float, float, float] | None = None
        self._zoom = 1.0
        self._pan = QPointF()
        self._drag_position: QPointF | None = None
        self.setMouseTracking(True)

    @property
    def segments_2d(self) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
        """Visible vector linework in model units, suitable for a DXF writer."""
        return tuple(self._segments_2d)

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
            normal_axis = 2
            view_up = (0.0, 1.0, 0.0)
            coordinate_value = 0.0
        else:
            normal, normal_axis, view_up = plane_data
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

        try:
            self._render_visible_lines(
                clipped_meshes,
                normal,
                view_up,
                orientation,
                float(rotation_degrees),
            )
        except (IndexError, RuntimeError, TypeError, ValueError):
            self._clear_preview()

    def _clear_preview(self) -> None:
        self._segments_2d.clear()
        self._bounds_2d = None
        self._zoom = 1.0
        self._pan = QPointF()
        self.update()

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
        normal: tuple[float, float, float],
        view_up: tuple[float, float, float],
        orientation: str,
        rotation_degrees: float,
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
            painter.end()
            return
        painter.setPen(QPen(QColor("#24292f"), 1.0))
        for start, end in self._segments_2d:
            painter.drawLine(self._to_screen(start), self._to_screen(end))
        painter.end()

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
