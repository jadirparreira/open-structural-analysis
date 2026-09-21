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
from .solid_member_renderer import SolidMemberRenderer


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
        self._solid_member_renderer = SolidMemberRenderer()
        self._orientation_widget = self._create_orientation_widget()
        self._model = StructuralModel()
        self._actors: dict[str, tuple[str, str, object]] = {}
        self._label_actors: dict[str, list[object]] = {"node": [], "bar": []}
        self._node_label_actors: dict[str, object] = {}
        self._member_label_actors: dict[str, object] = {}
        self._local_axis_actors: list[object] = []
        self._local_axis_actors_by_member: dict[str, list[object]] = {}
        self._member_aura_actors: dict[str, object] = {}
        self._member_line_actors: dict[str, object] = {}
        self._member_solid_actors: dict[str, object] = {}
        self._member_cap_actors: dict[str, list[object]] = {}
        self._member_aura_cap_actors: dict[str, list[object]] = {}
        self._member_release_actors: dict[str, list[object]] = {}
        self._node_aura_actors: dict[str, object] = {}
        self._node_support_actors: dict[str, object] = {}
        self._local_axes_visible = True
        self._labels_visibility = {"node": True, "bar": True}
        self._solid_members_visible = True
        self._member_releases_visible = True
        self._node_supports_visible = True
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
        self._member_line_actors.clear()
        self._member_solid_actors.clear()
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
            self._member_line_actors[bar.name] = self._actors[f"bar:{bar.name}"][2]
            self._local_axis_actors_by_member[bar.name] = axes
            self._local_axis_actors.extend(axes)
            self._member_aura_actors[bar.name] = aura
            self._member_cap_actors[bar.name] = member_caps
            self._member_aura_cap_actors[bar.name] = aura_caps
            self._member_release_actors[bar.name] = release_actors
            self._set_release_actors_visible(release_actors)

        if self._solid_members_visible:
            for member_name in model.bars:
                self._switch_member_representation(member_name)

        # Render nodes after members so endpoint markers have visual priority
        # when their geometry overlaps a member or one of its axes.
        for node in model.nodes.values():
            label_actor, aura, support = self._node_renderer.render(
                self.plotter, node, self._node_marker_radius(), self._register_actor,
                self._labels_visibility["node"], support_radius=self._marker_radius_current,
            )
            self._label_actors["node"].append(label_actor)
            self._node_label_actors[node.name] = label_actor
            self._node_aura_actors[node.name] = aura
            if support is not None:
                self._node_support_actors[node.name] = support
                self._set_support_actor_visible(support)
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
        self._update_depth_overlays()
        self.plotter.render()

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
            member_actor = self._member_line_actors.get(member_name)
            aura = self._member_aura_actors.get(member_name)
            if member_actor is not None:
                member_actor.GetProperty().SetLineWidth(4.0 * zoom_factor)
            if aura is not None:
                aura.GetProperty().SetLineWidth(self._member_renderer.AURA_LINE_WIDTH * zoom_factor)
            member_radius = 4.0 * zoom_factor * world_units_per_pixel / 2.0
            aura_radius = (
                self._member_renderer.AURA_LINE_WIDTH * zoom_factor * world_units_per_pixel / 2.0
            )
            for cap in self._member_cap_actors.get(member_name, ()):
                cap.SetScale(member_radius, member_radius, member_radius)
            for cap in self._member_aura_cap_actors.get(member_name, ()):
                cap.SetScale(aura_radius, aura_radius, aura_radius)

    def _on_interaction_end(self, *_args) -> None:
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self.plotter.render()

    def _update_depth_overlays(self) -> None:
        """Offset only selection auras and local axes relative to the camera."""
        camera_position = np.array(self.plotter.renderer.GetActiveCamera().GetPosition(), dtype=float)
        aura_offset = self._marker_radius_current * 0.08
        axes_offset = self._marker_radius_current * 0.25
        for member_name, member in self._model.bars.items():
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
            aura_position = -direction * aura_offset
            axes_position = direction * axes_offset
            aura = self._member_aura_actors.get(member_name)
            if aura is not None:
                aura.SetPosition(*aura_position)
            for cap, point in zip(self._member_aura_cap_actors.get(member_name, ()), (start, end)):
                cap.SetPosition(
                    point.x + aura_position[0],
                    point.y + aura_position[1],
                    point.z + aura_position[2],
                )
            for actor in self._local_axis_actors_by_member.get(member_name, ()):
                actor.SetPosition(*axes_position)

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
        release_actors = self._member_renderer.releases.render(
            self.plotter, start, end, member.releases, self._marker_radius_current,
            rotation=member.rotation,
        )
        self._member_release_actors[member_name] = release_actors
        self._set_release_actors_visible(release_actors)
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
        self._set_release_actors_visible(release_actors)
        self._local_axis_actors = [
            actor for member_axes in self._local_axis_actors_by_member.values()
            for actor in member_axes
        ]
        self._update_depth_overlays()
        self.plotter.render()

    def update_member_rotation(self, member_name: str) -> None:
        """Update a member's solid transform and local-axis annotations."""
        if member_name not in self._model.bars or f"bar:{member_name}" not in self._actors:
            self.render_model(self._model)
            return
        member = self._model.bars[member_name]
        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        solid_visual = self._member_solid_actors.get(member_name)
        if solid_visual is not None:
            self._solid_member_renderer.update_transform(
                solid_visual.face_actor, start, end, rotation=member.rotation,
            )
            self._solid_member_renderer.update_transform(
                solid_visual.edge_actor, start, end, rotation=member.rotation,
            )
        self.update_member_axes(member_name)

    def update_member_geometry(self, member_name: str) -> None:
        """Rebuild one member after its section or profile geometry changes."""
        if member_name not in self._model.bars or member_name not in self._member_line_actors:
            self.render_model(self._model)
            return
        self._update_member_geometry(member_name)
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self.plotter.render()

    def update_member_color(self, member_name: str) -> None:
        """Update only one member's actor color without rebuilding the scene."""
        identifier = f"bar:{member_name}"
        if member_name not in self._model.bars or identifier not in self._actors:
            self.render_model(self._model)
            return
        color = pv.Color(self._member_base_color(member_name)).float_rgb
        solid_visual = self._member_solid_actors.get(member_name)
        for actor in (
            self._member_line_actors.get(member_name),
            solid_visual.face_actor if solid_visual is not None else None,
        ):
            if actor is not None:
                actor.GetProperty().SetColor(*color)
        if solid_visual is not None:
            solid_visual.edge_actor.GetProperty().SetColor(
                *self._solid_member_renderer.edge_color(self._member_base_color(member_name))
            )
        for cap in self._member_cap_actors.get(member_name, ()):
            cap.GetProperty().SetColor(*color)
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)
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
            self._set_support_actor_visible(support)
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
        self._update_depth_overlays()
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
            self.plotter, node, self._node_marker_radius(), self._register_actor,
            self._labels_visibility["node"], support_radius=self._marker_radius_current,
        )
        self._node_label_actors[node_name] = label
        self._label_actors["node"].append(label)
        self._node_aura_actors[node_name] = aura
        if support is not None:
            self._node_support_actors[node_name] = support
            self._set_support_actor_visible(support)
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if identifier == self._hovered or identifier == selected_identifier:
            self._set_color(identifier, True)

    def _update_member_geometry(self, member_name: str) -> None:
        member = self._model.bars[member_name]
        identifier = f"bar:{member_name}"
        active_entry = self._actors.pop(identifier, None)
        line_actor = self._member_line_actors.pop(member_name, None)
        solid_visual = self._member_solid_actors.pop(member_name, None)
        removed = set()
        solid_actors = (
            (solid_visual.face_actor, solid_visual.edge_actor)
            if solid_visual is not None else ()
        )
        for actor in (active_entry[2] if active_entry is not None else None, line_actor, *solid_actors):
            if actor is not None and id(actor) not in removed:
                self.plotter.remove_actor(actor, reset_camera=False, render=False)
                removed.add(id(actor))
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
        self._member_line_actors[member_name] = self._actors[identifier][2]
        self._label_actors["bar"].append(label)
        self._local_axis_actors_by_member[member_name] = axes
        self._local_axis_actors.extend(axes)
        self._member_aura_actors[member_name] = aura
        self._member_cap_actors[member_name] = caps
        self._member_aura_cap_actors[member_name] = aura_caps
        self._member_release_actors[member_name] = releases
        self._set_release_actors_visible(releases)
        if self._solid_members_visible:
            self._switch_member_representation(member_name)
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
        self._update_depth_overlays()
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
                solid_visual = self._member_solid_actors.get(name)
                if solid_visual is not None and solid_visual.face_actor is actor:
                    solid_visual.edge_actor.GetProperty().SetColor(
                        *self._solid_member_renderer.edge_color(color)
                    )
                    return
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

    def _switch_member_representation(self, member_name: str) -> None:
        """Make one member's line or solid actor the active representation."""
        member = self._model.bars.get(member_name)
        line_actor = self._member_line_actors.get(member_name)
        if member is None or line_actor is None:
            return
        identifier = f"bar:{member_name}"
        if self._solid_members_visible:
            solid_visual = self._member_solid_actors.get(member_name)
            if solid_visual is None:
                start = self._model.nodes[member.start_node]
                end = self._model.nodes[member.end_node]
                solid_visual = self._solid_member_renderer.render(
                    self.plotter, member, start, end, visible=True,
                )
                if solid_visual is not None:
                    self._member_solid_actors[member_name] = solid_visual
            if solid_visual is not None:
                line_actor.SetVisibility(False)
                line_actor.SetPickable(False)
                for actor in self._member_cap_actors.get(member_name, ()):
                    actor.SetVisibility(False)
                for actor in self._member_aura_cap_actors.get(member_name, ()):
                    actor.SetVisibility(False)
                aura = self._member_aura_actors.get(member_name)
                if aura is not None:
                    aura.SetVisibility(False)
                solid_visual.face_actor.SetObjectName(identifier)
                solid_visual.face_actor.SetVisibility(True)
                solid_visual.face_actor.SetPickable(True)
                solid_visual.edge_actor.SetVisibility(True)
                self._actors[identifier] = "bar", member_name, solid_visual.face_actor
                return

        solid_visual = self._member_solid_actors.get(member_name)
        if solid_visual is not None:
            solid_visual.face_actor.SetVisibility(False)
            solid_visual.face_actor.SetPickable(False)
            solid_visual.edge_actor.SetVisibility(False)
        line_actor.SetObjectName(identifier)
        line_actor.SetVisibility(True)
        line_actor.SetPickable(True)
        for actor in self._member_cap_actors.get(member_name, ()):
            actor.SetVisibility(True)
        self._actors[identifier] = "bar", member_name, line_actor

    def set_solid_members_visible(self, visible: bool) -> None:
        """Toggle the exclusive line/solid representation of structural members."""
        visible = bool(visible)
        if visible == self._solid_members_visible:
            return
        self._solid_members_visible = visible
        self._hovered = None
        for member_name in self._model.bars:
            self._switch_member_representation(member_name)
        selected_identifier = f"{self._selected[0]}:{self._selected[1]}" if self._selected else None
        if selected_identifier in self._actors:
            self._set_color(selected_identifier, True)
        self._update_depth_overlays()
        self.plotter.render()

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

    def set_member_releases_visible(self, visible: bool) -> None:
        """Toggle the circular release symbols displayed on members."""
        self._member_releases_visible = bool(visible)
        for actors in self._member_release_actors.values():
            self._set_release_actors_visible(actors)
        self.plotter.render()

    def set_node_supports_visible(self, visible: bool) -> None:
        """Toggle the 3D support symbols displayed at supported nodes."""
        self._node_supports_visible = bool(visible)
        for actor in self._node_support_actors.values():
            self._set_support_actor_visible(actor)
        self.plotter.render()

    def _set_release_actors_visible(self, actors: list[object]) -> None:
        for actor in actors:
            actor.SetVisibility(self._member_releases_visible)

    def _set_support_actor_visible(self, actor: object) -> None:
        actor.SetVisibility(self._node_supports_visible)

    def _node_marker_radius(self) -> float:
        """Return the radius used by the permanent 3D node marker."""
        return self._marker_radius_current


    @staticmethod
    def _address(actor) -> str:
        return actor.GetAddressAsString("")

    @staticmethod
    def _marker_radius(positions: np.ndarray) -> float:
        # Keep node/support symbols visually consistent regardless of model size.
        return 0.05
