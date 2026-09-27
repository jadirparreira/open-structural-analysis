"""Fast Qt overlay for structural identifiers.

VTK's label-placement pipeline is useful for collision-aware annotations, but
it becomes the dominant frame cost when hundreds of always-visible identifiers
move with the camera.  This overlay keeps text out of the 3D pipeline, caches
glyph layout with ``QStaticText`` and projects all positions in one NumPy pass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QStaticText, QTransform
from PySide6.QtWidgets import QWidget


def project_world_to_screen(
    positions: np.ndarray,
    matrix: np.ndarray,
    width: int,
    height: int,
    *,
    clip_to_viewport: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Project 3D points to Qt coordinates with a vectorized clip transform.

    With ``clip_to_viewport=False``, points outside the left/right/top/bottom
    bounds remain valid as long as they are inside the camera's depth range.
    This is useful for line segments that cross the viewport while both of
    their endpoints are off-screen.
    """
    if not len(positions):
        return np.empty((0, 2), dtype=float), np.empty(0, dtype=bool)
    homogeneous = np.column_stack((np.asarray(positions, dtype=float), np.ones(len(positions))))
    clip = homogeneous @ np.asarray(matrix, dtype=float).T
    w = clip[:, 3]
    valid_w = w > 1e-12
    safe_w = np.where(valid_w, w, 1.0)
    normalized = clip[:, :3] / safe_w[:, None]
    visible = valid_w & (np.abs(normalized[:, 2]) <= 1.0)
    if clip_to_viewport:
        visible &= np.all(np.abs(normalized[:, :2]) <= 1.0, axis=1)
    screen = np.empty((len(positions), 2), dtype=float)
    screen[:, 0] = (normalized[:, 0] + 1.0) * float(width) / 2.0
    screen[:, 1] = (1.0 - normalized[:, 1]) * float(height) / 2.0
    return screen, visible


@dataclass(slots=True)
class _LabelGroup:
    positions: np.ndarray
    labels: tuple[QStaticText, ...]
    sizes: tuple[object, ...]
    screen: np.ndarray
    on_screen: np.ndarray
    draw_indices: np.ndarray
    visible: bool
    deduplicate: bool


class LabelOverlay(QWidget):
    """One transparent widget for every node and member identifier."""

    def __init__(self, plotter_widget: QWidget) -> None:
        super().__init__(plotter_widget)
        self.plotter_widget = plotter_widget
        self._groups: dict[str, _LabelGroup] = {}
        self._font = QFont()
        self._font.setPixelSize(11)
        self._font.setBold(True)
        self._color = QColor("#24292f")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.resize_to_parent()
        self.show()
        self.raise_()

    def set_group(
        self,
        kind: str,
        positions: np.ndarray,
        labels: tuple[str, ...],
        *,
        visible: bool,
        deduplicate: bool = False,
    ) -> None:
        static_labels = []
        for label in labels:
            text = QStaticText(label)
            text.prepare(QTransform(), self._font)
            static_labels.append(text)
        count = len(labels)
        self._groups[kind] = _LabelGroup(
            positions=np.asarray(positions, dtype=float),
            labels=tuple(static_labels),
            sizes=tuple(text.size() for text in static_labels),
            screen=np.empty((count, 2), dtype=float),
            on_screen=np.zeros(count, dtype=bool),
            draw_indices=np.arange(count, dtype=np.int64),
            visible=bool(visible),
            deduplicate=bool(deduplicate),
        )

    def clear(self) -> None:
        self._groups.clear()
        self.update()

    def set_group_visible(self, kind: str, visible: bool) -> None:
        group = self._groups.get(kind)
        if group is not None:
            group.visible = bool(visible)
        self.update()

    def resize_to_parent(self) -> None:
        self.setGeometry(self.plotter_widget.rect())
        self.raise_()

    def sync(self, renderer) -> None:
        camera = renderer.GetActiveCamera()
        aspect = renderer.GetTiledAspectRatio()
        vtk_matrix = camera.GetCompositeProjectionTransformMatrix(aspect, -1.0, 1.0)
        matrix = np.asarray([
            [vtk_matrix.GetElement(row, column) for column in range(4)]
            for row in range(4)
        ])
        for group in self._groups.values():
            group.screen, group.on_screen = project_world_to_screen(
                group.positions, matrix, self.width(), self.height(),
            )
            group.draw_indices = self._visible_indices(group)
        self.raise_()
        self.update()

    @staticmethod
    def _visible_indices(group: _LabelGroup) -> np.ndarray:
        """Cull only crowded action/result labels in screen space.

        Structural identifiers keep their previous behavior.  Auxiliary
        labels are culled only after the overlay becomes dense, preserving the
        most useful labels while preventing a quadratic-looking paint cost and
        unreadable text clouds.
        """
        indices = np.flatnonzero(group.on_screen)
        if not group.deduplicate or len(indices) <= 160:
            return indices
        occupied: set[tuple[int, int]] = set()
        selected: list[int] = []
        for index in indices:
            point = group.screen[index]
            size = group.sizes[index]
            left = int((point[0] - size.width() / 2.0) // 28)
            right = int((point[0] + size.width() / 2.0) // 28)
            top = int((point[1] - size.height() / 2.0) // 18)
            bottom = int((point[1] + size.height() / 2.0) // 18)
            cells = {
                (column, row)
                for column in range(left, right + 1)
                for row in range(top, bottom + 1)
            }
            if cells & occupied:
                continue
            occupied.update(cells)
            selected.append(int(index))
        return np.asarray(selected, dtype=np.int64)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setFont(self._font)
        painter.setPen(self._color)
        for group in self._groups.values():
            if not group.visible:
                continue
            for index in group.draw_indices:
                text = group.labels[index]
                point = group.screen[index]
                size = group.sizes[index]
                painter.drawStaticText(
                    QPointF(point[0] - size.width() / 2.0, point[1] - size.height() / 2.0),
                    text,
                )
        painter.end()
