"""Fast Qt overlay for structural identifiers.

VTK's label-placement pipeline is useful for collision-aware annotations, but
it becomes the dominant frame cost when hundreds of always-visible identifiers
move with the camera.  This overlay keeps text out of the 3D pipeline, caches
glyph layout with ``QStaticText`` and projects all positions in one NumPy pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QStaticText, QTransform
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
    text: tuple[str, ...]
    labels: tuple[QStaticText, ...]
    sizes: tuple[object, ...]
    atlases: tuple[QPixmap, ...]
    atlas_rects: tuple[tuple[int, QRectF], ...]
    atlas_ratio: float
    screen: np.ndarray
    on_screen: np.ndarray
    draw_indices: np.ndarray
    visible: bool
    deduplicate: bool


class LabelOverlay(QWidget):
    """One transparent widget for every node and member identifier."""

    _atlas_width = 2048
    _atlas_height = 2048

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
        for _ in self.set_group_steps(kind, positions, labels, visible=visible, deduplicate=deduplicate):
            pass

    def set_group_steps(
        self,
        kind: str,
        positions: np.ndarray,
        labels: tuple[str, ...],
        *,
        visible: bool,
        deduplicate: bool = False,
    ):
        """Prepare label glyphs in bounded GUI tasks while opening a project."""
        labels = tuple(labels)
        previous = self._groups.get(kind)
        if previous is not None and previous.text == labels:
            # Geometry changes frequently while identifiers rarely change.
            # Preserve prepared glyphs and their atlas across those edits.
            previous.positions = np.asarray(positions, dtype=float)
            previous.visible = bool(visible)
            previous.deduplicate = bool(deduplicate)
            return
        static_labels = []
        sizes = []
        for index, label in enumerate(labels):
            text = QStaticText(label)
            text.prepare(QTransform(), self._font)
            static_labels.append(text)
            sizes.append(text.size())
            if index % 128 == 127:
                yield
        sizes = tuple(sizes)
        atlases, atlas_rects, atlas_ratio = yield from self._build_atlas_steps(tuple(static_labels), sizes)
        count = len(labels)
        self._groups[kind] = _LabelGroup(
            positions=np.asarray(positions, dtype=float),
            text=labels,
            labels=tuple(static_labels),
            sizes=sizes,
            atlases=atlases,
            atlas_rects=atlas_rects,
            atlas_ratio=atlas_ratio,
            screen=np.empty((count, 2), dtype=float),
            on_screen=np.zeros(count, dtype=bool),
            draw_indices=np.arange(count, dtype=np.int64),
            visible=bool(visible),
            deduplicate=bool(deduplicate),
        )

    def _build_atlas(
        self, labels: tuple[QStaticText, ...], sizes: tuple[object, ...],
    ) -> tuple[tuple[QPixmap, ...], tuple[tuple[int, QRectF], ...], float]:
        steps = self._build_atlas_steps(labels, sizes)
        while True:
            try:
                next(steps)
            except StopIteration as completed:
                return completed.value

    def _build_atlas_steps(self, labels: tuple[QStaticText, ...], sizes: tuple[object, ...]):
        ratio = max(1.0, float(self.devicePixelRatioF()))
        if not labels:
            return (), (), ratio
        width = max(self._atlas_width, max(ceil(size.width()) + 2 for size in sizes))
        placements: list[tuple[int, QRectF]] = []
        pages: list[list[tuple[QStaticText, int, int]]] = [[]]
        x = y = row_height = 0
        for index, (text, size) in enumerate(zip(labels, sizes)):
            cell_width = ceil(size.width()) + 2
            cell_height = ceil(size.height()) + 2
            if x + cell_width > width:
                x = 0
                y += row_height
                row_height = 0
            if y + cell_height > self._atlas_height and pages[-1]:
                pages.append([])
                x = y = row_height = 0
            pages[-1].append((text, x, y))
            placements.append((len(pages) - 1, QRectF(x, y, cell_width, cell_height)))
            x += cell_width
            row_height = max(row_height, cell_height)
            if index % 256 == 255:
                yield

        atlases = []
        for page, entries in enumerate(pages):
            height = ceil(max(
                placement.y() + placement.height()
                for page_index, placement in placements if page_index == page
            ))
            atlas = QPixmap(ceil(width * ratio), ceil(height * ratio))
            atlas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(atlas)
            painter.scale(ratio, ratio)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(self._font)
            painter.setPen(self._color)
            for text, left, top in entries:
                painter.drawStaticText(QPointF(left + 1, top + 1), text)
            painter.end()
            atlases.append(atlas)
            yield
        physical_rects = tuple(
            (page, QRectF(
                rect.x() * ratio, rect.y() * ratio,
                rect.width() * ratio, rect.height() * ratio,
            )) for page, rect in placements
        )
        return tuple(atlases), physical_rects, ratio

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
        ratio = max(1.0, float(self.devicePixelRatioF()))
        for group in self._groups.values():
            if group.labels and abs(group.atlas_ratio - ratio) > 1e-6:
                group.atlases, group.atlas_rects, group.atlas_ratio = self._build_atlas(
                    group.labels, group.sizes,
                )
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
        for group in self._groups.values():
            if not group.visible:
                continue
            for index in group.draw_indices:
                point = group.screen[index]
                size = group.sizes[index]
                page, source = group.atlas_rects[index]
                painter.drawPixmap(
                    QRectF(
                        point[0] - size.width() / 2.0 - 1,
                        point[1] - size.height() / 2.0 - 1,
                        source.width() / group.atlas_ratio,
                        source.height() / group.atlas_ratio,
                    ),
                    group.atlases[page], source,
                )
        painter.end()
