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
        self._node_label_actors: dict[str, object] = {}
        self._member_label_actors: dict[str, object] = {}
        self._local_axis_actors: list[object] = []
        self._local_axis_actors_by_member: dict[str, list[object]] = {}
        self._member_aura_actors: dict[str, object] = {}
        self._member_cap_actors: dict[str, list[object]] = {}
        self._member_aura_cap_actors: dict[str, list[object]] = {}
        self._member_release_actors: dict[str, list[object]] = {}
        self._node_aura_actors: dict[str, object] = {}
        self._node_support_actors: dict[str, object] = {}
        self._local_axes_visible = True
        self._labels_visibility = {"node": True, "bar": True}
        self._hovered: str | None = None
        self._selected: tuple[str, str] | None = None
        self._marker_radius_current = 0.025
        self._marker_radius_locked = False
        self._zoom_reference_parallel_scale: float | None = None
        self._picker = vtk.vtkCellPicker()
        self._picker.SetTolerance(0.01)
        self.plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_click)
        self.plotter.iren.add_observer("EndInteractionEvent", self._on_interaction_end)

    def render_model(self, model: StructuralModel) -> None:
        camera_state = self._camera_state()
        preserve_camera = bool(self._actors)
        self._model = model
        self._actors.clear()
        self._label_actors = {"node": [], "bar": []}
        self._node_label_actors.clear()
        self._member_label_actors.clear()
        self._local_axis_actors.clear()
        self._local_axis_actors_by_member.clear()
        self._member_aura_actors.clear()
        self._member_cap_actors.clear()
        self._member_aura_cap_actors.clear()
        self._member_release_actors.clear()
        self._node_aura_actors.clear()
        self._node_support_actors.clear()
        self._hovered = None
        self.plotter.clear()
        self.plotter.set_background("#ffffff")
        self._orientation_widget.SetEnabled(1)
        self._grid_renderer.render(self.plotter)
        if not model.nodes:
            self._marker_radius_locked = False
            if preserve_camera and camera_state is not None:
                self._restore_camera(camera_state)
            self.plotter.render()
            return

        positions = np.array([[node.x, node.y, node.z] for node in model.nodes.values()])
        if self._marker_radius_locked:
            radius = self._marker_radius_current
        else:
            radius = self._marker_radius(positions)
            self._marker_radius_locked = True
        self._marker_radius_current = radius
        for bar in model.bars.values():
            start, end = model.nodes[bar.start_node], model.nodes[bar.end_node]
            label_actor, axes, aura, release_actors, member_caps, aura_caps = self._member_renderer.render(
                self.plotter, bar, start, end, radius, self._register_actor,
                self._labels_visibility["bar"], self._local_axes_visible,
            )
            self._label_actors["bar"].append(label_actor)
            self._member_label_actors[bar.name] = label_actor
            self._local_axis_actors_by_member[bar.name] = axes
            self._local_axis_actors.extend(axes)
            self._member_aura_actors[bar.name] = aura
            self._member_cap_actors[bar.name] = member_caps
            self._member_aura_cap_actors[bar.name] = aura_caps
            self._member_release_actors[bar.name] = release_actors

        # Render nodes after members so endpoint markers have visual priority
        # when their geometry overlaps a member or one of its axes.
        for node in model.nodes.values():
            label_actor, aura, support = self._node_renderer.render(
                self.plotter, node, radius, self._register_actor, self._labels_visibility["node"]
            )
            self._label_actors["node"].append(label_actor)
            self._node_label_actors[node.name] = label_actor
            self._node_aura_actors[node.name] = aura
            if support is not None:
                self._node_support_actors[node.name] = support
        if self._selected:
            selected_identifier = f"{self._selected[0]}:{self._selected[1]}"
            if selected_identifier in self._actors:
                self._set_color(selected_identifier, True)
        if preserve_camera and camera_state is not None:
            self._restore_camera(camera_state)
        else:
            self.plotter.reset_camera()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._position_members_in_front()
        self._position_nodes_in_front()
        self._position_local_axes_in_front()
        self._position_release_indicators_in_front()
        self.plotter.render()

    def _position_members_in_front(self) -> None:
        """Move member lines and their auras slightly toward the camera."""
        camera_position = np.array(self.plotter.renderer.GetActiveCamera().GetPosition(), dtype=float)
        aura_offset = self._marker_radius_current * 0.08
        member_offset = self._marker_radius_current * 0.22
        for member_name, member in self._model.bars.items():
            actor_entry = self._actors.get(f"bar:{member_name}")
            aura = self._member_aura_actors.get(member_name)
            if actor_entry is None or aura is None:
                continue
            start = self._model.nodes[member.start_node]
            end = self._model.nodes[member.end_node]
            midpoint = np.array(
                ((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2),
                dtype=float,
            )
            direction = camera_position - midpoint
            length = np.linalg.norm(direction)
            if length <= 1e-12:
                continue
            direction /= length
            aura_front_offset = direction * aura_offset
            member_front_offset = direction * member_offset
            actor_entry[2].SetPosition(*member_front_offset)
            aura.SetPosition(*aura_front_offset)
            for caps, front_offset in (
                (self._member_cap_actors.get(member_name, ()), member_front_offset),
                (self._member_aura_cap_actors.get(member_name, ()), aura_front_offset),
            ):
                for cap, point in zip(caps, (start, end)):
                    cap.SetPosition(
                        point.x + front_offset[0],
                        point.y + front_offset[1],
                        point.z + front_offset[2],
                    )

    def _position_nodes_in_front(self) -> None:
        """Keep node circles in front of members and their rounded caps."""
        camera_position = np.array(self.plotter.renderer.GetActiveCamera().GetPosition(), dtype=float)
        offset = self._marker_radius_current * 0.8
        for node_name, node in self._model.nodes.items():
            self._position_node_in_front(node_name, node, camera_position, offset)

    def _position_node_in_front(self, node_name, node, camera_position, offset) -> None:
        identifier = f"node:{node_name}"
        aura = self._node_aura_actors.get(node_name)
        actor = self._actors.get(identifier, (None, None, None))[2]
        if aura is None or actor is None:
            return
        node_position = np.array((node.x, node.y, node.z), dtype=float)
        direction = camera_position - node_position
        length = np.linalg.norm(direction)
        if length <= 1e-12:
            return
        front_position = node_position + direction / length * offset
        aura.SetPosition(*front_position)
        actor.SetPosition(*front_position)

    def _current_parallel_scale(self) -> float | None:
        camera = self.plotter.renderer.GetActiveCamera()
        if not camera.GetParallelProjection():
            return None
        scale = float(camera.GetParallelScale())
        return scale if scale > 0 else None

    def _camera_state(self):
        camera = self.plotter.renderer.GetActiveCamera()
        return (
            tuple(camera.GetPosition()),
            tuple(camera.GetFocalPoint()),
            tuple(camera.GetViewUp()),
            float(camera.GetParallelScale()),
        )

    def _restore_camera(self, state) -> None:
        position, focal_point, view_up, parallel_scale = state
        camera = self.plotter.renderer.GetActiveCamera()
        camera.SetPosition(*position)
        camera.SetFocalPoint(*focal_point)
        camera.SetViewUp(*view_up)
        camera.SetParallelScale(parallel_scale)
        camera.OrthogonalizeViewUp()

    def _update_zoom_dependent_sizes(self) -> None:
        """Scale member line widths with the current parallel-camera zoom."""
        current_scale = self._current_parallel_scale()
        reference_scale = self._zoom_reference_parallel_scale
        if current_scale is None or reference_scale is None:
            return
        zoom_factor = reference_scale / current_scale
        height = self.plotter.render_window.GetSize()[1]
        world_units_per_pixel = (2.0 * current_scale / height) if height > 0 else 0.0
        for member_name in self._model.bars:
            member_actor = self._actors.get(f"bar:{member_name}", (None, None, None))[2]
            aura = self._member_aura_actors.get(member_name)
            if member_actor is not None:
                member_actor.GetProperty().SetLineWidth(4.0 * zoom_factor)
            if aura is not None:
                aura.GetProperty().SetLineWidth(10.0 * zoom_factor)
            member_radius = 4.0 * zoom_factor * world_units_per_pixel / 2.0
            aura_radius = 10.0 * zoom_factor * world_units_per_pixel / 2.0
            for cap in self._member_cap_actors.get(member_name, ()):
                cap.SetScale(member_radius, member_radius, member_radius)
            for cap in self._member_aura_cap_actors.get(member_name, ()):
                cap.SetScale(aura_radius, aura_radius, aura_radius)

    def _position_local_axes_in_front(self) -> None:
        """Move local-axis actors slightly toward the camera over members."""
        camera_position = np.array(self.plotter.renderer.GetActiveCamera().GetPosition(), dtype=float)
        offset = self._marker_radius_current * 0.25
        for member_name, actors in self._local_axis_actors_by_member.items():
            member = self._model.bars.get(member_name)
            if member is None:
                continue
            start = self._model.nodes[member.start_node]
            end = self._model.nodes[member.end_node]
            midpoint = np.array(
                ((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2),
                dtype=float,
            )
            direction = camera_position - midpoint
            length = np.linalg.norm(direction)
            if length <= 1e-12:
                continue
            front_offset = direction / length * offset
            for actor in actors:
                actor.SetPosition(*front_offset)

    def _position_release_indicators_in_front(self) -> None:
        """Move release symbols slightly toward the camera over the member."""
        camera_position = np.array(self.plotter.renderer.GetActiveCamera().GetPosition(), dtype=float)
        offset = self._marker_radius_current * 0.3
        for member_name, actors in self._member_release_actors.items():
            member = self._model.bars.get(member_name)
            if member is None:
                continue
            start = self._model.nodes[member.start_node]
            end = self._model.nodes[member.end_node]
            midpoint = np.array(
                ((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2),
                dtype=float,
            )
            direction = camera_position - midpoint
            length = np.linalg.norm(direction)
            if length <= 1e-12:
                continue
            front_offset = direction / length * offset
            for actor in actors:
                actor.SetPosition(*front_offset)

    def _on_interaction_end(self, *_args) -> None:
        self._update_zoom_dependent_sizes()
        self._position_members_in_front()
        self._position_nodes_in_front()
        self._position_local_axes_in_front()
        self._position_release_indicators_in_front()
        self.plotter.render()

    def update_member_releases(self, member_name: str) -> None:
        """Update one member's release symbols without rebuilding the scene."""
        if member_name not in self._model.bars or f"bar:{member_name}" not in self._actors:
            self.render_model(self._model)
            return
        for actor in self._member_release_actors.get(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        member = self._model.bars[member_name]
        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        self._member_release_actors[member_name] = self._member_renderer.releases.render(
            self.plotter, start, end, member.releases, self._marker_radius_current,
            rotation=member.rotation,
        )
        self._position_release_indicators_in_front()
        self.plotter.render()

    def update_member_axes(self, member_name: str) -> None:
        """Update only one member's local axes without rebuilding the scene."""
        if member_name not in self._model.bars or f"bar:{member_name}" not in self._actors:
            self.render_model(self._model)
            return
        member = self._model.bars[member_name]
        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        for actor in self._member_release_actors.get(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        for actor in self._local_axis_actors_by_member.get(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        axes = self._member_renderer.axes.render(
            self.plotter, start, end, rotation=member.rotation, visible=self._local_axes_visible,
        )
        release_actors = self._member_renderer.releases.render(
            self.plotter, start, end, member.releases, self._marker_radius_current,
            rotation=member.rotation,
        )
        self._local_axis_actors_by_member[member_name] = axes
        self._member_release_actors[member_name] = release_actors
        self._local_axis_actors = [
            actor for member_axes in self._local_axis_actors_by_member.values()
            for actor in member_axes
        ]
        self._position_local_axes_in_front()
        self._position_release_indicators_in_front()
        self.plotter.render()

    def update_member_color(self, member_name: str) -> None:
        """Update only one member's actor color without rebuilding the scene."""
        identifier = f"bar:{member_name}"
        if member_name not in self._model.bars or identifier not in self._actors:
            self.render_model(self._model)
            return
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)
        else:
            actor = self._actors[identifier][2]
            actor.GetProperty().SetColor(*pv.Color(self._member_base_color(member_name)).float_rgb)
            for cap in self._member_cap_actors.get(member_name, ()):
                cap.GetProperty().SetColor(*pv.Color(self._member_base_color(member_name)).float_rgb)
        self.plotter.render()

    def update_node_visual(self, node_name: str) -> None:
        """Update a node's color/support symbol without rebuilding the scene."""
        identifier = f"node:{node_name}"
        if node_name not in self._model.nodes or identifier not in self._actors:
            self.render_model(self._model)
            return
        actor = self._actors[identifier][2]
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)
        else:
            actor.GetProperty().SetColor(*pv.Color(self._node_base_color(node_name)).float_rgb)
        support = self._node_support_actors.pop(node_name, None)
        if support is not None:
            self.plotter.remove_actor(support, reset_camera=False, render=False)
        node = self._model.nodes[node_name]
        support = self._node_renderer.supports.render(
            self.plotter, node, self._marker_radius_current,
        )
        if support is not None:
            self._node_support_actors[node_name] = support
        self.plotter.render()

    def update_node(self, node_name: str) -> None:
        """Update one node and all member visuals attached to it."""
        if node_name not in self._model.nodes or f"node:{node_name}" not in self._actors:
            self.render_model(self._model)
            return

        connected_members = [
            member.name for member in self._model.bars.values()
            if member.start_node == node_name or member.end_node == node_name
        ]
        for member_name in connected_members:
            self._update_member_geometry(member_name)

        self._update_node_geometry(node_name)
        self._update_zoom_dependent_sizes()
        self._position_members_in_front()
        self._position_nodes_in_front()
        self._position_local_axes_in_front()
        self._position_release_indicators_in_front()
        self.plotter.render()

    def _update_node_geometry(self, node_name: str) -> None:
        identifier = f"node:{node_name}"
        actor_entry = self._actors.pop(identifier, None)
        if actor_entry is not None:
            self.plotter.remove_actor(actor_entry[2], reset_camera=False, render=False)
        aura = self._node_aura_actors.pop(node_name, None)
        if aura is not None:
            self.plotter.remove_actor(aura, reset_camera=False, render=False)
        support = self._node_support_actors.pop(node_name, None)
        if support is not None:
            self.plotter.remove_actor(support, reset_camera=False, render=False)
        self._remove_label("node", node_name)

        node = self._model.nodes[node_name]
        label, aura, support = self._node_renderer.render(
            self.plotter, node, self._marker_radius_current,
            self._register_actor, self._labels_visibility["node"],
        )
        self._node_label_actors[node_name] = label
        self._label_actors["node"].append(label)
        self._node_aura_actors[node_name] = aura
        if support is not None:
            self._node_support_actors[node_name] = support
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)

    def _update_member_geometry(self, member_name: str) -> None:
        member = self._model.bars[member_name]
        identifier = f"bar:{member_name}"
        actor_entry = self._actors.pop(identifier, None)
        if actor_entry is not None:
            self.plotter.remove_actor(actor_entry[2], reset_camera=False, render=False)
        aura = self._member_aura_actors.pop(member_name, None)
        if aura is not None:
            self.plotter.remove_actor(aura, reset_camera=False, render=False)
        for actor in self._member_cap_actors.pop(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        for actor in self._member_aura_cap_actors.pop(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        for actor in self._local_axis_actors_by_member.pop(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        self._local_axis_actors = [
            actor for member_axes in self._local_axis_actors_by_member.values()
            for actor in member_axes
        ]
        for actor in self._member_release_actors.pop(member_name, ()):
            self.plotter.remove_actor(actor, reset_camera=False, render=False)
        self._remove_label("bar", member_name)

        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        label, axes, aura, releases, caps, aura_caps = self._member_renderer.render(
            self.plotter, member, start, end, self._marker_radius_current,
            self._register_actor, self._labels_visibility["bar"], self._local_axes_visible,
        )
        self._member_label_actors[member_name] = label
        self._label_actors["bar"].append(label)
        self._local_axis_actors_by_member[member_name] = axes
        self._local_axis_actors.extend(axes)
        self._member_aura_actors[member_name] = aura
        self._member_cap_actors[member_name] = caps
        self._member_aura_cap_actors[member_name] = aura_caps
        self._member_release_actors[member_name] = releases
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)

    def _remove_label(self, kind: str, name: str) -> None:
        labels = self._node_label_actors if kind == "node" else self._member_label_actors
        label = labels.pop(name, None)
        if label is not None:
            self.plotter.remove_actor(label, reset_camera=False, render=False)
            if label in self._label_actors[kind]:
                self._label_actors[kind].remove(label)

    def _create_orientation_widget(self):
        widget = NavigationWidget.create(self.plotter)
        return widget

    def reset_camera(self) -> None:
        self.plotter.reset_camera()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._position_members_in_front()
        self._position_nodes_in_front()
        self._position_local_axes_in_front()
        self._position_release_indicators_in_front()
        self.plotter.render()

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
            self._update_zoom_dependent_sizes()




    def _set_color(self, identifier: str, hovered: bool) -> None:
        kind, name, actor = self._actors[identifier]
        if kind in {"bar", "node"}:
            color = self._member_base_color(name) if kind == "bar" else self._node_base_color(name)
            actor.GetProperty().SetColor(*pv.Color(color).float_rgb)
            if kind == "bar":
                reference_scale = self._zoom_reference_parallel_scale
                current_scale = self._current_parallel_scale()
                zoom_factor = (
                    reference_scale / current_scale
                    if reference_scale is not None and current_scale is not None
                    else 1.0
                )
                actor.GetProperty().SetLineWidth(4.0 * zoom_factor)
                for cap in self._member_cap_actors.get(name, ()):
                    cap.GetProperty().SetColor(*pv.Color(color).float_rgb)
            aura_map = self._member_aura_actors if kind == "bar" else self._node_aura_actors
            aura = aura_map.get(name)
            if aura is not None:
                aura.SetVisibility(hovered)
            if kind == "bar":
                for cap in self._member_aura_cap_actors.get(name, ()):
                    cap.SetVisibility(hovered)
            return

    def _node_base_color(self, name: str) -> str:
        del name
        return "#000000"

    def _member_base_color(self, name: str) -> str:
        return self._model.bars[name].color


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
