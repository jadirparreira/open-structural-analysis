"""Painel flutuante reservado à configuração de deslocamentos da barra."""

from math import isfinite

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QDoubleValidator, QRegularExpressionValidator, QTransform
from PySide6.QtWidgets import QScrollArea

from osa.sections import section_shape

from .common import *
from .group_positioning import group_endpoint_faces
from .navigation_buttons import SlopedPlaneButton


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

        self.title = QLabel("Posicionamento da barra")
        self.title.setObjectName("propertyTitle")
        layout.addWidget(self.title)
        layout.addSpacing(6)

        controls = QWidget()
        self._controls_widget = controls
        grid = QGridLayout(controls)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

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

        self._position_buttons: dict[str, QToolButton] = {}
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
            button.setCheckable(True)
            button.setIcon(self._positioning_icon(rotation_degrees))
            button.setIconSize(QSize(18, 18))
            button.setAccessibleName(f"Controle {position} de posicionamento")
            button.clicked.connect(
                lambda _checked=False, selected_position=position:
                self._position_requested(selected_position)
            )
            self._position_buttons[position] = button
            if position == "superior":
                self.top_center_button = button
            grid.addWidget(button, row, column, Qt.AlignmentFlag.AlignCenter)

        center = QToolButton(controls)
        center.setFixedSize(34, 34)
        center.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "dot.svg")))
        center.setIconSize(QSize(18, 18))
        center.setAccessibleName("Ponto central de posicionamento")
        center.setCheckable(True)
        center.clicked.connect(self._center_requested)
        self.center_button = center
        center.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 17px; padding: 0; "
            "background: #ffffff; }"
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
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
        values_layout = QVBoxLayout(values)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(5)
        self._solid_offset_inputs: dict[str, QLineEdit] = {}
        self._position_parameter_inputs: dict[str, QLineEdit] = {}
        self._position_parameter_titles: dict[str, QLabel] = {}
        self._end_angle_inputs: dict[tuple[str, str], QLineEdit] = {}

        endpoint_grid = QGridLayout()
        endpoint_grid.setContentsMargins(0, 0, 0, 0)
        endpoint_grid.setHorizontalSpacing(8)
        endpoint_grid.setVerticalSpacing(5)
        for column in range(2):
            endpoint_grid.setColumnStretch(column, 1)
        for column, endpoint in enumerate(("A", "B")):
            title = QLabel(endpoint)
            title.setObjectName("propertySection")
            endpoint_grid.addWidget(title, 0, column)
            field_box, field = self._offset_input(values)
            field.setAccessibleName(
                f"Deslocamento da face sólida no extremo {endpoint} (mm)"
            )
            field.setToolTip(
                f"Ajusta o deslocamento longitudinal da face sólida no extremo {endpoint}, em milímetros."
            )
            field.editingFinished.connect(
                lambda selected_endpoint=endpoint:
                self._solid_offset_changed(selected_endpoint)
            )
            self._solid_offset_inputs[endpoint] = field
            endpoint_grid.addWidget(field_box, 1, column)

        for row, local_axis in enumerate(("Y", "Z"), start=2):
            for column, endpoint in enumerate(("A", "B")):
                title = QLabel(f"{endpoint}-α{local_axis}")
                title.setObjectName("propertySection")
                endpoint_grid.addWidget(title, (row - 1) * 2, column)
                field_box, field = self._offset_input(values, unit="°")
                field.setAccessibleName(
                    f"Inclinação da face no extremo {endpoint}, direção do eixo local {local_axis} (graus)"
                )
                field.setToolTip(
                    f"Define a inclinação da face no extremo {endpoint} na direção do eixo local {local_axis}, em graus."
                )
                limit = float(self.window.solid_face_angle_limit_degrees)
                validator = QDoubleValidator(-limit, limit, 2, field)
                validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                field.setValidator(validator)
                field.setText("0")
                self._end_angle_inputs[(endpoint, local_axis)] = field
                field.editingFinished.connect(
                    lambda selected_endpoint=endpoint, selected_axis=local_axis:
                    self._end_angle_changed(selected_endpoint, selected_axis)
                )
                endpoint_grid.addWidget(field_box, (row - 1) * 2 + 1, column)
        self._endpoint_widget = QWidget(values)
        self._endpoint_widget.setLayout(endpoint_grid)
        parameter_grid = QGridLayout()
        self._parameter_widget = QWidget(values)
        self._parameter_widget.setLayout(parameter_grid)
        parameter_grid.setContentsMargins(0, 0, 0, 0)
        parameter_grid.setHorizontalSpacing(8)
        parameter_grid.setVerticalSpacing(5)
        parameter_grid.setColumnStretch(0, 1)
        parameter_grid.setColumnStretch(1, 1)
        for column, parameter in enumerate(("Y", "Z")):
            parameter_title = QLabel(f"{parameter} local")
            parameter_title.setObjectName("propertySection")
            parameter_grid.addWidget(parameter_title, 0, column)
            self._position_parameter_titles[parameter] = parameter_title
            field_box, field = self._offset_input(values)
            field.setAccessibleName(f"Parâmetro {parameter} local de posicionamento (mm)")
            field.setToolTip(
                f"Desloca a seção sólida ao longo do eixo local {parameter}, em milímetros."
            )
            field.editingFinished.connect(
                lambda selected_parameter=parameter:
                self._section_offset_changed(selected_parameter)
            )
            self._position_parameter_inputs[parameter] = field
            parameter_grid.addWidget(field_box, 1, column)
        values_layout.addWidget(self._parameter_widget)
        values_layout.addWidget(self._endpoint_widget)
        plate_displacement = QWidget(values)
        plate_layout = QVBoxLayout(plate_displacement)
        plate_layout.setContentsMargins(0, 0, 0, 0)
        plate_layout.setSpacing(5)
        self._plate_alignment_buttons: dict[str, QToolButton] = {}
        alignment_controls = QWidget(plate_displacement)
        alignment_layout = QVBoxLayout(alignment_controls)
        alignment_layout.setContentsMargins(0, 0, 0, 0)
        alignment_layout.setSpacing(8)
        alignment_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        for alignment, icon, accessible_name in (
            ("upper", self._positioning_icon(0), "Alinhar a face superior da placa ao plano"),
            ("center", QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "dot.svg")), "Centralizar a placa no plano"),
            ("lower", self._positioning_icon(180), "Alinhar a face inferior da placa ao plano"),
        ):
            if alignment == "center":
                button = QToolButton(alignment_controls)
                button.setFixedSize(34, 34)
                button.setStyleSheet(
                    "QToolButton { border: 1px solid #d0d7de; border-radius: 17px; padding: 0; "
                    "background: #ffffff; }"
                    "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
                    "QToolButton:pressed { background: #d0d7de; }"
                )
            else:
                button = self._square_control(alignment_controls)
            button.setCheckable(True)
            button.setIcon(icon)
            button.setIconSize(QSize(18, 18))
            button.setAccessibleName(accessible_name)
            button.clicked.connect(
                lambda _checked=False, selected=alignment:
                self._plate_alignment_requested(selected)
            )
            self._plate_alignment_buttons[alignment] = button
            alignment_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        plate_layout.addWidget(alignment_controls)
        plate_label = QLabel("X local")
        plate_label.setObjectName("propertySection")
        plate_layout.addWidget(plate_label)
        plate_box, plate_field = self._offset_input(values)
        plate_field.setAccessibleName("X local perpendicular ao plano da placa (mm)")
        plate_field.setToolTip(
            "Valor positivo desloca a placa no sentido da normal global do plano; "
            "valor negativo desloca no sentido oposto."
        )
        plate_field.editingFinished.connect(self._plate_displacement_changed)
        plate_layout.addWidget(plate_box)
        self._plate_edge_scroll = QScrollArea(plate_displacement)
        self._plate_edge_scroll.setObjectName("plateEdgeScroll")
        self._plate_edge_scroll.setWidgetResizable(True)
        self._plate_edge_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._plate_edge_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._plate_edge_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._plate_edge_scroll.setMaximumHeight(16777215)
        self._plate_edge_scroll.setStyleSheet(
            "QScrollArea#plateEdgeScroll { background: transparent; border: 0; }"
            "QScrollArea#plateEdgeScroll QWidget#qt_scrollarea_viewport { background: transparent; }"
            "QWidget#plateEdgeContent { background: transparent; }"
        )
        self._plate_edge_scroll.viewport().setAutoFillBackground(False)
        self._plate_edge_content = QWidget(self._plate_edge_scroll)
        self._plate_edge_content.setObjectName("plateEdgeContent")
        self._plate_edge_content.setAutoFillBackground(False)
        self._plate_edge_grid = QGridLayout(self._plate_edge_content)
        self._plate_edge_grid.setContentsMargins(0, 0, 0, 0)
        self._plate_edge_grid.setHorizontalSpacing(6)
        self._plate_edge_grid.setVerticalSpacing(5)
        for column in range(2):
            self._plate_edge_grid.setColumnStretch(column, 1)
        self._plate_edge_scroll.setWidget(self._plate_edge_content)
        plate_layout.addWidget(self._plate_edge_scroll)
        self._plate_edge_inputs: dict[tuple[str, str], QLineEdit] = {}
        self._plate_edge_widgets: list[QWidget] = []
        self._plate_displacement_container = plate_displacement
        self._plate_displacement_input = plate_field
        values_layout.addWidget(plate_displacement)
        plate_displacement.hide()

        layout.addWidget(values)
        layout.addStretch()
        self._member_name = ""
        self._member_names: tuple[str, ...] = ()
        self._plate_name = ""
        self._group_endpoint_faces: dict[str, tuple[str, int]] = {}
        self._is_group_positioning = False
        layout.activate()
        self.hide()

    @staticmethod
    def _square_control(parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        button.setFixedSize(34, 34)
        button.setAccessibleName("Controle de posicionamento")
        button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 7px; padding: 0; "
            "background: #ffffff; }"
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        return button

    @staticmethod
    def _offset_input(parent: QWidget, *, unit: str = "mm") -> tuple[QFrame, QLineEdit]:
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
        row.addWidget(QLabel(unit))
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

    def _resize_to_visible_contents(self, *, minimum_height: int) -> None:
        """Recompute the panel height from the currently visible controls."""
        self.setMinimumHeight(minimum_height)
        values_layout = self._plate_displacement_container.parentWidget().layout()
        layouts = (
            self._plate_edge_grid,
            self._plate_displacement_container.layout(),
            values_layout,
            self.layout(),
        )
        for layout in layouts:
            layout.invalidate()
            layout.activate()
        self._plate_displacement_container.parentWidget().updateGeometry()
        self._plate_displacement_container.updateGeometry()
        self.updateGeometry()
        self.adjustSize()
        self.resize(self.width(), max(minimum_height, self.sizeHint().height()))

    def configure_for(self, member_name: str) -> None:
        """Load the selected member's positioning values before displaying the panel."""
        self._plate_name = ""
        self._plate_displacement_container.hide()
        self._controls_widget.show()
        self._parameter_widget.show()
        self._endpoint_widget.show()
        self._member_name = member_name
        selected = self.window.properties._selected_names("bar")
        self._member_names = tuple(
            name for name in selected if name in self.window.model.bars
        ) if member_name in selected else ((member_name,) if member_name in self.window.model.bars else ())
        group = self.window.model.verification_group_for(member_name)
        if group is not None and set(self._member_names) == set(group["members"]):
            self._group_endpoint_faces = group_endpoint_faces(
                self.window.model, tuple(group["members"]),
            )
        else:
            self._group_endpoint_faces = {}
        self._is_group_positioning = bool(self._group_endpoint_faces and len(self._member_names) > 1)
        self.title.setText(
            "Posicionamento do grupo" if self._is_group_positioning
            else "Posicionamento da barra"
        )
        for parameter, label in self._position_parameter_titles.items():
            group_axis = {"Y": "X", "Z": "Y"}[parameter]
            label.setText(f"{group_axis if self._is_group_positioning else parameter} local")
            self._position_parameter_inputs[parameter].setAccessibleName(
                f"Parâmetro {group_axis if self._is_group_positioning else parameter} local do grupo (mm)"
                if self._is_group_positioning else f"Parâmetro {parameter} local de posicionamento (mm)"
            )
        members = self._members()
        member = members[0] if members else None
        self.center_button.setEnabled(member is not None)
        if member is None:
            for field in self._solid_offset_inputs.values():
                field.clear()
                field.setEnabled(False)
            for field in self._position_parameter_inputs.values():
                field.clear()
                field.setEnabled(False)
            for field in self._end_angle_inputs.values():
                field.clear()
                field.setEnabled(False)
        else:
            for field in self._solid_offset_inputs.values():
                field.setEnabled(True)
            for field in self._position_parameter_inputs.values():
                field.setEnabled(True)
            for field in self._end_angle_inputs.values():
                field.setEnabled(True)
            self._update_section_offset_inputs()
            self._update_end_angle_inputs()
            self._update_position_buttons()
            self._update_solid_offset_inputs()
        self._resize_to_visible_contents(minimum_height=250)

    def configure_for_plate(self, plate_name: str) -> None:
        """Load the selected plate's normal and per-edge detailing controls."""
        self._plate_name = plate_name if plate_name in self.window.model.plates else ""
        self._member_name = ""
        self._member_names = ()
        self._group_endpoint_faces = {}
        self._is_group_positioning = False
        plate_mode = bool(self._plate_name)
        self.setMinimumHeight(0)
        self.title.setText("Posicionamento da placa")
        self._controls_widget.setVisible(not plate_mode)
        self._parameter_widget.setVisible(not plate_mode)
        self._endpoint_widget.setVisible(not plate_mode)
        self._plate_displacement_container.setVisible(plate_mode)
        self._plate_displacement_input.setEnabled(plate_mode)
        if plate_mode:
            plate = self.window.model.plates[self._plate_name]
            self._plate_displacement_input.setText(
                self._format_solid_offset(plate.positioning_displacement)
            )
            self._update_plate_alignment_buttons()
            self._configure_plate_edge_inputs(plate)
        else:
            self._plate_displacement_input.clear()
            self._clear_plate_edge_inputs()
        self._resize_to_visible_contents(minimum_height=0 if plate_mode else 250)

    def _clear_plate_edge_inputs(self) -> None:
        self._plate_edge_inputs.clear()
        for widget in self._plate_edge_widgets:
            widget.setParent(None)
            widget.deleteLater()
        self._plate_edge_widgets.clear()

    def _configure_plate_edge_inputs(self, plate) -> None:
        self._clear_plate_edge_inputs()
        self._plate_edge_content.setMinimumHeight(0)
        saved = {name: (offset, angle) for name, offset, angle in plate.edge_positioning}
        for edge_index, (_kind, edge_name) in enumerate(plate.supports):
            offset, angle = saved.get(edge_name, (0.0, 0.0))
            label_row = edge_index * 2
            field_row = label_row + 1
            for column, role, suffix, unit, value, description in (
                (0, "YZ", "YZ", "mm", offset,
                 f"Deslocamento da aresta {edge_name}: positivo aumenta e negativo reduz a placa"),
                (1, "alpha", "α", "°", angle,
                 f"Inclinação da face lateral da aresta {edge_name}: 0° é perpendicular ao plano; "
                 "ângulo positivo inclina o topo para dentro da placa"),
            ):
                label = QLabel(f"{edge_name}-{suffix}")
                label.setObjectName("propertySection")
                label.setToolTip(description)
                self._plate_edge_grid.addWidget(label, label_row, column)
                box, field = self._offset_input(self._plate_displacement_container, unit=unit)
                if role == "alpha":
                    limit = float(self.window.solid_face_angle_limit_degrees)
                    validator = QDoubleValidator(-limit, limit, 2, field)
                    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                    field.setValidator(validator)
                field.setText(self._format_plate_edge_value(value))
                field.setAccessibleName(
                    f"{edge_name}-{suffix}: {description} ({'mm' if unit == 'mm' else 'graus'})"
                )
                field.setToolTip(description + (", em milímetros." if unit == "mm" else ", em graus."))
                field.editingFinished.connect(
                    lambda selected_edge=edge_name:
                    self._plate_edge_positioning_changed(selected_edge)
                )
                self._plate_edge_grid.addWidget(box, field_row, column)
                self._plate_edge_inputs[(edge_name, role)] = field
                self._plate_edge_widgets.extend((label, box))
        edge_count = len(plate.supports)
        self._plate_edge_scroll.setVisible(edge_count > 0)
        self._plate_edge_grid.activate()
        visible_rows = min(edge_count, 4) * 2
        visible_height = 0
        for row in range(visible_rows):
            item_heights = [
                self._plate_edge_grid.itemAtPosition(row, column).sizeHint().height()
                for column in range(2)
                if self._plate_edge_grid.itemAtPosition(row, column) is not None
            ]
            # QSS minimum heights are applied during widget polish; keep enough
            # room for the labels and unit boxes even before the first show.
            row_floor = 22 if row % 2 == 0 else 34
            visible_height += max([row_floor, *item_heights])
        if visible_rows > 1:
            visible_height += self._plate_edge_grid.verticalSpacing() * (visible_rows - 1)
        margins = self._plate_edge_grid.contentsMargins()
        visible_height += margins.top() + margins.bottom()
        if edge_count > 0:
            visible_height += 2
        content_rows = edge_count * 2
        content_height = 0
        for row in range(content_rows):
            item_heights = [
                self._plate_edge_grid.itemAtPosition(row, column).sizeHint().height()
                for column in range(2)
                if self._plate_edge_grid.itemAtPosition(row, column) is not None
            ]
            row_floor = 22 if row % 2 == 0 else 34
            content_height += max([row_floor, *item_heights])
        if content_rows > 1:
            content_height += self._plate_edge_grid.verticalSpacing() * (content_rows - 1)
        content_height += margins.top() + margins.bottom()
        content_height = max(visible_height, content_height)
        self._plate_edge_content.setMinimumHeight(content_height)
        self._plate_edge_content.updateGeometry()
        self._plate_edge_scroll.updateGeometry()
        if edge_count > 0:
            self._plate_edge_scroll.setMinimumHeight(visible_height)
        else:
            self._plate_edge_scroll.setMinimumHeight(0)
        self._plate_edge_scroll.setMaximumHeight(max(0, visible_height))
        self._plate_edge_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if edge_count > 4
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def _plate_edge_positioning_changed(self, edge_name: str) -> None:
        plate_name = self._plate_name
        if not plate_name or plate_name not in self.window.model.plates:
            return
        plate = self.window.model.plates[plate_name]
        values = {name: (offset, angle) for name, offset, angle in plate.edge_positioning}
        try:
            offset = float(self._plate_edge_inputs[(edge_name, "YZ")].text().strip().replace(",", "."))
            angle = float(self._plate_edge_inputs[(edge_name, "alpha")].text().strip().replace(",", "."))
            if not isfinite(offset) or not isfinite(angle):
                raise ValueError
        except (KeyError, ValueError):
            self._configure_plate_edge_inputs(plate)
            return
        values[edge_name] = (offset, angle)
        ordered = tuple(
            (name, *values.get(name, (0.0, 0.0)))
            for _kind, name in plate.supports
        )
        try:
            self.window.model_service.update_plate_edge_positioning(
                plate_name, ordered,
            )
        except ValueError:
            self._configure_plate_edge_inputs(plate)
            return
        self.window.scene.update_plate_rendering(plate_name)

    @staticmethod
    def _format_plate_edge_value(value: float) -> str:
        formatted = f"{float(value):.2f}".rstrip("0").rstrip(".")
        return formatted or "0"

    def _plate_displacement_changed(self) -> None:
        name = self._plate_name
        field = self._plate_displacement_input
        if not name or name not in self.window.model.plates:
            return
        try:
            value_mm = float(field.text().strip().replace(",", "."))
            if not isfinite(value_mm):
                raise ValueError
        except ValueError:
            self.configure_for_plate(name)
            return
        try:
            self.window.model_service.update_plate_positioning_displacement(
                name, value_mm / 1000.0,
            )
        except ValueError:
            self.configure_for_plate(name)
            return
        self.window.scene.update_plate_rendering(name)
        self.window.properties.update_positioning_status(name)
        self._update_plate_alignment_buttons()

    def _plate_alignment_requested(self, alignment: str) -> None:
        """Align a plate face with its analytical plane or center it on the plane."""
        name = self._plate_name
        if not name or name not in self.window.model.plates:
            return
        plate = self.window.model.plates[name]
        half_thickness_mm = plate.thickness_mm / 2.0
        displacement_mm = {
            "upper": -half_thickness_mm,
            "center": 0.0,
            "lower": half_thickness_mm,
        }.get(alignment)
        if displacement_mm is None:
            return
        self._plate_displacement_input.setText(self._format_solid_offset(displacement_mm / 1000.0))
        self._plate_displacement_changed()

    def _update_plate_alignment_buttons(self) -> None:
        name = self._plate_name
        if not name or name not in self.window.model.plates:
            for button in self._plate_alignment_buttons.values():
                button.setChecked(False)
            return
        plate = self.window.model.plates[name]
        displacement_mm = plate.positioning_displacement * 1000.0
        targets_mm = {
            "upper": -plate.thickness_mm / 2.0,
            "center": 0.0,
            "lower": plate.thickness_mm / 2.0,
        }
        for alignment, button in self._plate_alignment_buttons.items():
            button.setChecked(abs(displacement_mm - targets_mm[alignment]) <= 1e-6)

    def _members(self) -> list:
        return [self.window.model.bars[name] for name in self._member_names
                if name in self.window.model.bars]

    def _refresh_positioning_status(self) -> None:
        self.window.properties.update_positioning_status(self._member_name)

    def _center_requested(self, _checked: bool) -> None:
        """Select the member's original geometric-center position."""
        members = self._members()
        if not members:
            return
        try:
            for member in members:
                self.window.model_service.update_member_solid_section_offsets(
                    member.name, (0.0, 0.0)
                )
        except ValueError:
            return
        self._update_section_offset_inputs()
        self._update_position_buttons()
        for member in members:
            self.window.refresh_member_positioning(member.name)
        self._refresh_positioning_status()

    def _position_requested(self, position: str) -> None:
        """Align the requested solid-section face or corner with the line."""
        members = self._members()
        if not members:
            return
        offsets = [self._position_offsets(member, position) for member in members]
        if any(value is None for value in offsets):
            return
        try:
            for member, value in zip(members, offsets):
                self.window.model_service.update_member_solid_section_offsets(member.name, value)
        except ValueError:
            return
        self._update_section_offset_inputs()
        self._update_position_buttons()
        for member in members:
            self.window.refresh_member_positioning(member.name)
        self._refresh_positioning_status()

    def _section_offset_changed(self, parameter: str) -> None:
        """Apply a direct local section offset entered in millimetres."""
        members = self._members()
        field = self._position_parameter_inputs.get(parameter)
        if not members or field is None or parameter not in {"Y", "Z"}:
            return
        try:
            value_mm = float(field.text().strip().replace(",", "."))
            if not isfinite(value_mm):
                raise ValueError
        except ValueError:
            self._update_section_offset_inputs()
            return
        try:
            for member in members:
                offsets = list(getattr(member, "solid_section_offsets", (0.0, 0.0)))
                if len(offsets) != 2:
                    offsets = [0.0, 0.0]
                offsets[0 if parameter == "Y" else 1] = value_mm / 1000.0
                self.window.model_service.update_member_solid_section_offsets(
                    member.name, tuple(offsets)
                )
        except ValueError:
            self._update_section_offset_inputs()
            return
        self._update_section_offset_inputs()
        self._update_position_buttons()
        for member in members:
            self.window.refresh_member_positioning(member.name)
        self._refresh_positioning_status()

    @staticmethod
    def _format_solid_offset(value: float) -> str:
        if abs(value) < 0.000005:
            value = 0.0
        formatted = f"{value * 1000.0:.2f}".rstrip("0").rstrip(".")
        return formatted or "0"

    def _solid_offset_changed(self, endpoint: str) -> None:
        members = self._members()
        field = self._solid_offset_inputs.get(endpoint)
        if not members or field is None or endpoint not in {"A", "B"}:
            return
        try:
            value_mm = float(field.text().strip().replace(",", "."))
            if not isfinite(value_mm):
                raise ValueError
        except ValueError:
            self._update_solid_offset_inputs()
            return
        endpoint_target = self._group_endpoint_faces.get(endpoint)
        targets = (
            [(self.window.model.bars[endpoint_target[0]], endpoint_target[1])]
            if endpoint_target is not None
            else [(member, 0 if endpoint == "A" else 1) for member in members]
        )
        try:
            for member, endpoint_index in targets:
                offsets = list(getattr(member, "solid_face_offsets", (0.0, 0.0)))
                offsets[endpoint_index] = value_mm / 1000.0
                self.window.model_service.update_member_solid_face_offsets(
                    member.name, tuple(offsets)
                )
        except ValueError:
            self._update_solid_offset_inputs()
            return
        self._update_solid_offset_inputs()
        self._update_position_buttons()
        self._refresh_positioning_status()
        for member, _endpoint_index in targets:
            self.window.refresh_member_positioning(member.name)

    @staticmethod
    def _format_angle(value: float) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"

    def _update_end_angle_inputs(self) -> None:
        members = self._members()
        if not members:
            return
        limit = float(self.window.solid_face_angle_limit_degrees)
        for member in members:
            current = member.solid_face_angles
            if len(current) != 4:
                current = (0.0, 0.0, 0.0, 0.0)
            limited = tuple(min(limit, max(-limit, float(value))) for value in current)
            if limited != tuple(current):
                self.window.model_service.update_member_solid_face_angles(
                    member.name, limited
                )
                self.window.refresh_member_positioning(member.name)
        members = self._members()
        fields = (
            ("A", "Y", 0),
            ("A", "Z", 1),
            ("B", "Y", 2),
            ("B", "Z", 3),
        )
        for endpoint, local_axis, index in fields:
            endpoint_target = self._group_endpoint_faces.get(endpoint)
            if endpoint_target is not None:
                member = self.window.model.bars[endpoint_target[0]]
                angle_index = endpoint_target[1] * 2 + (0 if local_axis == "Y" else 1)
                angles = member.solid_face_angles if len(member.solid_face_angles) == 4 else (0.0,) * 4
                values = [angles[angle_index]]
            else:
                values = [
                    (item.solid_face_angles if len(item.solid_face_angles) == 4 else (0.0,) * 4)[index]
                    for item in members
                ]
            field = self._end_angle_inputs[(endpoint, local_axis)]
            field.setPlaceholderText("Variado" if len(set(values)) > 1 else "")
            field.setText(self._format_angle(float(values[0])) if len(set(values)) == 1 else "")

    def _end_angle_changed(self, endpoint: str, local_axis: str) -> None:
        field = self._end_angle_inputs.get((endpoint, local_axis))
        members = self._members()
        if field is None or not members:
            return
        text = field.text().strip()
        if not text:
            self._update_end_angle_inputs()
            return
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            self._update_end_angle_inputs()
            return
        limit = float(self.window.solid_face_angle_limit_degrees)
        value = min(limit, max(-limit, value))
        field.setText(self._format_angle(value))
        endpoint_target = self._group_endpoint_faces.get(endpoint)
        targets = (
            [(self.window.model.bars[endpoint_target[0]], endpoint_target[1])]
            if endpoint_target is not None
            else [(member, 0 if endpoint == "A" else 1) for member in members]
        )
        for member, endpoint_index in targets:
            angles = list(member.solid_face_angles)
            if len(angles) != 4:
                angles = [0.0] * 4
            angle_index = endpoint_index * 2 + (0 if local_axis == "Y" else 1)
            angles[angle_index] = value
            self.window.model_service.update_member_solid_face_angles(
                member.name, tuple(angles)
            )
            self.window.refresh_member_positioning(member.name)
        self._update_end_angle_inputs()
        self._refresh_positioning_status()

    def set_solid_face_angle_limit(self, limit: float) -> None:
        limit = min(89.9, max(0.0, float(limit)))
        for field in self._end_angle_inputs.values():
            validator = field.validator()
            if isinstance(validator, QDoubleValidator):
                validator.setRange(-limit, limit, 2)
            text = field.text().strip()
            if not text:
                continue
            try:
                value = float(text.replace(",", "."))
            except ValueError:
                continue
            field.setText(self._format_angle(min(limit, max(-limit, value))))

    def _update_solid_offset_inputs(self) -> None:
        members = self._members()
        if not members:
            return
        for index, endpoint in enumerate(("A", "B")):
            endpoint_target = self._group_endpoint_faces.get(endpoint)
            if endpoint_target is not None:
                member = self.window.model.bars[endpoint_target[0]]
                offsets = member.solid_face_offsets if len(member.solid_face_offsets) == 2 else (0.0, 0.0)
                values = [offsets[endpoint_target[1]]]
            else:
                values = [
                    (member.solid_face_offsets if len(member.solid_face_offsets) == 2 else (0.0, 0.0))[index]
                    for member in members
                ]
            field = self._solid_offset_inputs[endpoint]
            field.setPlaceholderText("Variado" if len(set(values)) > 1 else "")
            field.setText(self._format_solid_offset(values[0]) if len(set(values)) == 1 else "")

    def _update_position_buttons(self) -> None:
        members = self._members()
        bounds = [self._section_bounds(item) for item in members]
        centered = bool(members) and all(
            len(item.solid_section_offsets) == 2
            and all(abs(float(value)) <= 1e-12 for value in item.solid_section_offsets)
            for item in members
        )
        with QSignalBlocker(self.center_button):
            self.center_button.setChecked(centered)
        for position, button in self._position_buttons.items():
            positions = [
                self._position_offsets_from_bounds(value, position) if value is not None else None
                for value in bounds
            ]
            available = bool(positions) and all(offsets is not None for offsets in positions)
            active = available and all(
                all(abs(float(current) - float(expected)) <= 1e-12
                    for current, expected in zip(item.solid_section_offsets, offsets))
                for item, offsets in zip(members, positions)
            )
            button.setEnabled(available)
            with QSignalBlocker(button):
                button.setChecked(active)

    @staticmethod
    def _section_bounds(member) -> tuple[float, float, float, float] | None:
        try:
            shape = section_shape(
                member.section, member.geometry_dict(),
                mirror_z=member.section_mirrored,
            )
        except (KeyError, TypeError, ValueError):
            return None
        return shape.bounds if shape is not None else None

    @staticmethod
    def _position_offsets_from_bounds(
        bounds: tuple[float, float, float, float], position: str,
    ) -> tuple[float, float] | None:
        min_y, max_y, min_z, max_z = bounds
        horizontal = {
            "esquerdo": -float(min_y),
            "direito": -float(max_y),
        }
        vertical = {
            "superior": -float(max_z),
            "inferior": -float(min_z),
        }
        if position == "superior":
            return 0.0, vertical[position] * 1e-3
        if position == "inferior":
            return 0.0, vertical[position] * 1e-3
        if position == "esquerdo":
            return horizontal[position] * 1e-3, 0.0
        if position == "direito":
            return horizontal[position] * 1e-3, 0.0
        diagonal = {
            "noroeste": ("esquerdo", "superior"),
            "nordeste": ("direito", "superior"),
            "sudoeste": ("esquerdo", "inferior"),
            "sudeste": ("direito", "inferior"),
        }
        horizontal_position, vertical_position = diagonal.get(position, ("", ""))
        if not horizontal_position:
            return None
        return (
            horizontal[horizontal_position] * 1e-3,
            vertical[vertical_position] * 1e-3,
        )

    @classmethod
    def _position_offsets(cls, member, position: str) -> tuple[float, float] | None:
        bounds = cls._section_bounds(member)
        return cls._position_offsets_from_bounds(bounds, position) if bounds is not None else None

    def _update_section_offset_inputs(self) -> None:
        members = self._members()
        if not members:
            return
        for index, parameter in enumerate(("Y", "Z")):
            values = [
                (item.solid_section_offsets if len(item.solid_section_offsets) == 2 else (0.0, 0.0))[index]
                for item in members
            ]
            field = self._position_parameter_inputs[parameter]
            field.setPlaceholderText("Variado" if len(set(values)) > 1 else "")
            field.setText(self._format_solid_offset(float(values[0])) if len(set(values)) == 1 else "")
