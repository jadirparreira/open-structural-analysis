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
from osa.sections import section_shape
from osa.services import AnalysisService, ResultService

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
    ProgramSettingsDialog,
    SelfweightDialog,
    SettingsDialog,
    UnsavedChangesDialog,
)
from .displacement_panel import DisplacementPanel
from .group_positioning import group_endpoint_faces
from .home import HomePage
from .loading_indicator import LoadingIndicator
from .mcp_dispatcher import McpQtDispatcher
from .member_placement_panel import MemberPlacementEditor
from .navigation_buttons import LeftArrowButton, RightArrowButton, SlopedPlaneButton
from .palettes import (
    ActionTopPalette,
    AnalysisTopPalette,
    DetailingTopPalette,
    FloatingPalette,
    MemberPropertyCopyPanel,
    PaletteTooltip,
    TopIconPalette,
    VerificationTopPalette,
)
from .project_load_worker import ProjectLoadWorker
from .property_panel import PropertyPanel
from .reference_panel import ReferenceImportDialog, ReferencePanel
from .section_panel import (
    ILaminadoSectionPanel,
    LLaminadoSectionPanel,
    ParametricSectionPanel,
    TLaminadoSectionPanel,
    ULaminadoSectionPanel,
    WLaminadoSectionPanel,
    HPLaminadoSectionPanel,
)
from .split_member_dialog import SplitMemberDialog
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
    _interface_commands = frozenset({
        "bar", "split", "reverse", "join", "rigid", "copy", "cprop", "measure", "axes",
        "nodeforce", "nodemoment", "memberforce", "membermoment", "group", "ungroup",
        "action", "load", "selfweight", "combinations", "analyze", "verify", "grid",
        "configaxes", "nodelabels", "memberlabels", "localaxes", "nodes",
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
        self._saved_revision = self.model.revision
        self._saved_view_revision = self.model.view_revision
        self._command_mode: str | None = None
        self._detailing_views_dialog_open = False
        self._detailing_views_dialog: DetailingViewsDialog | None = None
        self._reference_axis_placement_direction: str | None = None
        self._last_command_callback = None
        self._member_placement_start: tuple[float, float, float] | None = None
        self._member_placement_start_snap_member_name: str | None = None
        self._member_placement_start_snap_target: tuple[str, str] | None = None
        self._endpoint_alignment_source_bar: str | None = None
        self._connect_member_ends_first_bar: str | None = None
        self._join_member_first: str | None = None
        self._copy_properties_reference: str | None = None
        self._copy_elements_selection: list[tuple[str, str]] = []
        self._copy_elements_reference: tuple[float, float, float] | None = None
        self._pending_action_launch: tuple[str, str, dict[str, tuple[float, ...]]] | None = None
        self._member_direction_normalization_enabled = True
        self._program_settings = QSettings("OpenStructuralAnalysis", "OpenStructuralAnalysis")
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
        self.home = HomePage(shell)
        self.view_stack = QStackedWidget(shell)
        self.view_stack.addWidget(self.home)
        self.view_stack.addWidget(self.scene)
        shell_layout.addWidget(self.title_bar)
        shell_layout.addWidget(self.view_stack, 1)
        self.window_frame.body.addWidget(shell)
        self.setCentralWidget(self.window_frame)
        self._create_project_loading_overlay()
        self.selected: tuple[str, str] | None = None
        self.selected_elements: list[tuple[str, str]] = []
        self.scene.element_clicked.connect(self.select_element)
        self.scene.solid_face_clicked.connect(self._align_member_endpoint_to_face)
        self.scene.empty_clicked.connect(self.clear_selection)
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
        self.home.recent_project_requested.connect(self._open_recent_project)
        self.home.manual_requested.connect(self.open_manual)
        self.show_home()

    def process_analysis(self, checked: bool = False) -> None:
        """Run PyNite in the background after the progress card is painted."""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            return
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
        self.processing_panel.succeed(len(self.model.analysis_results))

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

    def open_detailing_views(self) -> None:
        if self._detailing_views_dialog_open:
            return
        self._detailing_views_dialog_open = True
        dialog = None
        cancel_action = getattr(self, "_cancel_placement_action", None)
        cancel_action_was_enabled = cancel_action.isEnabled() if cancel_action is not None else None
        try:
            if cancel_action is not None:
                cancel_action.setEnabled(False)
            dialog = DetailingViewsDialog(self)
            self._detailing_views_dialog = dialog
            dialog._add_plane_requested = False
            dialog.move(self.geometry().center() - dialog.rect().center())
            dialog.exec()
            add_plane_requested = dialog._add_plane_requested
        finally:
            self._detailing_views_dialog_open = False
            self._detailing_views_dialog = None
            if dialog is not None:
                dialog._preview.shutdown()
                dialog.deleteLater()
            if cancel_action is not None:
                cancel_action.setEnabled(cancel_action_was_enabled)
        if add_plane_requested:
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
        """Start the two-step command for aligning a bar end to a connected face."""
        if self._command_mode is not None:
            self.cancel_member_placement()
        self.command_session.cancel()
        self.scene.set_member_placement_mode(False)
        self._endpoint_alignment_source_bar = None
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
            "<span style='color:#57606a'>(Selecione a barra que terá uma extremidade alinhada; Esc cancela)</span>"
        )
        self.scene.plotter.setFocus()

    def _align_member_endpoint_to_face(self, hit: object) -> None:
        """Match a connected bar end face to the clicked solid face plane."""
        if self._command_mode != "endpoint_alignment_face_selection":
            return
        try:
            target_name, _cell_id, face_point, face_normal = hit
            face_point = np.asarray(face_point, dtype=float)
            face_normal = np.asarray(face_normal, dtype=float)
        except (TypeError, ValueError):
            return
        source_name = self._endpoint_alignment_source_bar
        target = self.model.bars.get(target_name)
        if source_name is None or target is None:
            return
        source_names = self._detailing_group_member_names(source_name)
        if target_name in source_names:
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
        target_group_names = self._detailing_group_member_names(target_name)
        target_outer_nodes = {
            (member_name, self.model.bars[member_name].start_node if endpoint_index == 0
             else self.model.bars[member_name].end_node)
            for member_name, endpoint_index in group_endpoint_faces(
                self.model, target_group_names,
            ).values()
        }
        target_endpoints = (target.start_node, target.end_node)
        candidates = []
        for candidate_name in source_names:
            source_candidate = self.model.bars.get(candidate_name)
            if source_candidate is None:
                continue
            endpoints = (source_candidate.start_node, source_candidate.end_node)
            for source_node in endpoints:
                if (candidate_name, source_node) not in outer_nodes:
                    continue
                shared_nodes = set(endpoints).intersection(target_endpoints)
                if (
                    source_node in shared_nodes and len(shared_nodes) == 1
                    and (target_name, source_node) in target_outer_nodes
                ):
                    candidates.append((source_candidate, (source_node, source_node)))
                    continue
                # A rigid bar connects distinct nodes at the ends of two bars.
                for rigid in self.model.rigid_bars.values():
                    if (
                        rigid.start_node == source_node and rigid.end_node in target_endpoints
                        and (target_name, rigid.end_node) in target_outer_nodes
                    ):
                        candidates.append((source_candidate, (source_node, rigid.end_node)))
                    elif (
                        rigid.end_node == source_node and rigid.start_node in target_endpoints
                        and (target_name, rigid.start_node) in target_outer_nodes
                    ):
                        candidates.append((source_candidate, (source_node, rigid.start_node)))
        if len(candidates) != 1:
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(A face deve pertencer a uma barra ligada a uma extremidade externa do grupo)</span>"
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

        # The deformed end face has local normal proportional to
        # (1, tan(alphaY), tan(alphaZ)); use the selected face normal to set
        # both angles, then solve A/B for the plane's position through the hit.
        if normal_x < 0.0:
            face_normal = -face_normal
            normal_x = -normal_x
        alpha_y = math.degrees(math.atan(float(np.dot(face_normal, basis[1])) / normal_x))
        alpha_z = math.degrees(math.atan(float(np.dot(face_normal, basis[2])) / normal_x))
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
        self._endpoint_alignment_source_bar = None
        self.scene.set_endpoint_alignment_target(None)
        self.refresh_member_geometry(source.name)
        self.properties.update_positioning_status(source.name)
        offset_mm = offset * 1000.0
        self.history.append(
            "> <b>Alinhar extremidade</b> "
            f"<span style='color:#57606a'>(Extremidade {endpoint} alinhada; "
            f"{endpoint} = {offset_mm:.2f} mm; αY/αZ = {alpha_y:.2f}°/{alpha_z:.2f}°. "
            "Selecione outra barra para continuar; Esc encerra)</span>"
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
                math.atan(float(np.dot(plane_normal, basis[1])) / normal_x)
            )
            alpha_z = math.degrees(
                math.atan(float(np.dot(plane_normal, basis[2])) / normal_x)
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
            self.refresh_member_geometry(name)
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
        QTimer.singleShot(0, self._finish_detail_plane_placement)

    def _finish_detail_plane_placement(self) -> None:
        dialog = self._detailing_views_dialog
        self._detailing_views_dialog = None
        if dialog is not None:
            dialog.deleteLater()
        self.refresh_scene()
        QTimer.singleShot(0, self.open_detailing_views)

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
                self.refresh_member_geometry(name)
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
        member_name = self.selected[1] if self.selected and self.selected[0] == "bar" else ""
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
        }
        command_label = escape(name.upper())

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
            "endpoint_alignment_bar_selection", "endpoint_alignment_face_selection",
        }:
            self._command_mode = None
            self._endpoint_alignment_source_bar = None
            self.scene.set_endpoint_alignment_target(None)
            self.clear_selection()
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode == "detail_plane_placement":
            self._command_mode = None
            self._detail_plane_points = []
            self.scene.set_detail_plane_point_mode(False)
            self.history.append(
                "> <b>Adicionar plano</b> <span style='color:#8c959f'>(Operação cancelada)</span>"
            )
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
            if kind != "bar":
                self.history.append(
                    "> <b>Alinhar extremidade</b> "
                    "<span style='color:#8c959f'>(Selecione uma barra)</span>"
                )
                self.clear_selection()
                return
            self._endpoint_alignment_source_bar = name
            self._command_mode = "endpoint_alignment_face_selection"
            self.clear_selection()
            self.scene.set_endpoint_alignment_target(name)
            self.history.append(
                "> <b>Alinhar extremidade</b> "
                "<span style='color:#57606a'>(Selecione uma face de uma barra conectada; Esc cancela)</span>"
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
            elif active_section == "Geometria":
                self.close_section_panel()
                self.close_displacement_panel()

    def clear_selection(self) -> None:
        self.selected = None
        self.selected_elements = []
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
        if self.selected is None:
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QComboBox, QAbstractSpinBox)):
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
                else:
                    continue
            except ValueError as error:
                self.show_error(str(error))
                continue
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
        self.scene.set_model_name("Novo modelo")
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
        suggested_name = self.current_path.name if self.current_path else "modelo.osa"
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
            thumbnail = ThumbnailService.generate(self.model)
            self.project_service.save(path, thumbnail=thumbnail)
            self.current_path = Path(path)
            self.scene.set_model_name(self.current_path.stem)
            self._saved_revision = self.model.revision
            self._saved_view_revision = self.model.view_revision
            self.home.store.add(self.current_path)
            self.home.refresh()
        except OSError as error:
            self.show_error(f"Não foi possível salvar o arquivo: {error}")

    def open_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", self._project_file_filter)
        if path:
            self._open_model_path(path)

    def _open_model_path(self, path: str | Path) -> None:
        if self._project_load_thread is not None or self._project_loading_path is not None:
            return
        path = Path(path)
        if path.suffix.casefold() != ".osa":
            self.show_error("Selecione um arquivo de modelo com extensão .osa.")
            return
        thread = QThread(self)
        worker = ProjectLoadWorker(
            path,
            normalize_member_directions=self._member_direction_normalization_enabled,
            solid_members_visible=self.scene._solid_members_visible,
            solid_positioning_enabled=self.palette.active_group == "Detalhamento",
            reference_plane=self.scene._reference_plane_mode,
            preferred_plane_level=self.scene._reference_plane_z,
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
        self.centralWidget().setEnabled(False)
        self._project_loading_action_states = [(action, action.isEnabled()) for action in self.actions()]
        for action, _enabled in self._project_loading_action_states:
            action.setEnabled(False)
        self._project_loading_description.setText("Preparando a abertura do modelo…")
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
        try:
            self.axes_panel.discard()
            self.reference_panel.hide()
            self.member_placement_editor.reset()
            with self._model_access_lock:
                loaded_model.revision = self.model.revision + 1
                loaded_model.view_revision = self.model.view_revision + 1
                self.model.__dict__.update(loaded_model.__dict__)
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
            self.current_path = path
            self.scene.set_model_name(path.stem)
            self._saved_revision = self.model.revision
            self._saved_view_revision = self.model.view_revision
            self.home.store.add(self.current_path)
            self.refresh_action_palette()
            self.refresh_analysis_palette()
            self._project_loading_description.setText("Exibindo a estrutura e os identificadores…")
            self._project_scene_revision = self.model.revision
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
            self.properties.update_delete_button_state()
            self.show_editor()
            self._finish_project_loading()
        except Exception as error:  # noqa: BLE001 - recover the UI after a failed scene install
            self._project_load_failed(str(error))

    def _finish_project_loading(self) -> None:
        self._project_scene_timer.stop()
        self._project_scene_steps = None
        self._project_scene_revision = None
        self._project_loading_overlay.hide()
        self._project_loading_path = None
        self.centralWidget().setEnabled(True)
        for action, enabled in self._project_loading_action_states:
            action.setEnabled(enabled)
        self._project_loading_action_states.clear()

    @Slot(str)
    def _project_load_stage(self, message: str) -> None:
        self._project_loading_description.setText(message)

    @Slot(str)
    def _project_load_failed(self, message: str) -> None:
        self._finish_project_loading()
        self.show_error(f"Não foi possível abrir o modelo: {message}")

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
        self.properties.update_delete_button_state()

    def show_home(self) -> None:
        """Exibe a tela inicial sem deixar controles do editor sobrepostos."""
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
        self.view_stack.setCurrentWidget(self.scene)
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
        self.top_icon_palette.set_geometry_visible(self.palette.active_group == "Geometria")
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
        elif option in {
            "node_forces_visible", "node_moments_visible",
            "member_forces_visible", "member_moments_visible",
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
