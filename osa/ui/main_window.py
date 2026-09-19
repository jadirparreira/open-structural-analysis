"""Janela principal e composição dos componentes visuais."""
from .command_bar import CommandBar, CommandHistory
from .common import *
from .dialogs import SettingsDialog
from .palettes import FloatingPalette, TopIconPalette
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
        self.properties = PropertyPanel(self)
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

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "window_frame"):
            self.window_frame.update_state()
            maximized = self.isMaximized()
            self.title_bar.maximize_button.setText("⧉" if maximized else "□")
            self.title_bar.maximize_button.setToolTip("Restaurar" if maximized else "Maximizar")

    def _make_shortcuts(self) -> None:
        actions = (
            ("Novo modelo", QKeySequence.StandardKey.New, self.new_model),
            ("Abrir modelo", QKeySequence.StandardKey.Open, self.open_model),
            ("Salvar modelo", QKeySequence.StandardKey.Save, self.save_model),
            ("Vista isométrica", "0", self.scene.plotter.view_isometric),
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
        if hasattr(self, "properties"):
            self.properties.reposition()
            if self.properties._color_palette.isVisible():
                self.properties.reposition_color_palette()
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

    def handle_command(self, command: str) -> None:
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
        if response.model_changed:
            self.refresh_scene()


    def select_element(self, kind: str, name: str, center: object) -> None:
        self.selected = kind, name
        self.properties.show_for(kind, name)

    def clear_selection(self) -> None:
        self.selected = None
        self.properties.hide()
        self.section_panel.hide()



    def new_model(self) -> None:
        self.model.clear()
        self.section_profiles.clear()
        self.section_geometry.clear()
        self.command_session.cancel()
        self._command_mode = None
        self.clear_selection()
        self.current_path = None
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
                self.refresh_scene()
            except (OSError, ValueError, KeyError) as error:
                self.show_error(f"Não foi possível abrir o modelo: {error}")

    def refresh_scene(self) -> None:
        self.scene.render_model(self.model)

    def refresh_member_axes(self, member_name: str) -> None:
        self.scene.update_member_axes(member_name)

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
