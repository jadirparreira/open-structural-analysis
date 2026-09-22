from .common import *
from .window_frame import WindowFrame


class PaletteTooltip(QLabel):
    """Tooltip compacto que fica ancorado ao lado do botão da paleta."""

    SHOW_DELAY_MS = 220
    FADE_DURATION_MS = 140

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("paletteTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pending: tuple[QToolButton, str, str] | None = None
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_pending)
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(self.FADE_DURATION_MS)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade_animation.finished.connect(self._fade_finished)

    def schedule_for(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "right")

    def schedule_below(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "below")

    def _schedule(self, button: QToolButton, text: str, placement: str) -> None:
        self._show_timer.stop()
        self._pending = button, text, placement
        if self.isVisible():
            self._animate_to(0.0)
        self._show_timer.start(self.SHOW_DELAY_MS)

    def _show_pending(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        button, text, placement = pending
        if not button.isVisible():
            return
        self._show_now(button, text, placement)

    def _show_now(self, button: QToolButton, text: str, placement: str) -> None:
        self._show_timer.stop()
        self._pending = None
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is None:
            return
        if placement == "below":
            button_position = button.mapTo(parent, QPoint(0, button.height() + 10))
            self.move(
                button_position.x() + (button.width() - self.width()) // 2,
                button_position.y(),
            )
        else:
            button_position = button.mapTo(parent, QPoint(button.width() + 10, 0))
            self.move(
                button_position.x(),
                button_position.y() + (button.height() - self.height()) // 2,
            )
        self._fade_animation.stop()
        self._opacity_effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self._animate_to(1.0)

    def _animate_to(self, opacity: float, hide_when_done: bool = False) -> None:
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._opacity_effect.opacity())
        self._fade_animation.setEndValue(opacity)
        self._hide_when_done = hide_when_done
        self._fade_animation.start()

    def _fade_finished(self) -> None:
        if getattr(self, "_hide_when_done", False):
            self.hide()

    def dismiss(self) -> None:
        self._show_timer.stop()
        self._pending = None
        if not self.isVisible():
            self._opacity_effect.setOpacity(0.0)
            return
        self._animate_to(0.0, hide_when_done=True)


class FloatingPalette(QFrame):
    """Compact accordion palette overlaid on the 3D viewport."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("floatingPalette")
        self.setFixedWidth(54)
        self.setStyleSheet("""
            QFrame#floatingPalette {
                background: rgba(246, 248, 250, 248); border: 1px solid #d0d7de;
                border-radius: 14px;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(4)
        self._layout = layout
        self._primary_buttons: dict[str, QToolButton] = {}
        self._sections: dict[str, QWidget] = {}
        self._expanded: str | None = None
        self._tooltip = PaletteTooltip(window)
        self._add_group(
            "Geometria",
            "geometry-vector-square.svg",
            (
                ("Adicionar nó", "node-circle.svg", window.start_node_command),
                ("Adicionar membro", "member-spline.svg", window.start_member_command),
            ),
        )
        self._add_group(
            "Ações",
            "actions-bookmark.svg",
            (
                ("Grupo de ações", "group-actions.svg", window.open_action_groups),
                ("Adicionar ação", "add-action.svg", lambda: None),
            ),
        )
        self._add_group(
            "Análise",
            "analysis-frame.svg",
            (
                ("Combinações", "add-combination.svg", lambda: None),
                ("Processar", "process-analysis.svg", lambda: None),
            ),
        )
        self.toggle_group("Geometria")

    def _add_group(
        self,
        name: str,
        icon_filename: str,
        items: tuple[tuple[str, str, object], ...],
    ) -> None:
        primary = QToolButton(self)
        primary.setObjectName("palettePrimary")
        primary.setFixedSize(38, 38)
        primary.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_filename)))
        primary.setIconSize(QSize(22, 22))
        self._configure_tooltip(primary, name)
        primary.setCheckable(True)
        primary.clicked.connect(lambda _checked=False, group=name: self.toggle_group(group))
        self._layout.addWidget(primary, 0, Qt.AlignmentFlag.AlignHCenter)
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 3)
        section_layout.setSpacing(3)
        section_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        for label, item_icon, callback in items:
            button = QToolButton(self)
            button.setObjectName("paletteSecondary")
            button.setFixedSize(38, 34)
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / item_icon)))
            button.setIconSize(QSize(21, 21))
            self._configure_tooltip(button, label)
            button.clicked.connect(callback)
            section_layout.addWidget(button)
        section.hide()
        self._layout.addWidget(section)
        self._primary_buttons[name] = primary
        self._sections[name] = section

    def _configure_tooltip(self, button: QToolButton, text: str) -> None:
        """Register the label for the custom tooltip and block Qt's default one."""
        button.setToolTip(text)
        button.setProperty("paletteTooltip", text)
        button.setAccessibleName(text)
        button.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QToolButton):
            if event.type() == QEvent.Type.Enter:
                self._tooltip.schedule_for(watched, watched.property("paletteTooltip"))
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def toggle_group(self, name: str) -> None:
        next_group = None if self._expanded == name else name
        self._tooltip.dismiss()
        for group, section in self._sections.items():
            expanded = group == next_group
            section.setVisible(expanded)
            button = self._primary_buttons[group]
            button.setChecked(expanded)
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
        self._tooltip = PaletteTooltip(window)
        for filename, tooltip, kind in (("hash.svg", "Plano", "grid"),
                                        ("dot-n.svg", "Identificadores dos nós", "node"),
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
            button.setProperty("paletteTooltip", tooltip)
            button.setAccessibleName(tooltip)
            button.installEventFilter(self)
            button.setCheckable(True)
            button.setChecked(True)
            if kind == "grid":
                button.toggled.connect(window.scene.set_grid_visible)
            elif kind == "axes":
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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QToolButton):
            if event.type() == QEvent.Type.Enter:
                self._tooltip.schedule_below(watched, watched.property("paletteTooltip"))
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def set_geometry_visible(self, visible: bool) -> None:
        if not visible:
            self._tooltip.dismiss()
        self.setVisible(visible)

    def reposition(self) -> None:
        margin = 0 if self.window().isMaximized() else WindowFrame.MARGIN
        self.move((self.window().width() - self.width()) // 2, margin + 52)
        self.raise_()
