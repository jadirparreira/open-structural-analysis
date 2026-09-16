"""Interactive PyVista scene used by the desktop user interface."""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from osa.model import StructuralModel

from .grid_renderer import GridRenderer
from .member_renderer import MemberRenderer
from .navigation_widget import NavigationWidget
from .node_renderer import NodeRenderer


class StructureScene(QWidget):
    element_clicked = Signal(str, str, object)
    empty_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter)
        self.plotter.set_background("#ffffff")
        self.plotter.enable_parallel_projection()
        self._grid_renderer = GridRenderer()
        self._node_renderer = NodeRenderer()
        self._member_renderer = MemberRenderer()
        self._orientation_widget = self._create_orientation_widget()
        self._model = StructuralModel()
        self._actors: dict[str, tuple[str, str, object]] = {}
        self._label_actors: dict[str, list[object]] = {"node": [], "bar": []}
        self._local_axis_actors: list[object] = []
        self._local_axes_visible = True
        self._labels_visibility = {"node": True, "bar": True}
        self._hovered: str | None = None
        self._selected: tuple[str, str] | None = None
        self._marker_radius_current = 0.025
        self._marker_radius_locked = False
        self._picker = vtk.vtkCellPicker()
        self._picker.SetTolerance(0.01)
        self.plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_click)

    def render_model(self, model: StructuralModel) -> None:
        self._model = model
        self._actors.clear()
        self._label_actors = {"node": [], "bar": []}
        self._local_axis_actors.clear()
        self._hovered = None
        self.plotter.clear()
        self.plotter.set_background("#ffffff")
        self._orientation_widget.SetEnabled(1)
        self._grid_renderer.render(self.plotter)
        if not model.nodes:
            self._marker_radius_locked = False
            self.plotter.render()
            return

        positions = np.array([[node.x, node.y, node.z] for node in model.nodes.values()])
        if self._marker_radius_locked:
            radius = self._marker_radius_current
        else:
            radius = self._marker_radius(positions)
            self._marker_radius_locked = True
        self._marker_radius_current = radius
        for node in model.nodes.values():
            label_actor = self._node_renderer.render(
                self.plotter, node, radius, self._register_actor, self._labels_visibility["node"]
            )
            self._label_actors["node"].append(label_actor)

        for bar in model.bars.values():
            start, end = model.nodes[bar.start_node], model.nodes[bar.end_node]
            label_actor, axes = self._member_renderer.render(
                self.plotter, bar, start, end, radius, self._register_actor,
                self._labels_visibility["bar"], self._local_axes_visible,
            )
            self._label_actors["bar"].append(label_actor)
            self._local_axis_actors.extend(axes)
        self.plotter.reset_camera()
        self.plotter.render()

    def _create_orientation_widget(self):
        widget = NavigationWidget.create(self.plotter)
        return widget

    def _lock_navigation_viewport(self, widget=None) -> None:
        widget = widget or self._orientation_widget
        if hasattr(widget, "SetViewport"):
            width, height = self.plotter.render_window.GetSize()
            if width and height:
                size = 100
                widget.SetViewport(0.006, 0.012, (size + 6) / width, (size + 6) / height)

    def element_center(self, kind: str, name: str) -> tuple[float, float, float]:
        if kind == "node":
            node = self._model.nodes[name]
            return node.x, node.y, node.z
        bar = self._model.bars[name]
        start, end = self._model.nodes[bar.start_node], self._model.nodes[bar.end_node]
        return ((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2)


    def _pick(self) -> tuple[str, str] | None:
        x, y = self.plotter.iren.get_event_position()
        self._picker.Pick(x, y, 0, self.plotter.renderer)
        actor = self._picker.GetActor()
        identifier = actor.GetObjectName() if actor else None
        if identifier not in self._actors:
            return None
        kind, name, _actor = self._actors[identifier]
        return kind, name

    def _on_mouse_move(self, *_args) -> None:
        picked = self._pick()
        identifier = f"{picked[0]}:{picked[1]}" if picked else None
        if identifier == self._hovered:
            return
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if self._hovered in self._actors and self._hovered != selected_identifier:
            self._set_color(self._hovered, False)
        self._hovered = identifier
        if identifier in self._actors:
            self._set_color(identifier, True)
        self.plotter.render()

    def _on_left_click(self, *_args) -> None:
        picked = self._pick()
        if picked:
            kind, name = picked
            previous_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
            self._selected = picked
            if previous_identifier and previous_identifier != f"{kind}:{name}":
                self._set_color(previous_identifier, False)
            self._set_color(f"{kind}:{name}", True)
            self.plotter.render()
            self.element_clicked.emit(kind, name, self.element_center(kind, name))
        else:
            if self._selected:
                self._set_color(f"{self._selected[0]}:{self._selected[1]}", False)
                self.plotter.render()
            self._selected = None
            self.empty_clicked.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_orientation_widget"):
            self._lock_navigation_viewport()




    def _set_color(self, identifier: str, hovered: bool) -> None:
        kind, name, actor = self._actors[identifier]
        if hovered:
            color = "#bf8700"
        elif kind == "node":
            color = self._node_base_color(name)
        else:
            color = "#24292f"
        actor.GetProperty().SetColor(*pv.Color(color).float_rgb)
        actor.GetProperty().SetLineWidth(7 if hovered and kind == "bar" else 4)

    def _node_base_color(self, name: str) -> str:
        supports = self._model.nodes[name].supports
        supported_patterns = {
            (False, False, False, False, False, False),
            (True, True, True, False, False, False),
            (True, True, True, True, True, True),
        }
        return "#0969da" if supports in supported_patterns else "#cf222e"

    def _register_actor(self, actor, kind: str, name: str) -> None:
        identifier = f"{kind}:{name}"
        actor.SetObjectName(identifier)
        actor.SetPickable(True)
        self._actors[identifier] = kind, name, actor

    def set_labels_visible(self, kind: str, visible: bool) -> None:
        self._labels_visibility[kind] = visible
        for actor in self._label_actors.get(kind, []):
            actor.SetVisibility(visible)
        self.plotter.render()

    def set_local_axes_visible(self, visible: bool) -> None:
        self._local_axes_visible = visible
        for actor in self._local_axis_actors:
            actor.SetVisibility(visible)
        self.plotter.render()


    @staticmethod
    def _address(actor) -> str:
        return actor.GetAddressAsString("")

    @staticmethod
    def _marker_radius(positions: np.ndarray) -> float:
        # Keep node/support symbols visually consistent regardless of model size.
        return 0.05
