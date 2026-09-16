from .common import *
from .profile_selector import ProfileComboBox


class SectionPanel(QFrame):
    """Floating section-geometry inspector shown beside member properties."""
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(280)
        # Let the panel size itself from its contents; a fixed/minimum height
        # used to compress the geometry rows when the widget was repositioned.
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._member_name = ""
        layout = QVBoxLayout(self); layout.setContentsMargins(14, 14, 14, 14); layout.setSpacing(8)
        title = QLabel("Geometria da seção"); title.setObjectName("propertyTitle"); layout.addWidget(title)
        self.profile_preview = QLabel()
        self.profile_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profile_preview.setFixedSize(250, 150)
        layout.addWidget(self.profile_preview)
        self.profile = ProfileComboBox()
        self.profile.setPlaceholderText("Indefinido")
        layout.addWidget(self.profile)
        self.profile.currentTextChanged.connect(self._profile_changed)
        self.geometry = QFormLayout(); self.geometry.setSpacing(6); layout.addLayout(self.geometry)
        self.fields = {}
        for label in ("d", "bf", "tw", "tf"):
            box, field = self._unit_box("mm")
            self.geometry.addRow(label, box); self.fields[label] = field
        weight_label = QLabel(); weight_label.setToolTip("Peso linear")
        weight_label.setPixmap(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "weight.svg")).pixmap(18, 18))
        weight_box, weight_value = self._unit_box("kg/m")
        self.geometry.addRow(weight_label, weight_box); self.weight_value = weight_value
        area_label = QLabel(); area_label.setToolTip("Área da seção")
        area_label.setPixmap(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "square-dimensions.svg")).pixmap(18, 18))
        area_box, area_value = self._unit_box("cm²")
        self.geometry.addRow(area_label, area_box); self.area_value = area_value
        layout.addStretch(); self.hide()

    @staticmethod
    def _unit_box(unit: str) -> tuple[QFrame, QLineEdit]:
        box = QFrame()
        box.setObjectName("unitValueBox")
        box.setStyleSheet("QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; } QFrame#unitValueBox QLineEdit { border: 0; background: transparent; color: #57606a; padding: 2px 9px; } QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }")
        row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
        value = QLineEdit(); value.setReadOnly(True); value.setObjectName("unitValue")
        row.addWidget(value, 1)
        row.addWidget(QLabel(unit))
        return box, value

    def configure_for(self, member_name: str, section: str) -> None:
        self._member_name = member_name
        member = self.window.model.bars.get(member_name)
        if member is not None:
            if member.profile:
                self.window.section_profiles[member_name] = member.profile
            if member.section_geometry:
                self.window.section_geometry[member_name] = member.geometry_dict()
        self.profile.blockSignals(True)
        self.profile.clear()
        self.profile.setPlaceholderText("Indefinido")
        profile_options = GERDAU_W_PROFILES if section == "W Laminado" else []
        self.profile.addItems(profile_options)
        # Keep the popup compact: eight rows are visible, with the remainder
        # available through the native popup scrollbar.
        profile = self.window.section_profiles.get(member_name, "")
        if profile in profile_options:
            self.profile.setCurrentText(profile)
        else:
            self.profile.setCurrentIndex(-1)
        self.profile.blockSignals(False)
        values = self.window.section_geometry.get(member_name)
        has_profile = bool(profile and profile in profile_options)
        if has_profile:
            values = self.window.section_geometry.setdefault(member_name, self._default_geometry(profile))
        for label, field in self.fields.items():
            field.blockSignals(True)
            field.setEnabled(has_profile)
            field.setText(f"{values.get(label, 0.0):.3f}" if values else "")
            field.blockSignals(False)
        self.weight_value.setEnabled(has_profile)
        self.area_value.setEnabled(has_profile)
        data = GERDAU_W_DATA.get(profile)
        self.weight_value.setText(f"{data[0]:.3f}" if data and has_profile else "")
        area = data[5] if data and len(data) > 5 else None
        self.area_value.setText(f"{area:.1f}" if area is not None and has_profile else "")
        self._update_preview(profile if has_profile else "W 200 x 15.0")
        # Recompute the floating frame size after rebuilding the profile form.
        # Without this, Qt may keep the very small size from the first show.
        self.layout().activate()
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())

    @staticmethod
    def _default_geometry(profile: str) -> dict[str, float]:
        # Defaults are kept in the catalog and copied into the member-specific
        # store; avoid rebuilding a 100-entry dictionary on every open.
        data = GERDAU_W_DATA.get(profile)
        if data is None:
            return {"d": 0.0, "bf": 0.0, "tw": 0.0, "tf": 0.0}
        return {"d": float(data[1]), "bf": float(data[2]),
                "tw": float(data[3]), "tf": float(data[4])}

    def _profile_changed(self, value: str) -> None:
        if not self._member_name:
            return
        self.window.section_profiles[self._member_name] = value
        # Keep the member's selected section in sync with the geometry editor.
        # The geometry data itself remains keyed by member, so another member
        # can safely use a different profile and dimensions.
        if value not in GERDAU_W_PROFILES:
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
        for key, field in self.fields.items():
            field.setEnabled(True)
            field.setText(f"{values.get(key, 0.0):.3f}")
        data = GERDAU_W_DATA.get(value)
        self.weight_value.setEnabled(True)
        self.weight_value.setText(f"{data[0]:.3f}" if data else "")
        self.area_value.setEnabled(True)
        area = data[5] if data and len(data) > 5 else None
        self.area_value.setText(f"{area:.1f}" if area is not None else "")
        self._update_preview(value)

    def _update_preview(self, profile: str) -> None:
        """Render a proportional W outline, always using a 300 px canvas height."""
        data = GERDAU_W_DATA.get(profile)
        if data:
            _mass, d, bf, tw, tf, _area = data
        else:
            _mass, d, bf, tw, tf, _area = (15.0, 200.0, 100.0, 6.0, 8.0, 19.4)
        canvas_w, canvas_h = 250.0, 150.0
        scale = (canvas_h - 28.0) / float(d)
        flange_w = min(canvas_w - 34.0, bf * scale)
        total_h = (canvas_h - 28.0)
        web_w = max(2.0, tw * scale)
        flange_h = max(2.0, tf * scale)
        x0 = (canvas_w - flange_w) / 2.0
        y0 = 14.0
        xweb = (canvas_w - web_w) / 2.0
        yweb = y0 + flange_h
        bottom_y = y0 + total_h - flange_h
        path = (
            f"M {x0:.2f},{y0:.2f} H {x0 + flange_w:.2f} V {yweb:.2f} "
            f"H {xweb + web_w:.2f} V {bottom_y:.2f} H {x0 + flange_w:.2f} "
            f"V {y0 + total_h:.2f} H {x0:.2f} V {bottom_y:.2f} "
            f"H {xweb:.2f} V {yweb:.2f} H {x0:.2f} Z"
        )
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:g}" height="{canvas_h:g}" '
               f'viewBox="0 0 {canvas_w:g} {canvas_h:g}"><rect x="0.75" y="0.75" '
               f'width="{canvas_w - 1.5:g}" height="{canvas_h - 1.5:g}" rx="6" fill="#fff" stroke="#d0d7de" stroke-width="1"/>'
               f'<path d="{path}" fill="none" stroke="#24292f" stroke-width="1" stroke-linejoin="round"/></svg>')
        pixmap = QPixmap(int(canvas_w), int(canvas_h))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        self.profile_preview.setPixmap(pixmap)

    def reposition(self):
        prop = self.window.properties
        self.move(prop.x() - self.width() - 12,
                  prop.y() + (prop.height() - self.height()) // 2)
        self.raise_()
