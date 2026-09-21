from .common import *
from .window_frame import WindowFrame


class FloatingPalette(QFrame):
    """Compact accordion palette overlaid on the 3D viewport."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("floatingPalette")
        self.setFixedWidth(204)
        self.setStyleSheet("""
            QFrame#floatingPalette {
                background: rgba(246, 248, 250, 248); border: 1px solid #d0d7de;
                border-radius: 14px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(3)
        self._layout = layout
        self._primary_buttons: dict[str, QPushButton] = {}
        self._sections: dict[str, QWidget] = {}
        self._expanded: str | None = None
        self._add_group("Geometria", (
            ("Nó", window.start_node_command),
            ("Membro", window.start_member_command),
        ))
        self._add_group("Ações", (
            ("Grupo", lambda: None),
            ("Carga", lambda: None),
        ))
        self._add_group("Análise", (
            ("Combinações", lambda: None),
            ("Processar", lambda: None),
        ))
        self.toggle_group("Geometria")

    def _add_group(self, name: str, items: tuple[tuple[str, object], ...]) -> None:
        primary = QPushButton(f"▸  {name}")
        primary.setObjectName("palettePrimary")
        primary.setCheckable(True)
        primary.clicked.connect(lambda _checked=False, group=name: self.toggle_group(group))
        self._layout.addWidget(primary)
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(16, 0, 0, 3)
        section_layout.setSpacing(2)
        for label, callback in items:
            button = QPushButton(label)
            button.setObjectName("paletteSecondary")
            button.clicked.connect(callback)
            section_layout.addWidget(button)
        section.hide()
        self._layout.addWidget(section)
        self._primary_buttons[name] = primary
        self._sections[name] = section

    def toggle_group(self, name: str) -> None:
        next_group = None if self._expanded == name else name
        for group, section in self._sections.items():
            expanded = group == next_group
            section.setVisible(expanded)
            button = self._primary_buttons[group]
            button.setChecked(expanded)
            button.setText(f"{'▾' if expanded else '▸'}  {group}")
        self._expanded = next_group
        self._layout.activate()
        self.setFixedHeight(self.sizeHint().height())
        if hasattr(self.window, "top_icon_palette"):
            self.window.top_icon_palette.set_geometry_visible(next_group == "Geometria")

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        x = margin + 24
        y = max(24, (self.window.height() - self.height()) // 2)
        self.move(QPoint(x, y))
        self.raise_()


class TopIconPalette(QFrame):
    """Small floating icon palette centered above the 3D viewport."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("topIconPalette")
        self.setStyleSheet("QFrame#topIconPalette { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        for filename, tooltip, kind in (("dot-n.svg", "Identificadores dos nós", "node"),
                                        ("minus-m.svg", "Identificadores dos membros", "bar"),
                                        ("axis-3d.svg", "Eixos locais", "axes"),
                                        ("box.svg", "Seções sólidas", "solid"),
                                        ("release.svg", "Vinculações dos membros", "releases"),
                                        ("support-3d.svg", "Apoios dos nós", "supports")):
            button = QToolButton(self)
            button.setFixedSize(24, 24)
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / filename)))
            button.setIconSize(QSize(19, 19))
            button.setToolTip(tooltip)
            button.setCheckable(True)
            button.setChecked(True)
            if kind == "axes":
                button.toggled.connect(window.scene.set_local_axes_visible)
            elif kind == "solid":
                button.toggled.connect(window.scene.set_solid_members_visible)
            elif kind == "releases":
                button.toggled.connect(window.scene.set_member_releases_visible)
            elif kind == "supports":
                button.toggled.connect(window.scene.set_node_supports_visible)
            else:
                button.toggled.connect(lambda visible, element_kind=kind:
                                       window.scene.set_labels_visible(element_kind, visible))
            button.setStyleSheet(
                "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
                "QToolButton:hover { background: #eaeef2; }"
                "QToolButton:checked { background: #d0d7de; }"
                "QToolButton:pressed { background: #afb8c1; }"
            )
            layout.addWidget(button)
        self.adjustSize()

    def set_geometry_visible(self, visible: bool) -> None:
        self.setVisible(visible)

    def reposition(self) -> None:
        margin = 0 if self.window().isMaximized() else WindowFrame.MARGIN
        self.move((self.window().width() - self.width()) // 2, margin + 52)
        self.raise_()
