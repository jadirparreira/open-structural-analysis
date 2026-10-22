from math import isfinite

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QPainterPath, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import QStyle, QStyleOptionButton

from osa.services import calculate_rigid_bar_stiffness
from osa.memorial_data import calculation_memory
from osa.verification.elements import verification_elements

from .color_palette import HoneycombColorPalette
from .common import *
from .calculation_memorial_dialog import CalculationMemorialDialog
from .window_frame import WindowFrame


class CompactDoubleSpinBox(QDoubleSpinBox):
    """Spinbox numérica compacta que aceita ponto ou vírgula decimal."""

    def valueFromText(self, text: str) -> float:
        """Parse decimal input independently of the operating-system locale."""
        normalized = text.strip().replace(",", ".")
        try:
            return float(normalized)
        except ValueError:
            return super().valueFromText(text)

    def textFromValue(self, value: float) -> str:
        text = f"{value:.{self.decimals()}f}".rstrip("0").rstrip(".")
        return text or "0"


class MixedCheckBox(QCheckBox):
    """Three-state checkbox with a hatched indicator for mixed values."""

    def nextCheckState(self) -> None:
        self.setCheckState(
            Qt.CheckState.Unchecked if self.checkState() != Qt.CheckState.Unchecked
            else Qt.CheckState.Checked
        )

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.checkState() != Qt.CheckState.PartiallyChecked:
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = indicator.adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(box, 4, 4)
        painter.setPen(QPen(QColor("#0969da"), 1.2))
        painter.setBrush(QColor("#eaf3ff"))
        painter.drawPath(path)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(QPen(QColor("#0969da"), 1))
        for offset in range(-box.height(), box.width(), 4):
            painter.drawLine(
                box.left() + offset, box.bottom(),
                box.left() + offset + box.height(), box.top(),
            )
        painter.restore()
        painter.end()


class SelectionKindSwitch(QFrame):
    """Two-position selection control shared by property editors."""

    kind_changed = Signal(str)

    def __init__(self, parent: QWidget, *, choices=None) -> None:
        super().__init__(parent)
        self.setObjectName("selectionKindSwitch")
        self.setFixedHeight(34)
        self.setStyleSheet(
            "QFrame#selectionKindSwitch { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 16px; }"
            "QFrame#selectionKindSwitch QToolButton { background: transparent; border: 0; "
            "border-radius: 12px; color: #57606a; font-size: 12px; font-weight: 600; }"
            "QFrame#selectionKindSwitch QToolButton:checked { background: #0969da; color: #ffffff; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}
        for kind, label in choices or (("node", "Nós"), ("bar", "Barras")):
            button = QToolButton(self)
            button.setText(label)
            button.setCheckable(True)
            button.setFixedHeight(26)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(
                label if choices else f"Exibir propriedades dos {label.lower()} selecionados"
            )
            button.clicked.connect(
                lambda _checked=False, selected_kind=kind: self.kind_changed.emit(selected_kind)
            )
            group.addButton(button)
            layout.addWidget(button, 1)
            self._buttons[kind] = button

    def set_selection(self, kind: str) -> None:
        if kind in self._buttons:
            self._buttons[kind].setChecked(True)


class PropertyPanel(QFrame):
    """Floating inspector for the currently selected node or bar."""

    def __init__(self, window: "MainWindow", *, context=None, creation_mode: bool = False) -> None:
        super().__init__(window)
        self.window = context if context is not None else window
        self._creation_mode = creation_mode
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        self._selected: tuple[str, str] | None = None
        self._selection: tuple[tuple[str, str], ...] = ()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(7)
        self.title = QLabel()
        self.title.setObjectName("propertyTitle")
        self.kind_selector = QComboBox()
        self.kind_selector.setAccessibleName("Propriedades dos elementos selecionados")
        self.kind_selector.currentIndexChanged.connect(self._inspected_kind_changed)
        self.kind_control = QWidget()
        kind_control_layout = QVBoxLayout(self.kind_control)
        kind_control_layout.setContentsMargins(0, 0, 0, 0)
        kind_control_layout.setSpacing(0)
        kind_control_layout.addWidget(self.kind_selector)
        self.selection_kind_switch = SelectionKindSwitch(self.kind_control)
        self.selection_kind_switch.kind_changed.connect(self._switch_inspected_kind)
        kind_control_layout.addWidget(self.selection_kind_switch)
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
        self.member_color_button.setToolTip("Definir cor da barra")
        self.member_color_button.setAccessibleName("Definir cor da barra")
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
        self.verification_name_input = QLineEdit()
        self.verification_name_input.setObjectName("propertyValue")
        self.verification_name_input.setMinimumWidth(0)
        self.verification_name_input.setAccessibleName("Nome do elemento")
        self.verification_name_input.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"[\p{L}\p{N}]*"), self.verification_name_input,
        ))
        self.verification_name_input.editingFinished.connect(self._verification_name_changed)
        self._verification_name_row = QWidget()
        verification_name_layout = QVBoxLayout(self._verification_name_row)
        verification_name_layout.setContentsMargins(0, 0, 0, 0)
        verification_name_layout.setSpacing(self.layout.spacing())
        verification_name_label = QLabel("Nome")
        verification_name_label.setObjectName("propertySection")
        verification_name_label.setBuddy(self.verification_name_input)
        verification_name_layout.addWidget(verification_name_label)
        verification_name_layout.addWidget(self.verification_name_input)
        self._verification_result_rows: list[QWidget] = []
        self._verification_result_values: dict[str, QLineEdit] = {}
        for field_name, label_text, accessible_name in (
            ("utilization", "Taxa de solicitação", "Taxa de solicitação"),
            ("critical_check", "Verificação crítica", "Verificação crítica"),
            ("critical_combination", "Combinação crítica", "Combinação crítica"),
        ):
            result_row = QWidget()
            result_layout = QVBoxLayout(result_row)
            result_layout.setContentsMargins(0, 0, 0, 0)
            result_layout.setSpacing(self.layout.spacing())
            result_label = QLabel(label_text)
            result_label.setObjectName("propertySection")
            result_value = QLineEdit("A definir")
            result_value.setObjectName("propertyValue")
            result_value.setAccessibleName(accessible_name)
            result_value.setReadOnly(True)
            result_value.setToolTip("")
            result_label.setBuddy(result_value)
            result_layout.addWidget(result_label)
            if field_name == "utilization":
                value_row = QHBoxLayout()
                value_row.setContentsMargins(0, 0, 0, 0)
                value_row.setSpacing(6)
                value_row.addWidget(result_value, 1)
                memory_button = QToolButton(result_row)
                memory_button.setFixedSize(34, 34)
                memory_button.setIcon(QIcon(str(
                    Path(__file__).parents[1] / "resources" / "icons" / "calculation-memory.svg"
                )))
                memory_button.setIconSize(QSize(18, 18))
                memory_button.setToolTip("Abrir memorial de cálculo")
                memory_button.setAccessibleName("Abrir memorial de cálculo")
                memory_button.setStyleSheet(
                    "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; }"
                    "QToolButton:hover { background: #eaeef2; }"
                    "QToolButton:pressed { background: #d0d7de; }"
                )
                memory_button.clicked.connect(self._open_verification_memory)
                value_row.addWidget(memory_button)
                result_layout.addLayout(value_row)
            else:
                result_layout.addWidget(result_value)
            self._verification_result_rows.append(result_row)
            self._verification_result_values[field_name] = result_value
        self._color_palette = HoneycombColorPalette(window, self._color_selected)
        self.layout.addWidget(self.title)
        self.layout.addWidget(self.kind_control)
        self.layout.addWidget(self.name)
        self.layout.addWidget(identity_row)
        self.layout.addWidget(self._verification_name_row)
        self._verification_name_row.hide()
        for result_row in self._verification_result_rows:
            self.layout.addWidget(result_row)
            result_row.hide()
        self.point_mode_switch = None
        if creation_mode:
            self.point_mode_switch = SelectionKindSwitch(
                self, choices=(("exact", "Ponto exato"), ("midpoint", "Ponto Médio")),
            )
            self.point_mode_switch.set_selection("exact")
            self.point_mode_switch._buttons["exact"].setToolTip("Definir cada extremidade com um clique")
            self.point_mode_switch._buttons["midpoint"].setToolTip(
                "Definir cada extremidade pelo ponto médio entre dois cliques"
            )
            self.layout.addWidget(self.point_mode_switch)
        self.coordinates_title = QLabel("Coordenadas")
        self.coordinates_title.setObjectName("propertySection")
        self.nodes_title = QLabel("Nós")
        self.nodes_title.setObjectName("propertySection")
        self.solid_offsets_title = QLabel("Posicionamento")
        self.solid_offsets_title.setObjectName("propertySection")
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
        self._support_stiffness_inputs: list[QDoubleSpinBox] = []
        self._solid_offsets_widget: QWidget | None = None
        self._positioning_status: QLineEdit | None = None
        self._displacement_settings_button: QToolButton | None = None
        self._releases_widget: QWidget | None = None
        self._releases_header: QWidget | None = None
        self._release_stack: QStackedWidget | None = None
        self._release_boxes: list[QCheckBox] = []
        self._release_rotation_percent_inputs: dict[int, QLineEdit] = {}
        self._release_end = "A"
        self._release_switch_indicator: QFrame | None = None
        self._release_switch_buttons: dict[str, QToolButton] = {}
        self._release_switch_animation: QPropertyAnimation | None = None
        self._material_widget: QWidget | None = None
        self._section_label: QLabel | None = None
        self._section_combo: QComboBox | None = None
        self._section_container: QWidget | None = None
        self._section_profile_display: QLineEdit | None = None
        self._section_settings_button: QToolButton | None = None
        self._context_widgets: list[QWidget] = []
        self._member_action_reference = "global"
        self._member_action_inputs: dict[str, QLineEdit] = {}
        self._member_action_units: dict[str, QLabel] = {}
        self._member_action_boxes: dict[str, QFrame] = {}
        self._node_action_inputs: dict[str, QLineEdit] = {}
        self._member_action_switch_indicator: QFrame | None = None
        self._member_action_switch_buttons: dict[str, QToolButton] = {}
        self._member_action_switch_animation: QPropertyAnimation | None = None
        self._analysis_result_view = "A"
        self._analysis_switch_indicator: QFrame | None = None
        self._analysis_switch_buttons: dict[str, QToolButton] = {}
        self._analysis_switch_animation: QPropertyAnimation | None = None
        self._identity_row = identity_row
        self.delete_button.setEnabled(False)
        self.hide()

    def _selected_names(self, kind: str) -> list[str]:
        return [name for selected_kind, name in self._selection if selected_kind == kind]

    def _verification_name_changed(self) -> None:
        if self._selected is None or self._selected[0] != "bar":
            return
        names = tuple(self._selected_names("bar"))
        self.window.model.set_verification_element_name(names, self.verification_name_input.text())
        self.window.refresh_scene()

    def _open_verification_memory(self) -> None:
        """Open the stored calculation memory for the selected element or group."""
        names = tuple(self._selected_names("bar"))
        memory = calculation_memory(self.window.model, names)
        dialog = CalculationMemorialDialog(memory, self.window)
        dialog.exec()

    def _inspected_kind_changed(self, _index: int) -> None:
        self._switch_inspected_kind(self.kind_selector.currentData())

    def _switch_inspected_kind(self, kind: str | None) -> None:
        if kind is None or not self._selection:
            return
        name = self._selected_names(kind)[-1]
        self.window.selected = kind, name
        self.window.refresh_selected_property_panel(self.window.palette.active_group)

    @staticmethod
    def _all_equal(values: list[object]) -> bool:
        return bool(values) and all(value == values[0] for value in values[1:])

    @staticmethod
    def _check_state(values: list[bool]) -> Qt.CheckState:
        if all(values):
            return Qt.CheckState.Checked
        if not any(values):
            return Qt.CheckState.Unchecked
        return Qt.CheckState.PartiallyChecked

    def show_for(
        self, kind: str, name: str, section: str = "Geometria",
        *, selection: object = None,
    ) -> None:
        """Show the inspector content that belongs to the open work section."""
        if self._selected != (kind, name):
            self._analysis_result_view = "A"
        self._selected = kind, name
        self._selection = tuple(selection or ((kind, name),))
        names = self._selected_names(kind)
        kinds = [selected_kind for selected_kind in ("bar", "node", "rigid_bar")
                 if self._selected_names(selected_kind)]
        with QSignalBlocker(self.kind_selector):
            self.kind_selector.clear()
            for selected_kind in kinds:
                label = {"bar": "Barras", "node": "Nós", "rigid_bar": "Barras rígidas"}[selected_kind]
                self.kind_selector.addItem(
                    f"{label} ({len(self._selected_names(selected_kind))})", selected_kind
                )
            if kind in kinds:
                self.kind_selector.setCurrentIndex(kinds.index(kind))
        node_member_selection = set(kinds) == {"node", "bar"}
        self.selection_kind_switch.set_selection(kind)
        self.selection_kind_switch.setVisible(node_member_selection)
        self.kind_selector.setVisible(len(kinds) > 1 and not node_member_selection)
        self.kind_control.setVisible(len(kinds) > 1)
        self._clear_form()
        self.coordinates_title.hide()
        self.nodes_title.hide()
        self.solid_offsets_title.hide()
        self.releases_title.hide()
        self.supports_title.hide()
        self._color_palette.hide()
        verification_mode = section == "Memorial"
        self.member_color_button.setVisible(kind == "bar" and not verification_mode)
        self.delete_button.setVisible(not verification_mode)
        self.update_delete_button_state()
        title = {"node": "Nó", "bar": "Barra", "rigid_bar": "Barra rígida"}.get(kind, "Elemento")
        if len(self._selection) > 1:
            if len(kinds) > 1:
                title = f"Elementos · {len(self._selection)} selecionados"
            else:
                plural = {"node": "Nós", "bar": "Barras", "rigid_bar": "Barras rígidas"}.get(kind, "Elementos")
                title = f"{plural} · {len(names)} selecionados"
        self.title.setText("Adicionar barra" if self._creation_mode else title)
        self.name.setVisible(not self._creation_mode)
        self._identity_row.setVisible(not self._creation_mode)
        self.name.setText("Identidade")
        self.identity_value.setText(name if len(names) == 1 else f"Variado ({len(names)})")
        self._verification_name_row.setVisible(verification_mode and kind == "bar")
        for result_row in self._verification_result_rows:
            result_row.setVisible(verification_mode and kind == "bar")
        if verification_mode and kind == "bar":
            group = self.window.model.verification_group_for(names[-1]) if names else None
            is_group = group is not None and set(names) == set(group["members"])
            identity_names = list(group["members"]) if is_group else names
            identity = ", ".join(identity_names) if is_group else (
                names[0] if len(names) == 1 else f"Variado ({len(names)})"
            )
            self.identity_value.setText(identity)
            title = "Grupo de elementos" if is_group else "Elemento"
            self.title.setText(title)
            custom_name = (
                str(group.get("name", "")) if is_group
                else self.window.model.verification_element_names.get(names[-1], "") if names else ""
            )
            with QSignalBlocker(self.verification_name_input):
                self.verification_name_input.setText(custom_name)
            self.name.setVisible(True)
            self._verification_result_values["utilization"].setText("A definir")
            self._verification_result_values["critical_check"].setText("A definir")
            self._verification_result_values["critical_combination"].setText("A definir")
            selected_names = set(names)
            element_result = next((
                self.window.model.verification_results.get(element.key)
                for element in verification_elements(self.window.model)
                if set(element.member_names) == selected_names
            ), None)
            if element_result:
                if element_result.get("status") == "checked":
                    self._verification_result_values["utilization"].setText(
                        f"{element_result['utilization']:.2%}".replace(".", ",")
                    )
                    self._verification_result_values["critical_check"].setText(
                        str(element_result.get("critical_check", "N/D")).split(" — ", 1)[0]
                    )
                    self._verification_result_values["critical_combination"].setText(
                        element_result.get("critical_combination", "N/D")
                    )
                elif element_result.get("status") == "not_applicable":
                    for value in self._verification_result_values.values():
                        value.setText("N/A")
        if kind == "bar":
            colors = [self.window.model.bars[member_name].color for member_name in names]
            self._set_member_color_button(colors[0] if self._all_equal(colors) else "#ffffff")
            self.member_color_button.setToolTip(
                "Definir cor das barras" if len(names) > 1 else "Definir cor da barra"
            )

        # A rigid bar is an idealized connection, not a physical member.  Its
        # inspector is therefore informational and must be the same in every
        # work section; in particular, it must not expose editable endpoints
        # or action/result controls.
        if kind == "rigid_bar" and not verification_mode:
            self._show_rigid_bar_properties(name)
        elif section == "Ações" and not verification_mode:
            self._show_actions(kind, name, select_available_reference=True)
        elif section == "Análise" and not verification_mode:
            self._show_analysis(kind, name)
        elif kind == "node" and not verification_mode:
            node = self.window.model.nodes[name]
            form_index = self.layout.indexOf(self.form)
            self.layout.insertWidget(form_index, self.coordinates_title)
            self.coordinates_title.show()
            for axis, value in zip(("X", "Y", "Z"), (node.x, node.y, node.z)):
                field = CompactDoubleSpinBox()
                field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                field.setRange(-1_000_001.0, 1_000_000.0)
                field.setSpecialValueText("Variado")
                field.setDecimals(3)
                field.setSingleStep(0.1)
                values = [getattr(self.window.model.nodes[node_name], axis.lower()) for node_name in names]
                field.setValue(value if self._all_equal(values) else field.minimum())
                field.setAccessibleName(f"Coordenada {axis} (m)")
                # Coordinates are committed as a complete edit.  Connecting
                # to ``editingFinished`` prevents the model and scene from
                # changing on every keystroke, while still committing on
                # Enter or when the user moves focus to another input.
                field.editingFinished.connect(lambda axis=axis: self._node_changed(axis))
                self.fields.append(field)
                axis_label = QLabel(axis)
                axis_label.setObjectName("propertySection")
                self.form.addRow(axis_label, self._editable_unit_box(field, "m"))
            form_index = self.layout.indexOf(self.form)
            self.layout.insertWidget(form_index + 1, self.supports_title)
            self.supports_title.show()
            supports = QWidget()
            self._supports_widget = supports
            self._support_stiffness_inputs.clear()
            supports_layout = QVBoxLayout(supports)
            supports_layout.setContentsMargins(0, 0, 0, 0)
            supports_layout.setSpacing(4)
            for index, label in enumerate(("Dx", "Dy", "Dz", "Rx", "Ry", "Rz")):
                checkbox = MixedCheckBox(label)
                checkbox.setTristate(True)
                checkbox.setStyleSheet(
                    "QCheckBox::indicator:indeterminate { background: #ffffff; "
                    "border: 1px solid #0969da; border-radius: 5px; "
                    "width: 18px; height: 18px; }"
                )
                support_values = [self.window.model.nodes[node_name].supports[index] for node_name in names]
                checkbox.setCheckState(self._check_state(support_values))
                checkbox.stateChanged.connect(lambda _state, idx=index: self._support_changed(idx))
                value = CompactDoubleSpinBox()
                value.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                value.setDecimals(3)
                value.setRange(-1.0, 1_000_000.0)
                stiffness_values = [
                    self.window.model.nodes[node_name].support_stiffness[index]
                    for node_name in names
                ]
                value.setSpecialValueText("Variado" if not self._all_equal(stiffness_values) else "")
                value.setValue(node.support_stiffness[index] if self._all_equal(stiffness_values) else -1.0)
                # These values are spring stiffnesses, not DOF values:
                # force/length for translations and moment/radian for rotations.
                unit = "kN/m" if index < 3 else "kN·m/rad"
                value.setAccessibleName(f"{label} ({unit})")
                value_box = self._editable_unit_box(value, unit)
                value.valueChanged.connect(lambda _value, idx=index: self._support_stiffness_changed(idx))
                self._support_stiffness_inputs.append(value)
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)
                row.addWidget(checkbox)
                row.addWidget(value_box, 1)
                supports_layout.addLayout(row)
            self.layout.insertWidget(form_index + 2, supports)
        elif not verification_mode:
            bar = self.window.model.bars[name]
            if not self._creation_mode:
                nodes = list(self.window.model.nodes)
                self.layout.insertWidget(4, self.nodes_title)
                self.nodes_title.show()
                start, end = QComboBox(), QComboBox()
                start.addItems(nodes); end.addItems(nodes)
                for combo in (start, end):
                    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    combo.view().setMinimumHeight(min(5, len(nodes)) * 28 + 2)
                    combo.view().setMaximumHeight(min(5, len(nodes)) * 28 + 2)
                for index, combo in enumerate((start, end)):
                    values = [
                        (self.window.model.bars[member_name].start_node,
                         self.window.model.bars[member_name].end_node)[index]
                        for member_name in names
                    ]
                    if self._all_equal(values):
                        combo.setCurrentText(values[0])
                    else:
                        combo.setPlaceholderText("Variado")
                        combo.setCurrentIndex(-1)
                    combo.currentTextChanged.connect(
                        lambda _text, idx=index: self._bar_changed(idx)
                    )
                    combo.setEnabled(len(names) == 1)
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
            materials = [self.window.model.bars[member_name].material for member_name in names]
            material_combo.setPlaceholderText("Variado" if not self._all_equal(materials) else "Indefinido")
            if self._all_equal(materials) and bar.material in self.window.model.materials:
                material_combo.setCurrentText(bar.material)
            else:
                material_combo.setCurrentIndex(-1)
            material_layout.addWidget(material_combo)
            material_combo.currentTextChanged.connect(self._material_selected)
            self.layout.addWidget(material_widget)
            section_label = QLabel("Seção")
            section_label.setObjectName("propertySection")
            section_combo = QComboBox()
            section_combo.setPlaceholderText("Indefinido")
            sections = [self.window.model.bars[member_name].section for member_name in names]
            available_sections = [
                section for section in self._sections_for_material(materials[0])
                if all(section in self._sections_for_material(material) for material in materials[1:])
            ]
            section_combo.addItems(available_sections)
            section_combo.setPlaceholderText("Variado" if not self._all_equal(sections) else "Indefinido")
            if self._all_equal(sections) and bar.section:
                if bar.section not in available_sections:
                    section_combo.addItem(bar.section)
                    section_combo.setEnabled(False)
                section_combo.setCurrentText(bar.section)
            else:
                section_combo.setCurrentIndex(-1)
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
            settings_button.setEnabled(bool(section_combo.currentText()))
            settings_button.clicked.connect(lambda _checked=False, combo=section_combo, button=settings_button:
                                            self.window.toggle_section_panel(combo.currentText(), button))
            settings_button.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } QToolButton:hover, QToolButton:checked { background: #eaeef2; }")
            section_row.addWidget(settings_button)
            self.layout.addWidget(section_label)
            self.layout.addWidget(section_container)
            section_profile_display = QLineEdit()
            section_profile_display.setReadOnly(True)
            section_profile_display.setObjectName("identityDisplay")
            profiles = [
                self.window.section_profiles.get(member_name)
                or self.window.model.bars[member_name].profile
                for member_name in names
            ]
            section_profile_display.setText(
                (profiles[0] or "Indefinido") if self._all_equal(profiles) else "Variado"
            )
            self.layout.addWidget(section_profile_display)
            self._show_member_solid_offsets(bar)
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
            release_boxes: list[QCheckBox | None] = [None] * len(release_labels)
            checkbox_style = (
                "QCheckBox { color: #57606a; spacing: 6px; }"
                "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de; "
                "border-radius: 5px; background: #ffffff; }"
                "QCheckBox::indicator:hover { border-color: #d0d7de; }"
                "QCheckBox::indicator:checked, QCheckBox::indicator:checked:hover { "
                "background: #0969da; border-color: #0969da; }"
                "QCheckBox::indicator:indeterminate { background: #ffffff; border-color: #0969da; }"
            )
            endpoint_indices = {"A": (0, 6, 2, 8, 4, 10), "B": (1, 7, 3, 9, 5, 11)}
            self._release_stack = QStackedWidget()
            self._release_rotation_percent_inputs.clear()
            for endpoint in ("A", "B"):
                endpoint_widget = QWidget()
                endpoint_layout = QGridLayout(endpoint_widget)
                endpoint_layout.setContentsMargins(0, 0, 0, 0)
                endpoint_layout.setHorizontalSpacing(8)
                endpoint_layout.setVerticalSpacing(self.layout.spacing())
                endpoint_layout.setColumnStretch(0, 3)
                endpoint_layout.setColumnStretch(1, 3)
                endpoint_layout.setColumnStretch(2, 4)
                indices = endpoint_indices[endpoint]
                for position in range(3):
                    translation_index = indices[position * 2]
                    rotation_index = indices[position * 2 + 1]
                    translation_label = release_labels[translation_index]
                    translation_checkbox = MixedCheckBox(translation_label)
                    translation_checkbox.setTristate(True)
                    translation_checkbox.setToolTip(release_tooltips[translation_label])
                    translation_checkbox.setStyleSheet(checkbox_style)
                    translation_checkbox.setCheckState(self._check_state([
                        not self.window.model.bars[member_name].releases[translation_index]
                        for member_name in names
                    ]))
                    translation_checkbox.stateChanged.connect(
                        lambda state, idx=translation_index: self._releases_changed(idx, state)
                    )
                    release_boxes[translation_index] = translation_checkbox
                    endpoint_layout.addWidget(translation_checkbox, position, 0)

                    rotation_label = release_labels[rotation_index]
                    rotation_checkbox = MixedCheckBox(rotation_label)
                    rotation_checkbox.setTristate(True)
                    rotation_checkbox.setToolTip(release_tooltips[rotation_label])
                    rotation_checkbox.setStyleSheet(checkbox_style)
                    rotation_checkbox.setCheckState(self._check_state([
                        not self.window.model.bars[member_name].releases[rotation_index]
                        for member_name in names
                    ]))
                    rotation_checkbox.stateChanged.connect(
                        lambda state, idx=rotation_index: self._releases_changed(idx, state)
                    )
                    release_boxes[rotation_index] = rotation_checkbox
                    endpoint_layout.addWidget(rotation_checkbox, position, 1)

                    percent = QLineEdit()
                    percent.setObjectName("unitValue")
                    percent.setMinimumWidth(0)
                    percent.setValidator(QRegularExpressionValidator(
                        QRegularExpression(r"\d*"), percent
                    ))
                    percent_values = [
                        self.window.model.bars[member_name].rotation_flexibility_percent[rotation_index - 6]
                        for member_name in names
                    ]
                    rotation_states = [
                        self.window.model.bars[member_name].releases[rotation_index]
                        for member_name in names
                    ]
                    percent.setText(
                        str(percent_values[0]) if self._all_equal(percent_values)
                        and not any(rotation_states) else ""
                    )
                    percent.setPlaceholderText("Variado" if not self._all_equal(percent_values) else "")
                    percent.setEnabled(not any(rotation_states))
                    percent.setAccessibleName(f"{rotation_label} (%)")
                    percent_box = self._percentage_unit_box(percent)
                    percent.editingFinished.connect(
                        lambda idx=rotation_index: self._release_rotation_percent_changed(idx)
                    )
                    self._release_rotation_percent_inputs[rotation_index] = percent
                    endpoint_layout.addWidget(percent_box, position, 2)
                self._release_stack.addWidget(endpoint_widget)
            self._release_boxes = [box for box in release_boxes if box is not None]
            self._release_stack.setCurrentIndex(0)
            release_header = QWidget()
            release_header_layout = QHBoxLayout(release_header)
            release_header_layout.setContentsMargins(0, 0, 0, 0)
            release_header_layout.setSpacing(8)
            release_header_layout.addWidget(self.releases_title)
            release_header_layout.addStretch(1)
            release_header_layout.addWidget(self._release_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
            self._releases_header = release_header
            self._releases_widget = self._release_stack
            self.layout.addWidget(release_header)
            self.releases_title.show()
            self.layout.addWidget(self._release_stack)
            self._section_label, self._section_combo = section_label, section_combo
            self._section_profile_display = section_profile_display
            self._section_settings_button = settings_button
        # Recalculate after the previous form's deferred widgets are removed;
        # this is important when switching directly between selected elements.
        self.layout.activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.reposition()
        self.show(); self.raise_()
        QTimer.singleShot(0, self._refresh_size)

    def _show_member_solid_offsets(self, bar) -> None:
        """Show the entry point for visual member-face displacements."""
        self.layout.addWidget(self.solid_offsets_title)
        self.solid_offsets_title.show()
        offset_row = QWidget()
        offset_layout = QHBoxLayout(offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        offset_layout.setSpacing(6)

        status = QLineEdit()
        status.setReadOnly(True)
        status.setObjectName("identityDisplay")
        members = [self.window.model.bars[member_name] for member_name in self._selected_names("bar")]
        positioning = [self._positioning_summary(member) for member in members]
        signatures = [(
            member.rotation, member.solid_face_offsets, member.solid_section_offsets,
        ) for member in members]
        status.setText(positioning[0] if self._all_equal(signatures) else "Variado")
        status.setAccessibleName("Identificação do posicionamento")
        offset_layout.addWidget(status, 1)

        configure_button = QToolButton()
        configure_button.setFixedSize(34, 34)
        configure_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "move.svg"))
        )
        configure_button.setIconSize(QSize(18, 18))
        configure_button.setToolTip("Configurar posicionamento")
        configure_button.setAccessibleName("Configurar posicionamento")
        configure_button.setCheckable(True)
        configure_button.setEnabled(bool(positioning))
        configure_button.clicked.connect(
            lambda _checked=False, button=configure_button: self.window.toggle_displacement_panel(button)
        )
        configure_button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
        )
        offset_layout.addWidget(configure_button)

        self._displacement_settings_button = configure_button
        self._positioning_status = status
        self._solid_offsets_widget = offset_row
        self.layout.addWidget(offset_row)

    def update_positioning_status(self, member_name: str) -> None:
        """Synchronize the compact positioning summary after an offset change."""
        if self._selected is None or self._selected[0] != "bar" or self._positioning_status is None:
            return
        names = self._selected_names("bar")
        if member_name not in names:
            return
        members = [self.window.model.bars[name] for name in names]
        signatures = [(
            member.rotation, member.solid_face_offsets, member.solid_section_offsets,
        ) for member in members]
        self._positioning_status.setText(
            self._positioning_summary(members[0]) if self._all_equal(signatures) else "Variado"
        )

    @staticmethod
    def _positioning_summary(member) -> str:
        """Build the compact positioning identification shown beside the button."""
        face_offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
        section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
        rotation = float(getattr(member, "rotation", 0))
        tokens: list[str] = []
        if rotation != 0:
            tokens.append(f"R{PropertyPanel._format_positioning_value(rotation)}")
        for label, value in (
            ("A", face_offsets[0] if len(face_offsets) > 0 else 0.0),
            ("B", face_offsets[1] if len(face_offsets) > 1 else 0.0),
            ("Y", section_offsets[0] if len(section_offsets) > 0 else 0.0),
            ("Z", section_offsets[1] if len(section_offsets) > 1 else 0.0),
        ):
            value_mm = float(value) * 1000.0
            if abs(value_mm) <= 1e-9:
                continue
            sign = "+" if value_mm > 0.0 else "-"
            tokens.append(f"{label}{sign}{PropertyPanel._format_positioning_value(abs(value_mm))}")
        if tokens:
            return " ".join(tokens)
        return "Centro geométrico"

    @staticmethod
    def _format_positioning_value(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"

    def _show_rigid_bar_properties(self, name: str) -> None:
        """Render only the calculated rigid-link stiffnesses."""
        title = QLabel("Propriedades mecânicas")
        title.setObjectName("propertySection")
        title.setToolTip(
            "Rigidezes equivalentes finitas: 10⁴ vezes a maior rigidez das barras conectadas."
        )
        self._add_context_widget(title)

        rigidities = calculate_rigid_bar_stiffness(
            self.window.model,
            self.window.model.rigid_bars[name],
        )
        properties = (
            ("EA", "Rigidez axial", rigidities.axial_ea_kn, "kN"),
            ("EIy", "Rigidez à flexão no eixo local y", rigidities.bending_eiy_kn_m2, "kN·m²"),
            ("EIz", "Rigidez à flexão no eixo local z", rigidities.bending_eiz_kn_m2, "kN·m²"),
            ("GJ", "Rigidez à torção", rigidities.torsional_gj_kn_m2, "kN·m²"),
        ) if rigidities is not None else ()
        values = QWidget()
        values_layout = QFormLayout(values)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(7)
        for symbol, tooltip, value, unit in properties:
            label_widget = QLabel(symbol)
            label_widget.setObjectName("propertySection")
            label_widget.setToolTip(tooltip)
            value_widget = self._stiffness_value_box(self._format_stiffness(value), unit)
            value_widget.setToolTip(tooltip)
            value_widget.setAccessibleName(f"{tooltip} da barra rígida ({symbol})")
            values_layout.addRow(label_widget, value_widget)
        if rigidities is None:
            unavailable = QLabel(
                "Defina material e seção em pelo menos uma barra conectada para calcular as rigidezes."
            )
            unavailable.setWordWrap(True)
            unavailable.setObjectName("propertySection")
            values_layout.addRow(unavailable)
        self._add_context_widget(values)

    @staticmethod
    def _stiffness_value_box(value: str, unit: str) -> QFrame:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; } "
            "QFrame#unitValueBox QLineEdit { border: 0; background: transparent; "
            "color: #57606a; padding: 2px 9px; } "
            "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
        )
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        field = QLineEdit(value)
        field.setReadOnly(True)
        field.setObjectName("unitValue")
        field.setMinimumWidth(0)
        row.addWidget(field, 1)
        row.addWidget(QLabel(unit))
        return box

    @staticmethod
    def _format_stiffness(value: float) -> str:
        return f"{value:.3e}".replace(".", ",", 1)

    def _add_context_widget(self, widget: QWidget) -> None:
        """Append a widget that is exclusive to a non-geometry inspector."""
        self._context_widgets.append(widget)
        self.layout.addWidget(widget)

    @staticmethod
    def _action_description(action) -> str:
        labels = {
            "node_force": "Força no nó",
            "node_moment": "Momento no nó",
            "member_distributed_force": "Força distribuída na barra",
            "member_moment": "Momento na barra",
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
        if kind == "rigid_bar":
            message = QLabel("Barras rígidas não recebem ações diretamente.")
            message.setWordWrap(True)
            self._add_context_widget(message)
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
            message = QLabel("Nenhum carregamento aplicado a este " + ("nó." if kind == "node" else "barra."))
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

        for label, value, unit in self._selected_action_fields("node", load_case):
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
    def _editable_unit_box(field: QDoubleSpinBox, unit: str) -> QFrame:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; }"
            "QFrame#unitValueBox QDoubleSpinBox { border: 0; background: transparent; "
            "color: #57606a; padding: 2px 9px; }"
            "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
        )
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(field, 1)
        layout.addWidget(QLabel(unit))
        return box

    @staticmethod
    def _percentage_unit_box(field: QLineEdit) -> QFrame:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; }"
            "QFrame#unitValueBox QLineEdit { border: 0; background: transparent; "
            "color: #57606a; padding: 2px 9px; }"
            "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
        )
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(field, 1)
        layout.addWidget(QLabel("%"))
        return box

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

    def _action_components_for_field(
        self, kind: str, label: str, actions: list,
    ) -> tuple[float, ...]:
        """Compare effective loads, including missing and explicit zero loads."""
        if kind == "node":
            action_kinds = {
                f"node_{'force' if label.startswith('F') else 'moment'}_{label[-1]}"
            }
        elif label.startswith("M"):
            action_kinds = {f"member_moment_{label[-1]}"} if self._member_action_reference == "local" else set()
        elif self._member_action_reference == "local":
            action_kinds = {f"member_distributed_force_local_{label[-1]}"}
        else:
            action_kinds = {
                f"member_distributed_force_{label[-1]}",
                f"member_distributed_force_global_{label[-1]}",
            }
            if label == "FZ":
                action_kinds.add("member_distributed_force_selfweight_Z")
        components: tuple[float, ...] = ()
        for action in actions:
            if action.kind in action_kinds:
                components = tuple(action.components)
        return () if all(value == 0 for value in components) else components

    def _selected_action_fields(
        self, kind: str, load_case: str | None,
    ) -> tuple[tuple[str, str, str], ...]:
        names = self._selected_names(kind)
        if not names:
            return ()
        fields = self._node_action_fields if kind == "node" else self._member_action_fields
        rows = fields(names[0], load_case)
        actions_by_target = {name: [] for name in names}
        if load_case:
            for action in self.window.model.actions.values():
                if action.load_case == load_case and action.target in actions_by_target:
                    actions_by_target[action.target].append(action)
        return tuple(
            (
                label,
                value if self._all_equal([
                    self._action_components_for_field(kind, label, actions_by_target[name])
                    for name in names
                ]) else "Variado",
                unit,
            )
            for label, value, unit in rows
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
        for node_name in self._selected_names("node"):
            if label.startswith("F"):
                self.window.action_service.add_node_force(node_name, label[-1], value, load_case)
            else:
                self.window.action_service.add_node_moment(node_name, label[-1], value, load_case)
        self._update_node_action_fields()
        self.window.refresh_scene()

    def _update_node_action_fields(self) -> None:
        if not self._selected or self._selected[0] != "node":
            return
        locked = self._is_selfweight_locked(self.window.selected_action_name)
        for label, value, _unit in self._selected_action_fields("node", self.window.selected_action_name):
            if input_field := self._node_action_inputs.get(label):
                input_field.setReadOnly(locked)
                input_field.setText(value)

    def _show_member_actions(self, name: str, select_available_reference: bool) -> None:
        load_case = self.window.selected_action_name
        selfweight_locked = self._is_selfweight_locked(load_case)
        if select_available_reference:
            self._member_action_reference = self._member_action_reference_for(name, load_case)
        self._member_action_inputs.clear()
        self._member_action_units.clear()
        self._member_action_boxes.clear()

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

        for label, value, unit in self._selected_action_fields("bar", load_case):
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
                "QFrame#unitValueBox[disabledValue=\"true\"] { background: #eaeef2; "
                "border-color: #d0d7de; }"
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
            global_moment = self._member_action_reference == "global" and label.startswith("M")
            field.setReadOnly(not editable)
            field.setMinimumWidth(0)
            field.setPlaceholderText("" if global_moment else "—")
            field.setAccessibleName(f"{label} ({unit})")
            field.editingFinished.connect(
                lambda field=field, action_label=label: self._member_action_changed(action_label, field)
            )
            self._member_action_inputs[label] = field
            unit_label = QLabel("" if global_moment else unit)
            self._member_action_units[label] = unit_label
            self._member_action_boxes[label] = value_box
            value_box.setProperty("disabledValue", global_moment)
            value_box.style().unpolish(value_box)
            value_box.style().polish(value_box)
            value_layout.addWidget(field, 1)
            value_layout.addWidget(unit_label)
            row_layout.addWidget(field_label)
            row_layout.addWidget(value_box, 1)
            self._add_context_widget(row)

    def _release_switch(self) -> QFrame:
        switch = QFrame()
        switch.setObjectName("releaseEndSwitch")
        switch.setFixedSize(70, 30)
        switch.setStyleSheet(
            "QFrame#releaseEndSwitch { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 15px; }"
        )
        indicator = QFrame(switch)
        indicator.setObjectName("releaseEndIndicator")
        indicator.setStyleSheet(
            "QFrame#releaseEndIndicator { background: #0969da; border: 0; border-radius: 10px; }"
        )
        self._release_switch_indicator = indicator
        layout = QHBoxLayout(switch)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        buttons = QButtonGroup(switch)
        buttons.setExclusive(True)
        for endpoint in ("A", "B"):
            button = QToolButton(switch)
            button.setText(endpoint)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedSize(31, 24)
            button.setStyleSheet(
                "QToolButton { border: 0; border-radius: 12px; padding: 0; background: transparent; "
                "font-size: 12px; font-weight: 600; }"
                "QToolButton:hover { background: transparent; }"
            )
            button.setChecked(endpoint == self._release_end)
            button.setAccessibleName(f"Exibir vinculações do extremo {endpoint}")
            button.clicked.connect(
                lambda checked=False, selected_endpoint=endpoint: self._set_release_end(selected_endpoint)
            )
            buttons.addButton(button)
            layout.addWidget(button)
            self._release_switch_buttons[endpoint] = button
        indicator.setGeometry(self._release_switch_indicator_geometry())
        indicator.lower()
        self._update_release_switch_text()
        return switch

    def _release_switch_indicator_geometry(self) -> QRect:
        if self._release_end == "A":
            return QRect(4, 5, 29, 20)
        return QRect(36, 5, 29, 20)

    def _update_release_switch_text(self) -> None:
        for endpoint, button in self._release_switch_buttons.items():
            color = "#ffffff" if endpoint == self._release_end else "#57606a"
            palette = button.palette()
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(color))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
            button.setPalette(palette)
            button.update()

    def _set_release_end(self, endpoint: str) -> None:
        if endpoint == self._release_end or endpoint not in {"A", "B"}:
            return
        self._release_end = endpoint
        if self._release_stack is not None:
            self._release_stack.setCurrentIndex(0 if endpoint == "A" else 1)
        if self._release_switch_animation is not None:
            self._release_switch_animation.stop()
        indicator = self._release_switch_indicator
        if indicator is not None:
            animation = QPropertyAnimation(indicator, b"geometry", indicator)
            animation.setDuration(160)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(indicator.geometry())
            animation.setEndValue(self._release_switch_indicator_geometry())
            self._release_switch_animation = animation
            animation.start()
        self._update_release_switch_text()

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
        fields = self._selected_action_fields("bar", self.window.selected_action_name)
        for label, value, _unit in fields:
            if input_field := self._member_action_inputs.get(label):
                global_moment = self._member_action_reference == "global" and label.startswith("M")
                input_field.setReadOnly(
                    self._is_selfweight_locked(self.window.selected_action_name)
                    or not (self._member_action_reference == "local" or label.startswith("F"))
                )
                input_field.setPlaceholderText("" if global_moment else "—")
                input_field.setText(value)
                if unit_label := self._member_action_units.get(label):
                    unit_label.setText("" if global_moment else _unit)
                if value_box := self._member_action_boxes.get(label):
                    value_box.setProperty("disabledValue", global_moment)
                    value_box.style().unpolish(value_box)
                    value_box.style().polish(value_box)

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

        action_service = self.window.action_service
        if label.startswith("F"):
            initial, final = values if len(values) == 2 else (values[0], values[0])
            direction = label[-1]
            for member_name in self._selected_names("bar"):
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
                        member_name, direction, initial, final, load_case,
                        self._member_action_reference,
                    )
        else:
            if len(values) != 1:
                self._update_member_action_fields()
                return
            for member_name in self._selected_names("bar"):
                action_service.add_member_moment(member_name, label[-1], values[0], load_case)
        self._update_member_action_fields()
        self.window.refresh_scene()

    def _show_analysis(self, kind: str, name: str) -> None:
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = QLabel("Resultados")
        title.setObjectName("propertySection")
        header_layout.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addStretch(1)
        if kind == "bar":
            header_layout.addWidget(self._analysis_result_switch(), 0, Qt.AlignmentFlag.AlignVCenter)
        self._add_context_widget(header)
        results = [
            result for result in self.window.model.analysis_results
            if result.model_revision == self.window.model.revision
        ]
        if not results:
            target = "no nó" if kind == "node" else "na barra"
            message = QLabel(f"Nenhum resultado disponível. Processe o modelo para consultar os resultados {target}.")
            message.setWordWrap(True)
            self._add_context_widget(message)
            return

        selected_reference = getattr(self.window, "selected_analysis_combination", None)
        result = next(
            (item for item in results if item.load_reference == selected_reference),
            results[0] if selected_reference is None else None,
        )
        data_key = "node_results" if kind == "node" else "member_results"
        names = self._selected_names(kind) or [name]
        values = [getattr(result, data_key).get(target) for target in names] if result is not None else []
        if not any(isinstance(value, dict) for value in values):
            if kind == "node":
                message = QLabel("Não há resultados para os nós selecionados." if len(names) > 1
                                 else "Não há resultados para este nó.")
            else:
                label = "barra rígida" if kind == "rigid_bar" else "barra"
                message = QLabel(f"Não há resultados para os {label}s selecionados." if len(names) > 1
                                 else f"Não há resultados para esta {label}.")
            message.setWordWrap(True)
            self._add_context_widget(message)
            return

        if kind == "node":
            self._show_node_analysis_values(self._common_analysis_values(values))
        else:
            self._show_member_analysis_values(values)

    @staticmethod
    def _common_analysis_values(values: list[dict | None]) -> dict:
        """Retain shared result components and mark differing or missing ones."""
        keys = dict.fromkeys(key for value in values if isinstance(value, dict) for key in value)
        return {
            key: next(value.get(key) for value in values if isinstance(value, dict) and key in value)
            if all(isinstance(value, dict) and key in value and value[key] == values[0].get(key)
                   for value in values)
            else "Variado"
            for key in keys
        }

    def _analysis_result_switch(self) -> QFrame:
        switch = QFrame()
        switch.setObjectName("analysisResultSwitch")
        switch.setFixedSize(112, 30)
        switch.setStyleSheet(
            "QFrame#analysisResultSwitch { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 15px; }"
        )
        indicator = QFrame(switch)
        indicator.setObjectName("analysisResultIndicator")
        indicator.setStyleSheet(
            "QFrame#analysisResultIndicator { background: #0969da; border: 0; border-radius: 10px; }"
        )
        self._analysis_switch_indicator = indicator
        layout = QHBoxLayout(switch)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        buttons = QButtonGroup(switch)
        buttons.setExclusive(True)
        for view, label, width, accessible_name in (
            ("A", "A", 32, "Exibir resultados do extremo A"),
            ("MAX", "MAX", 42, "Exibir resultados máximos"),
            ("B", "B", 32, "Exibir resultados do extremo B"),
        ):
            button = QToolButton(switch)
            button.setText(label)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedSize(width, 24)
            button.setStyleSheet(
                "QToolButton { border: 0; border-radius: 12px; padding: 0; background: transparent; "
                "font-size: 12px; font-weight: 600; }"
                "QToolButton:hover { background: transparent; }"
            )
            button.setChecked(view == self._analysis_result_view)
            button.setAccessibleName(accessible_name)
            button.clicked.connect(
                lambda checked=False, selected_view=view: self._set_analysis_result_view(selected_view)
            )
            buttons.addButton(button)
            layout.addWidget(button)
            self._analysis_switch_buttons[view] = button
        indicator.setGeometry(self._analysis_switch_indicator_geometry())
        indicator.lower()
        self._update_analysis_switch_text()
        return switch

    def _analysis_switch_indicator_geometry(self) -> QRect:
        return {
            "A": QRect(4, 5, 30, 20),
            "MAX": QRect(34, 5, 42, 20),
            "B": QRect(76, 5, 30, 20),
        }[self._analysis_result_view]

    def _update_analysis_switch_text(self) -> None:
        for view, button in self._analysis_switch_buttons.items():
            color = "#ffffff" if view == self._analysis_result_view else "#57606a"
            palette = button.palette()
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(color))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
            button.setPalette(palette)
            button.update()

    def _set_analysis_result_view(self, view: str) -> None:
        if view == self._analysis_result_view or view not in {"A", "MAX", "B"}:
            return
        if not self._selected or self._selected[0] != "bar":
            return
        self._analysis_result_view = view
        if self._analysis_switch_animation is not None:
            self._analysis_switch_animation.stop()
        indicator = self._analysis_switch_indicator
        if indicator is not None:
            animation = QPropertyAnimation(indicator, b"geometry", indicator)
            animation.setDuration(160)
            animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            animation.setStartValue(indicator.geometry())
            animation.setEndValue(self._analysis_switch_indicator_geometry())
            self._analysis_switch_animation = animation
            animation.start()
        self._update_analysis_switch_text()
        self.show_for(self._selected[0], self._selected[1], "Análise", selection=self._selection)

    def _show_node_analysis_values(self, values: dict) -> None:
        """Render all nodal result components with their analysis units."""
        self._add_analysis_value_group(
            "Deslocamentos",
            values,
            (
                ("DX", "X", "m"), ("DY", "Y", "m"), ("DZ", "Z", "m"),
            ),
        )
        self._add_analysis_value_group(
            "Rotações",
            values,
            (
                ("RX", "X", "rad"), ("RY", "Y", "rad"), ("RZ", "Z", "rad"),
            ),
        )
        self._add_analysis_value_group(
            "Reações",
            values,
            (
                ("RXN_FX", "Força X", "kN"),
                ("RXN_FY", "Força Y", "kN"),
                ("RXN_FZ", "Força Z", "kN"),
                ("RXN_MX", "Momento X", "kN·m"),
                ("RXN_MY", "Momento Y", "kN·m"),
                ("RXN_MZ", "Momento Z", "kN·m"),
            ),
        )

    def _show_member_analysis_values(self, values: list[dict | None]) -> None:
        """Render the selected member view for the active combination."""
        fields = self._member_analysis_fields()
        if self._analysis_result_view == "MAX":
            extrema = []
            for member_values in values:
                if not isinstance(member_values, dict):
                    extrema.append((None, None))
                    continue
                samples = member_values.get("samples") or tuple(
                    endpoint for endpoint in (member_values.get("start"), member_values.get("end"))
                    if isinstance(endpoint, dict)
                )
                samples = tuple(self._member_analysis_display_values(sample) for sample in samples)
                extrema.append(self._member_analysis_extrema(samples, fields))
            positive = self._common_analysis_values([pair[0] for pair in extrema])
            negative = self._common_analysis_values([pair[1] for pair in extrema])
            self._add_analysis_extrema_values(positive, negative, fields)
            return

        endpoint = "start" if self._analysis_result_view == "A" else "end"
        endpoint_values = [
            self._member_analysis_display_values(value[endpoint])
            if isinstance(value, dict) and isinstance(value.get(endpoint), dict) else None
            for value in values
        ]
        if any(isinstance(value, dict) for value in endpoint_values):
            self._add_analysis_value_group(
                None,
                self._common_analysis_values(endpoint_values),
                fields,
            )

    @staticmethod
    def _member_analysis_display_values(values: dict) -> dict:
        """Convert PyNite bending signs to the convention used by the application."""
        displayed = dict(values)
        for key in ("moment_y", "moment_z"):
            if key not in displayed:
                continue
            try:
                displayed[key] = -float(displayed[key])
            except (TypeError, ValueError):
                continue
        return displayed

    @staticmethod
    def _member_analysis_fields() -> tuple[tuple[str, str, str], ...]:
        return (
            ("axial", "Normal", "kN"),
            ("shear_y", "Cortante Y", "kN"),
            ("shear_z", "Cortante Z", "kN"),
            ("moment_y", "Fletor Y", "kN·m"),
            ("moment_z", "Fletor Z", "kN·m"),
            ("torque", "Torsor", "kN·m"),
            ("deflection_x", "Deformação X", "m"),
            ("deflection_y", "Deformação Y", "m"),
            ("deflection_z", "Deformação Z", "m"),
        )

    @staticmethod
    def _member_analysis_extrema(
        samples, fields: tuple[tuple[str, str, str], ...],
    ) -> tuple[dict[str, float], dict[str, float]]:
        positive: dict[str, float] = {}
        negative: dict[str, float] = {}
        for key, _label, _unit in fields:
            numbers = []
            for sample in samples:
                if not isinstance(sample, dict) or key not in sample:
                    continue
                try:
                    numbers.append(float(sample[key]))
                except (TypeError, ValueError):
                    continue
            positive[key] = max((number for number in numbers if number > 0.0), default=0.0)
            negative[key] = min((number for number in numbers if number < 0.0), default=0.0)
        return positive, negative

    def _add_analysis_value_group(
        self, title: str | None, values: dict, fields: tuple[tuple[str, str, str], ...],
    ) -> None:
        if title is not None:
            heading = QLabel(title)
            heading.setObjectName("propertySection")
            self._add_context_widget(heading)
        self._add_analysis_value_rows(values, fields)

    def _add_analysis_value_rows(
        self, values: dict, fields: tuple[tuple[str, str, str], ...],
    ) -> None:
        for key, label, unit in fields:
            if key in values:
                self._add_analysis_value_row(label, values[key], unit)

    def _add_analysis_extrema_values(
        self,
        positive: dict[str, float],
        negative: dict[str, float],
        fields: tuple[tuple[str, str, str], ...],
    ) -> None:
        """Show positive and negative extrema side by side to keep the panel compact."""
        values = QWidget()
        grid = QGridLayout(values)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(self.layout.spacing())

        positive_header = QLabel("Máx. +")
        negative_header = QLabel("Máx. −")
        for column, header in ((1, positive_header), (2, negative_header)):
            header.setObjectName("propertySection")
            header.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(header, 0, column)
        for row, (key, label, unit) in enumerate(fields, start=1):
            name = QLabel(label)
            name.setObjectName("propertySection")
            grid.addWidget(name, row, 0)

            positive_value = QLabel(self._format_analysis_number(positive.get(key, 0.0)))
            positive_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(positive_value, row, 1)

            negative_value = QLabel(self._format_analysis_number(negative.get(key, 0.0)))
            negative_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(negative_value, row, 2)

            unit_label = QLabel(unit)
            unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(unit_label, row, 3)
        grid.setColumnStretch(0, 1)
        self._add_context_widget(values)

    def _add_analysis_value_row(self, label: str, value, unit: str) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        name = QLabel(label)
        name.setObjectName("propertySection")
        row_layout.addWidget(name, 1)
        formatted = QLabel(self._format_analysis_value(value, unit))
        formatted.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(formatted)
        self._add_context_widget(row)

    @staticmethod
    def _format_analysis_value(value, unit: str) -> str:
        """Format solver values in the same compact, locale-aware style as diagrams."""
        if value == "Variado":
            return "Variado"
        return f"{PropertyPanel._format_analysis_number(value)} {unit}"

    @staticmethod
    def _format_analysis_number(value) -> str:
        """Format a result number without a unit for compact multi-column layouts."""
        if value == "Variado":
            return "Variado"
        try:
            rounded = round(float(value), 3)
        except (TypeError, ValueError):
            return "—"
        if rounded == 0.0:
            rounded = 0.0
        return f"{rounded:.3f}".rstrip("0").rstrip(".").replace(".", ",")

    def _refresh_size(self) -> None:
        if self.isVisible():
            self.layout.activate()
            self.setMinimumHeight(0)
            self.adjustSize()
            self.resize(self.width(), self.sizeHint().height())
            self.reposition()

    def _clear_form(self) -> None:
        self._clear_context_widgets()
        if self._displacement_settings_button is not None:
            self.window.close_displacement_panel(self._displacement_settings_button)
            self._displacement_settings_button = None
        if self._coordinates_widget is not None:
            self.layout.removeWidget(self._coordinates_widget)
            self._coordinates_widget.deleteLater()
            self._coordinates_widget = None
        if self._supports_widget is not None:
            self.layout.removeWidget(self._supports_widget)
            self._supports_widget.deleteLater()
            self._supports_widget = None
        self._support_stiffness_inputs.clear()
        if self._solid_offsets_widget is not None:
            self.layout.removeWidget(self._solid_offsets_widget)
            self._solid_offsets_widget.deleteLater()
            self._solid_offsets_widget = None
            self._positioning_status = None
        if self._releases_widget is not None:
            self.layout.removeWidget(self._releases_widget)
            self._releases_widget.deleteLater()
            self._releases_widget = None
            self._release_stack = None
            self._release_boxes.clear()
            self._release_rotation_percent_inputs.clear()
        if self._releases_header is not None:
            header = self._releases_header
            self.layout.removeWidget(header)
            # The title is reused on the next member selection. Detach it
            # before deleting the header so it is not destroyed with it.
            header.layout().removeWidget(self.releases_title)
            self.releases_title.setParent(self)
            self.releases_title.hide()
            header.deleteLater()
            self._releases_header = None
        if self._release_switch_animation is not None:
            self._release_switch_animation.stop()
        self._release_switch_animation = None
        self._release_switch_indicator = None
        self._release_switch_buttons.clear()
        self._release_end = "A"
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
        self.layout.removeWidget(self.solid_offsets_title)
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
        if self._analysis_switch_animation is not None:
            self._analysis_switch_animation.stop()
        self._analysis_switch_animation = None
        self._analysis_switch_indicator = None
        self._analysis_switch_buttons.clear()
        self._node_action_inputs.clear()
        for widget in self._context_widgets:
            self.layout.removeWidget(widget)
            widget.deleteLater()
        self._context_widgets.clear()
        self._member_action_inputs.clear()
        self._member_action_units.clear()
        self._member_action_boxes.clear()

    def _node_changed(self, axis: str) -> None:
        if not self._selected or self._selected[0] != "node": return
        index = ("X", "Y", "Z").index(axis)
        field = self.fields[index]
        if not isinstance(field, QDoubleSpinBox) or field.value() == field.minimum():
            return
        changes = {}
        for name in self._selected_names("node"):
            node = self.window.model.nodes[name]
            values = [node.x, node.y, node.z]
            values[index] = field.value()
            changes[name] = tuple(values)
        try:
            self.window.model_service.update_nodes_coordinates(changes)
        except ValueError as error:
            self.window.show_error(str(error))
            self.show_for("node", self._selected[1], self.window.palette.active_group or "Geometria",
                          selection=self._selection)
            return
        for name in changes:
            self.window.refresh_node(name)

    def _support_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "node" or self._supports_widget is None:
            return
        boxes = self._supports_widget.findChildren(QCheckBox)
        if len(boxes) != 6 or boxes[index].checkState() == Qt.CheckState.PartiallyChecked:
            return
        for name in self._selected_names("node"):
            values = list(self.window.model.nodes[name].supports)
            values[index] = boxes[index].isChecked()
            self.window.model_service.update_supports(name, tuple(values))
            self.window.refresh_node_visual(name)

    def _support_stiffness_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "node" or len(self._support_stiffness_inputs) != 6:
            return
        value = self._support_stiffness_inputs[index].value()
        if value < 0:
            return
        for name in self._selected_names("node"):
            values = list(self.window.model.nodes[name].support_stiffness)
            values[index] = value
            self.window.model_service.update_support_stiffness(name, tuple(values))

    def _bar_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "bar" or len(self.fields) != 2: return
        field = self.fields[index]
        if not isinstance(field, QComboBox) or not field.currentText():
            return
        try:
            for name in self._selected_names("bar"):
                bar = self.window.model.bars[name]
                nodes = [bar.start_node, bar.end_node]
                nodes[index] = field.currentText()
                self.window.model_service.update_member_nodes(name, *nodes)
            self.window.normalize_member_directions_if_enabled()
            self.window.refresh_scene()
            self.show_for("bar", self._selected[1], self.window.palette.active_group or "Geometria",
                          selection=self._selection)
        except ValueError:
            self.show_for("bar", self._selected[1], self.window.palette.active_group or "Geometria",
                          selection=self._selection)

    def _rigid_bar_changed(self) -> None:
        if not self._selected or self._selected[0] != "rigid_bar" or len(self.fields) != 2:
            return
        start, end = (field.currentText() for field in self.fields if isinstance(field, QComboBox))
        old_name = self._selected[1]
        try:
            rigid = self.window.model_service.update_rigid_bar_nodes(old_name, start, end)
        except ValueError:
            self.show_for("rigid_bar", old_name, self.window.palette.active_group or "Geometria",
                          selection=self._selection)
            return
        self._selected = "rigid_bar", rigid.name
        self.window.selected = self._selected
        self.window.selected_elements = [
            ("rigid_bar", rigid.name) if target == ("rigid_bar", old_name) else target
            for target in self.window.selected_elements
        ]
        self.window.refresh_rigid_bar_name(old_name, rigid.name)
        self.show_for("rigid_bar", rigid.name, self.window.palette.active_group or "Geometria",
                      selection=self.window.selected_elements)

    def _toggle_color_palette(self) -> None:
        if not self._selected or self._selected[0] != "bar":
            return
        if self._color_palette.isVisible():
            self._color_palette.hide()
            return
        if self.window.section_panel.isVisible():
            self.window.close_section_panel(self._section_settings_button)
        colors = [self.window.model.bars[name].color for name in self._selected_names("bar")]
        color = colors[0] if self._all_equal(colors) else ""
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
        member_names = self._selected_names("bar")
        for member_name in member_names:
            self.window.model_service.update_member_color(member_name, color)
        self.window.refresh_member_colors(member_names)
        self._set_member_color_button(color)

    def _delete_requested(self) -> None:
        self.window.delete_selected()

    def update_delete_button_state(self) -> None:
        """Keep node deletion disabled while members still reference it."""
        if self._selected is None or getattr(self.window, "selected", None) != self._selected:
            self.delete_button.setEnabled(False)
            return
        if len(self._selection) > 1:
            self.delete_button.setEnabled(any(kind in {"bar", "rigid_bar"} for kind, _ in self._selection)
                                          or any(kind == "node" for kind, _ in self._selection))
            self.delete_button.setToolTip("Excluir elementos selecionados")
            return
        kind, name = self._selected
        if kind == "bar":
            enabled = name in self.window.model.bars
            tooltip = "Excluir barra"
        elif kind == "rigid_bar":
            enabled = name in self.window.model.rigid_bars
            tooltip = "Excluir barra rígida"
        else:
            connected = any(
                member.start_node == name or member.end_node == name
                for member in self.window.model.bars.values()
            )
            connected = connected or any(
                rigid.start_node == name or rigid.end_node == name
                for rigid in self.window.model.rigid_bars.values()
            )
            enabled = name in self.window.model.nodes and not connected
            tooltip = "Excluir nó" if enabled else "Remova as barras vinculadas antes de excluir o nó"
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

    def _releases_changed(self, index: int, state: int) -> None:
        if not self._selected or self._selected[0] != "bar" or len(self._release_boxes) != 12:
            return
        if state == Qt.CheckState.PartiallyChecked.value:
            return
        checked = state == Qt.CheckState.Checked.value
        for name in self._selected_names("bar"):
            bar = self.window.model.bars[name]
            releases = list(bar.releases)
            releases[index] = not checked
            self.window.model_service.update_member_releases(name, tuple(releases))
            if index >= 6 and checked:
                values = list(bar.rotation_flexibility_percent)
                values[index - 6] = 0
                self.window.model_service.update_member_rotation_flexibility_percent(name, tuple(values))
            self.window.refresh_member_releases(name)
        percent = self._release_rotation_percent_inputs.get(index)
        if percent is not None:
            with QSignalBlocker(percent):
                percent.setText("0" if checked else "")
            percent.setEnabled(checked)

    def _release_rotation_percent_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "bar":
            return
        percent = self._release_rotation_percent_inputs.get(index)
        if percent is None or not 0 <= index < len(self._release_boxes):
            return
        try:
            value = int(percent.text() or "0")
        except ValueError:
            value = 0
        checkbox = self._release_boxes[index]
        if value >= 100:
            with QSignalBlocker(checkbox):
                checkbox.setCheckState(Qt.CheckState.Unchecked)
            with QSignalBlocker(percent):
                percent.setText("")
            percent.setEnabled(False)
            self._releases_changed(index, Qt.CheckState.Unchecked.value)
        else:
            value = max(value, 0)
            with QSignalBlocker(percent):
                percent.setText(str(value))
            for name in self._selected_names("bar"):
                values = list(self.window.model.bars[name].rotation_flexibility_percent)
                values[index - 6] = value
                self.window.model_service.update_member_rotation_flexibility_percent(name, tuple(values))
                self.window.refresh_member_releases(name)

    def _material_selected(self, material: str) -> None:
        # A section profile belongs to a material catalog. Changing material
        # invalidates the open geometry editor, so close it before rebuilding
        # the available section-family list.
        if self.window.section_panel.isVisible():
            self.window.close_section_panel(self._section_settings_button)
        if not self._selected or self._selected[0] != "bar" or material not in self.window.model.materials:
            return
        available = self._sections_for_material(material)
        for name in self._selected_names("bar"):
            self.window.model_service.assign_material(name, material)
            if self.window.model.bars[name].section not in available:
                self.window.model_service.assign_section(name, "")
                self.window.section_profiles.pop(name, None)
                self.window.section_geometry.pop(name, None)
            self.window.refresh_member_geometry(name)
        self.show_for("bar", self._selected[1], self.window.palette.active_group or "Geometria",
                      selection=self._selection)

    def _sections_for_material(self, material: str) -> list[str]:
        if material == "Indefinido":
            return []
        material_type = self.window.model.material_types.get(material, "Aço")
        return list(self.window.model.sections.get(material_type, []))

    def _section_selected(self, section: str) -> None:
        if self._section_settings_button is not None:
            self._section_settings_button.setEnabled(bool(section))
        if not self._selected or self._selected[0] != "bar" or not section:
            return
        for member_name in self._selected_names("bar"):
            self.window.model_service.assign_section(member_name, section)
            self.window.refresh_member_geometry(member_name)
            self.window.section_profiles.pop(member_name, None)
            self.window.section_geometry.pop(member_name, None)
        if self._section_profile_display is not None:
            self._section_profile_display.setText("Indefinido")
        if section and self.window.section_panel.isVisible():
            self.window.show_section_panel(section, self._section_settings_button)

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move(self.window.width() - margin - self.width() - 24,
                  (self.window.height() - self.height()) // 2)
        self.raise_()
