"""Janela principal e composição dos componentes visuais."""
from .axes_panel import AxesPanel
from .command_bar import CommandBar, CommandHistory
from .common import *
from .dialogs import ActionGroupDialog, SettingsDialog
from .navigation_buttons import LeftArrowButton, RightArrowButton, SlopedPlaneButton
from .palettes import ActionTopPalette, FloatingPalette, PaletteTooltip, TopIconPalette
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
    def __init__(self) -> None:
        super().__init__()
        self.model = StructuralModel()
        self.model_service = ModelService(self.model)
        self.material_service = MaterialService(self.model)
        self.action_service = ActionService(self.model)
        self.section_service = SectionService(self.model)
        self.section_property_service = SectionPropertyService()
        self.project_service = ProjectService(self.model)
        self.command_session = CommandSession(self.model_service)
        self.section_geometry: dict[str, dict[str, float]] = {}
        self.section_profiles: dict[str, str] = {}
        self.current_path: Path | None = None
        self._command_mode: str | None = None
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
        self._make_shortcuts()
        self.palette = FloatingPalette(self)
        self.palette.reposition()
        self.top_icon_palette = TopIconPalette(self)
        self.top_icon_palette.reposition()
        self.selected_action_name: str | None = None
        self.action_top_palette = ActionTopPalette(self)
        self.refresh_action_palette()
        self.action_top_palette.set_actions_visible(False)
        self.action_top_palette.reposition()
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

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()

    def open_action_groups(self) -> None:
        dialog = ActionGroupDialog(self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()
        self.refresh_action_palette()

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
            ("Vista isométrica", "0", self.scene.view_isometric),
            ("Enquadrar estrutura", "F", self.scene.reset_camera),
        )
        for label, shortcut, callback in actions:
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "palette"):
            self.palette.reposition()
        if hasattr(self, "top_icon_palette"):
            self.top_icon_palette.reposition()
        if hasattr(self, "action_top_palette"):
            self.action_top_palette.reposition()
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

    def show_section_panel(self, section: str, button=None) -> None:
        """Show the geometry panel that corresponds to a section family."""
        panel = self.section_panels.get(section)
        if panel is None:
            if button is not None:
                button.setChecked(False)
            return
        self.properties.close_color_palette()
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


    def start_node_command(self) -> None:
        self.command_session.pending = "node"
        self._command_mode = "node"  # compatibilidade com extensões existentes
        self.history.append(
            "> <b>node</b> <span style='color:#57606a'>(Informe as coordenadas do nó em X,Y,Z)</span>"
        )
        self.command_bar.input.setFocus()

    def start_member_command(self) -> None:
        self.command_session.pending = "member"
        self._command_mode = "member"
        self.history.append(
            "> <b>member</b> <span style='color:#57606a'>(Informe o nó inicial e final A,B)</span>"
        )
        self.command_bar.input.setFocus()

    def start_load_command(self) -> None:
        if self.action_service.has_selfweight(self.selected_action_name or ""):
            self.history.append(
                "> <b>load</b> <span style='color:#8c959f'>(A ação atual está restrita apenas a cargas de peso próprio.)</span>"
            )
            self.command_bar.input.setFocus()
            return
        self.command_session.pending = "load_target"
        self.command_session.load_target = None
        self._command_mode = "load_target"
        self.history.append(
            "> <b>load</b> <span style='color:#57606a'>(Informe a identidade do nó ou do membro.)</span>"
        )
        self.command_bar.input.setFocus()

    def handle_command(self, command: str) -> None:
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
            self.refresh_action_palette()
            self.refresh_scene()


    def select_element(self, kind: str, name: str, center: object) -> None:
        self.axes_panel.hide()
        self.selected = kind, name
        self.properties.show_for(kind, name, self.palette.active_group or "Geometria")

    def refresh_selected_property_panel(self, section: str | None) -> None:
        """Rebuild the open inspector when the work section changes."""
        if section != "Geometria" and hasattr(self, "section_panel") and self.section_panel.isVisible():
            self.close_section_panel()
        if self.selected is not None and hasattr(self, "properties"):
            self.properties.show_for(*self.selected, section or "Geometria")

    def clear_selection(self) -> None:
        self.selected = None
        self.properties.hide()
        self.section_panel.hide()
        self.axes_panel.hide()

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
        try:
            if kind == "node":
                self.model_service.remove_node(name)
            else:
                self.model_service.remove_member(name)
        except ValueError as error:
            self.show_error(str(error))
            return
        self.scene.remove_element(kind, name)
        self.clear_selection()



    def new_model(self) -> None:
        self.axes_panel.discard()
        self.model.clear()
        self.section_profiles.clear()
        self.section_geometry.clear()
        self.command_session.cancel()
        self._command_mode = None
        self.clear_selection()
        self.current_path = None
        self.refresh_action_palette()
        self.refresh_scene()

    def save_model(self) -> None:
        path = str(self.current_path) if self.current_path else ""
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Salvar modelo", "modelo.osa.json", "Modelo OSA (*.osa.json)")
        if path:
            try:
                self.project_service.save(path)
                self.current_path = Path(path)
            except OSError as error:
                self.show_error(f"Não foi possível salvar o arquivo: {error}")

    def open_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir modelo", "", "Modelo OSA (*.osa.json);;JSON (*.json)")
        if path:
            try:
                self.axes_panel.discard()
                self.project_service.load(path)
                self.section_profiles = {
                    name: member.profile for name, member in self.model.bars.items() if member.profile
                }
                self.section_geometry = {
                    name: member.geometry_dict() for name, member in self.model.bars.items()
                    if member.section_geometry
                }
                self.command_session.cancel()
                self.clear_selection()
                self.current_path = Path(path)
                self.refresh_action_palette()
                self.refresh_scene()
            except (OSError, ValueError, KeyError) as error:
                self.show_error(f"Não foi possível abrir o modelo: {error}")

    def refresh_scene(self) -> None:
        self.scene.render_model(self.model)
        self.properties.update_delete_button_state()

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

    def show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Dados inválidos", message)
