"""Blank project sheet workspace shown in the detailing session."""
from __future__ import annotations

import math
import base64
from .special_dimensions import SPECIAL_DIMENSION_DEFAULTS, make_dimension, dimension_layout, draw_dimension, angular_geometry
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Signal
from PySide6.QtGui import (
    QCursor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPicture,
    QPixmap, QRegion, QTextCharFormat, QTextCursor, QTextDocument, QTextBlockFormat, QTransform,
)
from PySide6.QtSvg import QSvgRenderer

from osa.rendering.member_breaks import member_break_linework

from .common import (
    QCheckBox,
    QColor,
    QComboBox,
    QAbstractSpinBox,
    QFrame,
    QHBoxLayout,
    QIcon,
    QLabel,
    QLineEdit,
    QPushButton,
    QRectF,
    QSize,
    Qt,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from .property_panel import CompactDoubleSpinBox, MixedCheckBox
from .sheet_tables import AccessoriesTableLayout, RevisionTableLayout, SteelPlatesTableLayout, SteelProfilesTableLayout, revision_rows_for
from .window_frame import WindowFrame

PAPER_SIZES_MM = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}
PROJECT_AXIS_DASH_PATTERN = (6.0, 2.0, 1.0, 2.0)


class _SegmentSpatialGrid:
    """Small uniform-grid broad phase for projected sheet linework."""

    def __init__(self, segments, owners=()) -> None:
        normalized = tuple(
            ((float(start[0]), float(start[1])), (float(end[0]), float(end[1])))
            for start, end in segments
        )
        self.segments = normalized
        self.cell_size = 1.0
        self._cells: dict[tuple[int, int], list[int]] = {}
        self._overflow: list[int] = []
        self.owner_points: dict[str, list[tuple[float, float]]] = {}
        self._owner_faces = None
        owner_values = owners if len(owners) == len(normalized) else ()
        if owner_values:
            for (start, end), owner in zip(normalized, owner_values):
                name = str(owner)
                if name:
                    points = self.owner_points.setdefault(name, [])
                    points.extend((start, end))
        if not normalized:
            return
        min_x = min(min(start[0], end[0]) for start, end in normalized)
        max_x = max(max(start[0], end[0]) for start, end in normalized)
        min_y = min(min(start[1], end[1]) for start, end in normalized)
        max_y = max(max(start[1], end[1]) for start, end in normalized)
        span = max(max_x - min_x, max_y - min_y, 1e-6)
        divisions = max(8, min(128, round(math.sqrt(len(normalized)))))
        self.cell_size = span / divisions
        for index, (start, end) in enumerate(normalized):
            x0 = self._cell(min(start[0], end[0]))
            x1 = self._cell(max(start[0], end[0]))
            y0 = self._cell(min(start[1], end[1]))
            y1 = self._cell(max(start[1], end[1]))
            cell_count = (x1 - x0 + 1) * (y1 - y0 + 1)
            if cell_count > 4096:
                self._overflow.append(index)
                continue
            for grid_x in range(x0, x1 + 1):
                for grid_y in range(y0, y1 + 1):
                    self._cells.setdefault((grid_x, grid_y), []).append(index)

    def owner_faces(self):
        """Cache projected member silhouettes for picking inside their faces."""
        if self._owner_faces is not None:
            return self._owner_faces
        faces = {}
        for owner, points in self.owner_points.items():
            points = sorted(set(points))
            if len(points) < 3:
                continue

            def cross(first, second, third):
                return ((second[0] - first[0]) * (third[1] - first[1])
                        - (second[1] - first[1]) * (third[0] - first[0]))

            lower, upper = [], []
            for point in points:
                while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
                    lower.pop()
                lower.append(point)
            for point in reversed(points):
                while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
                    upper.pop()
                upper.append(point)
            hull = lower[:-1] + upper[:-1]
            if len(hull) < 3:
                continue
            path = QPainterPath(QPointF(*hull[0]))
            for point in hull[1:]:
                path.lineTo(QPointF(*point))
            path.closeSubpath()
            faces[owner] = path
        self._owner_faces = faces
        return faces

    def _cell(self, coordinate: float) -> int:
        return math.floor(coordinate / self.cell_size)

    def query(self, x: float, y: float, radius: float) -> tuple[int, ...]:
        radius = max(0.0, float(radius))
        x0, x1 = self._cell(x - radius), self._cell(x + radius)
        y0, y1 = self._cell(y - radius), self._cell(y + radius)
        found = set(self._overflow)
        for grid_x in range(x0, x1 + 1):
            for grid_y in range(y0, y1 + 1):
                found.update(self._cells.get((grid_x, grid_y), ()))
        return tuple(sorted(found))


class _DimensionSnapIndex:
    """Cached point candidates plus a spatial broad phase for intersections."""

    def __init__(
        self, points, segment_grid: _SegmentSpatialGrid, source_segments=(), source_owners=(),
    ) -> None:
        self.points = tuple(dict.fromkeys(points))
        self.segment_grid = segment_grid
        # Keep the source tuples alive while a cache entry refers to their ids.
        self.source_segments = source_segments
        self.source_owners = source_owners
        self.point_cells: dict[tuple[int, int], list[int]] = {}
        for index, (point, _kind) in enumerate(self.points):
            cell = (
                segment_grid._cell(point[0]),
                segment_grid._cell(point[1]),
            )
            self.point_cells.setdefault(cell, []).append(index)

    def nearby_points(self, x: float, y: float, radius: float) -> tuple:
        cell = self.segment_grid._cell
        x0, x1 = cell(x - radius), cell(x + radius)
        y0, y1 = cell(y - radius), cell(y + radius)
        found = set()
        for grid_x in range(x0, x1 + 1):
            for grid_y in range(y0, y1 + 1):
                found.update(self.point_cells.get((grid_x, grid_y), ()))
        return tuple(self.points[index] for index in sorted(found))


class ProjectSheetViewPanel(QFrame):
    """Inspector for the selected drawing view on a project sheet."""

    scale_edited = Signal(str)
    identity_edited = Signal(str)
    axes_visibility_edited = Signal(bool)
    settings_applied = Signal(dict)

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._view_instance = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        self.title_label = QLabel("Vista", self)
        self.title_label.setObjectName("propertyTitle")
        layout.addWidget(self.title_label)
        name_label = QLabel("Identidade", self)
        name_label.setObjectName("propertySection")
        layout.addWidget(name_label)
        self.name_input = QLineEdit(self)
        self.name_input.setObjectName("identityDisplay")
        self.name_input.setAccessibleName("Identidade da vista")
        self.name_input.editingFinished.connect(self._commit_identity)
        identity_row = QHBoxLayout()
        identity_row.setContentsMargins(0, 0, 0, 0)
        identity_row.setSpacing(6)
        identity_row.addWidget(self.name_input, 1)
        self.settings_button = QToolButton(self)
        self.settings_button.setFixedSize(34, 34)
        self.settings_button.setCheckable(True)
        self.settings_button.setIcon(QIcon(str(
            Path(__file__).parents[1] / "resources" / "icons" / "settings.svg"
        )))
        self.settings_button.setIconSize(QSize(19, 19))
        self.settings_button.setToolTip("Configurações da vista inserida")
        self.settings_button.setAccessibleName("Configurações da vista inserida")
        self.settings_button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover { background: #eaeef2; }"
        )
        self.settings_button.toggled.connect(self._toggle_settings_panel)
        identity_row.addWidget(self.settings_button)
        layout.addLayout(identity_row)
        scale_label = QLabel("Escala", self)
        scale_label.setObjectName("propertySection")
        layout.addWidget(scale_label)
        scale_box = QFrame(self)
        scale_box.setObjectName("unitValueBox")
        scale_box.setStyleSheet(
            "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; }"
            "QFrame#unitValueBox QLineEdit { min-height: 30px; border: 0; "
            "background: transparent; color: #57606a; padding: 2px 5px; }"
            "QFrame#unitValueBox QLabel { color: #57606a; padding-left: 9px; }"
        )
        scale_box_layout = QHBoxLayout(scale_box)
        scale_box_layout.setContentsMargins(0, 0, 0, 0)
        scale_box_layout.setSpacing(0)
        scale_prefix = QLabel("1:", scale_box)
        scale_prefix.setAccessibleName("Numerador fixo da escala")
        scale_box_layout.addWidget(scale_prefix)
        self.scale_input = QLineEdit(scale_box)
        self.scale_input.setObjectName("scaleDenominatorInput")
        self.scale_input.setAccessibleName("Denominador da escala da vista")
        self.scale_input.setPlaceholderText("100")
        self.scale_input.editingFinished.connect(
            lambda: self.scale_edited.emit(self.scale_input.text())
        )
        scale_box_layout.addWidget(self.scale_input, 1)
        layout.addWidget(scale_box)
        axes_row = QHBoxLayout()
        axes_row.setContentsMargins(0, 0, 0, 0)
        axes_label = QLabel("Eixos", self)
        axes_label.setObjectName("propertySection")
        axes_row.addWidget(axes_label, 1)
        self.axes_button = QToolButton(self)
        self.axes_button.setFixedSize(30, 30)
        self.axes_button.setIcon(QIcon(str(
            Path(__file__).parents[1] / "resources" / "icons" / "axis-configuration.svg"
        )))
        self.axes_button.setIconSize(QSize(20, 20))
        self.axes_button.setCheckable(True)
        self.axes_button.setToolTip("Exibir eixos da vista")
        self.axes_button.setAccessibleName("Exibir eixos da vista")
        self.axes_button.setStyleSheet(
            "QToolButton { border: 0; border-radius: 6px; background: transparent; padding: 2px; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:checked { background: #d0d7de; }"
            "QToolButton:pressed { background: #afb8c1; }"
        )
        self.axes_button.toggled.connect(self.axes_visibility_edited)
        axes_row.addWidget(self.axes_button)
        layout.addLayout(axes_row)

        self._settings_popup = QFrame(
            window, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
        )
        self._settings_popup.setObjectName("insertedViewSettingsPopup")
        self._settings_popup.setFixedSize(245, 380)
        self._settings_popup.setStyleSheet(
            "QFrame#insertedViewSettingsPopup { background: #f6f8fa; "
            "border: 1px solid #d0d7de; border-radius: 6px; }"
            "QLabel { color: #57606a; }"
            "QLabel#propertySection { color: #57606a; font-size: 13px; }"
            "QFrame#viewSettingsValueBox { min-height: 34px; border: 1px solid #d0d7de; "
            "border-radius: 6px; background: #ffffff; }"
            "QFrame#viewSettingsValueBox[focused=\"true\"] { border: 2px solid #0969da; }"
            "QFrame#viewSettingsValueBox QDoubleSpinBox { border: 0; background: transparent; "
            "color: #57606a; padding: 2px 9px; }"
            "QFrame#viewSettingsValueBox QLabel { color: #57606a; padding-right: 9px; }"
            "QComboBox#viewSettingsOrientation { min-height: 34px; padding: 2px 9px; "
            "border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; color: #24292f; }"
            "QComboBox#viewSettingsOrientation::drop-down { width: 0; border: 0; }"
            "QComboBox#viewSettingsOrientation::down-arrow { image: none; }"
            "QPushButton#applyInsertedViewSettings { min-height: 34px; padding: 4px 14px; "
            "border: 1px solid #0969da; border-radius: 7px; color: #ffffff; "
            "background: #0969da; font-weight: 600; }"
            "QPushButton#applyInsertedViewSettings:hover { background: #0550ae; }"
        )
        popup_layout = QVBoxLayout(self._settings_popup)
        popup_layout.setContentsMargins(14, 14, 14, 14)
        popup_layout.setSpacing(9)
        self._view_settings_inputs = {}
        for key, label_text in (
            ("upper_offset_cm", "Deslocamento superior"),
            ("lower_offset_cm", "Deslocamento inferior"),
        ):
            group = QWidget(self._settings_popup)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(4)
            label = QLabel(label_text, group)
            label.setObjectName("propertySection")
            group_layout.addWidget(label)
            value_box = QFrame(group)
            value_box.setObjectName("viewSettingsValueBox")
            value_layout = QHBoxLayout(value_box)
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(0)
            field = CompactDoubleSpinBox(value_box)
            field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            field.setRange(0, 1e9)
            field.setDecimals(1)
            field.setKeyboardTracking(False)
            field.setAccessibleName(f"{label_text} (cm)")
            value_layout.addWidget(field, 1)
            value_layout.addWidget(QLabel("cm", value_box))
            group_layout.addWidget(value_box)
            popup_layout.addWidget(group)
            self._view_settings_inputs[key] = field

        rotation_group = QWidget(self._settings_popup)
        rotation_layout = QVBoxLayout(rotation_group)
        rotation_layout.setContentsMargins(0, 0, 0, 0)
        rotation_layout.setSpacing(4)
        rotation_label = QLabel("Rotação", rotation_group)
        rotation_label.setObjectName("propertySection")
        rotation_layout.addWidget(rotation_label)
        rotation_row = QHBoxLayout()
        rotation_row.setContentsMargins(0, 0, 0, 0)
        rotation_row.setSpacing(8)
        rotation_box = QFrame(rotation_group)
        rotation_box.setObjectName("viewSettingsValueBox")
        rotation_box_layout = QHBoxLayout(rotation_box)
        rotation_box_layout.setContentsMargins(0, 0, 0, 0)
        rotation_box_layout.setSpacing(0)
        self._view_rotation_input = CompactDoubleSpinBox(rotation_box)
        self._view_rotation_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._view_rotation_input.setRange(-1e12, 1e12)
        self._view_rotation_input.setDecimals(1)
        self._view_rotation_input.setKeyboardTracking(False)
        self._view_rotation_input.setAccessibleName("Rotação (graus)")
        rotation_box_layout.addWidget(self._view_rotation_input, 1)
        rotation_box_layout.addWidget(QLabel("°", rotation_box))
        rotation_row.addWidget(rotation_box, 1)
        self._view_rotation_button = QToolButton(rotation_group)
        self._view_rotation_button.setFixedSize(36, 36)
        self._view_rotation_button.setIcon(QIcon(str(
            Path(__file__).parents[1] / "resources" / "icons" / "rotate-cw.svg"
        )))
        self._view_rotation_button.setIconSize(QSize(20, 20))
        self._view_rotation_button.setToolTip("Girar a vista em 90°")
        self._view_rotation_button.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } "
            "QToolButton:hover { background: #eaeef2; }"
        )
        self._view_rotation_button.clicked.connect(
            lambda: self._view_rotation_input.setValue(
                (self._view_rotation_input.value() + 90.0) % 360.0,
            )
        )
        rotation_row.addWidget(self._view_rotation_button)
        rotation_layout.addLayout(rotation_row)
        popup_layout.addWidget(rotation_group)

        orientation_group = QWidget(self._settings_popup)
        orientation_layout = QVBoxLayout(orientation_group)
        orientation_layout.setContentsMargins(0, 0, 0, 0)
        orientation_layout.setSpacing(4)
        orientation_label = QLabel("Orientação", orientation_group)
        orientation_label.setObjectName("propertySection")
        orientation_layout.addWidget(orientation_label)
        self._view_orientation_selector = QComboBox(self._settings_popup)
        self._view_orientation_selector.setObjectName("viewSettingsOrientation")
        self._view_orientation_selector.addItems(
            ("Superior para inferior", "Inferior para superior")
        )
        orientation_layout.addWidget(self._view_orientation_selector)
        popup_layout.addWidget(orientation_group)
        self._apply_view_settings_button = QPushButton("Aplicar", self._settings_popup)
        self._apply_view_settings_button.setObjectName("applyInsertedViewSettings")
        self._apply_view_settings_button.clicked.connect(self._apply_settings)
        popup_layout.addStretch(1)
        popup_layout.addWidget(self._apply_view_settings_button)
        self._settings_popup.hide()
        self._settings_popup.installEventFilter(self)
        self.hide()

    def show_for(self, view: dict | None) -> None:
        if view is None:
            self._settings_popup.hide()
            self._view_instance = None
            self.hide()
            return
        if self._view_instance is not view:
            self._settings_popup.hide()
            self.settings_button.setChecked(False)
        self._view_instance = view
        is_component_detail = isinstance(view.get("component_detail_group"), dict)
        self.title_label.setText("Detalhe" if is_component_detail else "Vista")
        self.name_input.setText(str(view.get("name", "Vista")))
        denominator = float(view.get("scale_denominator", 100.0))
        self.scale_input.setText(f"{denominator:g}")
        self.axes_button.blockSignals(True)
        self.axes_button.setChecked(bool(view.get("axes_visible", False)))
        self.axes_button.setEnabled(True)
        self.axes_button.blockSignals(False)
        self.layout().activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.show()
        self.raise_()
        self.reposition()

    def _commit_identity(self) -> None:
        if self._view_instance is None:
            return
        identity = self.name_input.text().strip()
        if not identity:
            self.name_input.setText(str(self._view_instance.get("name", "Vista")))
            return
        if identity != str(self._view_instance.get("name", "Vista")):
            self.identity_edited.emit(identity)

    def _toggle_settings_panel(self, opened: bool) -> None:
        if not opened or self._view_instance is None:
            self._settings_popup.hide()
            return
        projection = self._view_instance.get("projection", {})
        if not isinstance(projection, dict):
            return
        self._view_settings_inputs["upper_offset_cm"].setValue(
            max(0.0, float(projection.get("upper_offset_cm", 50.0)))
        )
        self._view_settings_inputs["lower_offset_cm"].setValue(
            max(0.0, float(projection.get("lower_offset_cm", 50.0)))
        )
        self._view_rotation_input.setValue(float(projection.get("rotation_degrees", 0.0)))
        self._view_orientation_selector.setCurrentIndex(
            1 if projection.get("orientation") == "Inferior para superior" else 0
        )
        isometric = str(projection.get("plane", "")).startswith("ISO-")
        for field in self._view_settings_inputs.values():
            field.setEnabled(not isometric)
        self._view_orientation_selector.setEnabled(not isometric)
        panel_origin = self.mapToGlobal(QPoint(0, 0))
        popup_x = panel_origin.x() - self._settings_popup.width() - 8
        popup_y = panel_origin.y() + (self.height() - self._settings_popup.height()) // 2
        self._settings_popup.move(popup_x, popup_y)
        self._settings_popup.show()
        self._settings_popup.raise_()

    def _apply_settings(self) -> None:
        if self._view_instance is None:
            return
        settings = {
            key: field.value() for key, field in self._view_settings_inputs.items()
        }
        settings.update({
            "rotation_degrees": self._view_rotation_input.value() % 360.0,
            "orientation": self._view_orientation_selector.currentText(),
        })
        self._settings_popup.hide()
        self.settings_button.setChecked(False)
        self.settings_applied.emit(settings)

    def eventFilter(self, watched, event):
        if watched is self._settings_popup and event.type() == QEvent.Type.Hide:
            if self.settings_button.isChecked():
                self.settings_button.blockSignals(True)
                self.settings_button.setChecked(False)
                self.settings_button.blockSignals(False)
        return super().eventFilter(watched, event)

    def reposition(self) -> None:
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)
        self.raise_()


class ProjectSheetDetailGroupPanel(QFrame):
    """Inspector for a component detail-view group on a project sheet."""

    identity_edited = Signal(str)
    add_views_requested = Signal()

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._group = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Grupo de detalhes", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        label = QLabel("Identidade", self)
        label.setObjectName("propertySection")
        layout.addWidget(label)
        self.identity_input = QLineEdit(self)
        self.identity_input.setObjectName("identityDisplay")
        self.identity_input.setAccessibleName("Identidade do grupo de detalhes")
        self.identity_input.editingFinished.connect(self._commit_identity)
        layout.addWidget(self.identity_input)
        self.add_views_button = QPushButton("Adicionar vistas", self)
        self.add_views_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_views_button.clicked.connect(self.add_views_requested.emit)
        layout.addWidget(self.add_views_button)
        self.hide()

    def show_for(self, group: dict | None) -> None:
        if group is None:
            self._group = None
            self.hide()
            return
        self._group = group
        self.identity_input.setText(str(group.get("identity", group.get("title", "Grupo de detalhes"))))
        self.layout().activate()
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.show()
        self.raise_()
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)

    def _commit_identity(self) -> None:
        if self._group is None:
            return
        identity = self.identity_input.text().strip()
        previous = str(self._group.get("identity", self._group.get("title", "")))
        if not identity:
            self.identity_input.setText(previous)
        elif identity != previous:
            self.identity_edited.emit(identity)


class ProjectSheetIdentificationPanel(QFrame):
    """Read-only inspector for one element identifier on a project sheet."""

    property_toggled = Signal(str, int)

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Identificador", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        self.values: dict[str, QLineEdit] = {}
        self.checkboxes: dict[str, QCheckBox] = {}
        checkbox_style = (
            "QCheckBox { spacing: 0; min-height: 22px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de; "
            "border-radius: 5px; background: #ffffff; }"
            "QCheckBox::indicator:hover { border-color: #d0d7de; }"
            "QCheckBox::indicator:checked, QCheckBox::indicator:checked:hover { "
            "background: #0969da; border-color: #0969da; }"
            "QCheckBox::indicator:indeterminate { background: #ffffff; border-color: #0969da; }"
        )
        for key, label in (
            ("identity", "Identidade"),
            ("name", "Nome"),
            ("section", "Seção"),
        ):
            property_row = QHBoxLayout()
            property_row.setContentsMargins(0, 0, 0, 0)
            property_row.setSpacing(6)
            property_label = QLabel(label, self)
            property_label.setObjectName("propertySection")
            property_row.addWidget(property_label, 1)
            checkbox = MixedCheckBox(self)
            checkbox.setTristate(True)
            checkbox.setStyleSheet(checkbox_style)
            checkbox.setAccessibleName(f"Exibir {label.lower()} no identificador")
            checkbox.stateChanged.connect(
                lambda state, property_key=key: self.property_toggled.emit(property_key, state)
            )
            self.checkboxes[key] = checkbox
            property_row.addWidget(checkbox)
            layout.addLayout(property_row)
            value = QLineEdit(self)
            value.setObjectName("identityDisplay")
            value.setReadOnly(True)
            value.setAccessibleName(label)
            self.values[key] = value
            layout.addWidget(value)
        self.hide()

    def show_for(self, properties: dict | None) -> None:
        if properties is None:
            self.hide()
            return
        for key, field in self.values.items():
            field.setText(str(properties.get(key, "—") or "—"))
            checkbox = self.checkboxes[key]
            checkbox.blockSignals(True)
            state = properties.get(f"show_{key}", False)
            if isinstance(state, bool):
                state = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
            checkbox.setCheckState(Qt.CheckState(state))
            checkbox.setEnabled(not properties.get(f"disabled_{key}", False))
            checkbox.blockSignals(False)
        self.layout().activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.show()
        self.raise_()
        self.reposition()

    def reposition(self) -> None:
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)
        self.raise_()


class ProjectSheetDetailIdentifierPanel(QFrame):
    """Inspector for a detail identifier placed on a project sheet."""

    identity_edited = Signal(str)

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._identifier = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Detalhe", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        identity_label = QLabel("Identidade", self)
        identity_label.setObjectName("propertySection")
        layout.addWidget(identity_label)
        self.identity_input = QLineEdit(self)
        self.identity_input.setObjectName("identityDisplay")
        self.identity_input.setAccessibleName("Identidade do detalhe")
        self.identity_input.editingFinished.connect(self._commit_identity)
        layout.addWidget(self.identity_input)
        self.hide()

    def show_for(self, identifier: dict | None) -> None:
        if identifier is None:
            self._identifier = None
            self.hide()
            return
        self._identifier = identifier
        self.identity_input.setText(str(identifier.get("name", "")))
        self.layout().activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.show()
        self.raise_()
        self.reposition()

    def _commit_identity(self) -> None:
        if self._identifier is None:
            return
        identity = self.identity_input.text().strip()
        if not identity:
            self.identity_input.setText(str(self._identifier.get("name", "")))
            return
        if identity != str(self._identifier.get("name", "")):
            self.identity_edited.emit(identity)

    def reposition(self) -> None:
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)
        self.raise_()


class ProjectSheetElevationIdentifierPanel(QFrame):
    """Inspector for an elevation identifier placed on a project sheet."""

    identity_edited = Signal(str)

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._identifier = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Elevação", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        identity_label = QLabel("Identidade", self)
        identity_label.setObjectName("propertySection")
        layout.addWidget(identity_label)
        self.identity_input = QLineEdit(self)
        self.identity_input.setObjectName("identityDisplay")
        self.identity_input.setAccessibleName("Identidade da elevação")
        self.identity_input.editingFinished.connect(self._commit_identity)
        layout.addWidget(self.identity_input)
        self.hide()

    def show_for(self, identifier: dict | None) -> None:
        if identifier is None:
            self._identifier = None
            self.hide()
            return
        self._identifier = identifier
        self.identity_input.setText(str(identifier.get("name", "Elevação A")))
        self.layout().activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.show()
        self.raise_()
        self.reposition()

    def _commit_identity(self) -> None:
        if self._identifier is None:
            return
        identity = self.identity_input.text().strip()
        if not identity:
            self.identity_input.setText(str(self._identifier.get("name", "Elevação A")))
            return
        if identity != str(self._identifier.get("name", "Elevação A")):
            self.identity_edited.emit(identity)

    def reposition(self) -> None:
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)
        self.raise_()


def default_project_sheet_settings(sheet_name: str) -> dict:
    sheet_number, separator, title = sheet_name.partition(" - ")
    if not separator:
        sheet_number, title = "01", sheet_name
    return {
        "paper_size": "A3",
        "orientation": "Paisagem",
        "custom_width_mm": 420.0,
        "custom_height_mm": 297.0,
        "margin_left_mm": 25.0,
        "margin_right_mm": 10.0,
        "margin_top_mm": 10.0,
        "margin_bottom_mm": 10.0,
        "subject": title or "Folha Geral",
        "file": "",
        "scale": "INDICADA",
        "sheet_number": sheet_number,
        "revision": "00",
        "date": "",
        "title_block_visible": True,
        "title_block_position": "Inferior",
        "visible_fields": {
            "client": True,
            "work": True,
            "subject": True,
            "address": True,
            "responsible": True,
            "crea": True,
            "file": True,
            "date": True,
            "scale": True,
            "revision": True,
            "size": True,
            "sheet_number": True,
        },
    }


def default_project_settings() -> dict:
    return {
        "client": "",
        "work": "",
        "address": "",
        "responsible": "",
        "crea": "",
        "visual_identity_path": "",
        "title_block_property_text_height_mm": 2.5,
        "title_block_value_text_height_mm": 4.0,
        "view_name_text_height_mm": 4.0,
        "view_scale_text_height_mm": 3.0,
        "view_element_text_height_mm": 3.0,
        "view_section_text_height_mm": 2.5,
        **SPECIAL_DIMENSION_DEFAULTS,
        "dimension_text_height_mm": 3.0,
        "dimension_terminator_height_mm": 3.0,
        "dimension_unit": "cm",
        "dimension_decimal_places": 0,
        "dimension_extension_gap_mm": 1.0,
        "dimension_line_extension_mm": 3.0,
        "dimension_extension_overrun_mm": 3.0,
        "dimension_text_color": "#000000",
        "dimension_line_color": "#ff0000",
        "dimension_extension_color": "#ff0000",
        "dimension_terminator_color": "#ff0000",
        "dimension_custom_colors": [],
        "dimension_text_position": "superior",
        "detail_identifier_circle_color": "#ff0000",
        "detail_identifier_leader_color": "#ff0000",
        "detail_identifier_text_color": "#000000",
        "detail_identifier_leader_length_mm": 5.0,
        "detail_identifier_text_height_mm": 3.0,
        "detail_identifier_custom_colors": [],
        "weld_line_color": "#ff0000",
        "weld_text_color": "#000000",
        "weld_symbol_color": "#000000",
        "weld_text_height_mm": 3.0,
        "weld_custom_colors": [],
        "elevation_identifier_symbol_color": "#ff0000",
        "elevation_identifier_text_color": "#000000",
        "elevation_identifier_text_height_mm": 3.0,
        "elevation_identifier_direction_snap_degrees": 45.0,
        "elevation_identifier_custom_colors": [],
    }


class ProjectSheetWorkspace(QWidget):
    """A clean drawing surface with a centered landscape sheet."""

    selection_changed = Signal(object)
    identification_selection_changed = Signal(object)
    detail_identifier_selection_changed = Signal(object)
    elevation_identifier_selection_changed = Signal(object)
    remove_view_requested = Signal(int)
    layout_changed = Signal()
    element_identification_requested = Signal(int, str, object)
    identification_finished = Signal(bool)
    member_break_finished = Signal(bool)
    member_break_step_changed = Signal(int)
    dimension_finished = Signal(bool)
    dimension_step_changed = Signal(int)
    detail_identifier_finished = Signal(bool)
    detail_identifier_step_changed = Signal(int)
    elevation_identifier_finished = Signal(bool)
    elevation_identifier_step_changed = Signal(int)
    element_visibility_finished = Signal(bool)
    element_visibility_view_activated = Signal(int)
    element_visibility_changed = Signal(int, object)
    text_editor_requested = Signal(object)
    table_editor_requested = Signal(int)
    annotation_finished = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("projectSheetWorkspace")
        self.setAutoFillBackground(True)
        self.setStyleSheet("QWidget#projectSheetWorkspace { background: #f6f8fa; }")
        info = QWidget(self)
        info.setObjectName("projectSheetModelInfo")
        info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info.setStyleSheet("QWidget#projectSheetModelInfo { background: transparent; }")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        caption = QLabel("Modelo", info)
        caption.setObjectName("propertySection")
        self._model_name = QLabel("Novo modelo", info)
        self._model_name.setObjectName("modelNameOverlay")
        info_layout.addWidget(caption)
        info_layout.addWidget(self._model_name)
        self._model_info = info
        self._model_info.move(20, 14)
        self._model_info.adjustSize()
        self._linework_update_label = QLabel("Atualizando vistas da folha…", self)
        self._linework_update_label.setStyleSheet(
            "background: #ffffff; color: #57606a; border: 1px solid #d0d7de; padding: 6px;"
        )
        self._linework_update_label.hide()
        self.export_button = QPushButton("Exportar projeto", self)
        self.export_button.setObjectName("primaryButton")
        self.export_button.setToolTip("Exportar a folha ativa para PDF")
        self.export_button.setAccessibleName("Exportar projeto para PDF")
        self.export_button.adjustSize()
        self._sheet_name = "01 - Folha Geral"
        self._settings = default_project_sheet_settings(self._sheet_name)
        self._project_settings = default_project_settings()
        self._sheet_count = 1
        self._sheet_views: tuple[dict, ...] = ()
        self._sheet_texts: list[dict] = []
        self._sheet_lines: list[dict] = []
        self._sheet_table_hit_rects: dict[int, QRectF] = {}
        self._sheet_table_layouts = {}
        self.steel_profile_rows_provider = lambda: []
        self.steel_plate_rows_provider = lambda: []
        self.accessory_rows_provider = lambda: []
        self._selected_sheet_table: int | None = None
        self._drag_sheet_table: int | None = None
        self._table_drag_raw_bounds: QRectF | None = None
        self._table_drag_snap_segments = []
        self._sheet_text_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._sheet_text_handle_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._sheet_line_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._sheet_image_cache = {}
        self._pending_sheet_image = None
        self._selected_sheet_text: tuple[int, int] | None = None
        self._selected_sheet_line: tuple[int, int] | None = None
        self._sheet_line_handle_hit_rects: dict[tuple[int, int, int], QRectF] = {}
        self._drag_sheet_line_endpoint: tuple[int, int, int] | None = None
        self._drag_sheet_text: tuple[int, int] | None = None
        self._drag_sheet_text_handle: tuple[int, int] | None = None
        self._drag_sheet_text_bounds: QRectF | None = None
        self._annotation_mode: str | None = None
        self._line_start_context: tuple[int | None, tuple[float, float]] | None = None
        self._line_preview_endpoint: tuple[float, float] | None = None
        self._line_preview_screen_endpoint: QPointF | None = None
        self._line_preview_snap_kind: str | None = None
        self._line_preview_snap_screen: QPointF | None = None
        self._view_linework: dict[int, tuple] = {}
        self._view_segment_grids: dict[int, tuple[object, object, _SegmentSpatialGrid]] = {}
        self._view_axis_geometry: dict[int, tuple] = {}
        self._selected_view_index: int | None = None
        self._selected_view_title_index: int | None = None
        self._selected_axis_endpoints: set[tuple[int, str]] = set()
        self._selected_identification_index: int | None = None
        self._selected_identification_indices: set[int] = set()
        self._selected_detail_identifier: tuple[int, int] | None = None
        self._selected_elevation_identifier: tuple[int, int] | None = None
        self._view_hit_rects: dict[int, QRectF] = {}
        self._view_geometry_bounds: dict[int, QRectF] = {}
        self._view_content_bounds: dict[int, QRectF] = {}
        self._view_title_hit_rects: dict[int, QRectF] = {}
        self._component_group_hit_rects: dict[str, QRectF] = {}
        self._component_group_paper_frames = {}
        self._component_group_title_hit_rects: dict[str, QRectF] = {}
        self._selected_component_detail_group: str | None = None
        self._drag_component_detail_group: str | None = None
        self._drag_component_detail_label: str | None = None
        self._axis_line_bounds: dict[tuple[int, str], QRectF] = {}
        self._view_dimension_bounds: dict[tuple[int, int], QRectF] = {}
        self._identification_resize_handles = {}
        self._drag_identification_resize = None
        self._identification_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._detail_identifier_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._detail_identifier_handle_hit_rects: dict[tuple[int, int, str], QRectF] = {}
        self._elevation_identifier_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._elevation_identifier_bounds: dict[tuple[int, int], QRectF] = {}
        self._view_draw_data: dict[int, tuple[float, float, float, float, float]] = {}
        self._axis_endpoint_hit_rects: dict[tuple[int, str], QRectF] = {}
        self._axis_endpoint_drag_data: dict[tuple[int, str], tuple[float, float, float]] = {}
        self._axis_dimension_snap_segments: dict[int, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
        self._drag_axis_endpoints: tuple[tuple[int, str], ...] = ()
        self._drag_axis_current_bounds: dict[tuple[int, str], QRectF] = {}
        self._drag_axis_painted_bounds: dict[tuple[int, str], QRectF] = {}
        self._drag_axis_frame_current_bounds: dict[int, QRectF] = {}
        self._drag_axis_frame_painted_bounds: dict[int, QRectF] = {}
        self._dimension_snap_cache: dict[
            tuple[int, int, int, tuple[str, ...], tuple[str, ...]], _DimensionSnapIndex,
        ] = {}
        self._dimension_text_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._dimension_endpoint_hit_rects: dict[tuple[int, int, str], QRectF] = {}
        self._dimension_bounds: dict[tuple[int, int], QRectF] = {}
        self._selected_dimension: tuple[int, int] | None = None
        self._identification_mode = False
        self._detail_identifier_mode = False
        self._detail_identifier_view_index: int | None = None
        self._detail_identifier_center: tuple[float, float] | None = None
        self._detail_identifier_hover_projected: tuple[float, float] | None = None
        self._detail_identifier_snap_screen: QPointF | None = None
        self._detail_identifier_snap_kind: str | None = None
        self._detail_identifier_preview_radius = 0.0
        self._elevation_identifier_mode = False
        self._elevation_identifier_view_index: int | None = None
        self._elevation_identifier_point: tuple[float, float] | None = None
        self._elevation_identifier_hover_projected: tuple[float, float] | None = None
        self._elevation_identifier_preview_direction: tuple[float, float] | None = None
        self._selected_member_break = None
        self._drag_member_break = None
        self._member_break_mode = False
        self._member_break_view_index = None
        self._break_linework_cache = {}
        self._dimension_mode = False
        self._element_visibility_mode: str | None = None
        self._element_visibility_pending: set[str] = set()
        self._element_visibility_pending_view_index: int | None = None
        self._dimension_type = "aligned"
        self._dimension_points: list[tuple[float, float]] = []
        self._dimension_view_index: int | None = None
        self._dimension_hover_view_index: int | None = None
        self._dimension_hover_point: QPointF | None = None
        self._dimension_hover_projected: tuple[float, float] | None = None
        self._dimension_preview: dict | None = None
        self._dimension_preview_bounds: QRectF | None = None
        self._dimension_snap_screen: QPointF | None = None
        self._dimension_snap_kind: str | None = None
        self._hover_owners: set[tuple[int, str]] = set()
        self._hover_raw_target: tuple[int, str] | None = None
        self._identification_pick_member = False
        self._last_identification_position: QPointF | None = None
        self._drawing_area = QRectF()
        self._paper_rect = QRectF()
        self._stamp_rect = QRectF()
        self._annotation_background: QPixmap | None = None
        self._suppress_sheet_annotations = False
        self._sheet_text_documents = {}
        # A fixed layout device keeps font metrics and line wrapping independent
        # of screen DPI, zoom and navigation's cached drawing scale.
        self._sheet_text_layout_device = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        self._sheet_text_layout_device.setDotsPerMeterX(round(96.0 / 0.0254))
        self._sheet_text_layout_device.setDotsPerMeterY(round(96.0 / 0.0254))
        self._drag_position: QPointF | None = None
        self._drag_view_title_index: int | None = None
        self._drag_view_index: int | None = None
        self._drag_view_current_bounds: QRectF | None = None
        self._drag_view_painted_bounds: QRectF | None = None
        self._drag_title_current_bounds: QRectF | None = None
        self._drag_title_painted_bounds: QRectF | None = None
        self._drag_title_frame_current_bounds: QRectF | None = None
        self._drag_title_frame_painted_bounds: QRectF | None = None
        self._drag_identification_index: int | None = None
        self._drag_detail_identifier: tuple[int, int] | None = None
        self._drag_detail_identifier_handle: tuple[int, int, str] | None = None
        self._drag_elevation_identifier: tuple[int, int] | None = None
        self._drag_elevation_identifier_bounds: QRectF | None = None
        self._drag_identification_indices: tuple[int, ...] = ()
        self._drag_dimension_index: tuple[int, int] | None = None
        self._drag_dimension_endpoint: tuple[int, int, str] | None = None
        self._drag_dimension_current_bounds: QRectF | None = None
        self._drag_dimension_painted_bounds: QRectF | None = None
        self._drag_dimension_content_current_bounds: QRectF | None = None
        self._drag_identification_current_bounds: dict[int, QRectF] = {}
        self._drag_identification_painted_bounds: dict[int, QRectF] = {}
        self._zoom_factor = 1.0
        self._sheet_pixels_per_mm = 1.0
        self._pan_offset = QPointF()
        self._pan_anchor: QPointF | None = None
        self._pan_origin = QPointF()
        self._navigation_picture: QPicture | None = None
        self._navigation_pixmap: QPixmap | None = None
        self._navigation_picture_dirty = True
        self._navigation_picture_size = QSize()
        self._navigation_picture_dpr = 0.0
        self._navigation_picture_model_key = None
        self._navigation_picture_zoom = 1.0
        self._navigation_picture_pan = QPointF()
        self._navigation_pixmap_zoom = 1.0
        self._navigation_pixmap_pan = QPointF()
        self._navigation_cache_margin = QPointF()
        self._navigating = False
        self._annotation_partial_repaint = False
        self._navigation_timer = QTimer(self)
        self._navigation_timer.setSingleShot(True)
        self._navigation_timer.setInterval(100)
        self._navigation_timer.timeout.connect(self._finish_navigation)
        self._snap_symbol_pixmaps = self._make_snap_symbol_pixmaps()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_model_name(self, name: str) -> None:
        self._model_name.setText(name.strip() or "Novo modelo")
        self._model_info.adjustSize()
        self._model_info.move(20, 14)
        self._model_info.raise_()

    def set_linework_updating(self, updating: bool) -> None:
        self._linework_update_label.adjustSize()
        self._linework_update_label.move(max(0, self.width() - self._linework_update_label.width() - 20), 14)
        self._linework_update_label.setVisible(updating)
        self.export_button.setEnabled(not updating)
        if updating:
            self._linework_update_label.raise_()

    def update(self, *args) -> None:
        # An explicit update accompanies changes to sheet content or selection.
        # Window exposure alone can reuse the previously recorded drawing.
        self._navigation_picture_dirty = True
        self._annotation_partial_repaint = False
        super().update(*args)

    def set_sheet_settings(
        self, sheet_name: str, settings: dict, project_settings: dict | None = None,
        sheet_count: int | None = None,
    ) -> None:
        if sheet_name != self._sheet_name:
            self._selected_sheet_table = None
            self._drag_sheet_table = None
            self._table_drag_raw_bounds = None
            self._table_drag_snap_segments = []
            self._annotation_background = None
        self._sheet_name = sheet_name
        self._settings = settings
        if project_settings is not None:
            self._project_settings = project_settings
        if sheet_count is not None:
            self._sheet_count = sheet_count
        self.update()

    def set_sheet_views(self, views, *, clear_selection: bool = False) -> None:
        self._drag_identification_resize = None
        self._identification_resize_handles.clear()
        self._component_group_paper_frames.clear()
        if hasattr(self, "weld_tool"):
            self.weld_tool.reset()
        if self._member_break_mode:
            self.set_member_break_mode(False)
            self.member_break_finished.emit(True)
        self._break_linework_cache.clear()
        self._selected_member_break = None
        self._drag_member_break = None
        if self._element_visibility_mode is not None:
            self.set_element_visibility_mode(None)
            self.element_visibility_finished.emit(True)
        if self._dimension_mode:
            self.set_dimension_mode(False)
            self.dimension_finished.emit(True)
        if self._detail_identifier_mode:
            self.set_detail_identifier_mode(False)
            self.detail_identifier_finished.emit(True)
        if self._elevation_identifier_mode:
            self.set_elevation_identifier_mode(False)
            self.elevation_identifier_finished.emit(True)
        self._sheet_views = tuple(views)
        self._view_linework.clear()
        self._view_segment_grids.clear()
        self._view_axis_geometry.clear()
        self._dimension_snap_cache.clear()
        self._selected_dimension = None
        self._selected_view_title_index = None
        self._selected_axis_endpoints.clear()
        if clear_selection or (
            self._selected_view_index is not None
            and self._selected_view_index >= len(self._sheet_views)
        ):
            self._selected_view_index = None
            self._selected_detail_identifier = None
            self._selected_elevation_identifier = None
            self._selected_identification_index = None
            self._selected_identification_indices.clear()
            self.detail_identifier_selection_changed.emit(None)
            self.elevation_identifier_selection_changed.emit(None)
            self.identification_selection_changed.emit(None)
            self.selection_changed.emit(None)
        elif (
            self._selected_view_index is not None
            and self._selected_identification_indices
        ):
            identifications = self._sheet_views[self._selected_view_index].get("identifications", ())
            self._emit_identification_selection(identifications)
        self.update()

    def set_sheet_annotations(self, texts, lines) -> None:
        self._sheet_image_cache.clear()
        self._sheet_texts = texts if isinstance(texts, list) else list(texts or ())
        self._sheet_lines = lines if isinstance(lines, list) else list(lines or ())
        self._selected_sheet_text = None
        self._selected_sheet_line = None
        self.update()

    def set_sheet_image_mode(self, annotation: dict) -> None:
        self.set_sheet_text_mode(True)
        self._pending_sheet_image = dict(annotation)
        self._annotation_mode = "image"

    def set_sheet_text_mode(self, active: bool) -> None:
        self._pending_sheet_image = None
        self._member_break_mode = False
        if active:
            self._selected_sheet_table = None
        self._annotation_mode = "text" if active else None
        self._annotation_background = None
        self._line_start_context = None
        self._line_preview_endpoint = None
        self._line_preview_screen_endpoint = None
        self._line_preview_snap_kind = None
        self._line_preview_snap_screen = None
        if active:
            self._dimension_mode = False
            self._identification_mode = False
            self._detail_identifier_mode = False
            self._elevation_identifier_mode = False
            self._element_visibility_mode = None
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_sheet_line_mode(self, active: bool, kind: str = "line") -> None:
        self._pending_sheet_image = None
        self._member_break_mode = False
        if kind not in {"line", "rectangle", "circle"}:
            raise ValueError("Tipo de desenho inválido")
        if active:
            self._selected_sheet_table = None
        self._annotation_mode = kind if active else None
        self._annotation_background = None
        self._line_start_context = None
        self._line_preview_endpoint = None
        self._line_preview_screen_endpoint = None
        self._line_preview_snap_kind = None
        self._line_preview_snap_screen = None
        if active:
            self._dimension_mode = False
            self._identification_mode = False
            self._detail_identifier_mode = False
            self._elevation_identifier_mode = False
            self._element_visibility_mode = None
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def add_sheet_text(self, annotation: dict) -> None:
        view_index = annotation.get("view_index")
        if isinstance(view_index, int) and 0 <= view_index < len(self._sheet_views):
            self._sheet_views[view_index].setdefault("sheet_texts", []).append(annotation)
        else:
            self._sheet_texts.append(annotation)
            view_index = None
        collection = (
            self._sheet_views[view_index].get("sheet_texts", [])
            if view_index is not None else self._sheet_texts
        )
        self._selected_sheet_text = (view_index if view_index is not None else -1, len(collection) - 1)
        self._selected_sheet_line = None
        self.select_view(None)
        self.set_sheet_text_mode(False)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.layout_changed.emit()

    def _annotation_view_at(self, point: QPointF) -> int | None:
        return next((
            index for index, rect in reversed(tuple(self._view_hit_rects.items()))
            if rect.contains(point)
        ), None)

    def _annotation_anchor(self, point: QPointF, view_index: int | None):
        if view_index is not None:
            projected = self._projected_point_at(view_index, point)
            return tuple(float(value) for value in projected) if projected is not None else None
        if self._drawing_area.width() <= 0 or self._drawing_area.height() <= 0:
            return None
        return (
            (point.x() - self._drawing_area.left()) / self._drawing_area.width(),
            (point.y() - self._drawing_area.top()) / self._drawing_area.height(),
        )

    def _sheet_annotation_screen_point(self, annotation: dict, view_index: int | None) -> QPointF | None:
        try:
            x, y = (float(value) for value in annotation.get("anchor", ()))
        except (TypeError, ValueError):
            return None
        if view_index is not None:
            return self._screen_point(view_index, (x, y))
        if self._drawing_area.isNull():
            return None
        return QPointF(
            self._drawing_area.left() + x * self._drawing_area.width(),
            self._drawing_area.top() + y * self._drawing_area.height(),
        )

    def _text_annotation_collection(self, view_index: int | None):
        if view_index is None:
            return self._sheet_texts
        if not 0 <= view_index < len(self._sheet_views):
            return []
        return self._sheet_views[view_index].setdefault("sheet_texts", [])

    def _line_annotation_collection(self, view_index: int | None):
        if view_index is None:
            return self._sheet_lines
        if not 0 <= view_index < len(self._sheet_views):
            return []
        return self._sheet_views[view_index].setdefault("sheet_lines", [])

    def _annotation_for_text_key(self, key: tuple[int, int]) -> dict | None:
        view_index, text_index = key
        collection = self._text_annotation_collection(None if view_index < 0 else view_index)
        return collection[text_index] if 0 <= text_index < len(collection) else None

    def delete_selected_sheet_text(self) -> bool:
        if self._selected_sheet_text is None:
            return False
        view_index, text_index = self._selected_sheet_text
        collection = self._text_annotation_collection(None if view_index < 0 else view_index)
        if 0 <= text_index < len(collection):
            collection.pop(text_index)
        self._selected_sheet_text = None
        self.update()
        self.layout_changed.emit()
        return True

    def delete_selected_sheet_line(self) -> bool:
        if self._selected_sheet_line is None:
            return False
        view_index, line_index = self._selected_sheet_line
        collection = self._line_annotation_collection(None if view_index < 0 else view_index)
        if 0 <= line_index < len(collection):
            collection.pop(line_index)
        self._selected_sheet_line = None
        self.update()
        self.layout_changed.emit()
        return True

    def invalidate_view_geometry(self, view_index: int) -> None:
        """Drop derived drawing and snap caches for one inserted sheet view."""
        self._view_linework.pop(view_index, None)
        self._view_segment_grids.pop(view_index, None)
        self._dimension_snap_cache = {
            key: value for key, value in self._dimension_snap_cache.items()
            if key[0] != view_index
        }

    def select_view(self, index: int | None) -> None:
        if index is not None and not 0 <= index < len(self._sheet_views):
            index = None
        appearance_changed = (
            index != self._selected_view_index
            or bool(self._selected_identification_indices)
            or self._selected_identification_index is not None
        )
        if index != self._selected_view_index:
            self._selected_dimension = None
            self._selected_detail_identifier = None
            self._selected_elevation_identifier = None
            self._selected_view_title_index = None
            self._selected_axis_endpoints.clear()
            self.detail_identifier_selection_changed.emit(None)
            self.elevation_identifier_selection_changed.emit(None)
        self._selected_view_index = index
        self._selected_identification_index = None
        self._selected_identification_indices.clear()
        self.identification_selection_changed.emit(None)
        self.selection_changed.emit(
            self._sheet_views[index] if index is not None else None
        )
        if appearance_changed:
            self.update()

    def _component_detail_group_selection(self, group_id: str) -> dict | None:
        for view in self._sheet_views:
            metadata = view.get("component_detail_group")
            if isinstance(metadata, dict) and str(metadata.get("id")) == str(group_id):
                return {
                    "_selection_type": "component_detail_group",
                    "id": str(group_id),
                    "identity": metadata.get("identity", metadata.get("title", "Grupo de detalhes")),
                }
        return None

    def _component_detail_group_bounds(
        self, group_id: str, *, view_override: tuple[int, QRectF] | None = None,
        title_override: QRectF | None = None,
    ) -> QRectF:
        if view_override is None and title_override is None:
            cached = self._component_group_hit_rects.get(str(group_id))
            if cached is not None:
                return QRectF(cached)
        bounds = QRectF()
        for index, view in enumerate(self._sheet_views):
            metadata = view.get("component_detail_group")
            if not isinstance(metadata, dict) or str(metadata.get("id")) != str(group_id):
                continue
            view_bounds = (
                view_override[1] if view_override is not None and view_override[0] == index
                else self._view_hit_rects.get(index)
            )
            if view_bounds is not None:
                bounds = bounds.united(view_bounds)
        title_bounds = (
            title_override if title_override is not None
            else self._component_group_title_hit_rects.get(str(group_id))
        )
        if title_bounds is not None:
            bounds = bounds.united(title_bounds)
        if bounds.isNull():
            return bounds
        gap = 5.0 * self._sheet_pixels_per_mm
        return bounds.adjusted(-gap, -gap, gap, gap).intersected(self._drawing_area)

    def _stable_component_group_frame(self, group_id, indices, content_bounds, inner, scale):
        """Keep a detail frame in paper coordinates across zoom/pan/resize.

        Screen hit tolerances and rounded font metrics must not resize the
        frame when only navigation changes. Refit it when its content changes.
        """
        signature = (
            self._sheet_name,
            round(inner.width() / scale, 6), round(inner.height() / scale, 6),
            repr(self._project_settings),
            tuple((id(self._sheet_views[i].get("segments")),
                   id(self._sheet_views[i].get("segment_owners")),
                   repr({key: value for key, value in self._sheet_views[i].items()
                         if key not in {"segments", "segment_owners"}})) for i in indices),
        )
        cached = self._component_group_paper_frames.get(group_id)
        if cached is None or cached[0] != signature:
            gap = 5.0 * scale
            fitted = content_bounds.adjusted(-gap, -gap, gap, gap)
            paper = QRectF((fitted.left() - inner.left()) / scale,
                           (fitted.top() - inner.top()) / scale,
                           fitted.width() / scale, fitted.height() / scale)
            self._component_group_paper_frames[group_id] = signature, paper
        else:
            paper = cached[1]
        return QRectF(inner.left() + paper.left() * scale,
                      inner.top() + paper.top() * scale,
                      paper.width() * scale, paper.height() * scale).intersected(inner)

    def set_component_detail_group_identity(self, identity: str) -> None:
        group_id = self._selected_component_detail_group
        identity = str(identity).strip()
        if not group_id or not identity:
            return
        changed = False
        for view in self._sheet_views:
            metadata = view.get("component_detail_group")
            if not isinstance(metadata, dict) or str(metadata.get("id")) != group_id:
                continue
            metadata["identity"] = identity
            metadata["title"] = identity
            changed = True
        if changed:
            self.update()
            self.layout_changed.emit()
            self.selection_changed.emit(self._component_detail_group_selection(group_id))

    @staticmethod
    def _make_snap_symbol_pixmaps() -> dict[str, QPixmap]:
        icon_root = Path(__file__).parents[1] / "resources" / "icons"
        filenames = {
            "intersection": "x.svg",
            "endpoint": "square.svg",
            "center": "triangle.svg",
            "perpendicular": "perpendicular.svg",
        }
        pixmaps = {}
        for kind, filename in filenames.items():
            source = QPixmap(24, 24)
            source.fill(Qt.GlobalColor.transparent)
            renderer = QSvgRenderer(str(icon_root / filename))
            source_painter = QPainter(source)
            renderer.render(source_painter, QRectF(1.0, 1.0, 22.0, 22.0))
            source_painter.end()
            colored = QPixmap(24, 24)
            colored.fill(QColor("#0969da"))
            painter = QPainter(colored)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, source)
            painter.end()
            pixmaps[kind] = colored
        return pixmaps

    def _emit_identification_selection(self, identifications=None) -> None:
        if identifications is None:
            index = self._selected_view_index
            identifications = (
                self._sheet_views[index].get("identifications", ())
                if index is not None and index < len(self._sheet_views) else ()
            )
        selected = [
            identifications[index]
            for index in sorted(self._selected_identification_indices)
            if 0 <= index < len(identifications)
        ]
        self.identification_selection_changed.emit(selected or None)

    def set_selected_view_scale(self, scale_denominator: float) -> None:
        index = self._selected_view_index
        if index is None or not 0 < scale_denominator < 1e9:
            return
        if float(self._sheet_views[index].get("scale_denominator", 100.0)) == float(scale_denominator):
            return
        self._sheet_views[index]["scale_denominator"] = float(scale_denominator)
        self.update()
        self.layout_changed.emit()

    def delete_selected_identification(self) -> bool:
        index = self._selected_view_index
        label_index = self._selected_identification_index
        if index is None or label_index is None or not 0 <= index < len(self._sheet_views):
            return False
        identifications = self._sheet_views[index].get("identifications", [])
        if not 0 <= label_index < len(identifications):
            self._selected_identification_index = None
            self._selected_identification_indices.clear()
            self.identification_selection_changed.emit(None)
            return False
        identifications.pop(label_index)
        self._selected_identification_index = None
        self._selected_identification_indices.clear()
        self.identification_selection_changed.emit(None)
        self.update()
        self.layout_changed.emit()
        return True

    def delete_selected_detail_identifier(self) -> bool:
        selected = self._selected_detail_identifier
        if selected is None:
            return False
        view_index, identifier_index = selected
        if not 0 <= view_index < len(self._sheet_views):
            self._selected_detail_identifier = None
            return False
        identifiers = self._sheet_views[view_index].get("detail_identifiers", [])
        if not 0 <= identifier_index < len(identifiers):
            self._selected_detail_identifier = None
            return False
        identifiers.pop(identifier_index)
        self._selected_detail_identifier = None
        self.detail_identifier_selection_changed.emit(None)
        self.update()
        self.layout_changed.emit()
        return True

    def delete_selected_elevation_identifier(self) -> bool:
        selected = self._selected_elevation_identifier
        if selected is None:
            return False
        view_index, identifier_index = selected
        if not 0 <= view_index < len(self._sheet_views):
            self._selected_elevation_identifier = None
            return False
        identifiers = self._sheet_views[view_index].get("elevation_identifiers", [])
        if not 0 <= identifier_index < len(identifiers):
            self._selected_elevation_identifier = None
            return False
        identifiers.pop(identifier_index)
        self._selected_elevation_identifier = None
        self.elevation_identifier_selection_changed.emit(None)
        self.update()
        self.layout_changed.emit()
        return True

    def delete_selected_dimension(self) -> bool:
        selected = self._selected_dimension
        if selected is None:
            return False
        view_index, dimension_index = selected
        if not 0 <= view_index < len(self._sheet_views):
            self._selected_dimension = None
            return False
        dimensions = self._sheet_views[view_index].get("dimensions", [])
        if not 0 <= dimension_index < len(dimensions):
            self._selected_dimension = None
            return False
        dimensions.pop(dimension_index)
        self._selected_dimension = None
        self.update()
        self.layout_changed.emit()
        return True

    def set_identification_mode(self, active: bool, view_index: int | None = None) -> None:
        self._member_break_mode = False
        self._dimension_mode = False
        self._detail_identifier_mode = False
        self._elevation_identifier_mode = False
        self._element_visibility_mode = None
        self._identification_mode = bool(active)
        self._hover_owners.clear()
        self._hover_raw_target = None
        self._identification_pick_member = False
        self.setCursor(QCursor(
            Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        ))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_dimension_mode(self, active: bool, dimension_type: str | None = None) -> None:
        self._member_break_mode = False
        if dimension_type is not None:
            if dimension_type not in {"aligned", "orthogonal", "angular", "level"}:
                raise ValueError("Tipo de cota desconhecido.")
            self._dimension_type = dimension_type
        self._dimension_mode = bool(active)
        self._dimension_points.clear()
        self._dimension_view_index = None
        self._dimension_hover_view_index = None
        self._dimension_hover_point = None
        self._dimension_hover_projected = None
        self._dimension_preview = None
        self._dimension_preview_bounds = None
        self._dimension_snap_screen = None
        self._dimension_snap_kind = None
        self._identification_mode = False
        self._detail_identifier_mode = False
        self._elevation_identifier_mode = False
        self._element_visibility_mode = None
        self._hover_owners.clear()
        self.setCursor(QCursor(
            Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        ))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_detail_identifier_mode(self, active: bool) -> None:
        self._member_break_mode = False
        self._dimension_mode = False
        self._identification_mode = False
        self._elevation_identifier_mode = False
        self._element_visibility_mode = None
        self._detail_identifier_mode = bool(active)
        self._detail_identifier_view_index = None
        self._detail_identifier_center = None
        self._detail_identifier_hover_projected = None
        self._detail_identifier_snap_screen = None
        self._detail_identifier_snap_kind = None
        self._detail_identifier_preview_radius = 0.0
        self.setCursor(QCursor(
            Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        ))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def set_elevation_identifier_mode(self, active: bool) -> None:
        self._member_break_mode = False
        self._dimension_mode = False
        self._identification_mode = False
        self._detail_identifier_mode = False
        self._element_visibility_mode = None
        self._elevation_identifier_mode = bool(active)
        self._elevation_identifier_view_index = None
        self._elevation_identifier_point = None
        self._elevation_identifier_hover_projected = None
        self._elevation_identifier_preview_direction = None
        self.setCursor(QCursor(
            Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor
        ))
        if active:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    def _next_elevation_identifier_name(self) -> str:
        used = set()
        for view in self._sheet_views:
            for identifier in view.get("elevation_identifiers", ()):
                name = str(identifier.get("name", "")) if isinstance(identifier, dict) else ""
                if name.lower().startswith("elevação "):
                    used.add(name[len("Elevação "):].strip().upper())
        number = 1
        while self._alphabetic_detail_suffix(number) in used:
            number += 1
        return f"Elevação {self._alphabetic_detail_suffix(number)}"

    def _elevation_direction_at(
        self, point: tuple[float, float], cursor: tuple[float, float], *, snap: bool,
    ) -> tuple[float, float] | None:
        dx, dy = cursor[0] - point[0], cursor[1] - point[1]
        if math.hypot(dx, dy) <= 1e-9:
            return None
        angle = math.atan2(dy, dx)
        if snap:
            try:
                interval = float(self._project_settings.get(
                    "elevation_identifier_direction_snap_degrees", 45.0,
                ))
            except (TypeError, ValueError):
                interval = 45.0
            if interval > 0.0:
                interval_radians = math.radians(interval)
                angle = round(angle / interval_radians) * interval_radians
        return math.cos(angle), math.sin(angle)

    def _elevation_identifier_click(self, position: QPointF, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        view_index = self._elevation_identifier_view_index
        if view_index is None:
            view_hit = next((
                index for index, rect in reversed(tuple(self._view_hit_rects.items()))
                if rect.contains(position)
            ), None)
            if view_hit is not None:
                self._elevation_identifier_view_index = view_hit
                self.select_view(view_hit)
                self.elevation_identifier_step_changed.emit(1)
                self.update()
            return
        if not 0 <= view_index < len(self._sheet_views):
            self._elevation_identifier_view_index = None
            return
        if self._elevation_identifier_point is None:
            snap = self._dimension_snap_at(position, view_index)
            projected = snap[2] if snap is not None else self._projected_point_at(view_index, position)
            if projected is None:
                return
            self._elevation_identifier_point = tuple(float(value) for value in projected)
            self._elevation_identifier_hover_projected = self._elevation_identifier_point
            self.elevation_identifier_step_changed.emit(2)
            self.update()
            return

        point = self._elevation_identifier_point
        cursor = self._projected_point_at(view_index, position)
        if cursor is None:
            return
        direction = self._elevation_direction_at(
            point, tuple(float(value) for value in cursor),
            snap=not bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
        )
        if direction is None:
            return
        self._sheet_views[view_index].setdefault("elevation_identifiers", []).append({
            "name": self._next_elevation_identifier_name(),
            "point": point,
            "direction": direction,
        })
        self._elevation_identifier_point = None
        self._elevation_identifier_hover_projected = None
        self._elevation_identifier_preview_direction = None
        self.elevation_identifier_step_changed.emit(1)
        self.update()
        self.layout_changed.emit()

    def _finish_elevation_identifier_mode(self, canceled: bool) -> None:
        if not self._elevation_identifier_mode:
            return
        self.set_elevation_identifier_mode(False)
        self.elevation_identifier_finished.emit(canceled)

    @staticmethod
    def _alphabetic_detail_suffix(number: int) -> str:
        """Return an Excel-style alphabetic sequence beginning at A."""
        number = max(1, int(number))
        letters = []
        while number:
            number, remainder = divmod(number - 1, 26)
            letters.append(chr(ord("A") + remainder))
        return "".join(reversed(letters))

    def _next_detail_identifier_name(self) -> str:
        used = set()
        for view in self._sheet_views:
            for identifier in view.get("detail_identifiers", ()):
                name = str(identifier.get("name", "")) if isinstance(identifier, dict) else ""
                if name.upper().startswith("DET "):
                    used.add(name[4:].strip().upper())
        number = 1
        while self._alphabetic_detail_suffix(number) in used:
            number += 1
        return f"DET {self._alphabetic_detail_suffix(number)}"

    def _detail_identifier_click(self, position: QPointF) -> None:
        view_index = self._detail_identifier_view_index
        if view_index is None:
            view_hit = next((
                index for index, rect in reversed(tuple(self._view_hit_rects.items()))
                if rect.contains(position)
            ), None)
            if view_hit is not None:
                self._detail_identifier_view_index = view_hit
                self.select_view(view_hit)
                self.detail_identifier_step_changed.emit(1)
                self.update()
            return
        if not 0 <= view_index < len(self._sheet_views):
            self._detail_identifier_view_index = None
            return

        snap = self._dimension_snap_at(position, view_index)
        projected = snap[2] if snap is not None else self._projected_point_at(view_index, position)
        if projected is None:
            return
        projected = (float(projected[0]), float(projected[1]))
        if self._detail_identifier_center is None:
            self._detail_identifier_center = projected
            self._detail_identifier_hover_projected = projected
            self._detail_identifier_snap_screen = None
            self._detail_identifier_preview_radius = 0.0
            self.detail_identifier_step_changed.emit(2)
            self.update()
            return

        center = self._detail_identifier_center
        radius = math.hypot(projected[0] - center[0], projected[1] - center[1])
        if radius <= 1e-9:
            return
        view = self._sheet_views[view_index]
        denominator = max(1.0, float(view.get("scale_denominator", 100.0)))
        tail_model = float(
            self._project_settings.get("detail_identifier_leader_length_mm", 5.0)
        ) * denominator / 1000.0
        label_gap_model = 3.0 * denominator / 1000.0
        label_position = (
            center[0] + radius * 1.5 + tail_model + label_gap_model,
            center[1] - radius * 0.9,
        )
        view.setdefault("detail_identifiers", []).append({
            "name": self._next_detail_identifier_name(),
            "center": center,
            "radius": radius,
            "label_position": label_position,
        })
        self._detail_identifier_center = None
        self._detail_identifier_hover_projected = None
        self._detail_identifier_snap_screen = None
        self._detail_identifier_snap_kind = None
        self._detail_identifier_preview_radius = 0.0
        self.detail_identifier_step_changed.emit(1)
        self.update()
        self.layout_changed.emit()

    def _finish_detail_identifier_mode(self, canceled: bool) -> None:
        if not self._detail_identifier_mode:
            return
        self.set_detail_identifier_mode(False)
        self.detail_identifier_finished.emit(canceled)

    def set_element_visibility_mode(self, mode: str | None) -> None:
        self._member_break_mode = False
        if mode not in {None, "hide", "reveal", "reveal_all"}:
            raise ValueError("Modo de visibilidade desconhecido.")
        self._dimension_mode = False
        self._identification_mode = False
        self._detail_identifier_mode = False
        self._elevation_identifier_mode = False
        self._element_visibility_mode = mode
        self._element_visibility_pending.clear()
        self._element_visibility_pending_view_index = self._selected_view_index if mode in {"hide", "reveal"} else None
        self._hover_owners.clear()
        self._hover_raw_target = None
        if mode is None:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            if self._selected_view_index is not None:
                self._activate_element_visibility_view(self._selected_view_index)
        self.update()

    def _activate_element_visibility_view(self, view_index: int) -> None:
        if not 0 <= view_index < len(self._sheet_views):
            return
        self.select_view(view_index)
        if self._element_visibility_pending_view_index != view_index:
            self._element_visibility_pending.clear()
            self._element_visibility_pending_view_index = view_index
        if self._element_visibility_mode == "reveal_all":
            view = self._sheet_views[view_index]
            if view.get("hidden_owners"):
                view["hidden_owners"] = []
                view["hidden_linework"] = {}
                self.layout_changed.emit()
                self.element_visibility_changed.emit(view_index, ())
            self._finish_element_visibility_mode(False)
            return
        self.element_visibility_view_activated.emit(view_index)

    def _finish_element_visibility_mode(self, canceled: bool) -> None:
        if self._element_visibility_mode is None:
            return
        self._element_visibility_mode = None
        self._hover_owners.clear()
        self._hover_raw_target = None
        self._element_visibility_pending.clear()
        self._element_visibility_pending_view_index = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
        self.element_visibility_finished.emit(canceled)

    def _confirm_element_visibility_selection(self) -> None:
        view_index = self._element_visibility_pending_view_index
        selected_owners = set(self._element_visibility_pending)
        mode = self._element_visibility_mode
        if mode not in {"hide", "reveal"} or view_index is None or not selected_owners:
            self._finish_element_visibility_mode(False)
            return
        if not 0 <= view_index < len(self._sheet_views):
            self._finish_element_visibility_mode(False)
            return
        view = self._sheet_views[view_index]
        hidden = {str(owner) for owner in view.get("hidden_owners", ())}
        updated = hidden | selected_owners if mode == "hide" else hidden - selected_owners
        if updated != hidden:
            hidden_linework = dict(view.get("hidden_linework", {}))
            owners = view.get("segment_owners", ())
            if mode == "hide":
                for owner in updated - hidden:
                    hidden_linework[owner] = tuple(
                        segment
                        for segment, segment_owner in zip(view.get("segments", ()), owners)
                        if str(segment_owner) == owner
                    )
            else:
                for owner in hidden - updated:
                    hidden_linework.pop(owner, None)
            view["hidden_linework"] = hidden_linework
            view["hidden_owners"] = sorted(updated)
            self.element_visibility_changed.emit(view_index, tuple(sorted(updated)))
            self.layout_changed.emit()
        self._finish_element_visibility_mode(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.export_button.adjustSize()
        self.export_button.move(max(0, self.width()-self.export_button.width()-24),
                                max(0, self.height()-self.export_button.height()-24))
        self.export_button.raise_()

    def paper_size_mm(self) -> tuple[float, float]:
        paper_size = self._settings.get("paper_size", "A3")
        if paper_size == "Personalizado":
            paper_width, paper_height = (
                float(self._settings.get("custom_width_mm", 420.0)),
                float(self._settings.get("custom_height_mm", 297.0)),
            )
        else:
            paper_width, paper_height = PAPER_SIZES_MM.get(paper_size, PAPER_SIZES_MM["A3"])
        if self._settings.get("orientation") == "Retrato":
            paper_width, paper_height = min(paper_width, paper_height), max(paper_width, paper_height)
        else:
            paper_width, paper_height = max(paper_width, paper_height), min(paper_width, paper_height)
        return paper_width, paper_height

    def paint_sheet(self, painter: QPainter, sheet: QRectF, scale: float) -> None:
        """Shared sheet drawing for the workspace and vector PDF export."""
        self._sheet_pixels_per_mm = scale
        self._paper_rect = sheet
        inner = sheet.adjusted(
            self._settings.get("margin_left_mm", 25.0) * scale,
            self._settings.get("margin_top_mm", 10.0) * scale,
            -self._settings.get("margin_right_mm", 10.0) * scale,
            -self._settings.get("margin_bottom_mm", 10.0) * scale,
        )
        painter.setPen(QColor("#000000"))
        painter.drawRect(inner)
        self._draw_sheet_views(painter, inner, scale)
        if not self._suppress_sheet_annotations:
            self._draw_sheet_annotations(painter, scale)
        if self._settings.get("title_block_visible", True):
            self._draw_title_block(painter, inner, scale)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        background_painter = QPainter(self)
        background_painter.fillRect(self.rect(), QColor("#f6f8fa"))
        background_painter.end()
        weld_tool = getattr(self, "weld_tool", None)
        if weld_tool is not None and weld_tool.paint_drag():
            return
        if (self._annotation_background is not None
                and self._annotation_background.deviceIndependentSize() != self.size()):
            self._annotation_background = None
        if self._annotation_background is not None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.drawPixmap(0, 0, self._annotation_background)
            painter.setFont(self.font())
            self._draw_sheet_annotations(painter, self._sheet_pixels_per_mm)
            painter.end()
            return
        partial_annotation = self._annotation_partial_repaint
        self._annotation_partial_repaint = False
        model = getattr(self.window(), "model", None)
        model_key = (
            id(model), getattr(model, "revision", None),
            tuple((id(view), id(view.get("segments"))) for view in self._sheet_views),
        )
        if model_key != self._navigation_picture_model_key:
            self._navigation_picture_dirty = True
        direct_zoom = (
            not partial_annotation and self._navigating
            and self._navigation_picture is not None
            and self._zoom_factor != self._navigation_picture_zoom
        )
        if (not partial_annotation and not direct_zoom and self._navigating and self._navigation_picture is not None and self._navigation_pixmap is not None
                and self._navigation_picture_size == self.size()
                and not self._navigation_picture_dirty
                and self._navigation_picture_dpr == self.devicePixelRatioF()):
            painter = QPainter(self)
            ratio = self._zoom_factor / self._navigation_pixmap_zoom
            center = QPointF(self.width() / 2, self.height() / 2)
            offset = center + self._pan_offset - (center + self._navigation_pixmap_pan) * ratio
            margin = self._navigation_cache_margin
            target = QRectF(
                offset.x() - margin.x() * ratio, offset.y() - margin.y() * ratio,
                (self.width() + 2 * margin.x()) * ratio,
                (self.height() + 2 * margin.y()) * ratio,
            )
            if not target.contains(QRectF(self.rect())):
                # Refill the overscan cache from the vector recording when a
                # long pan or zoom reaches its edge, so it remains complete.
                pixmap = QPixmap(self._navigation_pixmap.size())
                pixmap.setDevicePixelRatio(self.devicePixelRatioF())
                pixmap.fill(Qt.GlobalColor.transparent)
                cache_painter = QPainter(pixmap)
                cache_painter.translate(margin)
                picture_ratio = self._zoom_factor / self._navigation_picture_zoom
                picture_offset = center + self._pan_offset - (center + self._navigation_picture_pan) * picture_ratio
                cache_painter.translate(picture_offset)
                cache_painter.scale(picture_ratio, picture_ratio)
                cache_painter.drawPicture(QPointF(), self._navigation_picture)
                cache_painter.end()
                self._navigation_pixmap = pixmap
                self._navigation_pixmap_zoom = self._zoom_factor
                self._navigation_pixmap_pan = QPointF(self._pan_offset)
                painter.drawPixmap(-margin, pixmap)
            else:
                if ratio != 1.0:
                    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(target, self._navigation_pixmap, QRectF(self._navigation_pixmap.rect()))
            return
        if (not partial_annotation and not direct_zoom and not self._navigation_picture_dirty and self._navigation_pixmap is not None
                and self._navigation_picture_size == self.size()
                and self._navigation_picture_dpr == self.devicePixelRatioF()
                and self._navigation_picture_zoom == self._zoom_factor
                and self._navigation_picture_pan == self._pan_offset):
            painter = QPainter(self)
            painter.drawPixmap(-self._navigation_cache_margin, self._navigation_pixmap)
            return
        paper_width, paper_height = self.paper_size_mm()
        margin_x = max(32.0, self.width() * 0.1)
        margin_y = max(32.0, self.height() * 0.1)
        available_width = max(0.0, self.width() - 2 * margin_x)
        available_height = max(0.0, self.height() - 2 * margin_y)
        base_scale = (
            min(available_width / paper_width, available_height / paper_height)
            if paper_width and paper_height else 0.0
        )
        scale = base_scale * self._zoom_factor
        self._sheet_pixels_per_mm = scale
        sheet_width = paper_width * scale
        sheet_height = paper_height * scale
        center = QPointF(self.width() / 2, self.height() / 2) + self._pan_offset
        sheet = QRectF(
            center.x() - sheet_width / 2,
            center.y() - sheet_height / 2,
            sheet_width,
            sheet_height,
        )
        self._paper_rect = sheet
        picture = None if direct_zoom or partial_annotation else QPicture()
        painter = QPainter(self if picture is None else picture)
        if not direct_zoom:
            painter.setFont(self.font())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(sheet.translated(0, 3), QColor("#d8dee4"))
        painter.fillRect(sheet, QColor("#ffffff"))
        painter.setPen(QColor("#d0d7de"))
        painter.drawRect(sheet)
        self.paint_sheet(painter, sheet, scale)
        painter.end()
        self._refresh_dragged_item_bounds()
        if direct_zoom or partial_annotation:
            return
        self._navigation_picture = picture
        self._navigation_picture_model_key = model_key
        self._navigation_picture_size = self.size()
        self._navigation_picture_zoom = self._zoom_factor
        self._navigation_picture_pan = QPointF(self._pan_offset)
        self._navigation_pixmap_zoom = self._zoom_factor
        self._navigation_pixmap_pan = QPointF(self._pan_offset)
        dpr = self.devicePixelRatioF()
        self._navigation_picture_dpr = dpr
        # Keep some offscreen content ready for pan/zoom, while bounding the
        # extra raster allocation on high-DPI or very large displays.
        pixel_count = max(1.0, self.width() * self.height() * dpr * dpr)
        cache_scale = max(1.0, min(1.5, math.sqrt((64 * 1024 * 1024 / 4) / pixel_count)))
        margin = QPointF(self.width() * (cache_scale - 1) / 2, self.height() * (cache_scale - 1) / 2)
        self._navigation_cache_margin = margin
        pixmap = QPixmap(round((self.width() + 2 * margin.x()) * dpr),
                         round((self.height() + 2 * margin.y()) * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        cache_painter = QPainter(pixmap)
        cache_painter.translate(margin)
        cache_painter.drawPicture(QPointF(), picture)
        cache_painter.end()
        self._navigation_pixmap = pixmap
        self._navigation_picture_dirty = False
        display_painter = QPainter(self)
        display_painter.drawPixmap(-margin, pixmap)

    def _refresh_dragged_item_bounds(self) -> None:
        """Keep invalidation origins aligned with the last frame actually painted."""
        if self._drag_dimension_index is not None:
            bounds = self._dimension_bounds.get(self._drag_dimension_index)
            if bounds is not None:
                self._drag_dimension_current_bounds = QRectF(bounds)
                self._drag_dimension_painted_bounds = QRectF(bounds)
            content_bounds = self._view_dimension_bounds.get(self._drag_dimension_index)
            if content_bounds is not None:
                self._drag_dimension_content_current_bounds = QRectF(content_bounds)
        if self._drag_identification_index is not None:
            index = self._selected_view_index
            if index is None:
                return
            for label_index in self._drag_identification_indices:
                bounds = self._identification_hit_rects.get((index, label_index))
                if bounds is not None:
                    self._drag_identification_current_bounds[label_index] = QRectF(bounds)
                    self._drag_identification_painted_bounds[label_index] = QRectF(bounds)
        if self._drag_view_index is not None:
            bounds = self._view_hit_rects.get(self._drag_view_index)
            if bounds is not None:
                self._drag_view_current_bounds = QRectF(bounds)
                self._drag_view_painted_bounds = QRectF(bounds)
        if self._drag_view_title_index is not None:
            bounds = self._view_title_hit_rects.get(self._drag_view_title_index)
            if bounds is not None:
                self._drag_title_current_bounds = QRectF(bounds)
                self._drag_title_painted_bounds = QRectF(bounds)
            frame = self._view_hit_rects.get(self._drag_view_title_index)
            if frame is not None:
                self._drag_title_frame_current_bounds = QRectF(frame)
                self._drag_title_frame_painted_bounds = QRectF(frame)
        for view_index, endpoint_key in self._drag_axis_endpoints:
            axis_key = endpoint_key.rsplit(":", 1)[0]
            bounds = self._axis_line_bounds.get((view_index, axis_key))
            if bounds is not None:
                self._drag_axis_current_bounds[(view_index, axis_key)] = QRectF(bounds)
                self._drag_axis_painted_bounds[(view_index, axis_key)] = QRectF(bounds)
            frame = self._view_hit_rects.get(view_index)
            if frame is not None:
                self._drag_axis_frame_current_bounds[view_index] = QRectF(frame)
                self._drag_axis_frame_painted_bounds[view_index] = QRectF(frame)

    def _finish_navigation(self) -> None:
        self._navigation_timer.stop()
        if self._navigating:
            self._navigating = False
            self._navigation_picture_dirty = True
            super().update()

    def _begin_sheet_annotation_drag(self) -> None:
        """Cache the unchanged sheet once; pointer moves paint only annotations."""
        self._finish_navigation()
        self._annotation_partial_repaint = False
        self._navigation_picture_dirty = True
        background = QPixmap(self.size() * self.devicePixelRatioF())
        background.setDevicePixelRatio(self.devicePixelRatioF())
        background.fill(QColor("#f6f8fa"))
        self._suppress_sheet_annotations = True
        try:
            self.render(background, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
        finally:
            self._suppress_sheet_annotations = False
            self._navigation_picture_dirty = True
        self._annotation_background = background

    def _update_annotation_regions(self, *regions: QRectF | QRegion | None) -> None:
        """Repaint only the old/new annotation area during pointer movement."""
        dirty = QRegion()
        for region in regions:
            if region is None:
                continue
            if isinstance(region, QRegion):
                dirty = dirty.united(region)
                continue
            if region.isNull():
                continue
            bounds = region.adjusted(-5.0, -5.0, 5.0, 5.0).intersected(QRectF(self.rect()))
            if not bounds.isEmpty():
                dirty = dirty.united(QRegion(bounds.toAlignedRect()))
        dirty = dirty.intersected(QRegion(self.rect()))
        if dirty.isEmpty():
            self.update()
            return
        # Keep disconnected old/new annotation and selection-frame edges as
        # separate dirty rectangles instead of repainting the large area
        # between them. Paint redraws vector content clipped to this region.
        self._annotation_partial_repaint = True
        super().update(dirty)

    def _view_frame_geometry(
        self,
        view_index: int,
        *,
        title_hit_rect: QRectF | None = None,
        axis_bounds_override: dict[str, QRectF] | None = None,
        identification_bounds_override: dict[int, QRectF] | None = None,
        dimension_bounds_override: dict[int, QRectF] | None = None,
        elevation_identifier_bounds_override: dict[int, QRectF] | None = None,
    ) -> tuple[QRectF, QRectF, QRectF] | None:
        """Predict content, auto-positioned title, and outline after a drag."""
        geometry = self._view_geometry_bounds.get(view_index)
        if geometry is None:
            return None
        content = QRectF(geometry)
        id_overrides = identification_bounds_override or {}
        for (label_view_index, label_index), hit_bounds in self._identification_hit_rects.items():
            if label_view_index == view_index:
                label_bounds = id_overrides.get(label_index, hit_bounds)
                content = content.united(label_bounds.adjusted(4.0, 3.0, -4.0, -3.0))
        dim_overrides = dimension_bounds_override or {}
        for (dimension_view_index, dimension_index), dimension_bounds in self._view_dimension_bounds.items():
            if dimension_view_index == view_index:
                content = content.united(dim_overrides.get(dimension_index, dimension_bounds))
        elevation_overrides = elevation_identifier_bounds_override or {}
        for (identifier_view_index, identifier_index), identifier_bounds in (
            self._elevation_identifier_bounds.items()
        ):
            if identifier_view_index == view_index:
                content = content.united(
                    elevation_overrides.get(identifier_index, identifier_bounds)
                )
        overrides = axis_bounds_override or {}
        for (axis_view_index, axis_key), axis_bounds in self._axis_line_bounds.items():
            if axis_view_index == view_index:
                content = content.united(overrides.get(axis_key, axis_bounds))
        for axis_key, axis_bounds in overrides.items():
            if (view_index, axis_key) not in self._axis_line_bounds:
                content = content.united(axis_bounds)
        painted_content = self._view_content_bounds.get(view_index, content)
        if title_hit_rect is None:
            painted_title = self._view_title_hit_rects.get(view_index)
            title_hit_rect = (
                painted_title.translated(0.0, content.bottom() - painted_content.bottom())
                if painted_title is not None else None
            )
        if title_hit_rect is not None:
            outer = content.united(title_hit_rect.adjusted(4.0, 3.0, -4.0, -3.0))
        else:
            outer = QRectF(content)
        frame = outer.adjusted(-5.0, -5.0, 5.0, 5.0).intersected(self._drawing_area)
        title_bounds = QRectF(title_hit_rect) if title_hit_rect is not None else QRectF()
        return content, title_bounds, frame

    @staticmethod
    def _frame_outline_regions(bounds: QRectF | None) -> tuple[QRectF, ...]:
        """Return thin strips covering the four sides of a selection frame."""
        if bounds is None or bounds.isNull() or bounds.isEmpty():
            return ()
        thickness = 8.0
        horizontal = min(thickness, bounds.height())
        vertical = min(thickness, bounds.width())
        return (
            QRectF(bounds.left(), bounds.top(), bounds.width(), horizontal),
            QRectF(bounds.left(), bounds.bottom() - horizontal, bounds.width(), horizontal),
            QRectF(bounds.left(), bounds.top(), vertical, bounds.height()),
            QRectF(bounds.right() - vertical, bounds.top(), vertical, bounds.height()),
        )

    def _dimension_screen_bounds(self, view_index: int, dimension: dict) -> QRectF | None:
        """Cheap conservative bounds for invalidating a moving dimension."""
        if dimension.get("kind") in {"angular", "level"}:
            layout = dimension_layout(self, view_index, dimension, self.font())
            return layout['bounds'] if layout else None
        try:
            first = tuple(float(value) for value in dimension["start"])
            second = tuple(float(value) for value in dimension["end"])
        except (KeyError, TypeError, ValueError):
            return None
        line_first, line_second = self._dimension_line_points(dimension)
        points = (
            self._screen_point(view_index, first),
            self._screen_point(view_index, second),
            self._screen_point(view_index, line_first),
            self._screen_point(view_index, line_second),
        )
        if any(point is None for point in points):
            return None
        bounds = QRectF(points[0], points[1]).normalized()
        for point in points[2:]:
            bounds = bounds.united(QRectF(point, point).adjusted(-1.0, -1.0, 1.0, 1.0))
        text_height = float(self._project_settings.get("dimension_text_height_mm", 3.0))
        padding = max(32.0, text_height * self._sheet_pixels_per_mm * 4.0 + 12.0)
        return bounds.adjusted(-padding, -padding, padding, padding)

    def _axis_bounds_at_positions(self, view_index: int, axis_key: str) -> QRectF | None:
        cached = self._view_axis_geometry.get(view_index)
        draw_data = self._view_draw_data.get(view_index)
        if cached is None or draw_data is None:
            return self._axis_line_bounds.get((view_index, axis_key))
        axis = next((item for item in cached[1] if item[0] == axis_key), None)
        if axis is None:
            return None
        _key, _label, start, end = axis
        center_x, center_y, target_x, target_y, model_to_pixels = draw_data
        positions = self._sheet_views[view_index].get("axis_label_positions", {})
        endpoints = []
        for end_name, default_fraction in (("start", 0.0), ("end", 1.0)):
            try:
                fraction = float(positions.get(f"{axis_key}:{end_name}", default_fraction))
            except (TypeError, ValueError):
                fraction = default_fraction
            point = (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
            endpoints.append(QPointF(
                target_x + (point[0] - center_x) * model_to_pixels,
                target_y - (point[1] - center_y) * model_to_pixels,
            ))
        radius = max(0.5, 4.0 * self._sheet_pixels_per_mm) + 3.0
        return QRectF(endpoints[0], endpoints[1]).normalized().adjusted(
            -radius, -radius, radius, radius,
        )

    def _begin_navigation(self) -> None:
        if (self._navigation_picture is not None and self._navigation_picture_size == self.size()
                and self._navigation_picture_dpr == self.devicePixelRatioF()
                and not self._navigation_picture_dirty):
            self._navigating = True
            self._navigation_timer.start()

    def _ensure_navigation_geometry(self) -> None:
        if self._navigating:
            self._finish_navigation()
        if (self._navigation_picture is not None
                and (self._navigation_picture_zoom != self._zoom_factor
                     or self._navigation_picture_pan != self._pan_offset
                     or self._navigation_picture_size != self.size())):
            self.repaint()

    def _draw_sheet_views(self, painter: QPainter, inner: QRectF, scale: float) -> None:
        if not self._sheet_views:
            self._view_hit_rects = {}
            self._view_geometry_bounds = {}
            self._view_content_bounds = {}
            self._view_dimension_bounds = {}
            self._view_title_hit_rects = {}
            self._component_group_hit_rects = {}
            self._component_group_title_hit_rects = {}
            self._identification_resize_handles = {}
            self._identification_hit_rects = {}
            self._detail_identifier_hit_rects = {}
            self._detail_identifier_handle_hit_rects = {}
            self._elevation_identifier_hit_rects = {}
            self._elevation_identifier_bounds = {}
            self._axis_endpoint_hit_rects = {}
            self._axis_line_bounds = {}
            self._axis_endpoint_drag_data = {}
            self._axis_dimension_snap_segments = {}
            self._dimension_text_hit_rects = {}
            self._dimension_endpoint_hit_rects = {}
            self._dimension_bounds = {}
            self._view_draw_data = {}
            self._drawing_area = inner
            self._stamp_rect = self._title_block_rect(inner, scale)
            return
        drawing_area = inner
        self._drawing_area = drawing_area
        self._stamp_rect = self._title_block_rect(inner, scale)
        if drawing_area.width() <= 0 or drawing_area.height() <= 0:
            return
        self._view_hit_rects = {}
        self._view_geometry_bounds = {}
        self._view_content_bounds = {}
        self._view_dimension_bounds = {}
        self._view_title_hit_rects = {}
        self._component_group_hit_rects = {}
        self._component_group_title_hit_rects = {}
        self._identification_resize_handles = {}
        self._identification_hit_rects = {}
        self._detail_identifier_hit_rects = {}
        self._detail_identifier_handle_hit_rects = {}
        self._elevation_identifier_hit_rects = {}
        self._elevation_identifier_bounds = {}
        self._dimension_text_hit_rects = {}
        self._dimension_endpoint_hit_rects = {}
        self._dimension_bounds = {}
        self._view_draw_data = {}
        self._axis_endpoint_hit_rects = {}
        self._axis_line_bounds = {}
        self._axis_endpoint_drag_data = {}
        self._axis_dimension_snap_segments = {}
        painter.save()
        painter.setClipRect(inner)
        pen = painter.pen()
        pen.setColor(QColor("#000000"))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        base_font = painter.font()
        grouped_view_indices: dict[str, list[int]] = {}
        for index, view in enumerate(self._sheet_views):
            metadata = view.get("component_detail_group")
            if (
                view.get("segments")
                and isinstance(metadata, dict)
                and metadata.get("id")
            ):
                grouped_view_indices.setdefault(str(metadata["id"]), []).append(index)
        group_slots: dict[int, tuple[int, int]] = {}
        for indices in grouped_view_indices.values():
            for slot, index in enumerate(indices):
                group_slots[index] = (slot, len(indices))
        for index, view in enumerate(self._sheet_views):
            segments = self._display_linework(view)[0]
            if not segments:
                continue
            owners = self._display_linework(view)[1]
            hidden_owners = {str(owner) for owner in view.get("hidden_owners", ())}
            symbols = self._member_break_symbols(view)
            symbol_segments = {segment for lines in symbols.values() for segment in lines}
            hidden_key = tuple(sorted(hidden_owners))
            cached = self._view_linework.get(index)
            if cached is None or cached[0] is not segments or cached[1] != hidden_key:
                path = QPainterPath()
                hidden_path = QPainterPath()
                points = []
                hidden_points = []
                # Keep the view's origin fixed when a break trims an end.
                source_points = [point for segment in view.get("segments", ()) for point in segment]
                min_x = min(point[0] for point in source_points)
                max_x = max(point[0] for point in source_points)
                min_y = min(point[1] for point in source_points)
                max_y = max(point[1] for point in source_points)
                for segment_index, (start, end) in enumerate(segments):
                    if symbol_segments and (tuple(start), tuple(end)) in symbol_segments:
                        continue
                    x1, y1 = float(start[0]), float(start[1])
                    x2, y2 = float(end[0]), float(end[1])
                    owner = str(owners[segment_index]) if len(owners) == len(segments) else ""
                    target_path = hidden_path if owner in hidden_owners else path
                    target_points = hidden_points if owner in hidden_owners else points
                    if x1 == x2 and y1 == y2:
                        target_points.append(QPointF(x1, y1))
                    else:
                        target_path.moveTo(x1, y1)
                        target_path.lineTo(x2, y2)
                cached = (
                    segments, hidden_key, path, hidden_path, points, hidden_points,
                    (min_x, max_x, min_y, max_y),
                )
                self._view_linework[index] = cached
            _, _, path, hidden_path, points, hidden_points, (min_x, max_x, min_y, max_y) = cached
            center_x = (min_x + max_x) / 2.0
            center_y = (min_y + max_y) / 2.0
            position = view.get("position")
            if position is None:
                columns = min(2, len(self._sheet_views))
                rows = (len(self._sheet_views) + columns - 1) // columns
                position = (
                    (index % columns + 0.5) / columns,
                    (index // columns + 0.5) / rows,
                )
                view["position"] = position
            group = view.get("component_detail_group")
            if isinstance(group, dict) and group.get("id"):
                group_position = group.get("group_position", (0.5, 0.53))
                offset_index, view_count = group_slots.get(
                    index, (int(group.get("offset", 0)), max(1, int(group.get("view_count", 6)))),
                )
                extra_offset = group.get("offset_delta", (0.0, 0.0))
                paper_offset = group.get("paper_offset_mm")
                slot_offset = (offset_index - (view_count - 1) / 2.0) * 0.13 if paper_offset is None else 0.
                target_x = drawing_area.left() + (
                    float(group_position[0]) + slot_offset + float(extra_offset[0])
                ) * drawing_area.width()
                if paper_offset is not None:
                    target_x += float(paper_offset[0]) * scale
                target_y = drawing_area.top() + (
                    float(group_position[1]) + float(extra_offset[1])
                ) * drawing_area.height()
                if paper_offset is not None:
                    target_y += float(paper_offset[1]) * scale
            else:
                target_x = drawing_area.left() + float(position[0]) * drawing_area.width()
                target_y = drawing_area.top() + float(position[1]) * drawing_area.height()
            model_to_sheet = 1000.0 / max(1.0, float(view.get("scale_denominator", 100.0)))
            model_to_pixels = model_to_sheet * scale
            frame = QRectF(
                target_x - (max_x - min_x) * model_to_pixels / 2.0,
                target_y - (max_y - min_y) * model_to_pixels / 2.0,
                max(2.0, (max_x - min_x) * model_to_pixels),
                max(2.0, (max_y - min_y) * model_to_pixels),
            )
            self._view_geometry_bounds[index] = QRectF(frame)
            name_font = QFont(painter.font())
            name_font.setPixelSize(max(
                1,
                round(float(self._project_settings.get("view_name_text_height_mm", 4.0)) * scale),
            ))
            scale_font = QFont(painter.font())
            scale_font.setPixelSize(max(
                1,
                round(float(self._project_settings.get("view_scale_text_height_mm", 3.0)) * scale),
            ))
            name_metrics = QFontMetrics(name_font)
            scale_metrics = QFontMetrics(scale_font)
            view_name = str(view.get("name", "Vista"))
            view_scale_label = f"Escala 1:{float(view.get('scale_denominator', 100.0)):g}"
            name_width = name_metrics.horizontalAdvance(view_name)
            scale_width = scale_metrics.horizontalAdvance(view_scale_label)
            view_bounds = QRectF(frame)
            self._view_draw_data[index] = (
                center_x, center_y, target_x, target_y, model_to_pixels,
            )
            identification_rects = []
            for identification_index, identification in enumerate(view.get("identifications", ())):
                if not isinstance(identification, dict):
                    continue
                projected = identification.get("projected_point")
                if projected is None:
                    projected = self._project_world_point(
                        view, identification.get("world_point", ()),
                    )
                try:
                    projected_x, projected_y = (float(value) for value in projected)
                except (TypeError, ValueError):
                    continue
                text = str(identification.get("text", "")).strip()
                raw_runs = identification.get("text_runs")
                if not isinstance(raw_runs, (list, tuple)) or not raw_runs:
                    old_lines = identification.get("text_lines")
                    if not isinstance(old_lines, (list, tuple)) or not old_lines:
                        old_lines = (text,)
                    raw_runs = [[{"text": line, "role": "element"}] for line in old_lines]
                rendered_lines = []
                for raw_line in raw_runs:
                    if not isinstance(raw_line, (list, tuple)):
                        continue
                    rendered_runs = []
                    line_width = line_height = line_ascent = 0
                    for raw_run in raw_line:
                        if not isinstance(raw_run, dict):
                            continue
                        run_text = str(raw_run.get("text", ""))
                        if not run_text:
                            continue
                        role = str(raw_run.get("role", "element"))
                        key = (
                            "view_section_text_height_mm"
                            if role == "section" else "view_element_text_height_mm"
                        )
                        default_height = 2.5 if role == "section" else 3.0
                        run_font = QFont(painter.font())
                        run_font.setPixelSize(max(
                            1,
                            round(float(self._project_settings.get(key, default_height)) * scale),
                        ))
                        run_metrics = QFontMetrics(run_font)
                        rendered_runs.append((run_text, run_font, run_metrics))
                        line_width += run_metrics.horizontalAdvance(run_text)
                        line_height = max(line_height, run_metrics.height())
                        line_ascent = max(line_ascent, run_metrics.ascent())
                    if rendered_runs:
                        rendered_lines.append((rendered_runs, line_width, line_height, line_ascent))
                if not rendered_lines:
                    continue
                anchor_x = target_x + (projected_x - center_x) * model_to_pixels
                baseline_y = target_y - (projected_y - center_y) * model_to_pixels
                text_width = max(line[1] for line in rendered_lines)
                top = -rendered_lines[0][3]
                total_height = sum(line[2] for line in rendered_lines)
                bottom = total_height - rendered_lines[0][3]
                document = None
                if "width_mm" in identification:
                    # Physical layout units keep wrapping identical at every zoom.
                    dpi_scale = self._sheet_text_layout_device.logicalDpiY() / 25.4
                    document = QTextDocument()
                    document.documentLayout().setPaintDevice(self._sheet_text_layout_device)
                    document.setUseDesignMetrics(True)
                    document.setDocumentMargin(0)
                    cursor = QTextCursor(document)
                    block = QTextBlockFormat()
                    block.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                    cursor.setBlockFormat(block)
                    if identification.get("unwrapped_text") is not None:
                        raw_runs = [[{"text": identification["unwrapped_text"], "role": "element"}]]
                    for line_index, raw_line in enumerate(raw_runs):
                        if line_index:
                            cursor.insertBlock(block)
                        for run in raw_line:
                            role = run.get("role", "element")
                            height = float(self._project_settings.get(
                                "view_section_text_height_mm" if role == "section" else "view_element_text_height_mm",
                                2.5 if role == "section" else 3.))
                            font = QFont(painter.font())
                            font.setPointSizeF(height * 72 / 25.4)
                            fmt = QTextCharFormat()
                            fmt.setFont(font)
                            cursor.insertText(str(run.get("text", "")), fmt)
                    text_width = max(5., float(identification["width_mm"])) * scale
                    document.setTextWidth(text_width / scale * dpi_scale)
                    bottom = top + max(float(identification.get("height_mm", 0.))*scale,
                                       document.size().height()/dpi_scale*scale)
                anchor = QPointF(anchor_x, baseline_y)
                rotation = float(identification.get("text_rotation_degrees", 0.0))
                label_rect = self._rotated_text_rect(
                    anchor, text_width, top, bottom, rotation,
                )
                identification_rects.append(
                    (identification_index, anchor, rendered_lines, text_width, label_rect, rotation, document, top, bottom)
                )
                self._identification_hit_rects[(index, identification_index)] = label_rect.adjusted(
                    -4.0, -3.0, 4.0, 3.0,
                )
                view_bounds = view_bounds.united(label_rect)
            painter.save()
            painter.translate(target_x, target_y)
            painter.scale(model_to_pixels, -model_to_pixels)
            painter.translate(-center_x, -center_y)
            painter.drawPath(path)
            if points:
                painter.drawPoints(points)
            for mark_index, lines in symbols.items():
                mark = view["member_breaks"][mark_index]
                if mark["owner"] in hidden_owners:
                    continue
                selected = self._selected_member_break == (index, mark_index)
                symbol_pen = QPen(QColor("#ff0000"), 2.0 if selected else 1.2)
                symbol_pen.setCosmetic(True)
                painter.setPen(symbol_pen)
                for first, last in lines:
                    painter.drawLine(QPointF(*first), QPointF(*last))
                if selected:
                    painter.setBrush(QColor("#ffffff"))
                    radius = 3.0 / model_to_pixels
                    for point in (lines[0][0], lines[-1][1]):
                        painter.drawEllipse(QPointF(*point), radius, radius)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._element_visibility_mode == "reveal":
                hidden_pen = QPen(QColor("#afb8c1"), 1.0)
                hidden_pen.setCosmetic(True)
                painter.setPen(hidden_pen)
                painter.drawPath(hidden_path)
                if hidden_points:
                    painter.drawPoints(hidden_points)
            painter.restore()
            visibility_highlight_owners = set(self._hover_owners)
            if (
                self._element_visibility_mode in {"hide", "reveal"}
                and self._element_visibility_pending_view_index == index
            ):
                visibility_highlight_owners.update(
                    (index, owner) for owner in self._element_visibility_pending
                )
            if (
                (self._identification_mode or self._member_break_mode
                 or self._element_visibility_mode in {"hide", "reveal"})
                and visibility_highlight_owners and len(owners) == len(segments)
            ):
                for segment_index, (start, end) in enumerate(segments):
                    if symbol_segments and (tuple(start), tuple(end)) in symbol_segments:
                        continue
                    owner = str(owners[segment_index])
                    if (index, owner) not in visibility_highlight_owners:
                        continue
                    if (
                        self._element_visibility_mode == "hide" and owner in hidden_owners
                    ) or (
                        self._element_visibility_mode == "reveal" and owner not in hidden_owners
                    ):
                        continue
                    start_screen = QPointF(
                        target_x + (float(start[0]) - center_x) * model_to_pixels,
                        target_y - (float(start[1]) - center_y) * model_to_pixels,
                    )
                    end_screen = QPointF(
                        target_x + (float(end[0]) - center_x) * model_to_pixels,
                        target_y - (float(end[1]) - center_y) * model_to_pixels,
                    )
                    hover_pen = QPen(QColor("#0969da"), 2.5)
                    hover_pen.setCosmetic(True)
                    painter.setPen(hover_pen)
                    painter.drawLine(start_screen, end_screen)
                    painter.setPen(pen)
            if view.get("axes_visible", False):
                axes_bounds = self._draw_view_axes(painter, view, index, scale)
                if axes_bounds is not None:
                    view_bounds = view_bounds.united(axes_bounds)
            for dimension_index, dimension in enumerate(view.get("dimensions", ())):
                dimension_bounds = self._draw_dimension(
                    painter, index, dimension, dimension_index,
                )
                if dimension_bounds is not None:
                    view_bounds = view_bounds.united(dimension_bounds)
                    self._view_dimension_bounds[(index, dimension_index)] = QRectF(dimension_bounds)
            for identifier_index, identifier in enumerate(view.get("detail_identifiers", ())):
                if not isinstance(identifier, dict):
                    continue
                identifier_bounds = self._draw_detail_identifier(
                    painter, index, identifier, identifier_index,
                )
                if identifier_bounds is not None:
                    view_bounds = view_bounds.united(identifier_bounds)
            for identifier_index, identifier in enumerate(view.get("elevation_identifiers", ())):
                if not isinstance(identifier, dict):
                    continue
                identifier_bounds = self._draw_elevation_identifier(
                    painter, index, identifier, identifier_index,
                )
                if identifier_bounds is not None:
                    view_bounds = view_bounds.united(identifier_bounds)
            if (
                self._elevation_identifier_mode
                and self._elevation_identifier_view_index == index
                and self._elevation_identifier_point is not None
                and self._elevation_identifier_preview_direction is not None
            ):
                preview = {
                    "name": self._next_elevation_identifier_name(),
                    "point": self._elevation_identifier_point,
                    "direction": self._elevation_identifier_preview_direction,
                }
                preview_bounds = self._draw_elevation_identifier(painter, index, preview, None)
                if preview_bounds is not None:
                    view_bounds = view_bounds.united(preview_bounds)
            if (
                self._detail_identifier_mode
                and self._detail_identifier_view_index == index
                and self._detail_identifier_center is not None
                and self._detail_identifier_preview_radius > 1e-9
            ):
                preview = self._make_detail_identifier(
                    view,
                    self._next_detail_identifier_name(),
                    self._detail_identifier_center,
                    self._detail_identifier_preview_radius,
                )
                preview_bounds = self._draw_detail_identifier(painter, index, preview, None)
                if preview_bounds is not None:
                    view_bounds = view_bounds.united(preview_bounds)
            if (
                self._detail_identifier_mode
                and self._detail_identifier_view_index == index
                and self._detail_identifier_snap_screen is not None
            ):
                symbol = self._snap_symbol_pixmaps.get(self._detail_identifier_snap_kind)
                if symbol is not None:
                    painter.drawPixmap(
                        round(self._detail_identifier_snap_screen.x() - symbol.width() / 2),
                        round(self._detail_identifier_snap_screen.y() - symbol.height() / 2),
                        symbol,
                    )
            if hasattr(self, "weld_tool"):
                weld_bounds = self.weld_tool.draw(painter, index)
                if not weld_bounds.isEmpty():
                    view_bounds = view_bounds.united(weld_bounds)
            self._view_content_bounds[index] = QRectF(view_bounds)
            label_offset = view.get("label_offset_mm", (0.0, 0.0))
            try:
                label_offset_x, label_offset_y = (float(value) for value in label_offset)
            except (TypeError, ValueError):
                label_offset_x = label_offset_y = 0.0
            label_left = frame.left() + label_offset_x * scale
            label_top = view_bounds.bottom() + 2.0 * scale + label_offset_y * scale
            name_label_rect = QRectF(
                label_left, label_top, name_width, name_metrics.height(),
            )
            scale_label_rect = QRectF(
                label_left, label_top + name_metrics.height(),
                scale_width, scale_metrics.height(),
            )
            self._view_title_hit_rects[index] = name_label_rect.united(scale_label_rect).adjusted(
                -4.0, -3.0, 4.0, 3.0,
            )
            view_bounds = view_bounds.united(name_label_rect).united(scale_label_rect)
            if self._dimension_mode and index == self._dimension_hover_view_index:
                preview = None
                if self._dimension_type in {"angular", "level"}:
                    preview = self._dimension_preview
                elif (
                    len(self._dimension_points) == 1
                    and self._dimension_hover_projected is not None
                ):
                    preview = {
                        "start": self._dimension_points[0],
                        "end": self._dimension_hover_projected,
                        "offset": (0.0, 0.0),
                    }
                elif len(self._dimension_points) == 2:
                    preview = self._dimension_preview
                if preview is not None:
                    painter.save()
                    painter.setOpacity(0.58)
                    self._draw_dimension(painter, index, preview)
                    painter.restore()
                if self._dimension_snap_screen is not None:
                    symbol = self._snap_symbol_pixmaps.get(self._dimension_snap_kind)
                    if symbol is not None:
                        painter.drawPixmap(
                            round(self._dimension_snap_screen.x() - symbol.width() / 2),
                            round(self._dimension_snap_screen.y() - symbol.height() / 2),
                            symbol,
                        )
            painter.setPen(QColor("#000000"))
            painter.setFont(name_font)
            painter.drawText(
                QPointF(name_label_rect.left(), name_label_rect.top() + name_metrics.ascent()),
                view_name,
            )
            painter.setFont(scale_font)
            painter.drawText(
                QPointF(scale_label_rect.left(), scale_label_rect.top() + scale_metrics.ascent()),
                view_scale_label,
            )
            if self._selected_view_title_index == index:
                painter.save()
                title_selection_pen = QPen(QColor("#0969da"), 1.5)
                title_selection_pen.setCosmetic(True)
                painter.setPen(title_selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(name_label_rect.united(scale_label_rect).adjusted(
                    -3.0, -2.0, 3.0, 2.0,
                ))
                painter.restore()
            for identification_index, anchor, lines, text_width, label_rect, rotation, document, top, bottom in identification_rects:
                if (
                    index == self._selected_view_index
                    and identification_index in self._selected_identification_indices
                ):
                    selection_pen = QPen(QColor("#0969da"), 1.5)
                    selection_pen.setCosmetic(True)
                    painter.setPen(selection_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(label_rect.adjusted(-3.0, -2.0, 3.0, 2.0))
                    transform = QTransform().translate(anchor.x(), anchor.y()).rotate(rotation)
                    corner = transform.map(QPointF(text_width/2, bottom))
                    handle = QRectF(corner.x()-4, corner.y()-4, 8, 8)
                    painter.setBrush(QColor("#ffffff"))
                    painter.drawRect(handle)
                    self._identification_resize_handles[(index, identification_index)] = (
                        handle.adjusted(-3, -3, 3, 3), text_width/scale, (bottom-top)/scale)
                    painter.setPen(QColor("#000000"))
                painter.save()
                painter.translate(anchor)
                painter.rotate(rotation)
                if document is not None:
                    painter.translate(-text_width/2, top)
                    painter.scale(scale/dpi_scale, scale/dpi_scale)
                    document.drawContents(painter)
                    painter.restore()
                    continue
                baseline_offset = 0
                for rendered_runs, line_width, line_height, _line_ascent in lines:
                    run_x = -line_width / 2.0
                    for run_text, run_font, run_metrics in rendered_runs:
                        painter.setFont(run_font)
                        painter.drawText(QPointF(run_x, baseline_offset), run_text)
                        run_x += run_metrics.horizontalAdvance(run_text)
                    baseline_offset += line_height
                painter.restore()
            view_bounds = view_bounds.adjusted(-5.0, -5.0, 5.0, 5.0).intersected(inner)
            self._view_hit_rects[index] = view_bounds
            if index == self._selected_view_index:
                selection_pen = QPen(QColor("#0969da"), 2.0)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(view_bounds)
                painter.setPen(pen)
            painter.setFont(base_font)
            painter.setPen(pen)
        groups: dict[str, list[int]] = {}
        group_data: dict[str, dict] = {}
        for index, view in enumerate(self._sheet_views):
            metadata = view.get("component_detail_group")
            if not isinstance(metadata, dict) or not metadata.get("id"):
                continue
            group_id = str(metadata["id"])
            groups.setdefault(group_id, []).append(index)
            group_data[group_id] = metadata
        for group_id, indices in groups.items():
            bounds = QRectF()
            for index in indices:
                view_bounds = self._view_hit_rects.get(index)
                if view_bounds is not None:
                    bounds = bounds.united(view_bounds)
            metadata = group_data[group_id]
            label_position = metadata.get("label_position", (0.5, 0.40))
            title_font = QFont(base_font)
            title_font.setPixelSize(max(1, round(4.0 * scale)))
            title_metrics = QFontMetrics(title_font)
            title = str(metadata.get("title", "Componente"))
            group_position = metadata.get("group_position", (0.5, 0.53))
            title_x = (
                bounds.center().x()
                + (float(label_position[0]) - float(group_position[0])) * drawing_area.width()
                - title_metrics.horizontalAdvance(title) / 2.0
            )
            title_y = drawing_area.top() + float(label_position[1]) * drawing_area.height()
            title_rect = QRectF(
                title_x, title_y, title_metrics.horizontalAdvance(title), title_metrics.height(),
            )
            self._component_group_title_hit_rects[group_id] = title_rect.adjusted(-4, -3, 4, 3)
            bounds = bounds.united(title_rect)
            if bounds.isNull():
                continue
            bounds = self._stable_component_group_frame(group_id, indices, bounds, inner, scale)
            self._component_group_hit_rects[group_id] = bounds
            painter.save()
            frame_pen = QPen(QColor("#000000"), 1.0, Qt.PenStyle.DashLine)
            frame_pen.setCosmetic(True)
            painter.setPen(frame_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(bounds)
            painter.setFont(title_font)
            painter.setPen(QColor("#000000"))
            painter.drawText(
                QPointF(title_rect.left(), title_rect.top() + title_metrics.ascent()), title,
            )
            if self._selected_component_detail_group == group_id:
                selection_pen = QPen(QColor("#0969da"), 2.0)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.drawRect(bounds.adjusted(-3, -3, 3, 3))
            painter.restore()
        painter.restore()

    def _draw_sheet_annotations(self, painter: QPainter, scale: float) -> None:
        self._sheet_line_handle_hit_rects = {}
        self._sheet_text_hit_rects = {}
        self._sheet_text_handle_hit_rects = {}
        self._sheet_line_hit_rects = {}
        for view_index, view in enumerate(self._sheet_views):
            for text_index, annotation in enumerate(view.get("sheet_texts", ())):
                self._draw_sheet_text(painter, annotation, view_index, text_index, scale)
            for line_index, annotation in enumerate(view.get("sheet_lines", ())):
                self._draw_sheet_line(painter, annotation, view_index, line_index)
        for text_index, annotation in enumerate(self._sheet_texts):
            self._draw_sheet_text(painter, annotation, None, text_index, scale)
        for line_index, annotation in enumerate(self._sheet_lines):
            self._draw_sheet_line(painter, annotation, None, line_index)
        if self._annotation_mode in {"line", "rectangle", "circle"} and self._line_start_context is not None:
            view_index, start = self._line_start_context
            start_screen = self._sheet_annotation_screen_point({"anchor": start}, view_index)
            end_screen = self._line_preview_screen_endpoint
            if start_screen is not None and end_screen is not None:
                pen = QPen(QColor("#000000"), 1.0)
                pen.setCosmetic(True)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.save()
                painter.setPen(pen)
                self._draw_annotation_geometry(painter, self._annotation_mode, start_screen, end_screen)
                symbol = self._snap_symbol_pixmaps.get(self._line_preview_snap_kind)
                if symbol is not None and self._line_preview_snap_screen is not None:
                    painter.drawPixmap(
                        round(self._line_preview_snap_screen.x() - symbol.width() / 2),
                        round(self._line_preview_snap_screen.y() - symbol.height() / 2),
                        symbol,
                    )
                painter.restore()
        elif self._annotation_mode in {"line", "rectangle", "circle"} and self._line_preview_snap_screen is not None:
            symbol = self._snap_symbol_pixmaps.get(self._line_preview_snap_kind)
            if symbol is not None:
                painter.drawPixmap(
                    round(self._line_preview_snap_screen.x() - symbol.width() / 2),
                    round(self._line_preview_snap_screen.y() - symbol.height() / 2),
                    symbol,
                )

        self._draw_sheet_tables(painter, scale)

    def _draw_sheet_tables(self, painter: QPainter, scale: float) -> None:
        self._sheet_table_hit_rects = {}
        if scale <= 1e-12 or self._drawing_area.isEmpty():
            return
        width_mm = min(175.0, self._drawing_area.width() / scale)
        stack_height = 0.0
        for index, table in enumerate(self._settings.get("tables", ())):
            kind = table.get("kind")
            if kind not in {"sheet_revisions", "project_revisions", "steel_profiles", "steel_plates", "accessories"}:
                continue
            if kind == "steel_profiles":
                rows = self.steel_profile_rows_provider()
            elif kind == "steel_plates":
                rows = self.steel_plate_rows_provider()
            elif kind == "accessories":
                rows = self.accessory_rows_provider()
            else:
                rows = revision_rows_for(self._settings, self._project_settings, kind)
            font = QFont(self.font())
            if kind == "accessories":
                fields = ("name", "quantity")
            elif kind in {"steel_profiles", "steel_plates"}:
                fields = ("profile", "plate", "family", "geometry", "material", "linear_mass", "length", "total_mass")
            else:
                fields = ("number", "change", "responsible", "date")
            signature = (kind, width_mm, font.toString(),
                         tuple(tuple(row.get(key, "") for key in fields) for row in rows))
            cached = self._sheet_table_layouts.get(index)
            if cached is None or cached[0] != signature:
                if kind == "steel_profiles":
                    layout = SteelProfilesTableLayout(rows, width_mm, font)
                elif kind == "steel_plates":
                    layout = SteelPlatesTableLayout(rows, width_mm, font)
                elif kind == "accessories":
                    layout = AccessoriesTableLayout(rows, width_mm, font)
                else:
                    layout = RevisionTableLayout(kind, rows, width_mm, font)
                self._sheet_table_layouts[index] = (signature, layout)
            else:
                layout = cached[1]
            origin = self._sheet_annotation_screen_point({"anchor": table.get("position")}, None)
            if origin is None:
                left = self._drawing_area.right() - width_mm * scale
                if self._settings.get("title_block_visible", True) and self._settings.get("title_block_position") == "Superior":
                    top = self._stamp_rect.bottom() + (3.0 + stack_height) * scale
                else:
                    bottom = self._stamp_rect.top() if not self._stamp_rect.isEmpty() else self._drawing_area.bottom()
                    top = max(self._drawing_area.top(), bottom - (3.0 + stack_height + layout.height_mm) * scale)
                origin = QPointF(left, top)
            stack_height += layout.height_mm + 3.0
            layout.draw(painter, origin, scale)
            bounds = QRectF(origin.x(), origin.y(), layout.width_mm * scale, layout.height_mm * scale)
            self._sheet_table_hit_rects[index] = bounds
            if self._selected_sheet_table == index:
                painter.save()
                pen = QPen(QColor("#0969da"), 1.5)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(bounds.adjusted(-3, -3, 3, 3))
                painter.restore()

    def delete_selected_sheet_table(self) -> bool:
        if self._selected_sheet_table is None:
            return False
        tables = self._settings.get("tables", [])
        index = self._selected_sheet_table
        if 0 <= index < len(tables):
            tables.pop(index)
        self._selected_sheet_table = None
        self._sheet_table_layouts.clear()
        self.update()
        self.layout_changed.emit()
        return True

    def _draw_sheet_text(
        self, painter: QPainter, annotation: dict, view_index: int | None,
        text_index: int, scale: float,
    ) -> None:
        if annotation.get("kind") == "image":
            self._draw_sheet_image(painter, annotation, view_index, text_index, scale)
            return
        anchor = self._sheet_annotation_screen_point(annotation, view_index)
        if anchor is None:
            return
        try:
            width_mm = max(10.0, float(annotation.get("width_mm", 50.0)))
            height_mm = max(5.0, float(annotation.get("height_mm", 25.0)))
            text_height_mm = max(0.5, float(annotation.get("text_height_mm", 3.0)))
        except (TypeError, ValueError):
            return
        rect = QRectF(anchor.x(), anchor.y(), width_mm * scale, height_mm * scale)
        font = QFont(painter.font())
        # Lay out once in physical sheet units. Zoom only transforms the painter;
        # rounding the font to screen pixels would change wrapping at each zoom.
        font.setPointSizeF(text_height_mm * 72.0 / 25.4)
        layout_pixels_per_mm = self._sheet_text_layout_device.logicalDpiY() / 25.4
        document_rect = QRectF(0.0, 0.0, width_mm * layout_pixels_per_mm,
                              height_mm * layout_pixels_per_mm)
        key = (view_index if view_index is not None else -1, text_index)
        html = str(annotation.get("html", ""))
        signature = (html, font.toString(), width_mm)
        cached = self._sheet_text_documents.get(key)
        if cached is not None and cached[0] == signature:
            document = cached[1]
        else:
            document = QTextDocument()
            document.documentLayout().setPaintDevice(self._sheet_text_layout_device)
            document.setUseDesignMetrics(True)
            document.setDocumentMargin(0)
            document.setDefaultFont(font)
            document.setHtml(html)
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.SelectionType.Document)
            fixed_size = QTextCharFormat()
            fixed_size.setFontPointSize(font.pointSizeF())
            cursor.mergeCharFormat(fixed_size)
            document.setTextWidth(document_rect.width())
            self._sheet_text_documents[key] = (signature, document)
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.topLeft())
        painter.scale(scale / layout_pixels_per_mm, scale / layout_pixels_per_mm)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(QColor("#000000"))
        document.drawContents(painter, document_rect)
        painter.restore()
        self._draw_sheet_annotation_frame(painter, rect, view_index, text_index)

    def _draw_sheet_image(self, painter, annotation, view_index, text_index, scale):
        anchor = self._sheet_annotation_screen_point(annotation, view_index)
        if anchor is None:
            return
        data = annotation.get("image_data", "")
        image = self._sheet_image_cache.get(data)
        if image is None:
            image = QImage()
            try:
                image.loadFromData(base64.b64decode(data, validate=True))
            except (ValueError, TypeError):
                return
            if image.isNull():
                return
            self._sheet_image_cache[data] = image
        rect = QRectF(anchor.x(), anchor.y(), max(1., float(annotation.get("width_mm", 50.)))*scale,
                      max(1., float(annotation.get("height_mm", 25.)))*scale)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, image)
        painter.restore()
        self._draw_sheet_annotation_frame(painter, rect, view_index, text_index)

    def _draw_sheet_annotation_frame(self, painter, rect, view_index, text_index):
        key = (view_index if view_index is not None else -1, text_index)
        self._sheet_text_hit_rects[key] = rect.adjusted(-3.0, -3.0, 3.0, 3.0)
        if self._selected_sheet_text == key:
            painter.save()
            selection_pen = QPen(QColor("#0969da"), 1.5)
            selection_pen.setCosmetic(True)
            painter.setPen(selection_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            handle = QRectF(rect.right() - 4.0, rect.bottom() - 4.0, 8.0, 8.0)
            painter.setBrush(QColor("#ffffff"))
            painter.drawRect(handle)
            self._sheet_text_handle_hit_rects[key] = handle.adjusted(-4.0, -4.0, 4.0, 4.0)
            painter.restore()

    @staticmethod
    def _draw_annotation_geometry(painter, kind, first, second) -> None:
        if kind == "rectangle":
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(first, second).normalized())
        elif kind == "circle":
            radius = math.hypot(second.x() - first.x(), second.y() - first.y())
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(first, radius, radius)
        else:
            painter.drawLine(first, second)

    def _annotation_screen_primitives(self, annotation, view_index):
        try:
            first, second = annotation["points"]
            first = self._sheet_annotation_screen_point({"anchor": first}, view_index)
            second = self._sheet_annotation_screen_point({"anchor": second}, view_index)
        except (KeyError, TypeError, ValueError):
            return (), ()
        if first is None or second is None:
            return (), ()
        kind = annotation.get("kind", "line")
        if kind == "circle":
            radius = math.hypot(second.x() - first.x(), second.y() - first.y())
            return (), ((first, radius),)
        if kind == "rectangle":
            rect = QRectF(first, second).normalized()
            corners = (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())
            return tuple((corners[i], corners[(i + 1) % 4]) for i in range(4)), ()
        return ((first, second),), ()

    def _draw_sheet_line(
        self, painter: QPainter, annotation: dict, view_index: int | None,
        line_index: int,
    ) -> None:
        try:
            points = annotation["points"]
            first, second = points
            first_screen = self._sheet_annotation_screen_point({"anchor": first}, view_index)
            second_screen = self._sheet_annotation_screen_point({"anchor": second}, view_index)
        except (KeyError, TypeError, ValueError):
            return
        if first_screen is None or second_screen is None:
            return
        key = (view_index if view_index is not None else -1, line_index)
        selected = self._selected_sheet_line == key
        pen = QPen(QColor("#0969da") if selected else QColor("#000000"), 2.0 if selected else 1.0)
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        self._draw_annotation_geometry(painter, annotation.get("kind", "line"), first_screen, second_screen)
        if selected:
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(first_screen, 3.5, 3.5)
            painter.drawEllipse(second_screen, 3.5, 3.5)
            for endpoint, screen in enumerate((first_screen, second_screen)):
                self._sheet_line_handle_hit_rects[(*key, endpoint)] = QRectF(
                    screen.x() - 7.0, screen.y() - 7.0, 14.0, 14.0,
                )
        painter.restore()
        self._sheet_line_hit_rects[key] = QRectF(first_screen, second_screen).normalized().adjusted(
            -5.0, -5.0, 5.0, 5.0,
        )

    def _sheet_line_at(self, position: QPointF) -> tuple[int, int] | None:
        best = None
        collections = [(index, view.get("sheet_lines", ()))
                       for index, view in enumerate(self._sheet_views)]
        collections.append((-1, self._sheet_lines))
        for view_index, annotations in collections:
            context = None if view_index < 0 else view_index
            for index, annotation in enumerate(annotations):
                segments, circles = self._annotation_screen_primitives(annotation, context)
                distances = []
                for first, second in segments:
                    closest = self._closest_point_on_screen_segment(position, first, second)
                    distances.append(math.hypot(closest.x() - position.x(), closest.y() - position.y()))
                for center, radius in circles:
                    distances.append(abs(math.hypot(position.x() - center.x(), position.y() - center.y()) - radius))
                if distances:
                    distance = min(distances)
                    if best is None or distance < best[0]:
                        best = (distance, (view_index, index))
        return best[1] if best is not None and best[0] <= 7.0 else None

    def _line_endpoint_at(self, screen_point: QPointF, view_index: int | None) -> tuple[float, float] | None:
        return self._annotation_anchor(screen_point, view_index)

    def _constrain_line_endpoint(
        self, first_screen: QPointF, target_screen: QPointF, free: bool,
    ) -> QPointF:
        dx, dy = target_screen.x() - first_screen.x(), target_screen.y() - first_screen.y()
        length = math.hypot(dx, dy)
        if free or length <= 1e-9:
            return QPointF(target_screen)
        angle = math.atan2(dy, dx)
        snapped = round(angle / (math.pi / 4.0)) * (math.pi / 4.0)
        return QPointF(
            first_screen.x() + math.cos(snapped) * length,
            first_screen.y() + math.sin(snapped) * length,
        )

    @staticmethod
    def _closest_point_on_screen_segment(point: QPointF, first: QPointF, second: QPointF) -> QPointF:
        dx, dy = second.x() - first.x(), second.y() - first.y()
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-12:
            return QPointF(first)
        fraction = max(0.0, min(1.0, (
            (point.x() - first.x()) * dx + (point.y() - first.y()) * dy
        ) / length_squared))
        return QPointF(first.x() + fraction * dx, first.y() + fraction * dy)

    def _sheet_reference_segments(self):
        segments = []
        def add_rect(rect: QRectF) -> None:
            if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
                return
            corners = (rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft())
            segments.extend((corners[index], corners[(index + 1) % 4]) for index in range(4))

        add_rect(self._paper_rect)
        add_rect(self._drawing_area)
        if self._settings.get("title_block_visible", True):
            add_rect(self._stamp_rect)
            stamp = self._stamp_rect
            row_height = 10.0 * self._sheet_pixels_per_mm
            main_split = stamp.left() + stamp.width() * 0.78
            for row in range(1, 5):
                y = stamp.top() + row * row_height
                segments.append((QPointF(stamp.left(), y), QPointF(stamp.right(), y)))
            segments.append((QPointF(main_split, stamp.top()), QPointF(main_split, stamp.bottom())))
            row_four = stamp.top() + 3.0 * row_height
            right_split = main_split + (stamp.right() - main_split) / 2.0
            row_five = stamp.top() + 4.0 * row_height
            segments.append((QPointF(right_split, row_four), QPointF(right_split, row_five)))
            left_mid = stamp.left() + (main_split - stamp.left()) / 2.0
            segments.append((QPointF(left_mid, row_five), QPointF(left_mid, row_five+row_height)))
            logos_top = stamp.top() + 5*row_height
            segments.append((QPointF(stamp.left(), logos_top), QPointF(stamp.right(), logos_top)))
        return segments

    def _table_reference_segments(self, excluded_table=None):
        segments = []
        for index, bounds in self._sheet_table_hit_rects.items():
            if index == excluded_table:
                continue
            corners = (bounds.topLeft(), bounds.topRight(), bounds.bottomRight(), bounds.bottomLeft())
            segments.extend((corners[i], corners[(i + 1) % 4]) for i in range(4))
            cached = self._sheet_table_layouts.get(index)
            if cached is None:
                continue
            layout = cached[1]
            scale = bounds.width() / layout.width_mm
            x = bounds.left()
            footer_height = getattr(layout, "_footer_height", 0.0)
            for width in layout._widths[:-1]:
                x += width * scale
                segments.append((QPointF(x, bounds.top() + layout._title_height * scale),
                                 QPointF(x, bounds.bottom() - footer_height * scale)))
            y = bounds.top() + layout._title_height * scale
            for height, _docs in layout._rows:
                segments.append((QPointF(bounds.left(), y), QPointF(bounds.right(), y)))
                y += height * scale
            if footer_height:
                segments.append((QPointF(bounds.left(), y), QPointF(bounds.right(), y)))
                split = bounds.right() - layout._widths[-1] * scale
                segments.append((QPointF(split, y), QPointF(split, bounds.bottom())))
        return segments

    def _table_snap_segments(self):
        segments = self._sheet_reference_segments()
        segments.extend(self._table_reference_segments(self._drag_sheet_table))
        for view_index, annotations in [(None, self._sheet_lines)] + [
            (index, view.get("sheet_lines", ())) for index, view in enumerate(self._sheet_views)
        ]:
            for annotation in annotations:
                lines, _circles = self._annotation_screen_primitives(annotation, view_index)
                segments.extend(lines)
        for view_index, view in enumerate(self._sheet_views):
            if view_index not in self._view_draw_data:
                continue
            grid = self._segment_grid_for_view(view_index)
            owners = self._display_linework(view)[1]
            hidden = {str(owner) for owner in view.get("hidden_owners", ())}
            for index, (a, b) in enumerate(grid.segments):
                if len(owners) == len(grid.segments) and str(owners[index]) in hidden:
                    continue
                segments.append((self._screen_point(view_index, a), self._screen_point(view_index, b)))
        return [(a, b) for a, b in segments if a is not None and b is not None]

    @staticmethod
    def _snap_table_bounds(bounds: QRectF, segments, tolerance=8.0) -> QRectF:
        """Align parallel edges without accumulating snapped mouse deltas."""
        dx = dy = None
        for a, b in segments:
            if abs(a.x() - b.x()) < 1e-6 and abs(a.y() - b.y()) > 1e-6:
                if max(a.y(), b.y()) < bounds.top() - tolerance or min(a.y(), b.y()) > bounds.bottom() + tolerance:
                    continue
                for edge in (bounds.left(), bounds.right()):
                    delta = a.x() - edge
                    if abs(delta) <= tolerance and (dx is None or abs(delta) < abs(dx)):
                        dx = delta
            elif abs(a.y() - b.y()) < 1e-6 and abs(a.x() - b.x()) > 1e-6:
                if max(a.x(), b.x()) < bounds.left() - tolerance or min(a.x(), b.x()) > bounds.right() + tolerance:
                    continue
                for edge in (bounds.top(), bounds.bottom()):
                    delta = a.y() - edge
                    if abs(delta) <= tolerance and (dy is None or abs(delta) < abs(dy)):
                        dy = delta
        return bounds.translated(dx or 0.0, dy or 0.0)

    @staticmethod
    def _circle_segment_intersections(center, radius, first, second):
        dx, dy = second.x() - first.x(), second.y() - first.y()
        ox, oy = first.x() - center.x(), first.y() - center.y()
        a = dx * dx + dy * dy
        if a <= 1e-12:
            return ()
        b = 2.0 * (dx * ox + dy * oy)
        c = ox * ox + oy * oy - radius * radius
        discriminant = b * b - 4.0 * a * c
        if discriminant < -1e-9:
            return ()
        root = math.sqrt(max(0.0, discriminant))
        return tuple(QPointF(first.x() + t * dx, first.y() + t * dy)
                     for t in ((-b - root) / (2 * a), (-b + root) / (2 * a))
                     if 0.0 <= t <= 1.0)

    def _sheet_snap_at(self, position: QPointF, origin: QPointF | None = None):
        return self._line_snap_screen_point(position, None, origin)

    def _line_snap_screen_point(
        self, position: QPointF, view_index: int | None, origin: QPointF | None = None,
    ) -> tuple[QPointF, str] | None:
        """Only endpoints, midpoints, crossings and perpendiculars from the origin."""
        segments = self._sheet_reference_segments()
        segments.extend(self._table_reference_segments())
        circles = []
        if view_index is not None and 0 <= view_index < len(self._sheet_views):
            view = self._sheet_views[view_index]
            grid = self._segment_grid_for_view(view_index)
            projected = self._projected_point_at(view_index, position)
            draw_data = self._view_draw_data.get(view_index)
            if projected is not None and draw_data is not None and draw_data[4] > 1e-12:
                owners = self._display_linework(view)[1]
                hidden = {str(owner) for owner in view.get("hidden_owners", ())}
                for index in grid.query(*projected, 12.0 / draw_data[4]):
                    if len(owners) == len(grid.segments) and str(owners[index]) in hidden:
                        continue
                    first, second = grid.segments[index]
                    segments.append((self._screen_point(view_index, first),
                                     self._screen_point(view_index, second)))
                for first, second in self._axis_dimension_snap_segments.get(view_index, ()):
                    segments.append((self._screen_point(view_index, first),
                                     self._screen_point(view_index, second)))
        elif view_index is not None:
            return None
        annotations = (self._sheet_lines if view_index is None
                       else self._sheet_views[view_index].get("sheet_lines", ()))
        for index, annotation in enumerate(annotations):
            key = (-1 if view_index is None else view_index, index)
            if self._drag_sheet_line_endpoint is not None and self._drag_sheet_line_endpoint[:2] == key:
                continue
            shape_segments, shape_circles = self._annotation_screen_primitives(annotation, view_index)
            segments.extend(shape_segments)
            circles.extend(shape_circles)
        segments = [(a, b) for a, b in segments if a is not None and b is not None
                    and QRectF(a, b).normalized().adjusted(-12, -12, 12, 12).contains(position)]
        best = None
        def consider(point, kind):
            nonlocal best
            distance = math.hypot(point.x() - position.x(), point.y() - position.y())
            if distance <= 12.0 and (best is None or distance < best[0]):
                best = (distance, point, kind)
        for first, second in segments:
            consider(first, "endpoint")
            consider(second, "endpoint")
            consider((first + second) / 2.0, "center")
            if origin is not None:
                dx, dy = second.x() - first.x(), second.y() - first.y()
                length_squared = dx * dx + dy * dy
                if length_squared > 1e-12:
                    t = ((origin.x() - first.x()) * dx + (origin.y() - first.y()) * dy) / length_squared
                    if 0.0 <= t <= 1.0:
                        consider(QPointF(first.x() + t * dx, first.y() + t * dy), "perpendicular")
        for i, (first, second) in enumerate(segments):
            for other_first, other_second in segments[i + 1:]:
                crossing = self._segment_intersection(
                    ((first.x(), first.y()), (second.x(), second.y())),
                    ((other_first.x(), other_first.y()), (other_second.x(), other_second.y())),
                )
                if crossing is not None:
                    consider(QPointF(*crossing), "intersection")
            for center, radius in circles:
                for crossing in self._circle_segment_intersections(center, radius, first, second):
                    consider(crossing, "intersection")
        for i, (center, radius) in enumerate(circles):
            if origin is not None:
                delta = origin - center
                length = math.hypot(delta.x(), delta.y())
                if length > 1e-12:
                    consider(center + delta * (radius / length), "perpendicular")
                    consider(center - delta * (radius / length), "perpendicular")
            for other, other_radius in circles[i + 1:]:
                delta = other - center
                distance = math.hypot(delta.x(), delta.y())
                if distance <= 1e-12 or distance > radius + other_radius or distance < abs(radius - other_radius):
                    continue
                offset = (radius * radius - other_radius * other_radius + distance * distance) / (2 * distance)
                height = math.sqrt(max(0.0, radius * radius - offset * offset))
                base = center + delta * (offset / distance)
                normal = QPointF(-delta.y(), delta.x()) * (height / distance)
                consider(base + normal, "intersection")
                consider(base - normal, "intersection")
        return (QPointF(best[1]), best[2]) if best is not None else None

    def _line_endpoint_screen_point(
        self, first_screen: QPointF, position: QPointF, view_index: int | None, free: bool,
    ) -> QPointF:
        # Explicit geometry snaps take precedence over the 45-degree angle snap.
        snap = self._line_snap_screen_point(position, view_index, first_screen)
        if snap is not None:
            return snap[0]
        kind = self._annotation_mode
        if self._drag_sheet_line_endpoint is not None:
            view_key, index, _endpoint = self._drag_sheet_line_endpoint
            collection = self._line_annotation_collection(None if view_key < 0 else view_key)
            if 0 <= index < len(collection):
                kind = collection[index].get("kind", "line")
        if kind in {"rectangle", "circle"}:
            return QPointF(position)
        return self._constrain_line_endpoint(first_screen, position, free)

    def _sheet_annotation_click(self, point: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        if self._annotation_mode == "image":
            if not self._paper_rect.contains(point) or self._pending_sheet_image is None:
                return
            # Logos and sheet images belong to the paper, including the carimbo.
            anchor = self._annotation_anchor(point, None)
            if anchor is None:
                return
            annotation = dict(self._pending_sheet_image, anchor=anchor)
            self.add_sheet_text(annotation)
            self.annotation_finished.emit("image", False)
            return
        if self._annotation_mode == "text":
            view_index = self._annotation_view_at(point)
            anchor = self._annotation_anchor(point, view_index)
            if anchor is None:
                return
            self._annotation_mode = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.text_editor_requested.emit({
                "view_index": view_index,
                "anchor": anchor,
                "width_mm": 50.0,
                "height_mm": 25.0,
                "html": "",
            })
            return
        if self._annotation_mode not in {"line", "rectangle", "circle"}:
            return
        if self._line_start_context is None:
            view_index = self._annotation_view_at(point)
            snap = self._line_snap_screen_point(point, view_index)
            start_point = snap[0] if snap is not None else point
            anchor = self._annotation_anchor(start_point, view_index)
            if anchor is None:
                return
            self._begin_sheet_annotation_drag()
            self._line_start_context = (view_index, anchor)
            self._line_preview_endpoint = anchor
            self._line_preview_screen_endpoint = QPointF(start_point)
            self._line_preview_snap_screen = QPointF(start_point) if snap is not None else None
            self._line_preview_snap_kind = snap[1] if snap is not None else None
            self.update()
            return
        view_index, start = self._line_start_context
        start_screen = self._sheet_annotation_screen_point({"anchor": start}, view_index)
        if start_screen is None:
            return
        end_screen = self._line_endpoint_screen_point(
            start_screen, point, view_index,
            bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
        )
        end = self._line_endpoint_at(end_screen, view_index)
        if end is None or math.hypot(end[0] - start[0], end[1] - start[1]) <= 1e-9:
            return
        kind = self._annotation_mode
        if kind == "rectangle" and (abs(end_screen.x() - start_screen.x()) < 1e-6
                                     or abs(end_screen.y() - start_screen.y()) < 1e-6):
            return
        collection = self._line_annotation_collection(view_index)
        collection.append({"kind": kind, "points": (start, end)})
        self._selected_component_detail_group = None
        self.select_view(None)
        self._selected_sheet_line = (view_index if view_index is not None else -1, len(collection) - 1)
        self._selected_sheet_text = None
        self._annotation_mode = None
        self._annotation_background = None
        self._line_start_context = None
        self._line_preview_endpoint = None
        self._line_preview_screen_endpoint = None
        self._line_preview_snap_kind = None
        self._line_preview_snap_screen = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
        self.layout_changed.emit()
        self.annotation_finished.emit(kind, False)

    def _make_detail_identifier(self, view, name, center, radius) -> dict:
        denominator = max(1.0, float(view.get("scale_denominator", 100.0)))
        tail_and_gap = (
            float(self._project_settings.get("detail_identifier_leader_length_mm", 5.0))
            + 3.0
        ) * denominator / 1000.0
        return {
            "name": str(name),
            "center": tuple(float(value) for value in center),
            "radius": float(radius),
            "label_position": (
                float(center[0]) + float(radius) * 1.5 + tail_and_gap,
                float(center[1]) - float(radius) * 0.9,
            ),
        }

    def _draw_detail_identifier(
        self, painter: QPainter, view_index: int, identifier: dict,
        identifier_index: int | None,
    ) -> QRectF | None:
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None or draw_data[4] <= 1e-12:
            return None
        try:
            center_x, center_y = (float(value) for value in identifier["center"])
            label_x, label_y = (float(value) for value in identifier["label_position"])
            radius = float(identifier["radius"])
        except (KeyError, TypeError, ValueError):
            return None
        if radius <= 0.0:
            return None
        _view_center_x, _view_center_y, target_x, target_y, model_to_pixels = draw_data
        center = QPointF(
            target_x + (center_x - _view_center_x) * model_to_pixels,
            target_y - (center_y - _view_center_y) * model_to_pixels,
        )
        label_anchor = QPointF(
            target_x + (label_x - _view_center_x) * model_to_pixels,
            target_y - (label_y - _view_center_y) * model_to_pixels,
        )
        radius_pixels = radius * model_to_pixels
        font = QFont(painter.font())
        text_height_mm = float(
            self._project_settings.get("detail_identifier_text_height_mm", 3.0)
        )
        font.setPixelSize(max(1, round(text_height_mm * self._sheet_pixels_per_mm)))
        metrics = QFontMetrics(font)
        name = str(identifier.get("name", "DET"))
        text_width = metrics.horizontalAdvance(name)
        tail_length = float(
            self._project_settings.get("detail_identifier_leader_length_mm", 5.0)
        ) * self._sheet_pixels_per_mm
        text_gap = 3.0 * self._sheet_pixels_per_mm
        text_is_right = label_anchor.x() + text_width / 2.0 >= center.x()
        tail_end = QPointF(
            label_anchor.x() - text_gap if text_is_right
            else label_anchor.x() + text_width + text_gap,
            label_anchor.y(),
        )
        elbow = QPointF(
            tail_end.x() - tail_length if text_is_right else tail_end.x() + tail_length,
            label_anchor.y(),
        )
        direction_x = elbow.x() - center.x()
        direction_y = elbow.y() - center.y()
        direction_length = math.hypot(direction_x, direction_y)
        if direction_length <= 1e-9:
            direction_x, direction_y, direction_length = 1.0, 0.0, 1.0
        circle_edge = QPointF(
            center.x() + direction_x / direction_length * radius_pixels,
            center.y() + direction_y / direction_length * radius_pixels,
        )

        circle_pen = QPen(QColor(str(self._project_settings.get(
            "detail_identifier_circle_color", "#ff0000",
        ))), 1.0)
        circle_pen.setCosmetic(True)
        circle_pen.setStyle(Qt.PenStyle.DashLine)
        leader_pen = QPen(QColor(str(self._project_settings.get(
            "detail_identifier_leader_color", "#ff0000",
        ))), 1.0)
        leader_pen.setCosmetic(True)
        painter.save()
        painter.setPen(circle_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius_pixels, radius_pixels)
        painter.setPen(leader_pen)
        painter.drawLine(circle_edge, elbow)
        painter.drawLine(elbow, tail_end)

        painter.setFont(font)
        painter.setPen(QColor(str(self._project_settings.get(
            "detail_identifier_text_color", "#000000",
        ))))
        text_rect = QRectF(
            label_anchor.x(),
            label_anchor.y() - metrics.height() / 2.0,
            metrics.horizontalAdvance(name),
            metrics.height(),
        )
        bounds = QRectF(center.x() - radius_pixels, center.y() - radius_pixels,
                        radius_pixels * 2.0, radius_pixels * 2.0)
        bounds = bounds.united(QRectF(circle_edge, elbow).normalized())
        bounds = bounds.united(QRectF(elbow, tail_end).normalized())
        bounds = bounds.united(text_rect)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        if identifier_index is not None:
            self._detail_identifier_hit_rects[(view_index, identifier_index)] = (
                text_rect.adjusted(-4.0, -3.0, 4.0, 3.0)
            )
            if self._selected_detail_identifier == (view_index, identifier_index):
                selection_pen = QPen(QColor("#0969da"), 1.5)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(text_rect.adjusted(-3.0, -2.0, 3.0, 2.0))
                handle_radius = 4.0
                handle_hit_radius = 9.0
                painter.setPen(selection_pen)
                painter.setBrush(QColor("#ffffff"))
                for handle_name, handle_point in (("center", center), ("radius", circle_edge)):
                    painter.drawEllipse(handle_point, handle_radius, handle_radius)
                    self._detail_identifier_handle_hit_rects[
                        (view_index, identifier_index, handle_name)
                    ] = QRectF(
                        handle_point.x() - handle_hit_radius,
                        handle_point.y() - handle_hit_radius,
                        handle_hit_radius * 2.0,
                        handle_hit_radius * 2.0,
                    )
                    bounds = bounds.united(QRectF(
                        handle_point.x() - handle_radius,
                        handle_point.y() - handle_radius,
                        handle_radius * 2.0,
                        handle_radius * 2.0,
                    ))
        painter.restore()
        return bounds.adjusted(-2.0, -2.0, 2.0, 2.0)

    def _draw_elevation_identifier(
        self, painter: QPainter, view_index: int, identifier: dict,
        identifier_index: int | None,
    ) -> QRectF | None:
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None or draw_data[4] <= 1e-12:
            return None
        try:
            point_x, point_y = (float(value) for value in identifier["point"])
            direction_x, direction_y = (float(value) for value in identifier["direction"])
        except (KeyError, TypeError, ValueError):
            return None
        _center_x, _center_y, target_x, target_y, model_to_pixels = draw_data
        length = math.hypot(direction_x, direction_y)
        if length <= 1e-9:
            return None
        direction_x, direction_y = direction_x / length, direction_y / length
        direction = QPointF(direction_x, -direction_y)
        perpendicular = QPointF(-direction.y(), direction.x())
        anchor = QPointF(
            target_x + (point_x - _center_x) * model_to_pixels,
            target_y - (point_y - _center_y) * model_to_pixels,
        )
        width = 16.0 * self._sheet_pixels_per_mm
        wall_height = 2.5 * self._sheet_pixels_per_mm
        roof_height = 2.0 * wall_height
        text_gap = 0.5 * self._sheet_pixels_per_mm
        half_width = width / 2.0
        base_left = anchor - perpendicular * half_width
        base_right = anchor + perpendicular * half_width
        wall_left = base_left + direction * wall_height
        wall_right = base_right + direction * wall_height
        roof_peak = anchor + direction * roof_height

        symbol_color = QColor(str(self._project_settings.get(
            "elevation_identifier_symbol_color", "#ff0000",
        )))
        if not symbol_color.isValid():
            symbol_color = QColor("#ff0000")
        symbol_pen = QPen(symbol_color, 1.0)
        symbol_pen.setCosmetic(True)

        font = QFont(painter.font())
        text_height_mm = float(self._project_settings.get(
            "elevation_identifier_text_height_mm", 3.0,
        ))
        font.setPixelSize(max(1, round(text_height_mm * self._sheet_pixels_per_mm)))
        metrics = QFontMetrics(font)
        name = str(identifier.get("name", "Elevação"))
        text_width = metrics.horizontalAdvance(name)
        text_center = anchor - direction * (text_gap + metrics.height() / 2.0)
        text_rotation = math.degrees(math.atan2(perpendicular.y(), perpendicular.x()))
        text_rect = self._rotated_text_rect(
            text_center, text_width, -metrics.height() / 2.0,
            metrics.height() / 2.0, text_rotation,
        )

        painter.save()
        painter.setPen(symbol_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for first, second in (
            (base_left, wall_left),
            (wall_left, roof_peak),
            (roof_peak, wall_right),
            (wall_right, base_right),
            (base_right, base_left),
        ):
            painter.drawLine(first, second)
        painter.setFont(font)
        text_color = QColor(str(self._project_settings.get(
            "elevation_identifier_text_color", "#000000",
        )))
        painter.setPen(text_color if text_color.isValid() else QColor("#000000"))
        painter.translate(text_center)
        painter.rotate(text_rotation)
        painter.drawText(
            QRectF(-text_width / 2.0, -metrics.height() / 2.0, text_width, metrics.height()),
            Qt.AlignmentFlag.AlignCenter,
            name,
        )
        painter.restore()

        points = (base_left, wall_left, roof_peak, wall_right, base_right)
        bounds = QRectF(
            min(point.x() for point in points), min(point.y() for point in points),
            max(point.x() for point in points) - min(point.x() for point in points),
            max(point.y() for point in points) - min(point.y() for point in points),
        ).united(text_rect)
        if identifier_index is not None:
            self._elevation_identifier_hit_rects[(view_index, identifier_index)] = (
                text_rect.adjusted(-4.0, -3.0, 4.0, 3.0)
            )
            self._elevation_identifier_bounds[(view_index, identifier_index)] = (
                bounds.adjusted(-2.0, -2.0, 2.0, 2.0)
            )
            if self._selected_elevation_identifier == (view_index, identifier_index):
                selection_pen = QPen(QColor("#0969da"), 1.25)
                selection_pen.setCosmetic(True)
                painter.save()
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(text_rect.adjusted(-3.0, -2.0, 3.0, 2.0))
                painter.restore()
        return bounds.adjusted(-2.0, -2.0, 2.0, 2.0)

    def _draw_view_axes(
        self, painter: QPainter, view: dict, view_index: int, scale: float,
    ) -> QRectF | None:
        projection = view.get("projection", {})
        plane = projection.get("plane") if isinstance(projection, dict) else None
        axes_by_plane = {
            "XY": (("X", 0, 1), ("Y", 1, 0)),
            "XZ": (("X", 0, 2), ("Z", 2, 0)),
            "YZ": (("Y", 1, 2), ("Z", 2, 1)),
        }
        specs = axes_by_plane.get(plane)
        generic_projection = specs is None and (
            plane == "custom" or str(plane).startswith("ISO-")
        )
        if generic_projection:
            specs = (("X", 0, 1), ("Y", 1, 2), ("Z", 2, 0))
        if specs is None:
            return None
        main_window = self.window()
        model = getattr(main_window, "model", None)
        if model is None:
            return None
        axes = getattr(model, "axes", {})
        nodes = tuple(getattr(model, "nodes", {}).values())
        if not nodes:
            return None
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None:
            return None
        center_x, center_y, target_x, target_y, model_to_pixels = draw_data
        section_coordinate = 0.0
        if not generic_projection:
            coordinate = projection.get("coordinate", 0.0)
            try:
                section_coordinate = float(coordinate)
            except (TypeError, ValueError):
                return None
        fixed_index = {"XY": 2, "XZ": 1, "YZ": 0}.get(plane)
        segments = self._display_linework(view)[0]
        axes_key = tuple(
            (direction, tuple(
                (str(axis.label), float(axis.value)) for axis in axes.get(direction, ())
            ))
            for direction in ("X", "Y", "Z")
        )
        cache_key = (
            id(model), getattr(model, "revision", None), id(segments), plane,
            section_coordinate, projection.get("orientation"), projection.get("rotation_degrees"),
            axes_key,
        )
        cached = self._view_axis_geometry.get(view_index)
        if cached is None or cached[0] != cache_key:
            node_coordinates = [(node.x, node.y, node.z) for node in nodes]
            geometry_points = [
                (float(point[0]), float(point[1]))
                for segment in segments for point in segment
            ]
            axis_geometry = []
            if geometry_points:
                for direction, axis_index, varying_index in specs:
                    minimum = min(point[varying_index] for point in node_coordinates)
                    maximum = max(point[varying_index] for point in node_coordinates)
                    for axis in axes.get(direction, ()):
                        axis_key = f"{direction}:{axis.label}:{float(axis.value):.6f}"
                        if generic_projection:
                            start = [
                                (min(point[i] for point in node_coordinates)
                                 + max(point[i] for point in node_coordinates)) / 2.0
                                for i in range(3)
                            ]
                            end = list(start)
                            start[axis_index] = end[axis_index] = float(axis.value)
                            start[varying_index], end[varying_index] = minimum, maximum
                            axis_key = (
                                f"{direction}:{axis.label}:{float(axis.value):.6f}:"
                                f"{varying_index}"
                            )
                        else:
                            start = [0.0, 0.0, 0.0]
                            end = [0.0, 0.0, 0.0]
                            start[fixed_index] = end[fixed_index] = section_coordinate
                            start[axis_index] = end[axis_index] = float(axis.value)
                            start[varying_index], end[varying_index] = minimum, maximum
                        projected_start = self._project_world_point(view, start)
                        projected_end = self._project_world_point(view, end)
                        if projected_start is None or projected_end is None:
                            continue
                        axis_dx = projected_end[0] - projected_start[0]
                        axis_dy = projected_end[1] - projected_start[1]
                        axis_length = math.hypot(axis_dx, axis_dy)
                        if axis_length <= 1e-9:
                            continue
                        axis_direction = (axis_dx / axis_length, axis_dy / axis_length)
                        intersects = False
                        for first, second in segments:
                            first_distance = (axis_direction[0] * (float(first[1]) - projected_start[1])
                                              - axis_direction[1] * (float(first[0]) - projected_start[0]))
                            second_distance = (axis_direction[0] * (float(second[1]) - projected_start[1])
                                               - axis_direction[1] * (float(second[0]) - projected_start[0]))
                            if (abs(first_distance) <= 1e-5 or abs(second_distance) <= 1e-5
                                    or first_distance * second_distance < 0.0):
                                intersects = True
                                break
                        if not intersects:
                            continue
                        coordinates = [point[0] * axis_direction[0] + point[1] * axis_direction[1]
                                       for point in geometry_points]
                        axis_start = min(coordinates) - 2.0
                        axis_end = max(coordinates) + 2.0
                        anchor = projected_start[0] * axis_direction[0] + projected_start[1] * axis_direction[1]
                        projected_start = (
                            projected_start[0] + axis_direction[0] * (axis_start - anchor),
                            projected_start[1] + axis_direction[1] * (axis_start - anchor),
                        )
                        projected_end = (
                            projected_start[0] + axis_direction[0] * (axis_end - axis_start),
                            projected_start[1] + axis_direction[1] * (axis_end - axis_start),
                        )
                        axis_geometry.append((axis_key, str(axis.label), projected_start, projected_end))
            cached = (cache_key, axis_geometry)
            self._view_axis_geometry[view_index] = cached
        axis_geometry = cached[1]
        if not axis_geometry:
            return None
        pen = QPen(QColor("#57606a"), 1.0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.SolidLine)
        # The axis stroke is cosmetic, so its pattern must stay in screen
        # pixels as well. Scaling the dash lengths with sheet zoom caused the
        # dash-dot rhythm to change and visibly crawl along the axis.
        pen.setDashPattern(PROJECT_AXIS_DASH_PATTERN)
        painter.save()
        painter.setPen(pen)
        axis_font = QFont(painter.font())
        axis_font.setPixelSize(max(1, round(2.5 * scale)))
        painter.setFont(axis_font)
        axes_bounds = QRectF()
        has_axes_bounds = False
        for axis_key, label, projected_start, projected_end in axis_geometry:
            start_screen = QPointF(
                target_x + (projected_start[0] - center_x) * model_to_pixels,
                target_y - (projected_start[1] - center_y) * model_to_pixels,
            )
            end_screen = QPointF(
                target_x + (projected_end[0] - center_x) * model_to_pixels,
                target_y - (projected_end[1] - center_y) * model_to_pixels,
            )
            base_dx = end_screen.x() - start_screen.x()
            base_dy = end_screen.y() - start_screen.y()
            base_length = math.hypot(base_dx, base_dy)
            base_direction = (
                (base_dx / base_length, base_dy / base_length)
                if base_length > 1e-9 else (0.0, 0.0)
            )
            positions = view.setdefault("axis_label_positions", {})
            if not isinstance(positions, dict):
                positions = view["axis_label_positions"] = {}
            endpoints = []
            projected_endpoints = []
            for end_name, default_fraction in (("start", 0.0), ("end", 1.0)):
                try:
                    fraction = float(positions.get(f"{axis_key}:{end_name}", default_fraction))
                except (TypeError, ValueError):
                    fraction = default_fraction
                projected = (
                    projected_start[0] + (projected_end[0] - projected_start[0]) * fraction,
                    projected_start[1] + (projected_end[1] - projected_start[1]) * fraction,
                )
                projected_endpoints.append(projected)
                endpoints.append(QPointF(
                    target_x + (projected[0] - center_x) * model_to_pixels,
                    target_y - (projected[1] - center_y) * model_to_pixels,
                ))
            self._axis_dimension_snap_segments.setdefault(view_index, []).append(
                (projected_endpoints[0], projected_endpoints[1])
            )
            start_screen, end_screen = endpoints
            painter.drawLine(start_screen, end_screen)
            badge_diameter = max(1.0, 8.0 * scale)
            badge_radius = badge_diameter / 2.0
            badge_font = QFont(axis_font)
            badge_font.setPixelSize(max(1, round(3.0 * scale)))
            painter.setFont(badge_font)
            badge_pen = QPen(QColor("#57606a"), 1.0)
            badge_pen.setCosmetic(True)
            painter.setPen(badge_pen)
            painter.setBrush(QColor("#ffffff"))
            for end_name, endpoint in zip(("start", "end"), endpoints):
                badge_rect = QRectF(
                    endpoint.x() - badge_radius, endpoint.y() - badge_radius,
                    badge_diameter, badge_diameter,
                )
                painter.drawEllipse(badge_rect)
                painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)
                endpoint_selection_key = (view_index, f"{axis_key}:{end_name}")
                if endpoint_selection_key in self._selected_axis_endpoints:
                    painter.save()
                    selection_pen = QPen(QColor("#0969da"), 1.5)
                    selection_pen.setCosmetic(True)
                    painter.setPen(selection_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(badge_rect.adjusted(-3.0, -3.0, 3.0, 3.0))
                    painter.restore()
                axes_bounds = (
                    axes_bounds.united(badge_rect)
                    if has_axes_bounds else QRectF(badge_rect)
                )
                has_axes_bounds = True
                self._axis_endpoint_hit_rects[(view_index, f"{axis_key}:{end_name}")] = (
                    badge_rect.adjusted(-2.0, -2.0, 2.0, 2.0)
                )
                self._axis_endpoint_drag_data[(view_index, f"{axis_key}:{end_name}")] = (
                    base_direction[0], base_direction[1], base_length,
                )
            axis_bounds = QRectF(start_screen, end_screen).normalized().adjusted(
                -badge_radius - 3.0, -badge_radius - 3.0,
                badge_radius + 3.0, badge_radius + 3.0,
            )
            self._axis_line_bounds[(view_index, axis_key)] = axis_bounds
            axes_bounds = (
                axes_bounds.united(axis_bounds) if has_axes_bounds else QRectF(axis_bounds)
            )
            has_axes_bounds = True
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setFont(axis_font)
            painter.setPen(pen)
        painter.restore()
        return axes_bounds if has_axes_bounds else None

    @staticmethod
    def _rotated_text_rect(
        baseline: QPointF, width: float, local_top: float, local_bottom: float,
        rotation_degrees: float,
    ) -> QRectF:
        half_width = width / 2.0
        angle = math.radians(rotation_degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        corners = []
        for x in (-half_width, half_width):
            for y in (local_top, local_bottom):
                corners.append(QPointF(
                    baseline.x() + x * cosine - y * sine,
                    baseline.y() + x * sine + y * cosine,
                ))
        return QRectF(
            min(point.x() for point in corners),
            min(point.y() for point in corners),
            max(point.x() for point in corners) - min(point.x() for point in corners),
            max(point.y() for point in corners) - min(point.y() for point in corners),
        )

    @staticmethod
    def _project_world_point(view: dict, point) -> tuple[float, float] | None:
        try:
            x, y, z = (float(value) for value in point)
        except (TypeError, ValueError):
            return None
        projection = view.get("projection", {})
        plane = projection.get("plane") if isinstance(projection, dict) else None
        rotation = math.radians(-float(projection.get("rotation_degrees", 0.0)))
        if plane == "custom":
            try:
                origin, u_point, third_point = projection["coordinate"]
                origin = tuple(float(value) for value in origin)
                u_point = tuple(float(value) for value in u_point)
                third_point = tuple(float(value) for value in third_point)
                u = tuple(u_point[i] - origin[i] for i in range(3))
                u_length = math.sqrt(sum(value * value for value in u))
                if u_length <= 1e-12:
                    return None
                u = tuple(value / u_length for value in u)
                v_seed = tuple(third_point[i] - origin[i] for i in range(3))
                normal = (
                    u[1] * v_seed[2] - u[2] * v_seed[1],
                    u[2] * v_seed[0] - u[0] * v_seed[2],
                    u[0] * v_seed[1] - u[1] * v_seed[0],
                )
                n_length = math.sqrt(sum(value * value for value in normal))
                if n_length <= 1e-12:
                    return None
                normal = tuple(value / n_length for value in normal)
                v = (
                    normal[1] * u[2] - normal[2] * u[1],
                    normal[2] * u[0] - normal[0] * u[2],
                    normal[0] * u[1] - normal[1] * u[0],
                )
                delta = (x - origin[0], y - origin[1], z - origin[2])
                orientation = projection.get("orientation", "Superior para inferior")
                camera_direction = tuple(
                    -value if orientation == "Inferior para superior" else value
                    for value in normal
                )
                view_direction = tuple(-value for value in camera_direction)
                cosine, sine = math.cos(rotation), math.sin(rotation)
                dot = sum(v[i] * view_direction[i] for i in range(3))
                cross = (
                    view_direction[1] * v[2] - view_direction[2] * v[1],
                    view_direction[2] * v[0] - view_direction[0] * v[2],
                    view_direction[0] * v[1] - view_direction[1] * v[0],
                )
                rotated_up = tuple(
                    v[i] * cosine + cross[i] * sine
                    + view_direction[i] * dot * (1 - cosine)
                    for i in range(3)
                )
                right = (
                    view_direction[1] * rotated_up[2] - view_direction[2] * rotated_up[1],
                    view_direction[2] * rotated_up[0] - view_direction[0] * rotated_up[2],
                    view_direction[0] * rotated_up[1] - view_direction[1] * rotated_up[0],
                )
                return sum(delta[i] * right[i] for i in range(3)), sum(
                    delta[i] * rotated_up[i] for i in range(3)
                )
            except (KeyError, TypeError, ValueError, IndexError):
                return None

        plane_data = {
            "XY": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
            "XZ": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            "YZ": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "ISO-SE": ((1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
            "ISO-NE": ((1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
            "ISO-NW": ((-1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
            "ISO-SW": ((-1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        }
        if plane not in plane_data:
            return None
        normal, base_up = plane_data[plane]
        normal_length = math.sqrt(sum(value * value for value in normal))
        normal = tuple(value / normal_length for value in normal)
        if plane.startswith("ISO-"):
            dot = sum(normal[i] * base_up[i] for i in range(3))
            up = tuple(base_up[i] - dot * normal[i] for i in range(3))
            up_length = math.sqrt(sum(value * value for value in up))
            base_up = tuple(value / up_length for value in up)
        orientation = projection.get("orientation", "Superior para inferior")
        camera_direction = tuple(
            -value if orientation == "Inferior para superior" and not plane.startswith("ISO-") else value
            for value in normal
        )
        view_direction = tuple(-value for value in camera_direction)
        cosine, sine = math.cos(rotation), math.sin(rotation)
        dot = sum(base_up[i] * view_direction[i] for i in range(3))
        cross = (
            view_direction[1] * base_up[2] - view_direction[2] * base_up[1],
            view_direction[2] * base_up[0] - view_direction[0] * base_up[2],
            view_direction[0] * base_up[1] - view_direction[1] * base_up[0],
        )
        rotated_up = tuple(
            base_up[i] * cosine + cross[i] * sine + view_direction[i] * dot * (1 - cosine)
            for i in range(3)
        )
        right = (
            view_direction[1] * rotated_up[2] - view_direction[2] * rotated_up[1],
            view_direction[2] * rotated_up[0] - view_direction[0] * rotated_up[2],
            view_direction[0] * rotated_up[1] - view_direction[1] * rotated_up[0],
        )
        point = (x, y, z)
        return sum(point[i] * right[i] for i in range(3)), sum(
            point[i] * rotated_up[i] for i in range(3)
        )

    def _title_block_rect(self, inner: QRectF, scale: float) -> QRectF:
        if not self._settings.get("title_block_visible", True):
            return QRectF()
        block_width = min(175.0 * scale, inner.width())
        block_height = 80.0 * scale
        top = (
            inner.top()
            if self._settings.get("title_block_position") == "Superior"
            else inner.bottom() - block_height
        )
        return QRectF(inner.right() - block_width, top, block_width, block_height)

    @staticmethod
    def _distance_to_segment(point: QPointF, start: QPointF, end: QPointF) -> tuple[float, float]:
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length_squared = dx * dx + dy * dy
        if length_squared <= 1e-12:
            return math.hypot(point.x() - start.x(), point.y() - start.y()), 0.0
        fraction = max(0.0, min(1.0, (
            (point.x() - start.x()) * dx + (point.y() - start.y()) * dy
        ) / length_squared))
        nearest_x, nearest_y = start.x() + fraction * dx, start.y() + fraction * dy
        return math.hypot(point.x() - nearest_x, point.y() - nearest_y), fraction

    @staticmethod
    def _segment_intersection(first, second):
        (ax, ay), (bx, by) = first
        (cx, cy), (dx, dy) = second
        rx, ry = bx - ax, by - ay
        sx, sy = dx - cx, dy - cy
        denominator = rx * sy - ry * sx
        if abs(denominator) <= 1e-12:
            return None
        qx, qy = cx - ax, cy - ay
        t = (qx * sy - qy * sx) / denominator
        u = (qx * ry - qy * rx) / denominator
        if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
            return ax + t * rx, ay + t * ry
        return None

    def _screen_point(self, view_index: int, point) -> QPointF | None:
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None:
            return None
        center_x, center_y, target_x, target_y, model_to_pixels = draw_data
        return QPointF(
            target_x + (float(point[0]) - center_x) * model_to_pixels,
            target_y - (float(point[1]) - center_y) * model_to_pixels,
        )

    def _projected_point_at(self, view_index: int, position: QPointF):
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None or abs(draw_data[4]) <= 1e-12:
            return None
        center_x, center_y, target_x, target_y, model_to_pixels = draw_data
        return (
            center_x + (position.x() - target_x) / model_to_pixels,
            center_y - (position.y() - target_y) / model_to_pixels,
        )

    def _member_break_axis(self, view, owner):
        model = getattr(self.window(), "model", None)
        # Component details saved by earlier versions use bare member names.
        name = owner.removeprefix("bar:")
        member = model.bars.get(name) if model is not None else None
        if member is None:
            return None
        endpoints = []
        for name in (member.start_node, member.end_node):
            node = model.nodes[name]
            point = self._project_world_point(view, (node.x, node.y, node.z))
            if point is None:
                return None
            endpoints.append(point)
        dx, dy = (endpoints[1][i] - endpoints[0][i] for i in range(2))
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-9 else None

    def _display_linework(self, view):
        segments, owners = view.get("segments", ()), view.get("segment_owners", ())
        marks = view.get("member_breaks", ())
        if not marks:
            return segments, owners
        key = id(view)
        signature = repr(marks)
        cached = self._break_linework_cache.get(key)
        if cached is None or cached[0] is not segments or cached[1] is not owners or cached[2] != signature:
            effective_marks = [dict(mark, axis=self._member_break_axis(view, mark.get("owner", ""))
                                    or mark.get("axis", ())) for mark in marks]
            decorated, sources, symbols = member_break_linework(segments, owners, effective_marks, return_symbols=True)
            cached = segments, owners, signature, (decorated, sources), symbols
            self._break_linework_cache[key] = cached
        return cached[3]

    def _member_break_symbols(self, view):
        if not view.get("member_breaks"):
            return {}
        self._display_linework(view)
        return self._break_linework_cache[id(view)][4]

    def _member_break_at(self, position):
        best = None
        for index, view in enumerate(self._sheet_views):
            draw_data = self._view_draw_data.get(index)
            if draw_data is None:
                continue
            cx, cy, tx, ty, scale = draw_data
            for mark_index, lines in self._member_break_symbols(view).items():
                if view["member_breaks"][mark_index]["owner"] in view.get("hidden_owners", ()):
                    continue
                distance = min(self._distance_to_segment(
                    position, QPointF(tx + (first[0] - cx) * scale, ty - (first[1] - cy) * scale),
                    QPointF(tx + (last[0] - cx) * scale, ty - (last[1] - cy) * scale),
                )[0] for first, last in lines)
                if distance <= 8.0 and (best is None or distance < best[0]):
                    best = distance, index, mark_index
        return best[1:] if best else None

    def _member_break_axis_range(self, view, mark):
        axis = self._member_break_axis(view, mark["owner"]) or mark["axis"]
        values = [sum(point[i] * axis[i] for i in range(2))
                  for segment, owner in zip(view["segments"], view["segment_owners"])
                  if owner == mark["owner"] for point in segment]
        return axis, min(values), max(values)

    def cancel_member_break_drag(self):
        if self._drag_member_break is None:
            return False
        index, mark_index, original, _cursor, _position = self._drag_member_break
        self._sheet_views[index]["member_breaks"][mark_index] = original
        self._drag_member_break = None
        self.invalidate_view_geometry(index)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
        return True

    def set_member_break_mode(self, active: bool) -> None:
        self._member_break_mode = bool(active)
        self._member_break_view_index = None
        self._hover_owners.clear()
        if active:
            self._selected_member_break = None
            self._annotation_mode = None
            self._dimension_mode = False
            self._identification_mode = False
            self._element_visibility_mode = None
            self._detail_identifier_mode = False
            self._elevation_identifier_mode = False
            self.select_view(None)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if active else Qt.CursorShape.ArrowCursor))
        self.update()

    def _member_break_target_at(self, position: QPointF, index: int):
        if self._stamp_rect.contains(position):
            return None
        cursor = self._projected_point_at(index, position)
        if cursor is None:
            return None
        view = self._sheet_views[index]
        model = getattr(self.window(), "model", None)
        if model is None:
            return None
        hidden = set(view.get("hidden_owners", ()))
        grid = self._segment_grid_for_view(index)
        candidates = []
        point = QPointF(*cursor)
        # Include the face interior, even far from every visible edge.
        for owner, face in grid.owner_faces().items():
            if owner in hidden or owner.removeprefix("bar:") not in model.bars:
                continue
            if face.contains(point):
                candidates.append(owner)
        edge_target = self._element_at(position, view_index=index)
        if edge_target is not None:
            owner = edge_target[5]
            if (owner not in hidden and owner.removeprefix("bar:") in model.bars
                    and (not candidates or owner in candidates)):
                return owner, cursor
        if not candidates:
            return None
        # Where silhouettes overlap, prefer the visible outline nearest the click.
        def distance(owner):
            return min(
                self._distance_to_segment(point, QPointF(*start), QPointF(*end))[0]
                for (start, end), source in zip(grid.segments, self._display_linework(view)[1])
                if source == owner
            )
        return min(candidates, key=distance), cursor

    def _member_break_click(self, position: QPointF) -> None:
        view_hit = self._annotation_view_at(position)
        if self._member_break_view_index is None or (
            view_hit is not None and view_hit != self._member_break_view_index
        ):
            if view_hit is not None:
                self._member_break_view_index = view_hit
                self.select_view(view_hit)
                self.member_break_step_changed.emit(1)
            return
        index = self._member_break_view_index
        target = self._member_break_target_at(position, index)
        if target is None:
            return
        owner, cursor = target
        view = self._sheet_views[index]
        axis = self._member_break_axis(view, owner)
        if axis is None:
            return
        points = [point for segment, source in zip(view.get("segments", ()), view.get("segment_owners", ()))
                  if source == owner for point in segment]
        if not points:
            return
        stations = [point[0] * axis[0] + point[1] * axis[1] for point in points]
        station = cursor[0] * axis[0] + cursor[1] * axis[1]
        end = int(station > (min(stations) + max(stations)) / 2.0)
        marks = view.setdefault("member_breaks", [])
        existing = next((mark for mark in marks if mark.get("owner") == owner and mark.get("end") == end), None)
        if existing is not None:
            marks.remove(existing)
        else:
            marks.append({"owner": owner, "end": end, "axis": list(axis)})
        self.invalidate_view_geometry(index)
        self._annotation_background = None
        self.update()
        self.layout_changed.emit()

    def _segment_grid_for_view(self, view_index: int) -> _SegmentSpatialGrid:
        view = self._sheet_views[view_index]
        segments = self._display_linework(view)[0]
        owners = self._display_linework(view)[1]
        cached = self._view_segment_grids.get(view_index)
        if cached is None or cached[0] is not segments or cached[1] is not owners:
            grid = _SegmentSpatialGrid(segments, owners)
            self._view_segment_grids[view_index] = (segments, owners, grid)
            return grid
        return cached[2]

    def projected_points_for_owners(self, view_index: int, owners) -> tuple[tuple[float, float], ...]:
        if not 0 <= view_index < len(self._sheet_views):
            return ()
        grid = self._segment_grid_for_view(view_index)
        return tuple(
            point
            for owner in owners
            for point in grid.owner_points.get(str(owner), ())
        )

    def _dimension_snap_at(
        self, position: QPointF, view_index: int | None = None,
        perpendicular_origin: tuple[float, float] | None = None,
    ):
        best = None
        enabled = self._enabled_dimension_snap_types()
        indices = (view_index,) if view_index is not None else range(len(self._sheet_views))
        for index in indices:
            if index is None or not 0 <= index < len(self._sheet_views):
                continue
            draw_data = self._view_draw_data.get(index)
            if draw_data is None or draw_data[4] <= 1e-12:
                continue
            center_x, center_y, target_x, target_y, model_to_pixels = draw_data
            projected_cursor = (
                center_x + (position.x() - target_x) / model_to_pixels,
                center_y - (position.y() - target_y) / model_to_pixels,
            )
            search_radius = 12.0 / model_to_pixels
            segment_grid = self._segment_grid_for_view(index)
            view = self._sheet_views[index]
            hidden_owners = {str(owner) for owner in view.get("hidden_owners", ())}
            segments = self._display_linework(view)[0]
            owners = self._display_linework(view)[1]
            cache_key = (
                index,
                id(segments),
                id(owners),
                tuple(sorted(enabled)),
                tuple(sorted(hidden_owners)),
            )
            snap_index = self._dimension_snap_cache.get(cache_key)
            if snap_index is None:
                visible_items = [
                    (
                        segment,
                        str(owners[segment_index]) if len(owners) == len(segment_grid.segments) else "",
                    )
                    for segment_index, segment in enumerate(segment_grid.segments)
                    if len(owners) != len(segment_grid.segments)
                    or str(owners[segment_index]) not in hidden_owners
                ]
                normalized_segments = tuple(segment for segment, _owner in visible_items)
                visible_grid = _SegmentSpatialGrid(
                    normalized_segments, tuple(owner for _segment, owner in visible_items),
                )
                candidates = []
                collinear_intervals: dict[tuple[float, float, float], list[tuple[float, float]]] = {}
                for first, second in normalized_segments:
                    if "endpoint" in enabled:
                        candidates.extend(((first, "endpoint"), (second, "endpoint")))
                    if "center" in enabled:
                        candidates.append((
                            ((first[0] + second[0]) / 2.0,
                             (first[1] + second[1]) / 2.0),
                            "center",
                        ))
                        dx, dy = second[0] - first[0], second[1] - first[1]
                        length = math.hypot(dx, dy)
                        if length > 1e-12:
                            ux, uy = dx / length, dy / length
                            if ux < 0.0 or (abs(ux) <= 1e-12 and uy < 0.0):
                                ux, uy = -ux, -uy
                            nx, ny = -uy, ux
                            line_offset = nx * first[0] + ny * first[1]
                            key = (round(ux, 7), round(uy, 7), round(line_offset, 7))
                            interval = sorted((
                                ux * first[0] + uy * first[1],
                                ux * second[0] + uy * second[1],
                            ))
                            collinear_intervals.setdefault(key, []).append(interval)
                if "center" in enabled:
                    for (ux, uy, line_offset), intervals in collinear_intervals.items():
                        intervals.sort()
                        merged_start, merged_end = intervals[0]
                        for interval_start, interval_end in intervals[1:]:
                            if interval_start <= merged_end + 1e-7:
                                merged_end = max(merged_end, interval_end)
                                continue
                            midpoint = (merged_start + merged_end) / 2.0
                            candidates.append((
                                (ux * midpoint - uy * line_offset,
                                 uy * midpoint + ux * line_offset),
                                "center",
                            ))
                            merged_start, merged_end = interval_start, interval_end
                        midpoint = (merged_start + merged_end) / 2.0
                        candidates.append((
                            (ux * midpoint - uy * line_offset,
                             uy * midpoint + ux * line_offset),
                            "center",
                        ))
                snap_index = _DimensionSnapIndex(
                    candidates, visible_grid, segments, owners,
                )
                self._dimension_snap_cache[cache_key] = snap_index
            normalized_segments = snap_index.segment_grid.segments
            for candidate, kind in snap_index.nearby_points(
                projected_cursor[0], projected_cursor[1], search_radius,
            ):
                screen = self._screen_point(index, candidate)
                if screen is None:
                    continue
                distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
                if best is None or distance < best[0]:
                    best = (distance, index, candidate, screen, kind)
            nearby_segments = snap_index.segment_grid.query(
                projected_cursor[0], projected_cursor[1], search_radius,
            )
            if "intersection" in enabled:
                for offset, first_index in enumerate(nearby_segments):
                    first_segment = normalized_segments[first_index]
                    for second_index in nearby_segments[offset + 1:]:
                        crossing = self._segment_intersection(
                            first_segment, normalized_segments[second_index],
                        )
                        if crossing is None:
                            continue
                        screen = self._screen_point(index, crossing)
                        if screen is None:
                            continue
                        distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
                        if best is None or distance < best[0]:
                            best = (distance, index, crossing, screen, "intersection")
            axis_segments = self._axis_dimension_snap_segments.get(index, ())
            if "intersection" in enabled and axis_segments:
                axis_grid = _SegmentSpatialGrid(axis_segments)
                nearby_axis_segments = axis_grid.query(
                    projected_cursor[0], projected_cursor[1], search_radius,
                )
                for offset, first_index in enumerate(nearby_axis_segments):
                    first_segment = axis_grid.segments[first_index]
                    for second_index in nearby_axis_segments[offset + 1:]:
                        second_segment = axis_grid.segments[second_index]
                        crossing = self._segment_intersection(first_segment, second_segment)
                        if crossing is None:
                            continue
                        screen = self._screen_point(index, crossing)
                        if screen is None:
                            continue
                        distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
                        if best is None or distance < best[0]:
                            best = (distance, index, crossing, screen, "intersection")
            if perpendicular_origin is not None:
                all_segments = [
                    normalized_segments[segment_index]
                    for segment_index in nearby_segments
                ]
                all_segments.extend(axis_segments)
                origin_x, origin_y = perpendicular_origin
                for start, end in all_segments:
                    dx, dy = end[0] - start[0], end[1] - start[1]
                    length_squared = dx * dx + dy * dy
                    if length_squared <= 1e-12:
                        continue
                    fraction = (
                        (origin_x - start[0]) * dx + (origin_y - start[1]) * dy
                    ) / length_squared
                    if not 0.0 <= fraction <= 1.0:
                        continue
                    perpendicular = (start[0] + fraction * dx, start[1] + fraction * dy)
                    screen = self._screen_point(index, perpendicular)
                    if screen is None:
                        continue
                    distance = math.hypot(screen.x() - position.x(), screen.y() - position.y())
                    if best is None or distance < best[0]:
                        best = (distance, index, perpendicular, screen, "perpendicular")
        if best is None or best[0] > 12.0:
            return None
        return best

    def _enabled_dimension_snap_types(self) -> set[str]:
        window = self.window()
        scene = getattr(window, "scene", None)
        if scene is None:
            return {"intersection", "endpoint", "center"}
        return {
            kind for kind in ("intersection", "endpoint", "center")
            if scene.snap_type_enabled(kind)
        }

    def _special_dimension_input(self, position, clicked):
        required = 3 if self._dimension_type == "angular" else 1
        old = self._dimension_preview_bounds
        old_snap = self._dimension_snap_screen
        if len(self._dimension_points) < required:
            snap = self._dimension_snap_at(position, self._dimension_view_index)
            self._dimension_snap_screen = snap[3] if snap else None
            self._dimension_snap_kind = snap[4] if snap else None
            self._dimension_hover_view_index = snap[1] if snap else None
            if clicked and snap:
                point = tuple(float(v) for v in snap[2])
                if any(math.dist(point, other) < 1e-9 for other in self._dimension_points):
                    return
                if self._dimension_view_index is None:
                    self._dimension_view_index = snap[1]
                    self.select_view(snap[1])
                if self._dimension_type == "level":
                    from .special_dimensions import elevation
                    if elevation(self, snap[1], point) is None:
                        return
                if self._dimension_type == "angular" and len(self._dimension_points) == 2:
                    vertex, start = self._dimension_points
                    trial = dict(vertex=vertex, start=start, end=point, offset=(point[0]-vertex[0], point[1]-vertex[1]))
                    if angular_geometry(trial) is None:
                        return
                self._dimension_points.append(point)
                self.dimension_step_changed.emit(len(self._dimension_points))
        else:
            vi = self._dimension_view_index
            self._dimension_hover_view_index = vi
            cursor = self._projected_point_at(vi, position)
            self._dimension_preview = make_dimension(self, vi, self._dimension_points, cursor) if cursor else None
            self._dimension_preview_bounds = self._dimension_screen_bounds(vi, self._dimension_preview) if self._dimension_preview else None
            self._dimension_snap_screen = None
            if clicked and self._dimension_preview:
                self._sheet_views[vi].setdefault("dimensions", []).append(self._dimension_preview)
                self.layout_changed.emit()
                self.set_dimension_mode(True, self._dimension_type)
                self.dimension_step_changed.emit(0)
                return
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        regions = [old, self._dimension_preview_bounds]
        for point in (old_snap, self._dimension_snap_screen):
            if point is not None:
                regions.append(QRectF(point.x()-16, point.y()-16, 32, 32))
        if any(region is not None for region in regions):
            self._update_annotation_regions(*regions)

    def _dimension_from_screen_point(self, view_index: int, position: QPointF):
        if len(self._dimension_points) != 2:
            return None
        third = self._projected_point_at(view_index, position)
        if third is None:
            return None
        first, second = self._dimension_points
        if self._dimension_type == "orthogonal":
            midpoint_x = (first[0] + second[0]) / 2.0
            midpoint_y = (first[1] + second[1]) / 2.0
            delta_x = abs(second[0] - first[0])
            delta_y = abs(second[1] - first[1])
            can_measure_x = delta_x > 1e-12
            can_measure_y = delta_y > 1e-12
            if not can_measure_x and not can_measure_y:
                return None
            choose_x = can_measure_x and (
                not can_measure_y
                or abs(third[1] - midpoint_y) >= abs(third[0] - midpoint_x)
            )
            if choose_x:
                offset = (0.0, third[1] - first[1])
                return {
                    "start": first,
                    "end": second,
                    "offset": offset,
                    "orthogonal_axis": "x",
                }
            offset = (third[0] - first[0], 0.0)
            return {
                "start": first,
                "end": second,
                "offset": offset,
                "orthogonal_axis": "y",
            }
        dx, dy = second[0] - first[0], second[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            return None
        normal = (-dy / length, dx / length)
        offset_amount = (third[0] - first[0]) * normal[0] + (third[1] - first[1]) * normal[1]
        return {
            "start": first,
            "end": second,
            "offset": (normal[0] * offset_amount, normal[1] * offset_amount),
        }

    @staticmethod
    def _dimension_line_points(dimension: dict) -> tuple[tuple[float, float], tuple[float, float]]:
        start = tuple(float(value) for value in dimension["start"])
        end = tuple(float(value) for value in dimension["end"])
        offset = tuple(float(value) for value in dimension["offset"])
        axis = dimension.get("orthogonal_axis")
        if axis == "x":
            line_y = start[1] + offset[1]
            return (start[0], line_y), (end[0], line_y)
        if axis == "y":
            line_x = start[0] + offset[0]
            return (line_x, start[1]), (line_x, end[1])
        return (
            (start[0] + offset[0], start[1] + offset[1]),
            (end[0] + offset[0], end[1] + offset[1]),
        )

    def _align_dimension_to_existing(
        self, view_index: int, dimension: dict, tolerance: float = 4.0,
    ) -> dict:
        """Snap a dimension line to a nearby parallel dimension in the same view."""
        if dimension.get("kind") in {"angular", "level"}:
            return dimension
        draw_data = self._view_draw_data.get(view_index)
        if draw_data is None or draw_data[4] <= 0:
            return dimension
        model_to_pixels = draw_data[4]
        start = tuple(float(value) for value in dimension["start"])
        source = self._screen_point(view_index, start)
        line_start, line_end = self._dimension_line_points(dimension)
        moving_start = self._screen_point(view_index, line_start)
        moving_end = self._screen_point(view_index, line_end)
        if None in (source, moving_start, moving_end):
            return dimension
        moving_dx = moving_end.x() - moving_start.x()
        moving_dy = moving_end.y() - moving_start.y()
        moving_length = math.hypot(moving_dx, moving_dy)
        if moving_length <= 1e-9:
            return dimension
        moving_axis = (moving_dx / moving_length, moving_dy / moving_length)
        moving_normal = (-moving_axis[1], moving_axis[0])
        current_distance = (
            (moving_start.x() - source.x()) * moving_normal[0]
            + (moving_start.y() - source.y()) * moving_normal[1]
        )
        best = None
        for other in self._sheet_views[view_index].get("dimensions", ()):
            if other is dimension or other.get("kind") in {"angular", "level"}:
                continue
            try:
                other_line = self._dimension_line_points(other)
            except (KeyError, TypeError, ValueError):
                continue
            other_line_start = self._screen_point(view_index, other_line[0])
            other_line_end = self._screen_point(view_index, other_line[1])
            if other_line_start is None or other_line_end is None:
                continue
            other_dx = other_line_end.x() - other_line_start.x()
            other_dy = other_line_end.y() - other_line_start.y()
            other_length = math.hypot(other_dx, other_dy)
            if other_length <= 1e-9:
                continue
            other_axis = (other_dx / other_length, other_dy / other_length)
            if abs(moving_axis[0] * other_axis[0] + moving_axis[1] * other_axis[1]) < 0.999999:
                continue
            target_distance = (
                (other_line_start.x() - source.x()) * moving_normal[0]
                + (other_line_start.y() - source.y()) * moving_normal[1]
            )
            delta = target_distance - current_distance
            if abs(delta) > tolerance:
                continue
            if best is None or abs(delta) < best[0]:
                best = (abs(delta), target_distance)
        if best is None:
            return dimension
        target_distance = best[1]
        aligned = dict(dimension)
        aligned["offset"] = (
            moving_normal[0] * target_distance / model_to_pixels,
            -moving_normal[1] * target_distance / model_to_pixels,
        )
        return aligned

    def _draw_dimension(
        self, painter: QPainter, view_index: int, dimension: dict,
        dimension_index: int | None = None,
    ) -> QRectF | None:
        if dimension.get("kind") in {"angular", "level"}:
            return draw_dimension(self, painter, view_index, dimension, dimension_index)
        try:
            first = tuple(float(value) for value in dimension["start"])
            second = tuple(float(value) for value in dimension["end"])
            if len(first) != 2 or len(second) != 2:
                return None
            line_first, line_second = self._dimension_line_points(dimension)
        except (KeyError, TypeError, ValueError):
            return None
        first_screen = self._screen_point(view_index, first)
        second_screen = self._screen_point(view_index, second)
        dim_first = self._screen_point(view_index, line_first)
        dim_second = self._screen_point(view_index, line_second)
        if None in (first_screen, second_screen, dim_first, dim_second):
            return None
        dx, dy = dim_second.x() - dim_first.x(), dim_second.y() - dim_first.y()
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            return None
        axis = (dx / length, dy / length)
        normal = (-axis[1], axis[0])
        pen = QPen(QColor("#24292f"), 1.0)
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        def dimension_color(key: str, default: str) -> QColor:
            color = QColor(str(self._project_settings.get(key, default)))
            return color if color.isValid() else QColor(default)

        line_extension = max(
            0.0,
            float(self._project_settings.get("dimension_line_extension_mm", 3.0))
            * self._sheet_pixels_per_mm,
        )
        line_start = QPointF(
            dim_first.x() - axis[0] * line_extension,
            dim_first.y() - axis[1] * line_extension,
        )
        line_end = QPointF(
            dim_second.x() + axis[0] * line_extension,
            dim_second.y() + axis[1] * line_extension,
        )
        dimension_bounds = QRectF(line_start, line_end).normalized()
        # Witness lines extend slightly beyond the dimension line and leave a small gap
        # at the measured point, as in the architectural reference.
        extension_pen = QPen(dimension_color("dimension_extension_color", "#ff0000"), 1.0)
        extension_pen.setCosmetic(True)
        painter.setPen(extension_pen)
        for source, target in ((first_screen, dim_first), (second_screen, dim_second)):
            vx, vy = target.x() - source.x(), target.y() - source.y()
            magnitude = math.hypot(vx, vy)
            if magnitude > 1e-9:
                unit = (vx / magnitude, vy / magnitude)
                extension_gap = max(
                    0.0,
                    float(self._project_settings.get("dimension_extension_gap_mm", 1.0))
                    * self._sheet_pixels_per_mm,
                )
                extension_overrun = max(
                    0.0,
                    float(self._project_settings.get("dimension_extension_overrun_mm", 3.0))
                    * self._sheet_pixels_per_mm,
                )
                witness_start = QPointF(
                    source.x() + unit[0] * extension_gap,
                    source.y() + unit[1] * extension_gap,
                )
                witness_end = QPointF(
                    target.x() + unit[0] * extension_overrun,
                    target.y() + unit[1] * extension_overrun,
                )
                painter.drawLine(
                    witness_start,
                    witness_end,
                )
                dimension_bounds = dimension_bounds.united(
                    QRectF(witness_start, witness_end).normalized(),
                )
        line_pen = QPen(dimension_color("dimension_line_color", "#ff0000"), 1.0)
        line_pen.setCosmetic(True)
        painter.setPen(line_pen)
        painter.drawLine(line_start, line_end)
        tick = (
            float(self._project_settings.get("dimension_terminator_height_mm", 3.0))
            * self._sheet_pixels_per_mm / 2.0
        )
        tick_direction = ((normal[0] + axis[0]) / math.sqrt(2.0),
                          (normal[1] + axis[1]) / math.sqrt(2.0))
        terminator_pen = QPen(dimension_color("dimension_terminator_color", "#ff0000"), 1.0)
        terminator_pen.setCosmetic(True)
        painter.setPen(terminator_pen)
        for point in (dim_first, dim_second):
            tick_start = QPointF(
                point.x() - tick_direction[0] * tick,
                point.y() - tick_direction[1] * tick,
            )
            tick_end = QPointF(
                point.x() + tick_direction[0] * tick,
                point.y() + tick_direction[1] * tick,
            )
            painter.drawLine(
                tick_start,
                tick_end,
            )
            dimension_bounds = dimension_bounds.united(
                QRectF(tick_start, tick_end).normalized(),
            )
        orthogonal_axis = dimension.get("orthogonal_axis")
        if orthogonal_axis == "x":
            numeric_value = abs(second[0] - first[0])
        elif orthogonal_axis == "y":
            numeric_value = abs(second[1] - first[1])
        else:
            numeric_value = math.hypot(second[0] - first[0], second[1] - first[1])
        unit_scales = {"m": 1.0, "cm": 100.0, "dm": 10.0, "mm": 1000.0}
        unit_key = str(dimension.get(
            "unit", self._project_settings.get("dimension_unit", "cm"),
        )).lower()
        unit_scale = unit_scales.get(unit_key, unit_scales["cm"])
        try:
            decimal_places = max(0, min(8, int(dimension.get(
                "decimal_places", self._project_settings.get("dimension_decimal_places", 0),
            ))))
        except (TypeError, ValueError):
            decimal_places = 0
        displayed_value = numeric_value * unit_scale
        text = f"{displayed_value:.{decimal_places}f}"
        font = QFont(painter.font())
        height_mm = float(self._project_settings.get("dimension_text_height_mm", 3.0))
        font.setPixelSize(max(1, round(height_mm * self._sheet_pixels_per_mm)))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(text)
        midpoint = QPointF((dim_first.x() + dim_second.x()) / 2.0,
                           (dim_first.y() + dim_second.y()) / 2.0)
        text_position = str(self._project_settings.get("dimension_text_position", "superior"))
        rotation = math.degrees(math.atan2(axis[1], axis[0]))
        if rotation > 90.0:
            rotation -= 180.0
        elif rotation < -90.0:
            rotation += 180.0
        text_width_with_padding = text_width + 6.0 * self._sheet_pixels_per_mm
        text_height_with_padding = metrics.height() + 2.0 * self._sheet_pixels_per_mm
        text_gap = self._sheet_pixels_per_mm
        if text_position == "superior":
            text_top = -text_height_with_padding - text_gap
        elif text_position == "inferior":
            text_top = text_gap
        else:
            text_top = -text_height_with_padding / 2.0
        text_rect = QRectF(
            -text_width_with_padding / 2.0,
            text_top,
            text_width_with_padding,
            text_height_with_padding,
        )
        rotated_text_bounds = self._rotated_text_rect(
            midpoint,
            text_rect.width(),
            text_rect.top(),
            text_rect.bottom(),
            rotation,
        )
        dimension_bounds = dimension_bounds.united(rotated_text_bounds)
        if dimension_index is not None:
            selection_padding_x = 3.0 * self._sheet_pixels_per_mm
            selection_padding_y = 2.0 * self._sheet_pixels_per_mm
            if self._selected_dimension == (view_index, dimension_index):
                dimension_bounds = dimension_bounds.united(rotated_text_bounds.adjusted(
                    -selection_padding_x, -selection_padding_y,
                    selection_padding_x, selection_padding_y,
                ))
            self._dimension_bounds[(view_index, dimension_index)] = dimension_bounds.adjusted(
                -2.0, -2.0, 2.0, 2.0,
            )
        painter.save()
        painter.translate(midpoint)
        painter.rotate(rotation)
        painter.setPen(dimension_color("dimension_text_color", "#000000"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        if dimension_index is not None:
            selection_padding_x = 3.0 * self._sheet_pixels_per_mm
            selection_padding_y = 2.0 * self._sheet_pixels_per_mm
            self._dimension_text_hit_rects[(view_index, dimension_index)] = rotated_text_bounds.adjusted(
                -selection_padding_x,
                -selection_padding_y,
                selection_padding_x,
                selection_padding_y,
            )
            if self._selected_dimension == (view_index, dimension_index):
                selection_pen = QPen(QColor("#0969da"), 1.25)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(text_rect.adjusted(
                    -selection_padding_x,
                    -selection_padding_y,
                    selection_padding_x,
                    selection_padding_y,
                ))
        painter.restore()
        if dimension_index is not None and self._selected_dimension == (view_index, dimension_index):
            handle_radius = 4.0
            handle_hit_radius = 9.0
            handle_pen = QPen(QColor("#0969da"), 1.5)
            handle_pen.setCosmetic(True)
            painter.setPen(handle_pen)
            painter.setBrush(QColor("#ffffff"))
            for endpoint_name, point in (("start", first_screen), ("end", second_screen)):
                painter.drawEllipse(point, handle_radius, handle_radius)
                self._dimension_endpoint_hit_rects[(view_index, dimension_index, endpoint_name)] = (
                    QRectF(point.x() - handle_hit_radius, point.y() - handle_hit_radius,
                           handle_hit_radius * 2.0, handle_hit_radius * 2.0)
                )
                dimension_bounds = dimension_bounds.united(
                    QRectF(point.x() - handle_hit_radius, point.y() - handle_hit_radius,
                           handle_hit_radius * 2.0, handle_hit_radius * 2.0)
                )
            self._dimension_bounds[(view_index, dimension_index)] = dimension_bounds.adjusted(
                -2.0, -2.0, 2.0, 2.0,
            )
        painter.restore()
        return dimension_bounds.adjusted(-2.0, -2.0, 2.0, 2.0)

    def _element_at(self, position: QPointF, view_index: int | None = None):
        if self._stamp_rect.contains(position):
            return None
        best = None
        view_indices = (view_index,) if view_index is not None else range(len(self._sheet_views))
        for index in view_indices:
            if index is None or not 0 <= index < len(self._sheet_views):
                continue
            view = self._sheet_views[index]
            draw_data = self._view_draw_data.get(index)
            if draw_data is None:
                continue
            center_x, center_y, target_x, target_y, model_to_pixels = draw_data
            grid = self._segment_grid_for_view(index)
            segments = grid.segments
            owners = self._display_linework(view)[1]
            if model_to_pixels <= 1e-12:
                continue
            projected_cursor = (
                center_x + (position.x() - target_x) / model_to_pixels,
                center_y - (position.y() - target_y) / model_to_pixels,
            )
            candidate_indices = grid.query(
                projected_cursor[0], projected_cursor[1], 12.0 / model_to_pixels,
            )
            hidden_owners = {str(owner) for owner in view.get("hidden_owners", ())}
            for segment_index in candidate_indices:
                start, end = segments[segment_index]
                start_screen = QPointF(
                    target_x + (float(start[0]) - center_x) * model_to_pixels,
                    target_y - (float(start[1]) - center_y) * model_to_pixels,
                )
                end_screen = QPointF(
                    target_x + (float(end[0]) - center_x) * model_to_pixels,
                    target_y - (float(end[1]) - center_y) * model_to_pixels,
                )
                distance, fraction = self._distance_to_segment(position, start_screen, end_screen)
                if best is None or distance < best[0]:
                    projected_point = (
                        float(start[0]) + (float(end[0]) - float(start[0])) * fraction,
                        float(start[1]) + (float(end[1]) - float(start[1])) * fraction,
                    )
                    owner = str(owners[segment_index]) if len(owners) == len(segments) else ""
                    if self._element_visibility_mode == "reveal":
                        if owner not in hidden_owners:
                            continue
                    elif owner in hidden_owners:
                        continue
                    best = (distance, index, owner, projected_point)
        if best is None or best[0] > 12.0:
            return None
        distance, view_index, owner, projected_point = best
        hover_owners = {(view_index, owner)} if owner else set()
        selected_owner = owner
        if owner.startswith("bar:"):
            model = getattr(self.window(), "model", None)
            member_name = owner.partition(":")[2]
            group = model.verification_group_for(member_name) if model is not None else None
            if group is not None:
                members = tuple(str(name) for name in group.get("members", ()))
                hover_owners = {
                    (view_index, f"bar:{member}") for member in members
                }
                if self._element_visibility_mode == "reveal":
                    hidden_owners = {
                        str(token) for token in self._sheet_views[view_index].get("hidden_owners", ())
                    }
                    hover_owners = {
                        key for key in hover_owners if key[1] in hidden_owners
                    }
                if not self._identification_pick_member:
                    selected_owner = "bar_group:" + "|".join(members)
        return distance, view_index, selected_owner, projected_point, hover_owners, owner

    def _identify_element_at(self, position: QPointF) -> bool:
        target = self._element_at(position)
        if target is None:
            return False
        _distance, view_index, element_name, projected_point, _hover_owners, _raw_owner = target
        self.select_view(view_index)
        self.element_identification_requested.emit(view_index, element_name, projected_point)
        return True

    def _element_visibility_click(self, position: QPointF) -> None:
        mode = self._element_visibility_mode
        if mode is None:
            return
        view_hit = next((
            index for index, rect in reversed(tuple(self._view_hit_rects.items()))
            if rect.contains(position)
        ), None)
        if self._selected_view_index is None:
            if view_hit is not None:
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._activate_element_visibility_view(view_hit)
            return
        if view_hit is not None and view_hit != self._selected_view_index:
            self._activate_element_visibility_view(view_hit)
            return
        if mode == "reveal_all":
            self._activate_element_visibility_view(self._selected_view_index)
            return
        view_index = self._selected_view_index
        if not 0 <= view_index < len(self._sheet_views):
            return
        target = self._element_at(position, view_index=view_index)
        if target is None or not target[5]:
            return
        selected_owners = {key[1] for key in target[4]}
        if not selected_owners:
            selected_owners = {str(target[5])}
        if self._element_visibility_pending_view_index != view_index:
            self._element_visibility_pending.clear()
            self._element_visibility_pending_view_index = view_index
        if selected_owners.issubset(self._element_visibility_pending):
            self._element_visibility_pending.difference_update(selected_owners)
        else:
            self._element_visibility_pending.update(selected_owners)
        self._hover_owners = {
            (view_index, owner) for owner in self._element_visibility_pending
        }
        self._hover_raw_target = None
        self.update()

    def wheelEvent(self, event) -> None:
        self._annotation_background = None
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        old_zoom = self._zoom_factor
        new_zoom = max(0.25, min(128.0, old_zoom * (1.15 ** (delta / 120.0))))
        if new_zoom == old_zoom:
            event.accept()
            return
        pointer = event.position()
        center = QPointF(self.width() / 2, self.height() / 2)
        ratio = new_zoom / old_zoom
        relative_pointer = pointer - center
        self._pan_offset = relative_pointer - (relative_pointer - self._pan_offset) * ratio
        self._zoom_factor = new_zoom
        self._begin_navigation()
        super().update()
        event.accept()

    def cancel_identification_resize(self):
        if self._drag_identification_resize is None:
            return False
        vi, ii, _start, original, *_rest = self._drag_identification_resize
        item = self._sheet_views[vi]["identifications"][ii]
        item.clear()
        item.update(original)
        self._drag_identification_resize = None
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()
        return True

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.MiddleButton:
            self._ensure_navigation_geometry()
        if event.button() == Qt.MouseButton.LeftButton and not any((
            self._annotation_mode, self._dimension_mode, self._identification_mode,
            self._detail_identifier_mode, self._elevation_identifier_mode,
            self._element_visibility_mode, self._member_break_mode,
        )):
            for (vi, ii), (handle, width, height) in self._identification_resize_handles.items():
                if vi == self._selected_view_index and handle.contains(event.position()):
                    item = self._sheet_views[vi]["identifications"][ii]
                    point = item.get("projected_point") or self._project_world_point(self._sheet_views[vi], item.get("world_point", ()))
                    self._drag_identification_resize = (vi, ii, QPointF(event.position()), dict(item), width, height, tuple(point))
                    self._annotation_background = None
                    self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    event.accept()
                    return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._annotation_background = None
            self._pan_anchor = event.position()
            self._pan_origin = QPointF(self._pan_offset)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._member_break_mode:
                self._member_break_click(event.position())
                event.accept()
                return
            if not any((self._annotation_mode, self._dimension_mode, self._identification_mode,
                        self._detail_identifier_mode, self._elevation_identifier_mode, self._element_visibility_mode)):
                hit = self._member_break_at(event.position())
                self._selected_member_break = hit
                if hit is not None:
                    index, mark_index = hit
                    self.select_view(index)
                    mark = self._sheet_views[index]["member_breaks"][mark_index]
                    axis, bottom, top = self._member_break_axis_range(self._sheet_views[index], mark)
                    lines = self._member_break_symbols(self._sheet_views[index])[mark_index]
                    points = [lines[0][0], *(line[1] for line in lines)]
                    station = sum(sum(p[i] * axis[i] for i in range(2)) for p in points) / len(points)
                    cursor = self._projected_point_at(index, event.position())
                    self._drag_member_break = index, mark_index, dict(mark), cursor, (station - bottom) / (top - bottom)
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                    self.update()
                    event.accept()
                    return
            if self._annotation_mode is not None:
                self._sheet_annotation_click(event.position(), event.modifiers())
                event.accept()
                return
            table_hit = next((index for index, rect in reversed(tuple(self._sheet_table_hit_rects.items()))
                              if rect.contains(event.position())), None)
            if table_hit is not None and not any((self._dimension_mode, self._identification_mode,
                                                 self._detail_identifier_mode, self._elevation_identifier_mode,
                                                 self._element_visibility_mode)):
                self._selected_sheet_table = table_hit
                self._selected_sheet_text = None
                self._selected_sheet_line = None
                self._selected_component_detail_group = None
                self.select_view(None)
                self._begin_sheet_annotation_drag()
                self._drag_sheet_table = table_hit
                self._table_drag_raw_bounds = QRectF(self._sheet_table_hit_rects[table_hit])
                self._table_drag_snap_segments = self._table_snap_segments()
                self._drag_position = event.position()
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.update()
                event.accept()
                return
            if self._selected_sheet_table is not None:
                self._selected_sheet_table = None
                self.update()
            line_handle = next((
                key for key, rect in self._sheet_line_handle_hit_rects.items()
                if rect.contains(event.position())
            ), None)
            if line_handle is not None:
                self._begin_sheet_annotation_drag()
                self._drag_sheet_line_endpoint = line_handle
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
                event.accept()
                return
            text_handle = next((
                key for key, rect in reversed(tuple(self._sheet_text_handle_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if text_handle is not None:
                self._begin_sheet_annotation_drag()
                self._selected_sheet_text = text_handle
                self._selected_sheet_line = None
                self._drag_sheet_text_handle = text_handle
                self._drag_position = event.position()
                self._drag_sheet_text_bounds = QRectF(self._sheet_text_hit_rects[text_handle])
                self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
                self.update()
                event.accept()
                return
            text_hit = next((
                key for key, rect in reversed(tuple(self._sheet_text_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if text_hit is not None:
                self._selected_sheet_text = text_hit
                self._selected_sheet_line = None
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._drag_sheet_text = text_hit
                self._drag_position = event.position()
                had_group_selection = self._selected_component_detail_group is not None
                self._selected_component_detail_group = None
                self.select_view(None)
                self._begin_sheet_annotation_drag()
                if had_group_selection:
                    self.update()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.update()
                event.accept()
                return
            line_hit = self._sheet_line_at(event.position())
            if line_hit is not None:
                self._selected_sheet_line = line_hit
                self._selected_sheet_text = None
                self._selected_component_detail_group = None
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.select_view(None)
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                self.update()
                event.accept()
                return
            if self._selected_sheet_text is not None:
                self._selected_sheet_text = None
                self.update()
            if self._selected_sheet_line is not None:
                self._selected_sheet_line = None
                self.update()
            if self._element_visibility_mode is not None:
                self._element_visibility_click(event.position())
                event.accept()
                return
            if self._detail_identifier_mode:
                self._detail_identifier_click(event.position())
                event.accept()
                return
            if self._elevation_identifier_mode:
                self._elevation_identifier_click(event.position(), event.modifiers())
                event.accept()
                return
            if self._dimension_mode:
                if self._dimension_type in {"angular", "level"}:
                    self._special_dimension_input(event.position(), True)
                    event.accept()
                    return
                if len(self._dimension_points) < 2:
                    snap = self._dimension_snap_at(
                        event.position(), self._dimension_view_index,
                        perpendicular_origin=(
                            self._dimension_points[0] if self._dimension_points else None
                        ),
                    )
                    if snap is None:
                        event.accept()
                        return
                    _distance, view_index, projected, _screen, _kind = snap
                    if self._dimension_view_index is None:
                        self._dimension_view_index = view_index
                        self.select_view(view_index)
                    elif math.hypot(
                        projected[0] - self._dimension_points[0][0],
                        projected[1] - self._dimension_points[0][1],
                    ) <= 1e-9:
                        event.accept()
                        return
                    self._dimension_points.append(projected)
                    self._dimension_snap_screen = None
                    self._dimension_hover_projected = None
                    self._dimension_hover_view_index = view_index
                    self._dimension_preview = None
                    self._dimension_preview_bounds = None
                    if len(self._dimension_points) == 1:
                        self.dimension_step_changed.emit(1)
                    else:
                        self.dimension_step_changed.emit(2)
                    self.update()
                    event.accept()
                    return
                dimension = self._dimension_from_screen_point(
                    self._dimension_view_index, event.position(),
                )
                if dimension is not None:
                    dimension = self._align_dimension_to_existing(
                        self._dimension_view_index, dimension,
                    )
                    view = self._sheet_views[self._dimension_view_index]
                    view.setdefault("dimensions", []).append(dimension)
                    self.update()
                    self.layout_changed.emit()
                    self.set_dimension_mode(True, self._dimension_type)
                    self.dimension_step_changed.emit(0)
                event.accept()
                return
            self._selected_detail_identifier = None
            self.detail_identifier_selection_changed.emit(None)
            self._selected_elevation_identifier = None
            self.elevation_identifier_selection_changed.emit(None)
            selected_view = self._selected_view_index
            dimension_endpoint_hit = next((
                key for key, rect in reversed(tuple(self._dimension_endpoint_hit_rects.items()))
                if key[0] == selected_view and rect.contains(event.position())
            ), None)
            if dimension_endpoint_hit is not None:
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._selected_dimension = dimension_endpoint_hit[:2]
                self._drag_dimension_endpoint = dimension_endpoint_hit
                self._drag_position = event.position()
                self._selected_identification_index = None
                self._selected_identification_indices.clear()
                self.identification_selection_changed.emit(None)
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            detail_identifier_handle_hit = next((
                key for key, rect in reversed(tuple(self._detail_identifier_handle_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if detail_identifier_handle_hit is not None:
                view_index, identifier_index, _handle_name = detail_identifier_handle_hit
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._selected_dimension = None
                self.select_view(view_index)
                self._selected_detail_identifier = (view_index, identifier_index)
                self.detail_identifier_selection_changed.emit(
                    self._sheet_views[view_index].get("detail_identifiers", ())[identifier_index]
                )
                self._drag_detail_identifier_handle = detail_identifier_handle_hit
                self._drag_position = event.position()
                self._selected_identification_index = None
                self._selected_identification_indices.clear()
                self.identification_selection_changed.emit(None)
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            detail_identifier_hit = next((
                key for key, rect in reversed(tuple(self._detail_identifier_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if detail_identifier_hit is not None:
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._selected_dimension = None
                self.select_view(detail_identifier_hit[0])
                self._selected_detail_identifier = detail_identifier_hit
                view_index, identifier_index = detail_identifier_hit
                self.detail_identifier_selection_changed.emit(
                    self._sheet_views[view_index].get("detail_identifiers", ())[identifier_index]
                )
                self._drag_detail_identifier = detail_identifier_hit
                self._drag_position = event.position()
                self._selected_identification_index = None
                self._selected_identification_indices.clear()
                self.identification_selection_changed.emit(None)
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            elevation_identifier_hit = next((
                key for key, rect in reversed(tuple(self._elevation_identifier_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if elevation_identifier_hit is not None:
                view_index, identifier_index = elevation_identifier_hit
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._selected_dimension = None
                self.select_view(view_index)
                self._selected_elevation_identifier = elevation_identifier_hit
                identifiers = self._sheet_views[view_index].get("elevation_identifiers", ())
                if 0 <= identifier_index < len(identifiers):
                    self.elevation_identifier_selection_changed.emit(identifiers[identifier_index])
                self._drag_elevation_identifier = elevation_identifier_hit
                bounds = self._elevation_identifier_bounds.get(elevation_identifier_hit)
                self._drag_elevation_identifier_bounds = (
                    QRectF(bounds) if bounds is not None else None
                )
                self._drag_position = event.position()
                self._selected_identification_index = None
                self._selected_identification_indices.clear()
                self.identification_selection_changed.emit(None)
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            axis_hit = next((
                key for key, rect in reversed(tuple(self._axis_endpoint_hit_rects.items()))
                if key[0] == selected_view and rect.contains(event.position())
            ), None)
            if axis_hit is not None:
                self.select_view(axis_hit[0])
                self._selected_dimension = None
                self._selected_view_title_index = None
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if axis_hit in self._selected_axis_endpoints:
                        self._selected_axis_endpoints.remove(axis_hit)
                    else:
                        self._selected_axis_endpoints.add(axis_hit)
                    self._drag_axis_endpoints = ()
                    self._drag_position = None
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                    self.update()
                    event.accept()
                    return
                if axis_hit not in self._selected_axis_endpoints or len(self._selected_axis_endpoints) < 2:
                    self._selected_axis_endpoints = {axis_hit}
                self._drag_axis_endpoints = tuple(sorted(self._selected_axis_endpoints))
                self._drag_axis_current_bounds.clear()
                self._drag_axis_painted_bounds.clear()
                self._drag_axis_frame_current_bounds.clear()
                self._drag_axis_frame_painted_bounds.clear()
                for view_index, endpoint_key in self._drag_axis_endpoints:
                    axis_key = endpoint_key.rsplit(":", 1)[0]
                    bounds = self._axis_bounds_at_positions(view_index, axis_key)
                    if bounds is not None:
                        self._drag_axis_current_bounds[(view_index, axis_key)] = QRectF(bounds)
                        self._drag_axis_painted_bounds[(view_index, axis_key)] = QRectF(bounds)
                    frame = self._view_hit_rects.get(view_index)
                    if frame is not None:
                        self._drag_axis_frame_current_bounds[view_index] = QRectF(frame)
                        self._drag_axis_frame_painted_bounds[view_index] = QRectF(frame)
                self._drag_position = event.position()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
            group_title_hit = next((
                group_id for group_id, rect in reversed(
                    tuple(self._component_group_title_hit_rects.items())
                ) if rect.contains(event.position())
            ), None)
            if group_title_hit is not None:
                self._selected_component_detail_group = group_title_hit
                self._selected_view_title_index = None
                self.select_view(None)
                self.selection_changed.emit(self._component_detail_group_selection(group_title_hit))
                self._drag_component_detail_label = group_title_hit
                self._drag_position = event.position()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            title_hit = next((
                index for index, rect in reversed(tuple(self._view_title_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if title_hit is not None:
                self.select_view(title_hit)
                self._selected_dimension = None
                self._selected_axis_endpoints.clear()
                self._selected_view_title_index = title_hit
                self._drag_view_title_index = title_hit
                title_bounds = self._view_title_hit_rects.get(title_hit)
                self._drag_title_current_bounds = (
                    QRectF(title_bounds) if title_bounds is not None else None
                )
                self._drag_title_painted_bounds = (
                    QRectF(title_bounds) if title_bounds is not None else None
                )
                title_frame = self._view_hit_rects.get(title_hit)
                self._drag_title_frame_current_bounds = (
                    QRectF(title_frame) if title_frame is not None else None
                )
                self._drag_title_frame_painted_bounds = (
                    QRectF(title_frame) if title_frame is not None else None
                )
                self._drag_position = event.position()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
            hit_dimension = None if self._identification_mode else next((
                key for key, rect in reversed(tuple(self._dimension_text_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if hit_dimension is not None:
                if self._selected_view_index != hit_dimension[0]:
                    self._selected_view_title_index = None
                    self._selected_axis_endpoints.clear()
                    self._drag_dimension_index = None
                    self.select_view(hit_dimension[0])
                    event.accept()
                    return
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._selected_dimension = hit_dimension
                self._drag_dimension_index = hit_dimension
                initial_bounds = self._dimension_bounds.get(hit_dimension)
                if initial_bounds is not None:
                    selection_padding = max(3.0, 3.0 * self._sheet_pixels_per_mm)
                    initial_bounds = initial_bounds.adjusted(
                        -selection_padding, -selection_padding,
                        selection_padding, selection_padding,
                    )
                self._drag_dimension_current_bounds = (
                    QRectF(initial_bounds) if initial_bounds is not None else None
                )
                self._drag_dimension_painted_bounds = (
                    QRectF(initial_bounds) if initial_bounds is not None else None
                )
                content_bounds = self._view_dimension_bounds.get(hit_dimension)
                self._drag_dimension_content_current_bounds = (
                    QRectF(content_bounds) if content_bounds is not None else None
                )
                self._drag_position = event.position()
                self._selected_identification_index = None
                self._selected_identification_indices.clear()
                self.identification_selection_changed.emit(None)
                self.update()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                event.accept()
                return
            self._selected_dimension = None
            self._drag_dimension_index = None
            if self._identification_mode:
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self._last_identification_position = event.position()
                self._identify_element_at(event.position())
                event.accept()
                return
            selected_index = self._selected_view_index
            if selected_index is not None:
                label_index = next((
                    label_index
                    for (view_index, label_index), rect in reversed(
                        tuple(self._identification_hit_rects.items())
                    )
                    if view_index == selected_index and rect.contains(event.position())
                ), None)
                if label_index is not None:
                    self._selected_view_title_index = None
                    self._selected_axis_endpoints.clear()
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        if label_index in self._selected_identification_indices:
                            self._selected_identification_indices.remove(label_index)
                        else:
                            self._selected_identification_indices.add(label_index)
                        self._selected_identification_index = (
                            max(self._selected_identification_indices)
                            if self._selected_identification_indices else None
                        )
                        self._drag_identification_index = None
                        self._drag_identification_indices = ()
                        self._drag_position = None
                        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                    else:
                        if label_index not in self._selected_identification_indices:
                            self._selected_identification_indices = {label_index}
                        self._selected_identification_index = label_index
                        self._drag_identification_index = label_index
                        self._drag_identification_indices = tuple(
                            sorted(self._selected_identification_indices)
                        )
                        self._drag_identification_current_bounds = {
                            index: QRectF(bounds)
                            for index in self._drag_identification_indices
                            if (bounds := self._identification_hit_rects.get((selected_index, index))) is not None
                        }
                        self._drag_identification_painted_bounds = {
                            index: QRectF(bounds)
                            for index, bounds in self._drag_identification_current_bounds.items()
                        }
                        self._drag_position = event.position()
                        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                    self._emit_identification_selection()
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    self.update()
                    event.accept()
                    return
            if self._stamp_rect.contains(event.position()):
                had_group_selection = self._selected_component_detail_group is not None
                self._selected_component_detail_group = None
                self._selected_view_title_index = None
                self._selected_axis_endpoints.clear()
                self.select_view(None)
                if had_group_selection:
                    self.update()
                super().mousePressEvent(event)
                return
            group_hit = next((
                group_id for group_id, rect in reversed(
                    tuple(self._component_group_hit_rects.items())
                ) if rect.contains(event.position()) and not any(
                    child_rect.contains(event.position())
                    for child_index, child_rect in self._view_hit_rects.items()
                    if str((self._sheet_views[child_index].get("component_detail_group") or {}).get("id")) == group_id
                )
            ), None)
            if group_hit is not None:
                self._selected_component_detail_group = group_hit
                self._selected_view_title_index = None
                self.select_view(None)
                self.selection_changed.emit(self._component_detail_group_selection(group_hit))
                self._drag_component_detail_group = group_hit
                self._drag_position = event.position()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
                event.accept()
                return
            selected = next(
                (
                    index for index, rect in reversed(tuple(self._view_hit_rects.items()))
                    if rect.contains(event.position())
                ),
                None,
            )
            had_group_selection = self._selected_component_detail_group is not None
            self._selected_component_detail_group = None
            self._selected_view_title_index = None
            self._selected_axis_endpoints.clear()
            self.select_view(selected)
            if had_group_selection:
                self.update()
            if selected is not None:
                self._drag_position = event.position()
                view_bounds = self._view_hit_rects.get(selected)
                if view_bounds is not None:
                    view_bounds = view_bounds.adjusted(-3.0, -3.0, 3.0, 3.0)
                self._drag_view_index = selected
                self._drag_view_current_bounds = (
                    QRectF(view_bounds) if view_bounds is not None else None
                )
                self._drag_view_painted_bounds = (
                    QRectF(view_bounds) if view_bounds is not None else None
                )
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_identification_resize is not None and event.buttons() & Qt.MouseButton.LeftButton:
            vi, ii, start, original, width, height, point = self._drag_identification_resize
            item = self._sheet_views[vi]["identifications"][ii]
            angle = float(item.get("text_rotation_degrees", 0.))
            delta = QTransform().rotate(-angle).map(event.position()-start) / max(self._sheet_pixels_per_mm, .01)
            new_width = max(5., width + delta.x())
            item["width_mm"] = new_width
            item["height_mm"] = max(3., height + delta.y())
            shift = QTransform().rotate(angle).map(QPointF((new_width-width)/2, 0))
            factor = float(self._sheet_views[vi].get("scale_denominator", 10)) / 1000
            item["projected_point"] = (point[0]+shift.x()*factor, point[1]-shift.y()*factor)
            self.update()
            event.accept()
            return
        if self._drag_member_break is not None and event.buttons() & Qt.MouseButton.LeftButton:
            index, mark_index, _original, start, initial = self._drag_member_break
            view = self._sheet_views[index]
            mark = view["member_breaks"][mark_index]
            axis, bottom, top = self._member_break_axis_range(view, mark)
            cursor = self._projected_point_at(index, event.position())
            if cursor is not None and top - bottom > 1e-12:
                delta = sum((cursor[i] - start[i]) * axis[i] for i in range(2)) / (top - bottom)
                lower, upper = 0.02, 0.98
                for other_index, other in enumerate(view["member_breaks"]):
                    if other_index != mark_index and other["owner"] == mark["owner"]:
                        other_position = other.get("position", 0.02 if other["end"] == 0 else 0.98)
                        if mark["end"] == 0:
                            upper = min(upper, other_position - 0.03)
                        else:
                            lower = max(lower, other_position + 0.03)
                mark["position"] = max(lower, min(upper, initial + delta))
                self.invalidate_view_geometry(index)
                self.update()
            event.accept()
            return
        if self._drag_sheet_table is not None and event.buttons() & Qt.MouseButton.LeftButton:
            index = self._drag_sheet_table
            bounds = self._sheet_table_hit_rects.get(index)
            tables = self._settings.get("tables", ())
            if bounds is not None and self._drag_position is not None and 0 <= index < len(tables):
                delta = event.position() - self._drag_position
                self._drag_position = event.position()
                raw_bounds = self._table_drag_raw_bounds if self._table_drag_raw_bounds is not None else bounds
                self._table_drag_raw_bounds = raw_bounds.translated(delta)
                moved = self._snap_table_bounds(self._table_drag_raw_bounds, self._table_drag_snap_segments)
                position = self._annotation_anchor(moved.topLeft(), None)
                if position is not None:
                    tables[index]["position"] = position
                    self._sheet_table_hit_rects[index] = moved
                    self._update_annotation_regions(bounds, moved)
            event.accept()
            return
        if self._drag_sheet_line_endpoint is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_key, line_index, endpoint = self._drag_sheet_line_endpoint
            view_index = None if view_key < 0 else view_key
            collection = self._line_annotation_collection(view_index)
            if 0 <= line_index < len(collection):
                points = list(collection[line_index]["points"])
                opposite = self._sheet_annotation_screen_point({"anchor": points[1 - endpoint]}, view_index)
                if opposite is not None:
                    screen = self._line_endpoint_screen_point(
                        opposite, event.position(), view_index,
                        bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                    )
                    anchor = self._annotation_anchor(screen, view_index)
                    if anchor is not None:
                        if collection[line_index].get("kind") == "circle" and endpoint == 0:
                            dx, dy = anchor[0] - points[0][0], anchor[1] - points[0][1]
                            points[1] = (points[1][0] + dx, points[1][1] + dy)
                        points[endpoint] = anchor
                        collection[line_index]["points"] = tuple(points)
                        self.update()
            event.accept()
            return
        if self._pan_anchor is not None and event.buttons() & Qt.MouseButton.MiddleButton:
            self._pan_offset = self._pan_origin + (event.position() - self._pan_anchor)
            self._begin_navigation()
            super().update()
            event.accept()
            return
        if self._annotation_mode == "image":
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            event.accept()
            return
        if self._drag_sheet_text_handle is not None and event.buttons() & Qt.MouseButton.LeftButton:
            key = self._drag_sheet_text_handle
            if self._drag_position is not None:
                delta = event.position() - self._drag_position
                self._drag_position = event.position()
                annotation = self._annotation_for_text_key(key)
                if annotation is not None and self._sheet_pixels_per_mm > 1e-9:
                    if annotation.get("kind") == "image":
                        width = float(annotation["width_mm"])
                        height = float(annotation["height_mm"])
                        dx, dy = delta.x()/self._sheet_pixels_per_mm, delta.y()/self._sheet_pixels_per_mm
                        growth = dx/width if abs(dx/width) >= abs(dy/height) else dy/height
                        ratio = max(5./width, 1.+growth)
                        annotation["width_mm"] = width*ratio
                        annotation["height_mm"] = height*ratio
                        delta = QPointF((width*ratio-width)*self._sheet_pixels_per_mm,
                                        (height*ratio-height)*self._sheet_pixels_per_mm)
                    else:
                        annotation["width_mm"] = max(
                            10.0, float(annotation.get("width_mm", 50.0)) + delta.x() / self._sheet_pixels_per_mm,
                        )
                        annotation["height_mm"] = max(
                            5.0, float(annotation.get("height_mm", 25.0)) + delta.y() / self._sheet_pixels_per_mm,
                        )
                    old_bounds = self._drag_sheet_text_bounds
                    self._drag_sheet_text_bounds = (
                        old_bounds.adjusted(0.0, 0.0, delta.x(), delta.y())
                        if old_bounds is not None else None
                    )
                    self._update_annotation_regions(old_bounds, self._drag_sheet_text_bounds)
            event.accept()
            return
        if self._drag_sheet_text is not None and event.buttons() & Qt.MouseButton.LeftButton:
            key = self._drag_sheet_text
            annotation = self._annotation_for_text_key(key)
            if annotation is not None and self._drag_position is not None:
                delta = event.position() - self._drag_position
                self._drag_position = event.position()
                view_index = key[0] if key[0] >= 0 else None
                anchor = tuple(float(value) for value in annotation.get("anchor", (0.0, 0.0)))
                if view_index is None and self._drawing_area.width() > 0 and self._drawing_area.height() > 0:
                    annotation["anchor"] = (
                        anchor[0] + delta.x() / self._drawing_area.width(),
                        anchor[1] + delta.y() / self._drawing_area.height(),
                    )
                elif view_index is not None:
                    draw_data = self._view_draw_data.get(view_index)
                    if draw_data is not None and abs(draw_data[4]) > 1e-9:
                        annotation["anchor"] = (
                            anchor[0] + delta.x() / draw_data[4],
                            anchor[1] - delta.y() / draw_data[4],
                        )
                old_bounds = self._drag_sheet_text_bounds
                if old_bounds is not None:
                    self._drag_sheet_text_bounds = old_bounds.translated(delta)
                self._update_annotation_regions(old_bounds, self._drag_sheet_text_bounds)
            event.accept()
            return
        if self._annotation_mode in {"line", "rectangle", "circle"} and self._line_start_context is not None:
            view_index, start = self._line_start_context
            start_screen = self._sheet_annotation_screen_point({"anchor": start}, view_index)
            if start_screen is not None:
                snap = self._line_snap_screen_point(event.position(), view_index, start_screen)
                end_screen = self._line_endpoint_screen_point(
                    start_screen, event.position(), view_index,
                    bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
                self._line_preview_screen_endpoint = end_screen
                self._line_preview_endpoint = self._line_endpoint_at(end_screen, view_index)
                self._line_preview_snap_screen = QPointF(snap[0]) if snap is not None else None
                self._line_preview_snap_kind = snap[1] if snap is not None else None
                self.update()
            event.accept()
            return
        if self._annotation_mode in {"line", "rectangle", "circle"}:
            view_index = self._annotation_view_at(event.position())
            snap = self._line_snap_screen_point(event.position(), view_index)
            self._line_preview_snap_screen = QPointF(snap[0]) if snap is not None else None
            self._line_preview_snap_kind = snap[1] if snap is not None else None
            self.update()
            event.accept()
            return
        if self._drag_position is not None and event.buttons() & Qt.MouseButton.LeftButton and (
            self._drag_component_detail_group is not None
            or self._drag_component_detail_label is not None
        ):
            delta = event.position() - self._drag_position
            self._drag_position = event.position()
            group_id = self._drag_component_detail_group or self._drag_component_detail_label
            old_group_bounds = self._component_detail_group_bounds(group_id)
            old_title_bounds = self._component_group_title_hit_rects.get(group_id)
            new_title_bounds = (
                old_title_bounds.translated(delta) if old_title_bounds is not None else None
            )
            if self._drawing_area.width() > 0 and self._drawing_area.height() > 0:
                for view in self._sheet_views:
                    metadata = view.get("component_detail_group")
                    if not isinstance(metadata, dict) or str(metadata.get("id")) != group_id:
                        continue
                    key = "label_position" if self._drag_component_detail_label else "group_position"
                    current = metadata.get(key, (0.5, 0.53 if key == "group_position" else 0.40))
                    new_position = (
                        max(0.0, min(1.0, float(current[0]) + delta.x() / self._drawing_area.width())),
                        max(0.0, min(1.0, float(current[1]) + delta.y() / self._drawing_area.height())),
                    )
                    metadata[key] = new_position
                    if self._drag_component_detail_group:
                        label_position = metadata.get("label_position", (0.5, 0.40))
                        metadata["label_position"] = (
                            max(0.0, min(1.0, float(label_position[0]) + delta.x() / self._drawing_area.width())),
                            max(0.0, min(1.0, float(label_position[1]) + delta.y() / self._drawing_area.height())),
                        )
            new_group_bounds = self._component_detail_group_bounds(
                group_id,
                title_override=new_title_bounds if self._drag_component_detail_label else None,
            )
            if self._drag_component_detail_group and not old_group_bounds.isNull():
                new_group_bounds = old_group_bounds.translated(delta).intersected(self._drawing_area)
            if self._drag_component_detail_group:
                self._update_annotation_regions(old_group_bounds, new_group_bounds)
            else:
                self._update_annotation_regions(
                    old_title_bounds, new_title_bounds,
                    *self._frame_outline_regions(old_group_bounds),
                    *self._frame_outline_regions(new_group_bounds),
                )
            event.accept()
            return
        if (
            self._dimension_mode or self._identification_mode
            or self._element_visibility_mode or self._detail_identifier_mode
            or self._elevation_identifier_mode
        ):
            self._ensure_navigation_geometry()
        if self._detail_identifier_mode:
            view_index = self._detail_identifier_view_index
            snap = (
                self._dimension_snap_at(event.position(), view_index)
                if view_index is not None else None
            )
            projected = None
            if snap is not None:
                projected = snap[2]
                self._detail_identifier_snap_screen = snap[3]
                self._detail_identifier_snap_kind = snap[4]
            elif view_index is not None:
                projected = self._projected_point_at(view_index, event.position())
                self._detail_identifier_snap_screen = None
                self._detail_identifier_snap_kind = None
            else:
                self._detail_identifier_snap_screen = None
                self._detail_identifier_snap_kind = None
            self._detail_identifier_hover_projected = (
                tuple(float(value) for value in projected)
                if projected is not None else None
            )
            self._detail_identifier_preview_radius = (
                math.hypot(
                    self._detail_identifier_hover_projected[0] - self._detail_identifier_center[0],
                    self._detail_identifier_hover_projected[1] - self._detail_identifier_center[1],
                )
                if self._detail_identifier_center is not None
                and self._detail_identifier_hover_projected is not None else 0.0
            )
            self.setCursor(QCursor(
                Qt.CursorShape.PointingHandCursor if snap is not None
                else Qt.CursorShape.CrossCursor
            ))
            self.update()
            event.accept()
            return
        if self._elevation_identifier_mode:
            view_index = self._elevation_identifier_view_index
            if view_index is not None and self._elevation_identifier_point is not None:
                cursor = self._projected_point_at(view_index, event.position())
                self._elevation_identifier_hover_projected = (
                    tuple(float(value) for value in cursor) if cursor is not None else None
                )
                self._elevation_identifier_preview_direction = (
                    self._elevation_direction_at(
                        self._elevation_identifier_point,
                        self._elevation_identifier_hover_projected,
                        snap=not bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                    )
                    if self._elevation_identifier_hover_projected is not None else None
                )
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            self.update()
            event.accept()
            return
        if self._dimension_mode:
            if self._dimension_type in {"angular", "level"}:
                self._special_dimension_input(event.position(), False)
                event.accept()
                return
            old_preview_bounds = self._dimension_preview_bounds
            old_snap_screen = self._dimension_snap_screen
            old_snap_kind = self._dimension_snap_kind
            if len(self._dimension_points) < 2:
                snap = self._dimension_snap_at(
                    event.position(), self._dimension_view_index,
                    perpendicular_origin=(
                        self._dimension_points[0] if self._dimension_points else None
                    ),
                )
                self._dimension_snap_screen = snap[3] if snap is not None else None
                self._dimension_hover_view_index = snap[1] if snap is not None else None
                self._dimension_hover_projected = snap[2] if snap is not None else None
                self._dimension_snap_kind = snap[4] if snap is not None else None
                self._dimension_preview = None
                self.setCursor(QCursor(
                    Qt.CursorShape.PointingHandCursor if snap is not None
                    else Qt.CursorShape.CrossCursor
                ))
                new_preview = None
                if len(self._dimension_points) == 1 and self._dimension_hover_projected is not None:
                    new_preview = {
                        "start": self._dimension_points[0],
                        "end": self._dimension_hover_projected,
                        "offset": (0.0, 0.0),
                    }
                self._dimension_preview_bounds = (
                    self._dimension_screen_bounds(self._dimension_hover_view_index, new_preview)
                    if new_preview is not None and self._dimension_hover_view_index is not None
                    else None
                )
            else:
                self._dimension_hover_point = event.position()
                self._dimension_hover_projected = None
                self._dimension_snap_screen = None
                raw_preview = self._dimension_from_screen_point(
                    self._dimension_view_index, event.position(),
                )
                if raw_preview is not None:
                    self._dimension_preview = self._align_dimension_to_existing(
                        self._dimension_view_index, raw_preview,
                    )
                else:
                    self._dimension_preview = None
                self._dimension_preview_bounds = (
                    self._dimension_screen_bounds(
                        self._dimension_view_index, self._dimension_preview,
                    )
                    if self._dimension_preview is not None
                    else None
                )
            snap_changed = (
                old_snap_screen != self._dimension_snap_screen
                or old_snap_kind != self._dimension_snap_kind
            )
            if (
                old_preview_bounds != self._dimension_preview_bounds
                or snap_changed
            ):
                snap_regions = ()
                if snap_changed:
                    snap_regions = tuple(
                        QRectF(point.x() - 16.0, point.y() - 16.0, 32.0, 32.0)
                        for point in (old_snap_screen, self._dimension_snap_screen)
                        if point is not None
                    )
                self._update_annotation_regions(
                    old_preview_bounds, self._dimension_preview_bounds, *snap_regions,
                )
            event.accept()
            return
        if self._drag_axis_endpoints and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self._drag_position
            for view_index, endpoint_key in self._drag_axis_endpoints:
                draw_data = self._view_draw_data.get(view_index)
                direction = self._axis_endpoint_drag_data.get((view_index, endpoint_key))
                if (
                    draw_data is None or direction is None
                    or draw_data[4] <= 1e-12 or direction[2] <= 1e-9
                ):
                    continue
                along = delta.x() * direction[0] + delta.y() * direction[1]
                positions = self._sheet_views[view_index].setdefault("axis_label_positions", {})
                default_fraction = 0.0 if endpoint_key.endswith(":start") else 1.0
                fraction = float(positions.get(endpoint_key, default_fraction))
                positions[endpoint_key] = fraction + along / direction[2]
            self._drag_position = event.position()
            dirty_regions = []
            axis_overrides: dict[int, dict[str, QRectF]] = {}
            for view_index, endpoint_key in self._drag_axis_endpoints:
                axis_key = endpoint_key.rsplit(":", 1)[0]
                key = (view_index, axis_key)
                bounds = self._axis_bounds_at_positions(view_index, axis_key)
                if bounds is not None:
                    dirty_regions.extend((
                        self._drag_axis_painted_bounds.get(key, self._drag_axis_current_bounds.get(key)),
                        bounds,
                    ))
                    self._drag_axis_current_bounds[key] = QRectF(bounds)
                    axis_overrides.setdefault(view_index, {})[axis_key] = QRectF(bounds)
            for view_index, overrides in axis_overrides.items():
                if view_index == self._selected_view_index:
                    previous_frame = self._drag_axis_frame_painted_bounds.get(
                        view_index, self._drag_axis_frame_current_bounds.get(view_index),
                    )
                    predicted = self._view_frame_geometry(
                        view_index, axis_bounds_override=overrides,
                    )
                    next_title = predicted[1] if predicted is not None else None
                    next_frame = predicted[2] if predicted is not None else None
                    dirty_regions.extend((
                        self._view_title_hit_rects.get(view_index), next_title,
                    ))
                    dirty_regions.extend(self._frame_outline_regions(previous_frame))
                    dirty_regions.extend(self._frame_outline_regions(next_frame))
                    if next_frame is not None:
                        self._drag_axis_frame_current_bounds[view_index] = QRectF(next_frame)
            self._update_annotation_regions(*dirty_regions)
            event.accept()
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            hovered_movable_label = any(
                key[0] == self._selected_view_index and rect.contains(event.position())
                for key, rect in self._axis_endpoint_hit_rects.items()
            )
            hovered_title = any(
                rect.contains(event.position())
                for rect in self._view_title_hit_rects.values()
            )
            hovered_elevation_identifier = any(
                rect.contains(event.position())
                for rect in self._elevation_identifier_hit_rects.values()
            )
            if hovered_movable_label or hovered_title or hovered_elevation_identifier:
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            elif not self._drag_axis_endpoints and self._drag_dimension_index is None:
                self.unsetCursor()
        if self._drag_view_title_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view = self._sheet_views[self._drag_view_title_index]
            offset = view.get("label_offset_mm", (0.0, 0.0))
            try:
                offset_x, offset_y = (float(value) for value in offset)
            except (TypeError, ValueError):
                offset_x = offset_y = 0.0
            pixels_per_mm = max(self._sheet_pixels_per_mm, 1e-12)
            delta = event.position() - self._drag_position
            view["label_offset_mm"] = (
                offset_x + delta.x() / pixels_per_mm,
                offset_y + delta.y() / pixels_per_mm,
            )
            self._drag_position = event.position()
            old_bounds = self._drag_title_painted_bounds or self._drag_title_current_bounds
            if self._drag_title_current_bounds is not None:
                self._drag_title_current_bounds = self._drag_title_current_bounds.translated(delta)
            dirty_regions = [old_bounds, self._drag_title_current_bounds]
            if self._drag_view_title_index == self._selected_view_index:
                previous_frame = (
                    self._drag_title_frame_painted_bounds
                    or self._drag_title_frame_current_bounds
                )
                predicted = self._view_frame_geometry(
                    self._drag_view_title_index,
                    title_hit_rect=self._drag_title_current_bounds,
                )
                next_frame = predicted[2] if predicted is not None else None
                dirty_regions.extend(self._frame_outline_regions(previous_frame))
                dirty_regions.extend(self._frame_outline_regions(next_frame))
                self._drag_title_frame_current_bounds = (
                    QRectF(next_frame) if next_frame is not None else None
                )
            self._update_annotation_regions(*dirty_regions)
            event.accept()
            return
        if self._drag_detail_identifier is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_index, identifier_index = self._drag_detail_identifier
            draw_data = self._view_draw_data.get(view_index)
            if (
                0 <= view_index < len(self._sheet_views)
                and draw_data is not None and draw_data[4] > 1e-12
                and self._drag_position is not None
            ):
                identifiers = self._sheet_views[view_index].get("detail_identifiers", ())
                if 0 <= identifier_index < len(identifiers):
                    identifier = identifiers[identifier_index]
                    label_position = tuple(float(value) for value in identifier["label_position"])
                    delta = event.position() - self._drag_position
                    identifier["label_position"] = (
                        label_position[0] + delta.x() / draw_data[4],
                        label_position[1] - delta.y() / draw_data[4],
                    )
                    self._drag_position = event.position()
                    self.update()
            event.accept()
            return
        if self._drag_elevation_identifier is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_index, identifier_index = self._drag_elevation_identifier
            draw_data = self._view_draw_data.get(view_index)
            if (
                0 <= view_index < len(self._sheet_views)
                and draw_data is not None and draw_data[4] > 1e-12
                and self._drag_position is not None
            ):
                identifiers = self._sheet_views[view_index].get("elevation_identifiers", ())
                if 0 <= identifier_index < len(identifiers):
                    identifier = identifiers[identifier_index]
                    point = tuple(float(value) for value in identifier["point"])
                    delta = event.position() - self._drag_position
                    previous_frame = self._view_hit_rects.get(view_index)
                    previous_title = self._view_title_hit_rects.get(view_index)
                    identifier["point"] = (
                        point[0] + delta.x() / draw_data[4],
                        point[1] - delta.y() / draw_data[4],
                    )
                    self._drag_position = event.position()
                    previous_bounds = self._drag_elevation_identifier_bounds
                    next_bounds = (
                        previous_bounds.translated(delta)
                        if previous_bounds is not None else None
                    )
                    self._drag_elevation_identifier_bounds = next_bounds
                    predicted = self._view_frame_geometry(
                        view_index,
                        elevation_identifier_bounds_override=(
                            {identifier_index: next_bounds} if next_bounds is not None else None
                        ),
                    )
                    next_title = predicted[1] if predicted is not None else None
                    next_frame = predicted[2] if predicted is not None else None
                    self._update_annotation_regions(
                        previous_bounds,
                        next_bounds,
                        previous_title,
                        next_title,
                        *self._frame_outline_regions(previous_frame),
                        *self._frame_outline_regions(next_frame),
                    )
            event.accept()
            return
        if self._drag_detail_identifier_handle is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_index, identifier_index, handle_name = self._drag_detail_identifier_handle
            if 0 <= view_index < len(self._sheet_views):
                identifiers = self._sheet_views[view_index].get("detail_identifiers", ())
                if 0 <= identifier_index < len(identifiers):
                    identifier = identifiers[identifier_index]
                    snap = self._dimension_snap_at(event.position(), view_index)
                    candidate = snap[2] if snap is not None else self._projected_point_at(
                        view_index, event.position(),
                    )
                    if candidate is not None:
                        candidate = tuple(float(value) for value in candidate)
                        if handle_name == "center":
                            identifier["center"] = candidate
                        else:
                            center = tuple(float(value) for value in identifier["center"])
                            radius = math.hypot(
                                candidate[0] - center[0], candidate[1] - center[1],
                            )
                            if radius > 1e-9:
                                identifier["radius"] = radius
                        self._drag_position = event.position()
                        self.update()
            event.accept()
            return
        if self._drag_dimension_endpoint is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_index, dimension_index, endpoint_name = self._drag_dimension_endpoint
            if 0 <= view_index < len(self._sheet_views):
                dimensions = self._sheet_views[view_index].get("dimensions", [])
                if 0 <= dimension_index < len(dimensions):
                    dimension = dimensions[dimension_index]
                    snap = self._dimension_snap_at(event.position(), view_index)
                    candidate = snap[2] if snap is not None else self._projected_point_at(
                        view_index, event.position(),
                    )
                    if candidate is not None:
                        other_name = "end" if endpoint_name == "start" else "start"
                        other = tuple(float(value) for value in dimension[other_name])
                        candidate = tuple(float(value) for value in candidate)
                        if math.hypot(candidate[0] - other[0], candidate[1] - other[1]) > 1e-9:
                            if dimension.get("kind") == "angular":
                                trial = dict(dimension, **{endpoint_name: candidate})
                                if angular_geometry(trial) is None:
                                    event.accept()
                                    return
                            dimension[endpoint_name] = candidate
                            if dimension.get("kind") == "level":
                                dimension["end"] = candidate
                            self._drag_position = event.position()
                            self.update()
            event.accept()
            return
        if self._drag_dimension_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            view_index, dimension_index = self._drag_dimension_index
            if 0 <= view_index < len(self._sheet_views):
                dimensions = self._sheet_views[view_index].get("dimensions", [])
                draw_data = self._view_draw_data.get(view_index)
                if (
                    0 <= dimension_index < len(dimensions)
                    and draw_data is not None
                    and draw_data[4] > 0
                ):
                    dimension = dimensions[dimension_index]
                    if dimension.get("kind") in {"angular", "level"}:
                        delta = event.position()-self._drag_position
                        self._drag_position = event.position()
                        offset = dimension["offset"]
                        dimension["offset"] = (offset[0]+delta.x()/draw_data[4], offset[1]-delta.y()/draw_data[4])
                        self.update()
                        event.accept()
                        return
                    offset = tuple(float(value) for value in dimension["offset"])
                    old_bounds = self._drag_dimension_current_bounds or self._dimension_bounds.get(
                        (view_index, dimension_index),
                    )
                    dimension_line = self._dimension_line_points(dimension)
                    line_first = self._screen_point(view_index, dimension_line[0])
                    line_second = self._screen_point(view_index, dimension_line[1])
                    if line_first is not None and line_second is not None:
                        dx = line_second.x() - line_first.x()
                        dy = line_second.y() - line_first.y()
                        length = math.hypot(dx, dy)
                        if length > 1e-9:
                            axis = (dx / length, dy / length)
                            normal = (-axis[1], axis[0])
                            delta = event.position() - self._drag_position
                            self._drag_position = event.position()
                            normal_delta = delta.x() * normal[0] + delta.y() * normal[1]
                            model_delta = (
                                normal[0] * normal_delta / draw_data[4],
                                -normal[1] * normal_delta / draw_data[4],
                            )
                            dimension["offset"] = (
                                offset[0] + model_delta[0],
                                offset[1] + model_delta[1],
                            )
                            aligned = self._align_dimension_to_existing(view_index, dimension)
                            dimension["offset"] = aligned["offset"]
                            final_offset = tuple(float(value) for value in dimension["offset"])
                            moved_bounds = None
                            if old_bounds is not None:
                                moved_bounds = old_bounds.translated(
                                    (final_offset[0] - offset[0]) * draw_data[4],
                                    -(final_offset[1] - offset[1]) * draw_data[4],
                                )
                            else:
                                moved_bounds = self._dimension_screen_bounds(view_index, dimension)
                            self._drag_dimension_current_bounds = (
                                QRectF(moved_bounds) if moved_bounds is not None else None
                            )
                            content_delta = QPointF(
                                (final_offset[0] - offset[0]) * draw_data[4],
                                -(final_offset[1] - offset[1]) * draw_data[4],
                            )
                            if self._drag_dimension_content_current_bounds is not None:
                                self._drag_dimension_content_current_bounds = (
                                    self._drag_dimension_content_current_bounds.translated(content_delta)
                                )
                            dirty_regions = [
                                self._drag_dimension_painted_bounds or old_bounds,
                                moved_bounds,
                            ]
                            if view_index == self._selected_view_index:
                                previous_frame = self._view_hit_rects.get(view_index)
                                predicted = self._view_frame_geometry(
                                    view_index,
                                    dimension_bounds_override={
                                        dimension_index: self._drag_dimension_content_current_bounds,
                                    } if self._drag_dimension_content_current_bounds is not None else None,
                                )
                                next_title = predicted[1] if predicted is not None else None
                                next_frame = predicted[2] if predicted is not None else None
                                dirty_regions.extend((
                                    self._view_title_hit_rects.get(view_index), next_title,
                                ))
                                dirty_regions.extend(self._frame_outline_regions(previous_frame))
                                dirty_regions.extend(self._frame_outline_regions(next_frame))
                            self._update_annotation_regions(*dirty_regions)
            event.accept()
            return
        dragging_identification = (
            self._drag_identification_index is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
        )
        if (
            self._identification_mode
            or self._member_break_mode
            or self._element_visibility_mode in {"hide", "reveal"}
        ) and not dragging_identification:
            self._last_identification_position = event.position()
            visibility_mode = self._element_visibility_mode in {"hide", "reveal"}
            target = None
            if not (visibility_mode or self._member_break_mode) or self._selected_view_index is not None:
                target = self._element_at(
                    event.position(),
                    view_index=self._selected_view_index if visibility_mode or self._member_break_mode else None,
                )
            if self._member_break_mode:
                hit = (self._member_break_target_at(event.position(), self._member_break_view_index)
                       if self._member_break_view_index is not None else None)
                target = (0.0, self._member_break_view_index, hit[0], hit[1], set(), hit[0]) if hit else None
            raw_target = (target[1], target[5]) if target is not None and target[5] else None
            if self._identification_mode and raw_target != self._hover_raw_target:
                self._identification_pick_member = False
                target = self._element_at(event.position())
                raw_target = (target[1], target[5]) if target is not None and target[5] else None
            hover_owners = set()
            if target is not None:
                hover_owners = {(target[1], target[5])} if self._member_break_mode else target[4]
            if hover_owners != self._hover_owners or raw_target != self._hover_raw_target:
                self._hover_owners = set(hover_owners)
                self._hover_raw_target = raw_target
                self.update()
            self.setCursor(QCursor(
                Qt.CursorShape.PointingHandCursor if hover_owners else Qt.CursorShape.CrossCursor
            ))
        if self._drag_position is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.position() - self._drag_position
            self._drag_position = event.position()
            if self._drag_identification_index is not None:
                index = self._selected_view_index
                draw_data = self._view_draw_data.get(index) if index is not None else None
                if draw_data is not None and draw_data[4] > 0:
                    view = self._sheet_views[index]
                    identifications = view.get("identifications", [])
                    dirty_regions = []
                    for label_index in self._drag_identification_indices:
                        if not 0 <= label_index < len(identifications):
                            continue
                        old_bounds = self._drag_identification_current_bounds.get(
                            label_index,
                            self._identification_hit_rects.get((index, label_index)),
                        )
                        if old_bounds is not None:
                            moved_bounds = old_bounds.translated(delta)
                            self._drag_identification_current_bounds[label_index] = moved_bounds
                            dirty_regions.extend((
                                self._drag_identification_painted_bounds.get(label_index, old_bounds),
                                moved_bounds,
                            ))
                        identification = identifications[label_index]
                        point = identification.get("projected_point")
                        if point is None:
                            point = self._project_world_point(
                                view, identification.get("world_point", ()),
                            )
                        if point is not None:
                            identification["projected_point"] = (
                                float(point[0]) + delta.x() / draw_data[4],
                                float(point[1]) - delta.y() / draw_data[4],
                            )
                    previous_frame = self._view_hit_rects.get(index)
                    predicted = self._view_frame_geometry(
                        index,
                        identification_bounds_override=self._drag_identification_current_bounds,
                    )
                    next_title = predicted[1] if predicted is not None else None
                    next_frame = predicted[2] if predicted is not None else None
                    dirty_regions.extend((self._view_title_hit_rects.get(index), next_title))
                    dirty_regions.extend(self._frame_outline_regions(previous_frame))
                    dirty_regions.extend(self._frame_outline_regions(next_frame))
                    self._update_annotation_regions(*dirty_regions)
                event.accept()
                return
            index = self._selected_view_index
            if index is not None and self._drawing_area.width() > 0 and self._drawing_area.height() > 0:
                view = self._sheet_views[index]
                metadata = view.get("component_detail_group")
                if isinstance(metadata, dict) and metadata.get("id"):
                    offset = metadata.get("offset_delta", (0.0, 0.0))
                    metadata["offset_delta"] = (
                        float(offset[0]) + delta.x() / self._drawing_area.width(),
                        float(offset[1]) + delta.y() / self._drawing_area.height(),
                    )
                    actual_delta = QPointF(delta)
                else:
                    x, y = view.get("position", (0.5, 0.5))
                    new_position = (
                        max(0.0, min(1.0, float(x) + delta.x() / self._drawing_area.width())),
                        max(0.0, min(1.0, float(y) + delta.y() / self._drawing_area.height())),
                    )
                    actual_delta = QPointF(
                        (new_position[0] - float(x)) * self._drawing_area.width(),
                        (new_position[1] - float(y)) * self._drawing_area.height(),
                    )
                    view["position"] = new_position
                old_bounds = self._drag_view_painted_bounds or self._drag_view_current_bounds
                if self._drag_view_current_bounds is not None:
                    self._drag_view_current_bounds = self._drag_view_current_bounds.translated(actual_delta)
                if isinstance(metadata, dict) and metadata.get("id"):
                    group_bounds = self._component_detail_group_bounds(str(metadata["id"]))
                    new_group_bounds = self._component_detail_group_bounds(
                        str(metadata["id"]),
                        view_override=(index, self._drag_view_current_bounds)
                        if self._drag_view_current_bounds is not None else None,
                    )
                    self._update_annotation_regions(
                        old_bounds, self._drag_view_current_bounds,
                        *self._frame_outline_regions(group_bounds),
                        *self._frame_outline_regions(new_group_bounds),
                    )
                else:
                    self._update_annotation_regions(old_bounds, self._drag_view_current_bounds)
            event.accept()
            return
        line_handle_hover = any(
            rect.contains(event.position()) for rect in self._sheet_line_handle_hit_rects.values()
        )
        text_handle_hover = any(
            rect.contains(event.position()) for rect in self._sheet_text_handle_hit_rects.values()
        )
        text_hover = any(
            rect.contains(event.position()) for rect in self._sheet_text_hit_rects.values()
        )
        if line_handle_hover:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif text_handle_hover:
            self.setCursor(QCursor(Qt.CursorShape.SizeFDiagCursor))
        elif text_hover:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_owners:
            self._hover_owners.clear()
            self._hover_raw_target = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_identification_resize is not None:
            self._drag_identification_resize = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_member_break is not None:
            self._drag_member_break = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_sheet_table is not None:
            self._drag_sheet_table = None
            self._table_drag_raw_bounds = None
            self._table_drag_snap_segments = []
            self._drag_position = None
            self._annotation_background = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_sheet_line_endpoint is not None:
            self._drag_sheet_line_endpoint = None
            self._annotation_background = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and (
            self._drag_sheet_text is not None or self._drag_sheet_text_handle is not None
        ):
            self._annotation_background = None
            self._drag_sheet_text = None
            self._drag_sheet_text_handle = None
            self._drag_position = None
            self._drag_sheet_text_bounds = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and (
            self._drag_component_detail_group is not None
            or self._drag_component_detail_label is not None
        ):
            self._drag_component_detail_group = None
            self._drag_component_detail_label = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_view_title_index is not None:
            self._drag_view_title_index = None
            self._drag_title_current_bounds = None
            self._drag_title_painted_bounds = None
            self._drag_title_frame_current_bounds = None
            self._drag_title_frame_painted_bounds = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_axis_endpoints:
            self._drag_axis_endpoints = ()
            self._drag_axis_current_bounds.clear()
            self._drag_axis_painted_bounds.clear()
            self._drag_axis_frame_current_bounds.clear()
            self._drag_axis_frame_painted_bounds.clear()
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_detail_identifier is not None:
            self._drag_detail_identifier = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_detail_identifier_handle is not None:
            self._drag_detail_identifier_handle = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_elevation_identifier is not None:
            self._drag_elevation_identifier = None
            self._drag_elevation_identifier_bounds = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_dimension_endpoint is not None:
            self._drag_dimension_endpoint = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_dimension_index is not None:
            self._drag_dimension_index = None
            self._drag_dimension_current_bounds = None
            self._drag_dimension_painted_bounds = None
            self._drag_position = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_position is not None:
            self._drag_position = None
            self._drag_view_index = None
            self._drag_view_current_bounds = None
            self._drag_view_painted_bounds = None
            moved_identification = self._drag_identification_index is not None
            self._drag_identification_index = None
            self._drag_identification_indices = ()
            self._drag_identification_current_bounds.clear()
            self._drag_identification_painted_bounds.clear()
            self.unsetCursor()
            if moved_identification or self._selected_view_index is not None:
                self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_anchor is not None:
            self._pan_anchor = None
            self._finish_navigation()
            if self._dimension_mode:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = None
            self._finish_navigation()
            self._zoom_factor = 1.0
            self._pan_offset = QPointF()
            if self._dimension_mode:
                self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            else:
                self.unsetCursor()
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            table_hit = next((index for index, rect in reversed(tuple(self._sheet_table_hit_rects.items()))
                              if rect.contains(event.position())), None)
            if table_hit is not None and self._annotation_mode is None:
                self._selected_sheet_table = table_hit
                self._drag_sheet_table = None
                self._table_drag_raw_bounds = None
                self._table_drag_snap_segments = []
                self._drag_position = None
                self._annotation_background = None
                self.table_editor_requested.emit(table_hit)
                self.update()
                event.accept()
                return
            text_hit = next((
                key for key, rect in reversed(tuple(self._sheet_text_hit_rects.items()))
                if rect.contains(event.position())
            ), None)
            if text_hit is not None:
                annotation = self._annotation_for_text_key(text_hit)
                if annotation is not None:
                    if annotation.get("kind") == "image":
                        event.accept()
                        return
                    self._selected_sheet_text = text_hit
                    self.text_editor_requested.emit({
                        **annotation,
                        "_edit_key": text_hit,
                        "_existing_text": True,
                    })
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.cancel_identification_resize():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self.cancel_member_break_drag():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self._selected_member_break is not None:
            index, mark_index = self._selected_member_break
            self._sheet_views[index]["member_breaks"].pop(mark_index)
            self._selected_member_break = None
            self._drag_member_break = None
            self.invalidate_view_geometry(index)
            self.update()
            self.layout_changed.emit()
            event.accept()
            return
        if self._member_break_mode and event.key() == Qt.Key.Key_Escape:
            self.set_member_break_mode(False)
            self.member_break_finished.emit(True)
            event.accept()
            return
        if self._member_break_mode and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        if self._annotation_mode is not None and event.key() == Qt.Key.Key_Escape:
            canceled_mode = self._annotation_mode
            self.set_sheet_text_mode(False) if canceled_mode == "text" else self.set_sheet_line_mode(False)
            self.annotation_finished.emit(canceled_mode, True)
            event.accept()
            return
        if self._detail_identifier_mode and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
        ):
            self._finish_detail_identifier_mode(event.key() == Qt.Key.Key_Escape)
            event.accept()
            return
        if self._elevation_identifier_mode and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
        ):
            self._finish_elevation_identifier_mode(event.key() == Qt.Key.Key_Escape)
            event.accept()
            return
        if self._dimension_mode and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
        ):
            if self._dimension_type in {"angular", "level"} and event.key() != Qt.Key.Key_Escape:
                event.accept()
                return
            self.set_dimension_mode(False)
            self.dimension_finished.emit(event.key() == Qt.Key.Key_Escape)
            event.accept()
            return
        if self._identification_mode and event.key() == Qt.Key.Key_Tab:
            if self._hover_raw_target is not None:
                self._identification_pick_member = not self._identification_pick_member
                if self._last_identification_position is not None:
                    target = self._element_at(self._last_identification_position)
                    self._hover_owners = target[4] if target is not None else set()
                    self.update()
            event.accept()
            return
        if self._identification_mode and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
        ):
            self.identification_finished.emit(event.key() == Qt.Key.Key_Escape)
            event.accept()
            return
        if self._element_visibility_mode is not None and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape,
        ):
            if event.key() == Qt.Key.Key_Escape:
                self._finish_element_visibility_mode(True)
            else:
                self._confirm_element_visibility_selection()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_sheet_table():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_dimension():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_detail_identifier():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_elevation_identifier():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_sheet_text():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self.delete_selected_sheet_line():
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete and self._selected_view_index is not None:
            if not self.delete_selected_identification():
                self.remove_view_requested.emit(self._selected_view_index)
            event.accept()
            return
        super().keyPressEvent(event)

    def _draw_title_block(self, painter: QPainter, inner: QRectF, scale: float) -> None:
        visible = self._settings.get("visible_fields", {})
        labels = (
            ("client", "Cliente", self._project_settings.get("client", "")),
            ("work", "Obra", self._project_settings.get("work", "")),
            ("subject", "Assunto", self._settings.get("subject", "")),
            ("address", "Endereço", self._project_settings.get("address", "")),
            ("responsible", "Responsável", self._project_settings.get("responsible", "")),
            ("crea", "CREA", self._project_settings.get("crea", "")),
            ("file", "Arquivo", self._settings.get("file", "")),
            ("date", "Data", self._settings.get("date", "")),
            ("scale", "Escala", self._settings.get("scale", "")),
            ("revision", "Revisão", self._settings.get("revision", "")),
            ("size", "Tamanho", self._paper_size_label()),
        )
        values = {key: (label, value) for key, label, value in labels}
        property_font = QFont(painter.font())
        property_font.setPixelSize(max(
            1,
            round(float(self._project_settings.get("title_block_property_text_height_mm", 2.5)) * scale),
        ))
        value_font = QFont(painter.font())
        value_font.setPixelSize(max(
            1,
            round(float(self._project_settings.get("title_block_value_text_height_mm", 4.0)) * scale),
        ))
        block_width = min(175.0 * scale, inner.width())
        right_width = block_width * 0.22
        left_width = block_width - right_width
        row_height = 10.0 * scale
        block_height = row_height * 8
        top = inner.top() if self._settings.get("title_block_position") == "Superior" else inner.bottom() - block_height
        left = inner.right() - block_width
        right = left + left_width
        y = top
        painter.setPen(QColor("#000000"))

        def cell(rect: QRectF, key: str) -> None:
            painter.drawRect(rect)
            if not visible.get(key, True):
                return
            label, value = values[key]
            label_rect = rect.adjusted(4.0, 2.0, -4.0, 0.0)
            value_left = max(10.0, 5.0 * scale)
            value_rect = QRectF(
                rect.left() + value_left,
                rect.top() + row_height * 0.34,
                max(0.0, rect.width() - value_left - 4.0),
                max(0.0, rect.height() - row_height * 0.34 - 2.0),
            )
            painter.setFont(property_font)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
            painter.setFont(value_font)
            painter.drawText(
                value_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                str(value),
            )

        for key in ("client", "work", "subject"):
            row = QRectF(left, y, left_width, row_height)
            cell(row, key)
            file_key = {"client": "file", "work": "date", "subject": "scale"}[key]
            cell(QRectF(right, y, right_width, row_height), file_key)
            y += row_height

        address_width = left_width
        revision_width = right_width / 2
        size_width = right_width - revision_width
        cell(QRectF(left, y, address_width, row_height), "address")
        cell(QRectF(right, y, revision_width, row_height), "revision")
        cell(QRectF(right + revision_width, y, size_width, row_height), "size")
        y += row_height

        bottom_cell_width = left_width / 2
        for index, key in enumerate(("responsible", "crea")):
            cell(QRectF(left + index * bottom_cell_width, y, bottom_cell_width, row_height), key)
        sheet_rect = QRectF(right, y, right_width, row_height)
        painter.drawRect(sheet_rect)
        if visible.get("sheet_number", True):
            painter.setFont(property_font)
            painter.drawText(
                sheet_rect.adjusted(4.0, 2.0, -4.0, 0.0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                "Folha",
            )
            sheet_value = "ÚNICA" if self._sheet_count == 1 else self._settings.get("sheet_number", "")
            painter.setFont(value_font)
            painter.drawText(
                QRectF(
                    sheet_rect.left() + max(10.0, 5.0 * scale),
                    sheet_rect.top() + row_height * 0.35,
                    max(0.0, sheet_rect.width() - max(10.0, 5.0 * scale) - 4.0),
                    max(0.0, sheet_rect.height() - row_height * 0.35 - 3.0),
                ),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                sheet_value,
            )

        # Three additional rows for office and client visual identities. The
        # full eight-row block still ends exactly at the sheet's inner border.
        logo_top = top + 5*row_height
        painter.drawRect(QRectF(left, logo_top, left_width, 3*row_height))
        client_logo = QRectF(right, logo_top, right_width, 3*row_height)
        painter.drawRect(client_logo)
        painter.setFont(property_font)
        painter.drawText(client_logo.adjusted(4., 2., -4., 0.),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "Cliente")

    def _paper_size_label(self) -> str:
        size = self._settings.get("paper_size", "A3")
        if size != "Personalizado":
            return size
        width = self._settings.get("custom_width_mm", 420)
        height = self._settings.get("custom_height_mm", 297)
        return f"{width:g} × {height:g} mm"
