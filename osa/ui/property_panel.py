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
        self.layout.addWidget(self.title)
        self.layout.addWidget(self.name)
        self.layout.addWidget(self.identity_value)
        self.coordinates_title = QLabel("Coordenadas")
        self.coordinates_title.setObjectName("propertySection")
        self.nodes_title = QLabel("Nós")
        self.nodes_title.setObjectName("propertySection")
        self.supports_title = QLabel("Restrições")
        self.supports_title.setObjectName("propertySection")
        self.form = QFormLayout()
        self.form.setSpacing(7)
        self.layout.addLayout(self.form)
        self.fields: list[QDoubleSpinBox | QComboBox] = []
        self._coordinates_widget: QWidget | None = None
        self._supports_widget: QWidget | None = None
        self._material_widget: QWidget | None = None
        self._section_label: QLabel | None = None
        self._section_combo: QComboBox | None = None
        self._section_container: QWidget | None = None
        self._section_profile_display: QLineEdit | None = None
        self._support_refresh_timer = QTimer(self)
        self._support_refresh_timer.setSingleShot(True)
        self._support_refresh_timer.timeout.connect(self.window.refresh_scene)
        self.hide()

    def show_for(self, kind: str, name: str) -> None:
        self._selected = kind, name
        self._clear_form()
        self.coordinates_title.hide()
        self.nodes_title.hide()
        self.supports_title.hide()
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
            settings_button.setToolTip("Configurar seções")
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
            self._section_label, self._section_combo = section_label, section_combo
            self._section_profile_display = section_profile_display
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
        if self._material_widget is not None:
            self.layout.removeWidget(self._material_widget)
            self._material_widget.deleteLater()
            self._material_widget = None
        for widget_name in ("_section_label", "_section_combo", "_section_profile_display"):
            widget = getattr(self, widget_name)
            if widget is not None:
                self.layout.removeWidget(widget); widget.deleteLater(); setattr(self, widget_name, None)
        if self._section_container is not None:
            self.layout.removeWidget(self._section_container)
            self._section_container.deleteLater(); self._section_container = None
        self.layout.removeWidget(self.coordinates_title)
        self.layout.removeWidget(self.nodes_title)
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
            self.window.refresh_scene()

    def _support_changed(self, index: int) -> None:
        if not self._selected or self._selected[0] != "node" or self._supports_widget is None:
            return
        values = [box.isChecked() for box in self._supports_widget.findChildren(QCheckBox)]
        if len(values) == 6:
            self.window.model_service.update_supports(self._selected[1], tuple(values))
            # Defer and coalesce scene rebuilds while the user clicks several
            # restrictions in sequence, keeping the interface responsive.
            self._support_refresh_timer.start(250)

    def _bar_changed(self) -> None:
        if not self._selected or self._selected[0] != "bar" or len(self.fields) != 2: return
        start, end = (field.currentText() for field in self.fields if isinstance(field, QComboBox))
        try:
            self.window.model_service.update_member_nodes(self._selected[1], start, end)
            self.window.refresh_scene()
        except ValueError:
            pass

    def _material_selected(self, material: str) -> None:
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
            # Selecting a section type starts a fresh profile selection.
            self.window.section_profiles.pop(member_name, None)
            self.window.section_geometry.pop(member_name, None)
            if self._section_profile_display is not None:
                self._section_profile_display.setText("Indefinido")

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move(self.window.width() - margin - self.width() - 24,
                  (self.window.height() - self.height()) // 2)
        self.raise_()
