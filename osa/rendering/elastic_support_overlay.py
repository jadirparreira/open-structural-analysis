"""Indicadores 2D de molas rotacionais nos apoios dos nós."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from .batched_renderer import has_semirigid_member_end
from .label_overlay import project_world_to_screen
from .local_axes_renderer import LocalAxesRenderer


class ElasticSupportOverlay(QWidget):
    """Desenha o ícone de mola sobre nós com apoio rotacional elástico ativo."""

    ICON_SIZE = 24

    def __init__(self, plotter_widget: QWidget) -> None:
        super().__init__(plotter_widget)
        icon_path = Path(__file__).parents[1] / "resources" / "icons" / "elastic-support.svg"
        self._renderer = QSvgRenderer(str(icon_path), self)
        self._positions = np.empty((0, 3), dtype=float)
        self._screen = np.empty((0, 2), dtype=float)
        self._on_screen = np.empty(0, dtype=bool)
        self._visible = True
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.resize_to_parent()
        self.show()
        self.raise_()

    def set_members(self, members, nodes, radius: float) -> None:
        node_map = {node.name: node for node in nodes}
        positions = [
            position
            for member in members
            for position in self._member_end_positions(member, node_map, radius)
        ]
        self._positions = np.asarray(positions, dtype=float).reshape((-1, 3))
        self._screen = np.empty((len(positions), 2), dtype=float)
        self._on_screen = np.zeros(len(positions), dtype=bool)
        self.update()

    @staticmethod
    def _member_end_positions(member, nodes, radius: float) -> list[np.ndarray]:
        start = nodes.get(member.start_node)
        end = nodes.get(member.end_node)
        if start is None or end is None:
            return []
        basis = LocalAxesRenderer.basis(start, end, rotation=member.rotation)
        if basis is None:
            return []
        local_x = basis[0]
        positions = []
        if has_semirigid_member_end(member, "start"):
            positions.append(np.asarray((start.x, start.y, start.z), dtype=float) + local_x * radius * 4.0)
        if has_semirigid_member_end(member, "end"):
            positions.append(np.asarray((end.x, end.y, end.z), dtype=float) - local_x * radius * 4.0)
        return positions

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self.update()

    def resize_to_parent(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()

    def sync(self, renderer) -> None:
        camera = renderer.GetActiveCamera()
        aspect = renderer.GetTiledAspectRatio()
        vtk_matrix = camera.GetCompositeProjectionTransformMatrix(aspect, -1.0, 1.0)
        matrix = np.asarray([
            [vtk_matrix.GetElement(row, column) for column in range(4)]
            for row in range(4)
        ])
        self._screen, self._on_screen = project_world_to_screen(
            self._positions, matrix, self.width(), self.height(),
        )
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if not self._visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        half_size = self.ICON_SIZE / 2.0
        for point, visible in zip(self._screen, self._on_screen):
            if visible:
                self._renderer.render(
                    painter,
                    QRectF(point[0] - half_size, point[1] - half_size, self.ICON_SIZE, self.ICON_SIZE),
                )
        painter.end()
