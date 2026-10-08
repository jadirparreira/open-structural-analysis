"""Janela principal e composição dos componentes visuais."""
import copy

from PySide6.QtCore import QThread, Signal

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.integrations import LocalMcpIntegration
from osa.mcp import LocalMcpServer, McpApplication
from osa.services import AnalysisService

from .analysis_panel import ProcessingPanel
from .analysis_worker import AnalysisWorker
from .axes_panel import AxesPanel
from .command_bar import CommandBar, CommandHistory
from .common import *
from .dialogs import (
    ActionDialog,
    ActionGroupDialog,
    CombinationsDialog,
    ErrorDialog,
    ProgramSettingsDialog,
    SelfweightDialog,
    SettingsDialog,
    UnsavedChangesDialog,
)
from .displacement_panel import DisplacementPanel
from .navigation_buttons import LeftArrowButton, RightArrowButton, SlopedPlaneButton
from .palettes import (
    ActionTopPalette,
    AnalysisTopPalette,
    FloatingPalette,
    MemberPropertyCopyPanel,
    PaletteTooltip,
    TopIconPalette,
)
from .property_panel import PropertyPanel
from .section_panel import (
    ILaminadoSectionPanel,
    LLaminadoSectionPanel,
    ParametricSectionPanel,
    TLaminadoSectionPanel,
    ULaminadoSectionPanel,
    WLaminadoSectionPanel,
)
from .window_frame import TitleBar, WindowFrame


class MainWindow(QMainWindow):
    mcp_model_changed = Signal()
    mcp_view_changed = Signal(str, bool)
    mcp_active_action_changed = Signal(str)
    mcp_analysis_view_changed = Signal(str, str)
    mcp_analysis_diagrams_changed = Signal(bool)
    mcp_session_changed = Signal(str)

    _initial_framing_commands = frozenset({"barrabieng", "galpao", "mezanino", "portico"})
    _project_file_filter = "Modelo OSA (*.osa)"
    _interface_commands = frozenset({
        "member", "split", "reverse", "join", "rigid", "copy", "cprop", "axes",
        "nodeforce", "nodemoment", "memberforce", "membermoment", "group",
        "action", "load", "selfweight", "combinations", "analyze", "grid",
        "referenceaxes", "nodelabels", "memberlabels", "localaxes", "nodes",
        "solids", "releases", "semirigid", "supports", "snap",
    })

    def __init__(self) -> None:
        super().__init__()
        self.model = StructuralModel()
        self.model_service = ModelService(self.model)
        self.material_service = MaterialService(self.model)
        self.action_service = ActionService(self.model)
        self.section_service = SectionService(self.model)
        self.section_property_service = SectionPropertyService()
        self.project_service = ProjectService(self.model)
        self.analysis_service = AnalysisService(self.model, PyniteAdapter())
        self._analysis_thread: QThread | None = None
        self._analysis_worker: AnalysisWorker | None = None
        self._analysis_revision: int | None = None
        self.command_session = CommandSession(self.model_service)
        self.section_geometry: dict[str, dict[str, float]] = {}
        self.section_profiles: dict[str, str] = {}
        self.current_path: Path | None = None
        self._saved_revision = self.model.revision
        self._command_mode: str | None = None
        self._member_placement_start: tuple[float, float, float] | None = None
        self._join_member_first: str | None = None
        self._copy_properties_reference: str | None = None
        self._copy_elements_selection: list[tuple[str, str]] = []
        self._copy_elements_reference: tuple[float, float, float] | None = None
        self._pending_action_launch: tuple[str, str, dict[str, tuple[float, ...]]] | None = None
        self._member_direction_normalization_enabled = True
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
        shell_layout.addWidget(self.title_bar)
        shell_layout.addWidget(self.scene, 1)
        self.window_frame.body.addWidget(shell)
        self.setCentralWidget(self.window_frame)
        self.selected: tuple[str, str] | None = None
        self.scene.element_clicked.connect(self.select_element)
        self.scene.empty_clicked.connect(self.clear_selection)
        self.scene.enter_pressed.connect(self._confirm_copy_elements)
        self.scene.placement_point_clicked.connect(self._handle_member_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_node_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_rigid_bar_placement_point)
        self.scene.placement_point_clicked.connect(self._handle_copy_placement_point)
        self._make_shortcuts()
        self.palette = FloatingPalette(self)
        self.palette.reposition()
        self.top_icon_palette = TopIconPalette(self)
        self.top_icon_palette.set_member_direction_normalization_enabled(
            self._member_direction_normalization_enabled
        )
        self.top_icon_palette.reposition()
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
        self.processing_panel = ProcessingPanel(self)
        self.axes_panel = AxesPanel(self)
        self.section_panels = {
            "W Laminado": WLaminadoSectionPanel(self),
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
        self.history = CommandHistory(self)
        self.command_bar = CommandBar(self)
        self.command_bar.reposition()
        self.history.reposition()
        self.refresh_scene()
        self.mcp_model_changed.connect(self._refresh_after_mcp_change)
        self.mcp_view_changed.connect(self._apply_mcp_view_change)
        self.mcp_active_action_changed.connect(self._select_active_action)
        self.mcp_analysis_view_changed.connect(self._apply_mcp_analysis_view)
        self.mcp_analysis_diagrams_changed.connect(self.scene.set_analysis_diagrams_visible)
        self.mcp_session_changed.connect(self.palette.show_group)
        self._mcp_application = McpApplication(
            self.model,
            self.model_service,
            analysis_engine=self.analysis_service.engine,
            on_model_changed=self.mcp_model_changed.emit,
            on_view_changed=self.mcp_view_changed.emit,
            get_view_state=self.scene.view_state,
            on_active_action_changed=self.mcp_active_action_changed.emit,
            get_active_action=lambda: self.selected_action_name,
            on_analysis_view_changed=self.mcp_analysis_view_changed.emit,
            get_analysis_view_state=self.scene.analysis_view_state,
            on_analysis_diagrams_changed=self.mcp_analysis_diagrams_changed.emit,
            on_session_changed=self.mcp_session_changed.emit,
            get_session=lambda: self.palette.active_group,
        )
        self._mcp_server = LocalMcpServer(self._mcp_application)
        self._mcp_server.start()
        self._mcp_integration = LocalMcpIntegration()
        self._mcp_integration.ensure_installed()

    def process_analysis(self) -> None:
        """Run PyNite in the background after the progress card is painted."""
        if self._analysis_thread is not None and self._analysis_thread.isRunning():
            return
        orphaned_actions = self.model.remove_orphaned_actions()
        if orphaned_actions:
            self.history.append(
                "> <b>Processamento estrutural</b> "
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

    def _analysis_finished(self, results: object) -> None:
        if self._analysis_revision != self.model.revision:
            self.processing_panel.fail(
                "O modelo foi alterado durante a análise. Execute o processamento novamente."
            )
            return
        self.model.analysis_results = list(results)
        self.processing_panel.succeed(len(self.model.analysis_results))
        self.refresh_analysis_palette()
        self.refresh_selected_property_panel(self.palette.active_group)

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

    def open_program_settings(self) -> None:
        dialog = ProgramSettingsDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()

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
                action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "palette"):
            self.palette.reposition()
        if hasattr(self, "top_icon_palette"):
            self.top_icon_palette.reposition()
        if hasattr(self, "member_property_copy_panel") and self.member_property_copy_panel.isVisible():
            self.member_property_copy_panel.reposition()
        if hasattr(self, "action_top_palette"):
            self.action_top_palette.reposition()
        if hasattr(self, "analysis_top_palette"):
            self.analysis_top_palette.reposition()
        if hasattr(self, "navigation_button"):
            self._reposition_navigation_button()
        if hasattr(self, "properties"):
            self.properties.reposition()
            if self.properties._color_palette.isVisible():
                self.properties.reposition_color_palette()
        if hasattr(self, "axes_panel") and self.axes_panel.isVisible():
            self.axes_panel.reposition()
        if hasattr(self, "command_bar"):
            self.command_bar.reposition()
        if hasattr(self, "history"):
            self.history.reposition()
        if hasattr(self, "section_panel") and self.section_panel.isVisible():
            self.section_panel.reposition()
        if hasattr(self, "displacement_panel") and self.displacement_panel.isVisible():
            self.displacement_panel.reposition()
        if hasattr(self, "processing_panel") and self.processing_panel.isVisible():
            self.processing_panel.reposition()

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

    def show_section_panel(self, section: str, button=None) -> None:
        """Show the geometry panel that corresponds to a section family."""
        panel = self.section_panels.get(section)
        if panel is None:
            if button is not None:
                button.setChecked(False)
            return
        self.properties.close_color_palette()
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
        if self.axes_panel.isVisible():
            self.axes_panel.hide()
            return
        self.properties.close_color_palette()
        self.properties.hide()
        self.close_section_panel()
        self.axes_panel.reposition()
        self.axes_panel.show()
        self.axes_panel.raise_()

    def start_member_placement(self) -> None:
        """Start the graphical member-placement flow from the geometry palette."""
        self.command_session.cancel()
        self._member_placement_start = None
        self._command_mode = "member_placement"
        self.scene.set_member_placement_mode(True)
        self.history.append(
            "> <b>Adicionar membro</b> <span style='color:#57606a'>(Clique na posição inicial do membro)</span>"
        )
        self.scene.plotter.setFocus()

    def start_node_placement(self) -> None:
        """Start the single-click graphical node-placement flow."""
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
        self.command_session.cancel()
        self._member_placement_start = None
        self._command_mode = "rigid_bar_placement"
        self.scene.set_member_placement_mode(True)
        self.history.append(
            "> <b>Adicionar barra rígida</b> "
            "<span style='color:#57606a'>(Clique na posição inicial da barra rígida)</span>"
        )
        self.scene.plotter.setFocus()

    def start_load_command(self) -> None:
        """Open the graphical action launcher instead of the text command flow."""
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
        target_label = "nós" if self._pending_action_launch[0] == "node" else "membros"
        self._command_mode = "action_selection"
        self.history.append(
            "> <b>Adicionar ação</b> "
            f"<span style='color:#57606a'>(Selecione {target_label}; pressione Esc para encerrar)</span>"
        )
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
            self.show_error("Não há membros no modelo para aplicar o peso próprio.")
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
            for material in dialog.selected_materials:
                weights.extend(self.model_service.member_selfweights(material))
        except ValueError as error:
            self.show_error(str(error))
            return

        if not weights:
            self.show_error(
                "Não há membros associados aos materiais selecionados "
                "para aplicar o peso próprio."
            )
            return

        self.action_service.replace_action_with_selfweight(load_case, tuple(weights))
        materials = ", ".join(dialog.selected_materials)
        self.history.append(
            "> <b>Adicionar peso próprio</b> "
            f"<span style='color:#57606a'>(Materiais: {escape(materials)})</span>"
        )
        self.refresh_action_palette()
        self.refresh_scene()

    def start_split_member(self) -> None:
        """Start the split-member flow from the geometry toolbar."""
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        if self.selected is not None and self.selected[0] == "bar":
            self._begin_member_split(self.selected[1])
            return

        self.command_session.cancel()
        self._command_mode = "split_member_selection"
        self.history.append(
            "> <b>Dividir membro</b> "
            "<span style='color:#57606a'>(Selecione um membro)</span>"
        )
        self.scene.plotter.setFocus()

    def _begin_member_split(self, member_name: str) -> None:
        try:
            self.command_session.start_member_split(member_name)
        except ValueError as error:
            self.history.append(
                f"> <b>Dividir membro</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self._command_mode = "split_parts"
        self.history.append(
            f"> <b>Dividir membro</b> <span style='color:#57606a'>"
            f"(Informe em quantas partes o membro {escape(member_name)} será dividido; inteiro maior que 1)</span>"
        )
        self.command_bar.input.setFocus()

    def start_reverse_member(self) -> None:
        """Reverse the selected member or enter graphical member-selection mode."""
        if self.member_direction_normalization_enabled:
            return
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        if self.selected is not None and self.selected[0] == "bar":
            self._reverse_member(self.selected[1])
            return

        self.command_session.cancel()
        self._command_mode = "reverse_member_selection"
        self.history.append(
            "> <b>Inverter membro</b> "
            "<span style='color:#57606a'>(Selecione o membro que deseja inverter)</span>"
        )
        self.scene.plotter.setFocus()

    def _reverse_member(self, member_name: str) -> None:
        if self.member_direction_normalization_enabled:
            return
        self.command_session.cancel()
        self._command_mode = None
        try:
            self.model_service.reverse_member(member_name)
        except ValueError as error:
            self.history.append(
                f"> <b>Inverter membro</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self.history.append(
            f"> <b>Inverter membro</b> <span style='color:#57606a'>"
            f"(Membro {escape(member_name)} invertido)</span>"
        )
        self.refresh_selected_property_panel(self.palette.active_group)
        self.refresh_scene()

    def start_join_members(self) -> None:
        """Start the graphical two-member selection flow for joining members."""
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._join_member_first = (
            self.selected[1]
            if self.selected is not None and self.selected[0] == "bar"
            else None
        )
        self._command_mode = "join_member_selection"
        if self._join_member_first is None:
            message = "Selecione o primeiro membro"
        else:
            message = "Selecione o segundo membro"
        self.history.append(
            "> <b>Unir membros</b> "
            f"<span style='color:#57606a'>({message})</span>"
        )
        self.scene.plotter.setFocus()

    def _join_members(self, first_name: str, second_name: str) -> None:
        try:
            joined = self.model_service.join_members(first_name, second_name)
        except ValueError as error:
            self.history.append(
                f"> <b>Unir membros</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return
        self.normalize_member_directions_if_enabled()
        self._join_member_first = None
        self._command_mode = None
        self.history.append(
            f"> <b>Unir membros</b> <span style='color:#57606a'>"
            f"(Membros unidos em {escape(joined.name)})</span>"
        )
        self.clear_selection()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
        self.refresh_scene()

    def start_copy_member_properties(self) -> None:
        """Choose a reference member and then any number of destination members."""
        self.command_session.cancel()
        self._member_placement_start = None
        self.scene.set_member_placement_mode(False)
        self._copy_elements_selection = []
        self._copy_elements_reference = None
        self.scene.set_selection_highlight(())
        self._copy_properties_reference = (
            self.selected[1]
            if self.selected is not None and self.selected[0] == "bar"
            else None
        )
        self._command_mode = "copy_member_properties_selection"
        self.member_property_copy_panel.begin(self.top_icon_palette.copy_properties_button)
        message = (
            "Selecione o membro de destino"
            if self._copy_properties_reference is not None
            else "Selecione o membro de referência"
        )
        self.history.append(
            "> <b>Copiar propriedades</b> "
            f"<span style='color:#57606a'>({message})</span>"
        )
        self.scene.plotter.setFocus()

    def _copy_member_properties(self, source_name: str, target_name: str) -> None:
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
        self.refresh_selected_property_panel(self.palette.active_group)
        self.refresh_scene()

    def start_copy_elements(self) -> None:
        """Start selecting nodes and members for a translated copy."""
        self.command_session.cancel()
        self._member_placement_start = None
        self._copy_elements_selection = []
        self._copy_elements_reference = None
        self._copy_properties_reference = None
        self.member_property_copy_panel.hide()
        self._command_mode = "copy_elements_selection"
        self.scene.set_member_placement_mode(False)
        self.scene.set_selection_highlight(())
        self.clear_selection()
        self.history.append(
            "> <b>Copiar</b> <span style='color:#57606a'>"
            "(Selecione nós e membros; pressione ENTER para confirmar)</span>"
        )
        self.scene.plotter.setFocus()

    def _confirm_copy_elements(self) -> None:
        """Confirm the element set and begin the two-point copy placement."""
        if self._command_mode != "copy_elements_selection":
            return
        if not self._copy_elements_selection:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#8c959f'>"
                "(Selecione pelo menos um nó ou membro)</span>"
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

    def _handle_copy_placement_point(self, point: object) -> None:
        """Collect the reference/destination points and copy the selection."""
        if self._command_mode == "copy_elements_reference_placement":
            self._copy_elements_reference = tuple(float(value) for value in point)
            self._command_mode = "copy_elements_destination_placement"
            self.scene.set_member_preview_start(self._copy_elements_reference)
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                "(Selecione a posição de destino)</span>"
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
        try:
            copied_nodes, copied_members = self.model_service.copy_elements(
                node_names, member_names, offset,
            )
        except ValueError as error:
            self.history.append(
                f"> <b>Copiar</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        for member_name in copied_members:
            copied_member = self.model.bars[member_name]
            if copied_member.profile:
                self.section_profiles[member_name] = copied_member.profile
            if copied_member.section_geometry:
                self.section_geometry[member_name] = copied_member.geometry_dict()

        self._copy_elements_selection = []
        self._copy_elements_reference = None
        self._command_mode = None
        self.scene.set_member_preview_start(None)
        self.scene.set_member_placement_mode(False)
        self.scene.set_selection_highlight(())
        self.clear_selection()
        if copied_nodes or copied_members:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                f"({len(copied_nodes)} nó(s) e {len(copied_members)} membro(s) criado(s))</span>"
            )
        else:
            self.history.append(
                "> <b>Copiar</b> <span style='color:#57606a'>"
                "(Nenhum elemento novo: os elementos já existiam na posição de destino)</span>"
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
            "referenceaxes": "reference-axes",
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

        if name in geometry_visibility:
            self.palette.show_group("Geometria")
            self.top_icon_palette.toggle_visibility_command(geometry_visibility[name])
            self.history.append(f"> <b>{command_label}</b>")
            return True

        if name == "snap":
            self.palette.show_group("Geometria")
            self.top_icon_palette.toggle_snap_command()
            self.history.append(f"> <b>{command_label}</b>")
            return True

        if name in action_visibility:
            self.palette.show_group("Ações")
            self.action_top_palette.toggle_action_visibility_command(action_visibility[name])
            self.history.append(f"> <b>{command_label}</b>")
            return True

        callbacks = {
            "member": ("Geometria", self.start_member_placement),
            "split": ("Geometria", self.start_split_member),
            "reverse": ("Geometria", self.start_reverse_member),
            "join": ("Geometria", self.start_join_members),
            "rigid": ("Geometria", self.start_rigid_bar_placement),
            "copy": ("Geometria", self.start_copy_elements),
            "cprop": ("Geometria", self.start_copy_member_properties),
            "axes": ("Geometria", self.toggle_axes_panel),
            "group": ("Ações", self.open_action_groups),
            "action": ("Ações", self.start_load_command),
            "load": ("Ações", self.start_load_command),
            "selfweight": ("Ações", self.start_selfweight_command),
            "combinations": ("Análise", self.open_combinations),
            "analyze": ("Análise", self.process_analysis),
        }
        target = callbacks.get(name)
        if target is None:
            return False
        self.palette.show_group(target[0])
        target[1]()
        if name in {"axes", "group", "combinations", "analyze"}:
            self.history.append(f"> <b>{command_label}</b>")
        return True

    def handle_command(self, command: str) -> None:
        if self._handle_interface_command(command):
            return
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

    def _handle_member_placement_point(self, point: object) -> None:
        """Advance the two-click graphical member placement flow."""
        if self._command_mode != "member_placement":
            return
        coordinates = tuple(float(value) for value in point)
        if self._member_placement_start is None:
            self._member_placement_start = coordinates
            self.scene.set_member_preview_start(coordinates)
            self.history.append(
                "> <b>Adicionar membro</b> <span style='color:#57606a'>(Clique na posição final do membro)</span>"
            )
            return

        start = self._member_placement_start
        try:
            start_name, end_name, member_name = self._create_graphical_member(start, coordinates)
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar membro</b> <span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self._member_placement_start = None
        self.command_session.cancel()
        self._command_mode = "member_placement"
        self.scene.set_member_preview_start(None)
        self.scene.set_member_placement_mode(True)
        self.history.append(
            f"> <b>Adicionar membro</b> <span style='color:#57606a'>"
            f"(Membro {escape(member_name)} criado entre {escape(start_name)} e {escape(end_name)})</span>"
        )
        self.history.append(
            "> <b>Adicionar membro</b> <span style='color:#57606a'>(Clique na posição inicial do próximo membro)</span>"
        )
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

    def _handle_rigid_bar_placement_point(self, point: object) -> None:
        """Advance the two-click graphical rigid-bar placement flow."""
        if self._command_mode != "rigid_bar_placement":
            return
        coordinates = tuple(float(value) for value in point)
        if self._member_placement_start is None:
            self._member_placement_start = coordinates
            self.scene.set_member_preview_start(coordinates)
            self.history.append(
                "> <b>Adicionar barra rígida</b> "
                "<span style='color:#57606a'>(Clique na posição final da barra rígida)</span>"
            )
            return

        start = self._member_placement_start
        try:
            start_name, end_name, rigid_name = self._create_graphical_rigid_bar(start, coordinates)
        except ValueError as error:
            self.history.append(
                f"> <b>Adicionar barra rígida</b> "
                f"<span style='color:#8c959f'>({escape(str(error))})</span>"
            )
            return

        self._member_placement_start = None
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

    def cancel_member_placement(self) -> None:
        """Cancel the active graphical geometry launch."""
        if self._command_mode == "action_selection":
            self._pending_action_launch = None
            self._command_mode = None
            self.history.append(
                "> <b>Adicionar ação</b> "
                "<span style='color:#8c959f'>(Lançamento cancelado)</span>"
            )
            return
        if self._command_mode in {
            "split_member_selection", "split_parts", "reverse_member_selection", "join_member_selection",
            "copy_member_properties_selection", "copy_elements_selection",
            "copy_elements_reference_placement", "copy_elements_destination_placement",
        }:
            labels = {
                "reverse_member_selection": "Inverter membro",
                "join_member_selection": "Unir membros",
                "copy_member_properties_selection": "Copiar propriedades",
                "copy_elements_selection": "Copiar",
                "copy_elements_reference_placement": "Copiar",
                "copy_elements_destination_placement": "Copiar",
            }
            copy_elements_active = self._command_mode.startswith("copy_elements_")
            label = labels.get(self._command_mode, "Dividir membro")
            self.command_session.cancel()
            self._command_mode = None
            self._join_member_first = None
            self._copy_properties_reference = None
            self._copy_elements_selection = []
            self._copy_elements_reference = None
            self.member_property_copy_panel.hide()
            if copy_elements_active:
                self.scene.set_member_preview_start(None)
                self.scene.set_member_placement_mode(False)
                self.scene.set_selection_highlight(())
                self.clear_selection()
            self.history.append(
                f"> <b>{label}</b> "
                "<span style='color:#8c959f'>(Operação cancelada)</span>"
            )
            return
        if self._command_mode not in {
            "member_placement", "node_placement", "rigid_bar_placement",
        }:
            return
        labels = {
            "member_placement": "Adicionar membro",
            "node_placement": "Adicionar nó",
            "rigid_bar_placement": "Adicionar barra rígida",
        }
        label = labels[self._command_mode]
        self._member_placement_start = None
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
    ) -> tuple[str, str, str]:
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
            member_name = self.model_service.next_member_name()
            self.model_service.create_member(start_name, end_name, name=member_name)
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
        tolerance = self.model.coordinate_tolerance
        for name, node in self.model.nodes.items():
            if all(
                abs(coordinate - node_coordinate) <= tolerance
                for coordinate, node_coordinate in zip(coordinates, (node.x, node.y, node.z))
            ):
                return name
        return None


    def _apply_pending_action(self, kind: str, name: str) -> None:
        launch = self._pending_action_launch
        if launch is None:
            return
        target_kind, reference, values = launch
        if kind != target_kind:
            expected = "nó" if target_kind == "node" else "membro"
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
        self.refresh_action_palette()
        self.refresh_scene()


    def select_element(self, kind: str, name: str, center: object) -> None:
        self.axes_panel.hide()
        self.selected = kind, name
        if self._command_mode == "action_selection":
            self._apply_pending_action(kind, name)
            return
        if self._command_mode == "split_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Dividir membro</b> "
                    "<span style='color:#8c959f'>(Selecione um membro, não um nó ou barra rígida)</span>"
                )
            else:
                self._begin_member_split(name)
        elif self._command_mode == "reverse_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Inverter membro</b> "
                    "<span style='color:#8c959f'>(Selecione um membro, não um nó ou barra rígida)</span>"
                )
            else:
                self._reverse_member(name)
        elif self._command_mode == "join_member_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Unir membros</b> "
                    "<span style='color:#8c959f'>(Selecione um membro, não um nó ou barra rígida)</span>"
                )
            elif self._join_member_first is None:
                self._join_member_first = name
                self.history.append(
                    "> <b>Unir membros</b> "
                    "<span style='color:#57606a'>(Selecione o segundo membro)</span>"
                )
            elif name == self._join_member_first:
                self.history.append(
                    "> <b>Unir membros</b> "
                    "<span style='color:#8c959f'>(Selecione um segundo membro diferente)</span>"
                )
            else:
                self._join_members(self._join_member_first, name)
        elif self._command_mode == "copy_elements_selection":
            if kind not in {"node", "bar"}:
                self.scene.set_selection_highlight(self._copy_elements_selection)
                self.history.append(
                    "> <b>Copiar</b> "
                    "<span style='color:#8c959f'>(Selecione apenas nós ou membros)</span>"
                )
            else:
                target = kind, name
                if target in self._copy_elements_selection:
                    self._copy_elements_selection.remove(target)
                    action = "removido da seleção"
                else:
                    self._copy_elements_selection.append(target)
                    action = "adicionado à seleção"
                self.scene.set_selection_highlight(self._copy_elements_selection)
                if self._copy_elements_selection:
                    self.selected = self._copy_elements_selection[-1]
                else:
                    self.selected = None
                    self.properties.hide()
                self.history.append(
                    f"> <b>Copiar</b> <span style='color:#57606a'>"
                    f"({escape(kind)} {escape(name)} {action}; "
                    f"{len(self._copy_elements_selection)} selecionado(s))</span>"
                )
            return
        elif self._command_mode == "copy_member_properties_selection":
            if kind != "bar":
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#8c959f'>(Selecione um membro, não um nó ou barra rígida)</span>"
                )
            elif self._copy_properties_reference is None:
                self._copy_properties_reference = name
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#57606a'>(Selecione o membro de destino)</span>"
                )
            elif name == self._copy_properties_reference:
                self.history.append(
                    "> <b>Copiar propriedades</b> "
                    "<span style='color:#8c959f'>(Selecione um membro de destino diferente)</span>"
                )
            else:
                self._copy_member_properties(self._copy_properties_reference, name)
        if self.selected is not None:
            self.properties.show_for(kind, name, self.palette.active_group or "Geometria")

    def refresh_selected_property_panel(self, section: str | None) -> None:
        """Rebuild the open inspector when the work section changes."""
        if section != "Geometria" and hasattr(self, "section_panel") and self.section_panel.isVisible():
            self.close_section_panel()
        if section != "Geometria" and hasattr(self, "displacement_panel") and self.displacement_panel.isVisible():
            self.close_displacement_panel()
        if self.selected is not None and hasattr(self, "properties"):
            self.properties.show_for(*self.selected, section or "Geometria")

    def clear_selection(self) -> None:
        self.selected = None
        self.properties.hide()
        self.section_panel.hide()
        self.displacement_panel.hide()
        self.axes_panel.hide()
        if self._command_mode == "copy_elements_selection":
            self.scene.set_selection_highlight(self._copy_elements_selection)

    def delete_selected(self) -> None:
        """Delete the selected element without rebuilding unrelated actors."""
        if self.selected is None:
            return
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QComboBox, QAbstractSpinBox)):
            return
        kind, name = self.selected
        if kind == "node" and any(
            member.start_node == name or member.end_node == name
            for member in self.model.bars.values()
        ):
            return
        if kind == "node" and any(
            rigid.start_node == name or rigid.end_node == name
            for rigid in self.model.rigid_bars.values()
        ):
            return
        try:
            if kind == "node":
                self.model_service.remove_node(name)
            elif kind == "bar":
                self.model_service.remove_member(name)
            elif kind == "rigid_bar":
                self.model_service.remove_rigid_bar(name)
            else:
                return
        except ValueError as error:
            self.show_error(str(error))
            return
        self.scene.remove_element(kind, name)
        self.clear_selection()



    def new_model(self) -> None:
        if not self._confirm_pending_changes():
            return
        self.axes_panel.discard()
        self.model.clear()
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
        self._saved_revision = self.model.revision
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

    def _save_model_to(self, path: str | Path) -> None:
        try:
            self.project_service.save(path)
            self.current_path = Path(path)
            self._saved_revision = self.model.revision
        except OSError as error:
            self.show_error(f"Não foi possível salvar o arquivo: {error}")

    def open_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", self._project_file_filter)
        if path:
            if Path(path).suffix.casefold() != ".osa":
                self.show_error("Selecione um arquivo de modelo com extensão .osa.")
                return
            try:
                self.axes_panel.discard()
                self.project_service.load(path)
                self.normalize_member_directions_if_enabled()
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
                self.member_property_copy_panel.hide()
                self.scene.set_member_placement_mode(False)
                self.scene.set_selection_highlight(())
                self.clear_selection()
                self.current_path = Path(path)
                self._saved_revision = self.model.revision
                self.refresh_action_palette()
                self.refresh_analysis_palette()
                self.refresh_scene(fit_camera=True)
            except (OSError, ValueError, KeyError) as error:
                self.show_error(f"Não foi possível abrir o modelo: {error}")

    def _has_unsaved_changes(self) -> bool:
        return self.model.revision != self._saved_revision

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
        if self._confirm_pending_changes():
            event.accept()
        else:
            event.ignore()

    def refresh_scene(self, *, fit_camera: bool = False) -> None:
        self.scene.render_model(self.model, preserve_camera=not fit_camera)
        self.properties.update_delete_button_state()

    def _refresh_after_mcp_change(self) -> None:
        """Atualiza a interface após uma operação recebida pelo MCP local."""
        self.normalize_member_directions_if_enabled()
        self.refresh_action_palette()
        self.refresh_analysis_palette()
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
            "snap_enabled": self.scene.set_snap_enabled,
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
        names = tuple(result.load_reference for result in self.model.analysis_results)
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
        self.scene.update_member_geometry(member_name)

    def refresh_member_color(self, member_name: str) -> None:
        self.scene.update_member_color(member_name)

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
