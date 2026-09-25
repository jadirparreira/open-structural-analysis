"""Interactive PyVista scene backed by batched VTK geometry."""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from pyvistaqt import QtInteractor

from osa.model import StructuralModel

from .action_renderer import ActionRenderer
from .batched_renderer import (
    BatchedMemberRenderer,
    BatchedNodeRenderer,
    BatchedRigidBarRenderer,
    MemberBatch,
    NodeBatch,
)
from .grid_renderer import GridRenderer
from .label_overlay import LabelOverlay, project_world_to_screen
from .navigation_widget import NavigationWidget
from .reference_axes_renderer import ReferenceAxesRenderer
from .result_renderer import ResultRenderer


class StructureScene(QWidget):
    """Render the full model with a small, stable number of VTK actors."""

    element_clicked = Signal(str, str, object)
    empty_clicked = Signal()
    # The wireframe member and local-axis strokes are intentionally separate:
    # they may be tuned independently while remaining visually lightweight.
    _member_line_width = 1.5
    _local_axis_line_width = 1.0
    _rigid_bar_line_width = 2.0
    _hover_highlight_padding = 2.0
    _selected_highlight_padding = 3.0
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
        self.plotter.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.plotter.installEventFilter(self)
        self.plotter.set_background("#ffffff")
        self.plotter.enable_parallel_projection()

        self._grid_renderer = GridRenderer()
        self._reference_axes_renderer = ReferenceAxesRenderer()
        self._member_renderer = BatchedMemberRenderer()
        self._node_renderer = BatchedNodeRenderer()
        self._rigid_bar_renderer = BatchedRigidBarRenderer()
        self._action_renderer = ActionRenderer()
        self._result_renderer = ResultRenderer()
        self._label_overlay = LabelOverlay(self.plotter)
        self._orientation_widget = NavigationWidget.create(self.plotter)
        self._model = StructuralModel()
        self._member_batch: MemberBatch | None = None
        self._node_batch: NodeBatch | None = None
        self._rigid_bar_names: tuple[str, ...] = ()
        self._rigid_bar_mesh: pv.PolyData | None = None

        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._rigid_bar_actor = None
        self._grid_actor = None
        self._reference_axes_actor = None
        self._node_actor = None
        self._support_actor = None
        self._release_actor = None
        self._local_axis_actors: list[object] = []
        self._action_actors: list[object] = []
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels: tuple[str, ...] = ()
        self._result_actors: list[object] = []
        self._result_line_widths: list[tuple[object, float]] = []
        self._result_label_positions = np.empty((0, 3), dtype=float)
        self._result_labels: tuple[str, ...] = ()
        self._active_load_case: str | None = None
        self._actions_visible = False
        self._analysis_visible = False
        self._active_analysis_combination: str | None = None
        self._active_result_type = "Normal"
        self._action_visibility = {
            "node_forces": True,
            "node_moments": True,
            "member_forces": True,
            "member_moments": True,
        }
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
        self._tab_hover_candidates: list[tuple[str, str]] = []
        self._tab_hover_position: tuple[int, int] | None = None
        self._pointer_position: tuple[float, float] | None = None
        self._marker_radius_current = 0.05
        self._reference_plane_mode = "XY"
        self._reference_plane_z = 0.0
        self._marker_radius_locked = False
        self._zoom_reference_parallel_scale: float | None = None
        self._camera_interacting = False

        self._solid_picker = vtk.vtkCellPicker()
        self._solid_picker.SetTolerance(0.0005)
        self._solid_picker.PickFromListOn()
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
        self._navigation_viewport_timer = QTimer(self)
        self._navigation_viewport_timer.setSingleShot(True)
        self._navigation_viewport_timer.timeout.connect(self._sync_navigation_viewport)
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
        self._rigid_bar_names, self._rigid_bar_mesh = self._rigid_bar_renderer.build(model)
        self._add_rigid_bar_batch()
        self._add_member_batches()
        self._add_node_batches()
        self._add_actions()
        self._add_results()
        self._add_labels()
        self._apply_representation_visibility()
        self._configure_solid_picker()
        self._sync_highlights()

        if preserve_camera and camera_state is not None:
            self._restore_camera(camera_state)
        else:
            self._set_default_isometric_view()
        # Keep the zoom reference when rebuilding an existing scene.  Toggling
        # the Ações palette rebuilds the actors while preserving the camera;
        # replacing the reference here would reset the line-width multiplier
        # and make members/axes visibly change thickness for one rebuild.
        if not preserve_camera or self._zoom_reference_parallel_scale is None:
            self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _add_member_batches(self) -> None:
        batch = self._member_batch
        if batch is None:
            return
        self._member_line_actor = self._add_colored_mesh(
            batch.lines, "batch:member-lines", line_width=self._member_line_width,
            render_lines_as_tubes=True, lighting=False,
        )
        self._member_fallback_actor = self._add_colored_mesh(
            batch.fallback_lines, "batch:member-fallback", line_width=self._member_line_width,
            render_lines_as_tubes=True, lighting=False,
        )
        self._member_face_actor = self._add_colored_mesh(
            batch.faces, "batch:member-faces", smooth_shading=False, lighting=True,
        )
        if self._member_face_actor is not None:
            prop = self._member_face_actor.GetProperty()
            prop.SetEdgeVisibility(False)
            prop.SetInterpolationToFlat()
            prop.SetSpecular(0.12)
        self._member_edge_actor = self._add_colored_mesh(
            batch.edges, "batch:member-edges", line_width=1.5, lighting=False,
        )
        if self._member_edge_actor is not None:
            self._member_edge_actor.SetPickable(False)
            edge_mapper = self._member_edge_actor.GetMapper()
            # Bring contour lines in front of coincident profile faces. This
            # prevents an edge from disappearing when another solid touches
            # the same face, without changing the analytical geometry.
            edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()
            edge_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            edge_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        for mesh, color in zip(batch.axes, self._axis_colors):
            if not mesh.n_cells:
                continue
            actor = self.plotter.add_mesh(
                mesh, color=color, line_width=self._local_axis_line_width, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
                lighting=False,
            )
            axis_mapper = actor.GetMapper()
            # Local axes are an analytical overlay: keep them visible over
            # coincident solid faces, just as the profile contour lines are.
            # The relative offset only affects depth ties and does not alter
            # the axis geometry or the picking order of structural elements.
            axis_mapper.SetResolveCoincidentTopologyToPolygonOffset()
            axis_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            axis_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
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
            self._node_actor = self._add_colored_mesh(
                batch.geometry, "batch:nodes", smooth_shading=True,
            )
        if batch.supports.n_cells:
            self._support_actor = self.plotter.add_mesh(
                batch.supports, color="#a8b0b9", edge_color="#6e7781",
                show_edges=True, line_width=1.5, pickable=False,
                reset_camera=False, render=False,
            )
            self._support_actor.SetVisibility(self._node_supports_visible)

    def _add_rigid_bar_batch(self) -> None:
        mesh = self._rigid_bar_mesh
        if mesh is None or not mesh.n_cells:
            return
        self._rigid_bar_actor = self.plotter.add_mesh(
            mesh, color=BatchedRigidBarRenderer.COLOR, line_width=self._rigid_bar_line_width,
            pickable=False, reset_camera=False, render=False, render_lines_as_tubes=True,
            lighting=False,
        )
        rigid_mapper = self._rigid_bar_actor.GetMapper()
        # Rigid bars share the members' depth level. They must not receive a
        # special foreground/background offset when crossing a member or node.
        rigid_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(0.0, 0.0)

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

    def _add_results(self) -> None:
        if not self._analysis_visible or self._active_analysis_combination is None:
            self._result_actors = []
            self._result_line_widths = []
            self._result_label_positions = np.empty((0, 3), dtype=float)
            self._result_labels = ()
            return
        result = next(
            (
                item for item in self._model.analysis_results
                if item.load_reference == self._active_analysis_combination
                and item.model_revision == self._model.revision
            ),
            None,
        )
        self._result_actors, self._result_label_positions, self._result_labels = self._result_renderer.render(
            self.plotter, self._model, result, self._active_result_type,
            solid_members_visible=self._solid_members_visible,
        )
        self._result_line_widths = []
        if self._active_result_type.startswith("Deformação") and self._result_actors:
            # Primeiro ator é sempre a referência indeformada tracejada.
            self._result_line_widths.append((self._result_actors[0], 1.0))
            if not self._solid_members_visible and len(self._result_actors) > 1:
                self._result_line_widths.append((self._result_actors[1], 2.0))

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
        self._label_overlay.set_group(
            "result", self._result_label_positions, self._result_labels, visible=self._analysis_visible,
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

    def _pick(self) -> tuple[str, str] | None:
        candidates = self._pick_candidates()
        return candidates[0] if candidates else None

    def _pick_candidates(self) -> list[tuple[str, str]]:
        candidates = self._screen_pick_candidates()
        solid = self._pick_solid_member()
        if solid is None:
            return candidates
        if solid in candidates:
            candidates.remove(solid)
        # A node marker is deliberately more specific than a member surface
        # at a joint. Everywhere else, the visible solid face has priority
        # over the analytical centreline.
        insert_at = 1 if candidates and candidates[0][0] == "node" else 0
        candidates.insert(insert_at, solid)
        return candidates

    def _configure_solid_picker(self) -> None:
        self._solid_picker.InitializePickList()
        actor = self._member_face_actor
        deformation_active = self._analysis_visible and self._active_result_type.startswith("Deformação")
        enabled = actor is not None and self._solid_members_visible and not deformation_active
        if actor is not None:
            actor.SetPickable(enabled)
        if enabled:
            self._solid_picker.AddPickList(actor)

    @staticmethod
    def _qt_to_vtk_position(
        pointer: tuple[float, float],
        widget_size: tuple[int, int],
        render_size: tuple[int, int],
    ) -> tuple[float, float]:
        """Map Qt logical pixels to the current VTK render-buffer pixels."""
        widget_width, widget_height = widget_size
        render_width, render_height = render_size
        if widget_width <= 1 or widget_height <= 1:
            return 0.0, 0.0
        x = min(max(pointer[0], 0.0), float(widget_width - 1))
        y = min(max(pointer[1], 0.0), float(widget_height - 1))
        return (
            x * float(max(render_width - 1, 0)) / float(widget_width - 1),
            (float(widget_height - 1) - y)
            * float(max(render_height - 1, 0)) / float(widget_height - 1),
        )

    def _pick_solid_member(self) -> tuple[str, str] | None:
        batch = self._member_batch
        actor = self._member_face_actor
        if (
            self._pointer_position is None
            or batch is None
            or actor is None
            or not actor.GetVisibility()
            or not actor.GetPickable()
        ):
            return None
        x, y = self._qt_to_vtk_position(
            self._pointer_position,
            (self.plotter.width(), self.plotter.height()),
            tuple(self.plotter.render_window.GetSize()),
        )
        if not self._solid_picker.Pick(x, y, 0.0, self.plotter.renderer):
            return None
        if self._solid_picker.GetActor() is not actor:
            return None
        cell_id = self._solid_picker.GetCellId()
        if cell_id < 0 or cell_id >= batch.faces.n_cells:
            return None
        element_index = int(batch.faces.cell_data["element_index"][cell_id])
        if element_index < 0 or element_index >= len(batch.names):
            return None
        return "bar", batch.names[element_index]

    @staticmethod
    def _distance_to_segment_2d(
        point: np.ndarray, start: np.ndarray, end: np.ndarray,
    ) -> float:
        delta = end - start
        length_squared = float(np.dot(delta, delta))
        if length_squared <= 1e-12:
            return float(np.linalg.norm(point - start))
        fraction = float(np.dot(point - start, delta) / length_squared)
        fraction = min(1.0, max(0.0, fraction))
        projection = start + delta * fraction
        return float(np.linalg.norm(point - projection))

    def _screen_pick_candidates(self) -> list[tuple[str, str]]:
        """Find selectable model elements in the same Qt coordinate space as the cursor.

        ``vtkCellPicker`` receives render-window pixels, while Qt reports
        logical widget pixels.  During the creation of a frameless OpenGL
        window those spaces may briefly diverge.  Projecting with the active
        camera directly into the Qt widget's dimensions avoids that stale
        viewport conversion and keeps selection attached to what is drawn.
        """
        if self._pointer_position is None:
            return []
        cursor = np.asarray(self._pointer_position, dtype=float)
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        vtk_matrix = camera.GetCompositeProjectionTransformMatrix(
            renderer.GetTiledAspectRatio(), -1.0, 1.0,
        )
        matrix = np.asarray([
            [vtk_matrix.GetElement(row, column) for column in range(4)]
            for row in range(4)
        ])

        node_names = tuple(self._model.nodes)
        node_positions = np.asarray([
            (
                self._model.nodes[name].x,
                self._model.nodes[name].y,
                self._model.nodes[name].z,
            )
            for name in node_names
        ], dtype=float).reshape((-1, 3))
        screen_positions, within_depth = project_world_to_screen(
            node_positions, matrix, self.plotter.width(), self.plotter.height(),
            clip_to_viewport=False,
        )
        width = float(self.plotter.width())
        height = float(self.plotter.height())
        on_screen = (
            within_depth
            & (screen_positions[:, 0] >= 0.0)
            & (screen_positions[:, 0] <= width)
            & (screen_positions[:, 1] >= 0.0)
            & (screen_positions[:, 1] <= height)
        )
        projected_nodes = {
            name: (screen_positions[index], bool(within_depth[index]), bool(on_screen[index]))
            for index, name in enumerate(node_names)
        }

        candidates: list[tuple[float, tuple[str, str]]] = []
        node_tolerance = 12.0
        member_tolerance = 10.0
        for name in node_names:
            display, _within_depth, visible = projected_nodes[name]
            if not visible:
                continue
            distance = float(np.linalg.norm(cursor - display))
            if distance <= node_tolerance:
                candidates.append((distance, ("node", name)))

        for kind, elements in (("bar", self._model.bars), ("rigid_bar", self._model.rigid_bars)):
            for name, element in elements.items():
                start_projection = projected_nodes.get(element.start_node)
                end_projection = projected_nodes.get(element.end_node)
                if start_projection is None or end_projection is None:
                    continue
                start, start_within_depth, _start_on_screen = start_projection
                end, end_within_depth, _end_on_screen = end_projection
                if not start_within_depth or not end_within_depth:
                    continue
                distance = self._distance_to_segment_2d(cursor, start, end)
                if distance <= member_tolerance:
                    candidates.append((distance, (kind, name)))
        candidates.sort(key=lambda item: item[0])
        return [candidate for _distance, candidate in candidates]

    def _hover_candidates_near_cursor(self) -> list[tuple[str, str]]:
        return self._pick_candidates()

    def _cycle_hover(self) -> None:
        if self._camera_interacting:
            return
        self._hover_timer.stop()
        x, y = self.plotter.iren.get_event_position()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        position = (int(x), int(y))
        if position != self._tab_hover_position:
            self._tab_hover_candidates = self._hover_candidates_near_cursor()
            self._tab_hover_position = position
        if not self._tab_hover_candidates:
            return
        if self._hovered in self._tab_hover_candidates:
            index = self._tab_hover_candidates.index(self._hovered)
            index = (index + 1) % len(self._tab_hover_candidates)
        else:
            index = 0
        self._hovered = self._tab_hover_candidates[index]
        self._sync_highlights()
        self.plotter.render()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.plotter and event.type() == QEvent.Type.Resize:
            self._schedule_navigation_viewport_sync()
        if watched is self.plotter and event.type() in (
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
        ):
            point = event.position()
            self._pointer_position = point.x(), point.y()
            self._orientation_widget.set_qt_pointer_position(point.x(), point.y())
        if (
            watched is self.plotter
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Tab
        ):
            self._cycle_hover()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_navigation_viewport_sync()

    def _on_mouse_move(self, *_args) -> None:
        if self._camera_interacting:
            return
        x, y = self.plotter.iren.get_event_position()
        position = (int(x), int(y))
        if position != self._tab_hover_position:
            self._tab_hover_candidates = []
            self._tab_hover_position = None
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
        position = (int(x), int(y))
        picked = (
            self._hovered
            if position == self._tab_hover_position
            and self._hovered in self._tab_hover_candidates
            else self._pick()
        )
        self._selected = picked
        self._sync_highlights()
        self.plotter.render()
        if picked is None:
            self.empty_clicked.emit()
            return
        kind, name = picked
        self.element_clicked.emit(kind, name, self.element_center(kind, name))

    def _sync_highlights(self) -> None:
        self._reset_node_highlight_colors()
        self._replace_highlight("selected", self._selected, "#0969da")
        hover = None if self._hovered == self._selected else self._hovered
        hover_color = "#4b5563" if hover is not None and hover[0] == "node" else "#24292f"
        self._replace_highlight("hover", hover, hover_color)

    def _replace_highlight(
        self, slot: str, target: tuple[str, str] | None, color: str,
    ) -> None:
        previous = self._highlight_actors.pop(slot, None)
        if previous is not None:
            self.plotter.remove_actor(previous, reset_camera=False, render=False)
        if target is None:
            return
        kind, name = target
        if kind == "node" and slot == "hover":
            self._set_node_highlight_color(name, color)
            return
        if kind in {"bar", "rigid_bar"}:
            mesh = self._member_highlight_mesh(name)
            if mesh is None or not mesh.n_cells:
                return
            actor = self.plotter.add_mesh(
                mesh, color=color, line_width=self._highlight_line_width(slot, kind),
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

    def _reset_node_highlight_colors(self) -> None:
        batch = self._node_batch
        if batch is None or not batch.geometry.n_cells:
            return
        values = batch.geometry.cell_data.get("rgb")
        if values is None:
            return
        values[...] = np.asarray(pv.Color("#000000").int_rgb, dtype=np.uint8)
        batch.geometry.cell_data["rgb"] = values
        batch.geometry.GetCellData().Modified()
        batch.geometry.Modified()

    def _set_node_highlight_color(self, name: str, color: str) -> None:
        batch = self._node_batch
        if batch is None or name not in batch.names:
            return
        values = batch.geometry.cell_data.get("rgb")
        indices = batch.geometry.cell_data.get("element_index")
        if values is None or indices is None:
            return
        values[np.asarray(indices) == batch.names.index(name)] = np.asarray(
            pv.Color(color).int_rgb, dtype=np.uint8,
        )
        batch.geometry.cell_data["rgb"] = values
        batch.geometry.GetCellData().Modified()
        batch.geometry.Modified()

    def _highlight_line_width(self, slot: str, kind: str = "bar") -> float:
        """Return a stroke wider than the representation currently visible.

        Member strokes are scaled after camera zoom.  A fixed-width hover
        actor could therefore be completely covered when the camera is close
        to a member.  Reading the active actor width keeps the highlight on
        top at every zoom level while preserving the separate solid/line
        representations.
        """
        if kind == "rigid_bar":
            reference_actor = self._rigid_bar_actor
            fallback = self._rigid_bar_line_width
        elif self._solid_members_visible:
            # Valid solid members are represented by the contour batch; a
            # member without a valid section remains a visible fallback line.
            reference_actor = (
                self._member_fallback_actor
                or self._member_edge_actor
                or self._member_line_actor
            )
            fallback = self._member_line_width if self._member_fallback_actor else 1.5
        else:
            reference_actor = self._member_line_actor or self._member_fallback_actor
            fallback = self._member_line_width
        width = fallback
        if reference_actor is not None:
            width = float(reference_actor.GetProperty().GetLineWidth())
        padding = (
            self._selected_highlight_padding
            if slot == "selected" else self._hover_highlight_padding
        )
        return max(1.0, width + padding)

    def _member_highlight_mesh(self, name: str) -> pv.PolyData | None:
        member = self._model.bars.get(name)
        if member is not None:
            if self._solid_members_visible and self._member_batch is not None:
                outline = self._member_batch.outlines.get(name)
                if outline is not None:
                    return outline
            start = self._model.nodes[member.start_node]
            end = self._model.nodes[member.end_node]
            return pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z))
        rigid = self._model.rigid_bars.get(name)
        if rigid is None:
            return None
        start = self._model.nodes[rigid.start_node]
        end = self._model.nodes[rigid.end_node]
        return pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z))

    def _apply_representation_visibility(self) -> None:
        deformation_active = self._analysis_visible and self._active_result_type.startswith("Deformação")
        solid = self._solid_members_visible and not deformation_active
        if self._member_line_actor is not None:
            self._member_line_actor.SetVisibility(not solid and not deformation_active)
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
        if self._analysis_visible and self._active_result_type.startswith("Deformação"):
            self.render_model(self._model)
        self._configure_solid_picker()
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

    def set_analysis_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._analysis_visible:
            return
        self._analysis_visible = visible
        self.render_model(self._model)

    def set_analysis_result(self, combination: str | None, result_type: str) -> None:
        combination = combination or None
        if combination == self._active_analysis_combination and result_type == self._active_result_type:
            return
        self._active_analysis_combination = combination
        self._active_result_type = result_type
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

    def update_rigid_bar_name(self, old_name: str, new_name: str) -> None:
        """Refresh a renamed rigid bar without losing its scene selection."""
        if self._selected == ("rigid_bar", old_name):
            self._selected = "rigid_bar", new_name
        if self._hovered == ("rigid_bar", old_name):
            self._hovered = "rigid_bar", new_name
        self.render_model(self._model)

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
        element = (
            self._model.bars.get(name)
            if kind == "bar" else self._model.rigid_bars.get(name)
        )
        if element is None:
            raise KeyError(name)
        start = self._model.nodes[element.start_node]
        end = self._model.nodes[element.end_node]
        return (
            (start.x + end.x) / 2.0,
            (start.y + end.y) / 2.0,
            (start.z + end.z) / 2.0,
        )

    def reset_camera(self) -> None:
        self.plotter.reset_camera()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def view_isometric(self) -> None:
        self._set_default_isometric_view()
        self._update_depth_overlays()
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
        self._update_depth_overlays()
        self._sync_labels()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _sync_labels(self) -> None:
        self._label_overlay.sync(self.plotter.renderer)

    def _on_camera_modified(self, *_args) -> None:
        self._update_depth_overlays()
        self._schedule_label_sync()

    def _update_depth_overlays(self) -> None:
        """Move analytical axis strokes slightly toward the active camera.

        The axes are batched into three actors, so one camera-facing offset is
        applied to each actor.  This reproduces the previous per-member
        overlay behavior while avoiding one actor per member.
        """
        if not self._local_axis_actors:
            return
        camera = self.plotter.renderer.GetActiveCamera()
        direction = np.asarray(camera.GetPosition(), dtype=float) - np.asarray(
            camera.GetFocalPoint(), dtype=float,
        )
        length = float(np.linalg.norm(direction))
        if length <= 1e-12:
            return
        direction /= length
        offset = direction * (self._marker_radius_current * 0.25)
        for actor in self._local_axis_actors:
            actor.SetPosition(*offset)

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
                actor.GetProperty().SetLineWidth(self._member_line_width * zoom_factor)
        if self._rigid_bar_actor is not None:
            self._rigid_bar_actor.GetProperty().SetLineWidth(self._rigid_bar_line_width * zoom_factor)
        for actor in self._local_axis_actors:
            actor.GetProperty().SetLineWidth(self._local_axis_line_width * zoom_factor)
        for actor, width in self._result_line_widths:
            actor.GetProperty().SetLineWidth(width * zoom_factor)
        highlight_targets = {"selected": self._selected, "hover": self._hovered}
        for slot, actor in self._highlight_actors.items():
            if actor is not None and slot in {"selected", "hover"}:
                target = highlight_targets.get(slot)
                kind = target[0] if target is not None else "bar"
                actor.GetProperty().SetLineWidth(self._highlight_line_width(slot, kind))

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
        collection = (
            self._model.nodes if kind == "node"
            else self._model.bars if kind == "bar"
            else self._model.rigid_bars
        )
        if name not in collection:
            self._selected = None

    def _has_scene(self) -> bool:
        return any((self._member_line_actor, self._member_face_actor, self._rigid_bar_actor, self._node_actor))

    def _clear_actor_references(self) -> None:
        self._grid_actor = None
        self._reference_axes_actor = None
        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._rigid_bar_actor = None
        self._node_actor = None
        self._support_actor = None
        self._release_actor = None
        self._local_axis_actors = []
        self._action_actors = []
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels = ()
        self._result_actors = []
        self._result_label_positions = np.empty((0, 3), dtype=float)
        self._result_labels = ()
        self._solid_picker.InitializePickList()
        self._highlight_actors.clear()
        self._member_batch = None
        self._node_batch = None
        self._rigid_bar_names = ()
        self._rigid_bar_mesh = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_orientation_widget"):
            self._label_overlay.resize_to_parent()
            self._sync_labels()
            self._orientation_widget.resize()
            self._orientation_widget.sync_from_camera()
            self._update_zoom_dependent_sizes()
            self._schedule_navigation_viewport_sync()

    def _schedule_navigation_viewport_sync(self) -> None:
        """Wait for QtInteractor.resizeGL before sizing the VTK overlay."""
        if not self._navigation_viewport_timer.isActive():
            self._navigation_viewport_timer.start(0)

    def _sync_navigation_viewport(self) -> None:
        if not self.plotter.isVisible():
            return
        self._orientation_widget.resize()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _node_marker_radius(self) -> float:
        return self._marker_radius_current

    @staticmethod
    def _marker_radius(_positions: np.ndarray) -> float:
        return 0.05
