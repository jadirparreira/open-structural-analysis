from .common import *
from .color_palette import HoneycombColorPalette
from .window_frame import WindowFrame
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator


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
        self._identity_row = identity_row
        self.hide()

    def show_for(self, kind: str, name: str) -> None:
        self._selected = kind, name
        self._clear_form()
        self.coordinates_title.hide()
        self.nodes_title.hide()
        self.rotation_title.hide()
        self.releases_title.hide()
        self.supports_title.hide()
        self._color_palette.hide()
        self.member_color_button.setVisible(kind == "bar")
        self.title.setText("Nó" if kind == "node" else "Membro")
        self.name.setText("Identidade")
        self.identity_value.setText(name)
        if kind == "node":
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
            self._set_member_color_button(bar.color)
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

    def _refresh_size(self) -> None:
        if self.isVisible():
            self.layout.activate()
            self.setMinimumHeight(0)
            self.adjustSize()
            self.setMinimumHeight(self.sizeHint().height())
            self.reposition()

    def _clear_form(self) -> None:
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

    def _set_member_color_button(self, color: str) -> None:
        self.member_color_button.setStyleSheet(
            "QToolButton { background: %s; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover { border-color: #0969da; }" % color
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
