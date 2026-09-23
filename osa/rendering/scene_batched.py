"""Interactive PyVista scene backed by batched VTK geometry."""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from osa.model import StructuralModel

from .batched_renderer import BatchedMemberRenderer, BatchedNodeRenderer, MemberBatch, NodeBatch
from .action_renderer import ActionRenderer
from .grid_renderer import GridRenderer
from .label_overlay import LabelOverlay
from .navigation_widget import NavigationWidget
from .reference_axes_renderer import ReferenceAxesRenderer


class StructureScene(QWidget):
    """Render the full model with a small, stable number of VTK actors."""

    element_clicked = Signal(str, str, object)
    empty_clicked = Signal()
    _axis_colors = ("#d1242f", "#f2b705", "#2da44e")
    # View the model from -X, -Y and +Z.  With Z kept vertical on screen,
    # positive X points northeast and positive Y points northwest.
    _default_view_direction = (-1.0, -1.0, 1.0)
    _default_view_up = (0.0, 0.0, 1.0)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter)
        self.plotter.set_background("#ffffff")
        self.plotter.enable_parallel_projection()

        self._grid_renderer = GridRenderer()
        self._reference_axes_renderer = ReferenceAxesRenderer()
        self._member_renderer = BatchedMemberRenderer()
        self._node_renderer = BatchedNodeRenderer()
        self._action_renderer = ActionRenderer()
        self._label_overlay = LabelOverlay(self.plotter)
        self._orientation_widget = NavigationWidget.create(self.plotter)
        self._model = StructuralModel()
        self._member_batch: MemberBatch | None = None
        self._node_batch: NodeBatch | None = None

        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._grid_actor = None
        self._reference_axes_actor = None
        self._node_actor = None
        self._support_actor = None
        self._release_actor = None
        self._local_axis_actors: list[object] = []
        self._action_actors: list[object] = []
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels: tuple[str, ...] = ()
        self._active_load_case: str | None = None
        self._actions_visible = False
        self._action_visibility = {
            "node_forces": True,
            "node_moments": True,
            "member_forces": True,
            "member_moments": True,
        }
        self._pick_sources: dict[str, tuple[str, pv.PolyData, tuple[str, ...]]] = {}
        self._highlight_actors: dict[str, object] = {}

        self._local_axes_visible = True
        self._grid_visible = True
        self._reference_axes_visible = True
        self._labels_visibility = {"node": True, "bar": True}
        self._solid_members_visible = True
        self._member_releases_visible = True
        self._node_supports_visible = True
        self._hovered: tuple[str, str] | None = None
        self._selected: tuple[str, str] | None = None
        self._marker_radius_current = 0.05
        self._reference_plane_mode = "XY"
        self._reference_plane_z = 0.0
        self._marker_radius_locked = False
        self._zoom_reference_parallel_scale: float | None = None
        self._camera_interacting = False

        self._picker = vtk.vtkCellPicker()
        self._picker.SetTolerance(0.01)
        self._picker.PickFromListOn()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(32)
        self._hover_timer.timeout.connect(self._update_hover)
        self._label_timer = QTimer(self)
        self._label_timer.setSingleShot(True)
        self._label_timer.setInterval(16)
        self._label_timer.timeout.connect(self._sync_labels)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(24)
        self._rebuild_timer.timeout.connect(self._rebuild_scene)

        # CameraCubeWidget animates the vtkCamera directly, so those changes do
        # not emit the interactor's InteractionEvent.  Observe the camera itself
        # and coalesce its several modifications into the existing 16 ms label
        # update.  This also covers future camera controls without coupling them
        # to the label overlay.
        self._observed_camera = self.plotter.renderer.GetActiveCamera()
        self._camera_observer_id = self._observed_camera.AddObserver(
            "ModifiedEvent", self._on_camera_modified,
        )

        self.plotter.iren.add_observer("MouseMoveEvent", self._on_mouse_move)
        self.plotter.iren.add_observer("LeftButtonPressEvent", self._on_left_click)
        self.plotter.iren.add_observer("InteractionEvent", self._on_interaction)
        self.plotter.iren.add_observer("EndInteractionEvent", self._on_interaction_end)

    def render_model(self, model: StructuralModel) -> None:
        self._rebuild_timer.stop()
        camera_state = self._camera_state()
        preserve_camera = self._has_scene()
        self._model = model
        self._reference_plane_z = self._reference_plane_for_model(model)
        self._hovered = None
        self._validate_selection()
        self._clear_actor_references()
        self.plotter.clear()
        self.plotter.set_background("#ffffff")
        self._grid_actor = self._grid_renderer.render(
            self.plotter, model.nodes.values(), model.axes,
            self._reference_plane_mode, self._reference_plane_z,
        )
        self._grid_actor.SetVisibility(self._grid_visible)
        self._reference_axes_actor = self._reference_axes_renderer.render(
            self.plotter, model.axes, self._grid_renderer.bounds,
            self._reference_plane_mode, self._reference_plane_z,
        )
        if self._reference_axes_actor is not None:
            self._reference_axes_actor.SetVisibility(self._reference_axes_visible)

        if not model.nodes:
            self._marker_radius_locked = False
            self._label_overlay.clear()
            self._add_reference_axis_labels()
            if preserve_camera and camera_state is not None:
                self._restore_camera(camera_state)
            elif self._reference_axes_actor is not None:
                self.plotter.reset_camera()
            self._orientation_widget.sync_from_camera()
            self._sync_labels()
            self.plotter.render()
            return

        positions = np.asarray([(node.x, node.y, node.z) for node in model.nodes.values()])
        if not self._marker_radius_locked:
            self._marker_radius_current = self._marker_radius(positions)
            self._marker_radius_locked = True

        self._member_batch = self._member_renderer.build(model, self._marker_radius_current)
        self._node_batch = self._node_renderer.build(model, self._node_marker_radius())
        self._add_member_batches()
        self._add_node_batches()
        self._add_actions()
        self._add_labels()
        self._apply_representation_visibility()
        self._configure_picker()
        self._sync_highlights()

        if preserve_camera and camera_state is not None:
            self._restore_camera(camera_state)
        else:
            self._set_default_isometric_view()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _add_member_batches(self) -> None:
        batch = self._member_batch
        if batch is None:
            return
        self._member_line_actor = self._add_colored_mesh(
            batch.lines, "batch:member-lines", line_width=4,
            render_lines_as_tubes=True, lighting=False,
        )
        self._register_pick_source(
            self._member_line_actor, "batch:member-lines", "bar", batch.lines, batch.names,
        )
        self._member_fallback_actor = self._add_colored_mesh(
            batch.fallback_lines, "batch:member-fallback", line_width=4,
            render_lines_as_tubes=True, lighting=False,
        )
        self._register_pick_source(
            self._member_fallback_actor, "batch:member-fallback", "bar",
            batch.fallback_lines, batch.names,
        )
        self._member_face_actor = self._add_colored_mesh(
            batch.faces, "batch:member-faces", smooth_shading=False, lighting=True,
        )
        if self._member_face_actor is not None:
            prop = self._member_face_actor.GetProperty()
            prop.SetEdgeVisibility(False)
            prop.SetInterpolationToFlat()
            prop.SetSpecular(0.12)
        self._register_pick_source(
            self._member_face_actor, "batch:member-faces", "bar", batch.faces, batch.names,
        )
        self._member_edge_actor = self._add_colored_mesh(
            batch.edges, "batch:member-edges", line_width=1.5, lighting=False,
        )
        if self._member_edge_actor is not None:
            self._member_edge_actor.SetPickable(False)

        for mesh, color in zip(batch.axes, self._axis_colors):
            if not mesh.n_cells:
                continue
            actor = self.plotter.add_mesh(
                mesh, color=color, line_width=4, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
                lighting=False,
            )
            actor.SetVisibility(self._local_axes_visible)
            self._local_axis_actors.append(actor)

        if batch.releases.n_cells:
            self._release_actor = self.plotter.add_mesh(
                batch.releases, color="#000000", line_width=3, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
                lighting=False,
            )
            self._release_actor.SetVisibility(self._member_releases_visible)

    def _add_node_batches(self) -> None:
        batch = self._node_batch
        if batch is None:
            return
        if batch.geometry.n_cells:
            self._node_actor = self.plotter.add_mesh(
                batch.geometry, color="#000000", smooth_shading=True,
                pickable=True, reset_camera=False, render=False,
            )
            self._register_pick_source(
                self._node_actor, "batch:nodes", "node", batch.geometry, batch.names,
            )
        if batch.supports.n_cells:
            self._support_actor = self.plotter.add_mesh(
                batch.supports, color="#a8b0b9", edge_color="#6e7781",
                show_edges=True, line_width=1.5, pickable=False,
                reset_camera=False, render=False,
            )
            self._support_actor.SetVisibility(self._node_supports_visible)

    def _add_actions(self) -> None:
        if not self._actions_visible:
            self._action_actors = []
            self._action_label_positions = np.empty((0, 3), dtype=float)
            self._action_labels = ()
            return
        (
            self._action_actors,
            self._action_label_positions,
            self._action_labels,
        ) = self._action_renderer.render(
            self.plotter, self._model, self._active_load_case, self._action_visibility,
        )

    def _add_labels(self) -> None:
        self._add_reference_axis_labels()
        if self._member_batch is not None:
            self._label_overlay.set_group(
                "bar", self._member_batch.label_positions, self._member_batch.names,
                visible=self._labels_visibility["bar"],
            )
        if self._node_batch is not None:
            self._label_overlay.set_group(
                "node", self._node_batch.label_positions, self._node_batch.names,
                visible=self._labels_visibility["node"],
            )
        self._label_overlay.set_group(
            "action", self._action_label_positions, self._action_labels, visible=True,
        )

    def _add_reference_axis_labels(self) -> None:
        positions, labels = self._reference_axes_renderer.labels(
            self._model.axes, self._grid_renderer.bounds, self._reference_plane_z,
            self._reference_plane_mode, self._reference_plane_z,
        )
        self._label_overlay.set_group(
            "reference-axis", positions, labels, visible=self._reference_axes_visible,
        )

    def _add_colored_mesh(self, mesh: pv.PolyData, name: str, **options):
        if not mesh.n_cells:
            return None
        actor = self.plotter.add_mesh(
            mesh, scalars="rgb", rgb=True, pickable=False,
            reset_camera=False, render=False, name=name, **options,
        )
        actor.SetObjectName(name)
        return actor

    def _register_pick_source(
        self, actor, identifier: str, kind: str, mesh: pv.PolyData, names: tuple[str, ...],
    ) -> None:
        if actor is None:
            return
        actor.SetObjectName(identifier)
        self._pick_sources[identifier] = kind, mesh, names

    def _configure_picker(self) -> None:
        self._picker.InitializePickList()
        actors = [self._node_actor]
        if self._solid_members_visible:
            actors.extend((self._member_face_actor, self._member_fallback_actor))
        else:
            actors.append(self._member_line_actor)
        active = {id(actor) for actor in actors if actor is not None}
        for actor in (
            self._node_actor, self._member_face_actor,
            self._member_fallback_actor, self._member_line_actor,
        ):
            if actor is None:
                continue
            enabled = id(actor) in active
            actor.SetPickable(enabled)
            if enabled:
                self._picker.AddPickList(actor)

    def _pick(self) -> tuple[str, str] | None:
        x, y = self.plotter.iren.get_event_position()
        if not self._picker.Pick(x, y, 0, self.plotter.renderer):
            return None
        actor = self._picker.GetActor()
        identifier = actor.GetObjectName() if actor is not None else None
        source = self._pick_sources.get(identifier)
        if source is None:
            return None
        kind, mesh, names = source
        cell_id = self._picker.GetCellId()
        if cell_id < 0 or cell_id >= mesh.n_cells:
            return None
        element_index = int(mesh.cell_data["element_index"][cell_id])
        if element_index < 0 or element_index >= len(names):
            return None
        return kind, names[element_index]

    def _on_mouse_move(self, *_args) -> None:
        if self._camera_interacting:
            return
        x, y = self.plotter.iren.get_event_position()
        if self._orientation_widget.is_pointer_over(x, y):
            if self._hovered is not None:
                self._hovered = None
                self._sync_highlights()
                self.plotter.render()
            return
        if not self._hover_timer.isActive():
            self._hover_timer.start()

    def _update_hover(self) -> None:
        if self._camera_interacting:
            return
        picked = self._pick()
        if picked == self._hovered:
            return
        self._hovered = picked
        self._sync_highlights()
        self.plotter.render()

    def _on_left_click(self, *_args) -> None:
        x, y = self.plotter.iren.get_event_position()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        picked = self._pick()
        self._selected = picked
        self._sync_highlights()
        self.plotter.render()
        if picked is None:
            self.empty_clicked.emit()
            return
        kind, name = picked
        self.element_clicked.emit(kind, name, self.element_center(kind, name))

    def _sync_highlights(self) -> None:
        self._replace_highlight("selected", self._selected, "#0969da")
        hover = None if self._hovered == self._selected else self._hovered
        self._replace_highlight("hover", hover, "#24292f")

    def _replace_highlight(
        self, slot: str, target: tuple[str, str] | None, color: str,
    ) -> None:
        previous = self._highlight_actors.pop(slot, None)
        if previous is not None:
            self.plotter.remove_actor(previous, reset_camera=False, render=False)
        if target is None:
            return
        kind, name = target
        if kind == "bar":
            mesh = self._member_highlight_mesh(name)
            if mesh is None or not mesh.n_cells:
                return
            actor = self.plotter.add_mesh(
                mesh, color=color, line_width=4 if slot == "selected" else 3,
                render_lines_as_tubes=True, lighting=False, pickable=False,
                reset_camera=False, render=False,
            )
        else:
            node = self._model.nodes.get(name)
            if node is None:
                return
            mesh = pv.Sphere(
                radius=self._node_marker_radius() * 1.35,
                center=(node.x, node.y, node.z), theta_resolution=20, phi_resolution=12,
            )
            actor = self.plotter.add_mesh(
                mesh, color=color, style="wireframe", line_width=2,
                lighting=False, pickable=False, reset_camera=False, render=False,
            )
        actor.SetObjectName(f"highlight:{slot}")
        self._highlight_actors[slot] = actor

    def _member_highlight_mesh(self, name: str) -> pv.PolyData | None:
        member = self._model.bars.get(name)
        if member is None:
            return None
        if self._solid_members_visible and self._member_batch is not None:
            outline = self._member_batch.outlines.get(name)
            if outline is not None:
                return outline
        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        return pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z))

    def _apply_representation_visibility(self) -> None:
        solid = self._solid_members_visible
        if self._member_line_actor is not None:
            self._member_line_actor.SetVisibility(not solid)
        if self._member_face_actor is not None:
            self._member_face_actor.SetVisibility(solid)
        if self._member_edge_actor is not None:
            self._member_edge_actor.SetVisibility(solid)
        if self._member_fallback_actor is not None:
            self._member_fallback_actor.SetVisibility(solid)

    def set_solid_members_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._solid_members_visible:
            return
        self._solid_members_visible = visible
        self._apply_representation_visibility()
        self._configure_picker()
        self._sync_highlights()
        self.plotter.render()

    def set_labels_visible(self, kind: str, visible: bool) -> None:
        self._labels_visibility[kind] = bool(visible)
        self._label_overlay.set_group_visible(kind, visible)

    def set_local_axes_visible(self, visible: bool) -> None:
        self._local_axes_visible = bool(visible)
        for actor in self._local_axis_actors:
            actor.SetVisibility(visible)
        self.plotter.render()

    def set_grid_visible(self, visible: bool) -> None:
        self._grid_visible = bool(visible)
        if self._grid_actor is not None:
            self._grid_actor.SetVisibility(visible)
        self.plotter.render()

    def set_reference_axes_visible(self, visible: bool) -> None:
        self._reference_axes_visible = bool(visible)
        if self._reference_axes_actor is not None:
            self._reference_axes_actor.SetVisibility(visible)
        self._label_overlay.set_group_visible("reference-axis", visible)
        self.plotter.render()

    def set_member_releases_visible(self, visible: bool) -> None:
        self._member_releases_visible = bool(visible)
        if self._release_actor is not None:
            self._release_actor.SetVisibility(visible)
        self.plotter.render()

    def set_node_supports_visible(self, visible: bool) -> None:
        self._node_supports_visible = bool(visible)
        if self._support_actor is not None:
            self._support_actor.SetVisibility(visible)
        self.plotter.render()

    def set_active_load_case(self, name: str | None) -> None:
        """Exibe somente as cargas associadas à ação selecionada."""
        name = name or None
        if name == self._active_load_case:
            return
        self._active_load_case = name
        self.render_model(self._model)

    def set_actions_visible(self, visible: bool) -> None:
        """Exibe ações somente quando a seção Ações estiver ativa."""
        visible = bool(visible)
        if visible == self._actions_visible:
            return
        self._actions_visible = visible
        self.render_model(self._model)

    def set_action_visibility(self, kind: str, visible: bool) -> None:
        """Liga ou desliga uma das quatro categorias de ações renderizadas."""
        if kind not in self._action_visibility:
            return
        visible = bool(visible)
        if self._action_visibility[kind] == visible:
            return
        self._action_visibility[kind] = visible
        self.render_model(self._model)

    def previous_reference_plane(self) -> None:
        self._step_reference_plane(-1)

    def next_reference_plane(self) -> None:
        self._step_reference_plane(1)

    def _step_reference_plane(self, step: int) -> None:
        levels = self._reference_plane_levels()
        current_index = min(
            range(len(levels)),
            key=lambda index: abs(levels[index] - self._reference_plane_z),
        )
        target_index = max(0, min(len(levels) - 1, current_index + step))
        target = levels[target_index]
        if np.isclose(target, self._reference_plane_z):
            return
        self._reference_plane_z = target
        self._refresh_reference_plane_renderers()
        self._add_reference_axis_labels()
        self._sync_labels()
        self.plotter.render()

    def set_reference_plane_mode(self, mode: str) -> None:
        mode = mode.upper()
        if mode not in {"XY", "XZ", "YZ"}:
            raise ValueError(f"Plano de referência desconhecido: {mode}")
        self._reference_plane_mode = mode
        self._reference_plane_z = self._reference_plane_for_model(self._model, preferred=0.0)
        self._refresh_reference_plane_renderers()
        self._add_reference_axis_labels()
        self._sync_labels()
        self.plotter.render()

    def _refresh_reference_plane_renderers(self) -> None:
        self._grid_renderer.update(
            self._model.nodes.values(), self._model.axes,
            self._reference_plane_mode, self._reference_plane_z,
        )
        self._reference_axes_renderer.mesh = self._reference_axes_renderer.build(
            self._model.axes, self._grid_renderer.bounds,
            self._reference_plane_mode, self._reference_plane_z,
        )
        if self._grid_actor is not None:
            self._grid_actor.GetMapper().SetInputData(self._grid_renderer.mesh)
            self._grid_actor.GetMapper().Modified()
        if self._reference_axes_actor is not None:
            self._reference_axes_actor.GetMapper().SetInputData(self._reference_axes_renderer.mesh)
            self._reference_axes_actor.GetMapper().Modified()

    def update_member_color(self, member_name: str) -> None:
        batch = self._member_batch
        if batch is None or member_name not in batch.names:
            self.render_model(self._model)
            return
        index = batch.names.index(member_name)
        base = np.asarray(pv.Color(self._model.bars[member_name].color).int_rgb, dtype=np.uint8)
        edge = np.clip(base.astype(float) * 0.65, 0, 255).astype(np.uint8)
        for mesh, color in (
            (batch.lines, base), (batch.fallback_lines, base),
            (batch.faces, base), (batch.edges, edge),
        ):
            if not mesh.n_cells or "rgb" not in mesh.cell_data:
                continue
            values = mesh.cell_data["rgb"]
            values[mesh.cell_data["element_index"] == index] = color
            mesh.cell_data["rgb"] = values
            mesh.GetCellData().Modified()
            mesh.Modified()
        self.plotter.render()

    def update_member_releases(self, _member_name: str) -> None:
        self._schedule_rebuild()

    def update_member_axes(self, _member_name: str) -> None:
        self._schedule_rebuild()

    def update_member_rotation(self, _member_name: str) -> None:
        self._schedule_rebuild()

    def update_member_geometry(self, _member_name: str) -> None:
        self._schedule_rebuild()

    def update_node_visual(self, _node_name: str) -> None:
        self._schedule_rebuild()

    def update_node(self, _node_name: str) -> None:
        self._schedule_rebuild()

    def _schedule_rebuild(self) -> None:
        """Coalesce rapid property edits into one batch reconstruction."""
        self._rebuild_timer.start()

    def _rebuild_scene(self) -> None:
        self.render_model(self._model)

    def remove_element(self, kind: str, name: str) -> None:
        target = kind, name
        if self._selected == target:
            self._selected = None
        if self._hovered == target:
            self._hovered = None
        self.render_model(self._model)

    def element_center(self, kind: str, name: str) -> tuple[float, float, float]:
        if kind == "node":
            node = self._model.nodes[name]
            return node.x, node.y, node.z
        member = self._model.bars[name]
        start = self._model.nodes[member.start_node]
        end = self._model.nodes[member.end_node]
        return (
            (start.x + end.x) / 2.0,
            (start.y + end.y) / 2.0,
            (start.z + end.z) / 2.0,
        )

    def reset_camera(self) -> None:
        self.plotter.reset_camera()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def view_isometric(self) -> None:
        self._set_default_isometric_view()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def rotate_camera_clockwise(self) -> None:
        self._orientation_widget.animate_camera_roll(clockwise=True)

    def rotate_camera_counterclockwise(self) -> None:
        self._orientation_widget.animate_camera_roll(clockwise=False)

    def _set_default_isometric_view(self) -> None:
        """Fit the scene using the structural-axis isometric convention."""
        self.plotter.view_vector(
            np.asarray(self._default_view_direction),
            viewup=self._default_view_up,
            render=False,
        )

    def _on_interaction(self, *_args) -> None:
        self._camera_interacting = True
        self._schedule_label_sync()
        self._orientation_widget.sync_from_camera()

    def _on_interaction_end(self, *_args) -> None:
        self._camera_interacting = False
        self._update_zoom_dependent_sizes()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _sync_labels(self) -> None:
        self._label_overlay.sync(self.plotter.renderer)

    def _on_camera_modified(self, *_args) -> None:
        self._schedule_label_sync()

    def _reference_plane_levels(self) -> tuple[float, ...]:
        values = {0.0}
        axis_name = {"XY": "Z", "XZ": "X", "YZ": "Y"}[self._reference_plane_mode]
        values.update(float(axis.value) for axis in self._model.axes.get(axis_name, ()))
        return tuple(sorted(values))

    def _reference_plane_for_model(self, model: StructuralModel, preferred: float | None = None) -> float:
        values = {0.0}
        axis_name = {"XY": "Z", "XZ": "X", "YZ": "Y"}[self._reference_plane_mode]
        values.update(float(axis.value) for axis in model.axes.get(axis_name, ()))
        levels = tuple(sorted(values))
        reference = self._reference_plane_z if preferred is None else preferred
        return min(levels, key=lambda level: abs(level - reference))

    def _schedule_label_sync(self) -> None:
        if not self._label_timer.isActive():
            self._label_timer.start()

    def _update_zoom_dependent_sizes(self) -> None:
        current = self._current_parallel_scale()
        reference = self._zoom_reference_parallel_scale
        if current is None or reference is None:
            return
        zoom_factor = reference / current
        for actor in (self._member_line_actor, self._member_fallback_actor):
            if actor is not None:
                actor.GetProperty().SetLineWidth(4.0 * zoom_factor)

    def _current_parallel_scale(self) -> float | None:
        camera = self.plotter.renderer.GetActiveCamera()
        if not camera.GetParallelProjection():
            return None
        scale = float(camera.GetParallelScale())
        return scale if scale > 0 else None

    def _camera_state(self):
        camera = self.plotter.renderer.GetActiveCamera()
        return (
            tuple(camera.GetPosition()), tuple(camera.GetFocalPoint()),
            tuple(camera.GetViewUp()), float(camera.GetParallelScale()),
        )

    def _restore_camera(self, state) -> None:
        position, focal_point, view_up, parallel_scale = state
        camera = self.plotter.renderer.GetActiveCamera()
        camera.SetPosition(*position)
        camera.SetFocalPoint(*focal_point)
        camera.SetViewUp(*view_up)
        camera.SetParallelScale(parallel_scale)
        camera.OrthogonalizeViewUp()

    def _validate_selection(self) -> None:
        if self._selected is None:
            return
        kind, name = self._selected
        collection = self._model.nodes if kind == "node" else self._model.bars
        if name not in collection:
            self._selected = None

    def _has_scene(self) -> bool:
        return any((self._member_line_actor, self._member_face_actor, self._node_actor))

    def _clear_actor_references(self) -> None:
        self._grid_actor = None
        self._reference_axes_actor = None
        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._node_actor = None
        self._support_actor = None
        self._release_actor = None
        self._local_axis_actors = []
        self._action_actors = []
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels = ()
        self._pick_sources.clear()
        self._highlight_actors.clear()
        self._member_batch = None
        self._node_batch = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_orientation_widget"):
            self._label_overlay.resize_to_parent()
            self._sync_labels()
            self._orientation_widget.resize()
            self._orientation_widget.sync_from_camera()
            self._update_zoom_dependent_sizes()

    def _node_marker_radius(self) -> float:
        return self._marker_radius_current

    @staticmethod
    def _marker_radius(_positions: np.ndarray) -> float:
        return 0.05
