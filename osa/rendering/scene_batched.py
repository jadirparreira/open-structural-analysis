"""Interactive PyVista scene backed by batched VTK geometry."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pyvista as pv
import vtk
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
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
    _offset_cells,
)
from .elastic_support_overlay import ElasticSupportOverlay
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


class SelectionRectangle(QWidget):
    """Screen-space marquee that never intercepts viewport input."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._crossing = False

    def set_crossing(self, crossing: bool) -> None:
        if self._crossing != crossing:
            self._crossing = crossing
            self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        color = QColor("#2da44e" if self._crossing else "#0969da")
        fill = QColor(color)
        fill.setAlpha(45)
        painter.fillRect(self.rect(), fill)
        painter.setPen(QPen(color, 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class StructureScene(QWidget):
    """Render the full model with a small, stable number of VTK actors."""

    _antialiasing_levels = (0, 2, 4, 8)
    _default_antialiasing_samples = 4

    element_clicked = Signal(str, str, object)
    empty_clicked = Signal()
    selection_changed = Signal(object)
    placement_point_clicked = Signal(object)
    enter_pressed = Signal()
    # The wireframe member and local-axis strokes are intentionally separate.
    # Keep both as screen-space strokes instead of tubes: tubes make a
    # line-only model feel heavier than the solid view it replaces.
    _member_line_width = 1.25
    _local_axis_line_width = 1.0
    _rigid_bar_line_width = 2.0
    _hover_highlight_padding = 2.0
    _selected_highlight_padding = 3.0
    _solid_highlight_line_width = 2.0
    _circular_silhouette_line_width = 3.0
    _snap_tolerance_pixels = 14.0
    _placement_drag_tolerance_pixels = 4.0
    _silhouette_navigation_interval_ms = 500
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
        # Keep a moderate default so edges and thin overlays retain a clean
        # finish without imposing the highest multisampling cost on every
        # project. The setting can be changed live from Program Settings.
        self._antialiasing_samples = self._default_antialiasing_samples
        self.plotter = QtInteractor(self, multi_samples=self._antialiasing_samples)
        layout.addWidget(self.plotter)
        self.plotter.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.plotter.installEventFilter(self)
        self._selection_rectangle = SelectionRectangle(self.plotter)
        self._selection_rectangle.hide()
        self._ctrl_selection_press: tuple[int, int] | None = None
        self.plotter.set_background("#ffffff")
        self.plotter.enable_parallel_projection()
        # Terrain style orbits around the focal point with a stable world-up
        # axis: horizontal dragging changes azimuth and vertical dragging
        # changes elevation, without the accumulated camera roll of VTK's
        # default trackball. This matches the architectural-model workflow.
        self._apply_revit_navigation_style()

        # Local axes are analytical overlays. Render them in a dedicated
        # full-viewport layer so a solid member can never occlude them.
        self._local_axes_renderer = vtk.vtkRenderer()
        self._local_axes_renderer.SetLayer(1)
        self._local_axes_renderer.SetInteractive(False)
        # Preserve the already-rendered color buffer, but let this layer
        # clear the previous depth buffer. With EraseOff, VTK can retain the
        # solid member's depth values and reject an axis that crosses it.
        self._local_axes_renderer.SetErase(True)
        self._local_axes_renderer.SetPreserveColorBuffer(True)
        self._local_axes_renderer.SetPreserveDepthBuffer(False)
        self._local_axes_renderer.SetActiveCamera(self.plotter.renderer.GetActiveCamera())
        if self.plotter.render_window.GetNumberOfLayers() < 2:
            self.plotter.render_window.SetNumberOfLayers(2)
        self.plotter.render_window.AddRenderer(self._local_axes_renderer)

        self._grid_renderer = GridRenderer()
        self._reference_axes_renderer = ReferenceAxesRenderer()
        self._member_renderer = BatchedMemberRenderer()
        self._member_renderer.position_indicators_with_section = False
        self._node_renderer = BatchedNodeRenderer()
        self._rigid_bar_renderer = BatchedRigidBarRenderer()
        self._action_renderer = ActionRenderer()
        self._result_renderer = ResultRenderer()
        self._label_overlay = LabelOverlay(self.plotter)
        self._elastic_support_overlay = ElasticSupportOverlay(self.plotter)
        self._model_info_overlay = QWidget(self.plotter)
        self._model_info_overlay.setObjectName("modelInfoOverlay")
        self._model_info_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._model_info_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._model_info_overlay.setAutoFillBackground(False)
        model_info_layout = QVBoxLayout(self._model_info_overlay)
        model_info_layout.setContentsMargins(0, 0, 0, 0)
        model_info_layout.setSpacing(0)
        self._model_name_caption = QLabel("Modelo", self._model_info_overlay)
        self._model_name_caption.setObjectName("propertySection")
        model_info_layout.addWidget(self._model_name_caption)
        self._model_name_overlay = QLabel("Novo modelo", self._model_info_overlay)
        self._model_name_overlay.setObjectName("modelNameOverlay")
        model_info_layout.addWidget(self._model_name_overlay)
        self._model_info_overlay.adjustSize()
        self._model_info_overlay.move(20, 14)
        self._model_info_overlay.show()
        self._model_info_overlay.raise_()
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
        self._measurement_readout = QFrame(self.plotter)
        self._measurement_readout.setObjectName("measurementReadout")
        self._measurement_readout.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._measurement_readout.setStyleSheet(
            "QFrame#measurementReadout { background: rgba(246, 248, 250, 245); "
            "border: 1px solid #d0d7de; border-radius: 8px; }"
            "QLabel { color: #57606a; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; font-weight: 600; }"
            "QLineEdit { color: #24292f; background: transparent; border: 0; "
            "padding: 0; font-size: 11px; }"
        )
        measurement_layout = QVBoxLayout(self._measurement_readout)
        measurement_layout.setContentsMargins(8, 6, 8, 6)
        measurement_layout.setSpacing(1)
        self._measurement_value_labels: list[QLineEdit] = []
        for label_text in ("Δ", "ΔX", "ΔY", "ΔZ"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            delta_label = QLabel(label_text, self._measurement_readout)
            delta_label.setFixedWidth(18 if label_text != "Δ" else 10)
            delta_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(delta_label)
            value_label = QLineEdit("0.000 m", self._measurement_readout)
            value_label.setObjectName("measurementValue")
            value_label.setReadOnly(True)
            value_label.setFixedWidth(readout_value_width)
            value_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(value_label)
            measurement_layout.addLayout(row)
            self._measurement_value_labels.append(value_label)
        self._measurement_readout.adjustSize()
        self._measurement_readout.hide()
        self._equalize_readout_widths()
        self._snap_marker = SnapMarker(self.plotter)
        self._snap_marker.hide()
        self._measurement_start_marker = SnapMarker(self.plotter)
        self._measurement_start_marker.hide()
        self._orientation_widget = NavigationWidget.create(self.plotter)
        self._model = StructuralModel()
        self._member_batch: MemberBatch | None = None
        self._node_batch: NodeBatch | None = None
        self._member_geometry_cache_key: tuple[object, ...] | None = None
        self._member_geometry_cache: MemberBatch | None = None
        self._pending_member_geometry_names: set[str] = set()
        self._pending_member_full_names: set[str] = set()
        self._silhouette_source_batch: MemberBatch | None = None
        self._silhouette_camera_key: tuple[object, ...] | None = None
        self._silhouette_mesh_cache: pv.PolyData | None = None
        self._node_geometry_cache_key: tuple[object, ...] | None = None
        self._node_geometry_cache: NodeBatch | None = None
        self._rigid_geometry_cache_key: tuple[object, ...] | None = None
        self._rigid_geometry_cache: tuple[tuple[str, ...], pv.PolyData] | None = None
        self._rendered_nodes: dict[str, object] = {}
        self._rendered_members: dict[str, object] = {}
        self._rendered_rigid_bars: dict[str, object] = {}
        self._rendered_axes: tuple[tuple[str, tuple[object, ...]], ...] = ()
        self._rendered_actions: tuple[object, ...] = ()
        self._rendered_revision = -1
        self._rigid_bar_names: tuple[str, ...] = ()
        self._rigid_bar_mesh: pv.PolyData | None = None
        self._measurement_face_locator: vtk.vtkCellLocator | None = None
        self._measurement_face_locator_key: tuple[int, int] | None = None

        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._member_silhouette_actor = None
        self._member_preview_actor = None
        self._measurement_preview_actor = None
        self._perpendicular_guide_actor = None
        self._orthogonal_guide_actor = None
        self._rigid_bar_actor = None
        self._grid_actor = None
        self._reference_axes_actor = None
        self._node_actor = None
        self._node_glyph_points: pv.PolyData | None = None
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
        self._result_diagrams_visible = True
        self._active_analysis_combination: str | None = None
        self._active_result_type = "Normal"
        self._action_layer_key: tuple[object, ...] | None = None
        self._result_layer_key: tuple[object, ...] | None = None
        self._action_visibility = {
            "node_forces": True,
            "node_moments": True,
            "member_forces": True,
            "member_moments": True,
        }
        self._highlight_actors: dict[str, object] = {}
        self._highlight_targets: dict[str, tuple[tuple[str, str], ...]] = {}
        self._highlighted_node_colors: dict[str, str] = {}
        self._highlight_state_key: tuple[object, ...] | None = None

        self._local_axes_visible = True
        self._grid_visible = True
        self._reference_axes_visible = True
        self._nodes_visible = True
        self._labels_visibility = {"node": True, "bar": True}
        self._solid_members_visible = False
        self._member_releases_visible = True
        self._semirigid_links_visible = True
        self._node_supports_visible = True
        self._hovered: tuple[str, str] | None = None
        self._selected: tuple[str, str] | None = None
        self._selected_elements: tuple[tuple[str, str], ...] = ()
        self._scene_selection_mode: str | None = None
        self._selection_press: tuple[int, int] | None = None
        self._selection_dragged = False
        self._tab_hover_candidates: list[tuple[str, str]] = []
        self._tab_hover_position: tuple[int, int] | None = None
        self._pointer_position: tuple[float, float] | None = None
        self._member_placement_mode = False
        self._node_placement_mode = False
        self._measurement_mode = False
        self._member_placement_press: tuple[float, float] | None = None
        self._member_preview_start: np.ndarray | None = None
        self._measurement_start: np.ndarray | None = None
        self._measurement_start_snap_kind: str | None = None
        self._measurement_segments_cache: tuple[tuple[object, ...], tuple] | None = None
        self._measurement_segment_bounds: tuple[np.ndarray, ...] | None = None
        self._projected_snap_cache: tuple[tuple[object, ...], tuple[np.ndarray, ...]] | None = None
        self._pick_projection_cache: tuple[tuple[object, ...], tuple] | None = None
        self._wheel_interaction_timer = QTimer(self)
        self._wheel_interaction_timer.setSingleShot(True)
        self._wheel_interaction_timer.setInterval(90)
        self._wheel_interaction_timer.timeout.connect(self._finish_wheel_interaction)
        self._camera_render_timer = QTimer(self)
        self._camera_render_timer.setSingleShot(True)
        self._camera_render_timer.setInterval(16)
        self._camera_render_timer.timeout.connect(self._render_camera_frame)
        self._measurement_refresh_timer = QTimer(self)
        self._measurement_refresh_timer.setSingleShot(True)
        # Let the final camera frame reach the screen before rebuilding the
        # measurement candidates. That rebuild projects every profile edge
        # and can perform several solid-ray tests on a dense model.
        self._measurement_refresh_timer.setInterval(80)
        self._measurement_refresh_timer.timeout.connect(
            self._refresh_measurement_after_navigation,
        )
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
        self._last_interaction_render_state: tuple[object, ...] | None = None
        self._camera_drag_mode: str | None = None
        self._camera_drag_last_position: tuple[int, int] | None = None
        self._camera_initialized = False
        self._manual_edit_target: np.ndarray | None = None
        self._manual_edit_direction: np.ndarray | None = None
        self._manual_edit_index: int | None = None
        self._manual_edit_confirmable = False
        self._last_display_position: np.ndarray | None = None

        self._solid_picker = vtk.vtkCellPicker()
        self._solid_picker.SetTolerance(0.0005)
        self._solid_picker.PickFromListOn()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(16)
        self._hover_timer.timeout.connect(self._update_hover)
        self._label_timer = QTimer(self)
        self._label_timer.setSingleShot(True)
        self._label_timer.setInterval(16)
        self._label_timer.timeout.connect(self._sync_labels)
        self._silhouette_timer = QTimer(self)
        self._silhouette_timer.setSingleShot(True)
        # Silhouettes remain visible during navigation, but are intentionally
        # refreshed at a much lower rate than camera events arrive.
        self._silhouette_timer.setInterval(self._silhouette_navigation_interval_ms)
        self._silhouette_timer.timeout.connect(self._refresh_member_silhouette_throttled)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(24)
        self._rebuild_timer.timeout.connect(self._rebuild_scene)
        self._member_update_timer = QTimer(self)
        self._member_update_timer.setSingleShot(True)
        self._member_update_timer.setInterval(24)
        self._member_update_timer.timeout.connect(self._refresh_pending_member_update)
        self._support_update_timer = QTimer(self)
        self._support_update_timer.setSingleShot(True)
        self._support_update_timer.setInterval(24)
        self._support_update_timer.timeout.connect(self._refresh_support_batch)
        self._clip_refresh_timer = QTimer(self)
        self._clip_refresh_timer.setSingleShot(True)
        self._clip_refresh_timer.setInterval(120)
        self._clip_refresh_timer.timeout.connect(self._refresh_camera_clipping_range)
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
        # Resolve selection on release, after distinguishing a click from an
        # orbit or pan. Camera drags must leave the current selection intact.
        self._selection_observer_ids = (
            self.plotter.iren.interactor.AddObserver(
                "LeftButtonPressEvent", self._on_selection_press, 1.0,
            ),
            self.plotter.iren.interactor.AddObserver(
                "LeftButtonReleaseEvent", self._on_selection_release, 1.0,
            ),
        )
        self._navigation_observer_ids = (
            self.plotter.iren.interactor.AddObserver(
                "LeftButtonPressEvent", self._on_navigation_left_press, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "LeftButtonReleaseEvent", self._on_navigation_button_release, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "MiddleButtonPressEvent", self._on_navigation_middle_press, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "MiddleButtonReleaseEvent", self._on_navigation_button_release, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "RightButtonPressEvent", self._on_navigation_right_press, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "RightButtonReleaseEvent", self._on_navigation_button_release, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "MouseMoveEvent", self._on_navigation_mouse_move, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "MouseWheelForwardEvent", self._on_navigation_wheel, 1.5,
            ),
            self.plotter.iren.interactor.AddObserver(
                "MouseWheelBackwardEvent", self._on_navigation_wheel, 1.5,
            ),
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
        self._member_update_timer.stop()
        self._support_update_timer.stop()
        self._clip_refresh_timer.stop()
        self._pending_member_geometry_names.clear()
        self._pending_member_full_names.clear()
        camera_state = self._camera_state()
        preserve_camera = bool(preserve_camera and self._camera_initialized)
        self._model = model
        hidden_members = self._scene_hidden_members()
        visible_bars = {
            name: member for name, member in model.bars.items() if name not in hidden_members
        }
        visible_node_names = self._scene_visible_node_names(hidden_members)
        visible_nodes = {
            name: node for name, node in model.nodes.items() if name in visible_node_names
        }
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
            self._elastic_support_overlay.set_members((), (), 0.0)
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
            self._capture_rendered_state()
            return

        positions = np.asarray([(node.x, node.y, node.z) for node in model.nodes.values()])
        if not self._marker_radius_locked:
            self._marker_radius_current = self._marker_radius(positions)
            self._marker_radius_locked = True

        node_radius = self._node_marker_radius()
        # A model revision is too broad a cache key: changing one support also
        # advances it, even though member geometry is unchanged. Keep each
        # rendered batch keyed by the domain data it actually consumes.
        member_key = (
            round(float(self._marker_radius_current), 12),
            self._solid_members_visible,
            tuple(
                (
                    member,
                    (model.nodes[member.start_node].x, model.nodes[member.start_node].y,
                     model.nodes[member.start_node].z),
                    (model.nodes[member.end_node].x, model.nodes[member.end_node].y,
                     model.nodes[member.end_node].z),
                )
                for member in visible_bars.values()
            ),
        )
        if member_key != self._member_geometry_cache_key or self._member_geometry_cache is None:
            self._member_geometry_cache = self._member_renderer.build(
                SimpleNamespace(bars=visible_bars, nodes=model.nodes), self._marker_radius_current,
            )
            self._member_geometry_cache_key = member_key
        self._member_batch = self._member_geometry_cache

        node_key = (
            round(float(node_radius), 12),
            tuple(visible_nodes.values()),
        )
        if node_key != self._node_geometry_cache_key or self._node_geometry_cache is None:
            self._node_geometry_cache = self._node_renderer.build(
                SimpleNamespace(nodes=visible_nodes), node_radius,
            )
            self._node_geometry_cache_key = node_key
        self._node_batch = self._node_geometry_cache

        rigid_key = tuple(
            (
                rigid,
                (model.nodes[rigid.start_node].x, model.nodes[rigid.start_node].y,
                 model.nodes[rigid.start_node].z),
                (model.nodes[rigid.end_node].x, model.nodes[rigid.end_node].y,
                 model.nodes[rigid.end_node].z),
            )
            for rigid in model.rigid_bars.values()
        )
        if rigid_key != self._rigid_geometry_cache_key or self._rigid_geometry_cache is None:
            self._rigid_geometry_cache = self._rigid_bar_renderer.build(model)
            self._rigid_geometry_cache_key = rigid_key
        self._rigid_bar_names, self._rigid_bar_mesh = self._rigid_geometry_cache
        self._elastic_support_overlay.set_members(visible_bars.values(), visible_nodes.values(), node_radius)
        self._add_rigid_bar_batch()
        self._add_member_batches()
        self._add_scene_reveal_preview(hidden_members)
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
        self._silhouette_timer.stop()
        self._refresh_member_silhouette()
        self.plotter.render()
        self._capture_rendered_state()

    def _capture_rendered_state(self) -> None:
        """Remember immutable domain values represented by the current actors."""
        self._rendered_nodes = dict(self._model.nodes)
        self._rendered_members = dict(self._model.bars)
        self._rendered_rigid_bars = dict(self._model.rigid_bars)
        self._rendered_axes = tuple(
            (direction, tuple(axes)) for direction, axes in self._model.axes.items()
        )
        self._rendered_actions = tuple(self._model.actions.values())
        self._rendered_revision = self._model.revision

    def refresh_model_changes(self, model: StructuralModel) -> None:
        """Refresh only layers affected by edits to an existing structure."""
        if model.active_scene_view != "Completo" or self._scene_selection_mode is not None:
            self.render_model(model)
            return
        old_node_names = tuple(self._rendered_nodes)
        old_member_names = tuple(self._rendered_members)
        node_names = tuple(model.nodes)
        member_names_now = tuple(model.bars)
        old_node_set = set(old_node_names)
        removed_nodes = tuple(name for name in old_node_names if name not in model.nodes)
        added_nodes = tuple(name for name in node_names if name not in old_node_set)
        old_member_positions = {
            name: index for index, name in enumerate(old_member_names)
        }
        kept_count = 0
        last_old_index = -1
        for name in member_names_now:
            old_index = old_member_positions.get(name, -1)
            if old_index <= last_old_index:
                break
            kept_count += 1
            last_old_index = old_index
        kept_members = member_names_now[:kept_count]
        kept_set = set(kept_members)
        removed_members = tuple(name for name in old_member_names if name not in kept_set)
        added_members = member_names_now[kept_count:]
        if (
            model is not self._model
            or not self._camera_initialized
            or self._node_batch is None
            or not node_names
            or node_names != tuple(name for name in old_node_names if name in model.nodes) + added_nodes
            or len(removed_members) > 12
        ):
            self.render_model(model)
            return
        self._member_update_timer.stop()
        self._support_update_timer.stop()
        self._rebuild_timer.stop()
        self._pending_member_geometry_names.clear()
        self._pending_member_full_names.clear()
        self._validate_selection()

        changed_nodes = tuple(
            name for name, node in model.nodes.items() if name in self._rendered_nodes
            if node != self._rendered_nodes[name]
        )
        moved_nodes = tuple(
            name for name in changed_nodes
            if (model.nodes[name].x, model.nodes[name].y, model.nodes[name].z)
            != (
                self._rendered_nodes[name].x,
                self._rendered_nodes[name].y,
                self._rendered_nodes[name].z,
            )
        )
        member_names = {
            name for name, member in model.bars.items()
            if name in self._rendered_members and name not in removed_members
            if member != self._rendered_members[name]
        }
        if moved_nodes:
            if removed_nodes:
                self.render_model(model)
                return
            moved_set = set(moved_nodes)
            member_names.update(
                name for name, member in model.bars.items()
                if (member.start_node in moved_set or member.end_node in moved_set)
                and name not in removed_members and name not in added_members
            )
            if not self._node_renderer.update_node_positions_in_place(
                self._node_batch, self._rendered_nodes, model, moved_nodes,
                self._node_marker_radius(),
            ):
                self.render_model(model)
                return
            self._node_geometry_cache_key = (
                round(float(self._node_marker_radius()), 12), tuple(model.nodes.values()),
            )
            self._update_node_glyph_positions(moved_nodes)
            if self._node_actor is not None:
                self._node_actor.GetMapper().Modified()
            self._label_overlay.set_group(
                "node", self._node_batch.label_positions, self._node_batch.names,
                visible=self._labels_visibility["node"],
            )

        if removed_nodes:
            self._refresh_node_batch()
        elif added_nodes:
            if not self._node_renderer.append_nodes(
                self._node_batch, model, added_nodes, self._node_marker_radius(),
            ):
                self.render_model(model)
                return
            self._node_geometry_cache = self._node_batch
            self._node_geometry_cache_key = (
                round(float(self._node_marker_radius()), 12), tuple(model.nodes.values()),
            )
            if self._node_actor is not None:
                self.plotter.renderer.RemoveActor(self._node_actor)
            self._node_actor = self._add_node_glyph_actor(self._node_batch)
            if self._node_actor is not None:
                self._node_actor.SetVisibility(self._nodes_visible)
            self._label_overlay.set_group(
                "node", self._node_batch.label_positions, self._node_batch.names,
                visible=self._labels_visibility["node"],
            )

        if member_names:
            names = tuple(name for name in model.bars if name in member_names)
            if not self._refresh_member_subset(names):
                self._refresh_member_batch()
        if removed_members:
            batch = self._member_batch
            had_silhouette = batch is not None and any(
                name in batch.silhouette_sources for name in removed_members
            )
            if batch is None or any(
                not self._member_renderer.remove_member(batch, name)
                for name in removed_members
            ):
                self._refresh_member_batch()
            else:
                self._member_geometry_cache = batch
                self._member_geometry_cache_key = self._member_cache_key(model)
                if had_silhouette:
                    self._silhouette_source_batch = None
                self._display_member_batch(removed_names=removed_members)
        if added_members:
            batch = self._member_batch
            if batch is None or not self._member_renderer.append_members(
                batch, model, added_members, self._marker_radius_current,
            ):
                self._refresh_member_batch()
            else:
                self._member_geometry_cache = batch
                self._member_geometry_cache_key = self._member_cache_key(model)
                if any(name in batch.silhouette_sources for name in added_members):
                    self._silhouette_source_batch = None
                self._display_member_batch(added_members)
        if (changed_nodes or added_nodes) and not removed_nodes:
            self._refresh_support_batch(capture_state=False)

        rigid_changed = (
            self._rendered_rigid_bars != model.rigid_bars
            or bool(moved_nodes) and any(
                rigid.start_node in moved_nodes or rigid.end_node in moved_nodes
                for rigid in model.rigid_bars.values()
            )
        )
        if rigid_changed:
            self._refresh_rigid_batch()

        axes = tuple((direction, tuple(items)) for direction, items in model.axes.items())
        if moved_nodes or added_nodes or removed_nodes or axes != self._rendered_axes:
            self._refresh_reference_plane_renderers()
            self._add_reference_axis_labels()
            self._sync_labels()
            self.plotter.render()

        actions_changed = tuple(model.actions.values()) != self._rendered_actions
        member_action_geometry_changed = any(
            (
                member.start_node, member.end_node, member.rotation,
            ) != (
                self._rendered_members[name].start_node,
                self._rendered_members[name].end_node,
                self._rendered_members[name].rotation,
            )
            for name, member in model.bars.items()
            if name in member_names and name in self._rendered_members
        )
        if self._actions_visible and (
            actions_changed or moved_nodes or member_action_geometry_changed
            or removed_members or removed_nodes or added_members or added_nodes
        ):
            self._refresh_action_layer()
        if self._rendered_revision != model.revision and self._analysis_visible:
            self._refresh_result_layer()
        elif self._rendered_revision != model.revision:
            self._clear_result_layer()
        self._capture_rendered_state()

    def antialiasing_samples(self) -> int:
        """Return the active multisampling level used by the viewport."""
        return self._antialiasing_samples

    def set_antialiasing_samples(self, samples: int) -> None:
        """Apply a supported multisampling level without closing the app."""
        samples = int(samples)
        if samples not in self._antialiasing_levels:
            raise ValueError("A qualidade do antialiasing deve ser 0, 2, 4 ou 8.")
        if samples == self._antialiasing_samples:
            return
        self._antialiasing_samples = samples
        self.plotter.render_window.SetMultiSamples(samples)
        self.plotter.render_window.Modified()
        self.plotter.render()

    def _add_member_batches(self) -> None:
        batch = self._member_batch
        if batch is None:
            return
        self._member_line_actor = self._add_colored_mesh(
            batch.lines, "batch:member-lines", line_width=self._member_line_width,
            lighting=False,
        )
        self._member_fallback_actor = self._add_colored_mesh(
            batch.fallback_lines, "batch:member-fallback", line_width=self._member_line_width,
            lighting=False,
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
        self._member_silhouette_actor = self._add_colored_mesh(
            self._member_silhouette_mesh(batch),
            "batch:member-silhouette",
            line_width=self._circular_silhouette_line_width,
            lighting=False,
        )
        if self._member_silhouette_actor is not None:
            self._member_silhouette_actor.SetPickable(False)
            silhouette_mapper = self._member_silhouette_actor.GetMapper()
            silhouette_mapper.SetResolveCoincidentTopologyToPolygonOffset()
            silhouette_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
            silhouette_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)

        for mesh, color in zip(batch.axes, self._axis_colors):
            if not mesh.n_cells:
                continue
            actor = self._add_local_axis_overlay(mesh, color)
            actor.SetVisibility(self._local_axes_visible)
            self._local_axis_actors.append(actor)

        if batch.releases.n_cells:
            self._release_actor = self.plotter.add_mesh(
                batch.releases, color="#000000", line_width=3, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
                lighting=False,
            )
            self._release_actor.SetVisibility(self._member_releases_visible)

    def _scene_hidden_members(self) -> set[str]:
        return set(self._model.scene_views.get(self._model.active_scene_view, ())).intersection(
            self._model.bars
        )

    def _scene_visible_node_names(self, hidden_members: set[str]) -> set[str]:
        connected = set()
        visible_connected = set()
        for member in self._model.bars.values():
            endpoints = (member.start_node, member.end_node)
            connected.update(endpoints)
            if member.name not in hidden_members:
                visible_connected.update(endpoints)
        for rigid in self._model.rigid_bars.values():
            endpoints = (rigid.start_node, rigid.end_node)
            connected.update(endpoints)
            visible_connected.update(endpoints)
        return set(self._model.nodes).difference(connected).union(visible_connected)

    def _scene_filtered_model(self) -> SimpleNamespace:
        hidden_members = self._scene_hidden_members()
        visible_nodes = self._scene_visible_node_names(hidden_members)
        bars = {
            name: member for name, member in self._model.bars.items()
            if name not in hidden_members
        }
        nodes = {
            name: node for name, node in self._model.nodes.items()
            if name in visible_nodes
        }
        actions = {
            name: action for name, action in self._model.actions.items()
            if action.target in bars or action.target in nodes
        }
        return SimpleNamespace(bars=bars, nodes=nodes, actions=actions)

    def _add_scene_reveal_preview(self, hidden_members: set[str]) -> None:
        if self._scene_selection_mode != "reveal" or not hidden_members:
            return
        preview_model = SimpleNamespace(
            bars={name: self._model.bars[name] for name in self._model.bars if name in hidden_members},
            nodes=self._model.nodes,
        )
        preview = self._member_renderer.build(preview_model, self._marker_radius_current)
        self._reveal_preview_batch = preview
        self._reveal_preview_line_actor = self._add_colored_mesh(
            preview.lines, "scene:reveal-lines", line_width=self._member_line_width, lighting=False,
        )
        self._reveal_preview_face_actor = self._add_colored_mesh(
            preview.faces, "scene:reveal-faces", lighting=True,
        )
        self._reveal_preview_fallback_actor = self._add_colored_mesh(
            preview.fallback_lines, "scene:reveal-fallback", line_width=self._member_line_width,
            lighting=False,
        )
        for actor in (
            self._reveal_preview_line_actor, self._reveal_preview_face_actor,
            self._reveal_preview_fallback_actor,
        ):
            if actor is not None:
                actor.GetProperty().SetOpacity(0.7)
                actor.SetPickable(False)

    def _add_local_axis_overlay(self, mesh: pv.PolyData, color: str):
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(mesh)
        mapper.SetScalarVisibility(False)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetPickable(False)
        actor.GetProperty().SetColor(*pv.Color(color).float_rgb)
        actor.GetProperty().SetLineWidth(self._local_axis_line_width)
        actor.GetProperty().LightingOff()
        actor.GetProperty().RenderLinesAsTubesOff()
        self._local_axes_renderer.AddActor(actor)
        return actor

    def _add_node_batches(self) -> None:
        batch = self._node_batch
        if batch is None:
            return
        if batch.geometry.n_cells:
            self._node_actor = self._add_node_glyph_actor(batch)
            if self._node_actor is not None:
                self._node_actor.SetVisibility(self._nodes_visible)
        if batch.supports.n_cells:
            self._support_actor = self.plotter.add_mesh(
                batch.supports, color="#a8b0b9", edge_color="#6e7781",
                show_edges=True, line_width=1.5, pickable=False,
                reset_camera=False, render=False,
            )
            self._support_actor.SetVisibility(self._node_supports_visible)

    def _add_node_glyph_actor(self, batch: NodeBatch) -> vtk.vtkActor | None:
        """Draw identical node spheres as GPU instances instead of packed faces."""
        if not batch.names:
            self._node_glyph_points = None
            return None
        positions = np.asarray([
            (self._model.nodes[name].x, self._model.nodes[name].y, self._model.nodes[name].z)
            for name in batch.names
        ], dtype=float)
        glyph_points = pv.PolyData(positions)
        cell_indices = np.asarray(batch.geometry.cell_data["element_index"])
        cell_colors = np.asarray(batch.geometry.cell_data["rgb"])
        first_cells = np.searchsorted(cell_indices, np.arange(len(batch.names)), side="left")
        glyph_points.point_data["rgb"] = cell_colors[first_cells].copy()

        sphere = pv.Sphere(
            radius=self._node_marker_radius(), center=(0.0, 0.0, 0.0),
            theta_resolution=20, phi_resolution=12,
        )
        mapper = vtk.vtkGlyph3DMapper()
        mapper.SetInputData(glyph_points)
        mapper.SetSourceData(sphere)
        mapper.SetScaleModeToNoDataScaling()
        mapper.OrientOff()
        mapper.SetScalarModeToUsePointFieldData()
        mapper.SelectColorArray("rgb")
        mapper.SetColorModeToDirectScalars()
        mapper.ScalarVisibilityOn()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.SetPickable(False)
        actor.SetObjectName("batch:nodes")
        actor.GetProperty().SetInterpolationToPhong()
        self.plotter.renderer.AddActor(actor)
        self._node_glyph_points = glyph_points
        return actor

    def _update_node_glyph_positions(self, names: tuple[str, ...]) -> None:
        points = self._node_glyph_points
        batch = self._node_batch
        if points is None or batch is None or not names:
            return
        indices = {name: index for index, name in enumerate(batch.names)}
        for name in names:
            index = indices.get(name)
            if index is not None and name in self._model.nodes:
                node = self._model.nodes[name]
                points.points[index] = (node.x, node.y, node.z)
        points.GetPoints().Modified()
        points.Modified()

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
            self._action_layer_key = None
            self._action_actors = []
            self._action_label_positions = np.empty((0, 3), dtype=float)
            self._action_labels = ()
            return
        (
            self._action_actors,
            self._action_label_positions,
            self._action_labels,
        ) = self._action_renderer.render(
            self.plotter, self._scene_filtered_model(), self._active_load_case,
            self._action_visibility,
        )
        self._action_layer_key = (
            id(self._model), self._model.revision, self._model.view_revision, self._active_load_case,
            tuple(sorted(self._action_visibility.items())),
        )

    def _remove_actors(self, actors: list[object]) -> None:
        """Remove an overlay without touching the structural scene."""
        renderer = self.plotter.renderer
        for actor in actors:
            if actor is not None:
                renderer.RemoveActor(actor)

    def _clear_action_layer(self) -> None:
        self._remove_actors(self._action_actors)
        self._action_layer_key = None
        self._action_actors = []
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels = ()
        self._label_overlay.set_group(
            "action", self._action_label_positions, (), visible=False, deduplicate=True,
        )

    def _clear_result_layer(self) -> None:
        self._remove_actors(self._result_actors)
        self._result_layer_key = None
        self._result_actors = []
        self._result_line_widths = []
        self._result_label_positions = np.empty((0, 3), dtype=float)
        self._result_labels = ()
        self._label_overlay.set_group(
            "result", self._result_label_positions, (), visible=False, deduplicate=True,
        )

    def _refresh_action_layer(self) -> None:
        """Refresh only action geometry and labels."""
        self._clear_action_layer()
        if self._actions_visible:
            self._add_actions()
            self._label_overlay.set_group(
                "action", self._action_label_positions, self._action_labels,
                visible=True, deduplicate=True,
            )
        self._sync_labels(render_preview=False)
        self.plotter.render()
        self._clip_refresh_timer.start()

    def _add_results(self) -> None:
        if not self._analysis_visible or self._active_analysis_combination is None:
            self._result_layer_key = None
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
            self.plotter, self._scene_filtered_model(), result, self._active_result_type,
            solid_members_visible=self._solid_members_visible,
        )
        self._result_layer_key = (
            id(self._model), self._model.revision, self._model.view_revision,
            self._active_analysis_combination,
            self._active_result_type, self._solid_members_visible,
        )
        self._result_line_widths = []
        if self._active_result_type.startswith("Deformação") and self._result_actors:
            # Primeiro ator é sempre a referência indeformada tracejada.
            self._result_line_widths.append((self._result_actors[0], 1.0))
            if not self._solid_members_visible and len(self._result_actors) > 1:
                self._result_line_widths.append((self._result_actors[1], 2.0))
        self._apply_result_layer_visibility()

    def _result_layer_is_visible(self) -> bool:
        """Deformation overlays are independent from the diagram toggle."""
        return self._analysis_visible and (
            self._result_diagrams_visible or self._active_result_type.startswith("Deformação")
        )

    def _apply_result_layer_visibility(self) -> None:
        visible = self._result_layer_is_visible()
        for actor in self._result_actors:
            actor.SetVisibility(visible)
        self._label_overlay.set_group_visible("result", visible)

    def _refresh_result_layer(self) -> None:
        """Refresh only the selected analysis overlay and its labels."""
        self._clear_result_layer()
        if self._analysis_visible:
            self._add_results()
            self._label_overlay.set_group(
                "result", self._result_label_positions, self._result_labels,
                visible=self._result_layer_is_visible(), deduplicate=True,
            )
            self._apply_result_layer_visibility()
        self._apply_representation_visibility()
        self._update_zoom_dependent_sizes()
        self._sync_labels()
        self.plotter.render()
        self._clip_refresh_timer.start()

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
            "action", self._action_label_positions, self._action_labels,
            visible=True, deduplicate=True,
        )
        self._label_overlay.set_group(
            "result", self._result_label_positions, self._result_labels,
            visible=self._result_layer_is_visible(), deduplicate=True,
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
        # In the solid representation, the analytical line is hidden. Keep
        # screen-space picking only for nodes, rigid bars and members whose
        # section could not produce a solid (their fallback line is visible).
        # Otherwise an offset or wide profile can be selected where nothing
        # is drawn, while its actual face is missed.
        preview = self._scene_selection_mode == "reveal"
        actor = self._reveal_preview_face_actor if preview else self._member_face_actor
        batch = self._reveal_preview_batch if preview else self._member_batch
        if actor is not None and actor.GetVisibility() and batch is not None:
            solid_names = batch.face_cell_ranges
            candidates = [
                target for target in candidates
                if target[0] != "bar" or target[1] not in solid_names
            ]
        solid = self._pick_solid_member(preview=preview)
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

    def _pick_solid_member(self, *, preview: bool = False) -> tuple[str, str] | None:
        batch = self._reveal_preview_batch if preview else self._member_batch
        actor = self._reveal_preview_face_actor if preview else self._member_face_actor
        if (
            self._pointer_position is None
            or batch is None
            or actor is None
            or not actor.GetVisibility()
            or (not preview and not actor.GetPickable())
        ):
            return None
        x, y = self._qt_to_vtk_position(
            self._pointer_position,
            (self.plotter.width(), self.plotter.height()),
            tuple(self.plotter.render_window.GetSize()),
        )
        if preview:
            locator = vtk.vtkCellLocator()
            locator.SetDataSet(batch.faces)
            locator.BuildLocator()
        else:
            locator = self._measurement_face_locator_for_current_batch()
        if locator is None:
            return None
        renderer = self.plotter.renderer
        near = self._display_to_world(renderer, x, y, 0.0)
        far = self._display_to_world(renderer, x, y, 1.0)
        if near is None or far is None:
            return None
        hit_points = vtk.vtkPoints()
        hit_cells = vtk.vtkIdList()
        if not locator.IntersectWithLine(
            tuple(near), tuple(far), 1e-9, hit_points, hit_cells,
        ):
            return None
        ray = far - near
        points = np.asarray(
            [hit_points.GetPoint(index) for index in range(hit_points.GetNumberOfPoints())],
            dtype=float,
        )
        closest = int(np.argmin((points - near) @ ray))
        cell_id = hit_cells.GetId(closest)
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
        (
            node_names, node_screens, node_visible,
            member_targets, member_starts, member_deltas, member_visible,
            min_x, max_x, min_y, max_y,
        ) = self._pick_projection_data()

        candidates: list[tuple[float, tuple[str, str]]] = []
        node_tolerance = 12.0
        member_tolerance = 10.0
        node_distances = np.linalg.norm(node_screens - cursor, axis=1)
        for index in np.flatnonzero(node_visible & (node_distances <= node_tolerance)):
            candidates.append((float(node_distances[index]), ("node", node_names[index])))

        nearby = np.flatnonzero(
            member_visible
            & (cursor[0] >= min_x - member_tolerance)
            & (cursor[0] <= max_x + member_tolerance)
            & (cursor[1] >= min_y - member_tolerance)
            & (cursor[1] <= max_y + member_tolerance)
        )
        starts = member_starts[nearby]
        deltas = member_deltas[nearby]
        lengths_squared = np.einsum("ij,ij->i", deltas, deltas)
        fractions = np.divide(
            np.einsum("ij,ij->i", cursor - starts, deltas),
            lengths_squared,
            out=np.zeros(len(nearby), dtype=float),
            where=lengths_squared > 1e-12,
        )
        closest = starts + np.clip(fractions, 0.0, 1.0)[:, None] * deltas
        distances = np.linalg.norm(cursor - closest, axis=1)
        for local_index in np.flatnonzero(distances <= member_tolerance):
            index = nearby[local_index]
            candidates.append((float(distances[local_index]), member_targets[index]))
        candidates.sort(key=lambda item: item[0])
        return [candidate for _distance, candidate in candidates]

    def _pick_projection_data(self) -> tuple:
        """Cache projected node positions and member centrelines for hover and clicks."""
        camera = self.plotter.renderer.GetActiveCamera()
        width, height = self.plotter.width(), self.plotter.height()
        key = (
            id(self._model), self._model.revision, self._model.view_revision,
            self._scene_selection_mode, int(camera.GetMTime()), width, height,
        )
        if self._pick_projection_cache is not None and self._pick_projection_cache[0] == key:
            return self._pick_projection_cache[1]
        matrix, _, _ = self._measurement_projection_context()
        node_names = tuple(self._model.nodes)
        node_indices = {name: index for index, name in enumerate(node_names)}
        node_points = np.asarray(
            [(node.x, node.y, node.z) for node in self._model.nodes.values()],
            dtype=float,
        ).reshape((-1, 3))
        node_screens, within_depth = project_world_to_screen(
            node_points, matrix, width, height, clip_to_viewport=False,
        )
        node_visible = (
            within_depth
            & (node_screens[:, 0] >= 0.0)
            & (node_screens[:, 0] <= width)
            & (node_screens[:, 1] >= 0.0)
            & (node_screens[:, 1] <= height)
        )
        visible_nodes = self._scene_visible_node_names(self._scene_hidden_members())
        node_visible &= np.asarray([
            name in visible_nodes and self._scene_selection_mode is None
            for name in node_names
        ], dtype=bool)
        member_targets = []
        starts = []
        ends = []
        for kind, elements in (("bar", self._model.bars), ("rigid_bar", self._model.rigid_bars)):
            for name, element in elements.items():
                first = node_indices.get(element.start_node)
                last = node_indices.get(element.end_node)
                if first is not None and last is not None:
                    member_targets.append((kind, name))
                    starts.append(first)
                    ends.append(last)
        start_indices = np.asarray(starts, dtype=np.intp)
        end_indices = np.asarray(ends, dtype=np.intp)
        member_starts = node_screens[start_indices]
        member_ends = node_screens[end_indices]
        hidden_members = self._scene_hidden_members()
        member_visible = within_depth[start_indices] & within_depth[end_indices]
        member_visible &= np.asarray([
            (kind == "bar" and name in hidden_members)
            if self._scene_selection_mode == "reveal"
            else (kind == "bar" and name not in hidden_members)
            if self._scene_selection_mode == "hide"
            else (kind != "bar" or name not in hidden_members)
            for kind, name in member_targets
        ], dtype=bool)
        data = (
            node_names, node_screens, node_visible,
            tuple(member_targets), member_starts, member_ends - member_starts,
            member_visible,
            np.minimum(member_starts[:, 0], member_ends[:, 0]),
            np.maximum(member_starts[:, 0], member_ends[:, 0]),
            np.minimum(member_starts[:, 1], member_ends[:, 1]),
            np.maximum(member_starts[:, 1], member_ends[:, 1]),
        )
        self._pick_projection_cache = key, data
        return data

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
        if (
            watched is self.plotter
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not self._placement_active()
        ):
            self.enter_pressed.emit()
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
            if self._ctrl_selection_press is not None:
                if event.type() == QEvent.Type.MouseMove:
                    self._update_selection_rectangle(int(point.x()), int(point.y()))
                    event.accept()
                    return True
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                    self._finish_ctrl_selection(int(point.x()), int(point.y()))
                    event.accept()
                    return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and not self._placement_active()
                and getattr(self.window(), "_command_mode", None) in (
                    None, "scene_hide_selection", "scene_reveal_selection",
                    "copy_elements_selection", "copy_member_properties_selection",
                    "reverse_member_selection", "split_member_selection",
                    "join_member_selection", "action_selection",
                )
                and not over_navigation_cube
            ):
                self._ctrl_selection_press = int(point.x()), int(point.y())
                event.accept()
                return True
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
                and self._placement_active()
                and not over_navigation_cube
            ):
                # Keep a normal click for placement, but let VTK receive the
                # press. If the pointer moves, the same orbit used outside
                # the drawing tool takes over.
                self._member_placement_press = point.x(), point.y()
            elif (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                # Ensure a release that occurs outside the OpenGL viewport
                # also ends an active camera gesture.
                QTimer.singleShot(0, self._finish_camera_drag)
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
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._hide_member_preview()
            self._hide_measurement_preview()
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

    def _update_selection_rectangle(self, x: int, y: int) -> None:
        start = self._ctrl_selection_press
        if start is None:
            return
        if np.hypot(x - start[0], y - start[1]) <= self._placement_drag_tolerance_pixels:
            return
        self._selection_rectangle.set_crossing(x < start[0])
        left, right = sorted((start[0], x))
        top, bottom = sorted((start[1], y))
        rectangle = QRect(left, top, right - left + 1, bottom - top + 1)
        self._selection_rectangle.setGeometry(rectangle)
        self._selection_rectangle.show()
        self._selection_rectangle.raise_()

    def _finish_ctrl_selection(self, x: int, y: int) -> None:
        start = self._ctrl_selection_press
        self._ctrl_selection_press = None
        self._selection_rectangle.hide()
        if start is None:
            return
        selected = list(self._selected_elements)
        if np.hypot(x - start[0], y - start[1]) <= self._placement_drag_tolerance_pixels:
            picked = self._pick()
            if picked in selected:
                selected.remove(picked)
            elif picked is not None:
                selected.append(picked)
        else:
            selected_set = set(selected)
            for target in self._elements_in_rectangle(start, (x, y)):
                if target not in selected_set:
                    selected.append(target)
                    selected_set.add(target)
        self.set_selection_highlight(selected)
        self.selection_changed.emit(tuple(selected))

    def _elements_in_rectangle(
        self, start: tuple[int, int], end: tuple[int, int],
    ) -> tuple[tuple[str, str], ...]:
        """Select contained elements to the right and intersecting elements to the left."""
        left, right = sorted((start[0], end[0]))
        top, bottom = sorted((start[1], end[1]))
        (
            node_names, node_screens, node_visible,
            member_targets, member_starts, member_deltas, member_visible,
            *_bounds,
        ) = self._pick_projection_data()
        nodes_inside = (
            node_visible
            & (node_screens[:, 0] >= left) & (node_screens[:, 0] <= right)
            & (node_screens[:, 1] >= top) & (node_screens[:, 1] <= bottom)
        )
        member_ends = member_starts + member_deltas
        preview = self._scene_selection_mode == "reveal"
        solid_actor = self._reveal_preview_face_actor if preview else self._member_face_actor
        solid_batch = self._reveal_preview_batch if preview else self._member_batch
        solid = solid_actor is not None and solid_actor.GetVisibility() and solid_batch is not None
        if solid:
            # The centreline is hidden for members with a rendered section.
            # Retain it only for members displayed as fallback lines.
            solid_names = solid_batch.face_cell_ranges
            member_visible = member_visible & np.asarray([
                kind != "bar" or name not in solid_names
                for kind, name in member_targets
            ], dtype=bool)
        if end[0] < start[0]:
            members_inside = member_visible & self._segments_touch_rectangle(
                member_starts, member_ends, left, top, right, bottom,
            )
        else:
            members_inside = (
                member_visible
                & (member_starts[:, 0] >= left) & (member_starts[:, 0] <= right)
                & (member_starts[:, 1] >= top) & (member_starts[:, 1] <= bottom)
                & (member_ends[:, 0] >= left) & (member_ends[:, 0] <= right)
                & (member_ends[:, 1] >= top) & (member_ends[:, 1] <= bottom)
            )
        solid_members = (
            self._solid_members_in_rectangle(
                left, top, right, bottom, crossing=end[0] < start[0], batch=solid_batch,
            ) if solid else set()
        )
        return (
            *(("node", node_names[index]) for index in np.flatnonzero(nodes_inside)),
            *(target for index, target in enumerate(member_targets)
              if target[0] == "bar" and (
                  members_inside[index] or target[1] in solid_members
              )),
        )

    def _solid_members_in_rectangle(
        self, left: float, top: float, right: float, bottom: float, *, crossing: bool,
        batch: MemberBatch | None = None,
    ) -> set[str]:
        """Test projected profile faces, including visual section/end offsets."""
        batch = batch or self._member_batch
        if batch is None or not batch.face_cell_ranges:
            return set()
        matrix, width, height = self._measurement_projection_context()
        screens, within_depth = project_world_to_screen(
            batch.faces.points, matrix, width, height, clip_to_viewport=False,
        )
        face_cells = np.asarray(batch.faces.faces, dtype=np.int64)
        if len(face_cells) % 4 or not np.all(face_cells[::4] == 3):
            return set()
        triangles = face_cells.reshape((-1, 4))[:, 1:]
        selected: set[str] = set()
        for name, (first, last) in batch.face_point_ranges.items():
            points = screens[first:last]
            if not len(points) or not np.any(within_depth[first:last]):
                continue
            if crossing:
                if (
                    points[:, 0].min() > right or points[:, 0].max() < left
                    or points[:, 1].min() > bottom or points[:, 1].max() < top
                ):
                    continue
                cell_first, cell_last = batch.face_cell_ranges[name]
                member_triangles = triangles[cell_first:cell_last]
                visible_faces = np.all(within_depth[member_triangles], axis=1)
                if self._triangles_touch_rectangle(
                    screens[member_triangles[visible_faces]], left, top, right, bottom,
                ):
                    selected.add(name)
            elif (
                np.all(within_depth[first:last])
                and np.all((points[:, 0] >= left) & (points[:, 0] <= right))
                and np.all((points[:, 1] >= top) & (points[:, 1] <= bottom))
            ):
                selected.add(name)
        return selected

    @classmethod
    def _triangles_touch_rectangle(
        cls, triangles: np.ndarray,
        left: float, top: float, right: float, bottom: float,
    ) -> bool:
        if not len(triangles):
            return False
        inside = (
            (triangles[:, :, 0] >= left) & (triangles[:, :, 0] <= right)
            & (triangles[:, :, 1] >= top) & (triangles[:, :, 1] <= bottom)
        )
        if np.any(inside):
            return True
        corners = np.asarray(((left, top), (right, top), (right, bottom), (left, bottom)))
        edges = np.roll(triangles, -1, axis=1) - triangles
        relative = corners[None, None, :, :] - triangles[:, :, None, :]
        cross = edges[:, :, 0, None] * relative[:, :, :, 1] - edges[:, :, 1, None] * relative[:, :, :, 0]
        if np.any(np.all(cross >= -1e-9, axis=1) | np.all(cross <= 1e-9, axis=1)):
            return True
        starts = triangles.reshape((-1, 2))
        ends = np.roll(triangles, -1, axis=1).reshape((-1, 2))
        return bool(np.any(cls._segments_touch_rectangle(starts, ends, left, top, right, bottom)))

    @staticmethod
    def _segments_touch_rectangle(
        starts: np.ndarray, ends: np.ndarray,
        left: float, top: float, right: float, bottom: float,
    ) -> np.ndarray:
        """Liang–Barsky clipping, including edges and segments crossing the whole box."""
        delta = ends - starts
        lower = np.zeros(len(starts), dtype=float)
        upper = np.ones(len(starts), dtype=float)
        outside = np.zeros(len(starts), dtype=bool)
        for p, q in (
            (-delta[:, 0], starts[:, 0] - left),
            (delta[:, 0], right - starts[:, 0]),
            (-delta[:, 1], starts[:, 1] - top),
            (delta[:, 1], bottom - starts[:, 1]),
        ):
            parallel = np.abs(p) <= 1e-12
            outside |= parallel & (q < 0)
            fraction = np.divide(q, p, out=np.zeros_like(q), where=~parallel)
            lower = np.maximum(lower, np.where(p < -1e-12, fraction, lower))
            upper = np.minimum(upper, np.where(p > 1e-12, fraction, upper))
        return ~outside & (lower <= upper)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_navigation_viewport_sync()

    def _placement_active(self) -> bool:
        return self._member_placement_mode or self._node_placement_mode or self._measurement_mode

    @property
    def measurement_start(self) -> tuple[float, float, float] | None:
        """Return the fixed first point of the active transient measurement."""
        if self._measurement_start is None:
            return None
        return tuple(float(value) for value in self._measurement_start)

    def _on_mouse_move(self, *_args) -> None:
        if self._camera_interacting:
            return
        self._update_coordinate_readout()
        if not self._measurement_refresh_timer.isActive():
            self._update_measurement_readout()
        if self._member_preview_start is not None or (
            self._measurement_start is not None
            and not self._measurement_refresh_timer.isActive()
        ):
            # Both placement previews are world-space actors.  Render after
            # changing their mapper so the line follows the cursor even when
            # the interactor itself does not schedule a paint for this move.
            self.plotter.render()
        x, y = self.plotter.iren.get_event_position()
        position = (int(x), int(y))
        if position != self._tab_hover_position:
            self._tab_hover_candidates = []
            self._tab_hover_position = None
        if self._placement_active():
            # Placement has its own snap marker. A solid VTK hover pick can
            # otherwise block the cursor for a full frame on a dense model.
            return
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
        self._measurement_mode = False
        self._measurement_start = None
        self._hide_measurement_preview()
        self._set_point_placement_mode(active)

    def set_selection_highlight(self, elements: object) -> None:
        """Show one or more selected elements in the viewport."""
        normalized: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for element in elements:
            target = str(element[0]), str(element[1])
            if target not in seen:
                normalized.append(target)
                seen.add(target)
        self._selected_elements = tuple(normalized)
        self._selected = self._selected_elements[-1] if self._selected_elements else None
        self._sync_highlights()
        self.plotter.render()

    def set_node_placement_mode(self, active: bool) -> None:
        """Enable the single-click graphical node-placement flow."""
        self._node_placement_mode = bool(active)
        self._member_placement_mode = False
        self._measurement_mode = False
        self._measurement_start = None
        self._hide_measurement_preview()
        if active:
            self._member_preview_start = None
        self._set_point_placement_mode(active)

    def set_measurement_mode(self, active: bool) -> None:
        """Enable the transient two-point measurement flow."""
        self._measurement_mode = bool(active)
        self._member_placement_mode = False
        self._node_placement_mode = False
        self._member_preview_start = None
        if not active:
            self._measurement_start = None
            self._measurement_start_snap_kind = None
            self._hide_measurement_preview()
        self._set_point_placement_mode(active)

    def set_measurement_start(self, point: object | None) -> None:
        """Set or clear the first point of the active measurement."""
        self._measurement_start = (
            None if point is None else np.asarray(tuple(point), dtype=float)
        )
        self._measurement_start_snap_kind = None
        if self._measurement_start is not None and self._measurement_mode:
            cursor_position = self._cursor_world_position()
            if cursor_position is not None:
                snapped, snap_kind = self._measurement_target(cursor_position)
                if snap_kind is not None and np.allclose(
                    snapped, self._measurement_start, atol=1e-9, rtol=0.0,
                ):
                    self._measurement_start_snap_kind = snap_kind
        self._update_measurement_readout()

    def _set_point_placement_mode(self, active: bool) -> None:
        if not active:
            self._member_placement_press = None
            self._member_preview_start = None
            self._manual_edit_target = None
            self._manual_edit_direction = None
            self._manual_edit_index = None
            self._manual_edit_confirmable = False
            self._last_display_position = None
            self._measurement_start = None
            self._measurement_start_snap_kind = None
            for editor in (*self._coordinate_value_labels, self._angle_editor):
                editor.setReadOnly(True)
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._measurement_start_marker.hide()
            self._hide_member_preview()
            self._hide_measurement_preview()
            self._hide_perpendicular_guide()
            self._hide_orthogonal_guide()
            return
        self._hover_timer.stop()
        if self._hovered is not None:
            self._hovered = None
            self._sync_highlights()
            self.plotter.render()
        self._update_coordinate_readout()
        self._update_measurement_readout()

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

    def view_state(self) -> dict[str, bool]:
        """Retorna o estado dos controles visuais da sessão de geometria."""
        return {
            "grid_visible": self._grid_visible,
            "reference_axes_visible": self._reference_axes_visible,
            "node_labels_visible": self._labels_visibility["node"],
            "member_labels_visible": self._labels_visibility["bar"],
            "local_axes_visible": self._local_axes_visible,
            "nodes_visible": self._nodes_visible,
            "solid_members_visible": self._solid_members_visible,
            "member_releases_visible": self._member_releases_visible,
            "semirigid_links_visible": self._semirigid_links_visible,
            "node_supports_visible": self._node_supports_visible,
            "snap_enabled": self._snap_enabled,
            "node_forces_visible": self._action_visibility["node_forces"],
            "node_moments_visible": self._action_visibility["node_moments"],
            "member_forces_visible": self._action_visibility["member_forces"],
            "member_moments_visible": self._action_visibility["member_moments"],
        }

    def analysis_view_state(self) -> dict[str, object]:
        """Retorna o estado visual da sessão de análise."""
        return {
            "selected_combination": self._active_analysis_combination,
            "selected_diagram": self._active_result_type,
            "result_diagrams_visible": self._result_diagrams_visible,
        }

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
                direction = 1.0
                if self._manual_edit_direction is not None:
                    component = float(self._manual_edit_direction[index])
                    if abs(component) > 1e-9:
                        direction = float(np.sign(component))
                value = float(self._member_preview_start[index]) + value * direction
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
            if self._member_preview_start is None:
                self._manual_edit_direction = None
            else:
                self._manual_edit_direction = (
                    self._manual_edit_target - self._member_preview_start
                )

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
        self._manual_edit_direction = None
        self._manual_edit_index = None
        self._manual_edit_confirmable = False
        for editor in (*self._coordinate_value_labels, self._angle_editor):
            editor.setReadOnly(True)
        if update:
            self._update_coordinate_readout()

    def _update_coordinate_readout(self) -> None:
        if not (self._member_placement_mode or self._node_placement_mode) or self._pointer_position is None:
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            if not self._measurement_mode:
                self._snap_marker.hide()
                self._hide_member_preview()
            return

        x, y = self._pointer_position
        if self._orientation_widget.is_pointer_over(int(x), int(y)):
            self._coordinate_readout.hide()
            self._angle_readout.hide()
            if not self._measurement_mode:
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

    def _update_measurement_readout(self) -> None:
        """Render the live delta box only after the first measurement click."""
        if (
            not self._measurement_mode
            or self._pointer_position is None
        ):
            self._measurement_readout.hide()
            self._measurement_start_marker.hide()
            self._hide_measurement_preview()
            if not self._member_placement_mode and not self._node_placement_mode:
                self._snap_marker.hide()
            return

        if self._camera_interacting:
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._measurement_start_marker.hide()
            return

        x, y = self._pointer_position
        if self._orientation_widget.is_pointer_over(int(x), int(y)):
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._measurement_start_marker.hide()
            self._hide_measurement_preview()
            return
        position = self._cursor_world_position()
        if position is None:
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._measurement_start_marker.hide()
            self._hide_measurement_preview()
            return
        display_position, snap_kind = self._measurement_target(position)

        # Before the first click the measurement tool only exposes the active
        # snap marker.  The delta panel starts after the first point is fixed.
        if self._measurement_start is None:
            self._measurement_readout.hide()
            self._measurement_start_marker.hide()
            self._hide_measurement_preview()
            if snap_kind is None:
                self._snap_marker.hide()
            else:
                self._position_snap_marker(display_position, snap_kind)
            return

        # The first point is fixed after the initial click.  Keep a lightweight
        # world-space line from it to the live (possibly snapped) endpoint so
        # the measured pair is obvious while the cursor moves.  This is the
        # same transient preview used by Add Member and is hidden on completion.
        self._update_measurement_preview(display_position)
        self._update_measurement_start_marker()
        delta = np.asarray(display_position, dtype=float) - self._measurement_start
        values = (
            float(np.linalg.norm(delta)),
            float(delta[0]),
            float(delta[1]),
            float(delta[2]),
        )
        for label, value in zip(self._measurement_value_labels, values):
            label.setText(f"{0.0 if abs(value) < 0.0005 else value:.3f} m")

        if snap_kind is None:
            self._snap_marker.hide()
        else:
            self._position_snap_marker(display_position, snap_kind)

        self._measurement_readout.adjustSize()
        offset = 16
        width = self._measurement_readout.width()
        height = self._measurement_readout.height()
        left = x + offset
        top = y + offset
        if left + width > self.plotter.width():
            left = x - width - offset
        if top + height > self.plotter.height():
            top = y - height - offset
        self._measurement_readout.move(
            max(0, min(int(left), self.plotter.width() - width)),
            max(0, min(int(top), self.plotter.height() - height)),
        )
        self._measurement_readout.show()
        self._measurement_readout.raise_()

    def _update_measurement_start_marker(self) -> None:
        if self._measurement_start_snap_kind is None or self._measurement_start is None:
            self._measurement_start_marker.hide()
            return
        self._position_snap_marker(
            self._measurement_start,
            self._measurement_start_snap_kind,
            marker=self._measurement_start_marker,
        )

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
        matrix, width, height = self._measurement_projection_context()
        pointer = np.asarray(self._pointer_position, dtype=float)

        # The grid is the construction plane's visible representation.  It
        # must not exert an invisible magnetic pull when the user turns the
        # plane off in the viewport palette.
        if self._snap_types["grid"] and self._grid_visible:
            grid_candidate = self._nearest_grid_candidate(
                position, projection=(matrix, width, height),
            )
            if grid_candidate is not None:
                candidate, distance = grid_candidate
                candidates.append((distance, 2, "grid", candidate))

        node_points, node_screens, node_visible, center_points, center_screens, center_visible = (
            self._projected_snap_points(matrix, width, height)
        )
        for enabled, points, screens, visible, priority, kind in (
            (self._snap_types["endpoint"], node_points, node_screens, node_visible, 0, "endpoint"),
            (self._snap_types["center"], center_points, center_screens, center_visible, 1, "center"),
        ):
            if not enabled or not len(points):
                continue
            distances = np.linalg.norm(screens - pointer, axis=1)
            distances[~visible] = np.inf
            index = int(np.argmin(distances))
            if distances[index] <= self._snap_tolerance_pixels:
                candidates.append((float(distances[index]), priority, kind, points[index]))

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

    def _projected_snap_points(
        self, matrix: np.ndarray, width: int, height: int,
    ) -> tuple[np.ndarray, ...]:
        """Reuse node and member-centre projections while the camera is still."""
        camera = self.plotter.renderer.GetActiveCamera()
        key = (
            id(self._model), self._model.revision, self._model.view_revision,
            int(camera.GetMTime()),
            width, height,
        )
        if self._projected_snap_cache is not None and self._projected_snap_cache[0] == key:
            return self._projected_snap_cache[1]

        visible_model = self._scene_filtered_model()
        node_points = np.asarray(
            [(node.x, node.y, node.z) for node in visible_model.nodes.values()],
            dtype=float,
        ).reshape((-1, 3))
        node_screens, node_visible = project_world_to_screen(
            node_points, matrix, width, height,
        )
        centers = []
        for member in visible_model.bars.values():
            start = visible_model.nodes.get(member.start_node)
            end = visible_model.nodes.get(member.end_node)
            if start is not None and end is not None:
                centers.append((
                    (start.x + end.x) * 0.5,
                    (start.y + end.y) * 0.5,
                    (start.z + end.z) * 0.5,
                ))
        center_points = np.asarray(centers, dtype=float).reshape((-1, 3))
        center_screens, center_visible = project_world_to_screen(
            center_points, matrix, width, height,
        )
        projected = (
            node_points, node_screens, node_visible,
            center_points, center_screens, center_visible,
        )
        self._projected_snap_cache = key, projected
        return projected

    def _measurement_target(self, position: np.ndarray) -> tuple[np.ndarray, str | None]:
        """Resolve a measurement point without changing the placement snaps."""
        if not self._snap_enabled or self._pointer_position is None:
            return np.asarray(position, dtype=float), None

        candidates: list[tuple[float, int, str, np.ndarray]] = []
        matrix, width, height = self._measurement_projection_context()
        pointer = np.asarray(self._pointer_position, dtype=float)
        depth_cache: dict[tuple[int, int], float] = {}

        if self._snap_types["grid"] and self._grid_visible:
            grid_candidate = self._nearest_grid_candidate(
                position, projection=(matrix, width, height),
            )
            if grid_candidate is not None:
                grid_point, distance = grid_candidate
                grid_screen, grid_visible = project_world_to_screen(
                    np.asarray([grid_point], dtype=float), matrix, width, height,
                )
                if (
                    distance <= self._snap_tolerance_pixels
                    and bool(grid_visible[0])
                    and self._measurement_visible_points(
                        grid_screen, np.asarray([grid_point], dtype=float),
                        matrix, depth_cache,
                    )[0]
                ):
                    candidates.append((distance, 5, "grid", np.asarray(grid_point, dtype=float)))

        node_points, node_screens, node_visible, center_points_array, center_screens, center_visible = (
            self._projected_snap_points(matrix, width, height)
        )
        if self._snap_types["endpoint"]:
            node_distances = np.linalg.norm(node_screens - pointer, axis=1)
            node_indices = np.flatnonzero(
                node_visible & (node_distances <= self._snap_tolerance_pixels)
            )
            if len(node_indices):
                node_depth_visible = self._measurement_visible_points(
                    node_screens[node_indices], node_points[node_indices],
                    matrix, depth_cache,
                )
            else:
                node_depth_visible = np.empty(0, dtype=bool)
            for index, visible in zip(node_indices, node_depth_visible):
                if not visible:
                    continue
                candidates.append(
                    (float(node_distances[index]), 0, "endpoint", node_points[index])
                )

        if self._snap_types["center"]:
            center_distances = np.linalg.norm(center_screens - pointer, axis=1)
            center_indices = np.flatnonzero(
                center_visible & (center_distances <= self._snap_tolerance_pixels)
            )
            if len(center_indices):
                center_depth_visible = self._measurement_visible_points(
                    center_screens[center_indices], center_points_array[center_indices],
                    matrix, depth_cache,
                )
            else:
                center_depth_visible = np.empty(0, dtype=bool)
            for index, visible in zip(center_indices, center_depth_visible):
                if not visible:
                    continue
                candidates.append(
                    (float(center_distances[index]), 3, "center", center_points_array[index])
                )

        segment_data, point_data = self._measurement_segments(matrix, width, height)
        screen_starts, screen_ends, world_starts, world_ends, kinds, priorities = segment_data
        if len(screen_starts):
            min_x, max_x, min_y, max_y = self._measurement_segment_bounds
            tolerance = self._snap_tolerance_pixels
            nearby = np.flatnonzero(
                (pointer[0] >= min_x - tolerance)
                & (pointer[0] <= max_x + tolerance)
                & (pointer[1] >= min_y - tolerance)
                & (pointer[1] <= max_y + tolerance)
            )
            near_starts = screen_starts[nearby]
            screen_deltas = screen_ends[nearby] - near_starts
            lengths_squared = np.einsum("ij,ij->i", screen_deltas, screen_deltas)
            fractions = np.divide(
                np.einsum("ij,ij->i", pointer - near_starts, screen_deltas),
                lengths_squared,
                out=np.zeros(len(nearby), dtype=float),
                where=lengths_squared > 1e-12,
            )
            fractions = np.clip(fractions, 0.0, 1.0)
            closest_screens = near_starts + fractions[:, None] * screen_deltas
            distances = np.linalg.norm(pointer - closest_screens, axis=1)
            local_indices = np.flatnonzero(distances <= tolerance)
            segment_indices = nearby[local_indices]
            if len(segment_indices):
                segment_fractions = fractions[local_indices]
                segment_worlds = world_starts[segment_indices] + segment_fractions[:, None] * (
                    world_ends[segment_indices] - world_starts[segment_indices]
                )
                segment_depth_visible = self._measurement_visible_points(
                    closest_screens[local_indices], segment_worlds,
                    matrix, depth_cache,
                    surface_points=np.asarray(
                        [str(kinds[index]).startswith(("edge", "silhouette"))
                         for index in segment_indices],
                        dtype=bool,
                    ),
                    edge_starts=world_starts[segment_indices],
                    edge_ends=world_ends[segment_indices],
                )
                visible_indices = segment_indices[segment_depth_visible]
                if len(visible_indices):
                    visible_distances = distances[local_indices][segment_depth_visible]
                    visible_order = np.lexsort(
                        (priorities[visible_indices], visible_distances)
                    )
                    chosen = int(visible_order[0])
                    segment_index = int(visible_indices[chosen])
                    candidates.append(
                        (
                            float(visible_distances[chosen]),
                            int(priorities[segment_index]),
                            kinds[segment_index],
                            world_starts[segment_index]
                            + segment_fractions[segment_depth_visible][chosen]
                            * (world_ends[segment_index] - world_starts[segment_index]),
                        )
                    )
        (
            point_screens, point_worlds, point_kinds, point_priorities,
            point_edge_starts, point_edge_ends,
        ) = point_data
        if len(point_screens):
            nearby = np.flatnonzero(
                (np.abs(point_screens[:, 0] - pointer[0]) <= self._snap_tolerance_pixels)
                & (np.abs(point_screens[:, 1] - pointer[1]) <= self._snap_tolerance_pixels)
            )
            point_distances = np.linalg.norm(point_screens[nearby] - pointer, axis=1)
            local_indices = np.flatnonzero(point_distances <= self._snap_tolerance_pixels)
            point_indices = nearby[local_indices]
            if len(point_indices):
                point_depth_visible = self._measurement_visible_points(
                    point_screens[point_indices], point_worlds[point_indices],
                    matrix, depth_cache,
                    surface_points=np.asarray(
                        [str(point_kinds[index]).startswith(("edge", "silhouette"))
                         for index in point_indices],
                        dtype=bool,
                    ),
                    edge_starts=point_edge_starts[point_indices],
                    edge_ends=point_edge_ends[point_indices],
                )
                visible_indices = point_indices[point_depth_visible]
                if len(visible_indices):
                    visible_distances = point_distances[local_indices][point_depth_visible]
                    visible_order = np.lexsort(
                        (point_priorities[visible_indices], visible_distances)
                    )
                    chosen = int(visible_order[0])
                    point_index = int(visible_indices[chosen])
                    candidates.append(
                        (
                            float(visible_distances[chosen]),
                            int(point_priorities[point_index]),
                            point_kinds[point_index],
                            point_worlds[point_index],
                        )
                    )

        candidates = [
            candidate for candidate in candidates
            if candidate[0] <= self._snap_tolerance_pixels
        ]
        if not candidates:
            return np.asarray(position, dtype=float), None
        _distance, _priority, kind, candidate = min(
            candidates, key=lambda item: (item[0], item[1])
        )
        return candidate, kind

    def _measurement_visible_points(
        self,
        screen_points: np.ndarray,
        world_points: np.ndarray,
        matrix: np.ndarray,
        depth_cache: dict[tuple[int, int], float],
        *,
        surface_points: np.ndarray | None = None,
        edge_starts: np.ndarray | None = None,
        edge_ends: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return points visible in the current camera view.

        Solid edge candidates are already tested against the first geometric
        face hit by their camera ray.  For those points the raster Z buffer is
        only a coarse, rounded pixel sample and can land on a neighboring face
        at a noticeably different depth.  Keep the geometric result for solid
        edges, while retaining the Z-buffer requirement for analytical lines,
        nodes and grid points.
        """
        if not len(screen_points):
            return np.empty(0, dtype=bool)
        render_window = self.plotter.render_window
        render_width, render_height = tuple(render_window.GetSize())
        widget_width, widget_height = self.plotter.width(), self.plotter.height()
        if (
            render_width <= 1 or render_height <= 1
            or widget_width <= 1 or widget_height <= 1
        ):
            return np.ones(len(screen_points), dtype=bool)

        pixel_x = np.rint(
            np.asarray(screen_points, dtype=float)[:, 0]
            * float(render_width - 1) / float(widget_width - 1)
        ).astype(int)
        pixel_y = np.rint(
            (float(widget_height - 1) - np.asarray(screen_points, dtype=float)[:, 1])
            * float(render_height - 1) / float(widget_height - 1)
        ).astype(int)
        pixel_x = np.clip(pixel_x, 0, render_width - 1)
        pixel_y = np.clip(pixel_y, 0, render_height - 1)
        display_x = np.clip(
            np.asarray(screen_points, dtype=float)[:, 0]
            * float(render_width - 1) / float(widget_width - 1),
            0.0, float(render_width - 1),
        )
        display_y = np.clip(
            (float(widget_height - 1) - np.asarray(screen_points, dtype=float)[:, 1])
            * float(render_height - 1) / float(widget_height - 1),
            0.0, float(render_height - 1),
        )

        surface_mask = None
        if surface_points is not None:
            surface_mask = np.asarray(surface_points, dtype=bool)
            if len(surface_mask) != len(world_points):
                surface_mask = np.zeros(len(world_points), dtype=bool)
            # Most calls contain only profile edge candidates.  Their raster
            # depths are intentionally not used, so avoid thousands of
            # redundant Z-buffer reads on every mouse move.
            if np.all(surface_mask):
                return self._measurement_solid_visible_points(
                    world_points, display_x, display_y,
                    edge_starts=edge_starts, edge_ends=edge_ends,
                )

        unique_pixels, inverse = np.unique(
            np.column_stack((pixel_x, pixel_y)), axis=0, return_inverse=True,
        )
        scene_depths = np.empty(len(unique_pixels), dtype=float)
        for index, (x, y) in enumerate(unique_pixels):
            key = int(x), int(y)
            if key not in depth_cache:
                try:
                    depth_cache[key] = float(
                        render_window.GetZbufferDataAtPoint(key[0], key[1])
                    )
                except (TypeError, ValueError, RuntimeError):
                    depth_cache[key] = float("nan")
            scene_depths[index] = depth_cache[key]

        points = np.asarray(world_points, dtype=float)
        homogeneous = np.column_stack((points, np.ones(len(points))))
        clip = homogeneous @ np.asarray(matrix, dtype=float).T
        safe_w = np.where(np.abs(clip[:, 3]) > 1e-12, clip[:, 3], 1.0)
        normalized_depth = (clip[:, 2] / safe_w + 1.0) * 0.5
        sampled_depth = scene_depths[inverse]
        valid_depth = np.isfinite(sampled_depth) & (sampled_depth < 1.0)
        visible = ~valid_depth
        visible[valid_depth] = (
            normalized_depth[valid_depth] <= sampled_depth[valid_depth] + 0.01
        )

        solid_visible = self._measurement_solid_visible_points(
            world_points, display_x, display_y,
            edge_starts=edge_starts, edge_ends=edge_ends,
        )
        if surface_mask is None:
            return visible & solid_visible
        # A visible profile edge lies precisely between raster pixels.  Its
        # one-pixel Z-buffer sample can therefore belong to the adjacent face
        # (or even to the background), which made an edge snap depend on zoom
        # level and which side of the member happened to cover that pixel.
        # The face locator tests the actual camera ray against solid geometry,
        # so it is the authoritative visibility test for feature edges.  Keep
        # the raster test for every other target, such as nodes, grid points
        # and analytical member lines.
        return np.where(surface_mask, solid_visible, visible & solid_visible)

    def _measurement_solid_visible_points(
        self,
        world_points: np.ndarray,
        display_x: np.ndarray,
        display_y: np.ndarray,
        *,
        edge_starts: np.ndarray | None = None,
        edge_ends: np.ndarray | None = None,
    ) -> np.ndarray:
        """Reject points behind the first solid face hit by the camera ray."""
        actor = self._member_face_actor
        if (
            actor is None
            or not actor.GetVisibility()
            or not self._solid_members_visible
        ):
            return np.ones(len(world_points), dtype=bool)

        locator = self._measurement_face_locator_for_current_batch()
        if locator is None:
            return np.ones(len(world_points), dtype=bool)

        visible = np.ones(len(world_points), dtype=bool)
        renderer = self.plotter.renderer
        unique_display_points, inverse = np.unique(
            np.column_stack((display_x, display_y)), axis=0, return_inverse=True,
        )
        hit_parameters = np.full(len(unique_display_points), np.nan, dtype=float)
        hit_cell_ids = np.full(len(unique_display_points), -1, dtype=np.int64)
        ray_nears = np.empty((len(unique_display_points), 3), dtype=float)
        ray_vectors = np.empty((len(unique_display_points), 3), dtype=float)
        ray_lengths = np.empty(len(unique_display_points), dtype=float)
        for index, (x, y) in enumerate(unique_display_points):
            near = self._display_to_world(renderer, float(x), float(y), 0.0)
            far = self._display_to_world(renderer, float(x), float(y), 1.0)
            if near is None or far is None:
                continue
            ray = np.asarray(far, dtype=float) - np.asarray(near, dtype=float)
            ray_length = float(np.linalg.norm(ray))
            if ray_length <= 1e-12:
                continue
            ray_nears[index] = near
            ray_vectors[index] = ray
            ray_lengths[index] = ray_length
            hit_points = vtk.vtkPoints()
            hit_cells = vtk.vtkIdList()
            if not locator.IntersectWithLine(
                tuple(near), tuple(far), 1e-9,
                hit_points, hit_cells,
            ):
                continue
            intersection_points = np.asarray(
                [hit_points.GetPoint(point_index) for point_index in range(hit_points.GetNumberOfPoints())],
                dtype=float,
            )
            intersection_parameters = np.einsum(
                "ij,j->i", intersection_points - near, ray,
            )
            closest_intersection = int(np.argmin(intersection_parameters))
            hit_parameters[index] = float(
                intersection_parameters[closest_intersection] / (ray_length * ray_length)
            )
            hit_cell_ids[index] = int(hit_cells.GetId(closest_intersection))

        candidate_nears = ray_nears[inverse]
        candidate_rays = ray_vectors[inverse]
        candidate_ray_squared = np.einsum("ij,ij->i", candidate_rays, candidate_rays)
        candidate_parameters = np.divide(
            np.einsum("ij,ij->i", np.asarray(world_points, dtype=float) - candidate_nears, candidate_rays),
            candidate_ray_squared,
            out=np.zeros(len(world_points), dtype=float),
            where=candidate_ray_squared > 1e-12,
        )
        valid_depth = np.isfinite(hit_parameters[inverse])
        tolerance = np.divide(
            5e-4, ray_lengths[inverse],
            out=np.full(len(world_points), 1e-8, dtype=float),
            where=ray_lengths[inverse] > 1e-12,
        )
        visible[valid_depth] = (
            candidate_parameters[valid_depth]
            <= hit_parameters[inverse][valid_depth] + tolerance[valid_depth]
        )
        # A feature edge is a topological boundary shared by one or more
        # faces. At an exact raster boundary, a ray can land a few floating
        # point units inside one of those adjacent faces. Treat that as the
        # same visible entity. Crucially, this does not admit a hidden edge:
        # a face from another part (or the front face of the same solid) has a
        # different topology and remains rejected.
        if edge_starts is not None and edge_ends is not None:
            starts = np.asarray(edge_starts, dtype=float)
            ends = np.asarray(edge_ends, dtype=float)
            if starts.shape == (len(world_points), 3) and ends.shape == starts.shape:
                rejected = np.flatnonzero(valid_depth & ~visible)
                if len(rejected):
                    faces = self._member_batch.faces
                    for point_index in rejected:
                        hit_cell = int(hit_cell_ids[inverse[point_index]])
                        if hit_cell >= 0 and self._measurement_face_contains_edge(
                            faces, hit_cell, starts[point_index], ends[point_index],
                        ):
                            visible[point_index] = True
        return visible

    @staticmethod
    def _measurement_edge_key(start: np.ndarray, end: np.ndarray) -> tuple[float, ...]:
        """Canonical key for an undirected topological edge."""
        first = tuple(np.round(np.asarray(start, dtype=float), decimals=9))
        second = tuple(np.round(np.asarray(end, dtype=float), decimals=9))
        return (*first, *second) if first <= second else (*second, *first)

    def _measurement_face_contains_edge(
        self, faces: pv.PolyData, cell_id: int,
        start: np.ndarray, end: np.ndarray,
    ) -> bool:
        """Check only the face hit by the camera ray for a shared edge."""
        target = self._measurement_edge_key(start, end)
        point_ids = faces.GetCell(cell_id).GetPointIds()
        count = point_ids.GetNumberOfIds()
        for index in range(count):
            first = faces.points[point_ids.GetId(index)]
            second = faces.points[point_ids.GetId((index + 1) % count)]
            if self._measurement_edge_key(first, second) == target:
                return True
        return False

    def _measurement_face_locator_for_current_batch(self) -> vtk.vtkCellLocator | None:
        """Return a cached locator for all visible solid member faces."""
        batch = self._member_batch
        if batch is None or not batch.faces.n_cells:
            return None
        key = id(batch.faces), self._model.revision
        if self._measurement_face_locator_key == key:
            return self._measurement_face_locator
        locator = vtk.vtkCellLocator()
        locator.SetDataSet(batch.faces)
        locator.BuildLocator()
        self._measurement_face_locator = locator
        self._measurement_face_locator_key = key
        return locator

    @staticmethod
    def _measurement_normalized_depth(
        world_points: np.ndarray, matrix: np.ndarray,
    ) -> np.ndarray:
        points = np.asarray(world_points, dtype=float)
        homogeneous = np.column_stack((points, np.ones(len(points))))
        clip = homogeneous @ np.asarray(matrix, dtype=float).T
        safe_w = np.where(np.abs(clip[:, 3]) > 1e-12, clip[:, 3], 1.0)
        return clip[:, 2] / safe_w

    def _measurement_projection_context(self) -> tuple[np.ndarray, int, int]:
        """Build one camera projection context for the current mouse update."""
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        vtk_matrix = camera.GetCompositeProjectionTransformMatrix(
            renderer.GetTiledAspectRatio(), -1.0, 1.0,
        )
        matrix = np.asarray([
            [vtk_matrix.GetElement(row, column) for column in range(4)]
            for row in range(4)
        ])
        return matrix, self.plotter.width(), self.plotter.height()

    def _measurement_segments(
        self, matrix: np.ndarray, width: int, height: int,
    ) -> tuple[tuple, tuple]:
        """Return projected snap segments, rebuilding only after a camera change."""
        solid_visible = bool(
            self._solid_members_visible
            and self._member_edge_actor is not None
            and self._member_edge_actor.GetVisibility()
        )
        silhouette_visible = bool(
            self._member_silhouette_actor is not None
            and self._member_silhouette_actor.GetVisibility()
        )
        camera = self.plotter.renderer.GetActiveCamera()
        key = (
            self._model.revision,
            id(self._member_batch),
            int(camera.GetMTime()),
            width,
            height,
            solid_visible,
            silhouette_visible,
        )
        if self._measurement_segments_cache is not None:
            cached_key, cached_segments = self._measurement_segments_cache
            if cached_key == key:
                return cached_segments

        meshes: list[tuple[pv.PolyData, str, int, bool]] = []
        if solid_visible and self._member_batch is not None:
            meshes.append((self._member_batch.edges, "edge", 1, True))
            if silhouette_visible and self._member_silhouette_actor is not None:
                vtk_mesh = self._member_silhouette_actor.GetMapper().GetInput()
                if vtk_mesh is not None:
                    meshes.append((pv.wrap(vtk_mesh), "silhouette", 1, True))
        elif self._member_batch is not None:
            meshes.append((self._member_batch.lines, "line", 2, True))
        if self._rigid_bar_mesh is not None:
            meshes.append((self._rigid_bar_mesh, "line", 2, True))

        segment_groups = []
        point_groups = []
        for mesh, kind, priority, discrete in meshes:
            arrays = self._measurement_mesh_arrays(
                mesh, kind, priority, matrix, width, height,
                discrete=discrete,
            )
            if arrays is None:
                # Polyline cells are uncommon here, but retain their original
                # per-segment behaviour for arbitrary imported line meshes.
                segments: list[tuple] = []
                points: list[tuple] = []
                self._append_measurement_mesh_segments(
                    segments, mesh, kind, priority, matrix, width, height,
                    points if discrete else None,
                )
                arrays = self._measurement_segment_arrays(segments), self._measurement_point_arrays(points)
            segment_groups.append(arrays[0])
            point_groups.append(arrays[1])
        segment_arrays = self._combine_measurement_arrays(
            segment_groups, self._measurement_segment_arrays([]),
        )
        point_arrays = self._combine_measurement_arrays(
            point_groups, self._measurement_point_arrays([]),
        )
        starts, ends = segment_arrays[:2]
        self._measurement_segment_bounds = (
            np.minimum(starts[:, 0], ends[:, 0]),
            np.maximum(starts[:, 0], ends[:, 0]),
            np.minimum(starts[:, 1], ends[:, 1]),
            np.maximum(starts[:, 1], ends[:, 1]),
        )
        cached_segments = segment_arrays, point_arrays
        self._measurement_segments_cache = key, cached_segments
        return cached_segments

    @staticmethod
    def _combine_measurement_arrays(groups: list[tuple], empty: tuple) -> tuple:
        if not groups:
            return empty
        return tuple(
            tuple(value for group in groups for value in group[index])
            if isinstance(empty[index], tuple)
            else np.concatenate([group[index] for group in groups], axis=0)
            for index in range(len(empty))
        )

    def _measurement_mesh_arrays(
        self, mesh: pv.PolyData, kind: str, priority: int,
        matrix: np.ndarray, width: int, height: int, *, discrete: bool,
    ) -> tuple[tuple, tuple] | None:
        """Project the usual two-point VTK lines without a Python loop per edge."""
        if mesh is None or not mesh.n_lines or not mesh.n_points:
            return self._measurement_segment_arrays([]), self._measurement_point_arrays([])
        encoded = np.asarray(mesh.lines, dtype=np.int64)
        if len(encoded) % 3 or not np.all(encoded[::3] == 2):
            return None
        point_ids = encoded.reshape((-1, 3))[:, 1:]
        world = np.asarray(mesh.points, dtype=float)
        screen, visible = project_world_to_screen(
            world, matrix, width, height, clip_to_viewport=False,
        )
        point_ids = point_ids[visible[point_ids].all(axis=1)]
        starts = world[point_ids[:, 0]]
        ends = world[point_ids[:, 1]]
        screen_starts = screen[point_ids[:, 0]]
        screen_ends = screen[point_ids[:, 1]]
        count = len(point_ids)
        segments = (
            screen_starts, screen_ends, starts, ends,
            (kind,) * count,
            np.full(count, priority, dtype=np.int8),
        )
        if not discrete or not count:
            return segments, self._measurement_point_arrays([])

        midpoints = (starts + ends) * 0.5
        midpoint_screens, midpoint_visible = project_world_to_screen(
            midpoints, matrix, width, height, clip_to_viewport=False,
        )
        visible_midpoints = np.flatnonzero(midpoint_visible)
        endpoint_screens = np.stack((screen_starts, screen_ends), axis=1).reshape((-1, 2))
        endpoint_worlds = np.stack((starts, ends), axis=1).reshape((-1, 3))
        repeated_starts = np.repeat(starts, 2, axis=0)
        repeated_ends = np.repeat(ends, 2, axis=0)
        points = (
            np.concatenate((endpoint_screens, midpoint_screens[visible_midpoints])),
            np.concatenate((endpoint_worlds, midpoints[visible_midpoints])),
            (f"{kind}-endpoint",) * (2 * count)
            + (f"{kind}-midpoint",) * len(visible_midpoints),
            np.concatenate((
                np.zeros(2 * count, dtype=np.int8),
                np.ones(len(visible_midpoints), dtype=np.int8),
            )),
            np.concatenate((repeated_starts, starts[visible_midpoints])),
            np.concatenate((repeated_ends, ends[visible_midpoints])),
        )
        return segments, points

    @staticmethod
    def _measurement_segment_arrays(segments: list[tuple]) -> tuple:
        if not segments:
            return (
                np.empty((0, 2), dtype=float),
                np.empty((0, 2), dtype=float),
                np.empty((0, 3), dtype=float),
                np.empty((0, 3), dtype=float),
                (),
                np.empty(0, dtype=np.int8),
            )
        return (
            np.asarray([segment[0] for segment in segments], dtype=float),
            np.asarray([segment[1] for segment in segments], dtype=float),
            np.asarray([segment[2] for segment in segments], dtype=float),
            np.asarray([segment[3] for segment in segments], dtype=float),
            tuple(str(segment[4]) for segment in segments),
            np.asarray([int(segment[5]) for segment in segments], dtype=np.int8),
        )

    @staticmethod
    def _measurement_point_arrays(points: list[tuple]) -> tuple:
        if not points:
            return (
                np.empty((0, 2), dtype=float),
                np.empty((0, 3), dtype=float),
                (),
                np.empty(0, dtype=np.int8),
                np.empty((0, 3), dtype=float),
                np.empty((0, 3), dtype=float),
            )
        return (
            np.asarray([point[0] for point in points], dtype=float),
            np.asarray([point[1] for point in points], dtype=float),
            tuple(str(point[2]) for point in points),
            np.asarray([int(point[3]) for point in points], dtype=np.int8),
            np.asarray([point[4] for point in points], dtype=float),
            np.asarray([point[5] for point in points], dtype=float),
        )

    def _append_measurement_mesh_segments(
        self,
        segments: list[tuple],
        mesh: pv.PolyData,
        kind: str,
        priority: int,
        matrix: np.ndarray,
        width: int,
        height: int,
        discrete_points: list[tuple] | None = None,
    ) -> None:
        """Project one line mesh in a single NumPy pass and cache its segments."""
        if mesh is None or not mesh.n_lines or not mesh.n_points:
            return
        screen_points, visible = project_world_to_screen(
            np.asarray(mesh.points, dtype=float), matrix, width, height,
            clip_to_viewport=False,
        )
        midpoint_records: list[tuple[np.ndarray, str, int, np.ndarray, np.ndarray]] = []
        encoded = np.asarray(mesh.lines, dtype=np.int64)
        cursor = 0
        while cursor < len(encoded):
            count = int(encoded[cursor])
            point_ids = encoded[cursor + 1:cursor + 1 + count]
            cursor += count + 1
            if count < 2:
                continue
            for first_id, second_id in zip(point_ids[:-1], point_ids[1:]):
                first_index = int(first_id)
                second_index = int(second_id)
                if not visible[first_index] or not visible[second_index]:
                    continue
                first_screen = screen_points[first_index]
                second_screen = screen_points[second_index]
                first_world = np.asarray(mesh.points[first_index], dtype=float)
                second_world = np.asarray(mesh.points[second_index], dtype=float)
                if discrete_points is None:
                    segments.append(
                        (
                            first_screen, second_screen,
                            first_world, second_world,
                            kind, priority,
                        )
                    )
                    continue
                endpoint_kind = f"{kind}-endpoint"
                midpoint_kind = f"{kind}-midpoint"
                discrete_points.append((
                    first_screen, first_world, endpoint_kind, 0, first_world, second_world,
                ))
                discrete_points.append((
                    second_screen, second_world, endpoint_kind, 0, first_world, second_world,
                ))
                midpoint_world = (first_world + second_world) * 0.5
                midpoint_records.append((
                    midpoint_world, midpoint_kind, 1, first_world, second_world,
                ))

        if midpoint_records and discrete_points is not None:
            midpoint_worlds = np.asarray(
                [record[0] for record in midpoint_records], dtype=float,
            )
            midpoint_screens, midpoint_visible = project_world_to_screen(
                midpoint_worlds, matrix, width, height, clip_to_viewport=False,
            )
            for screen, (world, midpoint_type, midpoint_priority, edge_start, edge_end), is_visible in zip(
                midpoint_screens, midpoint_records, midpoint_visible,
            ):
                if is_visible:
                    discrete_points.append((
                        screen, world, midpoint_type, midpoint_priority, edge_start, edge_end,
                    ))

    def _snap_to_grid(self, position: np.ndarray) -> np.ndarray | None:
        """Return the nearest grid intersection for compatibility callers."""
        if not self._snap_enabled or not self._snap_types["grid"] or not self._grid_visible:
            return None
        candidate = self._nearest_grid_candidate(position)
        if candidate is None or candidate[1] > self._snap_tolerance_pixels:
            return None
        return candidate[0]

    def _nearest_grid_candidate(
        self,
        position: np.ndarray,
        *,
        projection: tuple[np.ndarray, int, int] | None = None,
    ) -> tuple[np.ndarray, float] | None:
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
                if projection is None:
                    screen, visible = self._world_to_screen(candidate)
                else:
                    matrix, width, height = projection
                    projected, visible_values = project_world_to_screen(
                        np.asarray([candidate], dtype=float), matrix, width, height,
                    )
                    screen = projected[0]
                    visible = bool(visible_values[0])
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

    def _position_snap_marker(
        self,
        position: np.ndarray,
        kind: str | None,
        *,
        marker: SnapMarker | None = None,
    ) -> None:
        marker = self._snap_marker if marker is None else marker
        screen, visible = self._world_to_screen(position)
        if not visible:
            marker.hide()
            return
        marker_kind = {
            "grid": "grid",
            "endpoint": "endpoint",
            "center": "center",
            "edge-endpoint": "endpoint",
            "silhouette-endpoint": "endpoint",
            "line-endpoint": "endpoint",
            "edge-midpoint": "center",
            "silhouette-midpoint": "center",
            "line-midpoint": "center",
        }.get(kind or "grid", "grid")
        marker.set_kind(marker_kind)
        marker.move(
            int(round(float(screen[0]) - marker.width() / 2.0)),
            int(round(float(screen[1]) - marker.height() / 2.0)),
        )
        marker.show()
        marker.raise_()

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

    def _update_measurement_preview(self, endpoint: np.ndarray | None) -> None:
        """Show the transient line from the fixed measurement start point."""
        start = self._measurement_start
        if start is None or endpoint is None or not self._measurement_mode:
            self._hide_measurement_preview()
            return
        if float(np.linalg.norm(endpoint - start)) <= 1e-12:
            self._hide_measurement_preview()
            return
        mesh = pv.Line(tuple(start), tuple(endpoint))
        if self._measurement_preview_actor is None:
            self._measurement_preview_actor = self.plotter.add_mesh(
                mesh,
                color="#0969da",
                line_width=3.0,
                render_lines_as_tubes=True,
                lighting=False,
                pickable=False,
                reset_camera=False,
                render=False,
            )
            self._measurement_preview_actor.SetObjectName("measurement-preview")
        else:
            mapper = self._measurement_preview_actor.GetMapper()
            mapper.SetInputData(mesh)
            mapper.Modified()
        self._measurement_preview_actor.SetVisibility(True)

    def _hide_measurement_preview(self) -> None:
        if self._measurement_preview_actor is not None:
            self._measurement_preview_actor.SetVisibility(False)

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
        if self._camera_interacting or self._placement_active():
            return
        picked = self._pick()
        if picked == self._hovered:
            return
        self._hovered = picked
        self._sync_highlights()
        self.plotter.render()

    def _on_selection_press(self, _caller, *_args) -> None:
        self._selection_press = None
        self._selection_dragged = False
        x, y = self.plotter.iren.get_event_position()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        if self._placement_active():
            return
        self._selection_press = int(x), int(y)

    def _on_selection_release(self, _caller, *_args) -> None:
        start = self._selection_press
        dragged = self._selection_dragged
        self._selection_press = None
        self._selection_dragged = False
        if start is None or dragged or self._placement_active():
            return
        x, y = self.plotter.iren.get_event_position()
        if (
            self._orientation_widget.is_pointer_over(x, y)
            or np.hypot(x - start[0], y - start[1]) > self._placement_drag_tolerance_pixels
        ):
            return
        position = (int(x), int(y))
        picked = (
            self._hovered
            if position == self._tab_hover_position
            and self._hovered in self._tab_hover_candidates
            else self._pick()
        )
        self._selected = picked
        self._selected_elements = () if picked is None else (picked,)
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
        if self._measurement_mode:
            target, _snap_kind = self._measurement_target(position)
            return target
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
        selected_elements = self._selected_elements or (
            (self._selected,) if self._selected is not None else ()
        )
        groups: dict[str, list[tuple[str, str]]] = {}
        for kind, name in selected_elements:
            if kind == "node":
                continue
            slot = f"selected:{kind}"
            if (
                kind == "bar" and self._solid_members_visible
                and self._model.bars.get(name) is not None
                and self._model.bars[name].section in self._member_renderer._silhouette_sections
            ):
                slot = "selected:circular"
            groups.setdefault(slot, []).append((kind, name))
        desired = {slot: tuple(targets) for slot, targets in groups.items()}
        selected_targets = set(selected_elements)
        hover = None if self._hovered in selected_targets else self._hovered
        if hover is not None and hover[0] != "node":
            desired["hover"] = (hover,)

        node_colors = {
            name: "#0969da" for kind, name in selected_elements if kind == "node"
        }
        if hover is not None and hover[0] == "node":
            node_colors[hover[1]] = "#4b5563"

        state_key = (
            id(self._model), self._model.revision,
            id(self._member_batch),
            id(self._node_batch.geometry) if self._node_batch is not None else None,
            id(self._rigid_bar_mesh), self._solid_members_visible,
        )
        force = state_key != self._highlight_state_key
        if not force and desired == self._highlight_targets and node_colors == self._highlighted_node_colors:
            return
        changed = {
            slot for slot in self._highlight_targets.keys() | desired.keys()
            if force or self._highlight_targets.get(slot) != desired.get(slot)
        }
        for slot in changed:
            self._replace_highlight(slot, None, "#0969da")
        for slot, targets in desired.items():
            if slot in changed:
                color = "#0969da" if slot.startswith("selected") else "#24292f"
                self._replace_highlight(slot, targets, color)

        self._sync_node_highlight_colors(node_colors, force=force)
        self._highlight_targets = desired
        self._highlighted_node_colors = node_colors
        self._highlight_state_key = state_key

    def _replace_highlight(
        self, slot: str, targets: tuple[tuple[str, str], ...] | None, color: str,
    ) -> None:
        previous = self._highlight_actors.pop(slot, None)
        if previous is not None:
            self.plotter.remove_actor(previous, reset_camera=False, render=False)
        if not targets:
            return
        kind, name = targets[0]
        if kind in {"bar", "rigid_bar"}:
            mesh = self._batched_highlight_mesh(targets, slot)
            if mesh is None or not mesh.n_cells:
                return
            actor = self.plotter.add_mesh(
                mesh,
                color=color,
                line_width=self._highlight_line_width(slot, kind, name if kind == "bar" else None),
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
            actor.SetVisibility(self._nodes_visible)
        actor.SetObjectName(f"highlight:{slot}")
        self._highlight_actors[slot] = actor

    def _batched_highlight_mesh(
        self, targets: tuple[tuple[str, str], ...], slot: str,
    ) -> pv.PolyData | None:
        """Merge selected strokes into one actor without changing their shape."""
        kind = targets[0][0]
        if slot == "hover" and kind == "bar":
            return self._member_highlight_mesh(targets[0][1])
        if kind == "rigid_bar" or (kind == "bar" and not self._solid_members_visible):
            elements = self._model.rigid_bars if kind == "rigid_bar" else self._model.bars
            points = np.empty((len(targets) * 2, 3), dtype=float)
            count = 0
            for _, name in targets:
                element = elements.get(name)
                if element is None:
                    continue
                start = self._model.nodes.get(element.start_node)
                end = self._model.nodes.get(element.end_node)
                if start is None or end is None:
                    continue
                points[count * 2] = (start.x, start.y, start.z)
                points[count * 2 + 1] = (end.x, end.y, end.z)
                count += 1
            if not count:
                return None
            lines = np.empty((count, 3), dtype=np.int64)
            lines[:, 0] = 2
            lines[:, 1] = np.arange(count, dtype=np.int64) * 2
            lines[:, 2] = lines[:, 1] + 1
            return pv.PolyData(points[:count * 2], lines=lines.ravel())

        batch = self._reveal_preview_batch if self._scene_selection_mode == "reveal" else self._member_batch
        if slot == "selected:circular" and batch is not None:
            surfaces = vtk.vtkAppendPolyData()
            fallback = []
            for _, name in targets:
                source = batch.silhouette_sources.get(name)
                if source is None:
                    fallback.append(("bar", name))
                else:
                    surfaces.AddInputData(source)
            surfaces.Update()
            contour = self._member_renderer.solids.silhouette_for(
                pv.wrap(surfaces.GetOutput()), self.plotter.renderer.GetActiveCamera(),
            )
            if not fallback:
                return contour
            extra = self._batched_highlight_mesh(tuple(fallback), "selected:fallback")
            if extra is None:
                return contour
            append = vtk.vtkAppendPolyData()
            append.AddInputData(contour)
            append.AddInputData(extra)
            append.Update()
            return pv.wrap(append.GetOutput())

        points: list[np.ndarray] = []
        lines: list[np.ndarray] = []
        offset = 0
        for _, name in targets:
            source = batch.outlines.source(name) if batch is not None else None
            if source is None:
                member = self._model.bars.get(name)
                if member is None:
                    continue
                start = self._model.nodes[member.start_node]
                end = self._model.nodes[member.end_node]
                segment = np.asarray(((start.x, start.y, start.z),
                                      (end.x, end.y, end.z)), dtype=float)
                source = segment, np.asarray((2, 0, 1), dtype=np.int64)
            source_points, source_lines = source
            points.append(source_points)
            lines.append(_offset_cells(source_lines, offset))
            offset += len(source_points)
        if not points:
            return None
        return pv.PolyData(np.vstack(points), lines=np.concatenate(lines))

    def _sync_node_highlight_colors(self, node_colors: dict[str, str], *, force: bool) -> None:
        """Recolor selected node glyphs with one VTK data update."""
        batch = self._node_batch
        if batch is None:
            return
        old_colors = self._highlighted_node_colors
        changed = {
            name for name in old_colors.keys() | node_colors.keys()
            if force or old_colors.get(name) != node_colors.get(name)
        }
        if not changed:
            return
        values = batch.geometry.cell_data.get("rgb")
        indices = batch.geometry.cell_data.get("element_index")
        if values is None or indices is None:
            return
        positions = {name: index for index, name in enumerate(batch.names)}
        rgb = {
            color: np.asarray(pv.Color(color).int_rgb, dtype=np.uint8)
            for color in set(node_colors.values()) | {"#000000"}
        }
        glyph_colors = (
            self._node_glyph_points.point_data["rgb"]
            if self._node_glyph_points is not None else None
        )
        if len(changed) > 8:
            palette = np.zeros((len(batch.names), 3), dtype=np.uint8)
            for name, color in node_colors.items():
                if (index := positions.get(name)) is not None:
                    palette[index] = rgb[color]
            values[:] = palette[np.asarray(indices, dtype=np.intp)]
            if glyph_colors is not None:
                glyph_colors[:] = palette
        else:
            for name in changed:
                index = positions.get(name)
                if index is None:
                    continue
                color = rgb[node_colors.get(name, "#000000")]
                first = int(np.searchsorted(indices, index, side="left"))
                last = int(np.searchsorted(indices, index, side="right"))
                values[first:last] = color
                if glyph_colors is not None:
                    glyph_colors[index] = color
        if self._node_glyph_points is not None:
            self._node_glyph_points.GetPointData().GetArray("rgb").Modified()
            self._node_glyph_points.Modified()
        batch.geometry.GetCellData().GetArray("rgb").Modified()
        batch.geometry.GetCellData().Modified()
        batch.geometry.Modified()

    def _highlight_line_width(
        self, slot: str, kind: str = "bar", member_name: str | None = None,
    ) -> float:
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
        if slot == "selected:circular":
            return self._circular_silhouette_line_width
        if self._solid_members_visible and kind == "bar":
            member = self._model.bars.get(member_name) if member_name is not None else None
            if member is not None and member.section in self._member_renderer._silhouette_sections:
                return self._circular_silhouette_line_width
            return self._solid_highlight_line_width
        padding = (
            self._selected_highlight_padding
            if slot.startswith("selected") else self._hover_highlight_padding
        )
        return max(1.0, width + padding)

    def _member_highlight_mesh(self, name: str) -> pv.PolyData | None:
        member = self._model.bars.get(name)
        if member is not None:
            batch = self._reveal_preview_batch if self._scene_selection_mode == "reveal" else self._member_batch
            if self._solid_members_visible and batch is not None:
                source = batch.silhouette_sources.get(name)
                if source is not None:
                    return self._member_renderer.solids.silhouette_for(
                        source, self.plotter.renderer.GetActiveCamera(),
                    )
                outline = batch.outlines.get(name)
                if outline is not None and outline.n_cells:
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
        if self._member_silhouette_actor is not None:
            self._member_silhouette_actor.SetVisibility(solid)
        if self._member_fallback_actor is not None:
            self._member_fallback_actor.SetVisibility(solid)
        if self._reveal_preview_line_actor is not None:
            self._reveal_preview_line_actor.SetVisibility(not solid)
        if self._reveal_preview_face_actor is not None:
            self._reveal_preview_face_actor.SetVisibility(solid)
        if self._reveal_preview_fallback_actor is not None:
            self._reveal_preview_fallback_actor.SetVisibility(solid)

    def set_scene_selection_mode(self, mode: str | None) -> None:
        if mode not in (None, "hide", "reveal"):
            raise ValueError("Modo de seleção da cena inválido.")
        self._scene_selection_mode = mode
        self._pick_projection_cache = None
        self._hovered = None
        self._tab_hover_candidates = []
        self._tab_hover_position = None
        self.render_model(self._model)

    def set_solid_members_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._solid_members_visible:
            return
        self._solid_members_visible = visible
        self._member_renderer.position_indicators_with_section = visible
        self._elastic_support_overlay.follow_section = visible
        self._hovered = None
        self._tab_hover_candidates = []
        self._tab_hover_position = None
        self.render_model(self._model)

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

    def set_nodes_visible(self, visible: bool) -> None:
        """Show or hide the node markers without changing node identifiers."""
        self._nodes_visible = bool(visible)
        if self._node_actor is not None:
            self._node_actor.SetVisibility(self._nodes_visible)
        self.plotter.render()

    def set_member_releases_visible(self, visible: bool) -> None:
        self._member_releases_visible = bool(visible)
        if self._release_actor is not None:
            self._release_actor.SetVisibility(visible)
        self.plotter.render()

    def set_semirigid_links_visible(self, visible: bool) -> None:
        self._semirigid_links_visible = bool(visible)
        self._elastic_support_overlay.set_visible(visible)
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
        if self._actions_visible:
            self._refresh_action_layer()
        else:
            self._action_layer_key = None

    def set_actions_visible(self, visible: bool) -> None:
        """Exibe ações somente quando a seção Ações estiver ativa."""
        visible = bool(visible)
        if visible == self._actions_visible:
            return
        self._actions_visible = visible
        current_key = (
            id(self._model), self._model.revision, self._model.view_revision, self._active_load_case,
            tuple(sorted(self._action_visibility.items())),
        )
        if not visible and self._action_actors:
            for actor in self._action_actors:
                actor.SetVisibility(False)
            self._label_overlay.set_group_visible("action", False)
            self.plotter.render()
            return
        if visible and self._action_layer_key == current_key:
            for actor in self._action_actors:
                actor.SetVisibility(True)
            self._label_overlay.set_group_visible("action", True)
            self.plotter.render()
            return
        self._refresh_action_layer()

    def set_analysis_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible == self._analysis_visible:
            return
        self._analysis_visible = visible
        current_key = (
            id(self._model), self._model.revision, self._model.view_revision,
            self._active_analysis_combination,
            self._active_result_type, self._solid_members_visible,
        )
        if not visible and self._result_actors:
            self._apply_result_layer_visibility()
            self._apply_representation_visibility()
            self.plotter.render()
            return
        if visible and self._result_layer_key == current_key:
            self._apply_result_layer_visibility()
            self._apply_representation_visibility()
            self.plotter.render()
            return
        self._refresh_result_layer()

    def set_analysis_result(self, combination: str | None, result_type: str) -> None:
        combination = combination or None
        if combination == self._active_analysis_combination and result_type == self._active_result_type:
            return
        self._active_analysis_combination = combination
        self._active_result_type = result_type
        if self._analysis_visible:
            self._refresh_result_layer()
        else:
            self._result_layer_key = None

    def set_analysis_diagrams_visible(self, visible: bool) -> None:
        """Show or hide result diagrams without affecting deformation views."""
        visible = bool(visible)
        if visible == self._result_diagrams_visible:
            return
        self._result_diagrams_visible = visible
        if self._analysis_visible:
            self._apply_result_layer_visibility()
            self.plotter.render()

    def set_action_visibility(self, kind: str, visible: bool) -> None:
        """Liga ou desliga uma das quatro categorias de ações renderizadas."""
        if kind not in self._action_visibility:
            return
        visible = bool(visible)
        if self._action_visibility[kind] == visible:
            return
        self._action_visibility[kind] = visible
        if self._actions_visible:
            self._refresh_action_layer()
        else:
            self._action_layer_key = None

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
        self._sync_labels(render_preview=False)
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
            old_grid = self._grid_actor.GetMapper().GetInput()
            if (
                old_grid.GetNumberOfPoints() != self._grid_renderer.mesh.n_points
                or old_grid.GetNumberOfCells() != self._grid_renderer.mesh.n_cells
            ):
                self.plotter.renderer.RemoveActor(self._grid_actor)
                self._grid_actor = self.plotter.add_mesh(
                    self._grid_renderer.mesh, scalars="rgba", rgb=True,
                    line_width=1, pickable=False, name="reference-grid",
                    reset_camera=False, render=False,
                )
                self._grid_actor.SetVisibility(self._grid_visible)
            else:
                self._grid_actor.GetMapper().SetInputData(self._grid_renderer.mesh)
                self._grid_actor.GetMapper().Modified()
        if self._reference_axes_actor is not None and not self._reference_axes_renderer.mesh.n_cells:
            self.plotter.renderer.RemoveActor(self._reference_axes_actor)
            self._reference_axes_actor = None
        elif self._reference_axes_actor is not None:
            old_axes = self._reference_axes_actor.GetMapper().GetInput()
            if old_axes.GetNumberOfCells() != self._reference_axes_renderer.mesh.n_cells:
                self.plotter.renderer.RemoveActor(self._reference_axes_actor)
                self._reference_axes_actor = None
            else:
                self._reference_axes_actor.GetMapper().SetInputData(self._reference_axes_renderer.mesh)
                self._reference_axes_actor.GetMapper().Modified()
        if self._reference_axes_actor is None and self._reference_axes_renderer.mesh.n_cells:
            self._reference_axes_actor = self.plotter.add_mesh(
                self._reference_axes_renderer.mesh, color="#57606a", line_width=1.5,
                pickable=False, render_lines_as_tubes=True, lighting=False,
                name="reference-axes", reset_camera=False, render=False,
            )
            self._reference_axes_actor.SetVisibility(self._reference_axes_visible)
        # Moving the construction plane changes visible bounds.  Update only
        # the near/far range; the user's position, orientation and zoom stay
        # untouched.
        self._clip_refresh_timer.start()

    def update_member_color(self, member_name: str) -> None:
        self.update_member_colors((member_name,))

    def update_member_colors(self, member_names: Iterable[str]) -> None:
        """Apply a color edit to all affected batch cells in one render."""
        batch = self._member_batch
        if batch is None:
            self.render_model(self._model)
            return
        positions = {name: index for index, name in enumerate(batch.names)}
        changed = {
            positions[name]: np.asarray(pv.Color(self._model.bars[name].color).int_rgb, dtype=np.uint8)
            for name in dict.fromkeys(member_names)
            if name in positions and name in self._model.bars
        }
        if not changed:
            return
        indices = np.fromiter(changed, dtype=np.intp)
        colors = np.zeros((len(batch.names), 3), dtype=np.uint8)
        for index, color in changed.items():
            colors[index] = color
        edge_colors = np.clip(colors.astype(float) * 0.65, 0, 255).astype(np.uint8)
        for mesh, palette in (
            (batch.lines, colors), (batch.fallback_lines, colors),
            (batch.faces, colors), (batch.edges, edge_colors),
        ):
            if not mesh.n_cells or "rgb" not in mesh.cell_data:
                continue
            element_indices = np.asarray(mesh.cell_data["element_index"])
            mask = np.isin(element_indices, indices)
            if not np.any(mask):
                continue
            values = mesh.cell_data["rgb"]
            values[mask] = palette[element_indices[mask]]
            mesh.GetCellData().GetArray("rgb").Modified()
            mesh.GetCellData().Modified()
            mesh.Modified()
        silhouette_changed = False
        for index, color in changed.items():
            name = batch.names[index]
            if name in batch.silhouette_sources:
                batch.silhouette_member_colors[name] = tuple(int(channel) for channel in color)
                silhouette_changed = True
        if silhouette_changed:
            batch.silhouette_faces_by_color = self._member_renderer._build_silhouette_faces_by_color(
                batch.silhouette_sources, batch.silhouette_member_colors,
            )
            self._silhouette_source_batch = None
            self._silhouette_mesh_cache = None
            if self._member_silhouette_actor is not None:
                silhouette = self._member_silhouette_mesh(batch)
                mapper = self._member_silhouette_actor.GetMapper()
                mapper.SetInputData(silhouette)
                mapper.Modified()
        if (
            self._highlight_state_key is not None
            and not self._pending_member_geometry_names
            and not self._pending_member_full_names
            and not self._rebuild_timer.isActive()
        ):
            self._highlight_state_key = (
                self._highlight_state_key[0], self._model.revision,
                *self._highlight_state_key[2:],
            )
        self.plotter.render()
        self._capture_rendered_state()

    def update_member_releases(self, _member_name: str) -> None:
        self._pending_member_full_names.add(_member_name)
        self._schedule_member_update()

    def update_member_axes(self, _member_name: str) -> None:
        self._pending_member_full_names.add(_member_name)
        self._schedule_member_update()

    def update_member_rotation(self, _member_name: str) -> None:
        self._pending_member_full_names.add(_member_name)
        self._schedule_member_update()

    def update_member_geometry(self, _member_name: str) -> None:
        self._pending_member_geometry_names.add(_member_name)
        self._schedule_member_update()

    def update_node_visual(self, _node_name: str) -> None:
        self._support_update_timer.start()

    def update_node(self, _node_name: str) -> None:
        self._schedule_rebuild()

    def update_rigid_bar_name(self, old_name: str, new_name: str) -> None:
        """Refresh a renamed rigid bar without losing its scene selection."""
        if self._selected == ("rigid_bar", old_name):
            self._selected = "rigid_bar", new_name
        self._selected_elements = tuple(
            ("rigid_bar", new_name) if target == ("rigid_bar", old_name) else target
            for target in self._selected_elements
        )
        if self._hovered == ("rigid_bar", old_name):
            self._hovered = "rigid_bar", new_name
        self._refresh_rigid_batch()
        self._capture_rendered_state()

    def _schedule_rebuild(self) -> None:
        """Coalesce rapid property edits into one batch reconstruction."""
        self._rebuild_timer.start()

    def _schedule_member_update(self) -> None:
        """Coalesce member property edits without rebuilding unrelated layers."""
        self._member_update_timer.start()

    def _refresh_pending_member_update(self) -> None:
        self._member_update_timer.stop()
        full_names = tuple(self._pending_member_full_names)
        names = tuple(self._pending_member_geometry_names | self._pending_member_full_names)
        self._pending_member_geometry_names.clear()
        self._pending_member_full_names.clear()
        if not names:
            return
        if not full_names and names and self._member_batch is not None:
            batch = self._member_batch
            face_connectivity = batch.faces.faces
            edge_connectivity = batch.edges.lines
            silhouette_changed = any(
                name in batch.silhouette_sources
                or (
                    (member := self._model.bars.get(name)) is not None
                    and member.section in self._member_renderer._silhouette_sections
                )
                for name in names
            )
            if all(
                self._member_renderer.update_member_section_in_place(
                    batch, self._model, name, rebuild_silhouette=False,
                    face_connectivity=face_connectivity,
                    edge_connectivity=edge_connectivity,
                )
                for name in names
            ):
                if silhouette_changed:
                    batch.silhouette_faces_by_color = self._member_renderer._build_silhouette_faces_by_color(
                        batch.silhouette_sources, batch.silhouette_member_colors,
                    )
                self._member_geometry_cache_key = self._member_cache_key(self._model)
                for actor in (self._member_face_actor, self._member_edge_actor):
                    if actor is not None:
                        actor.GetMapper().Modified()
                if silhouette_changed:
                    if self._member_silhouette_actor is not None:
                        self.plotter.renderer.RemoveActor(self._member_silhouette_actor)
                        self._member_silhouette_actor = None
                    self._silhouette_source_batch = None
                    self._silhouette_camera_key = None
                    self._silhouette_mesh_cache = None
                    self._refresh_member_silhouette()
                self._clear_result_layer()
                self._configure_solid_picker()
                self._sync_highlights()
                self._sync_labels()
                self.plotter.render()
                self._clip_refresh_timer.start()
                self._capture_rendered_state()
                return
            # Positioning edits move indicators too; section-family changes
            # may alter topology. Rebuild the affected members in either case.
            if self._refresh_member_subset(names):
                self._capture_rendered_state()
                return
            self._refresh_member_batch()
            self._capture_rendered_state()
            return
        if names and self._refresh_member_subset(names):
            self._capture_rendered_state()
            return
        self._refresh_member_batch()
        self._capture_rendered_state()

    def _refresh_member_subset(self, names: tuple[str, ...]) -> bool:
        batch = self._member_batch
        if batch is None or len(names) > 12:
            return False
        if any(name not in batch.names or name not in self._model.bars for name in names):
            return False
        prior_silhouettes = set(batch.silhouette_sources)
        needs_actor_rebind = False
        for name in names:
            if not self._member_renderer.update_member_in_place(
                batch, self._model, name, self._marker_radius_current,
            ):
                if not self._member_renderer.update_member_in_batch(
                    batch, self._model, name, self._marker_radius_current,
                ):
                    return False
                needs_actor_rebind = True
        silhouette_changed = any(
            name in prior_silhouettes or name in batch.silhouette_sources for name in names
        )
        if silhouette_changed:
            self._silhouette_source_batch = None
            self._silhouette_camera_key = None
            self._silhouette_mesh_cache = None
        self._member_geometry_cache = batch
        self._member_geometry_cache_key = self._member_cache_key(self._model)
        if needs_actor_rebind:
            self._display_member_batch(names)
            return True
        for actor in (
            self._member_line_actor, self._member_fallback_actor,
            self._member_face_actor, self._member_edge_actor, self._release_actor,
            *self._local_axis_actors,
        ):
            if actor is not None:
                actor.GetMapper().Modified()
        if silhouette_changed:
            if self._member_silhouette_actor is not None:
                self.plotter.renderer.RemoveActor(self._member_silhouette_actor)
                self._member_silhouette_actor = None
            self._refresh_member_silhouette()
        for name in names:
            self._elastic_support_overlay.update_member(
                self._model.bars[name], self._model.nodes, self._node_marker_radius(),
            )
        self._label_overlay.set_group(
            "bar", batch.label_positions, batch.names,
            visible=self._labels_visibility["bar"],
        )
        self._clear_result_layer()
        self._configure_solid_picker()
        self._sync_highlights()
        self._sync_labels()
        self.plotter.render()
        self._clip_refresh_timer.start()
        return True

    def _member_cache_key(self, model: StructuralModel) -> tuple[object, ...]:
        return (
            round(float(self._marker_radius_current), 12),
            self._solid_members_visible,
            tuple(
                (
                    member,
                    (model.nodes[member.start_node].x, model.nodes[member.start_node].y,
                     model.nodes[member.start_node].z),
                    (model.nodes[member.end_node].x, model.nodes[member.end_node].y,
                     model.nodes[member.end_node].z),
                )
                for member in model.bars.values()
            ),
        )

    def _refresh_node_batch(self) -> None:
        """Rebuild only node markers and supports after node removal."""
        radius = self._node_marker_radius()
        batch = self._node_renderer.build(self._model, radius)
        self._node_batch = batch
        self._node_geometry_cache = batch
        self._node_geometry_cache_key = (
            round(float(radius), 12), tuple(self._model.nodes.values()),
        )
        for actor in (self._node_actor, self._support_actor):
            if actor is not None:
                self.plotter.renderer.RemoveActor(actor)
        self._node_actor = None
        self._node_glyph_points = None
        self._support_actor = None
        self._add_node_batches()
        self._label_overlay.set_group(
            "node", batch.label_positions, batch.names,
            visible=self._labels_visibility["node"],
        )
        self._sync_highlights()
        self._sync_labels()
        self.plotter.render()
        self._clip_refresh_timer.start()

    def _refresh_support_batch(self, *, capture_state: bool = True) -> None:
        """Replace only support geometry after a restraint toggle."""
        batch = self._node_batch
        if batch is None:
            self.render_model(self._model)
            return
        batch.supports = self._node_renderer.build_supports(
            self._model, self._node_marker_radius(),
        )
        self._node_geometry_cache = batch
        self._node_geometry_cache_key = (
            round(float(self._node_marker_radius()), 12),
            tuple(self._model.nodes.values()),
        )
        if not batch.supports.n_cells:
            if self._support_actor is not None:
                self.plotter.renderer.RemoveActor(self._support_actor)
                self._support_actor = None
        else:
            if self._support_actor is not None:
                self.plotter.renderer.RemoveActor(self._support_actor)
            self._support_actor = self.plotter.add_mesh(
                batch.supports, color="#a8b0b9", edge_color="#6e7781",
                show_edges=True, line_width=1.5, pickable=False,
                reset_camera=False, render=False,
            )
            self._support_actor.SetVisibility(self._node_supports_visible)
        self.plotter.render()
        self._clip_refresh_timer.start()
        if capture_state:
            self._capture_rendered_state()

    def _refresh_rigid_batch(self) -> None:
        """Replace only idealized rigid bars when their endpoints change."""
        self._rigid_bar_names, self._rigid_bar_mesh = self._rigid_bar_renderer.build(self._model)
        self._rigid_geometry_cache = self._rigid_bar_names, self._rigid_bar_mesh
        self._rigid_geometry_cache_key = tuple(
            (
                rigid,
                (self._model.nodes[rigid.start_node].x, self._model.nodes[rigid.start_node].y,
                 self._model.nodes[rigid.start_node].z),
                (self._model.nodes[rigid.end_node].x, self._model.nodes[rigid.end_node].y,
                 self._model.nodes[rigid.end_node].z),
            )
            for rigid in self._model.rigid_bars.values()
        )
        if self._rigid_bar_actor is not None:
            self.plotter.renderer.RemoveActor(self._rigid_bar_actor)
            self._rigid_bar_actor = None
        self._add_rigid_bar_batch()
        self._sync_highlights()
        self.plotter.render()
        self._clip_refresh_timer.start()

    def _refresh_camera_clipping_range(self) -> None:
        """Recalculate camera depth bounds after the immediate edit frame."""
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def _refresh_member_batch(self) -> None:
        """Rebuild member meshes and update their actors in place."""
        batch = self._member_renderer.build(self._model, self._marker_radius_current)
        self._member_batch = batch
        self._member_geometry_cache = batch
        self._member_geometry_cache_key = self._member_cache_key(self._model)

        self._display_member_batch()

    def _display_member_batch(
        self, changed_names: tuple[str, ...] = (), removed_names: tuple[str, ...] = (),
    ) -> None:
        """Rebind changed member meshes with the original actor styling."""
        batch = self._member_batch
        if batch is None:
            return

        # VTK mappers can retain scalar-array state when their input is swapped
        # after construction. Recreate just these few batched actors so the
        # replacement meshes receive the same mapper configuration as on open.
        for actor in (
            self._member_line_actor, self._member_fallback_actor,
            self._member_face_actor, self._member_edge_actor,
            self._member_silhouette_actor, self._release_actor,
        ):
            if actor is not None:
                self.plotter.renderer.RemoveActor(actor)
        for actor in self._local_axis_actors:
            self._local_axes_renderer.RemoveActor(actor)
        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._member_silhouette_actor = None
        self._release_actor = None
        self._local_axis_actors = []
        self._add_member_batches()

        self._label_overlay.set_group(
            "bar", batch.label_positions, batch.names,
            visible=self._labels_visibility["bar"],
        )
        self._clear_result_layer()
        if batch.silhouette_sources:
            self._refresh_member_silhouette()
        elif self._member_silhouette_actor is not None:
            self.plotter.renderer.RemoveActor(self._member_silhouette_actor)
            self._member_silhouette_actor = None
            self._silhouette_source_batch = None
            self._silhouette_camera_key = None
            self._silhouette_mesh_cache = None
        self._apply_representation_visibility()
        self._configure_solid_picker()
        self._sync_highlights()
        if changed_names or removed_names:
            for name in changed_names:
                self._elastic_support_overlay.update_member(
                    self._model.bars[name], self._model.nodes, self._node_marker_radius(),
                )
            for name in removed_names:
                self._elastic_support_overlay.remove_member(name)
        else:
            self._elastic_support_overlay.set_members(
                self._model.bars.values(), self._model.nodes.values(), self._node_marker_radius(),
            )
        self._update_zoom_dependent_sizes()
        self._sync_labels()
        self.plotter.render()
        self._clip_refresh_timer.start()

    def _rebuild_scene(self) -> None:
        self.refresh_model_changes(self._model)

    def remove_element(self, kind: str, name: str) -> None:
        target = kind, name
        if self._selected == target:
            self._selected = None
        self._selected_elements = tuple(
            element for element in self._selected_elements if element != target
        )
        if self._hovered == target:
            self._hovered = None
        self.refresh_model_changes(self._model)

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
        """Install explicit world-up navigation, independent of camera pose."""
        # Terrain treats the camera's ViewUp as its azimuth axis. That is
        # unsuitable after selecting the XY face or a corner of the cube,
        # because ViewUp then changes with the clicked face. A user style has
        # no built-in camera motion; the interactor callbacks below own every
        # navigation gesture and can keep horizontal rotation on global Z.
        self.plotter.iren.style = vtk.vtkInteractorStyleUser()

    @staticmethod
    def _rotate_camera_vector(
        vector: np.ndarray, axis: np.ndarray, angle_degrees: float,
    ) -> np.ndarray:
        """Rotate a camera offset around a unit axis using Rodrigues' formula."""
        axis_length = float(np.linalg.norm(axis))
        if axis_length <= 1e-12 or abs(float(angle_degrees)) <= 1e-12:
            return vector.copy()
        unit_axis = axis / axis_length
        angle = np.deg2rad(float(angle_degrees))
        cosine = float(np.cos(angle))
        sine = float(np.sin(angle))
        return (
            vector * cosine
            + np.cross(unit_axis, vector) * sine
            + unit_axis * float(np.dot(unit_axis, vector)) * (1.0 - cosine)
        )

    def _begin_revit_orbit(self, x: float, y: float) -> None:
        """Start a world-up orbit from the current cursor position."""
        if self._camera_drag_mode is not None:
            return
        self._wheel_interaction_timer.stop()
        self._camera_render_timer.stop()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        if self._orientation_widget._camera_animation.isActive():
            return

        self._camera_drag_mode = "orbit"
        self._camera_drag_last_position = int(x), int(y)
        self._on_interaction()

    def _begin_camera_drag(self, mode: str, x: float, y: float) -> None:
        if self._camera_drag_mode is not None:
            return
        self._wheel_interaction_timer.stop()
        self._camera_render_timer.stop()
        self._camera_drag_mode = mode
        self._camera_drag_last_position = int(x), int(y)
        self._on_interaction()

    def _on_navigation_left_press(self, caller, _event) -> None:
        """Start an orbit, or pan when Shift is held."""
        x, y = caller.GetEventPosition()
        if self._orientation_widget.is_pointer_over(x, y):
            return
        if self._orientation_widget._camera_animation.isActive():
            return
        if caller.GetShiftKey():
            self._begin_camera_drag("pan", x, y)
            return
        self._begin_revit_orbit(x, y)

    def _on_navigation_middle_press(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._begin_camera_drag("pan", x, y)

    def _on_navigation_right_press(self, caller, _event) -> None:
        x, y = caller.GetEventPosition()
        self._begin_camera_drag("dolly", x, y)

    def _on_revit_orbit_move(self, x: int, y: int) -> None:
        """Apply azimuth around global Z and elevation around camera right."""
        if self._camera_drag_mode != "orbit" or self._camera_drag_last_position is None:
            return

        last_x, last_y = self._camera_drag_last_position
        self._camera_drag_last_position = int(x), int(y)
        dx = float(x) - float(last_x)
        dy = float(y) - float(last_y)
        if abs(dx) <= 1e-12 and abs(dy) <= 1e-12:
            return

        render_width, render_height = self.plotter.render_window.GetSize()
        if render_width <= 0 or render_height <= 0:
            return
        azimuth = -dx / float(render_width) * 180.0
        elevation = -dy / float(render_height) * 180.0

        camera = self.plotter.renderer.GetActiveCamera()
        focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
        offset = np.asarray(camera.GetPosition(), dtype=float) - focal_point
        distance = float(np.linalg.norm(offset))
        if distance <= 1e-12:
            return

        world_up = np.asarray((0.0, 0.0, 1.0), dtype=float)
        current_up = np.asarray(camera.GetViewUp(), dtype=float)
        was_at_pole = float(np.linalg.norm(np.cross(world_up, offset))) <= 1e-8
        offset = self._rotate_camera_vector(offset, world_up, azimuth)
        if was_at_pole:
            current_up = self._rotate_camera_vector(current_up, world_up, azimuth)

        direction = -offset / max(float(np.linalg.norm(offset)), 1e-12)
        elevation_axis = np.cross(world_up, direction)
        if float(np.linalg.norm(elevation_axis)) <= 1e-8:
            # At the top/bottom pole, use the current screen heading as the
            # elevation hinge. This keeps the view usable without replacing
            # the exact top/bottom orientation with an artificial tilt.
            horizontal_up = current_up.copy()
            horizontal_up[2] = 0.0
            if float(np.linalg.norm(horizontal_up)) <= 1e-8:
                horizontal_up = np.asarray((0.0, 1.0, 0.0), dtype=float)
            elevation_axis = np.cross(horizontal_up, direction)
        offset = self._rotate_camera_vector(offset, elevation_axis, elevation)

        camera.SetPosition(*(focal_point + offset))
        at_pole = float(np.linalg.norm(np.cross(world_up, offset))) <= 1e-8
        if at_pole:
            current_up[2] = 0.0
            up_length = float(np.linalg.norm(current_up))
            if up_length <= 1e-8:
                current_up = np.asarray((0.0, 1.0, 0.0), dtype=float)
            else:
                current_up /= up_length
            camera.SetViewUp(*current_up)
        else:
            # Keep the azimuth reference on structural vertical Z for every
            # oblique view, even when the cube selected a corner.
            camera.SetViewUp(*world_up)

        self._queue_camera_frame()

    def _on_navigation_mouse_move(self, caller, _event) -> None:
        if self._selection_press is not None:
            x, y = caller.GetEventPosition()
            if np.hypot(x - self._selection_press[0], y - self._selection_press[1]) > self._placement_drag_tolerance_pixels:
                self._selection_dragged = True
        if self._camera_drag_mode is None:
            return
        x, y = caller.GetEventPosition()
        if self._camera_drag_mode == "orbit":
            self._on_revit_orbit_move(x, y)
        elif self._camera_drag_mode == "pan":
            self._pan_camera(x, y)
        else:
            self._dolly_camera(y)

    def _pan_camera(self, x: int, y: int) -> None:
        if self._camera_drag_last_position is None:
            return
        last_x, last_y = self._camera_drag_last_position
        self._camera_drag_last_position = int(x), int(y)
        renderer = self.plotter.renderer
        camera = renderer.GetActiveCamera()
        focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
        renderer.SetWorldPoint(*focal_point, 1.0)
        renderer.WorldToDisplay()
        depth = float(renderer.GetDisplayPoint()[2])
        current = self._display_to_world(renderer, x, y, depth)
        previous = self._display_to_world(renderer, last_x, last_y, depth)
        if current is None or previous is None:
            return
        movement = previous - current
        camera.SetPosition(*(np.asarray(camera.GetPosition(), dtype=float) + movement))
        camera.SetFocalPoint(*(focal_point + movement))
        self._queue_camera_frame()

    def _dolly_camera(self, y: int) -> None:
        if self._camera_drag_last_position is None:
            return
        _last_x, last_y = self._camera_drag_last_position
        self._camera_drag_last_position = self._camera_drag_last_position[0], int(y)
        center_y = float(self.plotter.renderer.GetCenter()[1])
        if abs(center_y) <= 1e-12:
            return
        factor = 1.1 ** (10.0 * (float(y) - float(last_y)) / center_y)
        camera = self.plotter.renderer.GetActiveCamera()
        if camera.GetParallelProjection():
            camera.SetParallelScale(camera.GetParallelScale() / factor)
        else:
            focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
            position = np.asarray(camera.GetPosition(), dtype=float)
            camera.SetPosition(*(focal_point + (position - focal_point) / factor))
        self._queue_camera_frame()

    def _on_navigation_wheel(self, _caller, event) -> None:
        if self._camera_drag_mode is not None:
            return
        if not self._camera_interacting:
            self._on_interaction()
        self._wheel_interaction_timer.start()
        factor = 1.0 / 1.05 if event == "MouseWheelForwardEvent" else 1.05
        camera = self.plotter.renderer.GetActiveCamera()
        if camera.GetParallelProjection():
            camera.SetParallelScale(camera.GetParallelScale() * factor)
        else:
            focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
            position = np.asarray(camera.GetPosition(), dtype=float)
            camera.SetPosition(*(focal_point + (position - focal_point) * factor))
        self._queue_camera_frame()

    def _queue_camera_frame(self) -> None:
        """Coalesce pointer and wheel changes into one render of the latest pose."""
        if not self._camera_render_timer.isActive():
            self._camera_render_timer.start()

    def _render_camera_frame(self) -> None:
        """Render the latest camera pose once, including its screen overlays."""
        if not self._camera_interacting:
            return
        self.plotter.reset_camera_clipping_range()
        self._update_zoom_dependent_sizes()
        self._orientation_widget.sync_from_camera()
        self._sync_labels(render_preview=False)
        self.plotter.render()
        self._last_interaction_render_state = self._camera_state()

    def _finish_wheel_interaction(self) -> None:
        """Finish a coalesced wheel gesture after the cursor stops scrolling."""
        self._camera_render_timer.stop()
        if self._camera_drag_mode is None and self._camera_interacting:
            self._on_interaction_end()

    def _on_navigation_button_release(self, _caller, _event) -> None:
        self._finish_camera_drag()

    def _finish_camera_drag(self) -> None:
        """Stop an orbit, pan or dolly gesture."""
        if self._camera_drag_mode is None:
            return
        self._camera_drag_mode = None
        self._camera_drag_last_position = None
        self._on_interaction_end()

    def _on_interaction(self, *_args) -> None:
        if not self._camera_interacting:
            self._last_interaction_render_state = None
        self._camera_interacting = True
        self._label_timer.stop()
        self._measurement_refresh_timer.stop()
        if self._measurement_mode:
            self._measurement_readout.hide()
            self._snap_marker.hide()
            self._measurement_start_marker.hide()
        self._orientation_widget.sync_from_camera()

    def _on_interaction_end(self, *_args) -> None:
        self._camera_render_timer.stop()
        self._camera_interacting = False
        self._silhouette_timer.stop()
        final_camera_state = self._camera_state()
        # Orbiting and panning change the viewing direction but are not camera
        # resets.  Recalculate only the clipping planes so no geometry remains
        # hidden after a navigation gesture.
        self.plotter.reset_camera_clipping_range()
        self._label_timer.stop()
        self._update_zoom_dependent_sizes()
        self._update_depth_overlays()
        if self._measurement_mode:
            self._measurement_refresh_timer.start()
        self._sync_labels(render_preview=False)
        self._update_coordinate_readout()
        self._orientation_widget.sync_from_camera()
        # Silhouettes and snap candidates are view-dependent and can be
        # expensive for a large model. Render the final camera pose first;
        # the existing throttled path refreshes the contour once navigation
        # has settled.
        if self._member_batch is not None and self._member_batch.silhouette_sources:
            self._silhouette_timer.start()
        if final_camera_state != self._last_interaction_render_state:
            self.plotter.render()
        self._last_interaction_render_state = final_camera_state

    def _refresh_measurement_after_navigation(self) -> None:
        """Resolve one fresh snap after the camera and cursor settle."""
        if self._camera_interacting or not self._measurement_mode:
            return
        self._update_measurement_readout()
        self.plotter.render()

    def _sync_labels(self, *, render_preview: bool = True) -> None:
        self._label_overlay.sync(self.plotter.renderer)
        self._elastic_support_overlay.sync(self.plotter.renderer)
        if hasattr(self, "_coordinate_readout"):
            self._update_coordinate_readout()
            if (
                not self._camera_interacting
                and not self._measurement_refresh_timer.isActive()
            ):
                self._update_measurement_readout()
            if render_preview and self._member_preview_start is not None:
                self.plotter.render()

    def _on_camera_modified(self, *_args) -> None:
        # Camera events can arrive hundreds of times during a wheel/dolly
        # gesture.  Measurement visibility, depth offsets and profile
        # silhouettes are deliberately deferred until the gesture ends;
        # doing any of them here makes zoom fight the render loop.
        if not self._camera_interacting:
            self._update_depth_overlays()
            if not self._silhouette_timer.isActive():
                self._silhouette_timer.start()
        else:
            self._silhouette_timer.stop()
            return
        self._schedule_label_sync()

    def _refresh_member_silhouette_throttled(self) -> None:
        if self._camera_interacting:
            return
        self._refresh_member_silhouette()
        circular = self._highlight_targets.get("selected:circular")
        if circular and self._solid_members_visible:
            self._replace_highlight("selected:circular", circular, "#0969da")
        hovered = self._highlight_targets.get("hover")
        if hovered and self._solid_members_visible and hovered[0][0] == "bar":
            member = self._model.bars.get(hovered[0][1])
            if member is not None and member.section in self._member_renderer._silhouette_sections:
                self._replace_highlight("hover", hovered, "#24292f")
        self.plotter.render()

    def _refresh_member_silhouette(self) -> None:
        """Refresh the screen-space contour after the camera changes."""
        batch = self._member_batch
        if batch is None or not batch.silhouette_sources:
            return
        mesh = self._member_silhouette_mesh(batch)
        if self._member_silhouette_actor is None:
            if not mesh.n_cells:
                return
            self._member_silhouette_actor = self._add_colored_mesh(
                mesh,
                "batch:member-silhouette",
                line_width=self._circular_silhouette_line_width,
                lighting=False,
            )
            self._member_silhouette_actor.SetPickable(False)
            self._member_silhouette_actor.SetVisibility(
                self._solid_members_visible and not (
                    self._analysis_visible and self._active_result_type.startswith("Deformação")
                )
            )
            return
        mapper = self._member_silhouette_actor.GetMapper()
        mapper.SetInputData(mesh)
        mapper.Modified()
        self._member_silhouette_actor.SetVisibility(
            self._solid_members_visible
            and not (self._analysis_visible and self._active_result_type.startswith("Deformação"))
        )

    def _member_silhouette_mesh(self, batch: MemberBatch) -> pv.PolyData:
        camera = self.plotter.renderer.GetActiveCamera()
        camera_key = self._camera_state()
        if (
            self._silhouette_source_batch is not batch
            or self._silhouette_camera_key != camera_key
            or self._silhouette_mesh_cache is None
        ):
            self._silhouette_mesh_cache = self._member_renderer.silhouette_mesh(batch, camera)
            self._silhouette_source_batch = batch
            self._silhouette_camera_key = camera_key
        return self._silhouette_mesh_cache

    def _update_depth_overlays(self) -> None:
        """Keep analytical axes aligned while the overlay layer owns depth."""
        if not self._local_axis_actors:
            return
        for actor in self._local_axis_actors:
            actor.SetPosition(0.0, 0.0, 0.0)

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
        for slot, actor in self._highlight_actors.items():
            if actor is not None and (slot.startswith("selected") or slot == "hover"):
                targets = self._highlight_targets.get(slot, ())
                kind = targets[0][0] if targets else "bar"
                member_name = targets[0][1] if targets and kind == "bar" else None
                actor.GetProperty().SetLineWidth(
                    self._highlight_line_width(slot, kind, member_name),
                )

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
        hidden_members = self._scene_hidden_members()
        visible_nodes = self._scene_visible_node_names(hidden_members)
        def is_valid(target: tuple[str, str]) -> bool:
            kind, name = target
            collection = (
                self._model.nodes if kind == "node"
                else self._model.bars if kind == "bar" else self._model.rigid_bars
            )
            if name not in collection:
                return False
            if self._scene_selection_mode == "reveal":
                return kind == "bar" and name in hidden_members
            if kind == "bar":
                return name not in hidden_members
            if kind == "node":
                return name in visible_nodes and self._scene_selection_mode is None
            return self._scene_selection_mode is None

        selected_elements = self._selected_elements or (
            (self._selected,) if self._selected is not None else ()
        )
        self._selected_elements = tuple(
            target for target in selected_elements if is_valid(target)
        )
        self._selected = self._selected_elements[-1] if self._selected_elements else None

    def _clear_actor_references(self) -> None:
        for actor in self._local_axis_actors:
            self._local_axes_renderer.RemoveActor(actor)
        self._grid_actor = None
        self._reference_axes_actor = None
        self._member_line_actor = None
        self._member_fallback_actor = None
        self._member_face_actor = None
        self._member_edge_actor = None
        self._member_silhouette_actor = None
        self._reveal_preview_line_actor = None
        self._reveal_preview_face_actor = None
        self._reveal_preview_fallback_actor = None
        self._reveal_preview_batch = None
        self._member_preview_actor = None
        self._measurement_preview_actor = None
        self._perpendicular_guide_actor = None
        self._orthogonal_guide_actor = None
        self._rigid_bar_actor = None
        self._node_actor = None
        self._node_glyph_points = None
        self._support_actor = None
        self._release_actor = None
        self._local_axis_actors = []
        self._action_actors = []
        self._action_layer_key = None
        self._action_label_positions = np.empty((0, 3), dtype=float)
        self._action_labels = ()
        self._result_actors = []
        self._result_layer_key = None
        self._result_label_positions = np.empty((0, 3), dtype=float)
        self._result_labels = ()
        self._solid_picker.InitializePickList()
        self._highlight_actors.clear()
        self._highlight_targets.clear()
        self._highlighted_node_colors.clear()
        self._highlight_state_key = None
        self._member_batch = None
        self._node_batch = None
        self._measurement_segments_cache = None
        self._measurement_segment_bounds = None
        self._projected_snap_cache = None
        self._pick_projection_cache = None
        self._measurement_face_locator = None
        self._measurement_face_locator_key = None
        self._rigid_bar_names = ()
        self._rigid_bar_mesh = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_orientation_widget"):
            self._label_overlay.resize_to_parent()
            self._elastic_support_overlay.resize_to_parent()
            self._model_info_overlay.raise_()
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

    def set_model_name(self, name: str) -> None:
        self._model_name_overlay.setText(name.strip() or "Novo modelo")
        self._model_info_overlay.adjustSize()
        self._model_info_overlay.move(20, 14)
        self._model_info_overlay.show()
        self._model_info_overlay.raise_()

    def _node_marker_radius(self) -> float:
        return self._marker_radius_current

    @staticmethod
    def _marker_radius(_positions: np.ndarray) -> float:
        return 0.05
