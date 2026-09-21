from .common import *
from .profile_selector import ProfileComboBox
from osa.sections.contours import (
    c_formed_svg_path,
    cartola_formed_svg_path,
    concrete_circular_hollow_svg_path,
    concrete_circular_svg_path,
    concrete_i_svg_path,
    concrete_l_svg_path,
    concrete_plus_svg_path,
    concrete_rectangular_hollow_svg_path,
    concrete_rectangular_svg_path,
    concrete_t_svg_path,
    concrete_u_svg_path,
    i_svg_path,
    l_formed_svg_path,
    l_svg_path,
    rounded_rect_svg_path,
    t_svg_path,
    u_formed_svg_path,
    u_svg_path,
    w_svg_path,
    z_formed_svg_path,
)


class SectionPanel(QFrame):
    """Floating section-geometry inspector shown beside member properties."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(340)
        # Let the panel size itself from its contents; a fixed/minimum height
        # used to compress the geometry rows when the widget was repositioned.
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._member_name = ""
        self._section_family = ""
        self._decimals = {
            "d": 0, "bf": 0, "tw": 2, "tf": 2,
            "b": 0, "t": 2, "c": 0, "D": 0, "De": 0, "Di": 0, "h": 0,
            "weight": 1, "area": 1,
            "Iy": 0, "Iz": 0, "J": 2,
        }
        layout = QVBoxLayout(self); layout.setContentsMargins(14, 14, 14, 14); layout.setSpacing(8)
        title = QLabel("Geometria da seção"); title.setObjectName("propertyTitle"); layout.addWidget(title)
        self.profile_preview = QLabel()
        self.profile_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profile_preview.setMinimumHeight(150)
        self.profile_preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.profile_preview)
        self.profile = ProfileComboBox()
        self.profile.setPlaceholderText("Indefinido")
        profile_row = QHBoxLayout(); profile_row.setSpacing(6)
        profile_row.addWidget(self.profile, 1)
        self.mechanical_toggle = QToolButton()
        self.mechanical_toggle.setCheckable(True)
        self.mechanical_toggle.setChecked(False)
        self.mechanical_toggle.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "table.svg")))
        # Match the visual treatment of the member's "Configurar seção"
        # button; only the icon and action differ.
        self.mechanical_toggle.setIconSize(QSize(18, 18)); self.mechanical_toggle.setFixedSize(34, 34)
        self.mechanical_toggle.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
        )
        self.mechanical_toggle.setToolTip("Propriedades mecânicas")
        self.mechanical_toggle.setAccessibleName("Propriedades mecânicas")
        self.mechanical_toggle.toggled.connect(self._toggle_mechanical_properties)
        profile_row.addWidget(self.mechanical_toggle)
        layout.addLayout(profile_row)
        self.profile.currentTextChanged.connect(self._profile_changed)
        self.geometry = QGridLayout(); self.geometry.setSpacing(6); layout.addLayout(self.geometry)
        self.geometry.setColumnStretch(1, 1)
        self.geometry.setColumnStretch(3, 1)
        self.fields = {}
        self._geometry_widgets = []
        # Keep the internal field keys in their plain form while rendering the
        # conventional mathematical subscripts in the property labels.
        label_markup = {"d": "d", "bf": "b<sub>f</sub>",
                        "tw": "t<sub>w</sub>", "tf": "t<sub>f</sub>",
                        "b": "b", "t": "t", "c": "c", "D": "D",
                        "De": "D<sub>e</sub>", "Di": "D<sub>i</sub>",
                        "h": "h"}
        label_tooltips = {
            "d": "Altura total da seção",
            "bf": "Largura da mesa",
            "tw": "Espessura da alma",
            "tf": "Espessura da mesa",
            "b": "Largura da aba da cantoneira",
            "t": "Espessura da cantoneira",
            "c": "Comprimento do enrijecedor",
            "D": "Diâmetro externo",
            "De": "Diâmetro externo",
            "Di": "Diâmetro interno",
            "h": "Altura externa",
        }
        for label in ("d", "bf", "tw", "tf", "b", "t", "c", "D", "De", "Di", "h"):
            box, field = self._unit_box("mm")
            label_widget = QLabel(label_markup[label])
            label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.editingFinished.connect(self._manual_geometry_changed)
            self._geometry_widgets.append((label_widget, box, field))
        self._geometry_label_markup = label_markup
        self._geometry_tooltips = label_tooltips
        weight_label = QLabel(); weight_label.setToolTip("Peso linear")
        weight_label.setPixmap(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "weight.svg")).pixmap(18, 18))
        weight_box, weight_value = self._unit_box("kg/m")
        self.weight_label = weight_label
        self.weight_box = weight_box
        self.weight_value = weight_value
        area_label = QLabel(); area_label.setToolTip("Área da seção")
        area_label.setPixmap(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "square-dimensions.svg")).pixmap(18, 18))
        area_box, area_value = self._unit_box("cm²")
        self.area_label = area_label
        self.area_box = area_box
        self.area_value = area_value
        self._set_geometry_layout("W Laminado")
        self.mechanical_container = QWidget()
        mechanical_layout = QVBoxLayout(self.mechanical_container)
        # Keep the separation balanced: the panel's 8 px layout spacing is
        # used both before and after the divider.
        mechanical_layout.setContentsMargins(0, 0, 0, 0)
        mechanical_layout.setSpacing(8)
        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: #e1e4e8; border: 0;")
        mechanical_layout.addWidget(separator)
        self.mechanical = QGridLayout(); self.mechanical.setSpacing(6)
        self.mechanical.setColumnStretch(1, 1); self.mechanical.setColumnStretch(3, 1)
        mechanical_layout.addLayout(self.mechanical)
        self.mechanical_fields = {}
        self.mechanical_widgets = {}
        mechanical_data = (
            ("area", "cm²"),
            ("weight", "kg/m"),
            ("Iy", "cm⁴"),
            ("Iz", "cm⁴"),
            ("J", "cm⁴"),
        )
        mechanical_markup = {"Iy": "I<sub>y</sub>", "Iz": "I<sub>z</sub>", "J": "J"}
        mechanical_tooltips = {
            "area": "Área da seção",
            "weight": "Peso linear",
            "Iy": "Momento de inércia em torno do eixo local y do PyNite",
            "Iz": "Momento de inércia em torno do eixo local z do PyNite",
            "J": "Constante de torção de Saint-Venant",
        }
        for index, (name, unit) in enumerate(mechanical_data):
            if name == "area":
                label_widget, box, field = self.area_label, self.area_box, self.area_value
            elif name == "weight":
                label_widget, box, field = self.weight_label, self.weight_box, self.weight_value
            else:
                box, field = self._unit_box(unit)
                label_widget = QLabel(mechanical_markup[name])
            row, column = index // 2, (index % 2) * 2
            label_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label_widget.setToolTip(mechanical_tooltips[name])
            box.setToolTip(mechanical_tooltips[name])
            self.mechanical.addWidget(label_widget, row, column)
            self.mechanical.addWidget(box, row, column + 1)
            self.mechanical_fields[name] = field
            self.mechanical_widgets[name] = (label_widget, box)
        mechanical_layout.addStretch()
        self.mechanical_container.setVisible(False)
        layout.addWidget(self.mechanical_container)
        layout.addStretch(); self.hide()

    def _toggle_mechanical_properties(self, visible: bool) -> None:
        self.mechanical_container.setVisible(visible)
        self.layout().activate()
        self.adjustSize()
        if self.isVisible() and hasattr(self.window, "properties"):
            self.reposition()

    @staticmethod
    def _unit_box(unit: str) -> tuple[QFrame, QLineEdit]:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet("QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; } QFrame#unitValueBox QLineEdit { border: 0; background: transparent; color: #57606a; padding: 2px 9px; } QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }")
        row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
        value = QLineEdit(); value.setReadOnly(True); value.setObjectName("unitValue")
        value.setMinimumWidth(0)
        row.addWidget(value, 1)
        row.addWidget(QLabel(unit))
        return box, value

    def configure_for(self, member_name: str, section: str) -> None:
        self._member_name = member_name
        self._section_family = section
        self._set_geometry_layout(section)
        self._set_mechanical_visibility()
        # Each member opens with the optional mechanical block collapsed.
        self.mechanical_toggle.setChecked(False)
        member = self.window.model.bars.get(member_name)
        if member is not None:
            if member.profile:
                self.window.section_profiles[member_name] = member.profile
            if member.section_geometry:
                self.window.section_geometry[member_name] = member.geometry_dict()
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.setPlaceholderText("Indefinido")
        profile_options = SECTION_PROFILE_OPTIONS.get(section, [])
        self.profile.addItems(profile_options)
        # Keep the popup compact: eight rows are visible, with the remainder
        # available through the native popup scrollbar.
        profile = self.window.section_profiles.get(member_name, "")
        if profile in profile_options:
            self.profile.setCurrentText(profile)
        else:
            self.profile.setCurrentIndex(-1)
        self.profile.blockSignals(False)
        is_manual = section in SECTION_PARAMETRIC_SPECS
        self.profile.setEnabled(not is_manual)
        values = self.window.section_geometry.get(member_name)
        if section == "Tipo L" and values:
            # Projects created while the optional angle existed may still
            # carry that key; keep the right-angle L data in the new schema.
            values = {name: values[name] for name in ("b", "h", "t") if name in values}
            self.window.section_geometry[member_name] = values
        elif section == "Circular Vazado" and values and "d" not in values:
            # Migrate the former De/Di representation to diameter and wall
            # thickness when an older project is reopened.
            outer = values.get("De")
            inner = values.get("Di")
            if outer is not None and inner is not None:
                values = {"d": float(outer), "t": (float(outer) - float(inner)) / 2.0}
                self.window.section_geometry[member_name] = values
        # Manual sections do not have catalog entries. Their identity is
        # generated from the dimensions entered by the user, so old projects
        # that still contain the former generic label are normalized as soon
        # as the geometry panel is opened.
        if is_manual and values and all(
            values.get(name, 0) > 0 for name, _tooltip, _unit in SECTION_PARAMETRIC_SPECS[section]
        ):
            generated_profile = self._manual_profile_name(values)
            if profile != generated_profile:
                self.window.section_profiles[member_name] = generated_profile
                self.window.model_service.assign_profile(member_name, generated_profile, values)
                self.window.refresh_member_geometry(member_name)
            profile = generated_profile
            display = getattr(self.window.properties, "_section_profile_display", None)
            if display is not None:
                display.setText(profile)
        if is_manual:
            self.profile.setPlaceholderText(profile or "Indefinido")
        has_profile = is_manual or bool(profile and profile in profile_options)
        if has_profile:
            if is_manual:
                values = values or {}
            else:
                values = self.window.section_geometry.setdefault(member_name, self._default_geometry(profile))
        for label, field in self.fields.items():
            field.blockSignals(True)
            field.setEnabled(has_profile)
            field.setReadOnly(not is_manual)
            field.setText(self._format_value(values[label], label) if values and label in values else "")
            field.blockSignals(False)
        self.weight_value.setEnabled(has_profile)
        self.area_value.setEnabled(has_profile)
        for field in self.mechanical_fields.values():
            field.setEnabled(has_profile)
            field.clear()
        properties = None
        preview_invalid = False
        if has_profile and values and all(values.get(name, 0) > 0 for name in self.fields):
            try:
                properties = self._calculate_properties(values)
            except ValueError:
                # Keep the panel usable when an older project contains
                # dimensions that no longer satisfy the minimum limits.
                properties = None
                preview_invalid = True
        if is_manual and values:
            required = tuple(self.fields)
            if any(name not in values for name in required):
                preview_pending = True
            elif any(float(values.get(name, 0)) <= 0 for name in required):
                preview_invalid = True
        self._populate_calculated_values(properties, has_profile)
        preview_values = values if has_profile else None
        if not has_profile and profile_options:
            # Keep the selector and fields undefined while showing the first
            # catalogued profile as the family-specific initial drawing.
            preview_values = self._default_geometry(profile_options[0])
        if not is_manual or not values:
            preview_pending = False
        else:
            preview_pending = any(name not in values for name in self.fields)
        self._update_preview(
            preview_values,
            invalid=preview_invalid,
            pending=preview_pending,
        )
        # Recompute the floating frame size after rebuilding the profile form.
        # Without this, Qt may keep the very small size from the first show.
        self.layout().activate()
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())

    def _default_geometry(self, profile: str) -> dict[str, float]:
        # Defaults are kept in the catalog and copied into the member-specific
        # store; avoid rebuilding a 100-entry dictionary on every open.
        data = self._profile_data(profile)
        if data is None:
            return {name: 0.0 for name, _key, _unit in self._geometry_specs}
        return {
            name: float(data[data_key])
            for name, data_key, _unit in self._geometry_specs
            if data_key in data
        }

    def _profile_changed(self, value: str) -> None:
        if not self._member_name:
            return
        self.window.section_profiles[self._member_name] = value
        # Keep the member's selected section in sync with the geometry editor.
        # The geometry data itself remains keyed by member, so another member
        # can safely use a different profile and dimensions.
        profile_options = SECTION_PROFILE_OPTIONS.get(self._section_family, [])
        if value not in profile_options:
            return
        if self._member_name in self.window.model.bars:
            display = getattr(self.window.properties, "_section_profile_display", None)
            if display is not None:
                display.setText(value)
        # A profile change initializes that member's dimensions only; it never
        # reuses or mutates another member's geometry values.
        values = self.window.section_geometry.setdefault(
            self._member_name, self._default_geometry(value)
        )
        values.update(self._default_geometry(value))
        self.window.model_service.assign_profile(self._member_name, value, values)
        self.window.refresh_member_geometry(self._member_name)
        for key, field in self.fields.items():
            field.setEnabled(True)
            field.setText(self._format_value(values.get(key, 0.0), key))
        self.weight_value.setEnabled(True)
        self.area_value.setEnabled(True)
        for field in self.mechanical_fields.values():
            field.setEnabled(True)
        self._populate_calculated_values(self._calculate_properties(values), True)
        self._update_preview(values)

    def _manual_geometry_changed(self) -> None:
        """Persist editable dimensions for non-catalogued section families."""
        if self._section_family not in SECTION_PARAMETRIC_SPECS or not self._member_name:
            return
        values: dict[str, float] = {}
        entered = [field.text().strip() for field in self.fields.values()]
        if not any(entered):
            self._update_preview(None)
            return
        try:
            for name, field in self.fields.items():
                text = field.text().strip().replace(",", ".")
                if not text:
                    self._update_preview(
                        None,
                        pending=True,
                    )
                    return
                value = float(text)
                if value <= 0:
                    self._update_preview(
                        None,
                        invalid=True,
                    )
                    return
                values[name] = value
        except ValueError:
            self._update_preview(
                None,
                invalid=True,
            )
            return
        # Normalize the stored geometry as well as its visual representation.
        # Formed and tubular dimensions use whole millimetres (with two
        # decimals for t); bar dimensions use one decimal place.
        bar_families = {"Barra Circular", "Barra Quadrada", "Barra Retangular"}
        concrete_families = {
            "Retangular", "Circular", "Tipo +", "Tipo L", "Tipo T", "Tipo U",
            "Tipo I", "Retangular Vazado", "Circular Vazado",
        }
        wood_families = {"Circular", "Quadrada", "Retangular"}
        member = self.window.model.bars.get(self._member_name)
        material_type = (
            self.window.model.material_types.get(member.material)
            if member is not None else None
        )
        for name in values:
            if self._section_family in wood_families and material_type == "Madeira":
                values[name] = round(values[name], 1)
            elif self._section_family in concrete_families:
                # Concrete dimensions accept at most one decimal when the
                # user explicitly enters it; integer input remains integer.
                values[name] = round(values[name], 1)
            elif self._section_family in bar_families:
                values[name] = round(values[name], 1)
            else:
                values[name] = round(values[name], 2) if name == "t" else round(values[name])
        square_family = {
            "Tubular Retangular": "Tubular Quadrado",
            "Barra Retangular": "Barra Quadrada",
        }.get(self._section_family)
        if self._section_family == "Retangular" and material_type == "Madeira":
            square_family = "Quadrada"
        if square_family and values.get("b") == values.get("h"):
            square_values = {"b": values["b"]}
            if "t" in values:
                square_values["t"] = values["t"]
            self._switch_to_square_family(square_family, square_values)
            return
        # Validate the complete geometry before changing the member model.
        # This enforces the minimum dimensions for each concrete family and
        # prevents an invalid edit from being persisted.
        try:
            properties = self._calculate_properties(values)
        except ValueError:
            self._update_preview(None, invalid=True)
            return
        # Keep the displayed dimensions consistent with the section rules.
        for name, field in self.fields.items():
            field.setText(self._format_value(values[name], name))
        profile = self._manual_profile_name(values)
        self.window.section_profiles[self._member_name] = profile
        self.profile.setPlaceholderText(profile)
        self.window.section_geometry[self._member_name] = values
        self.window.model_service.assign_profile(self._member_name, profile, values)
        display = getattr(self.window.properties, "_section_profile_display", None)
        if display is not None:
            display.setText(profile)
        self._populate_calculated_values(properties, True)
        self._update_preview(values)
        self.window.refresh_member_geometry(self._member_name)

    def _switch_to_square_family(self, family: str, geometry: dict[str, float]) -> None:
        """Replace an equal-sided rectangular family without losing input."""
        if not self._member_name:
            return
        self.window.model_service.assign_section(self._member_name, family)
        member = self.window.model.bars.get(self._member_name)
        if member is not None:
            material_type = self.window.model.material_types.get(member.material, "Aço")
            sections = self.window.model.sections.setdefault(material_type, [])
            if family not in sections:
                sections.append(family)
        self.window.section_profiles.pop(self._member_name, None)
        self.window.section_geometry[self._member_name] = geometry
        combo = getattr(self.window.properties, "_section_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            if combo.findText(family) < 0:
                combo.addItem(family)
            combo.setCurrentText(family)
            combo.blockSignals(False)
        button = getattr(self.window.properties, "_section_settings_button", None)
        self.window.show_section_panel(family, button)
        self.window.refresh_member_geometry(self._member_name)

    def _manual_profile_name(self, values: dict[str, float]) -> str:
        """Build the catalog-style identity for a manual section."""
        if self._section_family == "Tubular Circular":
            return f"TC {float(values['D']):.0f} x {float(values['t']):.2f}"
        if self._section_family == "Tubular Quadrado":
            return f"TQ {float(values['b']):.0f} x {float(values['t']):.2f}"
        if self._section_family == "Tubular Retangular":
            return f"TR {float(values['b']):.0f} x {float(values['h']):.0f} x {float(values['t']):.2f}"
        if self._section_family == "Barra Circular":
            return f"BC {float(values['d']):.1f}"
        if self._section_family == "Barra Quadrada":
            return f"BQ {float(values['b']):.1f}"
        if self._section_family == "Barra Retangular":
            return f"BR {float(values['b']):.1f} x {float(values['h']):.1f}"
        member = self.window.model.bars.get(self._member_name)
        material_type = (
            self.window.model.material_types.get(member.material)
            if member is not None else None
        )
        if material_type == "Madeira":
            if self._section_family == "Circular":
                return f"C {float(values['d']):.1f}"
            if self._section_family == "Quadrada":
                return f"Q {float(values['b']):.1f}"
            if self._section_family == "Retangular":
                return f"R {float(values['b']):.1f} x {float(values['h']):.1f}"
        if self._section_family == "Quadrada":
            return f"BQ {float(values['b']):.1f}"
        concrete_families = {
            "Retangular", "Circular", "Tipo +", "Tipo L", "Tipo T", "Tipo U",
            "Tipo I", "Retangular Vazado", "Circular Vazado",
        }
        if self._section_family in concrete_families:
            prefixes = {
                "Retangular": "R",
                "Circular": "C",
                "Tipo L": "L",
                "Tipo T": "T",
                "Tipo I": "I",
                "Tipo U": "U",
                "Tipo +": "+",
                "Retangular Vazado": "RV",
                "Circular Vazado": "CV",
            }
            parts = []
            for name, _tooltip, _unit in SECTION_PARAMETRIC_SPECS[self._section_family]:
                value = float(values[name])
                decimals = 1 if value % 1 else 0
                parts.append(f"{value:.{decimals}f}")
            return f"{prefixes[self._section_family]} {' x '.join(parts)}"
        prefixes = {
            "U Formado": "U",
            "C Formado": "C",
            "Z Formado": "Z",
            "L Formado": "L",
            "Cartola Formado": "Ω",
        }
        prefix = prefixes.get(self._section_family, self._section_family)
        # C and Cartola include the stiffener length before the thickness in
        # their public designation, even though Cartola's input grid stores t
        # before c for the established visual layout.
        names = ("d", "bf", "c", "t") if self._section_family in {"C Formado", "Cartola Formado"} else ("d", "bf", "t")
        parts = []
        for name in names:
            value = float(values[name])
            decimals = 2 if name == "t" else 0
            text = f"{value:.{decimals}f}"
            parts.append(text)
        return f"{prefix} {' x '.join(parts)}"

    def _format_value(self, value: float, parameter: str) -> str:
        """Format a section value with the precision used by its parameter."""
        decimals = self._decimals[parameter]
        concrete_families = {
            "Retangular", "Circular", "Tipo +", "Tipo L", "Tipo T", "Tipo U",
            "Tipo I", "Retangular Vazado", "Circular Vazado",
        }
        wood_families = {"Circular", "Quadrada", "Retangular"}
        if (
            self._section_family in concrete_families
            or self._section_family in wood_families
        ) and parameter in {"b", "h", "t", "d", "De", "Di"}:
            decimals = 1 if float(value) % 1 else 0
        if self._section_family in {"Barra Circular", "Barra Quadrada", "Barra Retangular"} and parameter in {"d", "b", "h"}:
            decimals = 1
        if parameter in {"Iy", "Iz"} and 0 < abs(float(value)) < 1:
            decimals = 2
        return f"{float(value):.{decimals}f}"

    def _set_mechanical_visibility(self) -> None:
        # Recreate the grid itself. QGridLayout keeps row/column geometry even
        # after its items are removed, which left W-sized gaps in the U panel.
        for label_widget, box in self.mechanical_widgets.values():
            label_widget.hide()
            box.hide()
        container_layout = self.mechanical_container.layout()
        container_layout.removeItem(self.mechanical)
        while self.mechanical.count():
            self.mechanical.takeAt(0)
        self.mechanical.deleteLater()
        self.mechanical = QGridLayout()
        self.mechanical.setSpacing(6)
        self.mechanical.setColumnStretch(1, 1)
        self.mechanical.setColumnStretch(3, 1)
        container_layout.insertLayout(1, self.mechanical)
        positions = {
            "area": (0, 0),
            "weight": (0, 2),
            "Iy": (1, 0),
            "Iz": (1, 2),
            "J": (2, 0),
        }
        for name, (row, column) in positions.items():
            label_widget, box = self.mechanical_widgets[name]
            label_widget.setVisible(True)
            box.setVisible(True)
            self.mechanical.addWidget(label_widget, row, column)
            self.mechanical.addWidget(box, row, column + 1)

    def _set_geometry_layout(self, section: str) -> None:
        definitions = {
            "W Laminado": (("d", "d_mm", "mm"), ("bf", "bf_mm", "mm"),
                           ("tw", "tw_mm", "mm"), ("tf", "tf_mm", "mm")),
            "U Laminado": (("d", "d_mm", "mm"), ("bf", "bf_mm", "mm"),
                           ("tw", "tw_mm", "mm"), ("tf", "tf_mm", "mm")),
            "I Laminado": (("d", "d_mm", "mm"), ("bf", "bf_mm", "mm"),
                           ("tw", "tw_mm", "mm"), ("tf", "tf_mm", "mm")),
            "L Laminado": (("b", "b_mm", "mm"), ("t", "t_mm", "mm")),
            "T Laminado": (("d", "d_mm", "mm"), ("bf", "bf_mm", "mm"),
                           ("tw", "tw_mm", "mm"), ("tf", "tf_mm", "mm")),
        }
        if section in SECTION_PARAMETRIC_SPECS:
            self._geometry_specs = tuple((name, name, unit) for name, _tooltip, unit in SECTION_PARAMETRIC_SPECS[section])
        else:
            self._geometry_specs = definitions.get(section, definitions["W Laminado"])
        while self.geometry.count():
            self.geometry.takeAt(0)
        self.fields = {}
        for label_widget, box, _field in self._geometry_widgets:
            label_widget.hide()
            box.hide()
        for index, (name, _data_key, unit) in enumerate(self._geometry_specs):
            label_widget, box, field = self._geometry_widgets[index]
            label_widget.setText(self._geometry_label_markup[name])
            manual_tooltips = {
                parameter: tooltip
                for parameter, tooltip, _unit in SECTION_PARAMETRIC_SPECS.get(section, ())
            }
            tooltip = manual_tooltips.get(name, self._geometry_tooltips[name])
            label_widget.setToolTip(tooltip)
            box.setToolTip(tooltip)
            box.findChildren(QLabel)[0].setText(unit)
            row, column = index // 2, (index % 2) * 2
            label_widget.show()
            box.show()
            self.geometry.addWidget(label_widget, row, column)
            self.geometry.addWidget(box, row, column + 1)
            self.fields[name] = field

    def _calculate_properties(self, geometry: dict[str, float]):
        member = self.window.model.bars.get(self._member_name)
        density = member.material_values[3] if member is not None else 7850.0
        return self.window.section_property_service.calculate(self._section_family, geometry, density)

    def _populate_calculated_values(self, properties, enabled: bool) -> None:
        values = {
            "area": properties.area_cm2 if properties else None,
            "weight": properties.mass_kg_m if properties else None,
            "Iy": properties.iy_cm4 if properties else None,
            "Iz": properties.iz_cm4 if properties else None,
            "J": properties.j_cm4 if properties else None,
        }
        for name, field in self.mechanical_fields.items():
            value = values[name]
            field.setText(self._format_value(value, name) if value is not None and enabled else "")

    def _update_preview(
        self,
        geometry: dict[str, float] | None,
        invalid: bool = False,
        pending: bool = False,
    ) -> None:
        """Render a proportional outline from the member's stored geometry."""
        if invalid or pending:
            # Invalid and incomplete entries are intentionally represented by
            # the untouched initial preview for the selected family.
            geometry = None
        geometry = geometry or {}
        family = self._section_family
        concrete_families = {
            "Retangular", "Circular", "Tipo L", "Tipo T", "Tipo I",
            "Tipo U", "Tipo +", "Retangular Vazado", "Circular Vazado",
        }
        if not geometry and family in {"U Formado", "C Formado", "Z Formado", "L Formado", "Cartola Formado"}:
            geometry = {"d": 200.0, "bf": 80.0, "t": 6.0}
            if family in {"C Formado", "Cartola Formado"}:
                geometry["c"] = 40.0
        elif not geometry and family in {"Tubular Retangular", "Barra Retangular"}:
            # Give the initial rectangular preview a clearly rectangular
            # proportion before the user enters the actual dimensions.
            geometry = {"b": 100.0, "h": 200.0}
        elif not geometry and family == "Retangular":
            geometry = {"b": 200.0, "h": 300.0}
        elif not geometry and family == "Circular":
            geometry = {"d": 200.0}
        elif not geometry and family == "Quadrada":
            geometry = {"b": 200.0}
        elif not geometry and family == "Tipo L":
            geometry = {"b": 200.0, "h": 300.0, "t": 40.0}
        elif not geometry and family in {"Tipo T", "Tipo I", "Tipo U", "Tipo +", "Retangular Vazado"}:
            geometry = {"b": 240.0, "h": 300.0, "t": 40.0}
        elif not geometry and family == "Circular Vazado":
            geometry = {"d": 240.0, "t": 40.0}
        if family in {"Tubular Circular", "Barra Circular"}:
            d = float(geometry.get("D", geometry.get("d", 200.0)))
            bf = d
            tw = tf = float(geometry.get("t", d * 0.08))
        elif family in {"Tubular Quadrado", "Barra Quadrada", "Quadrada"}:
            d = bf = float(geometry.get("b", 200.0))
            tw = tf = float(geometry.get("t", d * 0.08))
        elif family in {"Tubular Retangular", "Barra Retangular"}:
            d = float(geometry.get("h", 200.0))
            bf = float(geometry.get("b", d))
            tw = tf = float(geometry.get("t", min(d, bf) * 0.08))
        elif family == "Circular":
            d = bf = float(geometry.get("d", 200.0))
            tw = tf = d * 0.08
        elif family == "Circular Vazado":
            d = bf = float(geometry.get("d", 240.0))
            tw = tf = float(geometry.get("t", d * 0.15))
        elif family in concrete_families:
            d = float(geometry.get("h", geometry.get("b", 200.0)))
            bf = float(geometry.get("b", geometry.get("h", d)))
            tw = tf = float(geometry.get("t", min(d, bf) * 0.15))
        else:
            d = float(geometry.get("d", geometry.get("b", 200.0)))
            bf = float(geometry.get("bf", geometry.get("b", d)))
            tw = float(geometry.get("tw", geometry.get("t", 6.0)))
            tf = float(geometry.get("tf", geometry.get("t", 8.0)))
        # Follow the available panel width so the drawing frame aligns with
        # the profile selector and value boxes.
        canvas_w, canvas_h = max(1.0, float(self.profile_preview.width())), 150.0
        scale = (canvas_h - 28.0) / float(d)
        flange_w = min(canvas_w - 34.0, bf * scale)
        total_h = (canvas_h - 28.0)
        web_w = max(3.0, tw * scale)
        flange_h = max(2.0, tf * scale)
        x0 = (canvas_w - flange_w) / 2.0
        y0 = 14.0
        xweb = (canvas_w - web_w) / 2.0
        yweb = y0 + flange_h
        bottom_y = y0 + total_h - flange_h
        if family in concrete_families or family == "Quadrada":
            if family == "Circular":
                width = height = float(geometry.get("d", 200.0))
            elif family == "Quadrada":
                width = height = float(geometry.get("b", 200.0))
            elif family == "Circular Vazado":
                width = height = float(geometry.get("d", 240.0))
            else:
                width = float(geometry.get("b", 200.0))
                height = float(geometry.get("h", 300.0))
            profile_scale = min(
                (canvas_w - 34.0) / max(width, 1.0),
                (canvas_h - 28.0) / max(height, 1.0),
            )
            cx, cy = canvas_w / 2.0, y0 + total_h / 2.0
            if family in {"Retangular", "Quadrada"}:
                path = concrete_rectangular_svg_path(
                    width * profile_scale, height * profile_scale, cx, cy
                )
            elif family == "Circular":
                path = concrete_circular_svg_path(width * profile_scale, cx, cy)
            elif family == "Tipo L":
                path = concrete_l_svg_path(
                    width * profile_scale,
                    height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale,
                    cx=cx,
                    cy=cy,
                )
            elif family == "Tipo T":
                path = concrete_t_svg_path(
                    width * profile_scale, height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale, cx, cy
                )
            elif family == "Tipo I":
                path = concrete_i_svg_path(
                    width * profile_scale, height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale, cx, cy
                )
            elif family == "Tipo U":
                path = concrete_u_svg_path(
                    width * profile_scale, height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale, cx, cy
                )
            elif family == "Tipo +":
                path = concrete_plus_svg_path(
                    width * profile_scale, height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale, cx, cy
                )
            elif family == "Retangular Vazado":
                path = concrete_rectangular_hollow_svg_path(
                    width * profile_scale, height * profile_scale,
                    float(geometry.get("t", 40.0)) * profile_scale, cx, cy
                )
            else:  # Circular Vazado
                outer_diameter = width
                wall = float(geometry.get("t", 40.0))
                path = concrete_circular_hollow_svg_path(
                    outer_diameter * profile_scale,
                    max(0.0, outer_diameter - 2.0 * wall) * profile_scale,
                    cx,
                    cy,
                )
        elif family == "Tubular Circular":
            radius = min(canvas_w, total_h) * 0.34
            cx, cy = canvas_w / 2.0, y0 + total_h / 2.0
            profile_scale = min(
                (canvas_w - 34.0) / d,
                (canvas_h - 28.0) / d,
            )
            outer_radius = d * profile_scale / 2.0
            inner_radius = max(0.0, outer_radius - float(geometry.get("t", d * 0.08)) * profile_scale)
            radius = outer_radius
            path = (
                f"M {cx + radius:.2f},{cy:.2f} "
                f"A {radius:.2f},{radius:.2f} 0 1 1 {cx - radius:.2f},{cy:.2f} "
                f"A {radius:.2f},{radius:.2f} 0 1 1 {cx + radius:.2f},{cy:.2f} Z "
                f"M {cx + inner_radius:.2f},{cy:.2f} "
                f"A {inner_radius:.2f},{inner_radius:.2f} 0 1 0 {cx - inner_radius:.2f},{cy:.2f} "
                f"A {inner_radius:.2f},{inner_radius:.2f} 0 1 0 {cx + inner_radius:.2f},{cy:.2f} Z"
            )
        elif family in {"Tubular Quadrado", "Tubular Retangular"}:
            profile_scale = min(
                (canvas_w - 34.0) / bf,
                (canvas_h - 28.0) / d,
            )
            outer_w = bf * profile_scale
            outer_h = d * profile_scale
            wall = float(geometry.get("t", min(d, bf) * 0.08)) * profile_scale
            inner_w = max(0.0, outer_w - 2.0 * wall)
            inner_h = max(0.0, outer_h - 2.0 * wall)
            x_rect = (canvas_w - outer_w) / 2.0
            y_rect = y0 + (total_h - outer_h) / 2.0
            path = (
                f"{rounded_rect_svg_path(x_rect, y_rect, outer_w, outer_h, 2.0 * wall)} "
                f"{rounded_rect_svg_path(x_rect + wall, y_rect + wall, inner_w, inner_h, wall)}"
            )
        elif family in {"Barra Circular", "Barra Quadrada", "Barra Retangular"}:
            if family == "Barra Circular":
                radius = min(canvas_w, total_h) * 0.34
                cx, cy = canvas_w / 2.0, y0 + total_h / 2.0
                path = (
                    f"M {cx + radius:.2f},{cy:.2f} "
                    f"A {radius:.2f},{radius:.2f} 0 1 1 {cx - radius:.2f},{cy:.2f} "
                    f"A {radius:.2f},{radius:.2f} 0 1 1 {cx + radius:.2f},{cy:.2f} Z"
                )
            else:
                x_rect = (canvas_w - flange_w) / 2.0
                path = (
                    f"M {x_rect:.2f},{y0:.2f} H {x_rect + flange_w:.2f} "
                    f"V {y0 + total_h:.2f} H {x_rect:.2f} V {y0:.2f} Z"
                )
        elif family in {"U Formado", "C Formado"}:
            xweb_outer = x0
            xweb_inner = x0 + web_w
            bottom_y = y0 + total_h - flange_h
            radius = min(
                3.0,
                flange_h * 0.65,
                web_w * 1.2,
            )
            path = (
                f"M {xweb_outer:.2f},{y0:.2f} "
                f"H {x0 + flange_w:.2f} "
                f"V {y0 + flange_h:.2f} "
                f"H {xweb_inner + radius:.2f} "
                f"Q {xweb_inner:.2f},{y0 + flange_h:.2f} "
                f"{xweb_inner:.2f},{y0 + flange_h + radius:.2f} "
                f"V {bottom_y - radius:.2f} "
                f"Q {xweb_inner:.2f},{bottom_y:.2f} "
                f"{xweb_inner + radius:.2f},{bottom_y:.2f} "
                f"H {x0 + flange_w:.2f} "
                f"V {y0 + total_h:.2f} "
                f"H {xweb_outer:.2f} "
                f"V {y0:.2f} "
                f"Z"
            )
        elif family in {"L Laminado", "L Formado"}:
            path = (
                f"M {x0:.2f},{y0:.2f} H {x0 + flange_w:.2f} "
                f"V {y0 + flange_h:.2f} H {x0 + web_w:.2f} "
                f"V {y0 + total_h:.2f} H {x0:.2f} V {y0:.2f} Z"
            )
        elif family == "T Laminado":
            xweb = (canvas_w - web_w) / 2.0
            path = (
                f"M {x0:.2f},{y0:.2f} H {x0 + flange_w:.2f} "
                f"V {y0 + flange_h:.2f} H {xweb + web_w:.2f} "
                f"V {y0 + total_h:.2f} H {xweb:.2f} "
                f"V {y0 + flange_h:.2f} H {x0:.2f} Z"
            )
        elif family == "Z Formado":
            path = (
                f"M {x0 + flange_w:.2f},{y0:.2f} H {x0:.2f},{y0:.2f} "
                f"V {y0 + flange_h:.2f} H {xweb + web_w:.2f} "
                f"V {bottom_y:.2f} H {xweb:.2f} V {y0 + total_h:.2f} "
                f"H {x0 + flange_w:.2f} V {bottom_y:.2f} H {xweb + web_w:.2f} "
                f"V {y0 + flange_h:.2f} H {x0 + flange_w:.2f} Z"
            )
        elif family == "Cartola Formado":
            path = (
                f"M {x0:.2f},{y0:.2f} H {x0 + flange_w:.2f},{y0:.2f} "
                f"V {y0 + flange_h:.2f} H {xweb + web_w:.2f} "
                f"V {y0 + total_h - flange_h:.2f} H {xweb:.2f} "
                f"V {y0 + flange_h:.2f} H {x0:.2f} Z"
            )
        else:
            radius = min(3.0, flange_h * 0.65, web_w * 1.2)
            path = (
                f"M {x0:.2f},{y0:.2f} H {x0 + flange_w:.2f} V {yweb:.2f} "
                f"H {xweb + web_w + radius:.2f} Q {xweb + web_w:.2f},{yweb:.2f} {xweb + web_w:.2f},{yweb + radius:.2f} "
                f"V {bottom_y - radius:.2f} Q {xweb + web_w:.2f},{bottom_y:.2f} {xweb + web_w + radius:.2f},{bottom_y:.2f} H {x0 + flange_w:.2f} "
                f"V {y0 + total_h:.2f} H {x0:.2f} V {bottom_y:.2f} "
                f"H {xweb - radius:.2f} Q {xweb:.2f},{bottom_y:.2f} {xweb:.2f},{bottom_y - radius:.2f} "
                f"V {yweb + radius:.2f} Q {xweb:.2f},{yweb:.2f} {xweb - radius:.2f},{yweb:.2f} H {x0:.2f} Z"
            )
        if family == "W Laminado" and geometry and {"d", "bf", "tw", "tf"} <= geometry.keys():
            radius = float(geometry.get("r", geometry.get("r_mm", 10.0)))
            profile_scale = min(
                (canvas_w - 34.0) / bf,
                (canvas_h - 28.0) / d,
            )
            path = w_svg_path(
                d * profile_scale,
                bf * profile_scale,
                tw * profile_scale,
                tf * profile_scale,
                radius * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family in {"U Laminado", "U Inclinado Laminado"} and geometry and {"d", "bf", "tw", "tf"} <= geometry.keys():
            radius = geometry.get("r", geometry.get("r_mm"))
            tip_radius = geometry.get("r1", geometry.get("r1_mm"))
            flange_angle = float(geometry.get("flange_angle_deg", 2.0))
            profile_scale = min(
                (canvas_w - 34.0) / bf,
                (canvas_h - 28.0) / d,
            )
            path = u_svg_path(
                d * profile_scale,
                bf * profile_scale,
                tw * profile_scale,
                tf * profile_scale,
                None if radius is None else float(radius) * profile_scale,
                None if tip_radius is None else float(tip_radius) * profile_scale,
                flange_angle,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family == "L Laminado" and geometry and {"b", "t"} <= geometry.keys():
            leg = float(geometry["b"])
            thickness = float(geometry["t"])
            inner_radius = geometry.get("r1", geometry.get("r1_mm"))
            tip_radius = geometry.get("r2", geometry.get("r2_mm"))
            profile_scale = min(
                (canvas_w - 34.0) / leg,
                (canvas_h - 28.0) / leg,
            )
            path = l_svg_path(
                leg * profile_scale,
                thickness * profile_scale,
                None if inner_radius is None else float(inner_radius) * profile_scale,
                None if tip_radius is None else float(tip_radius) * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family == "T Laminado" and geometry and {"d", "bf", "tw", "tf"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            web_thickness = float(geometry["tw"])
            flange_thickness = float(geometry["tf"])
            inner_radius = geometry.get("r1", geometry.get("r1_mm"))
            tip_radius = geometry.get("r2", geometry.get("r2_mm"))
            profile_scale = min(
                (canvas_w - 34.0) / flange_width,
                (canvas_h - 28.0) / depth,
            )
            path = t_svg_path(
                depth * profile_scale,
                flange_width * profile_scale,
                web_thickness * profile_scale,
                flange_thickness * profile_scale,
                None if inner_radius is None else float(inner_radius) * profile_scale,
                None if tip_radius is None else float(tip_radius) * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family == "I Laminado" and geometry and {"d", "bf", "tw", "tf"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            web_thickness = float(geometry["tw"])
            flange_thickness = float(geometry["tf"])
            inner_radius = geometry.get("r1", geometry.get("r1_mm"))
            tip_radius = geometry.get("r2", geometry.get("r2_mm"))
            profile_scale = min(
                (canvas_w - 34.0) / flange_width,
                (canvas_h - 28.0) / depth,
            )
            path = i_svg_path(
                depth * profile_scale,
                flange_width * profile_scale,
                web_thickness * profile_scale,
                flange_thickness * profile_scale,
                None if inner_radius is None else float(inner_radius) * profile_scale,
                None if tip_radius is None else float(tip_radius) * profile_scale,
                float(geometry.get("flange_angle_deg", 2.0)),
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family in {"U Formado", "C Formado"} and geometry and {"d", "bf", "t"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            thickness = float(geometry["t"])
            profile_scale = min(
                (canvas_w - 34.0) / flange_width,
                (canvas_h - 28.0) / depth,
            )
            if family == "U Formado":
                path = u_formed_svg_path(
                    depth * profile_scale,
                    flange_width * profile_scale,
                    thickness * profile_scale,
                    cx=canvas_w / 2.0,
                    cy=y0 + total_h / 2.0,
                )
            elif {"d", "bf", "c", "t"} <= geometry.keys():
                path = c_formed_svg_path(
                    depth * profile_scale,
                    flange_width * profile_scale,
                    float(geometry["c"]) * profile_scale,
                    thickness * profile_scale,
                    cx=canvas_w / 2.0,
                    cy=y0 + total_h / 2.0,
                )
        elif family == "Z Formado" and geometry and {"d", "bf", "t"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            thickness = float(geometry["t"])
            profile_scale = min(
                (canvas_w - 34.0) / (2.0 * flange_width + thickness),
                (canvas_h - 28.0) / depth,
            )
            path = z_formed_svg_path(
                depth * profile_scale,
                flange_width * profile_scale,
                thickness * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family == "L Formado" and geometry and {"d", "bf", "t"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            thickness = float(geometry["t"])
            profile_scale = min(
                (canvas_w - 34.0) / flange_width,
                (canvas_h - 28.0) / depth,
            )
            path = l_formed_svg_path(
                depth * profile_scale,
                flange_width * profile_scale,
                thickness * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        elif family == "Cartola Formado" and geometry and {"d", "bf", "c", "t"} <= geometry.keys():
            depth = float(geometry["d"])
            flange_width = float(geometry["bf"])
            lip = float(geometry["c"])
            thickness = float(geometry["t"])
            profile_scale = min(
                (canvas_w - 34.0) / (flange_width + 2.0 * lip),
                (canvas_h - 28.0) / depth,
            )
            path = cartola_formed_svg_path(
                depth * profile_scale,
                flange_width * profile_scale,
                lip * profile_scale,
                thickness * profile_scale,
                cx=canvas_w / 2.0,
                cy=y0 + total_h / 2.0,
            )
        self.profile_preview.setToolTip(
            "Geometria Inválida"
            if invalid
            else "Parâmetros Incompletos"
            if pending
            else ""
        )
        invalid_icon = ""
        if invalid:
            icon_x = canvas_w - 30.0
            icon_y = canvas_h - 30.0
            invalid_icon = (
                f'<g transform="translate({icon_x:g} {icon_y:g})" fill="none" '
                'stroke="#cf222e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="m15 9-6 6"/>'
                '<path d="M2.586 16.726A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586-1.414l4.688-4.688A2 2 0 0 1 8.688 2h6.624a2 2 0 0 1 1.414.586l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414.586H8.688a2 2 0 0 1-1.414-.586z"/>'
                '<path d="m9 9 6 6"/></g>'
            )
        elif pending:
            icon_x = canvas_w - 30.0
            icon_y = canvas_h - 30.0
            invalid_icon = (
                f'<g transform="translate({icon_x:g} {icon_y:g})" fill="none" '
                'stroke="#f2b705" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
                '<path d="M12 9v4"/><path d="M12 17h.01"/></g>'
            )
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:g}" height="{canvas_h:g}" '
               f'viewBox="0 0 {canvas_w:g} {canvas_h:g}">'
               '<defs>'
               '<pattern id="hatch-ansi32" patternUnits="userSpaceOnUse" width="16" height="16" patternTransform="rotate(45)">'
               '<path d="M 0 0 H 16" stroke="#64748b" stroke-width="1" opacity="0.65"/>'
               '</pattern>'
               '<pattern id="hatch-ar-conc" patternUnits="userSpaceOnUse" width="48" height="48">'
               '<path d="M 4 8 l 5 -3 M 17 5 l 4 4 M 31 10 l 6 -5 M 43 4 l 3 5 '
               'M 1 24 l 6 -4 M 14 20 l 4 5 M 28 25 l 5 -4 M 40 21 l 6 3 '
               'M 6 40 l 5 -5 M 19 44 l 4 -3 M 33 39 l 6 5 M 44 45 l 3 -4" '
               'stroke="#64748b" stroke-width="0.8" opacity="0.65"/>'
               '<circle cx="10" cy="15" r="0.7" fill="#64748b" opacity="0.65"/>'
               '<circle cx="25" cy="14" r="0.9" fill="#64748b" opacity="0.65"/>'
               '<circle cx="38" cy="17" r="0.6" fill="#64748b" opacity="0.65"/>'
               '<circle cx="8" cy="31" r="0.8" fill="#64748b" opacity="0.65"/>'
               '<circle cx="23" cy="34" r="0.6" fill="#64748b" opacity="0.65"/>'
               '<circle cx="42" cy="32" r="0.9" fill="#64748b" opacity="0.65"/>'
               '</pattern>'
               '<pattern id="hatch-wood" patternUnits="userSpaceOnUse" width="72" height="48" patternTransform="rotate(45)">'
               '<path d="M 0 8 C 12 2, 24 14, 36 8 S 60 2, 72 8 '
               'M 0 24 C 12 18, 24 30, 36 24 S 60 18, 72 24 '
               'M 0 40 C 12 34, 24 46, 36 40 S 60 34, 72 40" '
               'fill="none" stroke="#64748b" stroke-width="0.9" opacity="0.65"/>'
               '</pattern>'
               '</defs>'
               f'<rect x="0.75" y="0.75" '
               f'width="{canvas_w - 1.5:g}" height="{canvas_h - 1.5:g}" rx="6" fill="#fff" stroke="#d0d7de" stroke-width="1"/>'
               f'<path d="{path}" fill="url(#{self._hatch_pattern_id(family)})" fill-rule="evenodd" stroke="#24292f" stroke-width="1.2" stroke-linejoin="round"/>'
               f'{invalid_icon}</svg>')
        pixmap = QPixmap(int(canvas_w), int(canvas_h))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        self.profile_preview.setPixmap(pixmap)

    def _hatch_pattern_id(self, family: str) -> str:
        """Select the material hatch used inside the section contour."""
        member = self.window.model.bars.get(self._member_name)
        material_type = (
            self.window.model.material_types.get(member.material)
            if member is not None else None
        )
        if material_type == "Madeira" or family == "Quadrada":
            # WOOD/SACNCR is represented by the wood-grain hatch pattern.
            return "hatch-wood"
        if material_type == "Concreto" or family in {
            "Retangular", "Circular", "Tipo L", "Tipo T", "Tipo I",
            "Tipo U", "Tipo +", "Retangular Vazado", "Circular Vazado",
        }:
            return "hatch-ar-conc"
        return "hatch-ansi32"

    def _profile_data(self, profile: str):
        return SECTION_PROFILE_DATA.get(self._section_family, {}).get(profile)

    def reposition(self):
        prop = self.window.properties
        self.move(prop.x() - self.width() - 12,
                  prop.y() + (prop.height() - self.height()) // 2)
        self.raise_()


class WSectionPanel(SectionPanel):
    """Panel dedicated to W and HP rolled profiles."""
    FAMILY = "W Laminado"

    def configure_for(self, member_name: str, section: str = FAMILY) -> None:
        super().configure_for(member_name, self.FAMILY)


class WLaminadoSectionPanel(WSectionPanel):
    """Explicit W Laminado panel type kept separate for family-specific UI."""


class USectionPanel(SectionPanel):
    """Panel dedicated to U rolled profiles."""
    FAMILY = "U Laminado"

    def configure_for(self, member_name: str, section: str = FAMILY) -> None:
        super().configure_for(member_name, self.FAMILY)


class ULaminadoSectionPanel(USectionPanel):
    """Explicit U Laminado panel with its own parameter set and drawing."""


class LSectionPanel(SectionPanel):
    """Panel dedicated to equal-leg rolled-angle profiles."""
    FAMILY = "L Laminado"

    def configure_for(self, member_name: str, section: str = FAMILY) -> None:
        super().configure_for(member_name, self.FAMILY)


class LLaminadoSectionPanel(LSectionPanel):
    """Explicit L Laminado panel with its own parameter set and drawing."""


class TSectionPanel(SectionPanel):
    """Panel dedicated to rolled-T profiles."""
    FAMILY = "T Laminado"

    def configure_for(self, member_name: str, section: str = FAMILY) -> None:
        super().configure_for(member_name, self.FAMILY)


class TLaminadoSectionPanel(TSectionPanel):
    """Explicit T Laminado panel with its own parameter set and drawing."""


class ISectionPanel(SectionPanel):
    """Panel dedicated to American rolled-I profiles."""
    FAMILY = "I Laminado"

    def configure_for(self, member_name: str, section: str = FAMILY) -> None:
        super().configure_for(member_name, self.FAMILY)


class ILaminadoSectionPanel(ISectionPanel):
    """Explicit I Laminado panel with its own parameter set and drawing."""


class ParametricSectionPanel(SectionPanel):
    """Panel for formed, tubular and bar families defined by user dimensions."""

    def __init__(self, window, family: str):
        self.FAMILY = family
        super().__init__(window)

    def configure_for(self, member_name: str, section: str = "") -> None:
        super().configure_for(member_name, self.FAMILY)
