"""Janela principal e composição dos componentes visuais."""
import copy
import math
import threading
import uuid

import numpy as np
from PySide6.QtCore import QSettings, QThread, Signal, Slot

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.integrations import LocalMcpIntegration
from osa.mcp import LocalMcpServer, McpApplication
from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.plate_result_display import (
    DEFAULT_PLATE_RESULT_DISPLAY_MODE,
    is_plate_result_display_mode,
)
from osa.sections import section_shape
from osa.services import AnalysisService, ResultService
from osa.services.plate_contour import plate_contour
from osa.transcriptions import is_import_path
from osa.transcriptions.plates import require_no_pending_plates

from .analysis_panel import ProcessingPanel, VerificationPanel
from .analysis_worker import AnalysisWorker
from .axes_panel import AxesPanel
from .calculation_properties_panel import CalculationPropertiesPanel
from .command_bar import CommandBar, CommandHistory
from .common import *
from .dialogs import (
    PROJECT_MANUAL_URL,
    AboutDialog,
    ActionDialog,
    ActionGroupDialog,
    CombinationsDialog,
    DetailingExportSuccessDialog,
    DetailingViewsDialog,
    ErrorDialog,
    MemberSnapSplitDialog,
    PlateClosureDialog,
    ProgramSettingsDialog,
    ProjectSheetSettingsDialog,
    RemoveProjectSheetDialog,
    SelfweightDialog,
    SettingsDialog,
    UnsavedChangesDialog,
)
from .displacement_panel import DisplacementPanel
from .detailing_preview import DetailingViewPreview, _ViewGeometryCalculator
from .group_positioning import group_endpoint_faces
from .home import HomePage
from .import_dialogs import ImportReportDialog, PrjImportDialog
from .loading_indicator import LoadingIndicator
from .mcp_dispatcher import McpQtDispatcher
from .member_placement_panel import MemberPlacementEditor
from .navigation_buttons import LeftArrowButton, RightArrowButton, SlopedPlaneButton
from .palettes import (
    ActionTopPalette,
    AnalysisTopPalette,
    DetailingTopPalette,
    DetailingModePalette,
    ProjectSheetsPalette,
    FloatingPalette,
    MemberPropertyCopyPanel,
    PaletteTooltip,
    TopIconPalette,
    VerificationTopPalette,
)
from .project_load_worker import ProjectLoadWorker
from .project_sheet import (
    ProjectSheetIdentificationPanel,
    ProjectSheetViewPanel,
    ProjectSheetWorkspace,
)
from .property_panel import PropertyPanel
from .reference_panel import ReferenceImportDialog, ReferencePanel
from .section_panel import (
    HPLaminadoSectionPanel,
    ILaminadoSectionPanel,
    LLaminadoSectionPanel,
    ParametricSectionPanel,
    TLaminadoSectionPanel,
    ULaminadoSectionPanel,
    WLaminadoSectionPanel,
)
from .split_member_dialog import SplitMemberDialog
from .subtractions_panel import SubtractionsPanel
from .verification_worker import VerificationWorker
from .window_frame import TitleBar, WindowFrame


class _ProjectLoadingDialog(QDialog):
    def reject(self) -> None:
        """Keep the modal loading state visible until the load finishes."""


class MainWindow(QMainWindow):
    mcp_model_changed = Signal()
    mcp_view_changed = Signal(str, bool)
    mcp_scene_views_changed = Signal()
    mcp_active_action_changed = Signal(str)
    mcp_analysis_view_changed = Signal(str, str)
    mcp_analysis_diagrams_changed = Signal(bool)
    mcp_session_changed = Signal(str)

    _initial_framing_commands = frozenset({"barrabieng", "galpao", "mezanino", "portico"})
    _project_file_filter = "Modelo OSA (*.osa)"
    _open_file_filter = _project_file_filter
    _import_file_filter = "Projeto PRJ (*.prj *.prj.zip)"
    _interface_commands = frozenset({
        "bar", "plate", "split", "reverse", "join", "rigid", "copy", "cprop", "measure", "axes",
        "nodeforce", "nodemoment", "memberforce", "membermoment", "group", "ungroup",
        "action", "load", "selfweight", "combinations", "analyze", "verify", "grid",
        "configaxes", "nodelabels", "memberlabels", "platelabels", "localaxes", "nodes",
        "solids", "releases", "semirigid", "supports", "scene", "configreference",
    })

    def __init__(self) -> None:
        super().__init__()
        self.model = StructuralModel()
        self._model_access_lock = threading.RLock()
        self.model_service = ModelService(self.model)
        self.material_service = MaterialService(self.model)
        self.action_service = ActionService(self.model)
        self.section_service = SectionService(self.model)
        self.section_property_service = SectionPropertyService()
        self.project_service = ProjectService(self.model)
        self.analysis_service = AnalysisService(self.model, PyniteAdapter())
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._verification_thread: QThread | None = None
        self._verification_worker: VerificationWorker | None = None
        self._verification_scope_names: tuple[str, ...] | None = None
        self._verification_revision: int | None = None
        self._verification_group_revision: int | None = None
        self._verification_properties_revision: int | None = None
        self._verification_restraint_angle_degrees: float | None = None
        self._verification_result_ids: tuple[int, ...] | None = None
        self._project_load_thread: QThread | None = None
        self._project_load_worker: ProjectLoadWorker | None = None
        self._project_loading_path: Path | None = None
        self._project_loading_importing = False
        self._project_loading_report: dict | None = None
        self._project_scene_steps = None
        self._project_scene_revision: int | None = None
        self._project_scene_timer = QTimer(self)
        self._project_scene_timer.setInterval(1)
        self._project_scene_timer.timeout.connect(self._advance_project_scene)
        self._project_loading_action_states: list[tuple[QAction, bool]] = []
        self._analysis_revision: int | None = None
        self.command_session = CommandSession(self.model_service)
        self.section_geometry: dict[str, dict[str, float]] = {}
        self.section_profiles: dict[str, str] = {}
        self.current_path: Path | None = None
        self._import_save_path: Path | None = None
        self._saved_revision = self.model.revision
        self._saved_view_revision = self.model.view_revision
        self._command_mode: str | None = None
        self._detailing_project_mode = False
        self._detail_plane_return_to_project = False
        self._detailing_views_dialog_open = False
        self._detailing_views_dialog: DetailingViewsDialog | None = None
        self._reference_axis_placement_direction: str | None = None
        self._last_command_callback = None
        self._member_placement_start: tuple[float, float, float] | None = None
        self._member_placement_start_snap_member_name: str | None = None
        self._member_placement_start_snap_target: tuple[str, str] | None = None
        self._endpoint_alignment_source: tuple[str, str] | None = None
        self._detail_subtraction_target: tuple[str, str] | None = None
        self._face_alignment_source: tuple[str, str] | None = None
        self._face_alignment_source_hit = None
        self._connect_member_ends_first_bar: str | None = None
        self._join_member_first: str | None = None
        self._copy_properties_reference: str | None = None
        self._copy_elements_selection: list[tuple[str, str]] = []
        self._copy_elements_reference: tuple[float, float, float] | None = None
        self._pending_action_launch: tuple[str, str, dict[str, tuple[float, ...]]] | None = None
        self._member_direction_normalization_enabled = True
        self._program_settings = QSettings("OpenStructuralAnalysis", "OpenStructuralAnalysis")
        self._face_intersection_edges_enabled = self._program_settings.value(
            "video/showFaceIntersectionEdges", False, type=bool,
        )
        plate_closure = str(self._program_settings.value("plates/closure", "perguntar"))
        self._plate_closure_mode = plate_closure if plate_closure in {"perguntar", "automatico"} else "perguntar"
        plate_result_mode = str(self._program_settings.value(
            "plates/resultDisplayMode", DEFAULT_PLATE_RESULT_DISPLAY_MODE,
        ))
        self._plate_result_display_mode = (
            plate_result_mode if is_plate_result_display_mode(plate_result_mode)
            else DEFAULT_PLATE_RESULT_DISPLAY_MODE
        )
        self._solid_face_angle_limit_degrees = self._read_solid_face_angle_limit()
        self._minimum_bar_restraint_angle_degrees = self._read_minimum_bar_restraint_angle()
        self.model.minimum_bar_restraint_angle_degrees = self._minimum_bar_restraint_angle_degrees
        split_mode = self._program_settings.value(
            "members/intermediateSnapSplit",
            self._program_settings.value("members/perpendicularSplit", "nao"),
        )
        split_mode = str(split_mode)
        self._member_intermediate_snap_split_mode = (
            split_mode if split_mode in {"sim", "perguntar", "nao"} else "nao"
        )
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Open Structural Analysis")
        self.resize(1280, 760)
        self.setMinimumSize(1280, 760)
        self.window_frame = WindowFrame(self)
        shell = QWidget(self)
        shell.setObjectName("appFrame")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        self.scene = StructureScene(shell)
        self.scene.set_face_intersection_edges_enabled(self._face_intersection_edges_enabled)
        self.scene.set_plate_result_display_mode(self._plate_result_display_mode)
        self.home = HomePage(shell)
        self.view_stack = QStackedWidget(shell)
        self.view_stack.addWidget(self.home)
        self.view_stack.addWidget(self.scene)
        self.project_sheet_workspace = ProjectSheetWorkspace(shell)
        self.view_stack.addWidget(self.project_sheet_workspace)
        shell_layout.addWidget(self.title_bar)
        shell_layout.addWidget(self.view_stack, 1)
        self.window_frame.body.addWidget(shell)
        self.setCentralWidget(self.window_frame)
        self._create_project_loading_overlay()
        self.project_sheet_view_panel = ProjectSheetViewPanel(self)
        self.project_sheet_identification_panel = ProjectSheetIdentificationPanel(self)
        self.project_sheet_workspace.selection_changed.connect(
            self._project_sheet_view_selected
        )
        self.project_sheet_workspace.identification_selection_changed.connect(
            self._project_sheet_identification_selected
        )
        self.project_sheet_workspace.layout_changed.connect(self._store_detailing_state)
        self.project_sheet_workspace.remove_view_requested.connect(
            lambda index: self.project_sheets_palette.remove_view_from_active_sheet(index)
        )
        self.project_sheet_workspace.element_identification_requested.connect(
            self._add_project_view_identification
        )
        self.project_sheet_workspace.identification_finished.connect(
            self._finish_project_view_identification
        )
        self.project_sheet_workspace.dimension_finished.connect(
            self._finish_project_view_dimension
        )
        self.project_sheet_workspace.dimension_step_changed.connect(
            self._project_view_dimension_step_changed
        )
        self.project_sheet_view_panel.scale_edited.connect(
            self._project_sheet_view_scale_edited
        )
        self.project_sheet_view_panel.axes_visibility_edited.connect(
            self._project_sheet_view_axes_visibility_edited
        )
        self.project_sheet_identification_panel.property_toggled.connect(
            self._project_sheet_identification_property_toggled
        )
        self.selected: tuple[str, str] | None = None
        self.selected_elements: list[tuple[str, str]] = []
        self._plate_selection = []
        self._plate_segments = []
        self._plate_manual_segments = []
        self._plate_manual_start = None
        self._plate_saved_endpoint_snap = None
        self.scene.element_clicked.connect(self.select_element)
        self.scene.analysis_point_clicked.connect(self._show_analysis_point_result)
        self.scene.solid_face_clicked.connect(self._align_member_endpoint_to_face)
        self.scene.alignment_face_clicked.connect(self._align_element_face_to_reference)
        self.scene.empty_clicked.connect(self._empty_scene_clicked)
        self.scene.selection_changed.connect(self._selection_changed)
        self.scene.enter_pressed.connect(self._confirm_copy_elements)
        self.scene.enter_pressed.connect(self._confirm_scene_view_selection)
        self.scene.enter_pressed.connect(self._confirm_command_selection)
        self.scene.placement_point_clicked.connect(self._handle_member_placement_point)
        self.scene.member_midpoint_pending.connect(self._member_midpoint_pending)
        self.scene.placement_point_clicked.connect(self._handle_node_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_reference_axis_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_rigid_bar_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_copy_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_measurement_point)
        self.scene.placement_point_clicked.connect(self._handle_detail_plane_placement_point)
        self._make_shortcuts()
        self.palette = FloatingPalette(self)
        self.palette.reposition()
        self.top_icon_palette = TopIconPalette(self)
        self.top_icon_palette.set_member_direction_normalization_enabled(
            self._member_direction_normalization_enabled
        )
        self.top_icon_palette.reposition()
        self.verification_top_palette = VerificationTopPalette(self)
        self.verification_top_palette.reposition()
        self.member_property_copy_panel = MemberPropertyCopyPanel(self)
        self.selected_action_name: str | None = None
        self.action_top_palette = ActionTopPalette(self)
        self.refresh_action_palette()
        self.action_top_palette.set_actions_visible(False)
        self.action_top_palette.reposition()
        self.selected_analysis_combination: str | None = None
        self.selected_analysis_diagram = "Normal"
        self.analysis_top_palette = AnalysisTopPalette(self)
        self.refresh_analysis_palette()
        self.analysis_top_palette.set_analysis_visible(False)
        self.analysis_top_palette.reposition()
        self.detailing_top_palette = DetailingTopPalette(self)
        self.detailing_top_palette.reposition()
        self.detailing_mode_palette = DetailingModePalette(self)
        self.detailing_mode_palette.reposition()
        self.project_sheets_palette = ProjectSheetsPalette(self)
        self.project_sheets_palette.reposition()
        self.navigation_button = QToolButton(self)
        self.navigation_button.setObjectName("navigationButton")
        self.navigation_button.setFixedSize(34, 34)
        self._navigation_plane_icons = ("axis-plane-xy.svg", "axis-plane-xz.svg", "axis-plane-yz.svg")
        self._navigation_plane_modes = ("XY", "XZ", "YZ")
        self._navigation_plane_index = 0
        self.navigation_button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 7px; padding: 0; "
            "background: #f6f8fa; color: #57606a; }"
            "QToolButton:hover { background: #eaeef2; color: #24292f; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        self.navigation_button.setIconSize(QSize(21, 21))
        self._navigation_tooltip = PaletteTooltip(self)
        self.navigation_button.setToolTip("Enquadrar modelo")
        self.navigation_button.setProperty("paletteTooltip", "Enquadrar modelo")
        self.navigation_button.setAccessibleName("Enquadrar modelo")
        self.navigation_button.installEventFilter(self)
        self.navigation_button.clicked.connect(self.scene.reset_camera)
        self.navigation_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "maximize.svg"))
        )
        self.sloped_plane_button = SlopedPlaneButton(
            self, horizontal_chamfer=12.0, icon_offset_x=-3, icon_offset_y=2,
        )
        self.sloped_plane_button.setObjectName("slopedPlaneButton")
        self.sloped_plane_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "corner-left-up.svg"))
        )
        self.sloped_plane_button.setIconSize(QSize(18, 18))
        self.sloped_plane_button.setToolTip("Rotacionar +90°")
        self.sloped_plane_button.setProperty("paletteTooltip", "Rotacionar +90°")
        self.sloped_plane_button.setAccessibleName("Rotacionar +90°")
        self.sloped_plane_button.installEventFilter(self)
        self.sloped_plane_button.clicked.connect(self.scene.rotate_camera_clockwise)
        self.sloped_plane_right_button = SlopedPlaneButton(
            self, vertical_chamfer=12.0, icon_offset_x=-2, icon_offset_y=3,
        )
        self.sloped_plane_right_button.setObjectName("slopedPlaneRightButton")
        self.sloped_plane_right_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "corner-down-right.svg"))
        )
        self.sloped_plane_right_button.setIconSize(QSize(18, 18))
        self.sloped_plane_right_button.setToolTip("Rotacionar -90°")
        self.sloped_plane_right_button.setProperty("paletteTooltip", "Rotacionar -90°")
        self.sloped_plane_right_button.setAccessibleName("Rotacionar -90°")
        self.sloped_plane_right_button.installEventFilter(self)
        self.sloped_plane_right_button.clicked.connect(self.scene.rotate_camera_counterclockwise)
        self.previous_plane_button = LeftArrowButton(self)
        self.previous_plane_button.setObjectName("previousPlaneButton")
        self.previous_plane_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "chevron-left.svg"))
        )
        self.previous_plane_button.setIconSize(QSize(20, 20))
        self.previous_plane_button.setToolTip("Plano anterior")
        self.previous_plane_button.setProperty("paletteTooltip", "Plano anterior")
        self.previous_plane_button.setAccessibleName("Plano anterior")
        self.previous_plane_button.installEventFilter(self)
        self.previous_plane_button.clicked.connect(self.scene.previous_reference_plane)
        self.plane_change_button = QToolButton(self)
        self.plane_change_button.setObjectName("planeChangeButton")
        self.plane_change_button.setFixedSize(34, 34)
        self.plane_change_button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 7px; padding: 0; "
            "background: #f6f8fa; color: #57606a; }"
            "QToolButton:hover { background: #eaeef2; color: #24292f; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        self.plane_change_button.setIconSize(QSize(21, 21))
        self.plane_change_button.setToolTip("Alterar plano")
        self.plane_change_button.setProperty("paletteTooltip", "Alterar plano")
        self.plane_change_button.setAccessibleName("Alterar plano")
        self.plane_change_button.installEventFilter(self)
        self.plane_change_button.clicked.connect(self._cycle_navigation_plane)
        self._update_navigation_button_icon()
        self.next_plane_button = RightArrowButton(self)
        self.next_plane_button.setObjectName("nextPlaneButton")
        self.next_plane_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "chevron-right.svg"))
        )
        self.next_plane_button.setIconSize(QSize(20, 20))
        self.next_plane_button.setToolTip("Próximo plano")
        self.next_plane_button.setProperty("paletteTooltip", "Próximo plano")
        self.next_plane_button.setAccessibleName("Próximo plano")
        self.next_plane_button.installEventFilter(self)
        self.next_plane_button.clicked.connect(self.scene.next_reference_plane)
        self._reposition_navigation_button()
        self.properties = PropertyPanel(self)
        self.subtractions_panel = SubtractionsPanel(self)
        self._detail_subtraction_visible_refs: set[tuple[str, str, str, str]] = set()
        self.displacement_panel = DisplacementPanel(self)
        self.calculation_properties_panel = CalculationPropertiesPanel(self)
        self.processing_panel = ProcessingPanel(self)
        self.verification_panel = VerificationPanel(self)
        self.axes_panel = AxesPanel(self)
        self.axes_panel.axis_selection_changed.connect(self.scene.set_selected_reference_axis)
        self.reference_panel = ReferencePanel(self)
        self.axes_panel.visibility_changed.connect(self.top_icon_palette.configure_axes_button.setChecked)
        self.reference_panel.visibility_changed.connect(self.top_icon_palette.configure_reference_button.setChecked)
        self.split_member_dialog = SplitMemberDialog(self)
        self.section_panels = {
            "W Laminado": WLaminadoSectionPanel(self),
            "HP Laminado": HPLaminadoSectionPanel(self),
            "I Laminado": ILaminadoSectionPanel(self),
            "U Laminado": ULaminadoSectionPanel(self),
            "L Laminado": LLaminadoSectionPanel(self),
            "T Laminado": TLaminadoSectionPanel(self),
        }
        self.section_panels.update({
            family: ParametricSectionPanel(self, family)
            for family in SECTION_PARAMETRIC_SPECS
        })
        self.section_panel = self.section_panels["W Laminado"]
        self.member_placement_editor = MemberPlacementEditor(self)
        self.history = CommandHistory(self)
        self.command_bar = CommandBar(self)
        self.scene.plotter.installEventFilter(self)
        self.command_bar.input.installEventFilter(self)
        self.command_bar.reposition()
        self.history.reposition()
        self.refresh_scene()
        self.mcp_model_changed.connect(self._refresh_after_mcp_change)
        self.mcp_view_changed.connect(self._apply_mcp_view_change)
        self.mcp_scene_views_changed.connect(self._refresh_after_mcp_scene_views_change)
        self.mcp_active_action_changed.connect(self._select_active_action)
        self.mcp_analysis_view_changed.connect(self._apply_mcp_analysis_view)
        self.mcp_analysis_diagrams_changed.connect(self.scene.set_analysis_diagrams_visible)
        self.mcp_session_changed.connect(self.palette.show_group)
        self._mcp_dispatcher = McpQtDispatcher(self)
        self._mcp_dispatcher.suspend()
        self._mcp_dispatcher.busy_changed.connect(self.command_bar.set_mcp_busy)
        self._mcp_application = McpApplication(
            self.model,
            self.model_service,
            analysis_engine=self.analysis_service.engine,
            on_model_changed=self.mcp_model_changed.emit,
            on_view_changed=self.mcp_view_changed.emit,
            on_scene_views_changed=self.mcp_scene_views_changed.emit,
            get_view_state=self.scene.view_state,
            on_active_action_changed=self.mcp_active_action_changed.emit,
            get_active_action=lambda: self.selected_action_name,
            on_analysis_view_changed=self.mcp_analysis_view_changed.emit,
            get_analysis_view_state=self.scene.analysis_view_state,
            on_analysis_diagrams_changed=self.mcp_analysis_diagrams_changed.emit,
            on_session_changed=self.mcp_session_changed.emit,
            get_session=lambda: self.palette.active_group,
            model_lock=self._model_access_lock,
            execute_on_model_thread=self._mcp_dispatcher.call,
            on_operation_started=self._mcp_dispatcher.begin_operation,
            on_operation_finished=self._mcp_dispatcher.end_operation,
        )
        self._mcp_server = LocalMcpServer(self._mcp_application)
        self._mcp_integration = LocalMcpIntegration()
        self._mcp_enabled = False
        self.home.new_project_requested.connect(self.new_model)
        self.home.open_project_requested.connect(self.open_model)
        self.home.import_project_requested.connect(self.import_model)
        self.home.recent_project_requested.connect(self._open_recent_project)
        self.home.manual_requested.connect(self.open_manual)
        self.show_home()

    def process_analysis(self, checked: bool = False) -> None:
        """Run PyNite in the background after the progress card is painted."""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            return
        try:
            require_no_pending_plates(self.model.import_metadata)
        except ValueError as error:
            self.show_error(str(error))
            return
        if self.model.import_metadata.get("requires_review"):
            dialog = ImportReportDialog(self.model.import_metadata, self, review=True)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self.project_service.confirm_import_review()
        orphaned_actions = self.model.remove_orphaned_actions()
        if orphaned_actions:
            self.history.append(
                "> <b>Analisar estrutura</b> "
                f"<span style='color:#57606a'>({len(orphaned_actions)} ação(ões) órfã(s) removida(s))</span>"
            )
            self.refresh_action_palette()
            self.refresh_scene()
        self.action_service.ensure_default_combinations()
        self.refresh_analysis_palette()
        self.processing_panel.start()
        self._analysis_revision = self.model.revision
        snapshot = copy.deepcopy(self.model)
        thread = QThread(self)
        worker = AnalysisWorker(snapshot, AnalysisRequest())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._update_processing_stage)
        worker.finished.connect(self._analysis_finished)
        worker.failed.connect(self._analysis_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._analysis_thread_finished)
        self._analysis_thread = thread
        self._analysis_worker = worker
        thread.start()

    def verify_model(self) -> None:
        """Run member checks only when current analysis results are available."""
        if self._verification_thread is not None and self._verification_thread.isRunning():
            return
        if self._has_calculation_property_overrides() and self._confirm_reset_calculation_properties():
            self._reset_calculation_property_overrides()
            self.refresh_scene()
            self.refresh_selected_property_panel(self.palette.active_group)
            if self.calculation_properties_panel.isVisible():
                self.calculation_properties_panel.configure_for(
                    tuple(self.properties._selected_names("bar")),
                )
        self._start_verification()

    def verify_selected_bar(self) -> None:
        """Verify only the selected bar or verification group with current overrides."""
        names = tuple(dict.fromkeys(self.properties._selected_names("bar")))
        if not names or self._verification_is_running():
            return
        self._start_verification(names)

    def _verification_is_running(self) -> bool:
        if self._verification_thread is not None and self._verification_thread.isRunning():
            return True
        return False

    def _has_calculation_property_overrides(self) -> bool:
        return any(
            member.calculation_property_overrides
            for member in self.model.bars.values()
        )

    def _confirm_reset_calculation_properties(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle("Propriedades de cálculo alteradas")
        dialog.setText(
            "Há barras com propriedades de cálculo alteradas manualmente. "
            "Deseja restaurar os valores padrão antes de verificar o modelo?"
        )
        restore_button = dialog.addButton("Sim", QMessageBox.ButtonRole.YesRole)
        keep_button = dialog.addButton("Não", QMessageBox.ButtonRole.NoRole)
        dialog.setDefaultButton(keep_button)
        dialog.exec()
        return dialog.clickedButton() is restore_button

    def _reset_calculation_property_overrides(self) -> None:
        for name, member in tuple(self.model.bars.items()):
            for property_name, _value in member.calculation_property_overrides:
                self.model.update_bar_calculation_property(name, property_name, None)

    def _start_verification(self, member_names: tuple[str, ...] | None = None) -> None:
        """Run checks using a private snapshot of the current model."""
        if self._verification_is_running():
            return
        results_are_current = bool(self.model.analysis_results) and all(
            result.model_revision == self.model.revision
            for result in self.model.analysis_results
        )
        if not results_are_current:
            return
        self.verification_panel.start()
        self._verification_revision = self.model.revision
        self._verification_group_revision = self.model.verification_group_revision
        self._verification_properties_revision = self.model.calculation_properties_revision
        self._verification_restraint_angle_degrees = self._minimum_bar_restraint_angle_degrees
        self._verification_result_ids = tuple(id(result) for result in self.model.analysis_results)
        restraint_cache = self.model._restraint_lengths_cache
        self.model._restraint_lengths_cache = None
        try:
            snapshot = copy.deepcopy(self.model)
        except Exception as error:  # noqa: BLE001
            self._verification_scope_names = None
            self._verification_revision = None
            self._verification_group_revision = None
            self._verification_properties_revision = None
            self._verification_restraint_angle_degrees = None
            self._verification_result_ids = None
            self.verification_panel.fail(str(error) or "não foi possível preparar o modelo para verificação")
            return
        finally:
            self.model._restraint_lengths_cache = restraint_cache
        thread = QThread(self)
        worker = VerificationWorker(snapshot, member_names)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        self._verification_scope_names = member_names
        worker.finished.connect(self._verification_finished)
        worker.failed.connect(self._verification_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._verification_thread_finished)
        self._verification_thread = thread
        self._verification_worker = worker
        thread.start()

    def _verification_finished(self, payload: object) -> None:
        member_names = self._verification_scope_names
        current_result_ids = tuple(id(result) for result in self.model.analysis_results)
        if (self._verification_revision != self.model.revision
                or self._verification_group_revision != self.model.verification_group_revision
                or self._verification_properties_revision != self.model.calculation_properties_revision
                or self._verification_restraint_angle_degrees != self._minimum_bar_restraint_angle_degrees
                or self._verification_result_ids != current_result_ids):
            self.verification_panel.fail(
                "O modelo foi alterado durante a verificação. Execute as verificações novamente."
            )
            return
        if member_names is None:
            self.model.verification_results = payload["results"]
        else:
            self.model.verification_results.update(payload["results"])
        self.refresh_scene()
        self.scene.refresh_utilization_thermometer()
        self.refresh_selected_property_panel(self.palette.active_group)
        self.verification_panel.succeed(payload["summary"])
        action = "Verificar barra" if member_names is not None else "Verificar modelo"
        self.history.append(
            f"> <b>{action}</b> "
            f"<span style='color:#57606a'>({payload['summary']['with_routine']} elemento(s) verificado(s))</span>"
        )

    def _verification_failed(self, message: str) -> None:
        self.verification_panel.fail(message)

    def _verification_thread_finished(self) -> None:
        thread = self._verification_thread
        self._verification_worker = None
        self._verification_thread = None
        self._verification_scope_names = None
        self._verification_revision = None
        self._verification_group_revision = None
        self._verification_properties_revision = None
        self._verification_restraint_angle_degrees = None
        self._verification_result_ids = None
        if thread is not None:
            thread.deleteLater()

    def _analysis_finished(self, results: object) -> None:
        if self._analysis_revision != self.model.revision:
            self.processing_panel.fail(
                "O modelo foi alterado durante a análise. Execute o processamento novamente."
            )
            return
        self.model.analysis_results = list(results)
        self.refresh_analysis_palette()
        self.refresh_selected_property_panel(self.palette.active_group)
        self.processing_panel.succeed()

    def _analysis_failed(self, message: str) -> None:
        self.processing_panel.fail(message)

    def _analysis_thread_finished(self) -> None:
        thread = self._analysis_thread
        self._analysis_worker = None
        self._analysis_thread = None
        if thread is not None:
            thread.deleteLater()

    def _update_processing_stage(self, stage: str) -> None:
        self.processing_panel.set_stage(stage)
        QApplication.processEvents()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
        # The geometry inspector and placement editor keep material selectors
        # alive while the modal catalog editor is open. Rebuild them from the
        # updated project catalog when it closes so additions/removals are
        # immediately reflected in the bar material selector.
        if self.member_placement_editor.isVisible():
            self.member_placement_editor.show()
        selected = self.properties._selected
        if selected and selected[0] == "bar" and self.palette.active_group == "Geometria":
            if self.section_panel.isVisible():
                self.close_section_panel()
            self.properties.show_for(
                selected[0], selected[1], "Geometria", selection=self.properties._selection,
            )

    def open_program_settings(self) -> None:
        dialog = ProgramSettingsDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
        self.set_plate_result_display_mode(dialog.selected_plate_result_display_mode)

    def set_detailing_project_mode(self, active: bool) -> None:
        """Switch between the detailing model and its blank project sheet view."""
        self._detailing_project_mode = bool(active)
        if self._detailing_project_mode and hasattr(self, "project_sheets_palette"):
            self.refresh_project_sheet_views(
                self.project_sheets_palette.sheet_selector.currentText(),
            )
        if not self._detailing_project_mode and hasattr(self, "project_sheet_workspace"):
            self.project_sheet_workspace.select_view(None)
        if self.view_stack.currentWidget() is not self.home:
            self.view_stack.setCurrentWidget(
                self.project_sheet_workspace if self._detailing_project_mode else self.scene
            )
        model_navigation_controls = (
            self.navigation_button,
            self.sloped_plane_button,
            self.sloped_plane_right_button,
            self.previous_plane_button,
            self.plane_change_button,
            self.next_plane_button,
        )
        for control in model_navigation_controls:
            if self._detailing_project_mode:
                control.hide()
            elif self.view_stack.currentWidget() is not self.home:
                control.show()
        if not self._detailing_project_mode and self.view_stack.currentWidget() is not self.home:
            self._reposition_navigation_button()
        self.project_sheet_workspace.set_model_name(self.scene.model_name)
        detailing_active = self.palette.active_group == "Detalhamento"
        self.detailing_top_palette.set_detailing_visible(
            detailing_active and not self._detailing_project_mode
        )
        if hasattr(self, "project_sheets_palette"):
            self.project_sheets_palette.set_project_mode(
                self._detailing_project_mode
                and detailing_active
                and self.view_stack.currentWidget() is not self.home
            )

    def refresh_project_sheet_views(self, sheet_name: str | None = None) -> None:
        """Regenerate saved sheet linework from the current model on sheet open."""
        palette = getattr(self, "project_sheets_palette", None)
        if palette is None:
            return
        sheet_name = sheet_name or palette.sheet_selector.currentText()
        views = palette._sheet_views.get(sheet_name)
        if views is None:
            return

        state_changed = False
        for view in views:
            if self._refresh_project_view_identifications(view):
                state_changed = True
            if view.get("model_revision") == self.model.revision:
                continue
            projection = view.get("projection")
            if not isinstance(projection, dict):
                continue
            plane = projection.get("plane")
            if not isinstance(plane, str) or "coordinate" not in projection:
                continue
            calculator = _ViewGeometryCalculator()
            calculator._mesh_cache_owner = self.model
            calculator._detail_scene = self.scene
            try:
                DetailingViewPreview.set_view(
                    calculator,
                    self.model,
                    plane,
                    projection["coordinate"],
                    upper_offset_cm=float(projection.get("upper_offset_cm", 50.0)),
                    lower_offset_cm=float(projection.get("lower_offset_cm", 50.0)),
                    orientation=str(projection.get("orientation", "Superior para inferior")),
                    rotation_degrees=float(projection.get("rotation_degrees", 0.0)),
                )
            except (IndexError, KeyError, OverflowError, RuntimeError, TypeError, ValueError):
                continue
            segments = tuple(calculator._segments_2d)
            owners = tuple(calculator._segment_sources)
            if (
                segments != tuple(view.get("segments", ()))
                or owners != tuple(view.get("segment_owners", ()))
            ):
                view["segments"] = segments
                view["segment_owners"] = owners
                state_changed = True
            view["model_revision"] = self.model.revision
            state_changed = True

        if state_changed:
            if palette.sheet_selector.currentText() == sheet_name:
                self.project_sheet_workspace.set_sheet_views(views)
            self._store_detailing_state()

    def _sync_project_sheet_view_settings(
        self,
        view_settings: dict,
        view_definitions: dict,
        view_names: dict,
        view_fallbacks: dict,
    ) -> None:
        """Refresh sheet instances linked to definitions changed in the view manager."""
        palette = getattr(self, "project_sheets_palette", None)
        if palette is None:
            return
        model_key = id(self.model)
        default_settings = {"top": 50.0, "bottom": 50.0, "orientation": 0, "rotation": 0.0}
        changed_sheets: set[str] = set()
        orientation_names = ("Superior para inferior", "Inferior para superior")

        def coordinates_match(first, second) -> bool:
            try:
                first_array = np.asarray(first, dtype=float)
                second_array = np.asarray(second, dtype=float)
            except (TypeError, ValueError):
                return False
            return (
                first_array.shape == second_array.shape
                and bool(np.allclose(first_array, second_array, rtol=0.0, atol=1e-9))
            )

        for sheet_name, views in palette._sheet_views.items():
            for view in views:
                projection = view.get("projection")
                if not isinstance(projection, dict):
                    continue
                for view_key, definition in view_definitions.items():
                    if not isinstance(view_key, tuple) or len(view_key) != 2 or view_key[0] != model_key:
                        continue
                    plane, coordinate = definition
                    stable_key = str(view_key[1])
                    linked = view.get("detail_view_key") == stable_key
                    same_definition = (
                        projection.get("plane") == plane
                        and coordinates_match(projection.get("coordinate"), coordinate)
                    )
                    if not linked and not same_definition:
                        continue
                    settings = view_settings.get(view_key, default_settings)
                    orientation_index = min(
                        len(orientation_names) - 1,
                        max(0, int(settings.get("orientation", 0))),
                    )
                    updated_projection = {
                        "upper_offset_cm": float(settings.get("top", 50.0)),
                        "lower_offset_cm": float(settings.get("bottom", 50.0)),
                        "orientation": orientation_names[orientation_index],
                        "rotation_degrees": float(settings.get("rotation", 0.0)),
                    }
                    view_name = str(view_names.get(view_key, "")).strip()
                    updated_name = view_name or str(
                        view_fallbacks.get(view_key, view.get("name", "Vista"))
                    )
                    instance_changed = (
                        any(projection.get(key) != value for key, value in updated_projection.items())
                        or view.get("detail_view_key") != stable_key
                        or view.get("name") != updated_name
                    )
                    if not instance_changed:
                        break
                    projection.update(updated_projection)
                    view["detail_view_key"] = stable_key
                    view["name"] = updated_name
                    view["model_revision"] = None
                    changed_sheets.add(sheet_name)
                    break

        if not changed_sheets:
            return
        for sheet_name in changed_sheets:
            self.refresh_project_sheet_views(sheet_name)
        self._store_detailing_state()

    def _refresh_project_view_identifications(self, view: dict) -> bool:
        """Refresh label text from current element names and bar sections."""
        changed = False
        for identification in view.get("identifications", ()):
            if not isinstance(identification, dict):
                continue
            before = (
                identification.get("text"),
                identification.get("text_lines"),
                identification.get("text_runs"),
                identification.get("show_identity"),
                identification.get("show_name"),
                identification.get("show_section"),
            )
            self._update_project_identification_text(identification)
            after = (
                identification.get("text"),
                identification.get("text_lines"),
                identification.get("text_runs"),
                identification.get("show_identity"),
                identification.get("show_name"),
                identification.get("show_section"),
            )
            if before != after:
                changed = True
        return changed

    def _project_sheet_view_selected(self, view: dict | None) -> None:
        identification_panel = getattr(self, "project_sheet_identification_panel", None)
        if identification_panel is not None:
            identification_panel.hide()
        panel = getattr(self, "project_sheet_view_panel", None)
        if panel is not None:
            panel.show_for(view)

    def _project_sheet_identification_selected(self, identification: dict | None) -> None:
        panel = getattr(self, "project_sheet_identification_panel", None)
        if panel is None:
            return
        if identification is None:
            panel.hide()
            selected = self.project_sheet_workspace._selected_view_index
            views = self.project_sheet_workspace._sheet_views
            view = views[selected] if selected is not None and selected < len(views) else None
            self.project_sheet_view_panel.show_for(view)
            return
        self.project_sheet_view_panel.hide()
        identifications = identification if isinstance(identification, (list, tuple)) else [identification]
        properties = [
            self._project_sheet_identification_properties(item)
            for item in identifications if isinstance(item, dict)
        ]
        if not properties:
            panel.hide()
            return
        aggregated = {}
        for key in ("identity", "name", "section"):
            values = [item[key] for item in properties]
            aggregated[key] = values[0] if all(value == values[0] for value in values) else "Variado"
            states = [item[f"show_{key}"] for item in properties]
            aggregated[f"show_{key}"] = (
                Qt.CheckState.PartiallyChecked
                if any(state != states[0] for state in states)
                else Qt.CheckState.Checked if states[0] else Qt.CheckState.Unchecked
            )
            aggregated[f"disabled_{key}"] = all(item[f"disabled_{key}"] for item in properties)
        panel.show_for(aggregated)

    def _project_sheet_identification_properties(self, identification: dict) -> dict:
        """Resolve read-only identifier properties from the current model."""
        kind = str(identification.get("kind", ""))
        element = str(identification.get("element", ""))
        identity = element.replace("|", ", ")
        name = ""
        section = ""

        if kind in {"bar", "bar_group"}:
            member_names = tuple(
                member for member in element.split("|") if member
            ) if kind == "bar_group" else (element,)
            bars = [self.model.bars[member] for member in member_names if member in self.model.bars]
            if kind == "bar_group" and member_names:
                group = self.model.verification_group_for(member_names[0])
                if group is not None:
                    name = str(group.get("name", "")).strip()
            elif bars:
                name = str(self.model.verification_element_names.get(bars[0].name, "")).strip()
            section_names = list(dict.fromkeys(
                str(bar.profile or self.section_profiles.get(bar.name) or bar.section).strip()
                for bar in bars
                if str(bar.profile or self.section_profiles.get(bar.name) or bar.section).strip()
            ))
            section = " / ".join(section_names)
        elif kind == "plate":
            name = str(self.model.plate_display_names.get(element, "")).strip()
        elif kind == "node":
            name = str(self.model.node_display_names.get(element, "")).strip()

        if (
            not identification.get("visibility_customized")
            and "show_identity" not in identification
            and "show_name" not in identification
        ):
            identification["show_name"] = bool(name)
            identification["show_identity"] = not bool(name)
            identification["show_section"] = bool(section)
        else:
            identification.setdefault("show_section", bool(section))
        return {
            "identity": identity,
            "name": name,
            "section": section,
            "show_identity": identification.get("show_identity", False),
            "show_name": identification.get("show_name", False),
            "show_section": identification.get("show_section", False),
            "disabled_identity": False,
            "disabled_name": not bool(name),
            "disabled_section": not bool(section),
        }

    def _project_sheet_identification_property_toggled(self, key: str, state: int) -> None:
        workspace = self.project_sheet_workspace
        view_index = workspace._selected_view_index
        if view_index is None or not 0 <= view_index < len(workspace._sheet_views):
            return
        identifications = workspace._sheet_views[view_index].get("identifications", [])
        selected = [
            identifications[index]
            for index in workspace._selected_identification_indices
            if 0 <= index < len(identifications)
        ]
        if not selected:
            return
        checked = state != Qt.CheckState.Unchecked.value
        for identification in selected:
            properties = self._project_sheet_identification_properties(identification)
            if key in {"identity", "name"}:
                name_available = bool(properties["name"])
                if key == "name" and not name_available:
                    continue
                other = "name" if key == "identity" else "identity"
                if checked:
                    identification[f"show_{key}"] = True
                    identification[f"show_{other}"] = False
                elif (
                    not identification.get("show_section")
                    and not identification.get(f"show_{other}")
                ):
                    # Keep the last visible property enabled.
                    continue
                else:
                    identification[f"show_{key}"] = False
            elif key == "section":
                if (
                    not checked
                    and not identification.get("show_identity")
                    and not identification.get("show_name")
                ):
                    continue
                identification["show_section"] = checked
            identification["visibility_customized"] = True
            self._update_project_identification_text(identification)
        self.project_sheet_workspace.update()
        workspace._emit_identification_selection()
        self._store_detailing_state()

    def _update_project_identification_text(self, identification: dict) -> None:
        properties = self._project_sheet_identification_properties(identification)
        primary = (
            properties["name"] if identification.get("show_name")
            else properties["identity"] if identification.get("show_identity")
            else ""
        )
        section = properties["section"] if identification.get("show_section") else ""
        has_section = bool(section)
        if "stacked_text" not in identification:
            identification["stacked_text"] = (
                len(identification.get("text_runs", ())) > 1
                or len(identification.get("text_lines", ())) > 1
            )
        stacked = bool(identification.get("stacked_text")) and has_section and bool(primary)
        text = f"{primary} {section}".strip()
        identification["text"] = text
        identification["text_lines"] = [primary, section] if stacked else [text]
        identification["text_runs"] = (
            [
                [{"text": primary, "role": "element"}],
                [{"text": section, "role": "section"}],
            ] if stacked else [
                ([{"text": primary, "role": "element"}] if primary else [])
                + ([{"text": f" {section}", "role": "section"}] if has_section else [])
            ]
        )

    def _project_sheet_view_scale_edited(self, text: str) -> None:
        try:
            denominator = float(text.strip().replace(",", "."))
        except ValueError:
            denominator = 0.0
        if denominator <= 0:
            selected = self.project_sheet_workspace._selected_view_index
            views = self.project_sheet_workspace._sheet_views
            self.project_sheet_view_panel.show_for(
                views[selected] if selected is not None and selected < len(views) else None
            )
            return
        self.project_sheet_workspace.set_selected_view_scale(denominator)
        selected = self.project_sheet_workspace._selected_view_index
        views = self.project_sheet_workspace._sheet_views
        self.project_sheet_view_panel.show_for(
            views[selected] if selected is not None and selected < len(views) else None
        )

    def _project_sheet_view_axes_visibility_edited(self, visible: bool) -> None:
        selected = self.project_sheet_workspace._selected_view_index
        views = self.project_sheet_workspace._sheet_views
        if selected is None or selected >= len(views):
            return
        views[selected]["axes_visible"] = bool(visible)
        self.project_sheet_workspace.update()
        self.project_sheet_workspace.layout_changed.emit()

    def start_project_view_identification(self) -> None:
        if not self._detailing_project_mode:
            return
        if not self.project_sheets_palette.sheet_selector.currentText():
            return
        self._command_mode = "project_sheet_identification"
        self.project_sheet_workspace.set_identification_mode(True)
        self.history.append(
            "> <b>Identificar</b> <span style='color:#57606a'>"
            "(Clique sobre um elemento da vista; clique nos próximos; Enter encerra; "
            "Esc encerra preservando as identificações lançadas)</span>"
        )

    def start_project_view_dimension(self) -> None:
        if not self._detailing_project_mode:
            return
        if not self.project_sheets_palette.sheet_selector.currentText():
            return
        self.command_session.cancel()
        self._command_mode = "project_sheet_dimension"
        self.project_sheet_workspace.set_identification_mode(False)
        self.project_sheet_workspace.set_dimension_mode(True)
        self.history.append(
            "> <b>Cota</b> <span style='color:#57606a'>"
            "(Selecione o ponto inicial da cota)</span>"
        )

    def _project_view_dimension_step_changed(self, step: int) -> None:
        if self._command_mode != "project_sheet_dimension":
            return
        prompt = {
            0: "Selecione o ponto inicial da próxima cota",
            1: "Selecione o ponto final da cota",
            2: "Clique na posição da linha de cota",
        }.get(step, "Selecione o ponto inicial da cota")
        self.history.append(f"> <b>Cota</b> <span style='color:#57606a'>({prompt})</span>")

    def _finish_project_view_dimension(self, canceled: bool = False) -> None:
        if self._command_mode != "project_sheet_dimension":
            return
        self._command_mode = None
        self._store_detailing_state()
        message = "Lançamento cancelado" if canceled else "Cota lançada"
        self.history.append(f"> <b>Cota</b> <span style='color:#8c959f'>({message})</span>")

    def _finish_project_view_identification(self, canceled: bool = False) -> None:
        if self._command_mode != "project_sheet_identification":
            return
        self._command_mode = None
        self.project_sheet_workspace.set_identification_mode(False)
        self._store_detailing_state()
        message = (
            "Lançamento cancelado; identificações preservadas"
            if canceled else "Lançamento encerrado"
        )
        self.history.append(
            f"> <b>Identificar</b> <span style='color:#8c959f'>({message})</span>"
        )

    def _add_project_view_identification(self, view_index: int, name: str, projected_point) -> None:
        sheet_name = self.project_sheets_palette.sheet_selector.currentText()
        views = self.project_sheets_palette._sheet_views.get(sheet_name, [])
        if not 0 <= view_index < len(views):
            return
        try:
            projected_point = tuple(float(value) for value in projected_point)
        except (TypeError, ValueError):
            return
        if len(projected_point) != 2:
            return
        view = views[view_index]
        if not name:
            self.history.append(
                "> <b>Identificar</b> <span style='color:#8c959f'>"
                "(Esta vista é antiga; adicione-a novamente para habilitar a identificação)</span>"
            )
            return
        source = str(name)
        kind, separator, owner_name = source.partition(":")
        group_members: tuple[str, ...] = ()
        custom_name = ""
        if kind == "bar_group" and separator:
            group_members = tuple(member for member in owner_name.split("|") if member)
            group = (
                self.model.verification_group_for(group_members[0])
                if group_members else None
            )
            if group is None or set(group.get("members", ())) != set(group_members):
                return
            owner_name = "|".join(group_members)
            custom_name = str(group.get("name", "")).strip()
            label = custom_name or ", ".join(group_members)
        else:
            group = None
        if not separator or kind not in {"bar", "plate", "rigid_bar", "node"}:
            if kind != "bar_group":
                owner_name = source
                kind = ""
        if kind in {"bar", "bar_group", "plate", "rigid_bar", "node"}:
            for existing in view.get("identifications", ()):
                if not isinstance(existing, dict) or existing.get("kind") != kind:
                    continue
                existing_element = str(existing.get("element", ""))
                same_element = (
                    set(existing_element.split("|")) == set(group_members)
                    if kind == "bar_group" else existing_element == owner_name
                )
                if same_element:
                    self.history.append(
                        "> <b>Identificar</b> <span style='color:#8c959f'>"
                        "(Este elemento já possui uma etiqueta nesta vista)</span>"
                    )
                    return
        if kind != "bar_group":
            if kind == "bar":
                custom_name = str(self.model.verification_element_names.get(owner_name, "")).strip()
            elif kind == "plate":
                custom_name = str(self.model.plate_display_names.get(owner_name, "")).strip()
            elif kind == "node":
                custom_name = str(self.model.node_display_names.get(owner_name, "")).strip()
            else:
                custom_name = ""
            label = custom_name or owner_name
        element_label = label
        section_members = group_members if group_members else (
            (owner_name,) if kind == "bar" else ()
        )
        section_labels = []
        for member_name in section_members:
            member = self.model.bars.get(member_name)
            if member is None:
                continue
            section_name = (
                member.profile
                or self.section_profiles.get(member_name)
                or member.section
            )
            section_name = str(section_name).strip()
            if section_name and section_name not in section_labels:
                section_labels.append(section_name)
        section_label = " / ".join(section_labels)
        if section_labels:
            label = f"{element_label} {section_label}"
        segments = view.get("segments", ())
        owners = view.get("segment_owners", ())
        group_source_owners = {f"bar:{member}" for member in group_members}
        element_points = [
            point
            for segment, owner in zip(segments, owners)
            if (
                str(owner) in group_source_owners
                if group_members else str(owner) == source
            )
            for point in segment
        ]
        if not element_points:
            return
        min_x = min(float(point[0]) for point in element_points)
        max_x = max(float(point[0]) for point in element_points)
        min_y = min(float(point[1]) for point in element_points)
        max_y = max(float(point[1]) for point in element_points)
        stacked_text = False
        text_rotation = 0.0
        axis_direction: tuple[float, float] | None = None
        world_length = 0.0
        projected_axis_length = 0.0
        has_projection = isinstance(view.get("projection"), dict)
        for member_name in section_members:
            member = self.model.bars.get(member_name)
            if member is None:
                continue
            start_node = self.model.nodes.get(member.start_node)
            end_node = self.model.nodes.get(member.end_node)
            if start_node is None or end_node is None:
                continue
            start_world = (start_node.x, start_node.y, start_node.z)
            end_world = (end_node.x, end_node.y, end_node.z)
            member_length = math.sqrt(sum(
                (end_world[axis] - start_world[axis]) ** 2 for axis in range(3)
            ))
            world_length += member_length
            if has_projection:
                start_projected = self.project_sheet_workspace._project_world_point(
                    view, start_world,
                )
                end_projected = self.project_sheet_workspace._project_world_point(
                    view, end_world,
                )
                if start_projected is not None and end_projected is not None:
                    projected_dx = end_projected[0] - start_projected[0]
                    projected_dy = end_projected[1] - start_projected[1]
                    projected_axis_length += math.hypot(projected_dx, projected_dy)
                    if axis_direction is None:
                        axis_direction = (projected_dx, projected_dy)
        projected_span = projected_axis_length
        if not has_projection:
            # Older sheets do not store the view projection. Infer an in-plane
            # bar direction from the principal axis of its owned 2D linework.
            coordinates = np.asarray(element_points, dtype=float)
            if coordinates.shape[0] >= 2:
                centered = coordinates - coordinates.mean(axis=0)
                covariance = centered.T @ centered
                eigenvalues, eigenvectors = np.linalg.eigh(covariance)
                direction = eigenvectors[:, int(np.argmax(eigenvalues))]
                axis_direction = (float(direction[0]), float(direction[1]))
                projected_values = centered @ direction
                projected_span = float(projected_values.max() - projected_values.min())
        if axis_direction is not None and world_length > 1e-12:
            if projected_span / world_length < math.sqrt(0.5):
                stacked_text = True
            else:
                if math.hypot(*axis_direction) > 1e-12:
                    text_rotation = math.degrees(math.atan2(-axis_direction[1], axis_direction[0]))
                    if text_rotation > 90.0:
                        text_rotation -= 180.0
                    elif text_rotation < -90.0:
                        text_rotation += 180.0
        denominator = max(1.0, float(view.get("scale_denominator", 100.0)))
        text_height_mm = float(
            self.project_sheets_palette._project_settings.get("view_element_text_height_mm", 3.0)
        )
        gap_mm = 2.0
        gap = (text_height_mm + gap_mm) * denominator / 1000.0
        label_position = ((min_x + max_x) / 2.0, max_y + gap)
        if not stacked_text and axis_direction is not None:
            magnitude = math.hypot(*axis_direction)
            if magnitude > 1e-12:
                axis_x, axis_y = axis_direction[0] / magnitude, axis_direction[1] / magnitude
                normal_x, normal_y = -axis_y, axis_x
                if normal_y < 0.0 or (abs(normal_y) <= 1e-9 and normal_x > 0.0):
                    normal_x, normal_y = -normal_x, -normal_y
                projections = [
                    float(point[0]) * normal_x + float(point[1]) * normal_y
                    for point in element_points
                ]
                normal_center = (min(projections) + max(projections)) / 2.0
                normal_offset = (max(projections) - min(projections)) / 2.0 + gap
                axis_projections = [
                    float(point[0]) * axis_x + float(point[1]) * axis_y
                    for point in element_points
                ]
                axis_center = (min(axis_projections) + max(axis_projections)) / 2.0
                label_position = (
                    axis_center * axis_x + (normal_center + normal_offset) * normal_x,
                    axis_center * axis_y + (normal_center + normal_offset) * normal_y,
                )
        identification = {
            "kind": kind,
            "element": owner_name,
            "text": label,
            "text_lines": (
                [element_label, section_label]
                if stacked_text and section_label else [label]
            ),
            "text_runs": (
                [
                    [{"text": element_label, "role": "element"}],
                    [{"text": section_label, "role": "section"}],
                ]
                if stacked_text and section_label else [
                    [{"text": element_label, "role": "element"}]
                    + ([{"text": f" {section_label}", "role": "section"}] if section_label else [])
                ]
            ),
            "text_rotation_degrees": 0.0 if stacked_text else text_rotation,
            "projected_point": label_position,
            "layout_version": 3,
            "stacked_text": stacked_text,
            "show_identity": not bool(custom_name),
            "show_name": bool(custom_name),
            "show_section": bool(section_label),
        }
        view.setdefault("identifications", []).append(identification)
        self._update_project_identification_text(identification)
        self.project_sheet_workspace.update()
        self._store_detailing_state()
        self.history.append(
            "> <b>Identificar</b> <span style='color:#57606a'>"
            f"({escape(label)} identificado; clique no próximo elemento ou pressione Enter)</span>"
        )

    def _detailing_state_snapshot(self) -> dict:
        palette = self.project_sheets_palette
        model_key = id(self.model)

        def current_model_entries(attribute: str) -> dict:
            values = getattr(self, attribute, {})
            return {
                str(key[1]): copy.deepcopy(value)
                for key, value in values.items()
                if isinstance(key, tuple) and len(key) == 2 and key[0] == model_key
            }

        preferred = getattr(self, "_detailing_preferred_view_key", None)
        return {
            "version": 1,
            "sheets": {
                "sheet_names": list(palette._sheet_names),
                "active_sheet": palette.sheet_selector.currentText(),
                "sheet_settings": copy.deepcopy(palette._sheet_settings),
                "project_settings": copy.deepcopy(palette._project_settings),
                "sheet_views": copy.deepcopy(palette._sheet_views),
            },
            "detail_views": {
                "names": current_model_entries("_detailing_view_names"),
                "settings": current_model_entries("_detailing_view_settings"),
                "custom_planes": copy.deepcopy(
                    getattr(self, "_detailing_custom_planes", {}).get(model_key, [])
                ),
                "preferred_view": (
                    preferred[1]
                    if isinstance(preferred, tuple) and len(preferred) == 2
                    and preferred[0] == model_key else None
                ),
            },
        }

    def _store_detailing_state(self) -> None:
        if not hasattr(self, "project_sheets_palette"):
            return
        state = self._detailing_state_snapshot()
        if state != self.model.detailing_data:
            self.model.detailing_data = state
            self.model.view_revision += 1

    def _restore_detailing_state(self) -> None:
        state = self.model.detailing_data if isinstance(self.model.detailing_data, dict) else {}
        self.project_sheets_palette.restore_detailing_state(state.get("sheets"))
        detail_views = state.get("detail_views", {})
        if not isinstance(detail_views, dict):
            detail_views = {}
        model_key = id(self.model)
        self._detailing_view_names = {
            (model_key, str(key)): str(value)
            for key, value in detail_views.get("names", {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        self._detailing_view_settings = {
            (model_key, str(key)): dict(value)
            for key, value in detail_views.get("settings", {}).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        custom_planes = detail_views.get("custom_planes", [])
        self._detailing_custom_planes = {
            model_key: [dict(item) for item in custom_planes if isinstance(item, dict)]
        }
        preferred = detail_views.get("preferred_view")
        self._detailing_preferred_view_key = (
            (model_key, preferred) if isinstance(preferred, str) else None
        )
        if self._upgrade_project_identification_layouts():
            self.project_sheet_workspace.update()
            self._store_detailing_state()

    def _upgrade_project_identification_layouts(self) -> bool:
        """Recompute label orientation for saved tags made before the layout rules."""
        changed = False
        for views in self.project_sheets_palette._sheet_views.values():
            for view in views:
                for identification in view.get("identifications", ()):
                    if not isinstance(identification, dict) or identification.get("layout_version", 0) >= 3:
                        continue
                    kind = str(identification.get("kind", ""))
                    element = str(identification.get("element", ""))
                    members = (
                        tuple(member for member in element.split("|") if member)
                        if kind == "bar_group" else (element,) if kind == "bar" else ()
                    )
                    bars = [self.model.bars[name] for name in members if name in self.model.bars]
                    if not bars:
                        text = str(identification.get("text", ""))
                        identification["text_runs"] = [[{"text": text, "role": "element"}]]
                        identification["layout_version"] = 3
                        changed = True
                        continue
                    if kind == "bar_group":
                        group = self.model.verification_group_for(bars[0].name)
                        element_label = (
                            str(group.get("name", "")).strip() or ", ".join(members)
                            if group else ", ".join(members)
                        )
                    else:
                        element_label = str(
                            self.model.verification_element_names.get(bars[0].name, "")
                        ).strip() or bars[0].name
                    section_labels = list(dict.fromkeys(
                        str(bar.profile or self.section_profiles.get(bar.name) or bar.section).strip()
                        for bar in bars
                        if str(bar.profile or self.section_profiles.get(bar.name) or bar.section).strip()
                    ))
                    section_label = " / ".join(section_labels)
                    owner_tokens = {f"bar:{bar.name}" for bar in bars}
                    points = [
                        point
                        for segment, owner in zip(
                            view.get("segments", ()), view.get("segment_owners", ()),
                        )
                        if str(owner) in owner_tokens
                        for point in segment
                    ]
                    if len(points) < 2:
                        text = str(identification.get("text", ""))
                        identification["text_runs"] = [[{"text": text, "role": "element"}]]
                        identification["layout_version"] = 3
                        changed = True
                        continue
                    coordinates = np.asarray(points, dtype=float)
                    minimum = coordinates.min(axis=0)
                    maximum = coordinates.max(axis=0)
                    axis_direction = None
                    projected_length = 0.0
                    world_length = 0.0
                    has_projection = isinstance(view.get("projection"), dict)
                    for bar in bars:
                        start_node = self.model.nodes.get(bar.start_node)
                        end_node = self.model.nodes.get(bar.end_node)
                        if start_node is None or end_node is None:
                            continue
                        start = (start_node.x, start_node.y, start_node.z)
                        end = (end_node.x, end_node.y, end_node.z)
                        world_length += math.dist(start, end)
                        if has_projection:
                            start_2d = self.project_sheet_workspace._project_world_point(view, start)
                            end_2d = self.project_sheet_workspace._project_world_point(view, end)
                            if start_2d is not None and end_2d is not None:
                                delta = (end_2d[0] - start_2d[0], end_2d[1] - start_2d[1])
                                projected_length += math.hypot(*delta)
                                if axis_direction is None:
                                    axis_direction = delta
                    if not has_projection:
                        centered = coordinates - coordinates.mean(axis=0)
                        _eigenvalues, eigenvectors = np.linalg.eigh(centered.T @ centered)
                        direction = eigenvectors[:, -1]
                        axis_direction = (float(direction[0]), float(direction[1]))
                        projected = centered @ direction
                        projected_length = float(projected.max() - projected.min())
                    stacked = (
                        world_length > 1e-12
                        and projected_length / world_length < math.sqrt(0.5)
                    )
                    rotation = 0.0
                    if axis_direction is not None and not stacked and math.hypot(*axis_direction) > 1e-12:
                        rotation = math.degrees(math.atan2(-axis_direction[1], axis_direction[0]))
                        if rotation > 90:
                            rotation -= 180
                        elif rotation < -90:
                            rotation += 180
                    label = f"{element_label} {section_label}".strip()
                    identification["text"] = label
                    identification["text_lines"] = (
                        [element_label, section_label] if stacked and section_label else [label]
                    )
                    identification["text_runs"] = (
                        [
                            [{"text": element_label, "role": "element"}],
                            [{"text": section_label, "role": "section"}],
                        ]
                        if stacked and section_label else [
                            [{"text": element_label, "role": "element"}]
                            + ([{"text": f" {section_label}", "role": "section"}] if section_label else [])
                        ]
                    )
                    identification["text_rotation_degrees"] = 0.0 if stacked else rotation
                    denominator = max(1.0, float(view.get("scale_denominator", 100.0)))
                    text_height = float(
                        self.project_sheets_palette._project_settings.get(
                            "view_element_text_height_mm", 3.0,
                        )
                    )
                    gap = (text_height + 2.0) * denominator / 1000.0
                    point = ((minimum[0] + maximum[0]) / 2, maximum[1] + gap)
                    if not stacked and axis_direction is not None and math.hypot(*axis_direction) > 1e-12:
                        axis_length = math.hypot(*axis_direction)
                        axis_x, axis_y = axis_direction[0] / axis_length, axis_direction[1] / axis_length
                        normal_x, normal_y = -axis_y, axis_x
                        if normal_y < 0 or (abs(normal_y) <= 1e-9 and normal_x > 0):
                            normal_x, normal_y = -normal_x, -normal_y
                        normal_values = coordinates @ np.asarray((normal_x, normal_y))
                        axis_values = coordinates @ np.asarray((axis_x, axis_y))
                        normal_center = (float(normal_values.min()) + float(normal_values.max())) / 2
                        axis_center = (float(axis_values.min()) + float(axis_values.max())) / 2
                        offset = (float(normal_values.max()) - float(normal_values.min())) / 2 + gap
                        point = (
                            axis_center * axis_x + (normal_center + offset) * normal_x,
                            axis_center * axis_y + (normal_center + offset) * normal_y,
                        )
                    identification["projected_point"] = point
                    identification["layout_version"] = 3
                    changed = True
        return changed

    def _set_model_display_name(self, name: str) -> None:
        self.scene.set_model_name(name)
        if hasattr(self, "project_sheet_workspace"):
            self.project_sheet_workspace.set_model_name(self.scene.model_name)

    def confirm_remove_project_sheet(self, name: str) -> bool:
        dialog = RemoveProjectSheetDialog(name, self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        return dialog.exec() == QDialog.DialogCode.Accepted

    def open_project_sheet_settings(self) -> None:
        sheet_name = self.project_sheets_palette.sheet_selector.currentText()
        settings = self.project_sheets_palette._sheet_settings.get(sheet_name)
        if not sheet_name or settings is None:
            return
        dialog = ProjectSheetSettingsDialog(
            sheet_name,
            settings,
            self.project_sheets_palette._project_settings,
            self.project_sheets_palette.sheet_selector.count(),
            self,
            rename_sheet_callback=self.project_sheets_palette._rename_sheet,
            sheet_settings=self.project_sheets_palette._sheet_settings,
            sheet_names=self.project_sheets_palette._sheet_names,
        )
        dialog.move(self.geometry().center() - dialog.rect().center())
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.result_settings is not None
            and dialog.result_project_settings is not None
        ):
            self.project_sheets_palette._sheet_settings.update(dialog.result_sheet_settings or {})
            self.project_sheets_palette._project_settings = dialog.result_project_settings
            sheet_name = dialog._active_sheet_label
            self.project_sheet_workspace.set_sheet_settings(
                sheet_name,
                self.project_sheets_palette._sheet_settings[sheet_name],
                self.project_sheets_palette._project_settings,
                len(self.project_sheets_palette._sheet_names),
            )
            self.project_sheets_palette.reorder_sheet(
                sheet_name, dialog.result_settings.get("sheet_number", "01"),
            )

    def open_detailing_views(self) -> None:
        if self._detailing_views_dialog_open:
            return
        self._detailing_views_dialog_open = True
        dialog = None
        updated_view_settings = {}
        updated_view_definitions = {}
        updated_view_names = {}
        updated_view_fallbacks = {}
        cancel_action = getattr(self, "_cancel_placement_action", None)
        cancel_action_was_enabled = cancel_action.isEnabled() if cancel_action is not None else None
        try:
            if cancel_action is not None:
                cancel_action.setEnabled(False)
            dialog = DetailingViewsDialog(self)
            self._detailing_views_dialog = dialog
            dialog._add_plane_requested = False
            dialog._add_view_requested = False
            dialog.move(self.geometry().center() - dialog.rect().center())
            dialog.exec()
            add_plane_requested = dialog._add_plane_requested
            add_view_requested = dialog._add_view_requested
            requested_sheet_view = dialog._requested_sheet_view
            updated_view_settings = copy.deepcopy(dialog._saved_view_settings)
            updated_view_definitions = dict(dialog._view_definitions)
            updated_view_names = dict(dialog._saved_view_names)
            updated_view_fallbacks = dict(dialog._view_fallbacks)
        finally:
            self._detailing_views_dialog_open = False
            self._detailing_views_dialog = None
            if dialog is not None:
                dialog._preview.shutdown()
                dialog.deleteLater()
            if cancel_action is not None:
                cancel_action.setEnabled(cancel_action_was_enabled)
        self._sync_project_sheet_view_settings(
            updated_view_settings,
            updated_view_definitions,
            updated_view_names,
            updated_view_fallbacks,
        )
        self._store_detailing_state()
        if add_view_requested and requested_sheet_view is not None:
            self.project_sheets_palette.add_view_to_active_sheet(requested_sheet_view)
        elif add_plane_requested:
            self._detail_plane_return_to_project = self._detailing_project_mode
            if self._detail_plane_return_to_project:
                self.detailing_mode_palette._buttons[0].click()
            self._start_detail_plane_placement()

    def _detailing_group_member_names(self, member_name: str) -> tuple[str, ...]:
        """Expand a picked bar to its group only while detailing is active."""
        group = (
            self.model.verification_group_for(member_name)
            if self.palette.active_group == "Detalhamento" else None
        )
        if group is not None:
            return tuple(name for name in group["members"] if name in self.model.bars)
        return (member_name,) if member_name in self.model.bars else ()

    def start_member_endpoint_alignment(self) -> None:
        """Start the two-step command for aligning a bar end or plate edge to a face."""
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._endpoint_alignment_source = None
        if not self.scene._solid_members_visible:
            self._apply_mcp_view_change("solid_members_visible", True)
        self.clear_selection()
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.axes_panel.hide()
        self.reference_panel.hide()
        self._command_mode = "endpoint_alignment_bar_selection"
        self.scene.set_endpoint_alignment_target(None)
        self.history.append(
            "> <b>Alinhar extremidade</b> "
            "<span style='color:#57606a'>(Selecione a barra ou placa que será ajustada; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def start_detail_subtraction(self) -> None:
        """Start a target-then-cutter detailing subtraction command."""
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._detail_subtraction_target = None
        if not self.scene._solid_members_visible:
            self._apply_mcp_view_change("solid_members_visible", True)
        self.clear_selection()
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.axes_panel.hide()
        self.reference_panel.hide()
        self._command_mode = "detail_subtraction_target_selection"
        self.history.append(
            "> <b>Subtrair trecho</b> "
            "<span style='color:#57606a'>(Selecione a barra ou placa que será cortada; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def start_face_alignment(self) -> None:
        """Start a two-step command to align one picked face with another."""
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._face_alignment_source = None
        self._face_alignment_source_hit = None
        if not self.scene._solid_members_visible:
            self._apply_mcp_view_change("solid_members_visible", True)
        self.clear_selection()
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.axes_panel.hide()
        self.reference_panel.hide()
        self._command_mode = "face_alignment_source_selection"
        self.scene.set_face_alignment_mode(True)
        self.history.append(
            "> <b>Alinhar faces</b> "
            "<span style='color:#57606a'>(Selecione a face que será movida; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def _align_element_face_to_reference(self, hit: object) -> None:
        """Use two picked faces to translate a bar or plate onto its reference plane."""
        try:
            target_kind, target_name, _cell_id, target_point, target_normal = hit
            target_point = np.asarray(target_point, dtype=float)
            target_normal = np.asarray(target_normal, dtype=float)
        except (TypeError, ValueError):
            return
        if self._command_mode == "face_alignment_source_selection":
            if target_kind not in {"bar", "plate"}:
                self.history.append(
                    "> <b>Alinhar faces</b> "
                    "<span style='color:#8c959f'>(Selecione uma face de barra ou placa)</span>"
                )
                return
            self._face_alignment_source = (target_kind, target_name)
            self._face_alignment_source_hit = (
                target_kind, target_name, _cell_id, target_point.copy(), target_normal.copy(),
            )
            self._command_mode = "face_alignment_reference_selection"
            self.scene.set_face_alignment_mode(True, self._face_alignment_source)
            self.history.append(
                "> <b>Alinhar faces</b> "
                "<span style='color:#57606a'>(Selecione a face que servirá como referência; Esc cancela)</span>"
            )
            self.scene.plotter.setFocus()
            return
        if self._command_mode != "face_alignment_reference_selection":
            return
        source = self._face_alignment_source
        source_hit = self._face_alignment_source_hit
        if source is None or source_hit is None:
            return
        source_kind, source_name = source
        if (target_kind, target_name) == source:
            self.history.append(
                "> <b>Alinhar faces</b> "
                "<span style='color:#8c959f'>(Escolha uma face de outro elemento como referência)</span>"
            )
            return
        _source_kind, _source_name, source_cell, source_point, source_normal = source_hit
        source_point = np.asarray(source_point, dtype=float)
        source_normal = np.asarray(source_normal, dtype=float)
        normal_length = float(np.linalg.norm(target_normal))
        source_normal_length = float(np.linalg.norm(source_normal))
        if (
            normal_length <= 1e-12 or source_normal_length <= 1e-12
            or not np.isfinite(target_point).all() or not np.isfinite(source_point).all()
        ):
            return
        target_normal /= normal_length
        source_normal /= source_normal_length
        if source_kind == "plate" and source_cell >= 2:
            try:
                edge_name, offset_mm, angle_degrees = self._plate_edge_alignment_values(
                    self.model.plates[source_name], source_cell - 2,
                    target_point, target_normal,
                )
                plate = self.model.plates[source_name]
                saved = {
                    name: (offset, angle)
                    for name, offset, angle in plate.edge_positioning
                }
                saved[edge_name] = (offset_mm, angle_degrees)
                edge_values = tuple(
                    (name, *saved.get(name, (0.0, 0.0)))
                    for _kind, name in plate.supports
                )
                self.model_service.update_plate_edge_positioning(source_name, edge_values)
                self.scene.update_plate_rendering(source_name)
            except (KeyError, ValueError) as error:
                self.history.append(
                    f"> <b>Alinhar faces</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
                )
                return
            self._face_alignment_source = None
            self._face_alignment_source_hit = None
            self._command_mode = "face_alignment_source_selection"
            self.scene.set_face_alignment_mode(True)
            self.clear_selection()
            self.history.append(
                "> <b>Alinhar faces</b> "
                f"<span style='color:#57606a'>(Face da aresta {escape(edge_name)} alinhada por "
                f"YZ = {offset_mm:.2f} mm e α = {angle_degrees:.2f}°. "
                "Selecione outra face para continuar; Esc encerra)</span>"
            )
            self.scene.plotter.setFocus()
            return
        if abs(float(np.dot(source_normal, target_normal))) < 1.0 - 1e-6:
            self.history.append(
                "> <b>Alinhar faces</b> "
                "<span style='color:#8c959f'>(As faces selecionadas precisam ser paralelas)</span>"
            )
            return
        gap = float(np.dot(target_normal, source_point - target_point))
        translation = -gap * target_normal
        source_names = (
            self._detailing_group_member_names(source_name)
            if source_kind == "bar" else (source_name,)
        )
        try:
            if source_kind == "plate":
                plate = self.model.plates[source_name]
                points = np.asarray(plate.contour, dtype=float)
                _, _, basis = np.linalg.svd(points - points[0], full_matrices=False)
                plate_normal = basis[-1]
                if plate_normal[np.argmax(np.abs(plate_normal))] < 0:
                    plate_normal = -plate_normal
                if abs(float(np.dot(plate_normal, target_normal))) < 1.0 - 1e-6:
                    raise ValueError("A placa só pode ser movida perpendicularmente ao seu plano.")
                displacement = plate.positioning_displacement + float(np.dot(translation, plate_normal))
                self.model_service.update_plate_positioning_displacement(source_name, displacement)
                self.scene.update_plate_rendering(source_name)
                self.properties.update_positioning_status(source_name)
            elif source_kind == "bar":
                self._translate_bar_positioning(source_names, translation)
                for name in source_names:
                    self.refresh_member_positioning(name)
                    self.properties.update_positioning_status(name)
            else:
                raise ValueError("Alinhar faces funciona com barras e placas.")
        except (KeyError, ValueError) as error:
            self.history.append(
                f"> <b>Alinhar faces</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        distance_mm = abs(gap) * 1000.0
        self._face_alignment_source = None
        self._face_alignment_source_hit = None
        self._command_mode = "face_alignment_source_selection"
        self.scene.set_face_alignment_mode(True)
        self.clear_selection()
        self.history.append(
            "> <b>Alinhar faces</b> "
            f"<span style='color:#57606a'>(Faces alinhadas; deslocamento de {distance_mm:.2f} mm. "
            "Selecione outra face para continuar; Esc encerra)</span>"
        )
        self.scene.plotter.setFocus()

    def _plate_support_for_edge(self, plate, edge_index: int) -> str | None:
        points = np.asarray(plate.contour, dtype=float)
        if edge_index < 0 or edge_index >= len(points):
            return None
        edge = points[[edge_index, (edge_index + 1) % len(points)]]
        for kind, name in plate.supports:
            member = (
                self.model.bars.get(name) if kind == "bar"
                else self.model.rigid_bars.get(name)
            )
            if member is None:
                continue
            start_node = self.model.nodes[member.start_node]
            end_node = self.model.nodes[member.end_node]
            endpoints = np.asarray((
                (start_node.x, start_node.y, start_node.z),
                (end_node.x, end_node.y, end_node.z),
            ), dtype=float)
            direct = max(np.linalg.norm(endpoints[0] - edge[0]),
                         np.linalg.norm(endpoints[1] - edge[1]))
            reverse = max(np.linalg.norm(endpoints[0] - edge[1]),
                          np.linalg.norm(endpoints[1] - edge[0]))
            if min(direct, reverse) <= 1e-7:
                return name
        return None

    def _plate_edge_alignment_values(
        self, plate, edge_index: int, target_point: np.ndarray, target_normal: np.ndarray,
    ) -> tuple[str, float, float]:
        """Solve the stored edge offset and inclination for a picked reference plane."""
        points = np.asarray(plate.contour, dtype=float)
        if edge_index < 0 or edge_index >= len(points):
            raise ValueError("A face selecionada não corresponde a uma aresta da placa.")
        edge = points[[edge_index, (edge_index + 1) % len(points)]]
        edge_name = self._plate_support_for_edge(plate, edge_index)
        if edge_name is None:
            raise ValueError("Não foi encontrada a barra que define essa aresta da placa.")

        centered = points - points[0]
        _u, singular, basis = np.linalg.svd(centered, full_matrices=False)
        if len(singular) < 2 or singular[1] <= 1e-12:
            raise ValueError("Não foi possível calcular o plano da placa.")
        normal = basis[-1]
        if normal[np.argmax(np.abs(normal))] < 0:
            normal = -normal
        tangent = edge[1] - edge[0]
        tangent_length = float(np.linalg.norm(tangent))
        if tangent_length <= 1e-12:
            raise ValueError("A aresta da placa possui comprimento nulo.")
        tangent /= tangent_length
        axis_u = points[1] - points[0]
        axis_u /= max(float(np.linalg.norm(axis_u)), 1e-12)
        axis_v = np.cross(normal, axis_u)
        local = np.column_stack((centered @ axis_u, centered @ axis_v))
        signed_area = 0.5 * float(np.sum(
            local[:, 0] * np.roll(local[:, 1], -1)
            - local[:, 1] * np.roll(local[:, 0], -1)
        ))
        winding = 1.0 if signed_area >= 0 else -1.0
        inward = winding * np.cross(normal, tangent)
        target_normal = target_normal / max(float(np.linalg.norm(target_normal)), 1e-12)
        if abs(float(np.dot(target_normal, tangent))) > 1e-5:
            raise ValueError("A face de referência precisa ser paralela à aresta da placa.")
        if float(np.dot(target_normal, inward)) > 0:
            target_normal = -target_normal
        angle = math.degrees(math.atan2(
            float(np.dot(target_normal, normal)),
            -float(np.dot(target_normal, inward)),
        ))
        limit = self.solid_face_angle_limit_degrees
        if abs(angle) > limit + 1e-9:
            raise ValueError(f"A inclinação excede o limite de {limit:.1f}°.")
        cosine = math.cos(math.radians(angle))
        if abs(cosine) <= 1e-8:
            raise ValueError("A inclinação da face é muito próxima de 90°.")
        base_point = edge[0] + normal * float(plate.positioning_displacement)
        geometric_offset = -float(
            np.dot(target_normal, target_point - base_point)
        ) / cosine
        # The UI convention is positive outward, opposite the inward line offset.
        offset_mm = -geometric_offset * 1000.0
        return edge_name, offset_mm, angle

    def _plate_edge_offset_to_face(
        self, plate, target_point: np.ndarray, target_normal: np.ndarray,
    ) -> tuple[str, float]:
        """Find the nearest supported plate edge parallel to a picked face and solve YZ."""
        points = np.asarray(plate.contour, dtype=float)
        if len(points) < 3:
            raise ValueError("A placa não possui arestas suficientes para alinhamento.")
        centered = points - points[0]
        _u, singular, basis = np.linalg.svd(centered, full_matrices=False)
        if len(singular) < 2 or singular[1] <= 1e-12:
            raise ValueError("Não foi possível calcular o plano da placa.")
        plate_normal = basis[-1]
        if plate_normal[np.argmax(np.abs(plate_normal))] < 0:
            plate_normal = -plate_normal
        axis_u = points[1] - points[0]
        axis_u_length = float(np.linalg.norm(axis_u))
        if axis_u_length <= 1e-12:
            raise ValueError("A placa possui uma aresta de comprimento nulo.")
        axis_u /= axis_u_length
        axis_v = np.cross(plate_normal, axis_u)
        local = np.column_stack((centered @ axis_u, centered @ axis_v))
        signed_area = 0.5 * float(np.sum(
            local[:, 0] * np.roll(local[:, 1], -1)
            - local[:, 1] * np.roll(local[:, 0], -1)
        ))
        winding = 1.0 if signed_area >= 0 else -1.0
        target_normal = np.asarray(target_normal, dtype=float)
        target_length = float(np.linalg.norm(target_normal))
        if target_length <= 1e-12:
            raise ValueError("Não foi possível calcular a normal da face selecionada.")
        target_normal = target_normal / target_length
        target_point = np.asarray(target_point, dtype=float)
        if not np.isfinite(target_point).all() or not np.isfinite(target_normal).all():
            raise ValueError("A face selecionada possui uma geometria inválida.")

        candidates = []
        for edge_index in range(len(points)):
            edge = points[[edge_index, (edge_index + 1) % len(points)]]
            tangent = edge[1] - edge[0]
            edge_length = float(np.linalg.norm(tangent))
            if edge_length <= 1e-12 or abs(float(np.dot(target_normal, tangent / edge_length))) > 1e-5:
                continue
            edge_name = self._plate_support_for_edge(plate, edge_index)
            if edge_name is None:
                continue
            inward = winding * np.cross(plate_normal, tangent / edge_length)
            normal_component = float(np.dot(target_normal, inward))
            if abs(normal_component) <= 1e-8:
                continue
            midpoint = 0.5 * (edge[0] + edge[1])
            base_point = midpoint + plate_normal * float(plate.positioning_displacement)
            signed_distance = float(np.dot(target_normal, base_point - target_point))
            # The mesh applies inward * (-YZ), so solve the target plane using
            # target_normal · (base - target) = YZ * target_normal · inward.
            offset_mm = signed_distance / normal_component * 1000.0
            candidates.append((abs(signed_distance), edge_index, edge_name, offset_mm))
        if not candidates:
            raise ValueError("A face selecionada não é paralela a uma aresta apoiada da placa.")
        _distance, _edge_index, edge_name, offset_mm = min(candidates)
        return edge_name, offset_mm

    def _align_plate_endpoint_to_face(
        self, plate_name: str, target_point: np.ndarray, target_normal: np.ndarray,
    ) -> None:
        plate = self.model.plates.get(plate_name)
        if plate is None:
            return
        try:
            edge_name, offset_mm = self._plate_edge_offset_to_face(
                plate, target_point, target_normal,
            )
            saved = {
                name: (float(offset), float(angle))
                for name, offset, angle in plate.edge_positioning
            }
            old_angle = saved.get(edge_name, (0.0, 0.0))[1]
            saved[edge_name] = (offset_mm, old_angle)
            edge_values = tuple(
                (name, *saved.get(name, (0.0, 0.0)))
                for _kind, name in plate.supports
            )
            self.model_service.update_plate_edge_positioning(plate_name, edge_values)
            self.scene.update_plate_rendering(plate_name)
        except (KeyError, ValueError) as error:
            self.history.append(
                f"> <b>Alinhar extremidade</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self._command_mode = "endpoint_alignment_bar_selection"
        self._endpoint_alignment_source = None
        self.scene.set_endpoint_alignment_target(None)
        self.refresh_selected_property_panel(self.palette.active_group)
        self.history.append(
            "> <b>Alinhar extremidade</b> "
            f"<span style='color:#57606a'>(Aresta {escape(edge_name)} alinhada; "
            f"YZ = {offset_mm:.2f} mm. Selecione outra barra ou placa; Esc encerra)</span>"
        )
        self.scene.plotter.setFocus()

    def _translate_bar_positioning(self, names: tuple[str, ...], translation: np.ndarray) -> None:
        for name in names:
            bar = self.model.bars[name]
            start_node = self.model.nodes[bar.start_node]
            end_node = self.model.nodes[bar.end_node]
            basis = LocalAxesRenderer.basis(start_node, end_node, rotation=bar.rotation)
            base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
            if basis is None or base_basis is None:
                raise ValueError(f"Não foi possível calcular os eixos locais da barra {name}.")
            delta_x = float(np.dot(translation, basis[0]))
            delta_y = float(np.dot(translation, base_basis[1]))
            delta_z = float(np.dot(translation, base_basis[2]))
            face_offsets = list(bar.solid_face_offsets)
            face_offsets[0] -= delta_x
            face_offsets[1] += delta_x
            section_offsets = list(bar.solid_section_offsets)
            section_offsets[0] += delta_y
            section_offsets[1] += delta_z
            self.model_service.update_member_solid_face_offsets(name, tuple(face_offsets))
            self.model_service.update_member_solid_section_offsets(name, tuple(section_offsets))

    def _align_member_endpoint_to_face(self, hit: object) -> None:
        """Match a connected bar end face to the clicked solid face plane."""
        if self._command_mode != "endpoint_alignment_face_selection":
            return
        try:
            target_kind, target_name, target_cell_id, face_point, face_normal = hit
            face_point = np.asarray(face_point, dtype=float)
            face_normal = np.asarray(face_normal, dtype=float)
        except (TypeError, ValueError):
            return
        source = self._endpoint_alignment_source
        if source is None or target_kind not in {"bar", "plate"}:
            return
        source_kind, source_name = source
        if source_kind == "plate":
            if target_kind == "plate" and target_name == source_name:
                self.history.append(
                    "> <b>Alinhar extremidade</b> "
                    "<span style='color:#8c959f'>(Selecione a face de outro elemento)</span>"
                )
                return
            self._align_plate_endpoint_to_face(source_name, face_point, face_normal)
            return
        source_names = self._detailing_group_member_names(source_name)
        if target_kind == "bar" and target_name in source_names:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(Selecione uma face de outra barra conectada)</span>"
            )
            return

        outer_faces = group_endpoint_faces(self.model, source_names)
        outer_nodes = {
            (member_name, self.model.bars[member_name].start_node if endpoint_index == 0
             else self.model.bars[member_name].end_node)
            for member_name, endpoint_index in outer_faces.values()
        }
        if target_kind == "bar":
            target_group_names = self._detailing_group_member_names(target_name)
            target_outer_nodes = {
                (member_name, self.model.bars[member_name].start_node if endpoint_index == 0
                 else self.model.bars[member_name].end_node)
                for member_name, endpoint_index in group_endpoint_faces(
                    self.model, target_group_names,
                ).values()
            }
            target_members = [
                ("bar", name, self.model.bars[name])
                for name in target_group_names if name in self.model.bars
            ]
        else:
            plate = self.model.plates.get(target_name)
            if plate is None:
                return
            if target_cell_id >= 2:
                edge_name = self._plate_support_for_edge(plate, target_cell_id - 2)
                target_supports = tuple(
                    (kind, name) for kind, name in plate.supports if name == edge_name
                ) if edge_name is not None else ()
            else:
                target_supports = plate.supports
            target_members = [
                (kind, name, self.model.bars[name] if kind == "bar"
                 else self.model.rigid_bars[name])
                for kind, name in target_supports
                if name in (self.model.bars if kind == "bar" else self.model.rigid_bars)
            ]
            target_outer_nodes = {
                (name, node_name)
                for _kind, name, member in target_members
                for node_name in (member.start_node, member.end_node)
            }
        candidates = []
        for candidate_name in source_names:
            source_candidate = self.model.bars.get(candidate_name)
            if source_candidate is None:
                continue
            endpoints = (source_candidate.start_node, source_candidate.end_node)
            for source_node in endpoints:
                if (candidate_name, source_node) not in outer_nodes:
                    continue
                for target_bar_kind, target_bar_name, target_bar in target_members:
                    if target_bar_kind == "bar" and target_bar_name in source_names:
                        continue
                    target_endpoints = (target_bar.start_node, target_bar.end_node)
                    shared_nodes = set(endpoints).intersection(target_endpoints)
                    if (
                        source_node in shared_nodes and len(shared_nodes) == 1
                        and (target_bar_name, source_node) in target_outer_nodes
                    ):
                        candidates.append((source_candidate, (source_node, source_node)))
                        continue
                    # A rigid bar connects distinct nodes at the ends of two bars.
                    for rigid in self.model.rigid_bars.values():
                        if (
                            rigid.start_node == source_node and rigid.end_node in target_endpoints
                            and (target_bar_name, rigid.end_node) in target_outer_nodes
                        ):
                            candidates.append((source_candidate, (source_node, rigid.end_node)))
                        elif (
                            rigid.end_node == source_node and rigid.start_node in target_endpoints
                            and (target_bar_name, rigid.start_node) in target_outer_nodes
                        ):
                            candidates.append((source_candidate, (source_node, rigid.start_node)))
        if len(candidates) != 1:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(Selecione uma face de barra ou de uma placa apoiada "
                "em uma barra ligada à extremidade externa do grupo)</span>"
            )
            return
        source, endpoint_pair = candidates[0]
        source_endpoint_node, _target_endpoint_node = endpoint_pair
        endpoint_index = 0 if source_endpoint_node == source.start_node else 1
        start_node = self.model.nodes[source.start_node]
        end_node = self.model.nodes[source.end_node]
        basis = LocalAxesRenderer.basis(start_node, end_node, rotation=source.rotation)
        base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
        if basis is None or base_basis is None:
            return
        start = np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
        end = np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
        length = float(np.linalg.norm(end - start))
        normal_length = float(np.linalg.norm(face_normal))
        if length <= 1e-12 or normal_length <= 1e-12:
            return
        face_normal /= normal_length
        normal_x = float(np.dot(face_normal, basis[0]))
        if abs(normal_x) <= 1e-8:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(Essa face é paralela ao eixo da barra e não pode formar a face da extremidade)</span>"
            )
            return

        # alphaY is rotation about local Y, so it is determined by the normal's
        # local Z component; alphaZ is rotation about local Z and uses local Y.
        # Then solve A/B for the plane's position through the hit.
        if normal_x < 0.0:
            face_normal = -face_normal
            normal_x = -normal_x
        alpha_y = math.degrees(math.atan(float(np.dot(face_normal, basis[2])) / normal_x))
        alpha_z = math.degrees(math.atan(float(np.dot(face_normal, basis[1])) / normal_x))
        limit = self.solid_face_angle_limit_degrees
        if abs(alpha_y) > limit + 1e-9 or abs(alpha_z) > limit + 1e-9:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                f"<span style='color:#8c959f'>(O corte exige inclinações acima do limite de {limit:.1f}°)</span>"
            )
            return

        endpoint = "A" if endpoint_index == 0 else "B"
        endpoint_point = start if endpoint_index == 0 else end
        offset_sign = -1.0 if endpoint_index == 0 else 1.0
        section_translation = (
            base_basis[1] * float(source.solid_section_offsets[0])
            + base_basis[2] * float(source.solid_section_offsets[1])
        )
        offset = float(
            np.dot(face_normal, face_point - endpoint_point - section_translation)
            / (offset_sign * normal_x)
        )
        offsets = list(source.solid_face_offsets)
        offsets[endpoint_index] = offset
        if length + offsets[0] + offsets[1] <= 1e-9:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(O alinhamento resultaria em uma barra sem comprimento)</span>"
            )
            return
        angles = list(source.solid_face_angles)
        angle_index = endpoint_index * 2
        angles[angle_index:angle_index + 2] = alpha_y, alpha_z
        try:
            self.model_service.update_member_solid_face_offsets(source.name, tuple(offsets))
            self.model_service.update_member_solid_face_angles(source.name, tuple(angles))
        except ValueError as error:
            self.history.append(
                f"> <b>Alinhar extremidade</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self._command_mode = "endpoint_alignment_bar_selection"
        self._endpoint_alignment_source = None
        self.scene.set_endpoint_alignment_target(None)
        self.refresh_member_positioning(source.name)
        self.properties.update_positioning_status(source.name)
        offset_mm = offset * 1000.0
        self.history.append(
            "> <b>Alinhar extremidade</b> "
            f"<span style='color:#57606a'>(Extremidade {endpoint} alinhada; "
            f"{endpoint} = {offset_mm:.2f} mm; αY/αZ = {alpha_y:.2f}°/{alpha_z:.2f}°. "
            "Selecione outra barra ou placa para continuar; Esc encerra)</span>"
        )
        self.scene.plotter.setFocus()

    def start_connect_member_ends(self) -> None:
        """Start the two-bar command that makes their connected faces coplanar."""
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._connect_member_ends_first_bar = None
        if not self.scene._solid_members_visible:
            self._apply_mcp_view_change("solid_members_visible", True)
        self.clear_selection()
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.axes_panel.hide()
        self.reference_panel.hide()
        self.scene.set_endpoint_alignment_target(None)
        self._command_mode = "connect_member_ends_selection"
        self.history.append(
            "> <b>Conectar extremidades</b> "
            "<span style='color:#57606a'>(Selecione a primeira barra; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def _connect_member_end_faces(self, first_name: str, second_name: str) -> bool:
        """Create a shared miter plane at the common node of two bars."""
        first = self.model.bars.get(first_name)
        second = self.model.bars.get(second_name)
        if first is None or second is None:
            return False
        shared_nodes = {
            node_name for node_name in (first.start_node, first.end_node)
            if node_name in {second.start_node, second.end_node}
        }
        if len(shared_nodes) != 1:
            self.history.append(
                "> <b>Conectar extremidades</b> "
                "<span style='color:#8c959f'>(As barras devem compartilhar exatamente uma extremidade)</span>"
            )
            return False

        shared_node = next(iter(shared_nodes))
        node = self.model.nodes[shared_node]
        node_point = np.asarray((node.x, node.y, node.z), dtype=float)

        def endpoint_data(member):
            start_node = self.model.nodes[member.start_node]
            end_node = self.model.nodes[member.end_node]
            basis = LocalAxesRenderer.basis(
                start_node, end_node, rotation=member.rotation,
            )
            base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
            if basis is None or base_basis is None:
                return None
            endpoint_index = 0 if shared_node == member.start_node else 1
            # The offset sign follows the rendered face center: A moves along
            # -local-X and B along +local-X. The ray points into the bar.
            offset_sign = -1.0 if endpoint_index == 0 else 1.0
            ray = -offset_sign * basis[0]
            section_translation = (
                base_basis[1] * float(member.solid_section_offsets[0])
                + base_basis[2] * float(member.solid_section_offsets[1])
            )
            length = float(np.linalg.norm(
                np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
                - np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
            ))
            return endpoint_index, offset_sign, basis, section_translation, ray, length

        first_data = endpoint_data(first)
        second_data = endpoint_data(second)
        if first_data is None or second_data is None:
            self.history.append(
                "> <b>Conectar extremidades</b> "
                "<span style='color:#8c959f'>(Não foi possível determinar os eixos locais das barras)</span>"
            )
            return False

        first_ray, second_ray = first_data[4], second_data[4]
        ray_cosine = min(1.0, max(-1.0, float(np.dot(first_ray, second_ray))))
        transverse_sine = float(np.linalg.norm(second_ray - ray_cosine * first_ray))
        profile_midpoints = (0.0, 0.0)
        first_transverse = second_transverse = None
        if transverse_sine > 1e-8:
            first_transverse = (
                second_ray - ray_cosine * first_ray
            ) / transverse_sine
            second_transverse = (
                first_ray - ray_cosine * second_ray
            ) / transverse_sine

            def profile_extent(member, basis, direction):
                try:
                    shape = section_shape(
                        member.section,
                        member.geometry_dict(),
                        arc_steps=24,
                        mirror_z=member.section_mirrored,
                    )
                except (KeyError, TypeError, ValueError):
                    shape = None
                if shape is None or not shape.loops:
                    return None
                points = np.asarray(
                    [point for loop in shape.loops for point in loop], dtype=float,
                )
                world_points = (
                    points[:, 0, None] * basis[1]
                    + points[:, 1, None] * basis[2]
                ) * 1e-3
                projections = world_points @ direction
                minimum, maximum = float(np.min(projections)), float(np.max(projections))
                return max(maximum - minimum, 1e-9), (minimum + maximum) / 2.0

            first_extent = profile_extent(
                first, first_data[2], first_transverse,
            )
            second_extent = profile_extent(
                second, second_data[2], second_transverse,
            )
            if first_extent is None or second_extent is None:
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#8c959f'>(Não foi possível obter as dimensões das seções para calcular o ângulo de conexão)</span>"
                )
                return False
            first_width, first_midpoint = first_extent
            second_width, second_midpoint = second_extent
            # The miter angle follows the projected section depths. This makes
            # the two cut spans equal; equal depths give 45° at a right angle.
            transverse_factor = (
                -second_width / first_width - ray_cosine
            ) / transverse_sine
            plane_normal = first_ray + transverse_factor * first_transverse
            plane_normal /= float(np.linalg.norm(plane_normal))
            profile_midpoints = (first_midpoint, second_midpoint)
        else:
            # Parallel or collinear bars have no unique joint plane from their
            # section heights; keep the cut perpendicular to their axes.
            plane_normal = first_ray.copy()
        limit = self.solid_face_angle_limit_degrees
        face_data = []
        for member, data, transverse, midpoint in (
            (first, first_data, first_transverse if transverse_sine > 1e-8 else None, profile_midpoints[0]),
            (second, second_data, second_transverse if transverse_sine > 1e-8 else None, profile_midpoints[1]),
        ):
            endpoint_index, offset_sign, basis, section_translation, _ray, length = data
            normal_x = float(np.dot(plane_normal, basis[0]))
            if abs(normal_x) <= 1e-8:
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#8c959f'>(O ângulo entre as barras exige um corte paralelo ao eixo de uma delas)</span>"
                )
                return False
            alpha_y = math.degrees(
                math.atan(float(np.dot(plane_normal, basis[2])) / normal_x)
            )
            alpha_z = math.degrees(
                math.atan(float(np.dot(plane_normal, basis[1])) / normal_x)
            )
            if abs(alpha_y) > limit + 1e-9 or abs(alpha_z) > limit + 1e-9:
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    f"<span style='color:#8c959f'>(O corte exige inclinações acima do limite de {limit:.1f}°)</span>"
                )
                return False

            old_offset = float(member.solid_face_offsets[endpoint_index])
            profile_center_offset = (
                np.zeros(3, dtype=float) if transverse is None
                else transverse * midpoint
            )
            current_plane_position = (
                float(np.dot(plane_normal, section_translation + profile_center_offset))
                + offset_sign * normal_x * old_offset
            )
            face_data.append((
                member, endpoint_index, offset_sign, normal_x, data[4],
                section_translation, length, alpha_y, alpha_z,
                section_translation + profile_center_offset, current_plane_position,
            ))

        if transverse_sine > 1e-8:
            joint_normal = np.cross(first_ray, second_ray)
            joint_normal /= float(np.linalg.norm(joint_normal))
            plane_tangent = np.cross(joint_normal, plane_normal)
            plane_tangent /= float(np.linalg.norm(plane_tangent))

            def cut_center_terms(data):
                (
                    _member, _endpoint_index, _offset_sign, _normal_x, ray,
                    _section_translation, _length, _alpha_y, _alpha_z,
                    center_offset, _current_plane_position,
                ) = data
                normal_ray = float(np.dot(plane_normal, ray))
                tangent_ray = float(np.dot(plane_tangent, ray))
                ratio = tangent_ray / normal_ray
                base = (
                    float(np.dot(plane_tangent, center_offset))
                    - ratio * float(np.dot(plane_normal, center_offset))
                )
                return base, ratio

            first_base, first_ratio = cut_center_terms(face_data[0])
            second_base, second_ratio = cut_center_terms(face_data[1])
            coefficient = first_ratio - second_ratio
            if abs(coefficient) > 1e-10:
                # Set the cut so the centers of the two projected profile
                # extents meet along the common face, including Y/Z offsets.
                plane_position = (second_base - first_base) / coefficient
            else:
                plane_position = sum(item[8] for item in face_data) / len(face_data)
        else:
            # Collinear bars use the midpoint of their current end planes.
            plane_position = sum(item[8] for item in face_data) / len(face_data)

        updates = []
        for (
            member, endpoint_index, offset_sign, normal_x, _ray, section_translation,
            length, alpha_y, alpha_z, _center_offset, _current_plane_position,
        ) in face_data:
            offset = (
                plane_position - float(np.dot(plane_normal, section_translation))
            ) / (offset_sign * normal_x)
            offsets = list(member.solid_face_offsets)
            offsets[endpoint_index] = offset
            if length + offsets[0] + offsets[1] <= 1e-9:
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    f"<span style='color:#8c959f'>(O corte deixaria a barra {escape(member.name)} sem comprimento)</span>"
                )
                return False
            angles = list(member.solid_face_angles)
            angle_index = endpoint_index * 2
            angles[angle_index:angle_index + 2] = alpha_y, alpha_z
            updates.append((member.name, endpoint_index, tuple(offsets), tuple(angles), alpha_y, alpha_z))

        try:
            for name, _index, offsets, angles, _alpha_y, _alpha_z in updates:
                self.model_service.update_member_solid_face_offsets(name, offsets)
                self.model_service.update_member_solid_face_angles(name, angles)
        except ValueError as error:
            self.history.append(
                f"> <b>Conectar extremidades</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return False

        self._command_mode = "connect_member_ends_selection"
        self._connect_member_ends_first_bar = None
        self.clear_selection()
        for name, endpoint_index, _offsets, _angles, _alpha_y, _alpha_z in updates:
            self.refresh_member_positioning(name)
            self.properties.update_positioning_status(name)
        first_update, second_update = updates
        self.history.append(
            "> <b>Conectar extremidades</b> "
            f"<span style='color:#57606a'>(Faces {('A', 'B')[first_update[1]]} e "
            f"{('A', 'B')[second_update[1]]} ajustadas para compartilhar o corte; "
            f"αY/αZ = {first_update[4]:.2f}°/{first_update[5]:.2f}° e "
            f"{second_update[4]:.2f}°/{second_update[5]:.2f}°. Selecione outras barras para continuar; Esc encerra)</span>"
        )
        self.scene.plotter.setFocus()
        return True

    def _start_detail_plane_placement(self) -> None:
        """Collect three 3D points to define a custom detailing plane."""
        self._detail_plane_points = []
        self._command_mode = "detail_plane_placement"
        self.scene.set_detail_plane_point_mode(True)
        self.history.append(
            "> <b>Adicionar plano</b> "
            "<span style='color:#57606a'>(Clique em 3 pontos não colineares no modelo; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def _handle_detail_plane_placement_point(self, point: object) -> None:
        if self._command_mode != "detail_plane_placement":
            return
        coordinates = np.asarray(tuple(float(value) for value in point), dtype=float)
        if not hasattr(self, "_detail_plane_points"):
            self._detail_plane_points = []
        if self._detail_plane_points:
            if float(np.linalg.norm(coordinates - self._detail_plane_points[-1])) <= 1e-6:
                self.history.append(
                    "> <b>Adicionar plano</b> "
                    "<span style='color:#8c959f'>(Escolha pontos diferentes)</span>"
                )
                return
        self._detail_plane_points.append(coordinates)
        if len(self._detail_plane_points) < 3:
            self.history.append(
                "> <b>Adicionar plano</b> "
                f"<span style='color:#57606a'>(Ponto {len(self._detail_plane_points)} de 3 selecionado; "
                "clique no próximo)</span>"
            )
            return

        first, second, third = self._detail_plane_points
        first_direction = second - first
        second_direction = third - first
        cross = np.cross(first_direction, second_direction)
        scale = float(np.linalg.norm(first_direction) * np.linalg.norm(second_direction))
        if scale <= 1e-12 or float(np.linalg.norm(cross)) <= scale * 1e-6:
            self._detail_plane_points.pop()
            self.history.append(
                "> <b>Adicionar plano</b> "
                "<span style='color:#8c959f'>(Os três pontos ficaram alinhados; escolha outro terceiro ponto)</span>"
            )
            return

        model_key = id(self.model)
        custom_planes = getattr(self, "_detailing_custom_planes", None)
        if custom_planes is None:
            custom_planes = self._detailing_custom_planes = {}
        records = custom_planes.setdefault(model_key, [])
        record_id = uuid.uuid4().hex
        record = {
            "id": record_id,
            "name": f"Plano personalizado {len(records) + 1}",
            "points": tuple(tuple(float(value) for value in coordinates) for coordinates in self._detail_plane_points),
        }
        records.append(record)
        self._detailing_preferred_view_key = (model_key, f"custom:{record_id}")
        self._detail_plane_points = []
        self._command_mode = None
        self.scene.set_detail_plane_point_mode(False)
        self.history.append(
            f"> <b>Adicionar plano</b> <span style='color:#57606a'>({record['name']} criado)</span>"
        )
        self._store_detailing_state()
        QTimer.singleShot(0, self._finish_detail_plane_placement)

    def _finish_detail_plane_placement(self) -> None:
        dialog = self._detailing_views_dialog
        self._detailing_views_dialog = None
        if dialog is not None:
            dialog.deleteLater()
        self.refresh_scene()
        self._restore_project_mode_after_detail_plane()
        QTimer.singleShot(0, self.open_detailing_views)

    def _restore_project_mode_after_detail_plane(self) -> None:
        if not self._detail_plane_return_to_project:
            return
        self._detail_plane_return_to_project = False
        if not self._detailing_project_mode:
            self.detailing_mode_palette._buttons[1].click()

    def open_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()

    @property
    def mcp_enabled(self) -> bool:
        """Indica se o servidor MCP foi ativado nesta execução do OpenSA."""
        return self._mcp_enabled

    @property
    def mcp_endpoint(self) -> str:
        return self._mcp_server.endpoint

    def set_mcp_enabled(self, enabled: bool) -> None:
        """Ativa ou desativa o servidor MCP a partir das configurações."""
        enabled = bool(enabled)
        if enabled == self._mcp_enabled:
            return
        if enabled:
            try:
                self._mcp_integration.ensure_installed()
                self._mcp_dispatcher.resume()
                self._mcp_server.start()
            except (OSError, RuntimeError) as error:
                self._mcp_dispatcher.suspend()
                self._mcp_enabled = False
                raise RuntimeError(f"Não foi possível ativar o servidor MCP: {error}") from error
            self._mcp_enabled = True
            return
        self._mcp_dispatcher.suspend()
        self._mcp_server.stop()
        self._mcp_enabled = False

    def mcp_status(self) -> dict[str, str]:
        """Retorna o estado que deve ser apresentado na página MCP."""
        if not self._mcp_enabled:
            return {
                "state": "disabled",
                "text": "Servidor MCP desativado",
                "detail": "Ative esta opção para permitir que um cliente MCP acesse o modelo aberto.",
            }
        if self._mcp_server.last_error:
            return {
                "state": "error",
                "text": "Não foi possível iniciar o servidor MCP",
                "detail": self._mcp_server.last_error,
            }
        if not self._mcp_server.is_running:
            return {
                "state": "starting",
                "text": "Iniciando servidor MCP…",
                "detail": "O OpenSA está preparando o endpoint local.",
            }
        if not self._mcp_server.is_listening():
            return {
                "state": "error",
                "text": "O endpoint MCP não está acessível",
                "detail": self._mcp_server.endpoint,
            }
        if self._mcp_integration.is_installed():
            return {
                "state": "ready",
                "text": "Servidor MCP acessível",
                "detail": (
                    "ChatGPT Desktop: plugin registrado. Reinicie o cliente e selecione OpenSA em um chat Work.\n"
                    f"Endpoint local: {self._mcp_server.endpoint}\n"
                    "Claude Code: use o .mcp.json na raiz do projeto.\n"
                    "Claude Desktop Chat: configure o adaptador local mcp-remote. Consulte docs/claude-mcp.md."
                ),
            }
        return {
            "state": "ready",
            "text": "Servidor MCP acessível",
            "detail": (
                "ChatGPT Desktop: registro não confirmado.\n"
                f"Endpoint local: {self._mcp_server.endpoint}\n"
                "Claude Code: use o .mcp.json na raiz do projeto.\n"
                "Claude Desktop Chat: configure o adaptador local mcp-remote. Consulte docs/claude-mcp.md."
            ),
        }

    @property
    def member_direction_normalization_enabled(self) -> bool:
        return self._member_direction_normalization_enabled

    def set_member_direction_normalization_enabled(self, enabled: bool) -> None:
        """Toggle canonical member orientation and synchronize the geometry tool."""
        enabled = bool(enabled)
        self._member_direction_normalization_enabled = enabled
        self.top_icon_palette.set_member_direction_normalization_enabled(enabled)
        if not enabled:
            return
        changed = self.normalize_member_directions_if_enabled()
        if changed:
            self.refresh_selected_property_panel(self.palette.active_group)
            self.refresh_scene()

    @property
    def member_intermediate_snap_split_mode(self) -> str:
        return self._member_intermediate_snap_split_mode

    @property
    def plate_closure_mode(self) -> str:
        return self._plate_closure_mode

    def set_plate_closure_mode(self, mode: str) -> None:
        if mode not in {"perguntar", "automatico"}:
            raise ValueError("Opção inválida para fechamento da placa.")
        self._plate_closure_mode = mode
        self._program_settings.setValue("plates/closure", mode)
        self._program_settings.sync()

    @property
    def face_intersection_edges_enabled(self) -> bool:
        return self._face_intersection_edges_enabled

    def set_face_intersection_edges_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._face_intersection_edges_enabled:
            return
        self._face_intersection_edges_enabled = enabled
        self._program_settings.setValue("video/showFaceIntersectionEdges", enabled)
        self._program_settings.sync()
        self.scene.set_face_intersection_edges_enabled(enabled)

    @property
    def plate_result_display_mode(self) -> str:
        return self._plate_result_display_mode

    def set_plate_result_display_mode(self, mode: str) -> None:
        if not is_plate_result_display_mode(mode):
            raise ValueError("Opção inválida para a visualização dos resultados das placas.")
        if mode == self._plate_result_display_mode:
            return
        self._plate_result_display_mode = mode
        self._program_settings.setValue("plates/resultDisplayMode", mode)
        self._program_settings.sync()
        self.scene.set_plate_result_display_mode(mode)

    @property
    def minimum_bar_restraint_angle_degrees(self) -> float:
        return self._minimum_bar_restraint_angle_degrees

    @property
    def solid_face_angle_limit_degrees(self) -> float:
        return self._solid_face_angle_limit_degrees

    def _read_solid_face_angle_limit(self) -> float:
        value = self._program_settings.value("members/solidFaceAngleLimitDegrees", 75.0)
        try:
            angle = float(value)
        except (TypeError, ValueError):
            angle = 75.0
        return round(min(89.9, max(0.0, angle)), 1)

    def set_solid_face_angle_limit_degrees(self, angle: float) -> None:
        angle = round(min(89.9, max(0.0, float(angle))), 1)
        if angle == self._solid_face_angle_limit_degrees:
            return
        self._solid_face_angle_limit_degrees = angle
        self._program_settings.setValue("members/solidFaceAngleLimitDegrees", angle)
        self._program_settings.sync()
        for name, member in tuple(self.model.bars.items()):
            current = member.solid_face_angles
            if len(current) != 4:
                current = (0.0, 0.0, 0.0, 0.0)
            limited = tuple(min(angle, max(-angle, float(value))) for value in current)
            if limited != tuple(current):
                self.model_service.update_member_solid_face_angles(name, limited)
                self.refresh_member_positioning(name)
        panel = getattr(self, "displacement_panel", None)
        if panel is not None:
            panel.set_solid_face_angle_limit(angle)

    def _read_minimum_bar_restraint_angle(self) -> float:
        value = self._program_settings.value("members/minimumBraceRestraintAngleDegrees", 30.0)
        try:
            angle = float(value)
        except (TypeError, ValueError):
            angle = 30.0
        return min(90.0, max(1.0, angle))

    def set_minimum_bar_restraint_angle_degrees(self, angle: float) -> None:
        angle = min(90.0, max(1.0, float(angle)))
        if angle == self._minimum_bar_restraint_angle_degrees:
            return
        self._minimum_bar_restraint_angle_degrees = angle
        self.model.minimum_bar_restraint_angle_degrees = angle
        self.model._restraint_lengths_cache = None
        self._program_settings.setValue("members/minimumBraceRestraintAngleDegrees", angle)
        self._program_settings.sync()
        if self.model.verification_results:
            self.model.verification_results.clear()
            self.refresh_scene()
            self.refresh_selected_property_panel(self.palette.active_group)
            self.verification_panel.status.setText(
                "Ângulo de travamento alterado. Execute a verificação novamente."
            )
            self.verification_panel.summary.clear()

    def set_member_intermediate_snap_split_mode(self, mode: str) -> None:
        if mode not in {"sim", "perguntar", "nao"}:
            raise ValueError("Opção inválida para segmentação da barra.")
        self._member_intermediate_snap_split_mode = mode
        self._program_settings.setValue("members/intermediateSnapSplit", mode)
        self._program_settings.remove("members/perpendicularSplit")
        self._program_settings.sync()

    def normalize_member_directions_if_enabled(self) -> tuple[str, ...]:
        if not self._member_direction_normalization_enabled:
            return ()
        return self.model_service.normalize_member_directions()

    def open_action_groups(self) -> None:
        dialog = ActionGroupDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
        self.refresh_action_palette()

    def open_combinations(self) -> None:
        dialog = CombinationsDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
        self.refresh_analysis_palette()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_frame"):
            self.window_frame.update_state()
            maximized = self.isMaximized()
            self.title_bar.set_maximized(maximized)

    def _make_shortcuts(self) -> None:
        actions = (
            ("Novo modelo", QKeySequence.StandardKey.New, self.new_model),
            ("Abrir modelo", QKeySequence.StandardKey.Open, self.open_model),
            ("Importar modelo", "Ctrl+I", self.import_model),
            ("Salvar modelo", QKeySequence.StandardKey.Save, self.save_model),
            ("Excluir elemento selecionado", "Delete", self.delete_selected),
            ("Cancelar lançamento", "Escape", self.cancel_member_placement),
            ("Vista isométrica", "0", self.scene.view_isometric),
            ("Enquadrar estrutura", "F", self.scene.reset_camera),
        )
        for label, shortcut, callback in actions:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            if label == "Cancelar lançamento":
                action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                action.setAutoRepeat(False)
                self._cancel_placement_action = action
            action.triggered.connect(callback)
            self.addAction(action)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "member_placement_editor"):
            self.member_placement_editor.reposition()
        if hasattr(self, "palette"):
            self.palette.reposition()
        if hasattr(self, "top_icon_palette"):
            self.top_icon_palette.reposition()
            self.verification_top_palette.reposition()
        if hasattr(self, "member_property_copy_panel") and self.member_property_copy_panel.isVisible():
            self.member_property_copy_panel.reposition()
        if hasattr(self, "action_top_palette"):
            self.action_top_palette.reposition()
        if hasattr(self, "analysis_top_palette"):
            self.analysis_top_palette.reposition()
        if hasattr(self, "detailing_top_palette"):
            self.detailing_top_palette.reposition()
        if hasattr(self, "detailing_mode_palette"):
            self.detailing_mode_palette.reposition()
        if hasattr(self, "project_sheets_palette") and self.project_sheets_palette.isVisible():
            self.project_sheets_palette.reposition()
        if hasattr(self, "project_sheet_view_panel") and self.project_sheet_view_panel.isVisible():
            self.project_sheet_view_panel.reposition()
        if (
            hasattr(self, "project_sheet_identification_panel")
            and self.project_sheet_identification_panel.isVisible()
        ):
            self.project_sheet_identification_panel.reposition()
        if hasattr(self, "navigation_button"):
            self._reposition_navigation_button()
        if hasattr(self, "properties"):
            self.properties.reposition()
            if self.properties._color_palette.isVisible():
                self.properties.reposition_color_palette()
        if hasattr(self, "axes_panel") and self.axes_panel.isVisible():
            self.axes_panel.reposition()
        if hasattr(self, "reference_panel") and self.reference_panel.isVisible():
            self.reference_panel.reposition()
        if hasattr(self, "split_member_dialog") and self.split_member_dialog.isVisible():
            self.split_member_dialog.reposition()
        if hasattr(self, "command_bar"):
            self.command_bar.reposition()
        if hasattr(self, "history"):
            self.history.reposition()
        if hasattr(self, "section_panel") and self.section_panel.isVisible():
            self.section_panel.reposition()
        if hasattr(self, "subtractions_panel") and self.subtractions_panel.isVisible():
            self.subtractions_panel.reposition()
        if hasattr(self, "displacement_panel") and self.displacement_panel.isVisible():
            self.displacement_panel.reposition()
        if hasattr(self, "calculation_properties_panel") and self.calculation_properties_panel.isVisible():
            self.calculation_properties_panel.reposition()
        if hasattr(self, "processing_panel") and self.processing_panel.isVisible():
            self.processing_panel.reposition()
        if hasattr(self, "verification_panel") and self.verification_panel.isVisible():
            self.verification_panel.reposition()

    def toggle_section_panel(self, section: str = "", button=None) -> None:
        if section in ("", "Indefinido"):
            if button is not None: button.setChecked(False)
            return
        active_panel = self.section_panel
        if active_panel.isVisible() and getattr(active_panel, "_section_family", "") == section:
            active_panel.hide()
            if button is not None: button.setChecked(False)
        else:
            self.show_section_panel(section, button)

    def toggle_displacement_panel(self, button=None) -> None:
        """Show or hide the selected member's positioning editor."""
        if self.displacement_panel.isVisible():
            self.close_displacement_panel(button)
            return
        self.properties.close_color_palette()
        self.close_calculation_properties_panel(self.properties._calculation_properties_button)
        self.close_section_panel(self.properties._section_settings_button)
        selected = self.selected
        if selected is not None and selected[0] == "plate":
            self.displacement_panel.configure_for_plate(selected[1])
        else:
            member_name = selected[1] if selected and selected[0] == "bar" else ""
            self.displacement_panel.configure_for(member_name)
        self.displacement_panel.reposition()
        self.displacement_panel.show()
        self.displacement_panel.raise_()
        if button is not None:
            button.setChecked(True)

    def _reposition_navigation_button(self) -> None:
        margin = 0 if self.isMaximized() else WindowFrame.MARGIN
        self.navigation_button.move(
            margin + 24,
            self.height() - margin - self.navigation_button.height() - 24,
        )
        self.navigation_button.raise_()
        if hasattr(self, "sloped_plane_button"):
            self.sloped_plane_button.move(
                self.navigation_button.x(),
                self.navigation_button.y() - self.sloped_plane_button.height() - 8,
            )
            self.sloped_plane_button.raise_()
        if hasattr(self, "sloped_plane_right_button"):
            self.sloped_plane_right_button.move(
                self.navigation_button.x() + self.navigation_button.width() + 8,
                self.navigation_button.y(),
            )
            self.sloped_plane_right_button.raise_()
        if hasattr(self, "plane_change_button"):
            self.plane_change_button.move(
                self.sloped_plane_right_button.x() + self.sloped_plane_right_button.width() + 80,
                self.navigation_button.y(),
            )
            self.plane_change_button.raise_()
        if hasattr(self, "previous_plane_button"):
            self.previous_plane_button.move(
                self.plane_change_button.x() - self.previous_plane_button.width() - 8,
                self.navigation_button.y(),
            )
            self.previous_plane_button.raise_()
        if hasattr(self, "next_plane_button"):
            self.next_plane_button.move(
                self.plane_change_button.x() + self.plane_change_button.width() + 8,
                self.navigation_button.y(),
            )
            self.next_plane_button.raise_()

    def _cycle_navigation_plane(self) -> None:
        self._navigation_plane_index = (self._navigation_plane_index + 1) % len(self._navigation_plane_icons)
        self.scene.set_reference_plane_mode(self._navigation_plane_modes[self._navigation_plane_index])
        self._update_navigation_button_icon()

    def _update_navigation_button_icon(self) -> None:
        icon = self._navigation_plane_icons[self._navigation_plane_index]
        self.plane_change_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon))
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        scene = getattr(self, "scene", None)
        command_bar = getattr(self, "command_bar", None)
        if (command_bar is not None and watched is command_bar.input
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self._command_mode == "plate_selection"
                and not command_bar.input.text().strip()):
            self._confirm_command_selection()
            return True
        if (
            scene is not None
            and command_bar is not None
            and watched in (scene.plotter, command_bar.input)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self._command_mode == "project_sheet_identification"
        ):
            self._finish_project_view_identification()
            return True
        if (
            scene is not None
            and command_bar is not None
            and watched in (scene.plotter, command_bar.input)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.view_stack.currentWidget() is self.scene
            and self._command_mode is None
            and self.command_session.pending is None
        ):
            if watched is command_bar.input and command_bar.input.text().strip():
                return super().eventFilter(watched, event)
            if self._last_command_callback is not None:
                self._last_command_callback()
                return True

        navigation_tooltips = {
            getattr(self, "navigation_button", None): "Enquadrar modelo",
            getattr(self, "sloped_plane_button", None): "Rotacionar +90°",
            getattr(self, "sloped_plane_right_button", None): "Rotacionar -90°",
            getattr(self, "previous_plane_button", None): "Plano anterior",
            getattr(self, "plane_change_button", None): "Alterar plano",
            getattr(self, "next_plane_button", None): "Próximo plano",
        }
        if watched in navigation_tooltips:
            if event.type() == QEvent.Type.Enter:
                if watched in (
                    self.previous_plane_button,
                    self.plane_change_button,
                    self.next_plane_button,
                ):
                    self._navigation_tooltip.schedule_above(
                        self.plane_change_button,
                        navigation_tooltips[watched],
                    )
                else:
                    self._navigation_tooltip.schedule_upper_right(
                        self.navigation_button,
                        navigation_tooltips[watched],
                    )
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._navigation_tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def close_section_panel(self, button=None) -> None:
        """Hide the geometry editor and restore its trigger button state."""
        self.section_panel.hide()
        if button is not None:
            button.setChecked(False)

    def close_displacement_panel(self, button=None) -> None:
        """Hide the displacement editor and restore its trigger state."""
        self.displacement_panel.hide()
        if button is not None:
            button.setChecked(False)

    def close_calculation_properties_panel(self, button=None) -> None:
        self.calculation_properties_panel.hide()
        if button is not None:
            button.setChecked(False)

    def close_subtractions_panel(self, button=None) -> None:
        self.subtractions_panel.hide()
        if self._detail_subtraction_visible_refs:
            self._detail_subtraction_visible_refs.clear()
            self.scene.set_detail_subtraction_previews(())
        trigger = button if button is not None else self.properties._subtractions_button
        if trigger is not None:
            trigger.setChecked(False)

    def toggle_subtractions_panel(self, kind: str, name: str, button=None) -> None:
        panel = self.subtractions_panel
        if panel.isVisible() and panel._target == (kind, name):
            self.close_subtractions_panel(button)
            return
        self.properties.close_color_palette()
        self.close_displacement_panel(self.properties._displacement_settings_button)
        self.close_section_panel(self.properties._section_settings_button)
        self.close_calculation_properties_panel(self.properties._calculation_properties_button)
        if panel.isVisible():
            self.close_subtractions_panel()
        panel.configure_for(kind, name)
        panel.reposition()
        panel.show()
        panel.raise_()
        if button is not None:
            button.setChecked(True)

    def set_detail_subtraction_preview(
        self, target: tuple[str, str], cutter: tuple[str, str], visible: bool,
    ) -> None:
        key = (*target, *cutter)
        if visible:
            self._detail_subtraction_visible_refs.add(key)
        else:
            self._detail_subtraction_visible_refs.discard(key)
        self.scene.set_detail_subtraction_previews(self._detail_subtraction_visible_refs)

    def remove_detail_subtraction(
        self, target: tuple[str, str], cutter: tuple[str, str],
    ) -> None:
        target_kind, target_name = target
        elements = self.model.bars if target_kind == "bar" else self.model.plates
        element = elements.get(target_name)
        if element is None or cutter not in element.detail_subtractions:
            return
        was_open = self.subtractions_panel.isVisible()
        self._detail_subtraction_visible_refs.discard((*target, *cutter))
        self.scene.set_detail_subtraction_previews(self._detail_subtraction_visible_refs)
        self.model.update_detail_subtractions(
            target_kind, target_name,
            tuple(reference for reference in element.detail_subtractions if reference != cutter),
        )
        self.refresh_scene()
        self.properties.update_subtractions_status(*target)
        if was_open:
            self.subtractions_panel.configure_for(*target)
            self.subtractions_panel.reposition()
            self.subtractions_panel.show()
            self.subtractions_panel.raise_()
            if self.properties._subtractions_button is not None:
                self.properties._subtractions_button.setChecked(True)
            self.scene.set_detail_subtraction_previews(self._detail_subtraction_visible_refs)

    def toggle_calculation_properties_panel(self, button=None) -> None:
        if self.calculation_properties_panel.isVisible():
            self.close_calculation_properties_panel(button)
            return
        names = self.properties._selected_names("bar")
        if not names:
            if button is not None:
                button.setChecked(False)
            return
        self.properties.close_color_palette()
        self.close_section_panel(self.properties._section_settings_button)
        self.close_displacement_panel(self.properties._displacement_settings_button)
        self.calculation_properties_panel.configure_for(names)
        self.calculation_properties_panel.reposition()
        self.calculation_properties_panel.show()
        self.calculation_properties_panel.raise_()
        if button is not None:
            button.setChecked(True)

    def show_section_panel(self, section: str, button=None) -> None:
        """Show the geometry panel that corresponds to a section family."""
        panel = self.section_panels.get(section)
        if panel is None:
            if button is not None:
                button.setChecked(False)
            return
        self.properties.close_color_palette()
        self.close_calculation_properties_panel(self.properties._calculation_properties_button)
        self.close_displacement_panel(self.properties._displacement_settings_button)
        for candidate in self.section_panels.values():
            candidate.hide()
        self.section_panel = panel
        panel.configure_for(
            self.selected[1] if self.selected and self.selected[0] == "bar" else "",
            section,
        )
        panel.reposition()
        panel.show()
        panel.raise_()
        if button is not None:
            button.setChecked(True)

    def toggle_axes_panel(self) -> None:
        if self._command_mode in {"member_placement", "reference_axis_placement"}:
            self.cancel_member_placement()
        self.reference_panel.hide()
        if self.axes_panel.isVisible():
            self.axes_panel.hide()
            return
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.axes_panel.reposition()
        self.axes_panel.show()
        self.axes_panel.raise_()

    def start_reference_axis_placement(self, direction: str) -> None:
        """Capture consecutive 3D points as axes in the selected direction list."""
        if direction not in {"X", "Y", "Z"}:
            return
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self._member_placement_start = None
        self._reference_axis_placement_direction = direction
        self._command_mode = "reference_axis_placement"
        self.scene.set_node_placement_mode(True)
        self.history.append(
            f"> <b>Definir eixos {direction}</b> "
            "<span style='color:#57606a'>(Clique no modelo 3D para definir o próximo eixo; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def toggle_reference_panel(self) -> None:
        if self._command_mode in {"member_placement", "reference_axis_placement"}:
            self.cancel_member_placement()
        if self.reference_panel.isVisible():
            self.reference_panel.hide()
            return
        self.axes_panel.hide()
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.reference_panel.reposition()
        self.reference_panel.show()
        self.reference_panel.raise_()

    def import_reference(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "Importar referência", "",
            "Desenhos CAD (*.dxf *.DXF *.dwg *.DWG);;Desenhos DXF (*.dxf *.DXF);;Desenhos DWG (*.dwg *.DWG)",
        )
        if not filename:
            return
        dialog = ReferenceImportDialog(self, filename)
        dialog.exec()
        if dialog.error:
            QMessageBox.warning(self, "Não foi possível importar a referência", dialog.error)
            dialog.deleteLater()
            return
        result = dialog.result_data
        dialog.deleteLater()
        if result is None:
            return
        with self._model_access_lock:
            self.model.add_reference(result.reference)
            self.scene.refresh_drawing_references(self.model, fit_camera=True)
        if not self.reference_panel.isVisible():
            self.toggle_reference_panel()
        self.reference_panel.reload(result.reference.id)
        if result.warnings:
            QMessageBox.information(self, "Referência importada com avisos", "\n\n".join(result.warnings))

    def _remember_last_command(self, callback) -> None:
        """Keep the most recently started graphical command for Enter to repeat."""
        self.member_placement_editor.hide()
        self._last_command_callback = callback

    def start_member_placement(self) -> None:
        """Start the graphical member-placement flow from the geometry palette."""
        self._remember_last_command(self.start_member_placement)
        self.command_session.cancel()
        self._member_placement_start = None
        self._member_placement_start_snap_member_name = None
        self._member_placement_start_snap_target = None
        self._command_mode = "member_placement"
        self.clear_selection()
        self.member_placement_editor.show()
        self.scene.set_member_placement_mode(True, point_mode=self.member_placement_editor.point_mode)
        self._show_member_placement_prompt()
        self.scene.plotter.setFocus()

    def _member_point_mode_changed(self, mode: str) -> None:
        """Change how the next endpoint is captured, preserving a defined start."""
        if self._command_mode != "member_placement" or mode == self.scene._member_point_mode:
            return
        self.scene._cancel_coordinate_edit(update=False)
        self.scene.set_member_placement_mode(True, point_mode=mode)
        self._show_member_placement_prompt()
        self.scene.plotter.setFocus()

    def _member_midpoint_pending(self) -> None:
        if self._command_mode == "member_placement":
            self._show_member_placement_prompt(second_point=True)

    def _show_member_placement_prompt(self, *, second_point: bool = False) -> None:
        endpoint = "inicial" if self._member_placement_start is None else "final"
        if self.member_placement_editor.point_mode == "midpoint":
            point = "segundo" if second_point else "primeiro"
            message = f"Clique no {point} ponto para definir a extremidade {endpoint} pelo ponto médio"
        else:
            message = f"Clique na posição {endpoint} da barra"
        self.history.append(
            f"> <b>Adicionar barra</b> <span style='color:#57606a'>({message})</span>"
        )

    def start_measurement(self) -> None:
        """Start a transient two-point distance measurement in the viewport."""
        self._remember_last_command(self.start_measurement)
        self.command_session.cancel()
        self._member_placement_start = None
        self._command_mode = "measurement"
        self.scene.set_measurement_mode(True)
        self.history.append(
            "> <b>Medir</b> "
            "<span style='color:#57606a'>(Clique no ponto inicial da medição)</span>"
        )
        self.scene.plotter.setFocus()

    def start_node_placement(self) -> None:
        """Start the single-click graphical node-placement flow."""
        self._remember_last_command(self.start_node_placement)
        self.command_session.cancel()
        self._member_placement_start = None
        self._command_mode = "node_placement"
        self.scene.set_node_placement_mode(True)
        self.history.append(
            "> <b>Adicionar nó</b> <span style='color:#57606a'>(Clique na posição do nó)</span>"
        )
        self.scene.plotter.setFocus()

    def start_rigid_bar_placement(self) -> None:
        """Start the graphical two-click rigid-bar placement flow."""
        self._remember_last_command(self.start_rigid_bar_placement)
        self.command_session.cancel()
        self._member_placement_start = None
        self._member_placement_start_snap_member_name = None
        self._member_placement_start_snap_target = None
        self._command_mode = "rigid_bar_placement"
        self.scene.set_member_placement_mode(True)
        self.history.append(
            "> <b>Adicionar barra rígida</b> "
            "<span style='color:#57606a'>(Clique na posição inicial da barra rígida)</span>"
        )
        self.scene.plotter.setFocus()

    def start_load_command(self) -> None:
        """Open the graphical action launcher instead of the text command flow."""
        self._remember_last_command(self.start_load_command)
        load_case = self.selected_action_name or ""
        if not load_case:
            self.show_error("Selecione uma ação ativa antes de lançar um carregamento.")
            return
        if self.action_service.has_selfweight(load_case):
            self.show_error("A ação atual está restrita apenas a cargas de peso próprio.")
            return
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self.command_session.cancel()
        self._command_mode = None
        self._pending_action_launch = None
        dialog = ActionDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._pending_action_launch = dialog.launch_data()
        target_label = "nós" if self._pending_action_launch[0] == "node" else "barras"
        self._command_mode = "action_selection"
        self.history.append(
            "> <b>Adicionar ação</b> "
            f"<span style='color:#57606a'>(Selecione {target_label}; use Ctrl e ENTER para multiseleção; Esc para encerrar)</span>"
        )
        targets = tuple(target for target in self.selected_elements if target[0] == self._pending_action_launch[0])
        self.clear_selection()
        if targets:
            self.scene.set_selection_highlight(targets)
            self._selection_changed(targets)
            self._confirm_command_selection()
        self.scene.plotter.setFocus()

    def start_selfweight_command(self) -> None:
        """Open the material picker and apply selfweight to the active action."""
        self.command_session.cancel()
        self._command_mode = None
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        load_case = self.selected_action_name or ""

        # Keep the command's existing toggle behavior: clicking while the
        # active action already contains selfweight removes those loads.
        if self.action_service.has_selfweight(load_case):
            self.action_service.remove_selfweight(load_case)
            self.history.append(
                "> <b>Aplicar peso próprio</b> "
                "<span style='color:#57606a'>(Pesos próprios removidos; ação liberada.)</span>"
            )
            self.refresh_action_palette()
            self.refresh_scene()
            return

        if not self.model.bars:
            self.show_error("Não há barras no modelo para aplicar o peso próprio.")
            return
        if not self.model.materials:
            self.show_error("Não há materiais cadastrados para aplicar o peso próprio.")
            return

        dialog = SelfweightDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        weights: list[tuple[str, float]] = []
        try:
            selected_types = set(dialog.selected_material_types)
            materials = dict.fromkeys(
                member.material
                for member in self.model.bars.values()
                if self.model.material_types.get(member.material, "Aço") in selected_types
            )
            for material in materials:
                weights.extend(self.model_service.member_selfweights(material))
        except ValueError as error:
            self.show_error(str(error))
            return

        if not weights:
            self.show_error(
                "Não há barras associadas aos tipos de material selecionados "
                "para aplicar o peso próprio."
            )
            return

        self.action_service.replace_action_with_selfweight(load_case, tuple(weights))
        material_types = ", ".join(dialog.selected_material_types)
        self.history.append(
            "> <b>Adicionar peso próprio</b> "
            f"<span style='color:#57606a'>(Tipos de material: {escape(material_types)})</span>"
        )
        self.refresh_action_palette()
        self.refresh_scene()

    def start_split_member(self) -> None:
        """Open the modal split window for the selected member or request one."""
        self._remember_last_command(self.start_split_member)
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.axes_panel.hide()
        self.reference_panel.hide()
        members = self._selected_command_members()
        if len(members) == 1:
            self._command_mode = None
            self.split_member_dialog.open_for_member(members[0])
            return

        self._command_mode = "split_member_selection"
        self.history.append(
            "> <b>Dividir barra</b> "
            "<span style='color:#57606a'>(Selecione apenas uma barra para dividir)</span>"
        )
        self.scene.plotter.setFocus()

    def _selected_command_members(self) -> tuple[str, ...]:
        targets = self.selected_elements or ([self.selected] if self.selected is not None else [])
        return tuple(dict.fromkeys(name for kind, name in targets if kind == "bar" and name in self.model.bars))

    def apply_split_member(self) -> None:
        """Apply the segment lengths entered in the modal split window."""
        configuration = self.split_member_dialog.split_configuration()
        if configuration is None:
            return
        member_name, segment_lengths = configuration
        try:
            _node_names, member_names = self.model_service.split_member_by_lengths(
                member_name, segment_lengths,
            )
        except ValueError as error:
            self.show_error(str(error))
            return

        self.command_session.cancel()
        self._command_mode = None
        if self.selected == ("bar", member_name):
            self.clear_selection()
        self.history.append(
            f"> <b>Dividir barra</b> <span style='color:#57606a'>"
            f"(Barra {escape(member_name)} dividida em {len(member_names)} segmentos)</span>"
        )
        self.normalize_member_directions_if_enabled()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.refresh_scene()
        self.split_member_dialog.accept()

    def start_reverse_member(self) -> None:
        """Reverse the selected member or enter graphical member-selection mode."""
        if self.member_direction_normalization_enabled:
            return
        self._remember_last_command(self.start_reverse_member)
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        members = self._selected_command_members()
        if members:
            self._reverse_members(members)
            return

        self.command_session.cancel()
        self._command_mode = "reverse_member_selection"
        self.history.append(
            "> <b>Inverter barra</b> "
            "<span style='color:#57606a'>(Selecione uma barra ou use Ctrl para selecionar vários e ENTER para confirmar)</span>"
        )
        self.scene.plotter.setFocus()

    def _reverse_member(self, member_name: str) -> None:
        self._reverse_members((member_name,))

    def _reverse_members(self, member_names: tuple[str, ...]) -> None:
        if self.member_direction_normalization_enabled:
            return
        self.command_session.cancel()
        self._command_mode = None
        try:
            for member_name in member_names:
                self.model_service.reverse_member(member_name)
        except ValueError as error:
            self.history.append(
                f"> <b>Inverter barra</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self.history.append(
            f"> <b>Inverter barra</b> <span style='color:#57606a'>"
            f"({len(member_names)} barra(s) invertida(s))</span>"
        )
        self.refresh_selected_property_panel(self.palette.active_group)
        self.refresh_scene()

    def start_join_members(self) -> None:
        """Join the selection or request connected collinear members."""
        self._remember_last_command(self.start_join_members)
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._command_mode = "join_member_selection"
        members = self._selected_command_members()
        self._join_member_first = (
            members[0]
            if len(members) == 1
            else None
        )
        if len(members) >= 2:
            self._join_members(*members)
            return
        if self._join_member_first is None:
            message = "Selecione barras na mesma reta com Ctrl e pressione ENTER"
        else:
            message = "Selecione outra barra ou use Ctrl e ENTER para unir vários na mesma reta"
        self.history.append(
            "> <b>Unir barras</b> "
            f"<span style='color:#57606a'>({message})</span>"
        )
        self.scene.plotter.setFocus()

    def _join_members(self, *member_names: str) -> None:
        try:
            joined = self.model_service.join_selected_members(member_names)
        except ValueError as error:
            self.history.append(
                f"> <b>Unir barras</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self.normalize_member_directions_if_enabled()
        self._join_member_first = None
        self._command_mode = None
        self.history.append(
            f"> <b>Unir barras</b> <span style='color:#57606a'>"
            f"(Barras unidas em {escape(joined.name)})</span>"
        )
        self.clear_selection()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.refresh_scene()

    def start_group_verification_elements(self) -> None:
        """Select a collinear chain of bars and group it for verification."""
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._command_mode = "verification_group_selection"
        self.scene.set_selection_highlight(())
        self.selected_elements = []
        self.selected = None
        self.properties.hide()
        self.history.append("> <b>Agrupar barras</b> <span style='color:#57606a'>(Use Ctrl para selecionar barras alinhadas; ENTER confirma, ESC cancela)</span>")
        self.scene.plotter.setFocus()

    def start_ungroup_verification_elements(self) -> None:
        """Select a member of a verification group and remove that group."""
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._command_mode = "verification_ungroup_selection"
        self.scene.set_selection_highlight(())
        self.selected_elements = []
        self.selected = None
        self.properties.hide()
        self.history.append("> <b>Desagrupar barras</b> <span style='color:#57606a'>(Selecione uma barra do grupo; ESC cancela)</span>")
        self.scene.plotter.setFocus()

    def start_copy_member_properties(self) -> None:
        """Choose a reference member and then any number of destination members."""
        self._remember_last_command(self.start_copy_member_properties)
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._copy_elements_selection = []
        self._copy_elements_reference = None
        members = self._selected_command_members()
        self._copy_properties_reference = (
            members[0]
            if members
            else None
        )
        self._command_mode = "copy_member_properties_selection"
        targets = tuple(("bar", name) for name in members[1:])
        self.scene.set_selection_highlight(targets)
        self.selected_elements = list(targets)
        self.selected = targets[-1] if targets else None
        self.member_property_copy_panel.begin(self.top_icon_palette.copy_properties_button)
        message = (
            f"Referência: {escape(self._copy_properties_reference)}; selecione destinos com Ctrl e pressione ENTER"
            if self._copy_properties_reference is not None
            else "Selecione a barra de referência"
        )
        self.history.append(
            "> <b>Copiar propriedades</b> "
            f"<span style='color:#57606a'>({message})</span>"
        )
        self.scene.plotter.setFocus()

    def _copy_member_properties(self, source_name: str, target_name: str, *, refresh: bool = True) -> None:
        properties = self.member_property_copy_panel.selected_properties()
        try:
            copied = self.model_service.copy_member_properties(
                source_name, target_name, properties,
            )
        except ValueError as error:
            self.history.append(
                f"> <b>Copiar propriedades</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        if "section" in properties:
            if copied.profile:
                self.section_profiles[target_name] = copied.profile
            else:
                self.section_profiles.pop(target_name, None)
            if copied.section_geometry:
                self.section_geometry[target_name] = copied.geometry_dict()
            else:
                self.section_geometry.pop(target_name, None)
        self.history.append(
            f"> <b>Copiar propriedades</b> <span style='color:#57606a'>"
            f"(Propriedades copiadas para {escape(target_name)}; "
            "selecione outro destino ou pressione ESC)</span>"
        )
        if refresh:
            self.refresh_selected_property_panel(self.palette.active_group)
            self.refresh_scene()

    def start_copy_elements(self) -> None:
        """Start selecting nodes, members, and rigid bars for a translated copy."""
        self._remember_last_command(self.start_copy_elements)
        self.command_session.cancel()
        self._member_placement_start = None
        targets = self.selected_elements or ([self.selected] if self.selected is not None else [])
        self._copy_elements_selection = [
            target for target in targets if target[0] in {"node", "bar", "rigid_bar"}
        ]
        self._copy_elements_reference = None
        self._copy_properties_reference = None
        self.member_property_copy_panel.hide()
        self._command_mode = "copy_elements_selection"
        self.scene.set_member_placement_mode(False)
        self.scene.set_selection_highlight(self._copy_elements_selection)
        self.selected_elements = list(self._copy_elements_selection)
        self.selected = self.selected_elements[-1] if self.selected_elements else None
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()
        self.history.append(
            "> <b>Copiar</b> <span style='color:#57606a'>"
            "(Selecione nós, barras e barras rígidas; use Ctrl para multiseleção e ENTER para confirmar)</span>"
        )
        self.scene.plotter.setFocus()

    def select_scene_view(self, name: str) -> None:
        if name not in self.model.scene_views:
            return
        if self._command_mode in {"scene_hide_selection", "scene_reveal_selection"}:
            self.cancel_member_placement()
        self.model.select_scene_view(name)
        if self.top_icon_palette.scene_view_selector.currentText() != name:
            self.top_icon_palette.reload_scene_views()
        self.clear_selection()
        self.scene.render_model(self.model)

    def _start_scene_member_selection(self, mode: str) -> None:
        if self.model.active_scene_view == "Completo":
            return
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._command_mode = f"scene_{mode}_selection"
        self.clear_selection()
        self.scene.set_scene_selection_mode(mode)
        action = "Ocultar" if mode == "hide" else "Reexibir"
        self.history.append(
            f"> <b>{action}</b> <span style='color:#57606a'>"
            "(Selecione barras e barras rígidas; use Ctrl para multiseleção e pressione ENTER para confirmar)</span>"
        )
        self.scene.plotter.setFocus()

    def start_scene_hide_selection(self) -> None:
        self._start_scene_member_selection("hide")

    def start_scene_reveal_selection(self) -> None:
        self._start_scene_member_selection("reveal")

    def _confirm_scene_view_selection(self) -> None:
        mode = self._command_mode
        if mode not in {"scene_hide_selection", "scene_reveal_selection"}:
            return
        member_names = {name for kind, name in self.selected_elements if kind == "bar"}
        rigid_bar_names = {name for kind, name in self.selected_elements if kind == "rigid_bar"}
        if not member_names and not rigid_bar_names:
            self.history.append(
                "> <b>Cena</b> <span style='color:#8c959f'>"
                "(Selecione pelo menos um elemento e pressione ENTER)</span>"
            )
            return
        hidden = mode == "scene_hide_selection"
        self.model.set_scene_members_hidden(member_names, hidden)
        self.model.set_scene_rigid_bars_hidden(rigid_bar_names, hidden)
        self._command_mode = None
        self.clear_selection()
        self.scene.set_scene_selection_mode(None)
        action = "ocultado(s)" if mode == "scene_hide_selection" else "reexibido(s)"
        self.history.append(
            f"> <b>Cena</b> <span style='color:#57606a'>"
            f"({len(member_names)} barra(s) e {len(rigid_bar_names)} barra(s) rígida(s) "
            f"{action})</span>"
        )

    def show_all_scene_members(self) -> None:
        if self.model.active_scene_view == "Completo":
            return
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.model.show_all_scene_members()
        self.clear_selection()
        self.scene.render_model(self.model)
        self.history.append(
            "> <b>Reexibir tudo</b> <span style='color:#57606a'>"
            "(Todos os elementos da vista estão visíveis)</span>"
        )

    def _confirm_copy_elements(self) -> None:
        """Confirm the element set and begin the two-point copy placement."""
        if self._command_mode != "copy_elements_selection":
            return
        self._copy_elements_selection = [
            target for target in self.selected_elements
            if target[0] in {"node", "bar", "rigid_bar"}
        ]
        if not self._copy_elements_selection:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#8c959f'>"
                "(Selecione pelo menos um nó ou elemento)</span>"
            )
            return
        self._copy_elements_reference = None
        self._command_mode = "copy_elements_reference_placement"
        self.scene.set_member_placement_mode(True)
        self.history.append(
            "> <b>Copiar</b> <span style='color:#57606a'>"
            "(Selecione a posição de referência)</span>"
        )
        self.scene.plotter.setFocus()

    def _confirm_command_selection(self) -> None:
        """Apply commands to the shared Ctrl selection when ENTER is pressed."""
        mode = self._command_mode
        if mode == "plate_selection":
            self._finish_plate_selection()
            return
        if mode not in {
            "split_member_selection", "reverse_member_selection", "join_member_selection",
            "copy_member_properties_selection", "action_selection", "verification_group_selection",
        }:
            return
        members = self._selected_command_members()
        if mode == "verification_group_selection":
            if len(members) < 2:
                self.history.append("> <b>Agrupar barras</b> <span style='color:#8c959f'>(Selecione ao menos duas barras e pressione ENTER)</span>")
                return
            try:
                self.model.group_verification_elements(members)
            except ValueError as error:
                self.history.append(f"> <b>Agrupar barras</b> <span style='color:#8c959f'>({escape(str(error))})</span>")
                return
            self._command_mode = None
            self.history.append(f"> <b>Agrupar barras</b> <span style='color:#57606a'>({len(members)} barras agrupadas)</span>")
            self.clear_selection()
            self.refresh_scene()
            return
        if mode == "action_selection":
            if self._pending_action_launch is None:
                return
            targets = tuple(target for target in self.selected_elements if target[0] == self._pending_action_launch[0])
            if not targets:
                self.history.append(
                    "> <b>Adicionar ação</b> <span style='color:#8c959f'>(Selecione os elementos e pressione ENTER)</span>"
                )
                return
            for kind, name in targets:
                self._apply_pending_action(kind, name, refresh=False)
            self.clear_selection()
            self.refresh_action_palette()
            self.refresh_scene()
            return
        if not members:
            self.history.append(
                "> <span style='color:#8c959f'>(Selecione pelo menos uma barra e pressione ENTER)</span>"
            )
            return
        if mode == "split_member_selection":
            if len(members) != 1:
                self.history.append(
                    "> <b>Dividir barra</b> <span style='color:#8c959f'>(Selecione apenas uma barra para dividir)</span>"
                )
                return
            self._command_mode = None
            self.split_member_dialog.open_for_member(members[0])
        elif mode == "reverse_member_selection":
            self._reverse_members(members)
        elif mode == "join_member_selection":
            if len(members) < 2:
                self.history.append(
                    "> <b>Unir barras</b> <span style='color:#8c959f'>(Selecione pelo menos duas barras e pressione ENTER)</span>"
                )
                return
            self._join_members(*members)
        elif self._copy_properties_reference is None:
            if len(members) != 1:
                self.history.append(
                    "> <b>Copiar propriedades</b> <span style='color:#8c959f'>(Selecione apenas uma barra de referência)</span>"
                )
                return
            self._copy_properties_reference = members[0]
            self.clear_selection()
            self.history.append(
                "> <b>Copiar propriedades</b> <span style='color:#57606a'>"
                f"(Referência: {escape(members[0])}; selecione destinos com Ctrl e pressione ENTER)</span>"
            )
        else:
            targets = tuple(name for name in members if name != self._copy_properties_reference)
            if not targets:
                self.history.append(
                    "> <b>Copiar propriedades</b> <span style='color:#8c959f'>(Selecione destinos diferentes da referência)</span>"
                )
                return
            if not self.member_property_copy_panel.selected_properties():
                self.history.append(
                    "> <b>Copiar propriedades</b> <span style='color:#8c959f'>(Selecione pelo menos uma propriedade para copiar)</span>"
                )
                return
            for name in targets:
                self._copy_member_properties(self._copy_properties_reference, name, refresh=False)
            self.clear_selection()
            self.refresh_scene()

    def _handle_copy_placement_point(self, point: object) -> None:
        """Collect the reference/destination points and copy the selection."""
        if self._command_mode == "copy_elements_reference_placement":
            self._copy_elements_reference = tuple(float(value) for value in point)
            self._command_mode = "copy_elements_destination_placement"
            self.scene.set_member_preview_start(self._copy_elements_reference)
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                "(Selecione a posição de destino; pressione ESC para encerrar)</span>"
            )
            return
        if self._command_mode != "copy_elements_destination_placement":
            return
        reference = self._copy_elements_reference
        if reference is None:
            return
        destination = tuple(float(value) for value in point)
        offset = tuple(
            destination[index] - reference[index]
            for index in range(3)
        )
        node_names = tuple(
            name for kind, name in self._copy_elements_selection if kind == "node"
        )
        member_names = tuple(
            name for kind, name in self._copy_elements_selection if kind == "bar"
        )
        rigid_bar_names = tuple(
            name for kind, name in self._copy_elements_selection if kind == "rigid_bar"
        )
        rigid_bars_before = set(self.model.rigid_bars)
        try:
            copied_nodes, copied_members = self.model_service.copy_elements(
                node_names, member_names, offset, rigid_bar_names,
            )
        except ValueError as error:
            self.history.append(
                f"> <b>Copiar</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        copied_rigid_bars = tuple(set(self.model.rigid_bars) - rigid_bars_before)

        for member_name in copied_members:
            copied_member = self.model.bars[member_name]
            if copied_member.profile:
                self.section_profiles[member_name] = copied_member.profile
            if copied_member.section_geometry:
                self.section_geometry[member_name] = copied_member.geometry_dict()

        self._command_mode = "copy_elements_destination_placement"
        if copied_nodes or copied_members or copied_rigid_bars:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                f"({len(copied_nodes)} nó(s), {len(copied_members)} barra(s) e "
                f"{len(copied_rigid_bars)} barra(s) rígida(s) criada(s); "
                "selecione outro destino ou pressione ESC para encerrar)</span>"
            )
        else:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                "(Nenhum elemento novo: os elementos já existiam na posição de destino; "
                "selecione outro destino ou pressione ESC para encerrar)</span>"
            )
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.refresh_scene()

    def start_plate_placement(self) -> None:
        self.cancel_member_placement()
        self._remember_last_command(self.start_plate_placement)
        self.command_session.cancel()
        self.clear_selection()
        self._plate_selection = []
        self._plate_segments = []
        self._plate_manual_segments = []
        self._plate_manual_start = None
        self._command_mode = "plate_selection"
        self.history.append(
            "> <b>Adicionar placa</b> <span style='color:#57606a'>"
            "(Selecione as barras do contorno; ENTER conclui e ESC cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def _plate_add_selection(self, kind: str, name: str) -> None:
        target = (kind, name)
        if kind not in {"bar", "rigid_bar"} or target in self._plate_selection:
            self.scene.set_selection_highlight(self._plate_selection)
            return
        element = (self.model.bars if kind == "bar" else self.model.rigid_bars).get(name)
        if element is None:
            return
        a, b = (self.model.nodes[element.start_node], self.model.nodes[element.end_node])
        segment = ((a.x, a.y, a.z), (b.x, b.y, b.z))
        if any(
            all(math.dist(point, endpoint) < 1e-8 for point, endpoint in zip(segment, old))
            or all(math.dist(point, endpoint) < 1e-8 for point, endpoint in zip(segment, reversed(old)))
            for old in self._plate_segments
        ) or any(
            sum(math.dist(point, endpoint) < 1e-8 for old in self._plate_segments for endpoint in old) >= 2
            for point in segment
        ):
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#8c959f'>"
                "(A barra repetiria uma aresta ou criaria uma ramificação)</span>"
            )
            self.scene.set_selection_highlight(self._plate_selection)
            return
        self._plate_selection.append(target)
        self._plate_segments.append(segment)
        self.selected_elements = list(self._plate_selection)
        self.selected = target
        self.scene.set_selection_highlight(self._plate_selection)
        self.history.append(
            f"> <b>Adicionar placa</b> <span style='color:#57606a'>"
            f"(Barra {escape(name)} selecionada; selecione a próxima ou pressione ENTER)</span>"
        )
        try:
            contour = plate_contour(self._plate_segments)
        except ValueError:
            return
        self._create_plate(contour)

    def _finish_plate_selection(self) -> None:
        if not self._plate_segments:
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#8c959f'>(Selecione as barras do contorno)</span>"
            )
            return
        if self.plate_closure_mode == "automatico":
            choice = "automatic"
        else:
            dialog = PlateClosureDialog(self)
            dialog.move(self.geometry().center() - dialog.rect().center())
            dialog.exec()
            choice = dialog.choice
        if choice == "automatic":
            try:
                contour = plate_contour(self._plate_segments, close_automatically=True)
            except ValueError as error:
                self.history.append(f"> <b>Adicionar placa</b> <span style='color:#8c959f'>({escape(str(error))})</span>")
                return
            self._create_plate(contour)
        elif choice == "manual":
            self._command_mode = "plate_manual"
            self._plate_saved_endpoint_snap = self.scene._snap_types["endpoint"]
            self.scene._snap_types["endpoint"] = True
            self.scene.set_member_placement_mode(True)
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#57606a'>"
                "(Clique em duas extremidades livres para ligá-las; ESC cancela)</span>"
            )
            self.scene.plotter.setFocus()
        else:
            self.cancel_member_placement()

    def _plate_manual_point(self, point) -> None:
        segments = self._plate_segments + self._plate_manual_segments
        points = [p for segment in segments for p in segment]
        free = [p for p in points if sum(math.dist(p, q) < 1e-8 for q in points) == 1]
        if not free:
            return
        nearest = min(free, key=lambda p: math.dist(p, point))
        if math.dist(nearest, point) > 0.002:
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#8c959f'>(Selecione uma extremidade livre)</span>"
            )
            return
        if self._plate_manual_start is None:
            self._plate_manual_start = nearest
            self.scene.set_member_preview_start(nearest)
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#57606a'>(Selecione outra extremidade livre)</span>"
            )
            return
        if math.dist(self._plate_manual_start, nearest) < 1e-8:
            return
        new_segment = (self._plate_manual_start, nearest)
        candidate = self._plate_segments + self._plate_manual_segments + [new_segment]
        remaining = len(free) - 2
        reachable = {self._plate_manual_start}
        while True:
            extended = reachable | {
                endpoint for a, b in segments for endpoint, other in ((a, b), (b, a))
                if any(math.dist(other, point) < 1e-8 for point in reachable)
            }
            if extended == reachable:
                break
            reachable = extended
        if remaining and any(math.dist(nearest, point) < 1e-8 for point in reachable):
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#8c959f'>"
                "(Esta ligação fecharia apenas parte do contorno)</span>"
            )
            self.scene.set_member_preview_start(None)
            self._plate_manual_start = None
            return
        if remaining == 0:
            try:
                plate_contour(candidate)
            except ValueError as error:
                self.history.append(f"> <b>Adicionar placa</b> <span style='color:#8c959f'>({escape(str(error))})</span>")
                self.scene.set_member_preview_start(None)
                self._plate_manual_start = None
                return
        self._plate_manual_segments.append(new_segment)
        self._plate_manual_start = None
        self.scene.set_member_preview_start(None)
        self.scene.set_plate_manual_segments(self._plate_manual_segments)
        try:
            contour = plate_contour(self._plate_segments + self._plate_manual_segments)
        except ValueError as error:
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#57606a'>"
                f"({escape(str(error))} Selecione outras extremidades livres)</span>"
            )
            return
        self._create_plate(contour)

    def _create_plate(self, contour) -> None:
        try:
            plate = self.model.add_plate(contour, supports=self._plate_selection)
        except ValueError as error:
            self.history.append(f"> <b>Adicionar placa</b> <span style='color:#8c959f'>({escape(str(error))})</span>")
            return
        self._command_mode = None
        self._restore_plate_snap()
        self.scene.set_member_preview_start(None)
        self.scene.set_member_placement_mode(False)
        self.scene.set_plate_manual_segments([])
        self.clear_selection()
        self.scene.render_model(self.model)
        self.history.append(f"> <b>Adicionar placa</b> <span style='color:#57606a'>(Placa {escape(plate.name)} criada)</span>")

    def _restore_plate_snap(self) -> None:
        if self._plate_saved_endpoint_snap is not None:
            self.scene._snap_types["endpoint"] = self._plate_saved_endpoint_snap
            self._plate_saved_endpoint_snap = None

    def _handle_interface_command(self, command: str) -> bool:
        """Dispatch one-word commands that mirror visible interface buttons."""
        text = command.strip()
        parts = text.split()
        name = parts[0].casefold() if parts else ""
        if name not in self._interface_commands:
            return False
        if len(parts) != 1:
            self.history.append(
                f"> <b>{escape(text)}</b> "
                "<span style='color:#8c959f'>(Este comando não aceita argumentos.)</span>"
            )
            return True

        geometry_visibility = {
            "grid": "grid",
            "axes": "reference-axes",
            "nodelabels": "node",
            "memberlabels": "bar",
            "platelabels": "plate",
            "localaxes": "axes",
            "nodes": "nodes",
            "solids": "solid",
            "releases": "releases",
            "semirigid": "semirigid",
            "supports": "supports",
        }
        action_visibility = {
            "nodeforce": "node_forces",
            "nodemoment": "node_moments",
            "memberforce": "member_forces",
            "membermoment": "member_moments",
            "platepressure": "plate_pressures",
        }
        command_label = escape(name.upper())

        if name == "plate":
            self.palette.show_group("Geometria")
            self.start_plate_placement()
            return True

        if name == "scene":
            self.palette.show_group("Geometria")
            self.top_icon_palette.scene_button.toggle()
            self.history.append(f"> <b>{command_label}</b>")
            return True

        if name == "group" and self.palette.active_group == "Memorial":
            self.start_group_verification_elements()
            return True

        if name == "ungroup":
            self.palette.show_group("Memorial")
            self.start_ungroup_verification_elements()
            return True

        if name in geometry_visibility:
            self.palette.show_group("Geometria")
            self.top_icon_palette.toggle_visibility_command(geometry_visibility[name])
            self.history.append(f"> <b>{command_label}</b>")
            return True

        if name in action_visibility:
            self.palette.show_group("Ações")
            self.action_top_palette.toggle_action_visibility_command(action_visibility[name])
            self.history.append(f"> <b>{command_label}</b>")
            return True

        callbacks = {
            "bar": ("Geometria", self.start_member_placement),
            "split": ("Geometria", self.start_split_member),
            "reverse": ("Geometria", self.start_reverse_member),
            "join": ("Geometria", self.start_join_members),
            "rigid": ("Geometria", self.start_rigid_bar_placement),
            "copy": ("Geometria", self.start_copy_elements),
            "cprop": ("Geometria", self.start_copy_member_properties),
            "measure": ("Geometria", self.start_measurement),
            "configaxes": ("Geometria", self.toggle_axes_panel),
            "configreference": ("Geometria", self.toggle_reference_panel),
            "group": ("Ações", self.open_action_groups),
            "action": ("Ações", self.start_load_command),
            "load": ("Ações", self.start_load_command),
            "selfweight": ("Ações", self.start_selfweight_command),
            "combinations": ("Análise", self.open_combinations),
            "analyze": ("Análise", self.process_analysis),
            "verify": ("Memorial", self.verify_model),
        }
        target = callbacks.get(name)
        if target is None:
            return False
        self.palette.show_group(target[0])
        target[1]()
        if name in {"configaxes", "configreference", "group", "combinations", "analyze", "verify"}:
            self.history.append(f"> <b>{command_label}</b>")
        return True

    def handle_command(self, command: str) -> None:
        if self._handle_interface_command(command):
            return
        self.member_placement_editor.hide()
        had_model_geometry = bool(self.model.nodes)
        command_name = command.strip().casefold().split(maxsplit=1)[0] if command.strip() else ""
        split_source = self.command_session.split_member_name
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        if command.strip().casefold() in {"load", "selfweight"} and self.command_session.pending is None:
            self.palette.show_group("Ações")
        response = self.command_session.submit(command)
        self._command_mode = self.command_session.pending
        escaped = escape(response.command)
        if response.level == "instruction":
            self.history.append(
                f"> <b>{escaped}</b> <span style='color:#57606a'>({escape(response.message)})</span>"
            )
        elif response.level == "error":
            self.history.append(
                f"> <b>{escaped}</b> <span style='color:#8c959f'>({escape(response.message)})</span>"
            )
        elif response.split_member_names:
            self.history.append(
                f"> <b>{escaped}</b> <span style='color:#57606a'>({escape(response.message)})</span>"
            )
        else:
            self.history.append(f"> <b>{escaped}</b>")
        if response.remove_selfweight:
            self.action_service.remove_selfweight(self.selected_action_name or "")
            self.refresh_action_palette()
            self.refresh_scene()
        elif response.selfweights:
            self.action_service.replace_action_with_selfweight(
                self.selected_action_name or "",
                tuple((weight.target, weight.value) for weight in response.selfweights),
            )
            self.refresh_action_palette()
            self.refresh_scene()
        elif response.distributed_member_forces:
            for load in response.distributed_member_forces:
                self.action_service.add_member_distributed_force(
                    load.target, load.direction, load.initial, load.final,
                    self.selected_action_name or "", load.reference,
                )
            self.refresh_scene()
        elif response.member_moments:
            for moment in response.member_moments:
                self.action_service.add_member_moment(
                    moment.target, moment.direction, moment.value, self.selected_action_name or "",
                )
            self.refresh_scene()
        elif response.node_forces:
            for force in response.node_forces:
                self.action_service.add_node_force(
                    force.target, force.direction, force.value, self.selected_action_name or "",
                )
            self.refresh_scene()
        elif response.node_moments:
            for moment in response.node_moments:
                self.action_service.add_node_moment(
                    moment.target, moment.direction, moment.value, self.selected_action_name or "",
                )
            self.refresh_scene()
        elif response.model_changed:
            if split_source is not None and self.selected == ("bar", split_source):
                self.clear_selection()
            self.normalize_member_directions_if_enabled()
            self.refresh_action_palette()
            self.refresh_analysis_palette()
            self.refresh_scene(
                fit_camera=(
                    not had_model_geometry and command_name in self._initial_framing_commands
                ),
            )

    def _current_placement_snap_target(self) -> tuple[str, str] | None:
        target = self.scene._placement_snap_element
        if target is not None:
            return target
        # Preserve compatibility with member-only placement integrations.
        member_name = self.scene._placement_snap_member_name
        return ("bar", member_name) if member_name is not None else None

    def _split_snapped_element_at_point(
        self, target: tuple[str, str], coordinates: tuple[float, float, float],
    ) -> str | None:
        kind, name = target
        if kind == "rigid_bar":
            node_names, _rigid_names = self.model_service.split_rigid_bar_at_point(
                name, coordinates,
            )
        else:
            node_names, _member_names = self.model_service.split_member_at_point(
                name, coordinates,
            )
        return node_names[0] if node_names else self._node_at_coordinates(coordinates)

    def _handle_member_placement_point(self, point: object) -> None:
        """Advance the two-click graphical member placement flow."""
        if self._command_mode == "plate_manual":
            self._plate_manual_point(tuple(float(value) for value in point))
            return
        if self._command_mode != "member_placement":
            return
        coordinates = tuple(float(value) for value in point)
        if self._member_placement_start is None:
            self._member_placement_start = coordinates
            self._member_placement_start_snap_target = self._current_placement_snap_target()
            self._member_placement_start_snap_member_name = (
                self._member_placement_start_snap_target[1]
                if self._member_placement_start_snap_target is not None
                and self._member_placement_start_snap_target[0] == "bar" else None
            )
            self.scene.set_member_preview_start(coordinates)
            self._show_member_placement_prompt()
            return

        start = self._member_placement_start
        if self.model.node_coordinates(*start) == self.model.node_coordinates(*coordinates):
            self.history.append(
                "> <b>Adicionar barra</b> "
                "<span style='color:#8c959f'>(O segundo ponto deve ser diferente do ponto inicial.)</span>"
            )
            return

        snapped_points = (
            ("inicial", self._member_placement_start_snap_target, start),
            ("final", self._current_placement_snap_target(), coordinates),
        )
        split_mode = self.member_intermediate_snap_split_mode
        split_decisions: list[tuple[str, tuple[str, str], tuple[float, float, float]]] = []
        for node_label, target, snap_point in snapped_points:
            if target is None:
                continue
            should_split = split_mode == "sim"
            if split_mode == "perguntar":
                dialog = MemberSnapSplitDialog(target[1], node_label, self)
                dialog.move(self.geometry().center() - dialog.rect().center())
                should_split = dialog.exec() == QDialog.DialogCode.Accepted and dialog.should_split
            if should_split:
                split_decisions.append((node_label, target, snap_point))

        start_node_name = None
        end_node_name = None
        try:
            for node_label, target, snap_point in split_decisions:
                node_name = self._split_snapped_element_at_point(target, snap_point)
                if node_label == "inicial":
                    start_node_name = node_name
                else:
                    end_node_name = node_name
            start_name, end_name, member_name = self._create_graphical_member(
                start, coordinates,
                start_node_name=start_node_name, end_node_name=end_node_name,
            )
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar barra</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            if self.member_placement_editor.point_mode == "midpoint":
                self._show_member_placement_prompt()
            return

        self._member_placement_start = None
        self._member_placement_start_snap_member_name = None
        self._member_placement_start_snap_target = None
        self.command_session.cancel()
        self._command_mode = "member_placement"
        self.scene.set_member_preview_start(None)
        self.scene.set_member_placement_mode(True, point_mode=self.member_placement_editor.point_mode)
        self.history.append(
            f"> <b>Adicionar barra</b> <span style='color:#57606a'>"
            f"(Barra {escape(member_name)} criada entre {escape(start_name)} e {escape(end_name)})</span>"
        )
        self._show_member_placement_prompt()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        # The point signal is deferred until VTK processes the mouse release.
        # Keep the scene rebuild queued as well so the next terrain orbit
        # always starts from a fully finished camera gesture.
        QTimer.singleShot(0, self.refresh_scene)

    def _handle_node_placement_point(self, point: object) -> None:
        """Create one node and keep the graphical node tool active."""
        if self._command_mode != "node_placement":
            return
        coordinates = tuple(float(value) for value in point)
        node_name = self._node_at_coordinates(coordinates)
        if node_name is not None:
            self.history.append(
                f"> <b>Adicionar nó</b> <span style='color:#8c959f'>"
                f"(O nó {escape(node_name)} já existe nessa posição)</span>"
            )
            return

        try:
            node_name = self.model_service.next_node_name()
            self.model_service.create_node(*coordinates, name=node_name)
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar nó</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self.command_session.cancel()
        self._command_mode = "node_placement"
        self.scene.set_node_placement_mode(True)
        self.history.append(
            f"> <b>Adicionar nó</b> <span style='color:#57606a'>"
            f"(Nó {escape(node_name)} criado em "
            f"X {coordinates[0]:.3f} m, Y {coordinates[1]:.3f} m, Z {coordinates[2]:.3f} m)</span>"
        )
        self.history.append(
            "> <b>Adicionar nó</b> <span style='color:#57606a'>(Clique na posição do próximo nó)</span>"
        )
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        QTimer.singleShot(0, self.refresh_scene)

    def _handle_reference_axis_placement_point(self, point: object) -> None:
        """Store the picked coordinate and keep requesting axes until cancelled."""
        if self._command_mode != "reference_axis_placement":
            return
        direction = self._reference_axis_placement_direction
        if direction is None:
            return
        coordinates = tuple(float(value) for value in point)
        if not self.axes_panel.add_axis_from_point(direction, coordinates):
            self.history.append(
                f"> <b>Definir eixos {direction}</b> "
                f"<span style='color:#8c959f'>(Já existe um eixo {direction} com essa coordenada ou rótulo; escolha outro ponto)</span>"
            )
            return
        value = round(coordinates[{"X": 0, "Y": 1, "Z": 2}[direction]], 3)
        self.history.append(
            f"> <b>Definir eixos {direction}</b> "
            f"<span style='color:#57606a'>(Eixo definido em {direction} = {value:.3f} m; clique para definir o próximo)</span>"
        )
        QTimer.singleShot(0, self.refresh_scene)

    def _handle_rigid_bar_placement_point(self, point: object) -> None:
        """Advance the two-click graphical rigid-bar placement flow."""
        if self._command_mode != "rigid_bar_placement":
            return
        coordinates = tuple(float(value) for value in point)
        if self._member_placement_start is None:
            self._member_placement_start = coordinates
            self._member_placement_start_snap_target = self._current_placement_snap_target()
            self._member_placement_start_snap_member_name = (
                self._member_placement_start_snap_target[1]
                if self._member_placement_start_snap_target is not None
                and self._member_placement_start_snap_target[0] == "bar" else None
            )
            self.scene.set_member_preview_start(coordinates)
            self.history.append(
                "> <b>Adicionar barra rígida</b> "
                "<span style='color:#57606a'>(Clique na posição final da barra rígida)</span>"
            )
            return

        start = self._member_placement_start
        if self.model.node_coordinates(*start) == self.model.node_coordinates(*coordinates):
            self.history.append(
                "> <b>Adicionar barra rígida</b> "
                "<span style='color:#8c959f'>(O segundo ponto deve ser diferente do ponto inicial.)</span>"
            )
            return
        snapped_points = (
            ("inicial", self._member_placement_start_snap_target, start),
            ("final", self._current_placement_snap_target(), coordinates),
        )
        split_decisions: list[tuple[str, tuple[str, str], tuple[float, float, float]]] = []
        split_mode = self.member_intermediate_snap_split_mode
        for node_label, target, snap_point in snapped_points:
            if target is None:
                continue
            should_split = split_mode == "sim"
            if split_mode == "perguntar":
                dialog = MemberSnapSplitDialog(target[1], node_label, self)
                dialog.move(self.geometry().center() - dialog.rect().center())
                should_split = dialog.exec() == QDialog.DialogCode.Accepted and dialog.should_split
            if should_split:
                split_decisions.append((node_label, target, snap_point))

        try:
            for _node_label, target, snap_point in split_decisions:
                self._split_snapped_element_at_point(target, snap_point)
            start_name, end_name, rigid_name = self._create_graphical_rigid_bar(start, coordinates)
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar barra rígida</b> "
                f"<span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self._member_placement_start = None
        self._member_placement_start_snap_member_name = None
        self._member_placement_start_snap_target = None
        self.command_session.cancel()
        self._command_mode = "rigid_bar_placement"
        self.scene.set_member_preview_start(None)
        self.scene.set_member_placement_mode(True)
        self.history.append(
            f"> <b>Adicionar barra rígida</b> <span style='color:#57606a'>"
            f"(Barra rígida {escape(rigid_name)} criada entre "
            f"{escape(start_name)} e {escape(end_name)})</span>"
        )
        self.history.append(
            "> <b>Adicionar barra rígida</b> "
            "<span style='color:#57606a'>(Clique na posição inicial da próxima barra rígida)</span>"
        )
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        QTimer.singleShot(0, self.refresh_scene)

    def _handle_measurement_point(self, point: object) -> None:
        """Collect two transient points and close the measurement tool."""
        if self._command_mode != "measurement":
            return
        coordinates = tuple(float(value) for value in point)
        if self.scene.measurement_start is None:
            self.scene.set_measurement_start(coordinates)
            self.history.append(
                "> <b>Medir</b> "
                "<span style='color:#57606a'>(Clique no ponto final da medição)</span>"
            )
            return

        start = self.scene.measurement_start
        if start is not None:
            delta = tuple(end - begin for begin, end in zip(start, coordinates))
            length = math.hypot(*delta)
            values = (length, *delta)
            formatted = tuple(
                f"{0.0 if abs(value) < 0.0005 else value:.3f} m"
                for value in values
            )
            self.history.append(
                "> <b>Medir</b> "
                "<span style='color:#57606a'>"
                f"(Δ: {formatted[0]}; ΔX: {formatted[1]}; "
                f"ΔY: {formatted[2]}; ΔZ: {formatted[3]})</span>"
            )
        self._command_mode = None
        self.scene.set_measurement_start(None)
        self.scene.set_measurement_mode(False)

    def cancel_member_placement(self) -> None:
        """Cancel the active graphical geometry launch."""
        self.member_placement_editor.hide()
        if self._command_mode == "project_sheet_dimension":
            self.project_sheet_workspace.set_dimension_mode(False)
            self._finish_project_view_dimension(canceled=True)
            return
        if self._command_mode == "project_sheet_identification":
            self._finish_project_view_identification(canceled=True)
            return
        if self._command_mode in {"plate_selection", "plate_manual"}:
            self._command_mode = None
            self._restore_plate_snap()
            self._plate_selection = []
            self._plate_segments = []
            self._plate_manual_segments = []
            self._plate_manual_start = None
            self.scene.set_member_preview_start(None)
            self.scene.set_member_placement_mode(False)
            self.scene.set_plate_manual_segments([])
            self.clear_selection()
            self.history.append(
                "> <b>Adicionar placa</b> <span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode == "connect_member_ends_selection":
            self._command_mode = None
            self._connect_member_ends_first_bar = None
            self.clear_selection()
            self.history.append(
                "> <b>Conectar extremidades</b> "
                "<span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode in {
            "detail_subtraction_target_selection", "detail_subtraction_cutter_selection",
        }:
            self._command_mode = None
            self._detail_subtraction_target = None
            self.clear_selection()
            self.history.append(
                "> <b>Subtrair trecho</b> "
                "<span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode in {
            "endpoint_alignment_bar_selection", "endpoint_alignment_face_selection",
        }:
            self._command_mode = None
            self._endpoint_alignment_source = None
            self.scene.set_endpoint_alignment_target(None)
            self.clear_selection()
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode in {
            "face_alignment_source_selection", "face_alignment_reference_selection",
        }:
            self._command_mode = None
            self._face_alignment_source = None
            self._face_alignment_source_hit = None
            self.scene.set_face_alignment_mode(False)
            self.clear_selection()
            self.history.append(
                "> <b>Alinhar faces</b> <span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode == "detail_plane_placement":
            self._command_mode = None
            self._detail_plane_points = []
            self.scene.set_detail_plane_point_mode(False)
            self.history.append(
                "> <b>Adicionar plano</b> <span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            self._restore_project_mode_after_detail_plane()
            QTimer.singleShot(0, self.open_detailing_views)
            return
        if self._command_mode == "reference_axis_placement":
            self._command_mode = None
            self._reference_axis_placement_direction = None
            self.scene.set_node_placement_mode(False)
            self.history.append(
                "> <b>Definir eixos</b> <span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode in {"scene_hide_selection", "scene_reveal_selection"}:
            self._command_mode = None
            self.scene.set_scene_selection_mode(None)
            self.clear_selection()
            self.history.append(
                "> <b>Cena</b> <span style='color:#8c959f'>(Seleção cancelada)</span>"
            )
            return
        if self._command_mode == "action_selection":
            self._pending_action_launch = None
            self._command_mode = None
            self.history.append(
                "> <b>Adicionar ação</b> "
                "<span style='color:#8c959f'>(Lançamento cancelado)</span>"
            )
            return
        if self._command_mode in {
            "split_member_selection", "reverse_member_selection", "join_member_selection",
            "copy_member_properties_selection", "copy_elements_selection",
            "copy_elements_reference_placement", "copy_elements_destination_placement",
            "verification_group_selection", "verification_ungroup_selection",
        }:
            labels = {
                "reverse_member_selection": "Inverter barra",
                "join_member_selection": "Unir barras",
                "copy_member_properties_selection": "Copiar propriedades",
                "verification_group_selection": "Agrupar barras",
                "verification_ungroup_selection": "Desagrupar barras",
                "copy_elements_selection": "Copiar",
                "copy_elements_reference_placement": "Copiar",
                "copy_elements_destination_placement": "Copiar",
            }
            copy_elements_active = self._command_mode.startswith("copy_elements_")
            split_member_active = self._command_mode == "split_member_selection"
            label = labels.get(self._command_mode, "Dividir barra")
            self.command_session.cancel()
            self._command_mode = None
            self._join_member_first = None
            self._copy_properties_reference = None
            self._copy_elements_selection = []
            self._copy_elements_reference = None
            self.member_property_copy_panel.hide()
            if split_member_active:
                self.split_member_dialog.hide()
            if copy_elements_active:
                self.scene.set_member_preview_start(None)
                self.scene.set_member_placement_mode(False)
                self.scene.set_selection_highlight(())
                self.clear_selection()
            if label in {"Agrupar barras", "Desagrupar barras"}:
                self.scene.cancel_ctrl_selection()
                self.clear_selection()
            result_message = (
                "Comando encerrado" if copy_elements_active else "Operação cancelada"
            )
            self.history.append(
                f"> <b>{label}</b> "
                f"<span style='color:#8c959f'>({result_message})</span>"
            )
            return
        if self._command_mode == "measurement":
            self._command_mode = None
            self.scene.set_measurement_start(None)
            self.scene.set_measurement_mode(False)
            self.history.append(
                "> <b>Medir</b> "
                "<span style='color:#8c959f'>(Medição cancelada)</span>"
            )
            return
        if self._command_mode not in {
            "member_placement", "node_placement", "rigid_bar_placement",
        }:
            return
        labels = {
            "member_placement": "Adicionar barra",
            "node_placement": "Adicionar nó",
            "rigid_bar_placement": "Adicionar barra rígida",
        }
        label = labels[self._command_mode]
        self._member_placement_start = None
        self._member_placement_start_snap_member_name = None
        self._member_placement_start_snap_target = None
        self._command_mode = None
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self.history.append(
            f"> <b>{label}</b> "
            "<span style='color:#8c959f'>(Lançamento cancelado)</span>"
        )

    def _create_graphical_member(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        *,
        start_node_name: str | None = None,
        end_node_name: str | None = None,
    ) -> tuple[str, str, str]:
        start = self.model.node_coordinates(*start)
        end = self.model.node_coordinates(*end)
        tolerance = self.model.coordinate_tolerance
        if all(abs(start[index] - end[index]) <= tolerance for index in range(3)):
            raise ValueError("O segundo ponto deve ser diferente do ponto inicial.")

        # Resolve each endpoint against the model first, even when the caller
        # supplies a node created by an intermediate-snap split. This keeps
        # the launched member attached to an existing coincident node instead
        # of allowing an override name to bypass coordinate de-duplication.
        start_name = self._node_at_coordinates(start) or start_node_name
        end_name = self._node_at_coordinates(end) or end_node_name
        created_nodes: list[str] = []
        try:
            if start_name is None:
                start_name = self.model_service.next_node_name()
                self.model_service.create_node(*start, name=start_name)
                created_nodes.append(start_name)
            if end_name is None:
                end_name = self.model_service.next_node_name()
                self.model_service.create_node(*end, name=end_name)
                created_nodes.append(end_name)
            member_name = self.model_service.next_member_name()
            template = (
                self.member_placement_editor.template
                if self._command_mode == "member_placement" else None
            )
            self.model_service.create_member(start_name, end_name, name=member_name, template=template)
            self.normalize_member_directions_if_enabled()
        except ValueError:
            for node_name in reversed(created_nodes):
                self.model_service.remove_node(node_name)
            raise
        return start_name, end_name, member_name

    def _create_graphical_rigid_bar(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
    ) -> tuple[str, str, str]:
        start = self.model.node_coordinates(*start)
        end = self.model.node_coordinates(*end)
        tolerance = self.model.coordinate_tolerance
        if all(abs(start[index] - end[index]) <= tolerance for index in range(3)):
            raise ValueError("O segundo ponto deve ser diferente do ponto inicial.")

        start_name = self._node_at_coordinates(start)
        end_name = self._node_at_coordinates(end)
        created_nodes: list[str] = []
        try:
            if start_name is None:
                start_name = self.model_service.next_node_name()
                self.model_service.create_node(*start, name=start_name)
                created_nodes.append(start_name)
            if end_name is None:
                end_name = self.model_service.next_node_name()
                self.model_service.create_node(*end, name=end_name)
                created_nodes.append(end_name)
            rigid = self.model_service.create_rigid_bar(start_name, end_name)
        except ValueError:
            for node_name in reversed(created_nodes):
                self.model_service.remove_node(node_name)
            raise
        return start_name, end_name, rigid.name

    def _node_at_coordinates(self, coordinates: tuple[float, float, float]) -> str | None:
        coordinates = self.model.node_coordinates(*coordinates)
        tolerance = self.model.coordinate_tolerance
        for name, node in self.model.nodes.items():
            if all(
                abs(coordinate - node_coordinate) <= tolerance
                for coordinate, node_coordinate in zip(coordinates, (node.x, node.y, node.z))
            ):
                return name
        return None


    def _apply_pending_action(self, kind: str, name: str, *, refresh: bool = True) -> None:
        launch = self._pending_action_launch
        if launch is None:
            return
        target_kind, reference, values = launch
        if kind != target_kind:
            expected = "nó" if target_kind == "node" else "barra"
            self.history.append(
                "> <b>Adicionar ação</b> "
                f"<span style='color:#8c959f'>(Selecione apenas {expected})</span>"
            )
            return
        load_case = self.selected_action_name or ""
        if not load_case:
            self.cancel_member_placement()
            self.show_error("Selecione uma ação ativa antes de lançar um carregamento.")
            return
        if self.action_service.has_selfweight(load_case):
            self.cancel_member_placement()
            self.show_error("A ação atual está restrita apenas a cargas de peso próprio.")
            return

        try:
            if target_kind == "node":
                for label, components in values.items():
                    axis = label[-1]
                    value = components[0]
                    if label.startswith("F"):
                        self.action_service.add_node_force(name, axis, value, load_case)
                    else:
                        self.action_service.add_node_moment(name, axis, value, load_case)
            else:
                for label, components in values.items():
                    axis = label[-1]
                    if label.startswith("F"):
                        initial, final = (
                            components if len(components) == 2
                            else (components[0], components[0])
                        )
                        self.action_service.add_member_distributed_force(
                            name, axis, initial, final, load_case, reference,
                        )
                    elif reference == "local":
                        self.action_service.add_member_moment(
                            name, axis, components[0], load_case,
                        )
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar ação</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self.history.append(
            f"> <b>Adicionar ação</b> <span style='color:#57606a'>"
            f"(Ação lançada em {escape(name)})</span>"
        )
        if refresh:
            self.refresh_action_palette()
            self.refresh_scene()


    def select_element(self, kind: str, name: str, center: object) -> None:
        if self.palette.active_group == "Análise":
            return
        if self._command_mode == "plate_selection":
            self._plate_add_selection(kind, name)
            return
        if self._command_mode in {
            "detail_subtraction_target_selection", "detail_subtraction_cutter_selection",
        }:
            if kind not in {"bar", "plate"}:
                self.history.append(
                    "> <b>Subtrair trecho</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra ou placa)</span>"
                )
                self.clear_selection()
                return
            if self._command_mode == "detail_subtraction_target_selection":
                self._detail_subtraction_target = (kind, name)
                self._command_mode = "detail_subtraction_cutter_selection"
                self.clear_selection()
                self.history.append(
                    "> <b>Subtrair trecho</b> "
                    "<span style='color:#57606a'>(Selecione o elemento que servirá de cortador; "
                    "o alvo pode receber outros cortes; Esc encerra)</span>"
                )
                self.scene.plotter.setFocus()
                return
            target = self._detail_subtraction_target
            if target is None:
                self._command_mode = "detail_subtraction_target_selection"
                self.clear_selection()
                return
            if target == (kind, name):
                self.history.append(
                    "> <b>Subtrair trecho</b> "
                    "<span style='color:#8c959f'>(Escolha um elemento cortador diferente do alvo)</span>"
                )
                self.clear_selection()
                return
            try:
                self.model_service.add_detail_subtraction(*target, kind, name)
            except ValueError as error:
                self.history.append(
                    f"> <b>Subtrair trecho</b> "
                    f"<span style='color:#8c959f'>({escape(str(error))})</span>"
                )
                self.clear_selection()
                return
            self.refresh_scene()
            self.clear_selection()
            if (*target, kind, name) in self.scene._detail_subtraction_failures:
                target_element = (
                    self.model.bars[target[1]] if target[0] == "bar"
                    else self.model.plates[target[1]]
                )
                self.model.update_detail_subtractions(
                    *target,
                    tuple(
                        reference for reference in target_element.detail_subtractions
                        if reference != (kind, name)
                    ),
                )
                self.refresh_scene()
                self.history.append(
                    "> <b>Subtrair trecho</b> "
                    "<span style='color:#8c959f'>(Não foi possível gerar um corte válido; "
                    "a geometria original foi preservada)</span>"
                )
                self.scene.plotter.setFocus()
                return
            self.history.append(
                "> <b>Subtrair trecho</b> <span style='color:#57606a'>"
                f"(Corte de {escape(name)} aplicado em {escape(target[1])}; "
                "selecione outro cortador ou pressione Esc)</span>"
            )
            self.scene.plotter.setFocus()
            return
        self.axes_panel.hide()
        self.reference_panel.hide()
        self.selected = kind, name
        self.selected_elements = [(kind, name)]
        if self._command_mode == "connect_member_ends_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra)</span>"
                )
                self.clear_selection()
                return
            if self._connect_member_ends_first_bar is None:
                self._connect_member_ends_first_bar = name
                self.clear_selection()
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#57606a'>(Selecione a segunda barra ou grupo ligado ao primeiro; Esc cancela)</span>"
                )
                self.scene.plotter.setFocus()
                return
            first_names = set(self._detailing_group_member_names(self._connect_member_ends_first_bar))
            second_names = set(self._detailing_group_member_names(name))
            if first_names.intersection(second_names):
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#8c959f'>(Selecione outra barra ou grupo)</span>"
                )
                self.clear_selection()
                return
            first_name = self._connect_member_ends_first_bar
            first_group = self._detailing_group_member_names(first_name)
            second_group = self._detailing_group_member_names(name)
            first_outer_faces = group_endpoint_faces(self.model, first_group).values()
            second_outer_faces = group_endpoint_faces(self.model, second_group).values()
            first_outer_nodes = {
                (member, self.model.bars[member].start_node if index == 0
                 else self.model.bars[member].end_node)
                for member, index in first_outer_faces
            }
            second_outer_nodes = {
                (member, self.model.bars[member].start_node if index == 0
                 else self.model.bars[member].end_node)
                for member, index in second_outer_faces
            }
            connected_pairs = []
            for first_member in first_group:
                first_bar = self.model.bars[first_member]
                for second_member in second_group:
                    second_bar = self.model.bars[second_member]
                    shared = set((first_bar.start_node, first_bar.end_node)).intersection(
                        (second_bar.start_node, second_bar.end_node)
                    )
                    if len(shared) != 1:
                        continue
                    shared_node = next(iter(shared))
                    if (
                        (first_member, shared_node) in first_outer_nodes
                        and (second_member, shared_node) in second_outer_nodes
                    ):
                        connected_pairs.append((first_member, second_member))
            if len(connected_pairs) != 1:
                self.history.append(
                    "> <b>Conectar extremidades</b> "
                    "<span style='color:#8c959f'>(Os elementos devem compartilhar uma única extremidade de conexão)</span>"
                )
                self.clear_selection()
                return
            if not self._connect_member_end_faces(*connected_pairs[0]):
                self.clear_selection()
            return
        if self._command_mode == "endpoint_alignment_bar_selection":
            if kind not in {"bar", "plate"}:
                self.history.append(
                    "> <b>Alinhar extremidade</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra ou placa)</span>"
                )
                self.clear_selection()
                return
            self._endpoint_alignment_source = (kind, name)
            self._command_mode = "endpoint_alignment_face_selection"
            self.clear_selection()
            self.scene.set_endpoint_alignment_target(name)
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#57606a'>(Selecione uma face de uma barra ou outra placa; Esc cancela)</span>"
            )
            self.scene.plotter.setFocus()
            return
        if self._command_mode == "verification_ungroup_selection":
            if kind != "bar":
                self.history.append("> <b>Desagrupar barras</b> <span style='color:#8c959f'>(Selecione uma barra que pertença a um grupo)</span>")
                return
            try:
                group = self.model.ungroup_verification_elements(name)
            except ValueError as error:
                self.history.append(f"> <b>Desagrupar barras</b> <span style='color:#8c959f'>({escape(str(error))})</span>")
                return
            self._command_mode = None
            self.history.append(
                "> <b>Desagrupar barras</b> <span style='color:#57606a'>"
                f"({len(group['members'])} barras desagrupadas)</span>"
            )
            self.clear_selection()
            self.refresh_scene()
            return
        if self._command_mode in {"scene_hide_selection", "scene_reveal_selection"}:
            return
        if self._command_mode == "action_selection":
            self._apply_pending_action(kind, name)
            self.clear_selection()
            return
        if self._command_mode == "verification_group_selection":
            self._selection_changed(self.scene._selected_elements)
            return
        if self._command_mode == "split_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Dividir barra</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra, não um nó ou uma barra rígida)</span>"
                )
            else:
                self._command_mode = None
                self.split_member_dialog.open_for_member(name)
                return
        elif self._command_mode == "reverse_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Inverter barra</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra, não um nó ou barra rígida)</span>"
                )
            else:
                self._reverse_member(name)
        elif self._command_mode == "join_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Unir barras</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra, não um nó ou barra rígida)</span>"
                )
            elif self._join_member_first is None:
                self._join_member_first = name
                self.history.append(
                    "> <b>Unir barras</b> "
                    "<span style='color:#57606a'>(Selecione a segunda barra)</span>"
                )
            elif name == self._join_member_first:
                self.history.append(
                    "> <b>Unir barras</b> "
                    "<span style='color:#8c959f'>(Selecione uma segunda barra diferente)</span>"
                )
            else:
                self._join_members(self._join_member_first, name)
        elif self._command_mode == "copy_elements_selection":
            self._selection_changed(((kind, name),))
            return
        elif self._command_mode == "copy_member_properties_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra, não um nó ou barra rígida)</span>"
                )
            elif self._copy_properties_reference is None:
                self._copy_properties_reference = name
                self.clear_selection()
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#57606a'>(Selecione um destino ou use Ctrl e ENTER para vários destinos)</span>"
                )
            elif name == self._copy_properties_reference:
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra de destino diferente)</span>"
                )
            else:
                self._copy_member_properties(self._copy_properties_reference, name)
                self.clear_selection()
        if self.selected is not None and self._command_mode != "split_member_selection":
            if kind == "bar" and self.palette.active_group in {"Memorial", "Detalhamento"}:
                group = self.model.verification_group_for(name)
                if group is not None:
                    self.selected_elements = [("bar", member) for member in group["members"]]
                    self.scene.set_selection_highlight(self.selected_elements)
            self.refresh_selected_property_panel(self.palette.active_group)

    def _selection_changed(self, elements: tuple[tuple[str, str], ...]) -> None:
        if self.palette.active_group == "Análise":
            self.clear_selection()
            return
        if self._command_mode == "plate_selection":
            for kind, name in elements:
                if self._command_mode == "plate_selection":
                    self._plate_add_selection(kind, name)
            return
        if self.palette.active_group == "Detalhamento":
            expanded = list(elements)
            seen = set(expanded)
            for kind, member_name in elements:
                if kind != "bar":
                    continue
                group = self.model.verification_group_for(member_name)
                if group is None:
                    continue
                for group_member in group["members"]:
                    target = ("bar", group_member)
                    if target not in seen:
                        expanded.append(target)
                        seen.add(target)
            elements = tuple(expanded)
        if self._command_mode in {"scene_hide_selection", "scene_reveal_selection"}:
            self.selected_elements = [
                target for target in elements if target[0] in {"bar", "rigid_bar"}
            ]
            self.selected = self.selected_elements[-1] if self.selected_elements else None
            return
        if self._command_mode in {
            "copy_elements_selection", "copy_member_properties_selection", "split_member_selection",
            "reverse_member_selection", "join_member_selection", "action_selection", "verification_group_selection",
            "verification_ungroup_selection",
        }:
            kinds = {"node", "bar", "rigid_bar"} if self._command_mode == "copy_elements_selection" else {"bar"}
            if self._command_mode == "action_selection" and self._pending_action_launch is not None:
                kinds = {self._pending_action_launch[0]}
            targets = tuple(target for target in elements if target[0] in kinds)
            self.selected_elements = list(targets)
            self.selected = targets[-1] if targets else None
            if self._command_mode == "copy_elements_selection":
                self._copy_elements_selection = list(targets)
            self.scene.set_selection_highlight(targets)
            self.properties.hide()
            self.history.append(
                "> <span style='color:#57606a'>"
                f"({len(targets)} elemento(s) selecionado(s); pressione ENTER para confirmar)</span>"
            )
            return
        if self._command_mode is not None:
            return
        self.selected_elements = list(elements)
        self.selected = elements[-1] if elements else None
        if self.selected is None:
            self.clear_selection()
        else:
            self.axes_panel.hide()
            self.reference_panel.hide()
            self.refresh_selected_property_panel(self.palette.active_group)

    def refresh_selected_property_panel(self, section: str | None) -> None:
        """Rebuild the open inspector when the work section changes."""
        active_section = section or "Geometria"
        if active_section == "Análise":
            self.clear_selection()
            return
        if active_section != "Geometria" and hasattr(self, "section_panel") and self.section_panel.isVisible():
            self.close_section_panel()
        if active_section != "Geometria" and hasattr(self, "displacement_panel") and self.displacement_panel.isVisible():
            self.close_displacement_panel()
        if active_section != "Memorial" and hasattr(self, "calculation_properties_panel"):
            self.close_calculation_properties_panel(self.properties._calculation_properties_button)
        if self.selected is not None and hasattr(self, "properties"):
            self.properties.show_for(
                *self.selected, active_section,
                selection=self.selected_elements or [self.selected],
            )
            if active_section == "Geometria" and self.selected[0] == "bar":
                member_name = self.selected[1]
                if self.section_panel.isVisible():
                    family = self.section_panel._section_family
                    names = self.properties._selected_names("bar")
                    if names and all(self.model.bars[name].section == family for name in names):
                        self.section_panel.configure_for(member_name, family)
                        self.properties._section_settings_button.setChecked(True)
                    else:
                        self.close_section_panel()
                if self.displacement_panel.isVisible():
                    self.displacement_panel.configure_for(member_name)
                    self.properties._displacement_settings_button.setChecked(True)
            elif active_section == "Memorial" and self.selected[0] == "bar":
                if self.calculation_properties_panel.isVisible():
                    names = self.properties._selected_names("bar")
                    if names:
                        self.calculation_properties_panel.configure_for(names)
                        self.properties._calculation_properties_button.setChecked(True)
                    else:
                        self.close_calculation_properties_panel()
            elif active_section == "Detalhamento" and self.selected[0] == "plate":
                if self.displacement_panel.isVisible():
                    self.displacement_panel.configure_for_plate(self.selected[1])
                    self.properties._displacement_settings_button.setChecked(True)
            elif active_section == "Geometria":
                self.close_section_panel()
                self.close_displacement_panel()

    def _empty_scene_clicked(self) -> None:
        if self._command_mode == "plate_selection":
            self.scene.set_selection_highlight(self._plate_selection)
            return
        self.clear_selection()

    def clear_selection(self) -> None:
        self.selected = None
        self.selected_elements = []
        self.close_subtractions_panel()
        if self.scene._selected_elements:
            self.scene.set_selection_highlight(())
        self.properties.hide()
        self.section_panel.hide()
        self.displacement_panel.hide()
        self.calculation_properties_panel.hide()
        self.axes_panel.hide()
        self.reference_panel.hide()
        if self._command_mode == "copy_elements_selection":
            self._copy_elements_selection = []

    def delete_selected(self) -> None:
        """Delete selected elements, removing members before their endpoint nodes."""
        focus = QApplication.focusWidget()
        if (
            self._detailing_project_mode
            and self.project_sheet_workspace.delete_selected_dimension()
        ):
            return
        if isinstance(focus, (QLineEdit, QComboBox, QAbstractSpinBox)):
            return
        if self._detailing_project_mode:
            if self.project_sheet_workspace.delete_selected_identification():
                return
            index = self.project_sheet_workspace._selected_view_index
            if index is not None:
                self.project_sheets_palette.remove_view_from_active_sheet(index)
            return
        if self.selected is None:
            return
        targets = self.selected_elements or [self.selected]
        ordered = sorted(targets, key=lambda item: item[0] == "node")
        for kind, name in ordered:
            if kind == "node" and any(
                member.start_node == name or member.end_node == name
                for member in self.model.bars.values()
            ):
                continue
            if kind == "node" and any(
                rigid.start_node == name or rigid.end_node == name
                for rigid in self.model.rigid_bars.values()
            ):
                continue
            try:
                if kind == "node":
                    self.model_service.remove_node(name)
                elif kind == "bar":
                    self.model_service.remove_member(name)
                elif kind == "rigid_bar":
                    self.model_service.remove_rigid_bar(name)
                elif kind == "plate":
                    self.model.remove_plate(name)
                else:
                    continue
            except ValueError as error:
                self.show_error(str(error))
                continue
            if kind == "plate":
                self.scene.render_model(self.model)
            else:
                self.scene.remove_element(kind, name)
        self.clear_selection()



    def new_model(self) -> None:
        if not self._confirm_pending_changes():
            return
        self._reset_model_state()
        self.show_editor()

    def close_project(self) -> None:
        """Fecha o modelo atual e retorna à Home, mantendo a aplicação aberta."""
        if not self._confirm_pending_changes():
            return
        self._reset_model_state()
        self.show_home()

    def _reset_model_state(self) -> None:
        self._restore_plate_snap()
        self._plate_selection = []
        self._plate_segments = []
        self._plate_manual_segments = []
        self._plate_manual_start = None
        self.member_placement_editor.reset()
        self.reference_panel.hide()
        self.split_member_dialog.hide()
        self.axes_panel.discard()
        self.model.clear()
        self.scene.set_scene_selection_mode(None)
        self.top_icon_palette.reload_scene_views()
        self.section_profiles.clear()
        self.section_geometry.clear()
        self.command_session.cancel()
        self._command_mode = None
        self._member_placement_start = None
        self._join_member_first = None
        self._copy_properties_reference = None
        self._copy_elements_selection = []
        self._copy_elements_reference = None
        self._pending_action_launch = None
        if hasattr(self, "member_property_copy_panel"):
            self.member_property_copy_panel.hide()
        self.scene.set_member_placement_mode(False)
        self.scene.set_selection_highlight(())
        self.clear_selection()
        self.current_path = None
        self._set_model_display_name("Novo modelo")
        self._restore_detailing_state()
        self._import_save_path = None
        self._saved_revision = self.model.revision
        self._saved_view_revision = self.model.view_revision
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.refresh_scene(fit_camera=True)

    def save_model(self) -> None:
        if self.current_path is None:
            self.save_model_as()
            return
        self._save_model_to(self.current_path)

    def save_model_as(self) -> None:
        """Escolhe um novo caminho e salva o modelo nesse arquivo."""
        suggested_name = (
            str(self.current_path) if self.current_path else
            str(self._import_save_path) if self._import_save_path else "modelo.osa"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar modelo como", suggested_name, self._project_file_filter,
        )
        if not path:
            return
        selected_path = Path(path)
        if selected_path.suffix.casefold() != ".osa":
            selected_path = selected_path.with_suffix(".osa")
        self._save_model_to(selected_path)

    def export_model_dxf(self) -> None:
        """Exporta o modelo unifilar para DXF, sem a geometria dos sólidos."""
        if not self.model.bars:
            QMessageBox.information(self, "Modelo sem barras", "O modelo não possui barras para exportar.")
            return
        suggested_name = f"{self.current_path.stem}.dxf" if self.current_path else "modelo.dxf"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar modelo para DXF",
            suggested_name,
            "Desenho DXF (*.dxf)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.casefold() != ".dxf":
            path = path.with_suffix(".dxf")
        try:
            from osa.exporters.model_dxf import export_model_to_dxf

            export_model_to_dxf(path, self.model)
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Falha ao exportar modelo",
                f"Não foi possível salvar o modelo em DXF:\n{error}",
            )
            return
        DetailingExportSuccessDialog(self, "Modelo exportado com sucesso").exec()

    def _save_model_to(self, path: str | Path) -> None:
        try:
            self._store_detailing_state()
            thumbnail = ThumbnailService.generate(self.model)
            self.project_service.save(path, thumbnail=thumbnail)
            self.current_path = Path(path)
            self._set_model_display_name(self.current_path.stem)
            self._saved_revision = self.model.revision
            self._saved_view_revision = self.model.view_revision
            self.home.store.add(self.current_path)
            self.home.refresh()
        except (OSError, ValueError) as error:
            self.show_error(f"Não foi possível salvar o arquivo: {error}")

    def open_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", self._open_file_filter)
        if path:
            self._open_model_path(path)

    def _open_model_path(self, path: str | Path) -> None:
        path = Path(path)
        if path.suffix.casefold() != ".osa":
            self.show_error("Abrir modelo aceita arquivos .osa. Para projetos de outros softwares, use Importar modelo.")
            return
        self._load_model_path(path, importing=False)

    def import_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar modelo", "", self._import_file_filter)
        if path:
            self._import_model_path(path)

    def _import_model_path(self, path: str | Path) -> None:
        path = Path(path)
        if not is_import_path(path):
            self.show_error("Selecione um projeto PRJ .prj/.prj.zip. Para arquivos .osa, use Abrir modelo.")
            return
        self._load_model_path(path, importing=True)

    def _load_model_path(self, path: str | Path, *, importing: bool) -> None:
        if not self._confirm_pending_changes():
            return
        if self._project_load_thread is not None or self._project_loading_path is not None:
            return
        path = Path(path)
        import_options = None
        if importing:
            dialog = PrjImportDialog(path, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            import_options = dialog.options()

        thread = QThread(self)
        worker = ProjectLoadWorker(
            path,
            normalize_member_directions=self._member_direction_normalization_enabled,
            solid_members_visible=self.scene._solid_members_preference,
            solid_positioning_enabled=self.palette.active_group == "Detalhamento",
            reference_plane=self.scene._reference_plane_mode,
            preferred_plane_level=self.scene._reference_plane_z,
            import_options=import_options,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._project_load_succeeded, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._project_load_failed, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(self._project_load_stage, Qt.ConnectionType.QueuedConnection)
        worker.loaded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._project_load_thread_finished)
        self._project_load_thread = thread
        self._project_load_worker = worker
        self._project_loading_path = path
        self._project_loading_importing = importing
        self._project_loading_report = None
        self.centralWidget().setEnabled(False)
        self._project_loading_action_states = [(action, action.isEnabled()) for action in self.actions()]
        for action, _enabled in self._project_loading_action_states:
            action.setEnabled(False)
        operation = "importação" if importing else "abertura"
        self._project_loading_overlay.setWindowTitle(
            "Importando modelo" if importing else "Abrindo modelo"
        )
        self._project_loading_title.setText(
            "Importando modelo..." if importing else "Abrindo modelo…"
        )
        self._project_loading_description.setText(f"Preparando a {operation} do modelo…")
        self._project_loading_overlay.adjustSize()
        self._project_loading_overlay.move(
            self.geometry().center() - self._project_loading_overlay.rect().center()
        )
        self._project_loading_overlay.show()
        self._project_loading_overlay.raise_()
        QTimer.singleShot(0, thread.start)

    @Slot(object, object)
    def _project_load_succeeded(
        self, loaded_model: StructuralModel, prepared_geometry,
    ) -> None:
        path = self._project_loading_path
        if path is None:
            self._project_loading_overlay.hide()
            return
        importing = self._project_loading_importing
        report = self._project_load_worker.report if self._project_load_worker is not None else None
        try:
            self.axes_panel.discard()
            self.reference_panel.hide()
            self.member_placement_editor.reset()
            with self._model_access_lock:
                loaded_model.revision = self.model.revision + 1
                loaded_model.view_revision = self.model.view_revision + 1
                self.model.__dict__.update(loaded_model.__dict__)
            self._restore_detailing_state()
            self.scene.set_scene_selection_mode(None, render=False)
            self.top_icon_palette.reload_scene_views()
            self.section_profiles = {
                name: member.profile for name, member in self.model.bars.items() if member.profile
            }
            self.section_geometry = {
                name: member.geometry_dict() for name, member in self.model.bars.items()
                if member.section_geometry
            }
            self.command_session.cancel()
            self._command_mode = None
            self._member_placement_start = None
            self._join_member_first = None
            self._copy_properties_reference = None
            self._copy_elements_selection = []
            self._copy_elements_reference = None
            self._pending_action_launch = None
            self.split_member_dialog.hide()
            self.member_property_copy_panel.hide()
            self.scene.set_member_placement_mode(False)
            self.scene.set_selection_highlight(())
            self.clear_selection()
            self.current_path = None if importing else path
            if importing:
                original_name = path.name[:-4] if path.name.casefold().endswith(".zip") else path.name
                self._import_save_path = path.with_name(Path(original_name).stem + ".osa")
                self._set_model_display_name(Path(original_name).stem)
            else:
                self._import_save_path = None
                self._set_model_display_name(path.stem)
                self.home.store.add(path)
            self._saved_revision = self.model.revision - 1 if importing else self.model.revision
            self._saved_view_revision = self.model.view_revision
            self.home.refresh()
            self.refresh_action_palette()
            self.refresh_analysis_palette()
            self._project_loading_description.setText("Exibindo a estrutura e os identificadores…")
            self._project_scene_revision = self.model.revision
            self._project_loading_report = report
            self._project_scene_steps = self.scene.render_model_steps(
                self.model, preserve_camera=False, prepared_geometry=prepared_geometry,
            )
            self._project_scene_timer.start()
        except Exception as error:  # noqa: BLE001 - always release the loading UI on setup errors
            self._project_load_failed(str(error))

    @Slot()
    def _advance_project_scene(self) -> None:
        if self._project_scene_steps is None:
            return
        try:
            if self.model.revision != self._project_scene_revision:
                raise RuntimeError("O modelo foi alterado durante sua abertura.")
            next(self._project_scene_steps)
        except StopIteration:
            report = self._project_loading_report
            path = self._project_loading_path
            self.properties.update_delete_button_state()
            self.show_editor()
            self._finish_project_loading()
            if report and path is not None:
                counts = report["counts"]
                self.history.append(
                    "> <b>Importação PRJ</b> "
                    f"{escape(path.name)} — {counts['nodes']} nós, "
                    f"{counts['members']} barras, {counts['rigid_links']} ligações rígidas. "
                    "Salvar cria um modelo .osa."
                )
                ImportReportDialog(report, self).exec()
        except Exception as error:  # noqa: BLE001 - recover the UI after a failed scene install
            self._project_load_failed(str(error))

    def _finish_project_loading(self) -> None:
        self._project_scene_timer.stop()
        self._project_scene_steps = None
        self._project_scene_revision = None
        self._project_loading_overlay.hide()
        self._project_loading_path = None
        self._project_loading_importing = False
        self._project_loading_report = None
        self.centralWidget().setEnabled(True)
        for action, enabled in self._project_loading_action_states:
            action.setEnabled(enabled)
        self._project_loading_action_states.clear()

    @Slot(str)
    def _project_load_stage(self, message: str) -> None:
        self._project_loading_description.setText(message)

    @Slot(str)
    def _project_load_failed(self, message: str) -> None:
        operation = "importar" if self._project_loading_importing else "abrir"
        self._finish_project_loading()
        self.show_error(f"Não foi possível {operation} o modelo: {message}")

    @Slot()
    def _project_load_thread_finished(self) -> None:
        thread = self._project_load_thread
        self._project_load_worker = None
        self._project_load_thread = None
        if thread is not None:
            thread.deleteLater()

    def _create_project_loading_overlay(self) -> None:
        overlay = _ProjectLoadingDialog(self)
        overlay.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        overlay.setModal(True)
        overlay.setWindowTitle("Abrindo modelo")
        overlay.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
        )
        overlay.setObjectName("projectLoadingOverlay")
        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QLabel("Abrindo modelo…", overlay)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 17px; font-weight: 600; color: #24292f; border: 0;")
        self._project_loading_title = title
        description = QLabel("Aguarde enquanto os dados são carregados.", overlay)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setStyleSheet("font-size: 13px; color: #57606a; border: 0;")
        description.setWordWrap(True)
        self._project_loading_description = description
        progress = LoadingIndicator(overlay)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(progress)
        overlay.setFixedWidth(400)
        overlay.hide()
        self._project_loading_overlay = overlay

    def _has_unsaved_changes(self) -> bool:
        return (
            self.model.revision != self._saved_revision
            or self.model.view_revision != self._saved_view_revision
        )

    def _confirm_pending_changes(self) -> bool:
        """Pergunta como tratar alterações antes de substituir ou fechar o modelo."""
        if not self._has_unsaved_changes():
            return True

        dialog = UnsavedChangesDialog(self)
        dialog.exec()

        if dialog.choice == UnsavedChangesDialog.SAVE:
            self.save_model()
            return not self._has_unsaved_changes()
        return dialog.choice == UnsavedChangesDialog.DISCARD

    def closeEvent(self, event) -> None:
        if self._project_loading_path is not None or self._project_load_thread is not None:
            event.ignore()
            return
        if self._confirm_pending_changes():
            self._mcp_dispatcher.suspend()
            self._mcp_server.stop()
            event.accept()
        else:
            event.ignore()

    def refresh_scene(self, *, fit_camera: bool = False, prepared_geometry=None) -> None:
        with self._model_access_lock:
            if fit_camera:
                self.scene.render_model(
                    self.model, preserve_camera=False, prepared_geometry=prepared_geometry,
                )
            else:
                self.scene.refresh_model_changes(self.model)
        if self._detail_subtraction_visible_refs:
            self.scene.set_detail_subtraction_previews(self._detail_subtraction_visible_refs)
        self.properties.update_delete_button_state()

    def show_home(self) -> None:
        """Exibe a tela inicial sem deixar controles do editor sobrepostos."""
        if self._detailing_project_mode:
            self.detailing_mode_palette.set_detailing_visible(False)
        self.member_placement_editor.hide()
        self.reference_panel.hide()
        self.view_stack.setCurrentWidget(self.home)
        self.title_bar.set_project_actions_enabled(False)
        self.home.refresh()
        self.top_icon_palette.scene_palette.hide()
        for widget in (
            self.palette,
            self.top_icon_palette,
            self.verification_top_palette,
            self.action_top_palette,
            self.analysis_top_palette,
            self.detailing_top_palette,
            self.detailing_mode_palette,
            self.project_sheets_palette,
            self.navigation_button,
            self.sloped_plane_button,
            self.sloped_plane_right_button,
            self.previous_plane_button,
            self.plane_change_button,
            self.next_plane_button,
            self.properties,
            self.displacement_panel,
            self.calculation_properties_panel,
            self.split_member_dialog,
            self.processing_panel,
            self.verification_panel,
            self.command_bar,
            self.history,
        ):
            widget.hide()

    def show_editor(self) -> None:
        """Retorna à cena 3D e restaura seus controles contextuais."""
        self.view_stack.setCurrentWidget(
            self.project_sheet_workspace if self._detailing_project_mode else self.scene
        )
        self.title_bar.set_project_actions_enabled(True)
        for widget in (
            self.palette,
            self.top_icon_palette,
            self.navigation_button,
            self.sloped_plane_button,
            self.sloped_plane_right_button,
            self.previous_plane_button,
            self.plane_change_button,
            self.next_plane_button,
            self.command_bar,
        ):
            widget.show()
        if self._detailing_project_mode:
            for control in (
                self.navigation_button,
                self.sloped_plane_button,
                self.sloped_plane_right_button,
                self.previous_plane_button,
                self.plane_change_button,
                self.next_plane_button,
            ):
                control.hide()
        self.top_icon_palette.set_geometry_visible(self.palette.active_group == "Geometria")
        detailing_active = self.palette.active_group == "Detalhamento"
        self.detailing_top_palette.set_detailing_visible(
            detailing_active and not self._detailing_project_mode
        )
        self.detailing_mode_palette.set_detailing_visible(detailing_active)
        if self._detailing_project_mode:
            self.project_sheets_palette.set_project_mode(True)
        else:
            self.project_sheets_palette.set_project_mode(False)
        self.palette.reposition()
        self.top_icon_palette.reposition()
        self.command_bar.reposition()
        self._reposition_navigation_button()

    def _open_recent_project(self, path: str) -> None:
        self._open_model_path(path)

    def open_manual(self) -> None:
        """Abre a página pública do projeto, que concentra o manual atual."""
        QDesktopServices.openUrl(QUrl(PROJECT_MANUAL_URL))

    def _refresh_after_mcp_change(self) -> None:
        """Atualiza a interface após uma operação recebida pelo MCP local."""
        self.normalize_member_directions_if_enabled()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.reference_panel.reload()
        self.refresh_scene()

    def _refresh_after_mcp_scene_views_change(self) -> None:
        """Atualiza o seletor e a geometria após operações MCP de vistas."""
        self.top_icon_palette.reload_scene_views()
        self.refresh_scene()

    def _apply_mcp_view_change(self, option: str, visible: bool) -> None:
        setters = {
            "grid_visible": self.scene.set_grid_visible,
            "reference_axes_visible": self.scene.set_reference_axes_visible,
            "local_axes_visible": self.scene.set_local_axes_visible,
            "nodes_visible": self.scene.set_nodes_visible,
            "solid_members_visible": self.scene.set_solid_members_visible,
            "member_releases_visible": self.scene.set_member_releases_visible,
            "semirigid_links_visible": self.scene.set_semirigid_links_visible,
            "node_supports_visible": self.scene.set_node_supports_visible,
        }
        if option in setters:
            setters[option](visible)
        elif option == "node_labels_visible":
            self.scene.set_labels_visible("node", visible)
        elif option == "member_labels_visible":
            self.scene.set_labels_visible("bar", visible)
        elif option == "plate_labels_visible":
            self.scene.set_labels_visible("plate", visible)
        elif option in {
            "node_forces_visible", "node_moments_visible",
            "member_forces_visible", "member_moments_visible",
            "plate_pressures_visible",
        }:
            self.scene.set_action_visibility(option.removesuffix("_visible"), visible)
        else:
            raise ValueError(f"Opção visual desconhecida: {option}")
        self.top_icon_palette.set_view_option(option, visible)
        self.action_top_palette.set_view_option(option, visible)

    def refresh_action_palette(self) -> None:
        """Atualiza o seletor a partir do grupo de ações atualmente ativo."""
        group = self.action_service.selected_group()
        names = tuple(action.name for action in group.actions) if group else ()
        previous = self.selected_action_name
        self.action_top_palette.set_actions(
            names,
            previous,
            self.action_service.selfweight_load_cases(),
        )
        self.selected_action_name = self.action_top_palette.action_selector.currentText() or None
        self.command_session.set_active_load_case(self.selected_action_name)
        self.action_top_palette.set_selfweight_active(
            self.action_service.has_selfweight(self.selected_action_name or "")
        )
        self.scene.set_active_load_case(self.selected_action_name)
        if hasattr(self, "properties"):
            self.refresh_selected_property_panel(self.palette.active_group)

    def prepare_analysis_palette(self) -> None:
        """Ensure default combinations exist before exposing the analysis controls."""
        self.action_service.ensure_default_combinations()
        self.refresh_analysis_palette()

    def refresh_analysis_palette(self) -> None:
        names = tuple(result.load_reference for result in ResultService(self.model).current())
        self.verification_top_palette.verify_button.setEnabled(bool(names))
        if not names:
            # Editing the model invalidates every analysis result.  Clear the
            # remembered result view as well, otherwise reopening the Analysis
            # group can request a stale deformation diagram with no result to
            # render.
            self.selected_analysis_combination = None
            self.selected_analysis_diagram = "Normal"
            self.analysis_top_palette.reset_result_view()
        previous = self.selected_analysis_combination
        self.analysis_top_palette.set_combinations(names, previous)
        self.analysis_top_palette.set_analysis_ready(bool(names))
        self.selected_analysis_combination = self.analysis_top_palette.combination_selector.currentText() or None
        self._sync_analysis_result()

    def _select_analysis_combination(self, name: str) -> None:
        self.selected_analysis_combination = name or None
        self._sync_analysis_result()
        self.refresh_selected_property_panel(self.palette.active_group)

    def _select_analysis_diagram(self, name: str) -> None:
        self.selected_analysis_diagram = name or "Normal"
        self._sync_analysis_result()

    def _sync_analysis_result(self) -> None:
        if hasattr(self, "scene"):
            self.scene.set_analysis_result(self.selected_analysis_combination, self.selected_analysis_diagram)

    def _show_analysis_point_result(self, kind: str, name: str, point: object) -> None:
        """Show the active analysis value at a clicked model location."""
        point = np.asarray(point, dtype=float).reshape(3)
        combination = self.selected_analysis_combination
        result = next((item for item in self.model.analysis_results
                       if item.load_reference == combination
                       and item.model_revision == self.model.revision), None)
        if result is None:
            self.scene.hide_analysis_point_result()
            return
        diagram = self.selected_analysis_diagram
        renderer = self.scene._result_renderer
        unit = self.scene._result_unit(diagram)
        detail = " · ".join(
            f"{axis}: {coordinate:.3f}".replace(".", ",") + " m"
            for axis, coordinate in zip("XYZ", point)
        )
        raw_value: float | None = None
        display_value = "Sem resultados neste ponto"
        if kind == "bar":
            member = self.model.bars.get(name)
            member_result = result.member_results.get(name)
            if member is not None and member_result:
                first, last = self.model.nodes[member.start_node], self.model.nodes[member.end_node]
                start = np.asarray((first.x, first.y, first.z), dtype=float)
                end = np.asarray((last.x, last.y, last.z), dtype=float)
                length = float(member_result.get("length", np.linalg.norm(end - start)))
                samples = member_result.get("samples", ())
                if diagram.startswith("Deformação") and len(samples) >= 2:
                    components = diagram.removeprefix("Deformação ") or "XYZ"
                    basis = LocalAxesRenderer.basis(first, last, member.rotation)
                    scale = max(1.0, min(100.0, float(self.scene._analysis_deformation_scale)))
                    if basis is not None:
                        curve = np.asarray([
                            start + basis[0] * float(sample.get("x", 0.0)) + np.asarray((
                                float(sample.get("deflection_x", 0.0)) if "X" in components else 0.0,
                                float(sample.get("deflection_y", 0.0)) if "Y" in components else 0.0,
                                float(sample.get("deflection_z", 0.0)) if "Z" in components else 0.0,
                            )) * scale for sample in samples
                        ], dtype=float)
                        distances = []
                        positions = []
                        for index, (a, b) in enumerate(zip(curve, curve[1:])):
                            delta = b - a
                            denominator = float(np.dot(delta, delta))
                            fraction = 0.0 if denominator <= 1e-12 else float(np.clip(
                                np.dot(point - a, delta) / denominator, 0.0, 1.0,
                            ))
                            distances.append(float(np.linalg.norm(point - (a + fraction * delta))))
                            x0 = float(samples[index].get("x", 0.0))
                            x1 = float(samples[index + 1].get("x", x0))
                            positions.append(x0 + fraction * (x1 - x0))
                        position = positions[int(np.argmin(distances))]
                    else:
                        position = 0.0
                else:
                    fraction = float(np.clip(np.dot(point - start, end - start) /
                                             max(float(np.dot(end - start, end - start)), 1e-12), 0.0, 1.0))
                    position = fraction * length
                if diagram.startswith("Deformação"):
                    components = diagram.removeprefix("Deformação ") or "XYZ"
                    key = {"X": "deflection_x", "Y": "deflection_y", "Z": "deflection_z"}.get(components)
                    if samples:
                        if key:
                            raw_value = self._interpolate_member_samples(samples, position, key) * 1000.0
                        else:
                            vector = np.asarray([self._interpolate_member_samples(samples, position, f"deflection_{axis}")
                                                 for axis in "xyz"], dtype=float)
                            raw_value = float(np.linalg.norm(vector) * 1000.0)
                elif diagram in renderer.DIAGRAMS and samples:
                    result_key, _axis, _result_unit, display_sign, _geometry_sign = renderer.DIAGRAMS[diagram]
                    raw_value = self._interpolate_member_samples(samples, position, result_key) * display_sign
                if diagram in renderer.DIAGRAMS:
                    unit = renderer.DIAGRAMS[diagram][2]
        elif kind == "node":
            node_values = result.node_results.get(name, {})
            if diagram == renderer.REACTION_DIAGRAM:
                components = [(key.removeprefix("RXN_"), float(node_values.get(key, 0.0)))
                              for key in (*renderer._REACTION_FORCE_KEYS, *renderer._REACTION_MOMENT_KEYS)]
                forces = " · ".join(
                    f"{label}: {renderer._format_value(value, 'kN')}"
                    for label, value in components[:3]
                )
                moments = " · ".join(
                    f"{label}: {renderer._format_value(value, 'kN·m')}"
                    for label, value in components[3:]
                )
                display_value = f"Reações de apoio\n{forces}\n{moments}"
            elif diagram.startswith("Deformação"):
                components = diagram.removeprefix("Deformação ") or "XYZ"
                raw_value = renderer._deformation_display_value(node_values, components)
            elif diagram in renderer.DIAGRAMS:
                result_key, _axis, _result_unit, display_sign, _geometry_sign = renderer.DIAGRAMS[diagram]
                connected_values = []
                for bar_name, bar in self.model.bars.items():
                    if name not in {bar.start_node, bar.end_node}:
                        continue
                    member_result = result.member_results.get(bar_name, {})
                    samples = member_result.get("samples", ())
                    if not samples:
                        continue
                    sample = samples[0] if bar.start_node == name else samples[-1]
                    value = float(sample.get(result_key, 0.0)) * display_sign
                    connected_values.append(f"{bar_name}: {renderer._format_value(value, renderer.DIAGRAMS[diagram][2])}")
                if connected_values:
                    display_value = "\n".join(connected_values)
        elif kind == "plate":
            plate_result = result.plate_results.get(name)
            if plate_result:
                raw_value = self._sample_analysis_plate(plate_result, diagram, point)
        if raw_value is not None:
            display_value = renderer._format_value(raw_value, unit)
        no_reaction_result = (
            diagram == renderer.REACTION_DIAGRAM
            and kind in {"bar", "plate", "rigid_bar"}
        )
        if no_reaction_result:
            display_value = "Reações de apoio:\nSem resultados neste ponto"
        elif not (kind == "node" and diagram == renderer.REACTION_DIAGRAM):
            display_value = f"{diagram}: {display_value}"
        self.scene.show_analysis_point_result(
            kind, name, point, detail, display_value,
            wide=kind == "node" and diagram == renderer.REACTION_DIAGRAM,
        )

    @staticmethod
    def _interpolate_member_samples(samples, position: float, key: str) -> float:
        rows = [(float(sample.get("x", 0.0)), float(sample.get(key, 0.0))) for sample in samples]
        if not rows:
            return 0.0
        rows.sort(key=lambda row: row[0])
        positions = [row[0] for row in rows]
        index = int(np.searchsorted(positions, position, side="right"))
        if index <= 0:
            return rows[0][1]
        if index >= len(rows):
            return rows[-1][1]
        x0, y0 = rows[index - 1]
        x1, y1 = rows[index]
        fraction = 0.0 if abs(x1 - x0) <= 1e-12 else (position - x0) / (x1 - x0)
        return y0 + fraction * (y1 - y0)

    def _sample_analysis_plate(self, plate_result, diagram: str, point: np.ndarray) -> float | None:
        renderer = self.scene._result_renderer
        plate_nodes = plate_result.get("nodes", {})
        elements = plate_result.get("elements", {})
        if diagram.startswith("Deformação"):
            components = diagram.removeprefix("Deformação ") or "XYZ"
            nodal_values = {node: renderer._deformation_display_value(values, components)
                            for node, values in plate_nodes.items()}
            element_values = {}
        else:
            element_values = renderer._plate_element_values(plate_result, diagram)
            nodal_values = {}
            if self.scene._plate_result_display_mode in {"nos_media", "nos_media_macro"}:
                sums: dict[str, float] = {}
                counts: dict[str, int] = {}
                active_result = next((item for item in self.model.analysis_results
                                      if item.load_reference == self.selected_analysis_combination
                                      and item.model_revision == self.model.revision), None)
                sources = (
                    active_result.plate_results.values()
                    if self.scene._plate_result_display_mode == "nos_media" and active_result
                    else (plate_result,)
                )
                for source in sources:
                    source_values = renderer._plate_element_values(source, diagram)
                    for element_name, (_center, corners) in source_values.items():
                        for node_name, value in zip(source.get("elements", {}).get(element_name, {}).get("nodes", ()), corners):
                            sums[node_name] = sums.get(node_name, 0.0) + value
                            counts[node_name] = counts.get(node_name, 0) + 1
                nodal_values = {node: sums[node] / counts[node] for node in sums if counts[node]}
        for element_name, element in elements.items():
            node_names = element.get("nodes", ())
            if len(node_names) != 4 or any(node not in plate_nodes for node in node_names):
                continue
            corners = np.asarray([plate_nodes[node].get("coordinates", ()) for node in node_names], dtype=float)
            if corners.shape != (4, 3):
                continue
            if diagram.startswith("Deformação"):
                components = diagram.removeprefix("Deformação ") or "XYZ"
                scale = self.scene._analysis_deformation_scale
                corners = corners + np.asarray([
                    [float(plate_nodes[node].get(f"D{axis}", 0.0)) if axis in components else 0.0
                     for axis in "XYZ"] for node in node_names
                ]) * scale
            local = np.asarray(point, dtype=float)
            u = v = 0.5
            for _ in range(12):
                weights = np.asarray(((1-u)*(1-v), u*(1-v), u*v, (1-u)*v))
                current = weights @ corners
                du = (1-v)*(corners[1]-corners[0]) + v*(corners[2]-corners[3])
                dv = (1-u)*(corners[3]-corners[0]) + u*(corners[2]-corners[1])
                jacobian = np.column_stack((du, dv))
                step = np.linalg.lstsq(jacobian, local-current, rcond=None)[0]
                u += float(step[0]); v += float(step[1])
                if np.linalg.norm(step) < 1e-8:
                    break
            weights = np.asarray(((1-u)*(1-v), u*(1-v), u*v, (1-u)*v))
            residual = float(np.linalg.norm(weights @ corners - local))
            if residual > max(0.02, float(np.ptp(corners, axis=0).max()) * 0.03) or not (-0.05 <= u <= 1.05 and -0.05 <= v <= 1.05):
                continue
            if diagram.startswith("Deformação"):
                values = [nodal_values.get(node) for node in node_names]
                return None if any(value is None for value in values) else float(weights @ np.asarray(values))
            if element_name not in element_values:
                return None
            center, corners_value = element_values[element_name]
            if self.scene._plate_result_display_mode == "centros":
                return float(center)
            if self.scene._plate_result_display_mode == "nos_sem_media":
                values = np.asarray(corners_value, dtype=float)
            else:
                values = np.asarray([nodal_values.get(node, corners_value[index])
                                     for index, node in enumerate(node_names)], dtype=float)
            return float(weights @ values)
        return None

    def _apply_mcp_analysis_view(self, combination: str, diagram: str) -> None:
        """Atualiza os seletores e o resultado visual após uma chamada MCP."""
        self.selected_analysis_combination = combination or None
        self.selected_analysis_diagram = diagram or "Normal"
        self.analysis_top_palette.set_combinations(
            tuple(result.load_reference for result in self.model.analysis_results),
            self.selected_analysis_combination,
        )
        self.analysis_top_palette.diagram_selector.blockSignals(True)
        self.analysis_top_palette.diagram_selector.setCurrentText(self.selected_analysis_diagram)
        self.analysis_top_palette.diagram_selector.blockSignals(False)
        self._sync_analysis_result()

    def _select_active_action(self, name: str) -> None:
        self.selected_action_name = name or None
        self.command_session.set_active_load_case(self.selected_action_name)
        self.action_top_palette.set_selfweight_active(
            self.action_service.has_selfweight(self.selected_action_name or "")
        )
        self.scene.set_active_load_case(self.selected_action_name)
        self.refresh_selected_property_panel(self.palette.active_group)

    def refresh_member_axes(self, member_name: str) -> None:
        self.scene.update_member_axes(member_name)

    def refresh_member_rotation(self, member_name: str) -> None:
        self.scene.update_member_rotation(member_name)

    def refresh_member_geometry(self, member_name: str) -> None:
        has_selfweight = any(
            action.target == member_name
            and action.kind == "member_distributed_force_selfweight_Z"
            for action in self.model.actions.values()
        )
        if has_selfweight:
            try:
                weight = self.model_service.member_selfweight(member_name)
            except ValueError:
                pass
            else:
                if self.action_service.update_selfweight_member(member_name, weight):
                    self.refresh_action_palette()
                    self.refresh_scene()
                    return
        self.scene.update_member_geometry(member_name)

    def refresh_member_positioning(self, member_name: str) -> None:
        """Refresh a bar after a detailing-only face or section offset edit."""
        self.scene.update_member_positioning(member_name)

    def refresh_member_color(self, member_name: str) -> None:
        self.scene.update_member_color(member_name)

    def refresh_member_colors(self, member_names: tuple[str, ...] | list[str]) -> None:
        self.scene.update_member_colors(member_names)

    def refresh_member_releases(self, member_name: str) -> None:
        self.scene.update_member_releases(member_name)

    def refresh_node_visual(self, node_name: str) -> None:
        self.scene.update_node_visual(node_name)

    def refresh_node(self, node_name: str) -> None:
        self.scene.update_node(node_name)

    def refresh_rigid_bar_name(self, old_name: str, new_name: str) -> None:
        self.scene.update_rigid_bar_name(old_name, new_name)

    def show_error(self, message: str) -> None:
        dialog = ErrorDialog(message, self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
