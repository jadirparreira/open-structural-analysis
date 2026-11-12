"""Blank project sheet workspace shown in the detailing session."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QPen

from .common import (
    QColor, QCheckBox, QFrame, QHBoxLayout, QLineEdit, QPainter, QRectF, QLabel, Qt,
    QVBoxLayout, QWidget,
)
from .property_panel import MixedCheckBox
from .window_frame import WindowFrame


PAPER_SIZES_MM = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}


class ProjectSheetViewPanel(QFrame):
    """Inspector for the selected drawing view on a project sheet."""

    scale_edited = Signal(str)

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Vista", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        name_label = QLabel("Identidade", self)
        name_label.setObjectName("propertySection")
        layout.addWidget(name_label)
        self.name_input = QLineEdit(self)
        self.name_input.setObjectName("identityDisplay")
        self.name_input.setReadOnly(True)
        self.name_input.setAccessibleName("Identidade da vista")
        layout.addWidget(self.name_input)
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
        self.hide()

    def show_for(self, view: dict | None) -> None:
        if view is None:
            self.hide()
            return
        self.name_input.setText(str(view.get("name", "Vista")))
        denominator = float(view.get("scale_denominator", 100.0))
        self.scale_input.setText(f"{denominator:g}")
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
    }


class ProjectSheetWorkspace(QWidget):
    """A clean drawing surface with a centered landscape sheet."""

    selection_changed = Signal(object)
    identification_selection_changed = Signal(object)
    remove_view_requested = Signal(int)
    layout_changed = Signal()
    element_identification_requested = Signal(int, str, object)
    identification_finished = Signal(bool)

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
        self._sheet_name = "01 - Folha Geral"
        self._settings = default_project_sheet_settings(self._sheet_name)
        self._project_settings = default_project_settings()
        self._sheet_count = 1
        self._sheet_views: tuple[dict, ...] = ()
        self._selected_view_index: int | None = None
        self._selected_identification_index: int | None = None
        self._selected_identification_indices: set[int] = set()
        self._view_hit_rects: dict[int, QRectF] = {}
        self._identification_hit_rects: dict[tuple[int, int], QRectF] = {}
        self._view_draw_data: dict[int, tuple[float, float, float, float, float]] = {}
        self._identification_mode = False
        self._hover_owners: set[tuple[int, str]] = set()
        self._hover_raw_target: tuple[int, str] | None = None
        self._identification_pick_member = False
        self._last_identification_position: QPointF | None = None
        self._drawing_area = QRectF()
        self._stamp_rect = QRectF()
        self._drag_position: QPointF | None = None
        self._drag_identification_index: int | None = None
        self._drag_identification_indices: tuple[int, ...] = ()
        self._zoom_factor = 1.0
        self._pan_offset = QPointF()
        self._pan_anchor: QPointF | None = None
        self._pan_origin = QPointF()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_model_name(self, name: str) -> None:
        self._model_name.setText(name.strip() or "Novo modelo")
        self._model_info.adjustSize()
        self._model_info.move(20, 14)
        self._model_info.raise_()

    def set_sheet_settings(
        self, sheet_name: str, settings: dict, project_settings: dict | None = None,
        sheet_count: int | None = None,
    ) -> None:
        self._sheet_name = sheet_name
        self._settings = settings
        if project_settings is not None:
            self._project_settings = project_settings
        if sheet_count is not None:
            self._sheet_count = sheet_count
        self.update()

    def set_sheet_views(self, views, *, clear_selection: bool = False) -> None:
        self._sheet_views = tuple(views)
        if clear_selection or (
            self._selected_view_index is not None
            and self._selected_view_index >= len(self._sheet_views)
        ):
            self._selected_view_index = None
            self._selected_identification_index = None
            self._selected_identification_indices.clear()
            self.identification_selection_changed.emit(None)
            self.selection_changed.emit(None)
        elif (
            self._selected_view_index is not None
            and self._selected_identification_indices
        ):
            identifications = self._sheet_views[self._selected_view_index].get("identifications", ())
            self._emit_identification_selection(identifications)
        self.update()

    def select_view(self, index: int | None) -> None:
        if index is not None and not 0 <= index < len(self._sheet_views):
            index = None
        self._selected_view_index = index
        self._selected_identification_index = None
        self._selected_identification_indices.clear()
        self.identification_selection_changed.emit(None)
        self.selection_changed.emit(
            self._sheet_views[index] if index is not None else None
        )
        self.update()

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

    def set_identification_mode(self, active: bool, view_index: int | None = None) -> None:
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

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
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
        margin_x = max(32.0, self.width() * 0.1)
        margin_y = max(32.0, self.height() * 0.1)
        available_width = max(0.0, self.width() - 2 * margin_x)
        available_height = max(0.0, self.height() - 2 * margin_y)
        base_scale = (
            min(available_width / paper_width, available_height / paper_height)
            if paper_width and paper_height else 0.0
        )
        scale = base_scale * self._zoom_factor
        sheet_width = paper_width * scale
        sheet_height = paper_height * scale
        center = QPointF(self.width() / 2, self.height() / 2) + self._pan_offset
        sheet = QRectF(
            center.x() - sheet_width / 2,
            center.y() - sheet_height / 2,
            sheet_width,
            sheet_height,
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(sheet.translated(0, 3), QColor("#d8dee4"))
        painter.fillRect(sheet, QColor("#ffffff"))
        painter.setPen(QColor("#d0d7de"))
        painter.drawRect(sheet)
        inner = sheet.adjusted(
            self._settings.get("margin_left_mm", 25.0) * scale,
            self._settings.get("margin_top_mm", 10.0) * scale,
            -self._settings.get("margin_right_mm", 10.0) * scale,
            -self._settings.get("margin_bottom_mm", 10.0) * scale,
        )
        painter.setPen(QColor("#000000"))
        painter.drawRect(inner)
        self._draw_sheet_views(painter, inner, scale)
        if self._settings.get("title_block_visible", True):
            self._draw_title_block(painter, inner, scale)

    def _draw_sheet_views(self, painter: QPainter, inner: QRectF, scale: float) -> None:
        if not self._sheet_views:
            self._view_hit_rects = {}
            self._identification_hit_rects = {}
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
        self._identification_hit_rects = {}
        self._view_draw_data = {}
        painter.save()
        painter.setClipRect(inner)
        pen = painter.pen()
        pen.setColor(QColor("#000000"))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        base_font = painter.font()
        for index, view in enumerate(self._sheet_views):
            segments = view.get("segments", ())
            if not segments:
                continue
            points = [point for segment in segments for point in segment]
            min_x = min(float(point[0]) for point in points)
            max_x = max(float(point[0]) for point in points)
            min_y = min(float(point[1]) for point in points)
            max_y = max(float(point[1]) for point in points)
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
            label_top = frame.bottom() + 2.0 * scale
            name_width = name_metrics.horizontalAdvance(view_name)
            scale_width = scale_metrics.horizontalAdvance(view_scale_label)
            name_label_rect = QRectF(
                frame.left(), label_top, name_width, name_metrics.height(),
            )
            scale_label_rect = QRectF(
                frame.left(), label_top + name_metrics.height(),
                scale_width, scale_metrics.height(),
            )
            view_bounds = frame.united(name_label_rect).united(scale_label_rect)
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
                anchor = QPointF(anchor_x, baseline_y)
                rotation = float(identification.get("text_rotation_degrees", 0.0))
                label_rect = self._rotated_text_rect(
                    anchor, text_width, top, bottom, rotation,
                )
                identification_rects.append(
                    (identification_index, anchor, rendered_lines, text_width, label_rect, rotation)
                )
                self._identification_hit_rects[(index, identification_index)] = label_rect.adjusted(
                    -4.0, -3.0, 4.0, 3.0,
                )
                view_bounds = view_bounds.united(label_rect)
            view_bounds = view_bounds.adjusted(-5.0, -5.0, 5.0, 5.0).intersected(inner)
            self._view_hit_rects[index] = view_bounds
            if index == self._selected_view_index:
                selection_pen = QPen(QColor("#0969da"), 2.0)
                selection_pen.setCosmetic(True)
                painter.setPen(selection_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(view_bounds)
                painter.setPen(pen)
            owners = view.get("segment_owners", ())
            for segment_index, (start, end) in enumerate(segments):
                start_screen = QPointF(
                    target_x + (float(start[0]) - center_x) * model_to_pixels,
                    target_y - (float(start[1]) - center_y) * model_to_pixels,
                )
                end_screen = QPointF(
                    target_x + (float(end[0]) - center_x) * model_to_pixels,
                    target_y - (float(end[1]) - center_y) * model_to_pixels,
                )
                painter.drawLine(
                    start_screen,
                    end_screen,
                )
                if (
                    self._identification_mode
                    and len(owners) == len(segments)
                    and (index, str(owners[segment_index])) in self._hover_owners
                ):
                    hover_pen = QPen(QColor("#0969da"), 2.5)
                    hover_pen.setCosmetic(True)
                    painter.setPen(hover_pen)
                    painter.drawLine(start_screen, end_screen)
                    painter.setPen(pen)
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
            for identification_index, anchor, lines, text_width, label_rect, rotation in identification_rects:
                if (
                    index == self._selected_view_index
                    and identification_index in self._selected_identification_indices
                ):
                    selection_pen = QPen(QColor("#0969da"), 1.5)
                    selection_pen.setCosmetic(True)
                    painter.setPen(selection_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(label_rect.adjusted(-3.0, -2.0, 3.0, 2.0))
                    painter.setPen(QColor("#000000"))
                painter.save()
                painter.translate(anchor)
                painter.rotate(rotation)
                baseline_offset = 0
                for rendered_runs, line_width, line_height, _line_ascent in lines:
                    run_x = -line_width / 2.0
                    for run_text, run_font, run_metrics in rendered_runs:
                        painter.setFont(run_font)
                        painter.drawText(QPointF(run_x, baseline_offset), run_text)
                        run_x += run_metrics.horizontalAdvance(run_text)
                    baseline_offset += line_height
                painter.restore()
            painter.setFont(base_font)
            painter.setPen(pen)
        painter.restore()

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
                return sum(delta[i] * u[i] for i in range(3)), sum(
                    delta[i] * v[i] for i in range(3)
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
        block_height = 50.0 * scale
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

    def _element_at(self, position: QPointF):
        if self._stamp_rect.contains(position):
            return None
        best = None
        for view_index, view in enumerate(self._sheet_views):
            draw_data = self._view_draw_data.get(view_index)
            if draw_data is None:
                continue
            center_x, center_y, target_x, target_y, model_to_pixels = draw_data
            segments = view.get("segments", ())
            owners = view.get("segment_owners", ())
            for segment_index, (start, end) in enumerate(segments):
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
                    best = (distance, view_index, owner, projected_point)
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

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if not delta:
            event.ignore()
            return
        old_zoom = self._zoom_factor
        new_zoom = max(0.25, min(8.0, old_zoom * (1.15 ** (delta / 120.0))))
        if new_zoom == old_zoom:
            event.accept()
            return
        pointer = event.position()
        center = QPointF(self.width() / 2, self.height() / 2)
        ratio = new_zoom / old_zoom
        relative_pointer = pointer - center
        self._pan_offset = relative_pointer - (relative_pointer - self._pan_offset) * ratio
        self._zoom_factor = new_zoom
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = event.position()
            self._pan_origin = QPointF(self._pan_offset)
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self._identification_mode:
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
                        self._drag_position = event.position()
                        self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                    self._emit_identification_selection()
                    self.setFocus(Qt.FocusReason.MouseFocusReason)
                    self.update()
                    event.accept()
                    return
            if self._stamp_rect.contains(event.position()):
                self.select_view(None)
                super().mousePressEvent(event)
                return
            selected = next(
                (
                    index for index, rect in reversed(tuple(self._view_hit_rects.items()))
                    if rect.contains(event.position())
                ),
                None,
            )
            self.select_view(selected)
            if selected is not None:
                self._drag_position = event.position()
                self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._identification_mode:
            self._last_identification_position = event.position()
            target = self._element_at(event.position())
            raw_target = (target[1], target[5]) if target is not None and target[5] else None
            if raw_target != self._hover_raw_target:
                self._identification_pick_member = False
                target = self._element_at(event.position())
                raw_target = (target[1], target[5]) if target is not None and target[5] else None
            hover_owners = target[4] if target is not None else set()
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
                    for label_index in self._drag_identification_indices:
                        if not 0 <= label_index < len(identifications):
                            continue
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
                    self.update()
                event.accept()
                return
            index = self._selected_view_index
            if index is not None and self._drawing_area.width() > 0 and self._drawing_area.height() > 0:
                view = self._sheet_views[index]
                x, y = view.get("position", (0.5, 0.5))
                view["position"] = (
                    max(0.0, min(1.0, float(x) + delta.x() / self._drawing_area.width())),
                    max(0.0, min(1.0, float(y) + delta.y() / self._drawing_area.height())),
                )
                self.update()
            event.accept()
            return
        if self._pan_anchor is not None and event.buttons() & Qt.MouseButton.MiddleButton:
            self._pan_offset = self._pan_origin + (event.position() - self._pan_anchor)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hover_owners:
            self._hover_owners.clear()
            self._hover_raw_target = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_position is not None:
            self._drag_position = None
            moved_identification = self._drag_identification_index is not None
            self._drag_identification_index = None
            self._drag_identification_indices = ()
            self.unsetCursor()
            if moved_identification:
                self.layout_changed.emit()
            elif self._selected_view_index is not None:
                self.layout_changed.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_anchor is not None:
            self._pan_anchor = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = None
            self._zoom_factor = 1.0
            self._pan_offset = QPointF()
            self.unsetCursor()
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
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
        block_height = row_height * 5
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

    def _paper_size_label(self) -> str:
        size = self._settings.get("paper_size", "A3")
        if size != "Personalizado":
            return size
        width = self._settings.get("custom_width_mm", 420)
        height = self._settings.get("custom_height_mm", 297)
        return f"{width:g} × {height:g} mm"
