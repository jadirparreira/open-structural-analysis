"""Geometry editor for the single rectangular plate section."""

from .common import *


class _TrimmedDoubleSpinBox(QDoubleSpinBox):
    """Spin box that keeps its precision while hiding insignificant zeros."""

    def textFromValue(self, value: float) -> str:
        text = self.locale().toString(value, "f", self.decimals())
        decimal_point = self.locale().decimalPoint()
        if decimal_point in text:
            text = text.rstrip("0").rstrip(decimal_point)
        return text


class PlateSectionPanel(QFrame):
    """Floating editor for a 1 m wide rectangular plate strip."""

    WIDTH_MM = 1000.0

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._plate_name = ""
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title = QLabel("Geometria da seção")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(112)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.preview)

        self.profile_label = QLabel("Perfil")
        self.profile_label.setObjectName("propertySection")
        layout.addWidget(self.profile_label)
        self.profile_value = QLineEdit()
        self.profile_value.setObjectName("identityDisplay")
        self.profile_value.setReadOnly(True)
        self.profile_value.setAccessibleName("Perfil da placa")
        layout.addWidget(self.profile_value)

        parameter_row = QHBoxLayout()
        parameter_row.setSpacing(8)
        parameter = QLabel("t")
        parameter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        parameter.setFixedWidth(20)
        parameter.setToolTip("Espessura da placa")
        parameter_row.addWidget(parameter)
        self.thickness_box = QFrame()
        self.thickness_box.setObjectName("unitValueBox")
        self.thickness_box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; } "
            "QFrame#unitValueBox QDoubleSpinBox { border: 0; background: transparent; "
            "color: #57606a; padding: 2px 9px; min-height: 30px; height: 30px; } "
            "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
        )
        thickness_layout = QHBoxLayout(self.thickness_box)
        thickness_layout.setContentsMargins(0, 0, 0, 0)
        thickness_layout.setSpacing(0)
        self.thickness = _TrimmedDoubleSpinBox()
        self.thickness.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.thickness.setDecimals(2)
        self.thickness.setRange(0.01, 1_000_000.0)
        self.thickness.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed,
        )
        thickness_layout.addWidget(self.thickness, 1)
        thickness_layout.addWidget(QLabel("mm"))
        self.thickness.setAccessibleName("Espessura t da placa (mm)")
        self.thickness.editingFinished.connect(self._thickness_changed)
        parameter_row.addWidget(self.thickness_box, 1)

        self.geometric_properties_button = QToolButton()
        self.geometric_properties_button.setIcon(
            QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "table.svg"))
        )
        self.geometric_properties_button.setIconSize(QSize(18, 18))
        self.geometric_properties_button.setFixedSize(34, 34)
        self.geometric_properties_button.setCheckable(True)
        self.geometric_properties_button.setToolTip("Propriedades geométricas")
        self.geometric_properties_button.setAccessibleName("Propriedades geométricas")
        self.geometric_properties_button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
        )
        self.geometric_properties_button.toggled.connect(self._toggle_geometric_properties)
        parameter_row.addWidget(self.geometric_properties_button)
        layout.addLayout(parameter_row)

        self.geometric_properties = QWidget()
        properties_layout = QGridLayout(self.geometric_properties)
        properties_layout.setContentsMargins(0, 0, 0, 0)
        properties_layout.setHorizontalSpacing(8)
        properties_layout.setVerticalSpacing(6)
        self.area_value = self._readonly_value("cm²")
        self.inertia_value = self._readonly_value("cm⁴")
        properties_layout.addWidget(QLabel("A · faixa de 1 m"), 0, 0)
        properties_layout.addWidget(self.area_value, 0, 1)
        properties_layout.addWidget(QLabel("I · flexão da placa"), 1, 0)
        properties_layout.addWidget(self.inertia_value, 1, 1)
        self.geometric_properties.setToolTip(
            "Propriedades da faixa retangular de 1000 mm: "
            "A = b·t e I = b·t³/12."
        )
        self.geometric_properties.hide()
        layout.addWidget(self.geometric_properties)
        self.thickness.valueChanged.connect(self._update_geometry_display)
        self._update_geometry_display()
        self.hide()

    @staticmethod
    def _readonly_value(unit: str) -> QFrame:
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
        value = QLineEdit()
        value.setReadOnly(True)
        value.setObjectName("unitValue")
        row.addWidget(value, 1)
        row.addWidget(QLabel(unit))
        return box

    def configure_for_plate(self, name: str) -> None:
        self._plate_name = name
        plate = self.window.model.plates[name]
        with QSignalBlocker(self.thickness):
            self.thickness.setValue(plate.thickness_mm)
        self._update_geometry_display()

    def _thickness_changed(self) -> None:
        if self._plate_name not in self.window.model.plates:
            return
        self.window.model.update_plate(
            self._plate_name, thickness_mm=self.thickness.value(),
        )
        self._update_geometry_display()
        self.window.properties.update_plate_section_identity(self._plate_name)
        self.window.refresh_scene()

    def _toggle_geometric_properties(self, visible: bool) -> None:
        self.geometric_properties.setVisible(visible)
        self.layout().activate()
        self.adjustSize()
        if self.isVisible():
            self.reposition()

    def _update_geometry_display(self, *_args) -> None:
        thickness = self.thickness.value()
        self.profile_value.setText(self._section_name(thickness))
        area_cm2 = self.WIDTH_MM * thickness / 100.0
        inertia_cm4 = self.WIDTH_MM * thickness**3 / 12.0 / 10_000.0
        self.area_value.findChild(QLineEdit).setText(self._format(area_cm2))
        self.inertia_value.findChild(QLineEdit).setText(self._format(inertia_cm4))

        canvas_w, canvas_h = 270.0, 150.0
        profile_scale = min(
            (canvas_w - 34.0) / self.WIDTH_MM,
            (canvas_h - 28.0) / max(thickness, 1.0),
        )
        rect_w = self.WIDTH_MM * profile_scale
        rect_h = thickness * profile_scale
        x = (canvas_w - rect_w) / 2.0
        y = 14.0 + (canvas_h - 28.0 - rect_h) / 2.0
        hatch = (
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
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_w:g}" '
            f'height="{canvas_h:g}" viewBox="0 0 {canvas_w:g} {canvas_h:g}">'
            '<defs>' + hatch + '</defs>'
            '<rect x="0.75" y="0.75" '
            f'width="{canvas_w - 1.5:g}" height="{canvas_h - 1.5:g}" rx="6" '
            'fill="#fff" stroke="#d0d7de" stroke-width="1"/>'
            f'<rect x="{x:g}" y="{y:g}" width="{rect_w:g}" height="{rect_h:g}" '
            'fill="url(#hatch-ar-conc)" fill-rule="evenodd" stroke="#24292f" '
            'stroke-width="1.2" stroke-linejoin="round"/>'
            '</svg>'
        )
        pixmap = QPixmap(int(canvas_w), int(canvas_h))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
        painter.end()
        self.preview.setPixmap(pixmap)

    @staticmethod
    def _section_name(thickness: float) -> str:
        value = f"{thickness:g}".replace(".", ",")
        return f"R {value}"

    @staticmethod
    def _format(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"

    def reposition(self) -> None:
        prop = self.window.properties
        self.move(prop.x() - self.width() - 12,
                  prop.y() + (prop.height() - self.height()) // 2)
        self.raise_()
