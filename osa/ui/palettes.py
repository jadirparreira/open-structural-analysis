from .common import *
from .window_frame import WindowFrame


def _command_tooltip(label: str, command: str) -> str:
    """Show the button label and its one-word text command on separate lines."""
    return f"{label}<br><span style='font-size: 10px;'>{command}</span>"


class PaletteTooltip(QLabel):
    """Tooltip compacto que fica ancorado ao lado do botão da paleta."""

    SHOW_DELAY_MS = 220
    FADE_DURATION_MS = 140

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("paletteTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pending: tuple[QToolButton, str, str, int] | None = None
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

    def schedule_for(self, button: QToolButton, text: str, gap: int = 10) -> None:
        self._schedule(button, text, "right", gap)

    def schedule_below(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "below", 10)

    def schedule_upper_right(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "upper-right", 10)

    def schedule_left(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "left", 10)

    def schedule_above(self, button: QToolButton, text: str) -> None:
        self._schedule(button, text, "above", 10)

    def _schedule(self, button: QToolButton, text: str, placement: str, gap: int) -> None:
        self._show_timer.stop()
        self._pending = button, text, placement, gap
        if self.isVisible():
            self._animate_to(0.0)
        self._show_timer.start(self.SHOW_DELAY_MS)

    def _show_pending(self) -> None:
        pending = self._pending
        self._pending = None
        if pending is None:
            return
        button, text, placement, gap = pending
        if not button.isVisible():
            return
        self._show_now(button, text, placement, gap)

    def _show_now(self, button: QToolButton, text: str, placement: str, gap: int) -> None:
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
        elif placement == "upper-right":
            button_position = button.mapTo(parent, QPoint(button.width() + 10, -self.height() - 10))
            self.move(button_position)
        elif placement == "above":
            button_position = button.mapTo(parent, QPoint(0, -self.height() - 10))
            self.move(
                button_position.x() + (button.width() - self.width()) // 2,
                button_position.y(),
            )
        elif placement == "left":
            button_position = button.mapTo(parent, QPoint(-self.width() - 10, 0))
            self.move(
                button_position.x(),
                button_position.y() + (button.height() - self.height()) // 2,
            )
        else:
            button_position = button.mapTo(parent, QPoint(button.width() + gap, 0))
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
    """Compact session selector overlaid on the 3D viewport."""

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
            QToolButton#palettePrimary {
                border: 0; border-radius: 6px; padding: 0;
                background: transparent; color: #24292f;
            }
            QToolButton#palettePrimary:hover { background: #eaeef2; }
            QToolButton#palettePrimary:checked,
            QToolButton#palettePrimary:checked:hover {
                border: 0; background: transparent; color: #24292f;
            }
            QFrame#paletteSelectionIndicator {
                background: #eaeef2; border: 1px solid #d0d7de; border-radius: 6px;
            }
            QToolButton#paletteUnavailable {
                border: 0; border-radius: 6px; padding: 0;
                background: transparent; color: #8c959f;
            }
            QToolButton#paletteUnavailable:hover { background: #eaeef2; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(4)
        self._layout = layout
        self._primary_buttons: dict[str, QToolButton] = {}
        self._sections: dict[str, QWidget] = {}
        self._expanded: str | None = None
        self._verification_view_state: dict[str, bool] | None = None
        self._tooltip = PaletteTooltip(window)
        self._selection_indicator = QFrame(self)
        self._selection_indicator.setObjectName("paletteSelectionIndicator")
        self._selection_indicator.setFixedSize(38, 38)
        self._selection_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._selection_animation = QPropertyAnimation(self._selection_indicator, b"geometry", self)
        self._selection_animation.setDuration(180)
        self._selection_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._selection_indicator.hide()
        self._add_group(
            "Geometria",
            "geometry-vector-square.svg",
            (),
        )
        self._add_group(
            "Ações",
            "actions-anvil.svg",
            (),
        )
        self._add_group(
            "Análise",
            "analysis-cpu.svg",
            (),
        )
        self._add_group(
            "Memorial",
            "calculation-memory.svg",
            (),
        )
        self._add_unavailable_button("Documentação", "documentation-scroll.svg")
        self._add_unavailable_button("Rotinas", "routines-chevrons.svg")
        self.toggle_group("Geometria", animate=False)

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
        self._primary_buttons[name] = primary
        if not items:
            return

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
        self._sections[name] = section

    def _add_unavailable_button(self, name: str, icon_filename: str) -> None:
        button = QToolButton(self)
        button.setObjectName("paletteUnavailable")
        button.setFixedSize(38, 38)
        icon_path = Path(__file__).parents[1] / "resources" / "icons" / icon_filename
        source_icon = QIcon(str(icon_path))
        button.setIcon(QIcon(source_icon.pixmap(QSize(22, 22), QIcon.Mode.Disabled)))
        button.setIconSize(QSize(22, 22))
        tooltip = f"{name}<br><span style='font-size: 10px;'>(em desenvolvimento)</span>"
        self._configure_tooltip(button, tooltip)
        button.setAccessibleName(f"{name} (em desenvolvimento)")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)

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

    def toggle_group(self, name: str, *, animate: bool = True) -> None:
        next_group = name
        previous_group = self._expanded
        if previous_group == "Memorial" and next_group != "Memorial":
            self._set_verification_view(False)
        if name != "Geometria" and getattr(self.window, "_command_mode", None) in {
            "scene_hide_selection", "scene_reveal_selection", "member_placement",
        }:
            self.window.cancel_member_placement()
        self._tooltip.dismiss()
        for group, button in self._primary_buttons.items():
            expanded = group == next_group
            button.setChecked(expanded)
            section = self._sections.get(group)
            if section is not None:
                section.setVisible(expanded)
        self._expanded = next_group
        if next_group == "Memorial" and previous_group != "Memorial":
            self._set_verification_view(True)
        self._layout.activate()
        self.setFixedHeight(self.sizeHint().height())
        self._move_selection_indicator(next_group, animate=animate)
        if hasattr(self.window, "top_icon_palette"):
            self.window.top_icon_palette.set_geometry_visible(next_group == "Geometria")
        if hasattr(self.window, "verification_top_palette"):
            self.window.verification_top_palette.set_verification_visible(next_group == "Memorial")
        if hasattr(self.window, "action_top_palette"):
            self.window.action_top_palette.set_actions_visible(next_group == "Ações")
        if hasattr(self.window, "analysis_top_palette"):
            if next_group == "Análise":
                self.window.prepare_analysis_palette()
            self.window.analysis_top_palette.set_analysis_visible(next_group == "Análise")
        if hasattr(self.window, "scene"):
            self.window.scene.set_actions_visible(next_group == "Ações")
            self.window.scene.set_analysis_visible(next_group == "Análise")
            self.window.scene.set_verification_group_selection_active(next_group == "Memorial")
        if hasattr(self.window, "refresh_selected_property_panel"):
            self.window.refresh_selected_property_panel(next_group)

    def _set_verification_view(self, enabled: bool) -> None:
        """Hide modeling annotations while the verification session is active."""
        options = (
            "nodes_visible",
            "node_labels_visible",
            "member_labels_visible",
            "local_axes_visible",
            "member_releases_visible",
            "semirigid_links_visible",
            "node_supports_visible",
        )
        if enabled:
            if self._verification_view_state is None:
                state = self.window.scene.view_state()
                self._verification_view_state = {option: state[option] for option in options}
            target = {
                "nodes_visible": True,
                "node_labels_visible": False,
                "member_labels_visible": False,
                "local_axes_visible": False,
                "member_releases_visible": False,
                "semirigid_links_visible": False,
                "node_supports_visible": True,
            }
        else:
            if self._verification_view_state is None:
                return
            target = self._verification_view_state
            self._verification_view_state = None

        for option, visible in target.items():
            self.window._apply_mcp_view_change(option, visible)

    def _move_selection_indicator(self, name: str, *, animate: bool) -> None:
        button = self._primary_buttons.get(name)
        if button is None:
            return
        target = QRect(button.geometry())
        self._selection_animation.stop()
        if not animate or not self._selection_indicator.isVisible():
            self._selection_indicator.setGeometry(target)
            self._selection_indicator.show()
            self._selection_indicator.lower()
            return
        self._selection_animation.setStartValue(self._selection_indicator.geometry())
        self._selection_animation.setEndValue(target)
        self._selection_animation.start()

    @property
    def active_group(self) -> str | None:
        """The currently open primary palette section."""
        return self._expanded

    def show_group(self, name: str) -> None:
        """Abre um grupo sem alterná-lo para fechado quando já está ativo."""
        if self._expanded != name:
            self.toggle_group(name)

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        x = margin + 24
        y = max(24, (self.window.height() - self.height()) // 2)
        self.move(QPoint(x, y))
        self.raise_()


class MemberPropertyCopyPanel(QFrame):
    """Compact property picker anchored below the copy-members button."""

    _options = (
        ("color", "Cor"),
        ("material", "Material"),
        ("section", "Seção"),
        ("rotation", "Rotação"),
        ("offsets", "Deslocamento"),
        ("releases", "Vinculações"),
    )

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self._button: QToolButton | None = None
        self.setObjectName("memberPropertyCopyPanel")
        self.setStyleSheet(
            "QFrame#memberPropertyCopyPanel { background: rgba(246, 248, 250, 245); "
            "border: 1px solid #d0d7de; border-radius: 8px; }"
            "QLabel#memberPropertyCopyTitle { color: #57606a; background: transparent; border: 0; "
            "font-size: 11px; font-weight: 600; padding: 0; }"
            "QCheckBox { color: #24292f; background: transparent; border: 0; spacing: 6px; "
            "font-size: 11px; min-height: 22px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de; "
            "border-radius: 5px; background: #ffffff; }"
            "QCheckBox::indicator:hover { border-color: #0969da; }"
            "QCheckBox::indicator:checked { background: #0969da; border-color: #0969da; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        title = QLabel("Copiar propriedades da barra", self)
        title.setObjectName("memberPropertyCopyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)
        choices = QGridLayout()
        choices.setContentsMargins(0, 0, 0, 0)
        choices.setHorizontalSpacing(12)
        choices.setVerticalSpacing(0)
        self.checkboxes: dict[str, QCheckBox] = {}
        for index, (key, label) in enumerate(self._options):
            checkbox = QCheckBox(label, self)
            checkbox.setAccessibleName(f"Copiar {label.casefold()}")
            checkbox.setChecked(True)
            self.checkboxes[key] = checkbox
            choices.addWidget(checkbox, index // 2, index % 2)
        layout.addLayout(choices)
        self.adjustSize()
        self.hide()

    def begin(self, button: QToolButton) -> None:
        self._button = button
        for checkbox in self.checkboxes.values():
            checkbox.setChecked(True)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

    def selected_properties(self) -> frozenset[str]:
        return frozenset(
            key for key, checkbox in self.checkboxes.items() if checkbox.isChecked()
        )

    def reposition(self) -> None:
        if self._button is None:
            return
        position = self._button.mapTo(
            self.window,
            QPoint((self._button.width() - self.width()) // 2, self._button.height() + 10),
        )
        self.move(position)


class VerificationTopPalette(QFrame):
    """Top palette for element names and memorial grouping."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("verificationTopPalette")
        self.setStyleSheet(
            "QFrame#verificationTopPalette { background: #f6f8fa; border: 1px solid #d0d7de; "
            "border-radius: 8px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._window = window
        self._tooltip = PaletteTooltip(window)
        self.name_button = self._identifier_button(
            "tag.svg", "Nome", "name",
        )
        layout.addWidget(self.name_button)
        self.utilization_button = self._identifier_button(
            "percent.svg", "Taxa de utilização", "utilization",
        )
        layout.addWidget(self.utilization_button)
        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setFixedHeight(18)
        separator.setStyleSheet("QFrame { color: #d0d7de; }")
        layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)
        self.group_button = QToolButton(self)
        self.group_button.setFixedSize(24, 24)
        self.group_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "group-elements.svg"))
        )
        self.group_button.setIconSize(QSize(19, 19))
        tooltip = _command_tooltip("Agrupar elementos", "GROUP")
        self.group_button.setToolTip(tooltip)
        self.group_button.setProperty("paletteTooltip", tooltip)
        self.group_button.setAccessibleName("Agrupar elementos")
        self.group_button.clicked.connect(window.start_group_verification_elements)
        self.group_button.installEventFilter(self)
        self.group_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(self.group_button)
        self.verify_button = QToolButton(self)
        self.verify_button.setFixedSize(24, 24)
        self.verify_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "verification-book-check.svg"))
        )
        self.verify_button.setIconSize(QSize(19, 19))
        tooltip = _command_tooltip("Verificar modelo", "VERIFY")
        self.verify_button.setToolTip(tooltip)
        self.verify_button.setProperty("paletteTooltip", tooltip)
        self.verify_button.setAccessibleName("Verificar modelo")
        self.verify_button.clicked.connect(window.verify_model)
        self.verify_button.installEventFilter(self)
        self.verify_button.setStyleSheet(self.group_button.styleSheet())
        layout.addWidget(self.verify_button)
        self.hide()

    def _identifier_button(self, icon_name: str, label: str, kind: str) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(24, 24)
        button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_name)))
        button.setIconSize(QSize(19, 19))
        button.setCheckable(True)
        button.setChecked(False)
        tooltip = label
        button.setToolTip(tooltip)
        button.setProperty("paletteTooltip", tooltip)
        button.setAccessibleName(label)
        button.toggled.connect(
            lambda visible, identifier_kind=kind:
            self._window.scene.set_verification_identifier_visible(identifier_kind, visible)
        )
        button.installEventFilter(self)
        button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        return button

    def set_verification_visible(self, visible: bool) -> None:
        if not visible:
            self._tooltip.dismiss()
        self._window.scene.set_verification_palette_visible(visible)
        self.setVisible(visible)
        if visible:
            self.reposition()

    def reposition(self) -> None:
        self.adjustSize()
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move((self._window.width() - self.width()) // 2, margin + 52)
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.name_button, self.utilization_button, self.group_button, self.verify_button):
            if event.type() == QEvent.Type.Enter:
                self._tooltip.schedule_below(watched, watched.property("paletteTooltip"))
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)


class TopIconPalette(QFrame):
    """Small floating icon palette centered above the 3D viewport."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("topIconPalette")
        self.setStyleSheet("QFrame#topIconPalette { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._tooltip = PaletteTooltip(window)
        self._visibility_buttons: dict[str, QToolButton] = {}
        self._solid_node_states: dict[str, tuple[bool, bool]] | None = None
        self._window = window
        for filename, tooltip, kind in (("hash.svg", "Plano", "grid"),
                                        ("reference-axes.svg", "Eixos", "reference-axes"),
                                        ("box.svg", "Seções sólidas", "solid"),
                                        ("node-circle.svg", "Nós", "nodes"),
                                        ("dot-n.svg", "Identificadores dos nós", "node"),
                                        ("minus-m.svg", "Identificadores das barras", "bar"),
                                        ("axis-3d.svg", "Eixos locais", "axes"),
                                        ("release.svg", "Vinculações das barras", "releases"),
                                        ("elastic-support.svg", "Flexibilização dos vínculos", "semirigid"),
                                        ("support-3d.svg", "Apoios dos nós", "supports")):
            button = QToolButton(self)
            button.setFixedSize(24, 24)
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / filename)))
            button.setIconSize(QSize(19, 19))
            command = {
                "grid": "GRID",
                "reference-axes": "AXES",
                "node": "NODELABELS",
                "bar": "MEMBERLABELS",
                "axes": "LOCALAXES",
                "nodes": "NODES",
                "solid": "SOLIDS",
                "releases": "RELEASES",
                "semirigid": "SEMIRIGID",
                "supports": "SUPPORTS",
            }[kind]
            palette_tooltip = _command_tooltip(tooltip, command)
            button.setToolTip(palette_tooltip)
            button.setProperty("paletteTooltip", palette_tooltip)
            button.setAccessibleName(tooltip)
            button.installEventFilter(self)
            button.setCheckable(True)
            button.setChecked(kind != "solid")
            if kind == "grid":
                button.toggled.connect(window.scene.set_grid_visible)
            elif kind == "reference-axes":
                button.toggled.connect(window.scene.set_reference_axes_visible)
            elif kind == "nodes":
                button.toggled.connect(window.scene.set_nodes_visible)
            elif kind == "axes":
                button.toggled.connect(window.scene.set_local_axes_visible)
            elif kind == "solid":
                button.toggled.connect(self._on_solid_visibility_toggled)
            elif kind == "releases":
                button.toggled.connect(window.scene.set_member_releases_visible)
            elif kind == "semirigid":
                button.toggled.connect(window.scene.set_semirigid_links_visible)
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
            self._visibility_buttons[kind] = button

        scene_button = QToolButton(self)
        scene_button.setFixedSize(24, 24)
        self._scene_icons = {
            False: QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "eye-closed.svg")),
            True: QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "eye.svg")),
        }
        scene_button.setIcon(self._scene_icons[False])
        scene_button.setIconSize(QSize(19, 19))
        scene_tooltip = _command_tooltip("Cena", "SCENE")
        scene_button.setToolTip(scene_tooltip)
        scene_button.setProperty("paletteTooltip", scene_tooltip)
        scene_button.setAccessibleName("Cena")
        scene_button.setCheckable(True)
        scene_button.setChecked(False)
        scene_button.toggled.connect(self._on_scene_toggled)
        scene_button.installEventFilter(self)
        scene_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(scene_button)
        self.scene_button = scene_button
        self.scene_palette = QFrame(window)
        self.scene_palette.setObjectName("scenePalette")
        self.scene_palette.setStyleSheet(
            "QFrame#scenePalette { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; }"
            "QComboBox { min-width: 120px; min-height: 24px; padding: 0 8px; border: 0; "
            "border-radius: 6px; background: #d0d7de; color: #24292f; }"
            "QComboBox:hover { background: #afb8c1; }"
            "QComboBox::drop-down { width: 22px; border: 0; }"
            "QComboBox QAbstractItemView { border: 1px solid #d0d7de; background: #ffffff; "
            "selection-background-color: #d0d7de; selection-color: #24292f; }"
            "QToolButton { min-width: 30px; min-height: 24px; border: 0; border-radius: 5px; "
            "background: transparent; color: #24292f; }"
            "QToolButton:hover { background: #eaeef2; }"
        )
        scene_palette_layout = QHBoxLayout(self.scene_palette)
        scene_palette_layout.setContentsMargins(4, 4, 4, 4)
        scene_palette_layout.setSpacing(3)
        self.scene_view_selector = QComboBox(self.scene_palette)
        self.scene_view_selector.addItem("Completo")
        self.scene_view_selector.setToolTip("Vista da cena")
        self.scene_view_selector.setAccessibleName("Vista da cena")
        self.scene_view_selector.currentTextChanged.connect(self._on_scene_view_selected)
        scene_palette_layout.addWidget(self.scene_view_selector)
        self.add_scene_view_button = self._scene_view_action_button(
            "plus.svg", "Adicionar vista", self._add_scene_view
        )
        scene_palette_layout.addWidget(self.add_scene_view_button)
        self.remove_scene_view_button = self._scene_view_action_button(
            "minus.svg", "Remover vista", self._remove_scene_view
        )
        scene_palette_layout.addWidget(self.remove_scene_view_button)
        self.rename_scene_view_button = self._scene_view_action_button(
            "pencil.svg", "Renomear vista", self._rename_scene_view
        )
        scene_palette_layout.addWidget(self.rename_scene_view_button)

        scene_separator = QFrame(self.scene_palette)
        scene_separator.setFrameShape(QFrame.Shape.VLine)
        scene_separator.setFrameShadow(QFrame.Shadow.Plain)
        scene_separator.setFixedHeight(18)
        scene_separator.setStyleSheet("QFrame { color: #d0d7de; }")
        scene_palette_layout.addWidget(scene_separator, 0, Qt.AlignmentFlag.AlignVCenter)

        self.hide_scene_items_button = self._scene_view_action_button(
            "lightbulb-off.svg", "Ocultar", window.start_scene_hide_selection
        )
        scene_palette_layout.addWidget(self.hide_scene_items_button)
        self.show_hidden_items_button = self._scene_view_action_button(
            "lightbulb.svg", "Reexibir", window.start_scene_reveal_selection
        )
        scene_palette_layout.addWidget(self.show_hidden_items_button)
        self.show_all_button = self._scene_view_action_button(
            "lightbulb-all.svg", "Reexibir tudo", window.show_all_scene_members
        )
        scene_palette_layout.addWidget(self.show_all_button)
        self._update_scene_view_actions()
        self.scene_palette.hide()

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setFixedHeight(18)
        separator.setStyleSheet("QFrame { color: #d0d7de; }")
        layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)

        configure_axes_button = QToolButton(self)
        configure_axes_button.setFixedSize(24, 24)
        configure_axes_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "axis-configuration.svg"))
        )
        configure_axes_button.setIconSize(QSize(19, 19))
        configure_axes_tooltip = _command_tooltip("Configurar eixos", "CONFIGAXES")
        configure_axes_button.setToolTip(configure_axes_tooltip)
        configure_axes_button.setProperty("paletteTooltip", configure_axes_tooltip)
        configure_axes_button.setAccessibleName("Configurar eixos")
        configure_axes_button.setCheckable(True)
        configure_axes_button.clicked.connect(window.toggle_axes_panel)
        configure_axes_button.installEventFilter(self)
        configure_axes_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        self.configure_axes_button = configure_axes_button

        configure_reference_button = QToolButton(self)
        configure_reference_button.setFixedSize(24, 24)
        configure_reference_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources/icons/scan-box.svg"))
        )
        configure_reference_button.setIconSize(QSize(19, 19))
        configure_reference_tooltip = _command_tooltip("Configurar referência", "CONFIGREFERENCE")
        configure_reference_button.setToolTip(configure_reference_tooltip)
        configure_reference_button.setProperty("paletteTooltip", configure_reference_tooltip)
        configure_reference_button.setAccessibleName("Configurar referência")
        configure_reference_button.setCheckable(True)
        configure_reference_button.clicked.connect(window.toggle_reference_panel)
        configure_reference_button.installEventFilter(self)
        configure_reference_button.setStyleSheet(configure_axes_button.styleSheet())
        layout.addWidget(configure_reference_button)
        self.configure_reference_button = configure_reference_button
        layout.addWidget(configure_axes_button)

        add_member_button = QToolButton(self)
        add_member_button.setFixedSize(24, 24)
        add_member_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "member-spline.svg"))
        )
        add_member_button.setIconSize(QSize(19, 19))
        add_member_tooltip = _command_tooltip("Adicionar barra", "BAR")
        add_member_button.setToolTip(add_member_tooltip)
        add_member_button.setProperty("paletteTooltip", add_member_tooltip)
        add_member_button.setAccessibleName("Adicionar barra")
        add_member_button.clicked.connect(window.start_member_placement)
        add_member_button.installEventFilter(self)
        add_member_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(add_member_button)
        self.add_member_button = add_member_button

        split_member_button = QToolButton(self)
        split_member_button.setFixedSize(24, 24)
        split_member_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "split-member.svg"))
        )
        split_member_button.setIconSize(QSize(19, 19))
        split_member_tooltip = _command_tooltip("Dividir barra", "SPLIT")
        split_member_button.setToolTip(split_member_tooltip)
        split_member_button.setProperty("paletteTooltip", split_member_tooltip)
        split_member_button.setAccessibleName("Dividir barra")
        split_member_button.clicked.connect(window.start_split_member)
        split_member_button.installEventFilter(self)
        split_member_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(split_member_button)
        self.split_member_button = split_member_button

        reverse_member_button = QToolButton(self)
        reverse_member_button.setFixedSize(24, 24)
        reverse_member_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "reverse-member.svg"))
        )
        reverse_member_button.setIconSize(QSize(19, 19))
        reverse_member_tooltip = _command_tooltip("Inverter barra", "REVERSE")
        reverse_member_button.setToolTip(reverse_member_tooltip)
        reverse_member_button.setProperty("paletteTooltip", reverse_member_tooltip)
        reverse_member_button.setAccessibleName("Inverter barra")
        reverse_member_button.clicked.connect(window.start_reverse_member)
        reverse_member_button.installEventFilter(self)
        reverse_member_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(reverse_member_button)
        self.reverse_member_button = reverse_member_button

        join_members_button = QToolButton(self)
        join_members_button.setFixedSize(24, 24)
        join_members_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "join-member-link.svg"))
        )
        join_members_button.setIconSize(QSize(19, 19))
        join_members_tooltip = _command_tooltip("Unir barras", "JOIN")
        join_members_button.setToolTip(join_members_tooltip)
        join_members_button.setProperty("paletteTooltip", join_members_tooltip)
        join_members_button.setAccessibleName("Unir barras")
        join_members_button.clicked.connect(window.start_join_members)
        join_members_button.installEventFilter(self)
        join_members_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.insertWidget(layout.indexOf(reverse_member_button), join_members_button)
        self.join_members_button = join_members_button

        rigid_member_button = QToolButton(self)
        rigid_member_button.setFixedSize(24, 24)
        rigid_member_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "rigid-member.svg"))
        )
        rigid_member_button.setIconSize(QSize(19, 19))
        rigid_member_tooltip = _command_tooltip("Adicionar barra rígida", "RIGID")
        rigid_member_button.setToolTip(rigid_member_tooltip)
        rigid_member_button.setProperty("paletteTooltip", rigid_member_tooltip)
        rigid_member_button.setAccessibleName("Adicionar barra rígida")
        rigid_member_button.clicked.connect(window.start_rigid_bar_placement)
        rigid_member_button.installEventFilter(self)
        rigid_member_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.insertWidget(layout.indexOf(join_members_button) + 1, rigid_member_button)
        self.rigid_member_button = rigid_member_button

        copy_properties_button = QToolButton(self)
        copy_properties_button.setFixedSize(24, 24)
        copy_properties_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "copy-member-properties.svg"))
        )
        copy_properties_button.setIconSize(QSize(19, 19))
        copy_properties_tooltip = _command_tooltip("Copiar propriedades", "CPROP")
        copy_properties_button.setToolTip(copy_properties_tooltip)
        copy_properties_button.setProperty("paletteTooltip", copy_properties_tooltip)
        copy_properties_button.setAccessibleName("Copiar propriedades")
        copy_properties_button.clicked.connect(window.start_copy_member_properties)
        copy_properties_button.installEventFilter(self)
        copy_properties_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(copy_properties_button)
        self.copy_properties_button = copy_properties_button

        measure_button = QToolButton(self)
        measure_button.setFixedSize(24, 24)
        measure_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "ruler.svg"))
        )
        measure_button.setIconSize(QSize(19, 19))
        measure_tooltip = _command_tooltip("Medir", "MEASURE")
        measure_button.setToolTip(measure_tooltip)
        measure_button.setProperty("paletteTooltip", measure_tooltip)
        measure_button.setAccessibleName("Medir")
        measure_button.clicked.connect(window.start_measurement)
        measure_button.installEventFilter(self)
        measure_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.addWidget(measure_button)
        self.measure_button = measure_button

        copy_elements_button = QToolButton(self)
        copy_elements_button.setFixedSize(24, 24)
        copy_elements_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "copy.svg"))
        )
        copy_elements_button.setIconSize(QSize(19, 19))
        copy_elements_tooltip = _command_tooltip("Copiar elementos", "COPY")
        copy_elements_button.setToolTip(copy_elements_tooltip)
        copy_elements_button.setProperty("paletteTooltip", copy_elements_tooltip)
        copy_elements_button.setAccessibleName("Copiar elementos")
        copy_elements_button.clicked.connect(window.start_copy_elements)
        copy_elements_button.installEventFilter(self)
        copy_elements_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout.insertWidget(layout.indexOf(copy_properties_button), copy_elements_button)
        self.copy_elements_button = copy_elements_button
        self.adjustSize()

    def _on_scene_toggled(self, active: bool) -> None:
        self.scene_button.setIcon(self._scene_icons[bool(active)])
        self._position_scene_palette()
        self.scene_palette.setVisible(bool(active) and self.isVisible())
        if active:
            self.scene_palette.raise_()

    def _position_scene_palette(self) -> None:
        button_position = self.scene_button.mapTo(self._window, QPoint(0, self.scene_button.height() + 8))
        self.scene_palette.adjustSize()
        x = button_position.x() + (self.scene_button.width() - self.scene_palette.width()) // 2
        x = max(8, min(x, self._window.width() - self.scene_palette.width() - 8))
        self.scene_palette.move(
            x,
            button_position.y(),
        )

    def _scene_view_action_button(self, icon_filename: str, tooltip: str, callback=None) -> QToolButton:
        button = QToolButton(self.scene_palette)
        button.setFixedSize(24, 24)
        button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_filename)))
        button.setIconSize(QSize(17, 17))
        button.setToolTip(tooltip)
        button.setProperty("paletteTooltip", tooltip)
        button.setAccessibleName(tooltip)
        if callback is not None:
            button.clicked.connect(callback)
        button.installEventFilter(self)
        return button

    def _update_scene_view_actions(self, *_args) -> None:
        selected_view = self.scene_view_selector.currentText()
        can_edit = bool(selected_view) and selected_view != "Completo"
        self.remove_scene_view_button.setEnabled(can_edit)
        self.rename_scene_view_button.setEnabled(can_edit)
        self.hide_scene_items_button.setEnabled(can_edit)
        self.show_hidden_items_button.setEnabled(can_edit)
        self.show_all_button.setEnabled(can_edit)

    def reload_scene_views(self) -> None:
        with QSignalBlocker(self.scene_view_selector):
            self.scene_view_selector.clear()
            self.scene_view_selector.addItems(self._window.model.scene_views)
            self.scene_view_selector.setCurrentText(self._window.model.active_scene_view)
        self._update_scene_view_actions()

    def _on_scene_view_selected(self, name: str) -> None:
        self._update_scene_view_actions()
        if name:
            self._window.select_scene_view(name)

    def _scene_view_name_dialog(self, title: str, initial_name: str = "") -> tuple[bool, str]:
        dialog = QInputDialog(self._window)
        dialog.setWindowTitle(title)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dialog.setLabelText("Nome da vista:")
        dialog.setTextValue(initial_name)
        dialog.setOkButtonText("Salvar")
        dialog.setCancelButtonText("Cancelar")
        dialog.setStyleSheet(
            "QInputDialog { background: #ffffff; border: 0; }"
            "QLabel { color: #57606a; }"
            "QLineEdit { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px; "
            "padding: 2px 9px; background: #ffffff; }"
            "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px; "
            "background: #f6f8fa; color: #57606a; }"
            "QPushButton:hover { background: #eaeef2; }"
        )
        for dialog_button in dialog.findChildren(QPushButton):
            dialog_button.setIcon(QIcon())
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return accepted, dialog.textValue().strip()

    def _add_scene_view(self) -> None:
        accepted, name = self._scene_view_name_dialog("Adicionar vista")
        existing_names = {
            self.scene_view_selector.itemText(index)
            for index in range(self.scene_view_selector.count())
        }
        if accepted and name and name not in existing_names:
            self._window.model.add_scene_view(name)
            self.reload_scene_views()
            self._window.select_scene_view(name)

    def _remove_scene_view(self) -> None:
        index = self.scene_view_selector.currentIndex()
        if index <= 0:
            return
        self._window.cancel_member_placement()
        self._window.model.remove_scene_view(self.scene_view_selector.itemText(index))
        self.reload_scene_views()
        self._window.scene.render_model(self._window.model)
        self._window.clear_selection()

    def _rename_scene_view(self) -> None:
        index = self.scene_view_selector.currentIndex()
        if index <= 0:
            return
        current_name = self.scene_view_selector.itemText(index)
        accepted, name = self._scene_view_name_dialog("Renomear vista", current_name)
        existing_names = {
            self.scene_view_selector.itemText(item_index)
            for item_index in range(self.scene_view_selector.count())
            if item_index != index
        }
        if accepted and name and name not in existing_names:
            self._window.model.rename_scene_view(current_name, name)
            self.reload_scene_views()

    def _on_solid_visibility_toggled(self, visible: bool) -> None:
        if visible:
            self._solid_node_states = {
                kind: (self._visibility_buttons[kind].isChecked(), self._visibility_buttons[kind].isEnabled())
                for kind in ("nodes", "node")
            }
            for kind in self._solid_node_states:
                button = self._visibility_buttons[kind]
                button.setChecked(False)
                button.setEnabled(False)
        self._window.scene.set_solid_members_visible(visible)
        if not visible and self._solid_node_states is not None:
            for kind, (checked, enabled) in self._solid_node_states.items():
                button = self._visibility_buttons[kind]
                button.setEnabled(enabled)
                button.setChecked(checked)
            self._solid_node_states = None

    def toggle_visibility_command(self, kind: str) -> None:
        button = self._visibility_buttons.get(kind)
        if button is not None and button.isEnabled():
            button.setChecked(not button.isChecked())

    def set_view_option(self, option: str, visible: bool) -> None:
        kind = {
            "grid_visible": "grid",
            "reference_axes_visible": "reference-axes",
            "node_labels_visible": "node",
            "member_labels_visible": "bar",
            "local_axes_visible": "axes",
            "nodes_visible": "nodes",
            "solid_members_visible": "solid",
            "member_releases_visible": "releases",
            "semirigid_links_visible": "semirigid",
            "node_supports_visible": "supports",
        }.get(option)
        if kind is not None:
            button = self._visibility_buttons.get(kind)
            if button is not None and button.isEnabled():
                button.setChecked(bool(visible))

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
        self.scene_palette.setVisible(visible and self.scene_button.isChecked())
        if visible and self.scene_button.isChecked():
            self._position_scene_palette()
            self.scene_palette.raise_()

    def set_member_direction_normalization_enabled(self, enabled: bool) -> None:
        """Disable manual reversal while automatic normalization is active."""
        self.reverse_member_button.setEnabled(not enabled)

    def reposition(self) -> None:
        margin = 0 if self.window().isMaximized() else WindowFrame.MARGIN
        self.move((self.window().width() - self.width()) // 2, margin + 52)
        self.raise_()
        self._position_scene_palette()
        if self.scene_button.isChecked() and self.isVisible():
            self.scene_palette.raise_()


class ActionTopPalette(QFrame):
    """Barra superior contextual para a edição de ações estruturais."""

    class ActionSelector(QComboBox):
        """Seletor que mostra o indicador de peso próprio dentro do campo."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._weight_rows: set[int] = set()
            self.setIconSize(QSize(15, 15))
            self._weight_icon = QIcon(
                str(Path(__file__).parents[1] / "resources" / "icons" / "weight.svg")
            )

        def set_weight_rows(self, rows: set[int]) -> None:
            self._weight_rows = set(rows)
            for index in range(self.count()):
                self.setItemIcon(index, self._weight_icon if index in self._weight_rows else QIcon())
            self.update()

        def set_selfweight_active(self, active: bool) -> None:
            index = self.currentIndex()
            if index < 0:
                return
            if active:
                self._weight_rows.add(index)
                self.setItemIcon(index, self._weight_icon)
            else:
                self._weight_rows.discard(index)
                self.setItemIcon(index, QIcon())
            self.update()

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("topIconPalette")
        self.setStyleSheet(
            "QFrame#topIconPalette { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; }"
            "QComboBox { min-width: 210px; min-height: 24px; padding: 0 8px; border: 0; "
            "border-radius: 6px; background: #d0d7de; color: #24292f; }"
            "QComboBox:hover { background: #afb8c1; }"
            "QComboBox::drop-down { width: 22px; border: 0; }"
            "QComboBox QAbstractItemView { border: 1px solid #d0d7de; background: #ffffff; "
            "selection-background-color: #d0d7de; selection-color: #24292f; }"
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._tooltip = PaletteTooltip(window)
        self.action_selector = self.ActionSelector(self)
        self.action_selector.setToolTip("Ação ativa")
        self.action_selector.setAccessibleName("Ação ativa")
        self.action_selector.currentTextChanged.connect(window._select_active_action)
        layout.addWidget(self.action_selector)

        self._action_visibility_buttons: dict[str, QToolButton] = {}
        for filename, tooltip, kind in (
            ("node-force.svg", "Forças nos nós", "node_forces"),
            ("node-moment.svg", "Momentos nos nós", "node_moments"),
            ("member-force.svg", "Forças nas barras", "member_forces"),
            ("member-moment.svg", "Momentos nas barras", "member_moments"),
        ):
            button = QToolButton(self)
            button.setFixedSize(24, 24)
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / filename)))
            button.setIconSize(QSize(19, 19))
            command = {
                "node_forces": "NODEFORCE",
                "node_moments": "NODEMOMENT",
                "member_forces": "MEMBERFORCE",
                "member_moments": "MEMBERMOMENT",
            }[kind]
            palette_tooltip = _command_tooltip(tooltip, command)
            button.setToolTip(palette_tooltip)
            button.setProperty("paletteTooltip", palette_tooltip)
            button.setAccessibleName(tooltip)
            button.setCheckable(True)
            button.setChecked(True)
            button.toggled.connect(
                lambda visible, action_kind=kind: window.scene.set_action_visibility(action_kind, visible)
            )
            button.installEventFilter(self)
            layout.addWidget(button)
            self._action_visibility_buttons[kind] = button

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setFixedHeight(18)
        separator.setStyleSheet("QFrame { color: #d0d7de; }")
        layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)

        group_actions_button = QToolButton(self)
        group_actions_button.setFixedSize(24, 24)
        group_actions_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "group-actions.svg"))
        )
        group_actions_button.setIconSize(QSize(19, 19))
        group_actions_tooltip = _command_tooltip("Grupo de ações", "GROUP")
        group_actions_button.setToolTip(group_actions_tooltip)
        group_actions_button.setProperty("paletteTooltip", group_actions_tooltip)
        group_actions_button.setAccessibleName("Grupo de ações")
        group_actions_button.clicked.connect(window.open_action_groups)
        group_actions_button.installEventFilter(self)
        layout.addWidget(group_actions_button)
        self.group_actions_button = group_actions_button

        add_action_button = QToolButton(self)
        add_action_button.setFixedSize(24, 24)
        add_action_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "add-action.svg"))
        )
        add_action_button.setIconSize(QSize(19, 19))
        add_action_tooltip = _command_tooltip("Adicionar ação", "ACTION")
        add_action_button.setToolTip(add_action_tooltip)
        add_action_button.setProperty("paletteTooltip", add_action_tooltip)
        add_action_button.setAccessibleName("Adicionar ação")
        add_action_button.clicked.connect(window.start_load_command)
        add_action_button.installEventFilter(self)
        layout.addWidget(add_action_button)
        self.add_action_button = add_action_button

        # Botão de aplicação do peso próprio.
        self.selfweight_button = QToolButton(self)
        self.selfweight_button.setObjectName("selfweightButton")
        self.selfweight_button.setFixedSize(24, 24)
        self.selfweight_button.setIcon(QIcon(str(
            Path(__file__).parents[1] / "resources" / "icons" / "selfweight.svg"
        )))
        self.selfweight_button.setIconSize(QSize(19, 19))
        selfweight_tooltip = _command_tooltip("Aplicar peso próprio", "SELFWEIGHT")
        self.selfweight_button.setToolTip(selfweight_tooltip)
        self.selfweight_button.setProperty("paletteTooltip", selfweight_tooltip)
        self.selfweight_button.setAccessibleName("Aplicar peso próprio")
        self.selfweight_button.clicked.connect(window.start_selfweight_command)
        self.selfweight_button.installEventFilter(self)
        layout.addWidget(self.selfweight_button)
        self.adjustSize()

    def toggle_action_visibility_command(self, kind: str) -> None:
        button = self._action_visibility_buttons.get(kind)
        if button is not None:
            button.setChecked(not button.isChecked())

    def set_view_option(self, option: str, visible: bool) -> None:
        kind = {
            "node_forces_visible": "node_forces",
            "node_moments_visible": "node_moments",
            "member_forces_visible": "member_forces",
            "member_moments_visible": "member_moments",
        }.get(option)
        if kind is not None:
            button = self._action_visibility_buttons.get(kind)
            if button is not None:
                button.setChecked(bool(visible))

    def set_actions(
        self,
        action_names: tuple[str, ...],
        selected_name: str | None = None,
        selfweight_names: set[str] | frozenset[str] = frozenset(),
    ) -> None:
        self.action_selector.blockSignals(True)
        self.action_selector.clear()
        self.action_selector.addItems(action_names)
        self.action_selector.set_weight_rows({
            index for index, name in enumerate(action_names) if name in selfweight_names
        })
        index = self.action_selector.findText(selected_name or "", Qt.MatchFlag.MatchExactly)
        self.action_selector.setCurrentIndex(index if index >= 0 else (0 if action_names else -1))
        self.action_selector.blockSignals(False)
        self.adjustSize()

    def set_selfweight_active(self, active: bool) -> None:
        self.action_selector.set_selfweight_active(active)
        self.adjustSize()

    def set_actions_visible(self, visible: bool) -> None:
        if not visible:
            self._tooltip.dismiss()
        self.setVisible(visible)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QToolButton):
            if event.type() == QEvent.Type.Enter:
                self._tooltip.schedule_below(watched, watched.property("paletteTooltip"))
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def reposition(self) -> None:
        margin = 0 if self.window().isMaximized() else WindowFrame.MARGIN
        self.move((self.window().width() - self.width()) // 2, margin + 52)
        self.raise_()


class AnalysisTopPalette(QFrame):
    """Barra contextual de combinação e diagrama para a seção Análise."""

    diagram_options = (
        "Normal", "Cortante Y", "Cortante Z", "Torsor", "Fletor Y", "Fletor Z",
        "Reações de apoio", "Deformação X", "Deformação Y", "Deformação Z", "Deformação XYZ",
    )

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.setObjectName("topIconPalette")
        self.setStyleSheet(
            "QFrame#topIconPalette { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px; }"
            "QComboBox { min-width: 184px; min-height: 24px; padding: 0 8px; border: 0; "
            "border-radius: 6px; background: #d0d7de; color: #24292f; }"
            "QComboBox:hover { background: #afb8c1; }"
            "QComboBox::drop-down { width: 22px; border: 0; }"
            "QComboBox QAbstractItemView { border: 1px solid #d0d7de; background: #ffffff; "
            "selection-background-color: #d0d7de; selection-color: #24292f; }"
            "QFrame#analysisPending { min-width: 376px; min-height: 24px; border: 0; border-radius: 6px; "
            "background: #d0d7de; }"
            "QLabel#analysisPendingLabel { color: #57606a; padding: 0 8px; }"
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._tooltip = PaletteTooltip(window)
        self.selectors = QWidget(self)
        selectors_layout = QHBoxLayout(self.selectors)
        selectors_layout.setContentsMargins(0, 0, 0, 0)
        selectors_layout.setSpacing(4)
        self.combination_selector = QComboBox(self)
        self.combination_selector.setToolTip("Combinação de carga para os diagramas")
        self.combination_selector.setAccessibleName("Combinação de análise")
        self.combination_selector.currentTextChanged.connect(window._select_analysis_combination)
        self.diagram_selector = QComboBox(self)
        self.diagram_selector.addItems(self.diagram_options)
        self.diagram_selector.setToolTip(
            "Tipo de diagrama a exibir. Y e Z referem-se aos eixos locais de cada barra."
        )
        self.diagram_selector.setAccessibleName("Tipo de diagrama")
        self.diagram_selector.currentTextChanged.connect(window._select_analysis_diagram)
        selectors_layout.addWidget(self.combination_selector)
        selectors_layout.addWidget(self.diagram_selector)

        result_diagrams_button = QToolButton(self)
        result_diagrams_button.setFixedSize(24, 24)
        result_diagrams_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "result-diagram.svg"))
        )
        result_diagrams_button.setIconSize(QSize(17, 17))
        result_diagrams_tooltip = "Diagrama dos resultados"
        result_diagrams_button.setToolTip(result_diagrams_tooltip)
        result_diagrams_button.setProperty("paletteTooltip", result_diagrams_tooltip)
        result_diagrams_button.setAccessibleName(result_diagrams_tooltip)
        result_diagrams_button.setCheckable(True)
        result_diagrams_button.setChecked(True)
        result_diagrams_button.toggled.connect(window.scene.set_analysis_diagrams_visible)
        result_diagrams_button.installEventFilter(self)
        selectors_layout.addWidget(result_diagrams_button)
        self.result_diagrams_button = result_diagrams_button
        self.diagram_selector.currentTextChanged.connect(self._update_result_diagrams_button)
        self._update_result_diagrams_button(self.diagram_selector.currentText())
        self.pending = QFrame(self)
        self.pending.setObjectName("analysisPending")
        pending_layout = QHBoxLayout(self.pending)
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_label = QLabel("A estrutura não foi analisada.")
        pending_label.setObjectName("analysisPendingLabel")
        pending_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pending_layout.addWidget(pending_label)
        layout.addWidget(self.selectors)
        layout.addWidget(self.pending)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setFixedHeight(18)
        separator.setStyleSheet("QFrame { color: #d0d7de; }")
        layout.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)

        combinations_button = QToolButton(self)
        combinations_button.setFixedSize(24, 24)
        combinations_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "add-combination.svg"))
        )
        combinations_button.setIconSize(QSize(19, 19))
        combinations_tooltip = _command_tooltip("Configurar combinações", "COMBINATIONS")
        combinations_button.setToolTip(combinations_tooltip)
        combinations_button.setProperty("paletteTooltip", combinations_tooltip)
        combinations_button.setAccessibleName("Configurar combinações")
        combinations_button.clicked.connect(window.open_combinations)
        combinations_button.installEventFilter(self)
        layout.addWidget(combinations_button)
        self.combinations_button = combinations_button

        process_button = QToolButton(self)
        process_button.setFixedSize(24, 24)
        process_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "process-analysis.svg"))
        )
        process_button.setIconSize(QSize(19, 19))
        process_tooltip = _command_tooltip("Analisar estrutura", "ANALYZE")
        process_button.setToolTip(process_tooltip)
        process_button.setProperty("paletteTooltip", process_tooltip)
        process_button.setAccessibleName("Analisar estrutura")
        process_button.clicked.connect(window.process_analysis)
        process_button.installEventFilter(self)
        layout.addWidget(process_button)
        self.process_button = process_button
        self.adjustSize()

    def set_combinations(self, names: tuple[str, ...], selected_name: str | None = None) -> None:
        self.combination_selector.blockSignals(True)
        self.combination_selector.clear()
        self.combination_selector.addItems(names)
        index = self.combination_selector.findText(selected_name or "", Qt.MatchFlag.MatchExactly)
        self.combination_selector.setCurrentIndex(index if index >= 0 else (0 if names else -1))
        self.combination_selector.blockSignals(False)
        self.adjustSize()

    def set_analysis_ready(self, ready: bool) -> None:
        self.selectors.setVisible(ready)
        self.pending.setVisible(not ready)
        self.adjustSize()

    def reset_result_view(self) -> None:
        """Return to the neutral view when analysis results are unavailable."""
        self.diagram_selector.blockSignals(True)
        self.diagram_selector.setCurrentText("Normal")
        self.diagram_selector.blockSignals(False)
        self._update_result_diagrams_button(self.diagram_selector.currentText())

    def _update_result_diagrams_button(self, result_type: str) -> None:
        """The result-visibility toggle does not apply to deformation views."""
        self.result_diagrams_button.setEnabled(not result_type.startswith("Deformação"))

    def set_analysis_visible(self, visible: bool) -> None:
        if not visible:
            self._tooltip.dismiss()
        self.setVisible(visible)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QToolButton):
            if event.type() == QEvent.Type.Enter:
                self._tooltip.schedule_below(watched, watched.property("paletteTooltip"))
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)

    def reposition(self) -> None:
        margin = 0 if self.window().isMaximized() else WindowFrame.MARGIN
        self.move((self.window().width() - self.width()) // 2, margin + 52)
        self.raise_()
