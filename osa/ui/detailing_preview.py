"""Two-dimensional previews of solid-member intersections with global planes."""

from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame

from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.solid_member_renderer import SolidMemberRenderer
from osa.sections import section_shape


class DetailingViewPreview(QFrame):
    """Draw solid member cross-sections cut by a selected global plane."""

    _plane_data = {
        "XY": ((0.0, 0.0, 1.0), (0, 1)),
        "XZ": ((0.0, 1.0, 0.0), (0, 2)),
        "YZ": ((1.0, 0.0, 0.0), (1, 2)),
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
        self._contours: list[list[list[np.ndarray]]] = []
        self._bounds: tuple[float, float, float, float] | None = None

    def set_view(self, model, plane: str, coordinate: float) -> None:
        """Rebuild the preview for the given plane and model coordinate."""
        self._contours = []
        self._bounds = None
        plane_data = self._plane_data.get(plane)
        if model is None or plane_data is None:
            self.update()
            return

        normal, display_axes = plane_data
        origin = [0.0, 0.0, 0.0]
        normal_axis = {"XY": 2, "XZ": 1, "YZ": 0}[plane]
        origin[normal_axis] = float(coordinate)
        all_points: list[np.ndarray] = []

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
                solid = self._renderer._mesh_for(shape).copy(deep=True)
                solid.transform(transform, inplace=True)
                cut = solid.slice(normal=normal, origin=origin)
                member_contours = self._slice_contours(cut, display_axes)
                if member_contours:
                    self._contours.append(member_contours)
                    all_points.extend(point for contour in member_contours for point in contour)
            except (KeyError, TypeError, ValueError, RuntimeError):
                # An invalid or unsupported solid should not prevent other
                # members from appearing in the view preview.
                continue

        if all_points:
            points = np.asarray(all_points, dtype=float)
            self._bounds = (
                float(points[:, 0].min()), float(points[:, 0].max()),
                float(points[:, 1].min()), float(points[:, 1].max()),
            )
        self.update()

    @staticmethod
    def _slice_contours(mesh, display_axes: tuple[int, int]) -> list[list[np.ndarray]]:
        if mesh.n_points == 0 or mesh.n_lines == 0:
            return []
        points = np.asarray(mesh.points, dtype=float)
        cells = np.asarray(mesh.lines, dtype=np.int64)
        contours: list[list[np.ndarray]] = []
        offset = 0
        while offset < len(cells):
            count = int(cells[offset])
            indices = cells[offset + 1:offset + count + 1]
            offset += count + 1
            if count < 2:
                continue
            projected = [points[index, list(display_axes)] for index in indices]
            if np.linalg.norm(projected[0] - projected[-1]) > 1e-9:
                projected.append(projected[0])
            contours.append(projected)
        return contours

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._contours or self._bounds is None:
            return

        min_x, max_x, min_y, max_y = self._bounds
        width = max(max_x - min_x, 1e-6)
        height = max(max_y - min_y, 1e-6)
        margin = 24.0
        available_width = max(1.0, self.width() - 2 * margin)
        available_height = max(1.0, self.height() - 2 * margin)
        scale = min(available_width / width, available_height / height)
        draw_width, draw_height = width * scale, height * scale
        left = (self.width() - draw_width) / 2.0
        top = (self.height() - draw_height) / 2.0

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(Qt.GlobalColor.darkGray, 1.25))
            painter.setBrush(Qt.GlobalColor.lightGray)
            for member_contours in self._contours:
                path = QPainterPath()
                path.setFillRule(Qt.FillRule.OddEvenFill)
                for contour in member_contours:
                    first_x, first_y = contour[0]
                    path.moveTo(left + (first_x - min_x) * scale,
                                top + (max_y - first_y) * scale)
                    for x, y in contour[1:]:
                        path.lineTo(left + (x - min_x) * scale,
                                    top + (max_y - y) * scale)
                    path.closeSubpath()
                painter.drawPath(path)
        finally:
            painter.end()
