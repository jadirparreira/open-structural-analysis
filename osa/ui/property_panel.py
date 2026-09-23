from math import isfinite

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator

from .color_palette import HoneycombColorPalette
from .common import *
from .window_frame import WindowFrame


class PropertyPanel(QFrame):
    """Floating inspector for the currently selected node or bar."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(238)
        self._selected: tuple[str, str] | None = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(7)
        self.title = QLabel()
        self.title.setObjectName("propertyTitle")
        self.name = QLabel()
        self.name.setObjectName("propertySection")
        self.identity_value = QLineEdit()
        self.identity_value.setReadOnly(True)
        self.identity_value.setObjectName("identityDisplay")
        identity_row = QWidget()
        identity_layout = QHBoxLayout(identity_row)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(6)
        identity_layout.addWidget(self.identity_value, 1)
        self.member_color_button = QToolButton()
        self.member_color_button.setFixedSize(34, 34)
        self.member_color_button.setToolTip("Definir cor do membro")
        self.member_color_button.setAccessibleName("Definir cor do membro")
        self.member_color_button.clicked.connect(self._toggle_color_palette)
        identity_layout.addWidget(self.member_color_button)
        self.delete_button = QToolButton()
        self.delete_button.setFixedSize(34, 34)
        self.delete_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "delete.svg")))
        self.delete_button.setIconSize(QSize(18, 18))
        self.delete_button.setToolTip("Excluir elemento")
        self.delete_button.setAccessibleName("Excluir elemento")
        self.delete_button.clicked.connect(self._delete_requested)
        self.delete_button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:disabled { background: #f6f8fa; border-color: #eaeef2; }"
        )
        identity_layout.addWidget(self.delete_button)
        self._color_palette = HoneycombColorPalette(self.window, self._color_selected)
        self.layout.addWidget(self.title)
        self.layout.addWidget(self.name)
        self.layout.addWidget(identity_row)
        self.coordinates_title = QLabel("Coordenadas")
        self.coordinates_title.setObjectName("propertySection")
        self.nodes_title = QLabel("Nós")
        self.nodes_title.setObjectName("propertySection")
        self.rotation_title = QLabel("Rotação")
        self.rotation_title.setObjectName("propertySection")
        self.releases_title = QLabel("Vinculações")
        self.releases_title.setObjectName("propertySection")
        self.supports_title = QLabel("Restrições")
        self.supports_title.setObjectName("propertySection")
        self.form = QFormLayout()
        self.form.setSpacing(7)
        self.layout.addLayout(self.form)
        self.fields: list[QDoubleSpinBox | QComboBox] = []
        self._coordinates_widget: QWidget | None = None
        self._supports_widget: QWidget | None = None
        self._rotation_box: QFrame | None = None
        self._rotation_input: QLineEdit | None = None
        self._releases_widget: QWidget | None = None
        self._release_boxes: list[QCheckBox] = []
        self._material_widget: QWidget | None = None
        self._section_label: QLabel | None = None
        self._section_combo: QComboBox | None = None
        self._section_container: QWidget | None = None
        self._section_profile_display: QLineEdit | None = None
        self._section_settings_button: QToolButton | None = None
        self._context_widgets: list[QWidget] = []
        self._member_action_reference = "global"
        self._member_action_inputs: dict[str, QLineEdit] = {}
        self._node_action_inputs: dict[str, QLineEdit] = {}
        self._member_action_switch_indicator: QFrame | None = None
        self._member_action_switch_buttons: dict[str, QToolButton] = {}
        self._member_action_switch_animation: QPropertyAnimation | None = None
        self._identity_row = identity_row
        self.delete_button.setEnabled(False)
        self.hide()

    def show_for(self, kind: str, name: str, section: str = "Geometria") -> None:
        """Show the inspector content that belongs to the open work section."""
        self._selected = kind, name
        self._clear_form()
        self.coordinates_title.hide()
        self.nodes_title.hide()
        self.rotation_title.hide()
        self.releases_title.hide()
        self.supports_title.hide()
        self._color_palette.hide()
        self.member_color_button.setVisible(kind == "bar")
        self.update_delete_button_state()
        self.title.setText("Nó" if kind == "node" else "Membro")
        self.name.setText("Identidade")
        self.identity_value.setText(name)
        if kind == "bar":
            self._set_member_color_button(self.window.model.bars[name].color)

        if section == "Ações":
            self._show_actions(kind, name, select_available_reference=True)
        elif section == "Análise":
            self._show_analysis(kind, name)
        elif kind == "node":
            node = self.window.model.nodes[name]
            self.layout.insertWidget(3, self.coordinates_title)
            self.coordinates_title.show()
            for axis, value in zip(("X", "Y", "Z"), (node.x, node.y, node.z)):
                field = QDoubleSpinBox()
                field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                field.setRange(-1_000_000.0, 1_000_000.0)
                field.setDecimals(3)
                field.setSingleStep(0.1)
                field.setValue(value)
                field.valueChanged.connect(lambda _value, axis=axis: self._node_changed(axis))
                self.fields.append(field)
                axis_label = QLabel(axis)
                axis_label.setObjectName("propertySection")
                self.form.addRow(axis_label, field)
            self.layout.insertWidget(5, self.supports_title)
            self.supports_title.show()
            supports = QWidget()
            self._supports_widget = supports
            supports_layout = QVBoxLayout(supports)
            supports_layout.setContentsMargins(0, 0, 0, 0)
            supports_layout.setSpacing(4)
            for index, label in enumerate(("Dx", "Dy", "Dz", "Rx", "Ry", "Rz")):
                checkbox = QCheckBox(label)
                checkbox.setChecked(node.supports[index])
                checkbox.stateChanged.connect(lambda _state, idx=index: self._support_changed(idx))
                value = QDoubleSpinBox()
                value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                value.setDecimals(3)
                value.setRange(0.0, 1_000_000.0)
                value.setSpecialValueText("")
                value.setValue(0.0)
                value.setFixedWidth(112)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(checkbox)
                row.addStretch(1)
                row.addWidget(value)
                supports_layout.addLayout(row)
            self.layout.insertWidget(6, supports)
        else:
            bar = self.window.model.bars[name]
            nodes = list(self.window.model.nodes)
            self.layout.insertWidget(3, self.nodes_title)
            self.nodes_title.show()
            start, end = QComboBox(), QComboBox()
            start.addItems(nodes); end.addItems(nodes)
            for combo in (start, end):
                combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                combo.view().setMinimumHeight(min(5, len(nodes)) * 28 + 2)
                combo.view().setMaximumHeight(min(5, len(nodes)) * 28 + 2)
            start.setCurrentText(bar.start_node); end.setCurrentText(bar.end_node)
            start.currentTextChanged.connect(self._bar_changed)
            end.currentTextChanged.connect(self._bar_changed)
            self.fields.extend((start, end))
            start_label = QLabel("A")
            start_label.setObjectName("propertySection")
            end_label = QLabel("B")
            end_label.setObjectName("propertySection")
            endpoints = QWidget()
            endpoint_grid = QGridLayout(endpoints)
            endpoint_grid.setContentsMargins(0, 0, 0, 0)
            endpoint_grid.setHorizontalSpacing(8)
            endpoint_grid.addWidget(start_label, 0, 0)
            endpoint_grid.addWidget(start, 0, 1)
            endpoint_grid.addWidget(end_label, 0, 2)
            endpoint_grid.addWidget(end, 0, 3)
            endpoint_grid.setColumnStretch(1, 1)
            endpoint_grid.setColumnStretch(3, 1)
            self.form.addRow(endpoints)
            material_widget = QWidget()
            self._material_widget = material_widget
            material_layout = QVBoxLayout(material_widget)
            material_layout.setContentsMargins(0, 8, 0, 0)
            material_layout.setSpacing(5)
            material_title = QLabel("Material")
            material_title.setObjectName("propertySection")
            material_layout.addWidget(material_title)
            material_combo = QComboBox()
            material_combo.addItems(self.window.model.materials)
            material_combo.setPlaceholderText("Indefinido")
            material_combo.setCurrentText(bar.material if bar.material in self.window.model.materials else "")
            if bar.material not in self.window.model.materials:
                material_combo.setCurrentIndex(-1)
            material_layout.addWidget(material_combo)
            material_combo.currentTextChanged.connect(self._material_selected)
            self.layout.addWidget(material_widget)
            section_label = QLabel("Seção")
            section_label.setObjectName("propertySection")
            section_combo = QComboBox()
            section_combo.setPlaceholderText("Indefinido")
            section_combo.addItems(self._sections_for_material(bar.material))
            if bar.section and bar.section in self._sections_for_material(bar.material):
                section_combo.setCurrentText(bar.section)
            section_combo.currentTextChanged.connect(self._section_selected)
            section_container = QWidget()
            self._section_container = section_container
            section_row = QHBoxLayout(section_container)
            section_row.setContentsMargins(0, 0, 0, 0)
            section_row.addWidget(section_combo, 1)
            settings_button = QToolButton()
            settings_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "section-dimension.svg")))
            settings_button.setIconSize(QSize(18, 18)); settings_button.setFixedSize(34, 34)
            settings_button.setToolTip("Configurar seção")
            settings_button.setAccessibleName("Configurar seção")
            settings_button.setCheckable(True)
            settings_button.clicked.connect(lambda _checked=False, combo=section_combo, button=settings_button:
                                            self.window.toggle_section_panel(combo.currentText(), button))
            settings_button.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } QToolButton:hover, QToolButton:checked { background: #eaeef2; }")
            section_row.addWidget(settings_button)
            self.layout.addWidget(section_label)
            self.layout.addWidget(section_container)
            section_profile_display = QLineEdit()
            section_profile_display.setReadOnly(True)
            section_profile_display.setObjectName("identityDisplay")
            section_profile_display.setText(
                self.window.section_profiles.get(name, "") or "Indefinido"
            )
            self.layout.addWidget(section_profile_display)
            rotation_box = QFrame()
            rotation_box.setObjectName("unitValueBox")
            rotation_box.setStyleSheet(
                "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; } "
                "QFrame#unitValueBox QLineEdit { border: 0; background: transparent; color: #57606a; padding: 2px 9px; } "
                "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
            )
            rotation_row = QHBoxLayout(rotation_box)
            rotation_row.setContentsMargins(0, 0, 0, 0)
            rotation_row.setSpacing(0)
            rotation_input = QLineEdit()
            rotation_input.setObjectName("unitValue")
            rotation_input.setValidator(
                QRegularExpressionValidator(QRegularExpression(r"[+-]?\d*"), rotation_input)
            )
            rotation_input.setText(str(bar.rotation))
            rotation_input.editingFinished.connect(self._rotation_changed)
            rotation_row.addWidget(rotation_input, 1)
            rotation_row.addWidget(QLabel("°"))
            self._rotation_box = rotation_box
            self._rotation_input = rotation_input
            self.layout.addWidget(self.rotation_title)
            self.rotation_title.show()
            self.layout.addWidget(rotation_box)
            releases_widget = QWidget()
            releases_layout = QGridLayout(releases_widget)
            releases_layout.setContentsMargins(0, 0, 0, 0)
            releases_layout.setHorizontalSpacing(12)
            releases_layout.setVerticalSpacing(self.layout.spacing())
            release_labels = (
                "Dxa", "Dxb", "Dya", "Dyb", "Dza", "Dzb",
                "Rxa", "Rxb", "Rya", "Ryb", "Rza", "Rzb",
            )
            release_tooltips = {
                "Dxa": "Deslocamento no eixo local x no nó inicial (A)",
                "Dxb": "Deslocamento no eixo local x no nó final (B)",
                "Dya": "Deslocamento no eixo local y no nó inicial (A)",
                "Dyb": "Deslocamento no eixo local y no nó final (B)",
                "Dza": "Deslocamento no eixo local z no nó inicial (A)",
                "Dzb": "Deslocamento no eixo local z no nó final (B)",
                "Rxa": "Rotação em torno do eixo local x no nó inicial (A)",
                "Rxb": "Rotação em torno do eixo local x no nó final (B)",
                "Rya": "Rotação em torno do eixo local y no nó inicial (A)",
                "Ryb": "Rotação em torno do eixo local y no nó final (B)",
                "Rza": "Rotação em torno do eixo local z no nó inicial (A)",
                "Rzb": "Rotação em torno do eixo local z no nó final (B)",
            }
            self._release_boxes = []
            for index, label in enumerate(release_labels):
                checkbox = QCheckBox(label)
                checkbox.setToolTip(release_tooltips[label])
                checkbox.setStyleSheet(
                    "QCheckBox { color: #57606a; spacing: 6px; }"
                    "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de; "
                    "border-radius: 5px; background: #ffffff; }"
                    "QCheckBox::indicator:hover { border-color: #d0d7de; }"
                    "QCheckBox::indicator:checked, QCheckBox::indicator:checked:hover { "
                    "background: #0969da; border-color: #0969da; }"
                )
                checkbox.setChecked(bar.releases[index])
                checkbox.stateChanged.connect(self._releases_changed)
                self._release_boxes.append(checkbox)
                releases_layout.addWidget(checkbox, index // 2, index % 2)
            self._releases_widget = releases_widget
            self.layout.addWidget(self.releases_title)
            self.releases_title.show()
            self.layout.addWidget(releases_widget)
            self._section_label, self._section_combo = section_label, section_combo
            self._section_profile_display = section_profile_display
            self._section_settings_button = settings_button
        # Recalculate after the previous form's deferred widgets are removed;
        # this is important when switching directly between selected elements.
        self.layout.activate()
        self.adjustSize()
        self.setMinimumHeight(self.sizeHint().height())
        self.reposition()
        self.show(); self.raise_()
        QTimer.singleShot(0, self._refresh_size)

    def _add_context_widget(self, widget: QWidget) -> None:
        """Append a widget that is exclusive to a non-geometry inspector."""
        self._context_widgets.append(widget)
        self.layout.addWidget(widget)

    @staticmethod
    def _action_description(action) -> str:
        labels = {
            "node_force": "Força no nó",
            "node_moment": "Momento no nó",
            "member_distributed_force": "Força distribuída no membro",
            "member_moment": "Momento no membro",
        }
        for prefix, label in labels.items():
            if action.kind.startswith(prefix):
                suffix = action.kind.removeprefix(prefix).strip("_").replace("_", " ")
                direction = suffix.upper().replace("GLOBAL ", "").replace("LOCAL ", " local ")
                values = ", ".join(f"{value:g}" for value in action.components)
                return f"{label}{' ' + direction if direction else ''}: {values}"
        values = ", ".join(f"{value:g}" for value in action.components)
        return f"{action.kind}: {values}"

    def _show_actions(self, kind: str, name: str, *, select_available_reference: bool = False) -> None:
        if kind == "bar":
            self._show_member_actions(name, select_available_reference)
            return
        if kind == "node":
            self._show_node_actions(name)
            return

        title = QLabel("Carregamentos")
        title.setObjectName("propertySection")
        self._add_context_widget(title)

        load_case = self.window.selected_action_name
        if not load_case:
            message = QLabel("Selecione uma ação ativa para consultar os carregamentos.")
            message.setWordWrap(True)
            self._add_context_widget(message)
            return

        active_case = QLabel(f"Ação ativa: {load_case}")
        active_case.setObjectName("propertySection")
        self._add_context_widget(active_case)
        actions = [
            action for action in self.window.model.actions.values()
            if action.target == name and action.load_case == load_case
        ]
        if not actions:
            message = QLabel("Nenhum carregamento aplicado a este " + ("nó." if kind == "node" else "membro."))
            message.setWordWrap(True)
            self._add_context_widget(message)
            return
        for action in actions:
            value = QLabel(self._action_description(action))
            value.setWordWrap(True)
            self._add_context_widget(value)

    def _show_node_actions(self, name: str) -> None:
        load_case = self.window.selected_action_name
        selfweight_locked = self._is_selfweight_locked(load_case)
        self._node_action_inputs.clear()

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Ações")
        title.setObjectName("propertySection")
        title.setStyleSheet("padding-top: 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        header_layout.addWidget(self._node_action_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
        self._add_context_widget(header)

        for label, value, unit in self._node_action_fields(name, load_case):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            field_label = QLabel(label)
            field_label.setObjectName("propertySection")
            field_label.setFixedWidth(28)
            value_box = self._action_unit_box(unit)
            field = value_box.findChild(QLineEdit)
            field.setText(value)
            field.setReadOnly(selfweight_locked)
            field.setPlaceholderText("—")
            field.setAccessibleName(f"{label} ({unit})")
            field.editingFinished.connect(
                lambda field=field, action_label=label: self._node_action_changed(action_label, field)
            )
            self._node_action_inputs[label] = field
            row_layout.addWidget(field_label)
            row_layout.addWidget(value_box, 1)
            self._add_context_widget(row)

    @staticmethod
    def _action_unit_box(unit: str) -> QFrame:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; }"
            "QFrame#unitValueBox QLineEdit { border: 0; background: transparent; color: #57606a; "
            "padding: 2px 9px; }"
            "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
        )
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        field = QLineEdit()
        field.setObjectName("unitValue")
        field.setMinimumWidth(0)
        layout.addWidget(field, 1)
        layout.addWidget(QLabel(unit))
        return box

    @staticmethod
    def _node_action_switch() -> QFrame:
        switch = QFrame()
        switch.setObjectName("nodeActionReferenceSwitch")
        switch.setFixedSize(62, 30)
        switch.setStyleSheet(
            "QFrame#nodeActionReferenceSwitch { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 15px; }"
        )
        indicator = QFrame(switch)
        indicator.setGeometry(4, 5, 54, 20)
        indicator.setStyleSheet("background: #0969da; border: 0; border-radius: 10px;")
        label = QLabel("Global", switch)
        label.setGeometry(4, 5, 54, 20)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #ffffff; font-size: 12px; font-weight: 600;")
        return switch

    def _node_action_fields(self, name: str, load_case: str | None) -> tuple[tuple[str, str, str], ...]:
        values = {label: "" for label in ("FX", "FY", "FZ", "MX", "MY", "MZ")}
        if load_case:
            for action in self.window.model.actions.values():
                if action.target != name or action.load_case != load_case:
                    continue
                for axis in "XYZ":
                    if action.kind == f"node_force_{axis}":
                        values[f"F{axis}"] = self._formatted_value(action.components)
                    elif action.kind == f"node_moment_{axis}":
                        values[f"M{axis}"] = self._formatted_value(action.components)
        return tuple(
            (label, values[label], "kN" if label.startswith("F") else "kNm")
            for label in values
        )

    def _node_action_changed(self, label: str, field: QLineEdit) -> None:
        if not self._selected or self._selected[0] != "node":
            return
        load_case = self.window.selected_action_name
        if self._is_selfweight_locked(load_case) or not load_case:
            self._update_node_action_fields()
            return
        try:
            raw_value = field.text().strip()
            value = 0.0 if not raw_value else float(raw_value.replace(",", "."))
            if not isfinite(value):
                raise ValueError
        except ValueError:
            self._update_node_action_fields()
            return
        if label.startswith("F"):
            self.window.action_service.add_node_force(self._selected[1], label[-1], value, load_case)
        else:
            self.window.action_service.add_node_moment(self._selected[1], label[-1], value, load_case)
        self._update_node_action_fields()
        self.window.refresh_scene()

    def _update_node_action_fields(self) -> None:
        if not self._selected or self._selected[0] != "node":
            return
        locked = self._is_selfweight_locked(self.window.selected_action_name)
        for label, value, _unit in self._node_action_fields(self._selected[1], self.window.selected_action_name):
            if input_field := self._node_action_inputs.get(label):
                input_field.setReadOnly(locked)
                input_field.setText(value)

    def _show_member_actions(self, name: str, select_available_reference: bool) -> None:
        load_case = self.window.selected_action_name
        selfweight_locked = self._is_selfweight_locked(load_case)
        if select_available_reference:
            self._member_action_reference = self._member_action_reference_for(name, load_case)
        self._member_action_inputs.clear()

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Ações")
        title.setObjectName("propertySection")
        title.setStyleSheet("padding-top: 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        header_layout.addWidget(self._member_action_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
        self._add_context_widget(header)

        for label, value, unit in self._member_action_fields(name, load_case):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            field_label = QLabel(label)
            field_label.setObjectName("propertySection")
            field_label.setFixedWidth(28)
            value_box = QFrame()
            value_box.setObjectName("unitValueBox")
            value_box.setStyleSheet(
                "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
                "border-radius: 6px; background: #ffffff; }"
                "QFrame#unitValueBox QLineEdit { border: 0; background: transparent; color: #57606a; "
                "padding: 2px 9px; }"
                "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
            )
            value_layout = QHBoxLayout(value_box)
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(0)
            field = QLineEdit(value)
            field.setObjectName("unitValue")
            editable = not selfweight_locked and (
                self._member_action_reference == "local" or label.startswith("F")
            )
            field.setReadOnly(not editable)
            field.setMinimumWidth(0)
            field.setPlaceholderText("—")
            field.setAccessibleName(f"{label} ({unit})")
            field.editingFinished.connect(
                lambda field=field, action_label=label: self._member_action_changed(action_label, field)
            )
            self._member_action_inputs[label] = field
            value_layout.addWidget(field, 1)
            value_layout.addWidget(QLabel(unit))
            row_layout.addWidget(field_label)
            row_layout.addWidget(value_box, 1)
            self._add_context_widget(row)

    def _member_action_switch(self) -> QFrame:
        switch = QFrame()
        switch.setObjectName("actionReferenceSwitch")
        switch.setFixedSize(98, 30)
        switch.setStyleSheet(
            "QFrame#actionReferenceSwitch { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 15px; }"
        )
        indicator = QFrame(switch)
        indicator.setObjectName("actionReferenceIndicator")
        indicator.setStyleSheet(
            "QFrame#actionReferenceIndicator { background: #0969da; border: 0; border-radius: 10px; }"
        )
        self._member_action_switch_indicator = indicator
        layout = QHBoxLayout(switch)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        buttons = QButtonGroup(switch)
        buttons.setExclusive(True)
        for reference, label in (("global", "Global"), ("local", "Local")):
            button = QToolButton(switch)
            button.setText(label)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedSize(46, 24)
            button.setStyleSheet(
                "QToolButton { border: 0; border-radius: 12px; padding: 0; background: transparent; "
                "font-size: 12px; font-weight: 600; }"
                "QToolButton:hover { background: transparent; }"
            )
            button.setChecked(reference == self._member_action_reference)
            button.setAccessibleName(f"Exibir ações no sistema {label.lower()}")
            button.clicked.connect(
                lambda checked=False, selected_reference=reference: self._set_member_action_reference(
                    selected_reference
                )
            )
            buttons.addButton(button)
            layout.addWidget(button)
            self._member_action_switch_buttons[reference] = button
        indicator.setGeometry(self._member_action_indicator_geometry())
        indicator.lower()
        self._update_member_action_switch_text()
        return switch

    def _member_action_reference_for(self, name: str, load_case: str | None) -> str:
        if not load_case:
            return "global"
        actions = [
            action for action in self.window.model.actions.values()
            if action.target == name and action.load_case == load_case
        ]
        has_global = any(
            action.kind.startswith("member_distributed_force_")
            and "_local_" not in action.kind
            for action in actions
        )
        has_local = any(
            "_local_" in action.kind or action.kind.startswith("member_moment_")
            for action in actions
        )
        if has_global:
            return "global"
        return "local" if has_local else "global"

    def _is_selfweight_locked(self, load_case: str | None) -> bool:
        return bool(load_case and self.window.action_service.has_selfweight(load_case))

    def _member_action_fields(self, name: str, load_case: str | None) -> tuple[tuple[str, str, str], ...]:
        values = {label: "" for label in ("FX", "FY", "FZ", "MX", "MY", "MZ")}
        if load_case:
            for action in self.window.model.actions.values():
                if action.target != name or action.load_case != load_case:
                    continue
                for axis in "XYZ":
                    global_force = {
                        f"member_distributed_force_{axis}",
                        f"member_distributed_force_global_{axis}",
                    }
                    if axis == "Z":
                        global_force.add("member_distributed_force_selfweight_Z")
                    local_force = f"member_distributed_force_local_{axis}"
                    is_selected_force = (
                        self._member_action_reference == "global" and action.kind in global_force
                    ) or (
                        self._member_action_reference == "local" and action.kind == local_force
                    )
                    if is_selected_force:
                        values[f"F{axis}"] = self._formatted_force(action.components)
                    elif self._member_action_reference == "local" and action.kind == f"member_moment_{axis}":
                        values[f"M{axis}"] = self._formatted_value(action.components)
        return tuple(
            (label, values[label], "kN/m" if label.startswith("F") else "kNm/m")
            for label in values
        )

    @staticmethod
    def _formatted_force(values: tuple[float, ...]) -> str:
        if len(values) != 2:
            return ""
        initial, final = values
        if initial == 0 and final == 0:
            return ""
        return (
            PropertyPanel._formatted_number(initial)
            if initial == final
            else f"{initial:.3f}".rstrip("0").rstrip(".")
            + "; "
            + f"{final:.3f}".rstrip("0").rstrip(".")
        )

    @staticmethod
    def _formatted_value(values: tuple[float, ...]) -> str:
        return PropertyPanel._formatted_number(values[0]) if values else ""

    @staticmethod
    def _formatted_number(value: float) -> str:
        if value == 0:
            return ""
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _set_member_action_reference(self, reference: str) -> None:
        if reference == self._member_action_reference or not self._selected or self._selected[0] != "bar":
            return
        self._member_action_reference = reference
        self._update_member_action_fields()
        self._animate_member_action_switch()

    def _animate_member_action_switch(self) -> None:
        indicator = self._member_action_switch_indicator
        if indicator is None:
            return
        if self._member_action_switch_animation is not None:
            self._member_action_switch_animation.stop()
        animation = QPropertyAnimation(indicator, b"geometry", indicator)
        animation.setDuration(160)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(indicator.geometry())
        animation.setEndValue(self._member_action_indicator_geometry())
        self._member_action_switch_animation = animation
        self._update_member_action_switch_text()
        animation.start()

    def _member_action_indicator_geometry(self) -> QRect:
        if self._member_action_reference == "global":
            return QRect(4, 5, 44, 20)
        return QRect(51, 5, 42, 20)

    def _update_member_action_switch_text(self) -> None:
        for reference, button in self._member_action_switch_buttons.items():
            color = "#ffffff" if reference == self._member_action_reference else "#57606a"
            palette = button.palette()
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(color))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
            button.setPalette(palette)
            button.update()

    def _update_member_action_fields(self) -> None:
        if not self._selected or self._selected[0] != "bar":
            return
        fields = self._member_action_fields(self._selected[1], self.window.selected_action_name)
        for label, value, _unit in fields:
            if input_field := self._member_action_inputs.get(label):
                input_field.setReadOnly(
                    self._is_selfweight_locked(self.window.selected_action_name)
                    or not (self._member_action_reference == "local" or label.startswith("F"))
                )
                input_field.setText(value)

    def _member_action_changed(self, label: str, field: QLineEdit) -> None:
        """Persist a member load typed into the contextual action inspector."""
        if not self._selected or self._selected[0] != "bar":
            return
        if self._is_selfweight_locked(self.window.selected_action_name):
            self._update_member_action_fields()
            return
        if label.startswith("M") and self._member_action_reference == "global":
            self._update_member_action_fields()
            return
        load_case = self.window.selected_action_name
        if not load_case:
            self._update_member_action_fields()
            return
        try:
            raw_value = field.text().strip()
            values = (0.0,) if not raw_value else tuple(
                float(part.strip().replace(",", "."))
                for part in raw_value.split(";")
            )
            if len(values) not in (1, 2) or not all(isfinite(value) for value in values):
                raise ValueError
        except ValueError:
            self._update_member_action_fields()
            return

        member_name = self._selected[1]
        action_service = self.window.action_service
        if label.startswith("F"):
            initial, final = values if len(values) == 2 else (values[0], values[0])
            direction = label[-1]
            selfweight = (
                self._member_action_reference == "global"
                and direction == "Z"
                and any(
                    action.target == member_name
                    and action.load_case == load_case
                    and action.kind == "member_distributed_force_selfweight_Z"
                    for action in self.window.model.actions.values()
                )
            )
            if selfweight:
                action_service.add_member_selfweight(member_name, initial, load_case)
            else:
                action_service.add_member_distributed_force(
                    member_name,
                    direction,
                    initial,
                    final,
                    load_case,
                    self._member_action_reference,
                )
        else:
            if len(values) != 1:
                self._update_member_action_fields()
                return
            action_service.add_member_moment(member_name, label[-1], values[0], load_case)
        self._update_member_action_fields()
        self.window.refresh_scene()

    def _show_analysis(self, kind: str, name: str) -> None:
        title = QLabel("Resultados")
        title.setObjectName("propertySection")
        self._add_context_widget(title)
        results = [
            result for result in self.window.model.analysis_results
            if result.model_revision == self.window.model.revision
        ]
        if not results:
            message = QLabel("Nenhum resultado disponível. Processe o modelo para consultar a análise.")
            message.setWordWrap(True)
            self._add_context_widget(message)
            return
        data_key = "node_results" if kind == "node" else "member_results"
        element_results = [
            (result.load_reference, getattr(result, data_key).get(name))
            for result in results
            if getattr(result, data_key).get(name) is not None
        ]
        if not element_results:
            message = QLabel("Não há resultados para este " + ("nó." if kind == "node" else "membro."))
            message.setWordWrap(True)
            self._add_context_widget(message)
            return
        for reference, values in element_results:
            label = QLabel(f"{reference}: {values}")
            label.setWordWrap(True)
            self._add_context_widget(label)

    def _refresh_size(self) -> None:
        if self.isVisible():
            self.layout.activate()
            self.setMinimumHeight(0)
            self.adjustSize()
            self.setMinimumHeight(self.sizeHint().height())
            self.reposition()

    def _clear_form(self) -> None:
        self._clear_context_widgets()
        if self._coordinates_widget is not None:
            self.layout.removeWidget(self._coordinates_widget)
            self._coordinates_widget.deleteLater()
            self._coordinates_widget = None
        if self._supports_widget is not None:
            self.layout.removeWidget(self._supports_widget)
            self._supports_widget.deleteLater()
            self._supports_widget = None
        if self._rotation_box is not None:
            self.layout.removeWidget(self._rotation_box)
            self._rotation_box.deleteLater()
            self._rotation_box = None
            self._rotation_input = None
        if self._releases_widget is not None:
            self.layout.removeWidget(self._releases_widget)
            self._releases_widget.deleteLater()
            self._releases_widget = None
            self._release_boxes.clear()
        if self._material_widget is not None:
            self.layout.removeWidget(self._material_widget)
            self._material_widget.deleteLater()
            self._material_widget = None
        for widget_name in ("_section_label", "_section_combo", "_section_profile_display", "_section_settings_button"):
            widget = getattr(self, widget_name)
            if widget is not None:
                self.layout.removeWidget(widget); widget.deleteLater(); setattr(self, widget_name, None)
        if self._section_container is not None:
            self.layout.removeWidget(self._section_container)
            self._section_container.deleteLater(); self._section_container = None
        self.layout.removeWidget(self.coordinates_title)
        self.layout.removeWidget(self.nodes_title)
        self.layout.removeWidget(self.rotation_title)
        self.layout.removeWidget(self.releases_title)
        self.layout.removeWidget(self.supports_title)
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.fields.clear()

    def _clear_context_widgets(self) -> None:
        if self._member_action_switch_animation is not None:
            self._member_action_switch_animation.stop()
        self._member_action_switch_animation = None
        self._member_action_switch_indicator = None
        self._member_action_switch_buttons.clear()
        self._node_action_inputs.clear()
        for widget in self._context_widgets:
            self.layout.removeWidget(widget)
            widget.deleteLater()
        self._context_widgets.clear()
        self._member_action_inputs.clear()

    def _node_changed(self, axis: str) -> None:
        if not self._selected or self._selected[0] != "node": return
        values = [field.value() for field in self.fields if isinstance(field, QDoubleSpinBox)]
        if len(values) == 3:
            self.window.model_service.update_node(self._selected[1], *values)
            self.window.refresh_node(self._selected[1])

    def _support_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "node" or self._supports_widget is None:
            return
        values = [box.isChecked() for box in self._supports_widget.findChildren(QCheckBox)]
        if len(values) == 6:
            self.window.model_service.update_supports(self._selected[1], tuple(values))
            self.window.refresh_node_visual(self._selected[1])

    def _bar_changed(self) -> None:
        if not self._selected or self._selected[0] != "bar" or len(self.fields) != 2: return
        start, end = (field.currentText() for field in self.fields if isinstance(field, QComboBox))
        try:
            self.window.model_service.update_member_nodes(self._selected[1], start, end)
            self.window.refresh_scene()
        except ValueError:
            pass

    def _rotation_changed(self) -> None:
        if not self._selected or self._selected[0] != "bar" or self._rotation_input is None:
            return
        value = self._rotation_input.text().strip()
        if not value:
            self._rotation_input.setText(str(self.window.model.bars[self._selected[1]].rotation))
            return
        try:
            member = self.window.model_service.update_member_rotation(self._selected[1], int(value))
        except ValueError:
            self._rotation_input.setText(str(self.window.model.bars[self._selected[1]].rotation))
            return
        self._rotation_input.setText(str(member.rotation))
        self.window.refresh_member_rotation(self._selected[1])

    def _toggle_color_palette(self) -> None:
        if not self._selected or self._selected[0] != "bar":
            return
        if self._color_palette.isVisible():
            self._color_palette.hide()
            return
        if self.window.section_panel.isVisible():
            self.window.close_section_panel(self._section_settings_button)
        color = self.window.model.bars[self._selected[1]].color
        self._color_palette.set_selected(color)
        self.reposition_color_palette()
        self._color_palette.show()
        self._color_palette.raise_()

    def close_color_palette(self) -> None:
        self._color_palette.hide()

    def reposition_color_palette(self) -> None:
        position = self.mapToGlobal(QPoint(
            -self._color_palette.width() - 12,
            (self.height() - self._color_palette.height()) // 2,
        ))
        self._color_palette.move(position)

    def _color_selected(self, color: str) -> None:
        if not self._selected or self._selected[0] != "bar":
            return
        member_name = self._selected[1]
        self.window.model_service.update_member_color(member_name, color)
        self._set_member_color_button(color)
        self.window.refresh_member_color(member_name)

    def _delete_requested(self) -> None:
        self.window.delete_selected()

    def update_delete_button_state(self) -> None:
        """Keep node deletion disabled while members still reference it."""
        if self._selected is None or getattr(self.window, "selected", None) != self._selected:
            self.delete_button.setEnabled(False)
            return
        kind, name = self._selected
        if kind == "bar":
            enabled = name in self.window.model.bars
            tooltip = "Excluir membro"
        else:
            connected = any(
                member.start_node == name or member.end_node == name
                for member in self.window.model.bars.values()
            )
            enabled = name in self.window.model.nodes and not connected
            tooltip = "Excluir nó" if enabled else "Remova os membros vinculados antes de excluir o nó"
        self.delete_button.setEnabled(enabled)
        self.delete_button.setToolTip(tooltip)

    def _set_member_color_button(self, color: str) -> None:
        self.member_color_button.setStyleSheet(
            f"QToolButton {{ background: {color}; border: 1px solid #d0d7de; border-radius: 6px; }} "
            "QToolButton:hover { border-color: #0969da; }"
        )

    def hideEvent(self, event) -> None:
        self._color_palette.hide()
        super().hideEvent(event)

    def _releases_changed(self, _state: int) -> None:
        if not self._selected or self._selected[0] != "bar" or len(self._release_boxes) != 12:
            return
        releases = tuple(checkbox.isChecked() for checkbox in self._release_boxes)
        self.window.model_service.update_member_releases(self._selected[1], releases)
        self.window.refresh_member_releases(self._selected[1])

    def _material_selected(self, material: str) -> None:
        # A section profile belongs to a material catalog. Changing material
        # invalidates the open geometry editor, so close it before rebuilding
        # the available section-family list.
        if self.window.section_panel.isVisible():
            self.window.close_section_panel(self._section_settings_button)
        if self._selected and self._selected[0] == "bar" and material in self.window.model.materials:
            self.window.model_service.assign_material(self._selected[1], material)
        if self._section_combo is not None:
            current = self._section_combo.currentText()
            self._section_combo.blockSignals(True)
            self._section_combo.clear()
            self._section_combo.setPlaceholderText("Indefinido")
            self._section_combo.addItems(self._sections_for_material(material))
            if current in self._sections_for_material(material):
                self._section_combo.setCurrentText(current)
            elif self._selected and self._selected[0] == "bar":
                self.window.model_service.assign_section(self._selected[1], "")
                self.window.refresh_member_geometry(self._selected[1])
            self._section_combo.blockSignals(False)

    def _sections_for_material(self, material: str) -> list[str]:
        if material == "Indefinido":
            return []
        material_type = self.window.model.material_types.get(material, "Aço")
        return list(self.window.model.sections.get(material_type, []))

    def _section_selected(self, section: str) -> None:
        if self._selected and self._selected[0] == "bar":
            member_name = self._selected[1]
            self.window.model_service.assign_section(member_name, section)
            self.window.refresh_member_geometry(member_name)
            # Selecting a section type starts a fresh profile selection.
            self.window.section_profiles.pop(member_name, None)
            self.window.section_geometry.pop(member_name, None)
            if self._section_profile_display is not None:
                self._section_profile_display.setText("Indefinido")
            # A visible geometry editor belongs to the previously selected
            # family. Rebind it immediately when the member's section family
            # changes, preserving the open state and the checked button.
            if section and self.window.section_panel.isVisible():
                self.window.show_section_panel(section, self._section_settings_button)

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move(self.window.width() - margin - self.width() - 24,
                  (self.window.height() - self.height()) // 2)
        self.raise_()
