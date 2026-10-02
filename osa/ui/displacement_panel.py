"""Painel flutuante reservado à configuração de deslocamentos do membro."""

from math import isfinite

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator, QTransform

from .common import *
from .navigation_buttons import LeftArrowButton, RightArrowButton, SlopedPlaneButton, VerticalArrowButton


class DisplacementPanel(QFrame):
    """Floating member-displacement editor kept aligned with the section panel."""

    WIDTH = 300

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Posicionamento do membro")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        layout.addSpacing(6)

        controls = QWidget()
        grid = QGridLayout(controls)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        up = VerticalArrowButton(controls)
        down = VerticalArrowButton(controls, point_down=True)
        left = LeftArrowButton(controls)
        right = RightArrowButton(controls)
        for control, rotation_degrees, position in (
            (up, -90, "superior"),
            (down, 90, "inferior"),
            (left, 180, "esquerdo"),
            (right, 0, "direito"),
        ):
            control.setProperty("controlBackground", "#ffffff")
            control.setIcon(self._rotated_icon("chevron-right.svg", rotation_degrees))
            control.setIconSize(QSize(18, 18))
            control.setAccessibleName(f"Controle externo {position} de posicionamento")
        grid.addWidget(up, 0, 2, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(left, 2, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(right, 2, 4, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(down, 4, 2, Qt.AlignmentFlag.AlignCenter)

        for row, column, mirrored, rotation_degrees in (
            (1, 1, False, -90),  # Noroeste: 90° anti-horário.
            (1, 3, True, 90),    # Nordeste: 90° horário.
            (3, 1, True, -90),   # Sudoeste: 90° anti-horário.
            (3, 3, False, 90),   # Sudeste: 90° horário.
        ):
            corner = SlopedPlaneButton(
                controls,
                mirrored=mirrored,
                horizontal_chamfer=12.0,
                rotation_degrees=rotation_degrees,
            )
            corner.setProperty("controlBackground", "#ffffff")
            grid.addWidget(corner, row, column, Qt.AlignmentFlag.AlignCenter)

        for row, column, rotation_degrees, position in (
            (1, 1, -45, "noroeste"),
            (1, 2, 0, "superior"),
            (1, 3, 45, "nordeste"),
            (2, 1, -90, "esquerdo"),
            (2, 3, 90, "direito"),
            (3, 1, -135, "sudoeste"),
            (3, 2, 180, "inferior"),
            (3, 3, 135, "sudeste"),
        ):
            button = self._square_control(controls)
            button.setIcon(self._positioning_icon(rotation_degrees))
            button.setIconSize(QSize(18, 18))
            button.setAccessibleName(f"Controle {position} de posicionamento")
            grid.addWidget(button, row, column, Qt.AlignmentFlag.AlignCenter)

        center = QToolButton(controls)
        center.setFixedSize(34, 34)
        center.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "dot.svg")))
        center.setIconSize(QSize(18, 18))
        center.setAccessibleName("Ponto central de posicionamento")
        center.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 17px; padding: 0; "
            "background: #ffffff; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        grid.addWidget(center, 2, 2, Qt.AlignmentFlag.AlignCenter)

        controls.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.addStretch()
        controls_row.addWidget(controls)
        controls_row.addStretch()
        layout.addStretch()
        layout.addLayout(controls_row)
        layout.addSpacing(10)

        values = QWidget()
        values_grid = QGridLayout(values)
        values_grid.setContentsMargins(0, 0, 0, 0)
        values_grid.setHorizontalSpacing(8)
        values_grid.setVerticalSpacing(5)
        values_grid.setColumnStretch(0, 1)
        values_grid.setColumnStretch(1, 1)
        self._solid_offset_inputs: dict[str, QLineEdit] = {}

        position_title = QLabel("Posição")
        position_title.setObjectName("propertySection")
        values_grid.addWidget(position_title, 0, 0)
        rotation_title = QLabel("Rotação")
        rotation_title.setObjectName("propertySection")
        values_grid.addWidget(rotation_title, 0, 1)

        self.position_input = QLineEdit()
        self.position_input.setReadOnly(True)
        self.position_input.setObjectName("identityDisplay")
        self.position_input.setAccessibleName("Estado do posicionamento")
        values_grid.addWidget(self.position_input, 1, 0)

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
        self.rotation_input = QLineEdit()
        self.rotation_input.setObjectName("unitValue")
        self.rotation_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[+-]?\d*"), self.rotation_input)
        )
        self.rotation_input.setAccessibleName("Rotação do membro (graus)")
        self.rotation_input.editingFinished.connect(self._rotation_changed)
        rotation_row.addWidget(self.rotation_input, 1)
        rotation_row.addWidget(QLabel("°"))
        values_grid.addWidget(rotation_box, 1, 1)

        for column, endpoint in enumerate(("A", "B")):
            endpoint_title = QLabel(endpoint)
            endpoint_title.setObjectName("propertySection")
            values_grid.addWidget(endpoint_title, 2, column)
            field_box, field = self._offset_input(values)
            field.setToolTip(
                "Positivo aumenta e negativo reduz o comprimento da extremidade"
            )
            field.setAccessibleName(
                f"Deslocamento da face sólida no extremo {endpoint} (mm)"
            )
            field.editingFinished.connect(
                lambda selected_endpoint=endpoint: self._solid_offset_changed(selected_endpoint)
            )
            self._solid_offset_inputs[endpoint] = field
            values_grid.addWidget(field_box, 3, column)

        layout.addWidget(values)
        layout.addStretch()
        self._member_name = ""
        self.hide()

    @staticmethod
    def _square_control(parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        button.setFixedSize(34, 34)
        button.setAccessibleName("Controle de posicionamento")
        button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 7px; padding: 0; "
            "background: #ffffff; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        return button

    @staticmethod
    def _offset_input(parent: QWidget) -> tuple[QFrame, QLineEdit]:
        box = QFrame(parent)
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
        field = QLineEdit()
        field.setObjectName("unitValue")
        field.setMinimumWidth(0)
        field.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"[+-]?\d*(?:[.,]\d{0,2})?"), field
            )
        )
        row.addWidget(field, 1)
        row.addWidget(QLabel("mm"))
        return box, field

    @staticmethod
    def _positioning_icon(rotation_degrees: int) -> QIcon:
        """Return the directional icon rotated toward the central control."""
        return DisplacementPanel._rotated_icon("arrow-down-from-line.svg", rotation_degrees)

    @staticmethod
    def _rotated_icon(icon_name: str, rotation_degrees: int) -> QIcon:
        """Render an SVG icon with its directional rotation preserved."""
        icon = QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_name))
        if rotation_degrees == 0:
            return icon
        source_size = QSize(48, 48)
        source = icon.pixmap(source_size)
        rotated = source.transformed(
            QTransform().rotate(rotation_degrees),
            Qt.TransformationMode.SmoothTransformation,
        )
        if rotated.size() != source_size:
            offset_x = (rotated.width() - source.width()) // 2
            offset_y = (rotated.height() - source.height()) // 2
            rotated = rotated.copy(offset_x, offset_y, source.width(), source.height())
        return QIcon(rotated)

    def reposition(self) -> None:
        properties = self.window.properties
        self.move(
            properties.x() - self.width() - 12,
            properties.y() + (properties.height() - self.height()) // 2,
        )
        self.raise_()

    def configure_for(self, member_name: str) -> None:
        """Load the selected member's positioning values before displaying the panel."""
        self._member_name = member_name
        member = self.window.model.bars.get(member_name)
        self.rotation_input.setEnabled(member is not None)
        self.position_input.setEnabled(member is not None)
        self.rotation_input.setText(str(member.rotation) if member is not None else "")
        if member is None:
            self.position_input.clear()
            for field in self._solid_offset_inputs.values():
                field.clear()
                field.setEnabled(False)
        else:
            for field in self._solid_offset_inputs.values():
                field.setEnabled(True)
            self._update_position_input(member)
            self._update_solid_offset_inputs()
        self.layout().activate()
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())

    def _rotation_changed(self) -> None:
        if not self._member_name:
            return
        member = self.window.model.bars.get(self._member_name)
        if member is None:
            return
        value = self.rotation_input.text().strip()
        if not value:
            self.rotation_input.setText(str(member.rotation))
            return
        try:
            member = self.window.model_service.update_member_rotation(self._member_name, int(value))
        except ValueError:
            self.rotation_input.setText(str(member.rotation))
            return
        self.rotation_input.setText(str(member.rotation))
        self.window.refresh_member_rotation(self._member_name)

    @staticmethod
    def _format_solid_offset(value: float) -> str:
        if abs(value) < 0.000005:
            value = 0.0
        formatted = f"{value * 1000.0:.2f}".rstrip("0").rstrip(".")
        return formatted or "0"

    def _solid_offset_changed(self, endpoint: str) -> None:
        member = self.window.model.bars.get(self._member_name)
        field = self._solid_offset_inputs.get(endpoint)
        if member is None or field is None or endpoint not in {"A", "B"}:
            return
        try:
            value_mm = float(field.text().strip().replace(",", "."))
            if not isfinite(value_mm):
                raise ValueError
        except ValueError:
            self._update_solid_offset_inputs()
            return
        offsets = list(getattr(member, "solid_face_offsets", (0.0, 0.0)))
        offsets[0 if endpoint == "A" else 1] = value_mm / 1000.0
        try:
            member = self.window.model_service.update_member_solid_face_offsets(
                self._member_name, tuple(offsets)
            )
        except ValueError:
            self._update_solid_offset_inputs()
            return
        field.setText(
            self._format_solid_offset(member.solid_face_offsets[0 if endpoint == "A" else 1])
        )
        self._update_position_input(member)
        self.window.properties.update_positioning_status(self._member_name)
        self.window.refresh_member_geometry(self._member_name)

    def _update_solid_offset_inputs(self) -> None:
        member = self.window.model.bars.get(self._member_name)
        if member is None:
            return
        offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
        if len(offsets) != 2:
            return
        for index, endpoint in enumerate(("A", "B")):
            field = self._solid_offset_inputs[endpoint]
            field.setText(self._format_solid_offset(offsets[index]))

    def _update_position_input(self, member) -> None:
        offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
        self.position_input.setText(
            "Definido" if any(float(value) != 0.0 for value in offsets) else "Indefinido"
        )
