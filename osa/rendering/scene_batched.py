"""Interactive PyVista scene backed by batched VTK geometry."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
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


class SnapMarker(QWidget):
    """Small blue marker identifying the active snap target in the viewport."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._kind = "grid"
        icon_root = Path(__file__).parents[1] / "resources" / "icons"
        self._renderers = {
            "grid": QSvgRenderer(str(icon_root / "hash.svg"), self),
            "endpoint": QSvgRenderer(str(icon_root / "square.svg"), self),
            "center": QSvgRenderer(str(icon_root / "triangle.svg"), self),
        }

    def set_kind(self, kind: str) -> None:
        if kind == self._kind:
            return
        self._kind = kind
        self.update()

    def paintEvent(self, event) -> None:
        del event
        rendered = QPixmap(self.size())
        rendered.fill(Qt.GlobalColor.transparent)
        renderer = self._renderers.get(self._kind, self._renderers["grid"])
        renderer_painter = QPainter(rendered)
        try:
            renderer_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            renderer.render(renderer_painter, QRectF(self.rect()))
        finally:
            renderer_painter.end()

        colored = QPixmap(self.size())
        colored.fill(QColor("#0969da"))
        color_painter = QPainter(colored)
        try:
            color_painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn
            )
            color_painter.drawPixmap(0, 0, rendered)
        finally:
            color_painter.end()

        painter = QPainter(self)
        try:
            painter.drawPixmap(0, 0, colored)
        finally:
            painter.end()


class StructureScene(QWidget):
    """Render the full model with a small, stable number of VTK actors."""

    element_clicked = Signal(str, str, object)
    empty_clicked = Signal()
    placement_point_clicked = Signal(object)
    # The wireframe member and local-axis strokes are intentionally separate:
    # they may be tuned independently while remaining visually lightweight.
    _member_line_width = 1.5
    _local_axis_line_width = 1.0
    _rigid_bar_line_width = 2.0
    _hover_highlight_padding = 2.0
    _selected_highlight_padding = 3.0
    _snap_tolerance_pixels = 14.0
    _placement_drag_tolerance_pixels = 4.0
    _perpendicular_guide_half_length = 5.0
    _perpendicular_snap_half_length = 10.0
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
        # Terrain style orbits around the focal point with a stable world-up
        # axis: horizontal dragging changes azimuth and vertical dragging
        # changes elevation, without the accumulated camera roll of VTK's
        # default trackball. This matches the architectural-model workflow.
        self._apply_revit_navigation_style()

        self._grid_renderer = GridRenderer()
        self._reference_axes_renderer = ReferenceAxesRenderer()
        self._member_renderer = BatchedMemberRenderer()
        self._node_renderer = BatchedNodeRenderer()
        self._rigid_bar_renderer = BatchedRigidBarRenderer()
        self._action_renderer = ActionRenderer()
        self._result_renderer = ResultRenderer()
        self._label_overlay = LabelOverlay(self.plotter)
        self._coordinate_readout = QFrame(self.plotter)
        self._coordinate_readout.setObjectName("coordinateReadout")
        self._coordinate_readout.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._coordinate_readout.setStyleSheet(
            "QFrame#coordinateReadout { background: rgba(246, 248, 250, 245); "
            "border: 1px solid #d0d7de; border-radius: 8px; }"
            "QLabel { color: #24292f; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; }"
            "QLabel#axisLabel { color: #57606a; font-weight: 600; }"
            "QLineEdit { color: #24292f; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; }"
        )
        coordinate_layout = QVBoxLayout(self._coordinate_readout)
        coordinate_layout.setContentsMargins(8, 6, 8, 6)
        coordinate_layout.setSpacing(1)
        self._coordinate_value_labels: list[QLineEdit] = []
        readout_value_width = 78
        for axis in "XYZ":
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            axis_label = QLabel(axis, self._coordinate_readout)
            axis_label.setObjectName("axisLabel")
            axis_label.setFixedWidth(10)
            axis_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(axis_label)
            value_label = QLineEdit("0.000 m", self._coordinate_readout)
            value_label.setObjectName("coordinateValue")
            value_label.setReadOnly(True)
            value_label.setFixedWidth(readout_value_width)
            value_label.installEventFilter(self)
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(value_label)
            coordinate_layout.addLayout(row)
            self._coordinate_value_labels.append(value_label)
        self._coordinate_readout.adjustSize()
        self._coordinate_readout.hide()
        self._angle_readout = QFrame(self.plotter)
        self._angle_readout.setObjectName("angleReadout")
        self._angle_readout.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._angle_readout.setStyleSheet(
            "QFrame#angleReadout { background: rgba(246, 248, 250, 245); "
            "border: 1px solid #d0d7de; border-radius: 8px; }"
            "QLabel { color: #24292f; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; }"
            "QLineEdit { color: #24292f; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; }"
        )
        angle_layout = QHBoxLayout(self._angle_readout)
        angle_layout.setContentsMargins(7, 4, 8, 4)
        angle_layout.setSpacing(3)
        angle_icon = QLabel(self._angle_readout)
        angle_icon.setPixmap(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "chevron-left.svg"))
            .pixmap(QSize(16, 16))
        )
        angle_layout.addWidget(angle_icon)
        self._angle_editor = QLineEdit("0.000°", self._angle_readout)
        self._angle_editor.setObjectName("angleValue")
        self._angle_editor.setReadOnly(True)
        self._angle_editor.setFixedWidth(readout_value_width)
        self._angle_editor.installEventFilter(self)
        self._angle_editor.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        angle_layout.addWidget(self._angle_editor)
        self._angle_readout.adjustSize()
        self._angle_readout.hide()
        self._equalize_readout_widths()
        self._snap_marker = SnapMarker(self.plotter)
        self._snap_marker.hide()
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
        self._member_preview_actor = None
        self._perpendicular_guide_actor = None
        self._orthogonal_guide_actor = None
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
        self._member_placement_mode = False
        self._node_placement_mode = False
        self._member_placement_press: tuple[float, float] | None = None
        self._member_preview_start: np.ndarray | None = None
        self._snap_enabled = True
        self._snap_types = {
            "grid": True,
            "endpoint": True,
            "center": True,
            "perpendicular": True,
            "orthogonal": True,
        }
        self._marker_radius_current = 0.05
        self._reference_plane_mode = "XY"
        self._reference_plane_z = 0.0
        self._marker_radius_locked = False
        self._zoom_reference_parallel_scale: float | None = None
        self._camera_interacting = False
        self._camera_initialized = False
        self._manual_edit_target: np.ndarray | None = None
        self._manual_edit_index: int | None = None
        self._manual_edit_confirmable = False
        self._last_display_position: np.ndarray | None = None

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
        # Selection is observed before the camera style.  Member placement is
        # finalized on mouse release in the Qt event filter, so a drag can
        # still use the normal Revit-like terrain orbit.
        self._left_click_observer_id = self.plotter.iren.interactor.AddObserver(
            "LeftButtonPressEvent", self._on_left_click, 1.0,
        )
        self.plotter.iren.add_observer("InteractionEvent", self._on_interaction)
        self.plotter.iren.add_observer("EndInteractionEvent", self._on_interaction_end)

    def render_model(self, model: StructuralModel, *, preserve_camera: bool = True) -> None:
        """Rebuild the model actors without changing the active view by default.

        ``preserve_camera`` is disabled only for explicit framing operations,
        such as opening a project or generating an initial preset structure.
        Regular commands, property edits, plane controls and graphical
        placement must never reframe the user's view.
        """
        self._rebuild_timer.stop()
        camera_state = self._camera_state()
        preserve_camera = bool(preserve_camera and self._camera_initialized)
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
            else:
                self._set_default_isometric_view()
            self._camera_initialized = True
            self.plotter.camera_set = True
            self.plotter.reset_camera_clipping_range()
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
        self._camera_initialized = True
        # ``_restore_camera`` writes the VTK camera directly. Tell PyVista
        # that this is an intentional camera configuration; otherwise its
        # first interactive render performs an automatic fit.
        self.plotter.camera_set = True
        # Rebuilding actors changes the bounds used by VTK's near/far planes.
        # Keep the camera pose untouched, but recalculate the clipping range so
        # newly added geometry is visible immediately instead of appearing only
        # after a zoom or orbit interaction.
        self.plotter.reset_camera_clipping_range()
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
        coordinate_editors = tuple(getattr(self, "_coordinate_value_labels", ()))
        angle_editor = getattr(self, "_angle_editor", None)
        if angle_editor is not None:
            coordinate_editors += (angle_editor,)
        if watched in coordinate_editors and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Tab:
                self._cycle_coordinate_edit()
                event.accept()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish_coordinate_edit()
                event.accept()
                return True
        if watched is self.plotter and event.type() == QEvent.Type.Resize:
            self._schedule_navigation_viewport_sync()
        if (
            watched is self.plotter
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._placement_active()
            and self._manual_edit_target is not None
            and self._manual_edit_index is None
            and self._manual_edit_confirmable
        ):
            self._emit_member_placement_point()
            event.accept()
            return True
        if watched is self.plotter and event.type() in (
            QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            if event.type() == QEvent.Type.MouseMove and self._manual_edit_target is not None:
                self._cancel_coordinate_edit()
            point = event.position()
            self._pointer_position = point.x(), point.y()
            self._orientation_widget.set_qt_pointer_position(point.x(), point.y())
            over_navigation_cube = self._orientation_widget.is_pointer_over(
                int(point.x()), int(point.y()),
            )
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._placement_active()
                and not over_navigation_cube
            ):
                # Keep a normal click for placement, but let VTK receive the
                # press.  If the pointer moves, Terrain handles it as an orbit
                # exactly as it does outside the drawing tool.
                self._member_placement_press = point.x(), point.y()
            elif (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                press_position = self._member_placement_press
                self._member_placement_press = None
                if (
                    self._placement_active()
                    and press_position is not None
                    and not over_navigation_cube
                    and np.hypot(point.x() - press_position[0], point.y() - press_position[1])
                    <= self._placement_drag_tolerance_pixels
                ):
                    # VTK must process the release before a model refresh.
                    # Deferring the emission prevents a click from replacing
                    # the active interactor style midway through its event.
                    QTimer.singleShot(0, self._emit_member_placement_point)
        if watched is self.plotter and event.type() == QEvent.Type.Leave:
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            self._snap_marker.hide()
            self._hide_member_preview()
            self._hide_orthogonal_guide()
        if (
            watched is self.plotter
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Tab
        ):
            if self._placement_active():
                self._cycle_coordinate_edit()
                event.accept()
                return True
            self._cycle_hover()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_navigation_viewport_sync()

    def _placement_active(self) -> bool:
        return self._member_placement_mode or self._node_placement_mode

    def _on_mouse_move(self, *_args) -> None:
        if self._camera_interacting:
            return
        self._update_coordinate_readout()
        if self._member_preview_start is not None:
            self.plotter.render()
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

    def set_member_placement_mode(self, active: bool) -> None:
        """Enable the coordinate readout used by graphical member placement."""
        self._member_placement_mode = bool(active)
        self._node_placement_mode = False
        self._set_point_placement_mode(active)

    def set_node_placement_mode(self, active: bool) -> None:
        """Enable the single-click graphical node-placement flow."""
        self._node_placement_mode = bool(active)
        self._member_placement_mode = False
        if active:
            self._member_preview_start = None
        self._set_point_placement_mode(active)

    def _set_point_placement_mode(self, active: bool) -> None:
        if not active:
            self._member_placement_press = None
            self._member_preview_start = None
            self._manual_edit_target = None
            self._manual_edit_index = None
            self._manual_edit_confirmable = False
            self._last_display_position = None
            for editor in (*self._coordinate_value_labels, self._angle_editor):
                editor.setReadOnly(True)
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            self._snap_marker.hide()
            self._hide_member_preview()
            self._hide_perpendicular_guide()
            self._hide_orthogonal_guide()
            return
        self._update_coordinate_readout()

    def set_member_preview_start(self, point: object | None) -> None:
        """Set the fixed 3D point from which the graphical preview begins."""
        self._member_preview_start = (
            None if point is None else np.asarray(tuple(point), dtype=float)
        )
        self._update_coordinate_readout()

    def set_snap_enabled(self, enabled: bool) -> None:
        """Enable or disable all graphical snap targets."""
        self._snap_enabled = bool(enabled)
        self._update_coordinate_readout()
        if self._member_preview_start is not None:
            self.plotter.render()

    def set_snap_type_enabled(self, snap_kind: str, enabled: bool) -> None:
        """Enable or disable one snap type without changing the master magnet."""
        if snap_kind not in self._snap_types:
            raise ValueError(f"Tipo de snap desconhecido: {snap_kind}")
        self._snap_types[snap_kind] = bool(enabled)
        self._update_coordinate_readout()
        if self._member_preview_start is not None:
            self.plotter.render()

    def snap_type_enabled(self, snap_kind: str) -> bool:
        """Return whether an individual snap type is enabled."""
        if snap_kind not in self._snap_types:
            raise ValueError(f"Tipo de snap desconhecido: {snap_kind}")
        return bool(self._snap_types[snap_kind])

    def _editable_coordinate_fields(self) -> list[QLineEdit]:
        fields = list(self._coordinate_value_labels)
        endpoint = (
            self._manual_edit_target
            if self._manual_edit_target is not None
            else self._last_display_position
        )
        if self._member_preview_start is not None and endpoint is not None:
            if self._preview_angle_degrees(endpoint) is not None:
                fields.append(self._angle_editor)
        return fields

    @staticmethod
    def _parse_editor_value(editor: QLineEdit) -> tuple[float, bool] | None:
        value = editor.text().strip().lower().replace("m", "").replace("°", "")
        relative = value.startswith("@")
        if relative:
            value = value[1:].strip()
        value = value.replace(",", ".")
        try:
            return float(value), relative
        except ValueError:
            return None

    def _commit_coordinate_editor(self, index: int) -> None:
        target = self._manual_edit_target
        if target is None:
            return
        editor = (
            self._angle_editor
            if index == 3 else self._coordinate_value_labels[index]
        )
        parsed = self._parse_editor_value(editor)
        if parsed is None:
            return
        value, relative = parsed
        if index < 3:
            if relative:
                if self._member_preview_start is None:
                    return
                value += float(self._member_preview_start[index])
            target[index] = value
            return
        if self._member_preview_start is None:
            return
        plane_axes = {
            "XY": (0, 1),
            "XZ": (0, 2),
            "YZ": (1, 2),
        }[self._reference_plane_mode]
        planar = target[list(plane_axes)] - self._member_preview_start[list(plane_axes)]
        planar_length = float(np.linalg.norm(planar))
        if planar_length <= 1e-9:
            return
        angle = np.radians(value)
        target[list(plane_axes)] = self._member_preview_start[list(plane_axes)] + (
            planar_length * np.asarray((np.cos(angle), np.sin(angle)))
        )

    def _cycle_coordinate_edit(self) -> None:
        if not self._placement_active():
            return
        if self._manual_edit_target is None:
            if self._last_display_position is None:
                self._update_coordinate_readout()
            if self._last_display_position is None:
                return
            self._manual_edit_target = self._last_display_position.copy()

        current = self._manual_edit_index
        if current is not None:
            self._commit_coordinate_editor(current)
        self._manual_edit_index = None
        self._manual_edit_confirmable = False
        self._update_coordinate_readout()
        fields = self._editable_coordinate_fields()
        if not fields:
            return
        indices = [
            self._coordinate_value_labels.index(field)
            if field in self._coordinate_value_labels else 3
            for field in fields
        ]
        next_position = 0 if current is None else (indices.index(current) + 1) % len(indices)
        next_index = indices[next_position]
        self._manual_edit_index = next_index
        editor = fields[next_position]
        editor.setReadOnly(False)
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        editor.selectAll()

    def _finish_coordinate_edit(self) -> None:
        if self._manual_edit_index is not None:
            self._commit_coordinate_editor(self._manual_edit_index)
        self._manual_edit_index = None
        self._manual_edit_confirmable = self._manual_edit_target is not None
        for editor in (*self._coordinate_value_labels, self._angle_editor):
            editor.setReadOnly(True)
        self.plotter.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_coordinate_readout()

    def _cancel_coordinate_edit(self, *, update: bool = True) -> None:
        self._manual_edit_target = None
        self._manual_edit_index = None
        self._manual_edit_confirmable = False
        for editor in (*self._coordinate_value_labels, self._angle_editor):
            editor.setReadOnly(True)
        if update:
            self._update_coordinate_readout()

    def _update_coordinate_readout(self) -> None:
        if not self._placement_active() or self._pointer_position is None:
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            self._snap_marker.hide()
            self._hide_member_preview()
            return

        x, y = self._pointer_position
        if self._orientation_widget.is_pointer_over(int(x), int(y)):
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            self._snap_marker.hide()
            self._hide_member_preview()
            return
        if self._manual_edit_target is not None:
            display_position = self._manual_edit_target.copy()
            snap_kind = None
        else:
            position = self._cursor_world_position()
            if position is None:
                self._coordinate_readout.hide()
                self._angle_readout.hide()
                self._snap_marker.hide()
                self._hide_member_preview()
                self._hide_perpendicular_guide()
                self._hide_orthogonal_guide()
                return
            display_position, snap_kind = self._placement_target(position)
        self._last_display_position = display_position.copy()
        snapped_position = (
            display_position
            if snap_kind in {"grid", "endpoint", "center"}
            else None
        )
        self._update_perpendicular_guide()
        self._update_orthogonal_guide()
        self._update_member_preview(display_position)
        angle = self._preview_angle_degrees(display_position)
        if angle is None:
            self._angle_readout.hide()
            self._angle_editor.setReadOnly(True)
            if self._manual_edit_index == 3:
                self._manual_edit_index = None
        else:
            if self._manual_edit_index != 3:
                self._angle_editor.setText(f"{angle:.3f}°")
                self._angle_editor.setReadOnly(True)
            self._angle_readout.adjustSize()
        if snapped_position is None:
            self._snap_marker.hide()
        else:
            self._position_snap_marker(snapped_position, snap_kind)
        coordinates = tuple(
            0.0 if abs(float(value)) < 0.0005 else float(value)
            for value in display_position
        )
        for index, (label, coordinate) in enumerate(zip(self._coordinate_value_labels, coordinates)):
            if self._manual_edit_index != index:
                label.setText(f"{coordinate:.3f} m")
        self._equalize_readout_widths()
        offset = 16
        readout_width = max(self._coordinate_readout.width(), self._angle_readout.width())
        angle_visible = angle is not None
        readout_height = self._coordinate_readout.height()
        if angle_visible:
            readout_height += 6 + self._angle_readout.height()
        left = x + offset
        top = y + offset
        if left + readout_width > self.plotter.width():
            left = x - readout_width - offset
        if top + readout_height > self.plotter.height():
            top = y - readout_height - offset
        self._coordinate_readout.move(
            max(0, min(int(left), self.plotter.width() - readout_width)),
            max(0, min(int(top), self.plotter.height() - readout_height)),
        )
        self._coordinate_readout.show()
        self._coordinate_readout.raise_()
        if angle_visible:
            self._angle_readout.move(
                max(0, min(int(left), self.plotter.width() - self._angle_readout.width())),
                max(0, min(
                    int(top + self._coordinate_readout.height() + 6),
                    self.plotter.height() - self._angle_readout.height(),
                )),
            )
            self._angle_readout.show()
            self._angle_readout.raise_()

    def _equalize_readout_widths(self) -> None:
        """Keep coordinate and angle readouts aligned as one visual stack."""
        maximum_width = 16_777_215
        for readout in (self._coordinate_readout, self._angle_readout):
            readout.setMinimumWidth(0)
            readout.setMaximumWidth(maximum_width)
            readout.adjustSize()
        width = max(
            self._coordinate_readout.sizeHint().width(),
            self._angle_readout.sizeHint().width(),
        )
        self._coordinate_readout.setFixedWidth(width)
        self._angle_readout.setFixedWidth(width)

    def _preview_angle_degrees(self, endpoint: np.ndarray) -> float | None:
        """Return the in-plane angle from the plane's global reference axis."""
        if self._member_preview_start is None:
            return None
        plane_axes = {
            "XY": (0, 1),
            "XZ": (0, 2),
            # Global X is the normal of YZ, so global Y is the meaningful
            # in-plane reference axis for that plane.
            "YZ": (1, 2),
        }[self._reference_plane_mode]
        delta = np.asarray(endpoint, dtype=float) - self._member_preview_start
        planar = delta[list(plane_axes)]
        if float(np.linalg.norm(planar)) <= 1e-9:
            return None
        angle = float(np.degrees(np.arctan2(planar[1], planar[0])))
        return angle % 360.0

    def _snap_position(self, position: np.ndarray) -> tuple[np.ndarray, str] | None:
        if not self._snap_enabled or self._pointer_position is None:
            return None
        candidates: list[tuple[float, int, str, np.ndarray]] = []

        # The grid is the construction plane's visible representation.  It
        # must not exert an invisible magnetic pull when the user turns the
        # plane off in the viewport palette.
        if self._snap_types["grid"] and self._grid_visible:
            grid_candidate = self._nearest_grid_candidate(position)
            if grid_candidate is not None:
                candidate, distance = grid_candidate
                candidates.append((distance, 2, "grid", candidate))

        if self._snap_types["endpoint"]:
            node_candidates = self._model.nodes.values()
        else:
            node_candidates = ()
        for node in node_candidates:
            candidate = np.asarray((node.x, node.y, node.z), dtype=float)
            screen, visible = self._world_to_screen(candidate)
            if not visible:
                continue
            distance = float(np.linalg.norm(screen - np.asarray(self._pointer_position)))
            candidates.append((distance, 0, "endpoint", candidate))

        member_candidates = self._model.bars.values() if self._snap_types["center"] else ()
        for member in member_candidates:
            start = self._model.nodes.get(member.start_node)
            end = self._model.nodes.get(member.end_node)
            if start is None or end is None:
                continue
            candidate = np.asarray(
                (
                    (start.x + end.x) / 2.0,
                    (start.y + end.y) / 2.0,
                    (start.z + end.z) / 2.0,
                ),
                dtype=float,
            )
            screen, visible = self._world_to_screen(candidate)
            if not visible:
                continue
            distance = float(np.linalg.norm(screen - np.asarray(self._pointer_position)))
            candidates.append((distance, 1, "center", candidate))

        candidates = [
            candidate for candidate in candidates
            if candidate[0] <= self._snap_tolerance_pixels
        ]
        if not candidates:
            return None
        _distance, _priority, kind, candidate = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        return candidate, kind

    def _snap_to_grid(self, position: np.ndarray) -> np.ndarray | None:
        """Return the nearest grid intersection for compatibility callers."""
        if not self._snap_enabled or not self._snap_types["grid"] or not self._grid_visible:
            return None
        candidate = self._nearest_grid_candidate(position)
        if candidate is None or candidate[1] > self._snap_tolerance_pixels:
            return None
        return candidate[0]

    def _nearest_grid_candidate(self, position: np.ndarray) -> tuple[np.ndarray, float] | None:
        if self._pointer_position is None:
            return None
        first_values, second_values, first_axis, second_axis = self._grid_intersection_axes()
        if not len(first_values) or not len(second_values):
            return None

        first_candidates = first_values[
            np.argsort(np.abs(first_values - position[first_axis]))[:2]
        ]
        second_candidates = second_values[
            np.argsort(np.abs(second_values - position[second_axis]))[:2]
        ]
        best_position = None
        best_distance = float("inf")
        for first_value in first_candidates:
            for second_value in second_candidates:
                candidate = np.asarray(position, dtype=float).copy()
                candidate[first_axis] = first_value
                candidate[second_axis] = second_value
                screen, visible = self._world_to_screen(candidate)
                if not visible:
                    continue
                distance = float(np.linalg.norm(screen - np.asarray(self._pointer_position)))
                if distance < best_distance:
                    best_position = candidate
                    best_distance = distance
        if best_position is None:
            return None
        return best_position, best_distance

    def _grid_intersection_axes(self) -> tuple[np.ndarray, np.ndarray, int, int]:
        points = np.asarray(self._grid_renderer.mesh.points, dtype=float)
        if not len(points):
            return np.empty(0), np.empty(0), 0, 1
        if self._reference_plane_mode == "XZ":
            return (
                np.unique(np.round(points[:, 0], decimals=9)),
                np.unique(np.round(points[:, 2], decimals=9)),
                0,
                2,
            )
        if self._reference_plane_mode == "YZ":
            return (
                np.unique(np.round(points[:, 1], decimals=9)),
                np.unique(np.round(points[:, 2], decimals=9)),
                1,
                2,
            )
        return (
            np.unique(np.round(points[:, 0], decimals=9)),
            np.unique(np.round(points[:, 1], decimals=9)),
            0,
            1,
        )

    def _position_snap_marker(self, position: np.ndarray, kind: str | None) -> None:
        screen, visible = self._world_to_screen(position)
        if not visible:
            self._snap_marker.hide()
            return
        self._snap_marker.set_kind(kind or "grid")
        self._snap_marker.move(
            int(round(float(screen[0]) - self._snap_marker.width() / 2.0)),
            int(round(float(screen[1]) - self._snap_marker.height() / 2.0)),
        )
        self._snap_marker.show()
        self._snap_marker.raise_()

    def _update_member_preview(self, endpoint: np.ndarray | None) -> None:
        start = self._member_preview_start
        if start is None or endpoint is None or not self._placement_active():
            self._hide_member_preview()
            return
        if float(np.linalg.norm(endpoint - start)) <= 1e-12:
            self._hide_member_preview()
            return
        mesh = pv.Line(tuple(start), tuple(endpoint))
        if self._member_preview_actor is None:
            self._member_preview_actor = self.plotter.add_mesh(
                mesh,
                color="#0969da",
                line_width=3.0,
                render_lines_as_tubes=True,
                lighting=False,
                pickable=False,
                reset_camera=False,
                render=False,
            )
            self._member_preview_actor.SetObjectName("member-preview")
        else:
            mapper = self._member_preview_actor.GetMapper()
            mapper.SetInputData(mesh)
            mapper.Modified()
        self._member_preview_actor.SetVisibility(True)

    def _hide_member_preview(self) -> None:
        if self._member_preview_actor is not None:
            self._member_preview_actor.SetVisibility(False)

    def _world_to_screen(self, position: np.ndarray) -> tuple[np.ndarray, bool]:
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        vtk_matrix = camera.GetCompositeProjectionTransformMatrix(
            renderer.GetTiledAspectRatio(), -1.0, 1.0,
        )
        matrix = np.asarray([
            [vtk_matrix.GetElement(row, column) for column in range(4)]
            for row in range(4)
        ])
        screen, visible = project_world_to_screen(
            np.asarray([position], dtype=float), matrix,
            self.plotter.width(), self.plotter.height(),
        )
        return screen[0], bool(visible[0])

    def _cursor_world_position(self) -> np.ndarray | None:
        pointer = self._pointer_position
        if pointer is None:
            return None
        x, y = self._qt_to_vtk_position(
            pointer,
            (self.plotter.width(), self.plotter.height()),
            tuple(self.plotter.render_window.GetSize()),
        )
        renderer = self.plotter.renderer
        near = self._display_to_world(renderer, x, y, 0.0)
        far = self._display_to_world(renderer, x, y, 1.0)
        if near is None or far is None:
            return None
        direction = far - near
        axis_index, offset = {
            "XY": (2, self._reference_plane_z),
            "XZ": (1, self._reference_plane_z),
            "YZ": (0, self._reference_plane_z),
        }[self._reference_plane_mode]
        denominator = float(direction[axis_index])
        if abs(denominator) <= 1e-12:
            return None
        intersection = near + direction * (
            (float(offset) - float(near[axis_index])) / denominator
        )
        return intersection

    @staticmethod
    def _display_to_world(renderer, x: float, y: float, z: float) -> np.ndarray | None:
        renderer.SetDisplayPoint(float(x), float(y), float(z))
        renderer.DisplayToWorld()
        world = renderer.GetWorldPoint()
        if world is None or abs(float(world[3])) <= 1e-12:
            return None
        return np.asarray(world[:3], dtype=float) / float(world[3])

    def _update_hover(self) -> None:
        if self._camera_interacting:
            return
        picked = self._pick()
        if picked == self._hovered:
            return
        self._hovered = picked
        self._sync_highlights()
        self.plotter.render()

    def _on_left_click(self, _caller, *_args) -> None:
        x, y = self.plotter.iren.get_event_position()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        if self._placement_active():
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

    def _placement_world_position(self) -> np.ndarray | None:
        if self._manual_edit_target is not None:
            return self._manual_edit_target.copy()
        position = self._cursor_world_position()
        if position is None:
            return None
        target, _snap_kind = self._placement_target(position)
        return target

    def _perpendicular_direction(self) -> np.ndarray:
        direction = np.zeros(3, dtype=float)
        direction[{"XY": 2, "XZ": 1, "YZ": 0}[self._reference_plane_mode]] = 1.0
        return direction

    def _perpendicular_guide_length(self) -> float:
        """Return the fixed five-unit length on each side of the first point."""
        return self._perpendicular_guide_half_length

    def _in_plane_directions(self) -> tuple[np.ndarray, np.ndarray]:
        directions = []
        for axis in {
            "XY": (0, 1),
            "XZ": (0, 2),
            "YZ": (1, 2),
        }[self._reference_plane_mode]:
            direction = np.zeros(3, dtype=float)
            direction[axis] = 1.0
            directions.append(direction)
        return directions[0], directions[1]

    def _line_snap_candidate(
        self, direction: np.ndarray,
    ) -> tuple[np.ndarray, float] | None:
        start = self._member_preview_start
        pointer = self._pointer_position
        if not self._snap_enabled or start is None or pointer is None:
            return None

        guide_length = self._perpendicular_guide_length()
        screen_start, visible_start = self._world_to_screen(start)
        if not visible_start:
            return None

        pointer_array = np.asarray(pointer, dtype=float)
        probe_length = max(guide_length * 0.25, 0.5)
        for sign in (1.0, -1.0):
            probe_end = start + direction * (probe_length * sign)
            screen_end, visible_end = self._world_to_screen(probe_end)
            if not visible_end:
                continue
            screen_direction = screen_end - screen_start
            length_squared = float(np.dot(screen_direction, screen_direction))
            if length_squared <= 1e-12:
                continue
            fraction = float(
                np.dot(pointer_array - screen_start, screen_direction) / length_squared
            )
            distance = probe_length * sign * fraction
            if abs(distance) > self._perpendicular_snap_half_length:
                continue
            closest = screen_start + fraction * screen_direction
            screen_distance = float(np.linalg.norm(pointer_array - closest))
            if screen_distance <= self._snap_tolerance_pixels:
                return start + direction * distance, screen_distance
        return None

    def _perpendicular_snap_target(self) -> np.ndarray | None:
        """Infer a point on the normal through the first point from the cursor."""
        if not self._snap_types["perpendicular"]:
            return None
        candidate = self._line_snap_candidate(self._perpendicular_direction())
        return candidate[0] if candidate is not None else None

    def _orthogonal_snap_target(self) -> np.ndarray | None:
        if not self._snap_types["orthogonal"]:
            return None
        candidates = [
            candidate
            for direction in self._in_plane_directions()
            if (candidate := self._line_snap_candidate(direction)) is not None
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[1])[0]

    def _placement_guide_target(self) -> tuple[np.ndarray, str] | None:
        candidates: list[tuple[float, np.ndarray, str]] = []
        if self._snap_types["perpendicular"]:
            perpendicular = self._line_snap_candidate(self._perpendicular_direction())
            if perpendicular is not None:
                candidates.append((perpendicular[1], perpendicular[0], "perpendicular"))
        if self._snap_types["orthogonal"]:
            for direction in self._in_plane_directions():
                candidate = self._line_snap_candidate(direction)
                if candidate is not None:
                    candidates.append((candidate[1], candidate[0], "orthogonal"))
        if not candidates:
            return None
        _distance, target, kind = min(candidates, key=lambda item: item[0])
        return target, kind

    def _update_perpendicular_guide(self) -> None:
        start = self._member_preview_start
        if (
            not self._placement_active()
            or not self._snap_enabled
            or not self._snap_types["perpendicular"]
            or start is None
        ):
            self._hide_perpendicular_guide()
            return
        direction = self._perpendicular_direction()
        length = self._perpendicular_guide_length()
        mesh = self._perpendicular_guide_mesh(start, direction, length)
        if self._perpendicular_guide_actor is None:
            self._perpendicular_guide_actor = self.plotter.add_mesh(
                mesh,
                scalars="rgba",
                rgb=True,
                line_width=1.0,
                pickable=False,
                reset_camera=False,
                render=False,
            )
            self._perpendicular_guide_actor.SetObjectName("perpendicular-guide")
            # QtInteractor can defer the first mapper input assignment for a
            # newly added RGBA line mesh.  Set it explicitly so the dashed
            # guide is available immediately, like the already-rendered grid.
            mapper = self._perpendicular_guide_actor.GetMapper()
            mapper.SetInputData(mesh)
            mapper.Modified()
        else:
            mapper = self._perpendicular_guide_actor.GetMapper()
            mapper.SetInputData(mesh)
            mapper.Modified()
        self._perpendicular_guide_actor.SetVisibility(True)

    def _update_orthogonal_guide(self) -> None:
        start = self._member_preview_start
        if (
            not self._placement_active()
            or not self._snap_enabled
            or not self._snap_types["orthogonal"]
            or start is None
        ):
            self._hide_orthogonal_guide()
            return
        mesh = self._orthogonal_guide_mesh(
            start, self._in_plane_directions(), self._perpendicular_guide_length(),
        )
        if self._orthogonal_guide_actor is None:
            self._orthogonal_guide_actor = self.plotter.add_mesh(
                mesh,
                scalars="rgba",
                rgb=True,
                line_width=1.0,
                pickable=False,
                reset_camera=False,
                render=False,
            )
            self._orthogonal_guide_actor.SetObjectName("orthogonal-guide")
        mapper = self._orthogonal_guide_actor.GetMapper()
        mapper.SetInputData(mesh)
        mapper.Modified()
        self._orthogonal_guide_actor.SetVisibility(True)

    @staticmethod
    def _perpendicular_guide_mesh(
        start: np.ndarray, direction: np.ndarray, length: float,
    ) -> pv.PolyData:
        """Build a faded dashed guide in the construction-grid style."""
        dash_length = max(length / 18.0, 0.15)
        gap_length = dash_length * 0.65
        points: list[np.ndarray] = []
        lines: list[list[int]] = []
        alphas: list[int] = []
        cursor = -length
        while cursor < length - 1e-9:
            dash_end = min(cursor + dash_length, length)
            first_index = len(points)
            for coordinate in (cursor, dash_end):
                points.append(start + direction * coordinate)
                fade = max(0.0, 1.0 - abs(coordinate) / length)
                alphas.append(int(round(fade * 255.0)))
            lines.append([2, first_index, first_index + 1])
            cursor += dash_length + gap_length

        # Ensure the visible guide reaches exactly five units on the positive
        # side even when the dash/gap cadence does not land on the endpoint.
        final_start = max(-length, length - dash_length)
        first_index = len(points)
        for coordinate in (final_start, length):
            points.append(start + direction * coordinate)
            fade = max(0.0, 1.0 - abs(coordinate) / length)
            alphas.append(int(round(fade * 255.0)))
        lines.append([2, first_index, first_index + 1])

        mesh = pv.PolyData(
            np.asarray(points, dtype=float),
            lines=np.asarray(lines, dtype=np.int64).ravel(),
        )
        rgba = np.empty((len(points), 4), dtype=np.uint8)
        rgba[:, :3] = np.asarray(GridRenderer._color, dtype=np.uint8)
        rgba[:, 3] = np.asarray(alphas, dtype=np.uint8)
        mesh.point_data["rgba"] = rgba
        return mesh

    @staticmethod
    def _orthogonal_guide_mesh(
        start: np.ndarray, directions: tuple[np.ndarray, np.ndarray], length: float,
    ) -> pv.PolyData:
        """Build the two solid, faded guides lying on the active plane."""
        points: list[np.ndarray] = []
        lines: list[list[int]] = []
        alphas: list[int] = []
        for direction in directions:
            first_index = len(points)
            for coordinate in (-length, 0.0, length):
                points.append(start + direction * coordinate)
                fade = max(0.0, 1.0 - abs(coordinate) / length)
                alphas.append(int(round(fade * 255.0)))
            lines.append([3, first_index, first_index + 1, first_index + 2])

        mesh = pv.PolyData(
            np.asarray(points, dtype=float),
            lines=np.asarray(lines, dtype=np.int64).ravel(),
        )
        rgba = np.empty((len(points), 4), dtype=np.uint8)
        rgba[:, :3] = np.asarray(GridRenderer._color, dtype=np.uint8)
        rgba[:, 3] = np.asarray(alphas, dtype=np.uint8)
        mesh.point_data["rgba"] = rgba
        return mesh

    def _hide_perpendicular_guide(self) -> None:
        if self._perpendicular_guide_actor is not None:
            self._perpendicular_guide_actor.SetVisibility(False)

    def _hide_orthogonal_guide(self) -> None:
        if self._orthogonal_guide_actor is not None:
            self._orthogonal_guide_actor.SetVisibility(False)

    def _placement_target(self, position: np.ndarray) -> tuple[np.ndarray, str | None]:
        """Return the cursor target, applying the first-point plane constraint.

        A real snap is authoritative.  Only a free cursor position is
        projected onto the active reference plane through the first point.
        This lets a member start on an existing node/member while still
        keeping unconstrained second points at the first point's elevation.
        """
        snap = self._snap_position(position)
        guide_target = self._placement_guide_target()
        if snap is not None:
            # A node or member centre is a concrete model snap and remains
            # authoritative.  The construction-grid candidate is only a
            # fallback: when the cursor is deliberately aligned with the
            # normal guide, keeping the grid point would prevent the normal
            # coordinate from ever varying in some camera angles.
            if snap[1] != "grid" or guide_target is None:
                return np.asarray(snap[0], dtype=float), snap[1]
        if self._member_preview_start is None:
            return np.asarray(position, dtype=float), None

        if guide_target is not None:
            return guide_target

        constrained = np.asarray(position, dtype=float).copy()
        constrained_axis = {"XY": 2, "XZ": 1, "YZ": 0}[self._reference_plane_mode]
        constrained[constrained_axis] = self._member_preview_start[constrained_axis]
        return constrained, None

    def _emit_member_placement_point(self) -> None:
        """Emit a click placement after VTK has ended its mouse gesture."""
        if not self._placement_active():
            return
        position = self._placement_world_position()
        self._cancel_coordinate_edit(update=False)
        if position is not None:
            self.placement_point_clicked.emit(tuple(float(value) for value in position))

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
        # Immediately remove a grid snap (or select another valid snap) while
        # a member is being placed; waiting for another mouse move makes the
        # inactive plane appear to remain active.
        self._update_coordinate_readout()
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
        self._update_coordinate_readout()
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
        self._update_coordinate_readout()
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
        # Moving the construction plane changes visible bounds.  Update only
        # the near/far range; the user's position, orientation and zoom stay
        # untouched.
        self.plotter.reset_camera_clipping_range()

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
        self.plotter.camera_set = True
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self._sync_labels()
        self._update_coordinate_readout()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def view_isometric(self) -> None:
        self._set_default_isometric_view()
        self.plotter.camera_set = True
        self.plotter.reset_camera_clipping_range()
        self._zoom_reference_parallel_scale = self._current_parallel_scale()
        self._update_depth_overlays()
        self._sync_labels()
        self._update_coordinate_readout()
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

    def _apply_revit_navigation_style(self) -> None:
        """Install the Revit-like terrain camera controls for this interactor."""
        self.plotter.enable_terrain_style(mouse_wheel_zooms=True, shift_pans=True)

    def _on_interaction(self, *_args) -> None:
        self._camera_interacting = True
        self._schedule_label_sync()
        self._orientation_widget.sync_from_camera()

    def _on_interaction_end(self, *_args) -> None:
        self._camera_interacting = False
        # Orbiting and panning change the viewing direction but are not camera
        # resets.  Recalculate only the clipping planes so no geometry remains
        # hidden after a navigation gesture.
        self.plotter.reset_camera_clipping_range()
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        self._sync_labels()
        self._update_coordinate_readout()
        self._orientation_widget.sync_from_camera()
        self.plotter.render()

    def _sync_labels(self) -> None:
        self._label_overlay.sync(self.plotter.renderer)
        if hasattr(self, "_coordinate_readout"):
            self._update_coordinate_readout()
            if self._member_preview_start is not None:
                self.plotter.render()

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

    def _clear_actor_references(self) -> None:
        self._grid_actor = None
        self._reference_axes_actor = None
        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._member_preview_actor = None
        self._perpendicular_guide_actor = None
        self._orthogonal_guide_actor = None
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
