"""View-local welding annotations, following Fakury §10.9.4 (single reference line)."""
from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen, QPicture, QPixmap, QPolygonF, QRegion
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from .property_panel import CompactDoubleSpinBox
from .window_frame import WindowFrame


class WeldNumberInput(CompactDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


TYPES = {"fillet": "Filete", "square": "Chanfro reto", "bevel": "Chanfro meio V", "v": "Chanfro V"}
SIDES = {"arrow": "Lado da seta", "other": "Lado oposto", "both": "Ambos os lados"}
DEFAULTS = dict(kind="fillet", side="arrow", size=6.0, length=0.0, pitch=0.0,
                root=0.0, angle=60.0, contour="none", all_around=False, field=False,
                tail="", direction="right")


def symbol_sides(mark):
    """Positive painter Y is below the reference line: arrow side."""
    return (1, -1) if mark.get("side") == "both" else ((-1,) if mark.get("side") == "other" else (1,))


def weld_layout(mark, font, text_height_mm=3.0):
    """Measure the notation at a fixed paper resolution, independent of zoom."""
    paper_font = QFont(font)
    paper_font.setPixelSize(max(1, round(text_height_mm * 20)))
    metrics = QFontMetricsF(paper_font)
    def number(key):
        value = float(mark.get(key, 0))
        return f"{value:g}".replace(".", ",") if value > 0 else ""
    size, length, root = number("size"), number("length"), number("root")
    kind = mark.get("kind", "fillet")
    if kind == "fillet" and length and number("pitch"):
        length += "-" + number("pitch")
    angle = number("angle") + "°" if kind in ("bevel", "v") and number("angle") else ""
    root = root if kind != "fillet" else ""
    width = 4.0 if kind in ("fillet", "square") else 6.0
    height = 6.0 if root else 4.0
    if root:
        interior_fraction = max(.15, .72 - metrics.height() / 20 / (2 * height))
        width = max(width, (metrics.horizontalAdvance(root) / 20 + 1.5) / interior_fraction)
    size_space = metrics.horizontalAdvance(size) / 20 + 1.3 if size else 0
    right_gap = 3.0 if kind == "fillet" and mark.get("contour", "none") != "none" else 1.3
    length_space = metrics.horizontalAdvance(length) / 20 + right_gap if length else 0
    angle_extra = max(0, metrics.horizontalAdvance(angle) / 20 - width) / 2
    before, after = max(size_space, angle_extra), max(length_space, angle_extra)
    occupied = before + width + after
    reference_length = max(18.0, math.ceil((occupied + 6.0) * 2) / 2)
    symbol_x = (reference_length - occupied) / 2 + before
    return dict(length_mm=reference_length, symbol_x_mm=symbol_x, width_mm=width,
                height_mm=height, right_gap_mm=right_gap, size=size, length=length, root=root, angle=angle)


def draw_weld(painter, anchor, mark, scale, selected=False, settings=None):
    """Draw the single-reference-line convention of Fakury §10.9.4."""
    settings = settings or {}
    scale = max(scale, 0.01)
    text_height = float(settings.get("weld_text_height_mm", 3.0))
    layout = weld_layout(mark, painter.font(), text_height)
    offset = mark.get("offset_mm", (18.0, -16.0))
    elbow = anchor + QPointF(float(offset[0]) * scale, float(offset[1]) * scale)
    right = mark.get("direction", "right") == "right"
    end = elbow + QPointF(layout["length_mm"] * scale * (1 if right else -1), 0)
    left = min(elbow.x(), end.x())
    leader = QPainterPath()
    symbols = QPainterPath()
    def line(path, x1, y1, x2, y2):
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
    line(leader, anchor.x(), anchor.y(), elbow.x(), elbow.y())
    line(leader, elbow.x(), elbow.y(), end.x(), end.y())
    theta = math.atan2(elbow.y() - anchor.y(), elbow.x() - anchor.x())
    arrow = QPolygonF([anchor, *(QPointF(anchor.x() + 2.8 * scale * math.cos(theta + delta),
                                       anchor.y() + 2.8 * scale * math.sin(theta + delta))
                                for delta in (-.35, .35))])
    leader.addPolygon(arrow)
    if mark.get("all_around"):
        symbols.addEllipse(elbow, 1.4 * scale, 1.4 * scale)
    flag = None
    if mark.get("field"):
        x, y = elbow.x(), elbow.y()
        line(symbols, x, y, x, y - 7 * scale)
        flag = QPolygonF([QPointF(x, y - 7 * scale), QPointF(x + 4 * scale, y - 5.5 * scale), QPointF(x, y - 4 * scale)])
        symbols.addPolygon(flag)
    font = QFont(painter.font())
    font.setPixelSize(max(1, round(text_height * scale)))
    metrics = QFontMetricsF(font)
    texts = []
    def text(x, center_y, value):
        if value:
            texts.append((QPointF(x, center_y + (metrics.ascent() - metrics.descent()) / 2), value))
    kind = mark.get("kind", "fillet")
    for side in symbol_sides(mark):
        x, y = left + layout["symbol_x_mm"] * scale, elbow.y()
        w, h = layout["width_mm"] * scale, layout["height_mm"] * scale * side
        if kind == "fillet":
            line(symbols, x, y, x, y + h)
            line(symbols, x, y + h, x + w, y)
        elif kind == "square":
            for dx in (0, w):
                line(symbols, x + dx, y, x + dx, y + h)
        elif kind == "bevel":
            # The vertex lies on the reference line; the vertical leg stays left.
            line(symbols, x, y, x, y + h)
            line(symbols, x, y, x + w, y + h)
        else:
            line(symbols, x + w / 2, y, x, y + h)
            line(symbols, x + w / 2, y, x + w, y + h)
        center_y = y + side * max(2., text_height * .6) * scale
        text(x - 1.3 * scale - metrics.horizontalAdvance(layout["size"]), center_y, layout["size"])
        text(x + w + layout["right_gap_mm"] * scale, center_y, layout["length"])
        if layout["root"]:
            root_center_x = (w * max(.15, .72 - metrics.height() / (2 * abs(h))) / 2
                             if kind == "bevel" else w / 2)
            text(x + root_center_x - metrics.horizontalAdvance(layout["root"]) / 2,
                 y + side * abs(h) * .72, layout["root"])
        contour = mark.get("contour", "none")
        if kind == "fillet":
            # Contour follows the inclined face, rather than the reference line.
            normal = QPointF(scale / math.sqrt(2), side * scale / math.sqrt(2))
            first = QPointF(x, y + h) + normal * 1.2
            last = QPointF(x + w, y) + normal * 1.2
        else:
            normal = QPointF(0, side * scale)
            first = QPointF(x, y + h) + normal * 1.4
            last = QPointF(x + w, y + h) + normal * 1.4
        if contour == "flat":
            symbols.moveTo(first)
            symbols.lineTo(last)
        elif contour in ("convex", "concave"):
            symbols.moveTo(first)
            control = (first + last) / 2 + normal * (2 if contour == "convex" else -2)
            symbols.quadTo(control, last)
        if layout["angle"]:
            text(x + (w - metrics.horizontalAdvance(layout["angle"])) / 2,
                 y + side * (abs(h) + (3.5 if contour != "none" else 1.2) * scale + metrics.height() / 2),
                 layout["angle"])
    tail = str(mark.get("tail", "")).strip()
    if tail:
        direction = 1 if right else -1
        for dy in (-3, 3):
            line(leader, end.x(), end.y(), end.x() + direction * 4 * scale, end.y() + dy * scale)
        text(end.x() + 5 * scale if right else end.x() - 5 * scale - metrics.horizontalAdvance(tail), end.y(), tail)
    painter.save()
    pen = QPen(QColor(str(settings.get("weld_line_color", "#ff0000"))), 1.0)
    pen.setCosmetic(True)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(leader)
    painter.setBrush(pen.color())
    painter.drawPolygon(arrow)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen.setColor(QColor(str(settings.get("weld_symbol_color", "#000000"))))
    painter.setPen(pen)
    painter.drawPath(symbols)
    if flag is not None:
        painter.setBrush(painter.pen().color())
        painter.drawPolygon(flag)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    pen.setColor(QColor(str(settings.get("weld_text_color", "#000000"))))
    painter.setPen(pen)
    painter.setFont(font)
    for point, value in texts:
        painter.drawText(point, value)
    stroker = QPainterPathStroker()
    stroker.setWidth(max(7, 2 * scale))
    hit = stroker.createStroke(symbols)
    hit.addPath(stroker.createStroke(leader))
    for point, value in texts:
        hit.addRect(QRectF(point.x(), point.y() - metrics.ascent(), metrics.horizontalAdvance(value), metrics.height()))
    if selected:
        painter.setPen(QPen(QColor("#0969da"), 1.0))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(elbow, 3, 3)
    painter.restore()
    return hit


class WeldPreview(QFrame):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setFixedHeight(112)
        self.setObjectName("weldSymbolPreview")
        self.setStyleSheet(
            "QFrame#weldSymbolPreview { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; }"
        )

    def diagram(self):
        mark = self.panel.values()
        mark["offset_mm"] = (14, -16) if mark["direction"] == "right" else (-14, -16)
        picture = QPicture()
        painter = QPainter(picture)
        painter.setFont(self.font())
        bounds = draw_weld(painter, QPointF(), mark, 3, settings=self.panel.project_settings()).boundingRect()
        painter.end()
        return picture, bounds

    def paintEvent(self, event):
        super().paintEvent(event)
        picture, bounds = self.diagram()
        area = QRectF(self.contentsRect()).adjusted(12, 10, -12, -10)
        if bounds.isEmpty() or area.isEmpty():
            return
        factor = min(1.0, area.width() / bounds.width(), area.height() / bounds.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(area)
        painter.translate(area.center())
        painter.scale(factor, factor)
        painter.translate(-bounds.center())
        painter.drawPicture(QPointF(), picture)
        painter.end()


class WeldPanel(QFrame):
    changed = Signal(dict)

    def __init__(self, window):
        super().__init__(window)
        self.setObjectName("propertyPanel")
        self.setFixedSize(310, 500)
        self.fields = {}
        layout = QVBoxLayout(self)
        title = QLabel("Solda")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        self.preview = WeldPreview(self)
        layout.addWidget(self.preview)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        content = QWidget()
        form = self.form = QFormLayout(content)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        def combo(key, label, choices):
            field = QComboBox()
            for value, name in choices.items():
                field.addItem(name, value)
            field.currentIndexChanged.connect(self._changed)
            self.fields[key] = field
            form.addRow(label, field)
        combo("kind", "Tipo", TYPES)
        combo("side", "Lado", SIDES)
        for key, label, default, maximum in (
            ("size", "Perna / profundidade (mm)", 6, 1000),
            ("length", "Comprimento (mm)", 0, 100000),
            ("pitch", "Passo entre centros (mm)", 0, 100000),
            ("root", "Abertura da raiz (mm)", 0, 1000),
            ("angle", "Ângulo do chanfro (°)", 60, 179),
        ):
            field = WeldNumberInput()
            field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            field.setDecimals(2)
            field.setRange(0, maximum)
            field.setSpecialValueText("Não indicar")
            field.setValue(default)
            field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            field.valueChanged.connect(self._changed)
            self.fields[key] = field
            form.addRow(label, field)
        combo("contour", "Contorno", {"none": "Não indicar", "flat": "Plano", "convex": "Convexo", "concave": "Côncavo"})
        combo("direction", "Linha de referência", {"right": "À direita", "left": "À esquerda"})
        for key, label in (("all_around", "Solda em toda a volta"), ("field", "Solda de campo")):
            field = QCheckBox(label)
            field.setStyleSheet("QCheckBox::indicator:checked { background: #0969da; border: 1px solid #0969da; border-radius: 3px; }")
            field.toggled.connect(self._changed)
            self.fields[key] = field
            form.addRow(field)
        field = QLineEdit()
        field.setObjectName("propertyValue")
        field.setPlaceholderText("Ex.: SMAW · E7018")
        field.textChanged.connect(self._changed)
        self.fields["tail"] = field
        form.addRow("Processo / observação", field)
        self.load(DEFAULTS)
        self.hide()

    def project_settings(self):
        workspace = getattr(self.parentWidget(), "project_sheet_workspace", None)
        return workspace._project_settings if workspace is not None else {}

    def values(self):
        result = {}
        for key, field in self.fields.items():
            result[key] = (field.currentData() if isinstance(field, QComboBox) else
                           field.value() if isinstance(field, QDoubleSpinBox) else
                           field.isChecked() if isinstance(field, QCheckBox) else field.text())
        return result

    def load(self, values):
        for key, field in self.fields.items():
            value = values.get(key, DEFAULTS[key])
            field.blockSignals(True)
            if isinstance(field, QComboBox):
                field.setCurrentIndex(max(0, field.findData(value)))
            elif isinstance(field, QDoubleSpinBox):
                field.setValue(float(value))
            elif isinstance(field, QCheckBox):
                field.setChecked(bool(value))
            else:
                field.setText(str(value))
            field.blockSignals(False)
        self._refresh()

    def _refresh(self):
        kind = self.fields["kind"].currentData()
        for key in ("root", "angle"):
            self.fields[key].setEnabled(kind != "fillet" and (key != "angle" or kind != "square"))
        self.fields["pitch"].setEnabled(kind == "fillet")
        self.form.setRowVisible(self.fields["pitch"], kind == "fillet")
        self.form.setRowVisible(self.fields["root"], kind != "fillet")
        self.form.setRowVisible(self.fields["angle"], kind in ("bevel", "v"))
        self.preview.update()

    def _changed(self, *args):
        self._refresh()
        # A pitch smaller than the weld length is not an intermittent weld.
        length, pitch = self.fields["length"].value(), self.fields["pitch"].value()
        if pitch and pitch < length:
            self.fields["pitch"].setValue(length)
            return
        self.changed.emit(self.values())

    def reposition(self):
        window = self.parentWidget()
        margin = 0 if window.isMaximized() else WindowFrame.MARGIN
        upper = 90
        for name in ("project_sheets_palette", "detailing_top_palette", "top_icon_palette"):
            palette = getattr(window, name, None)
            if palette is not None and palette.isVisible():
                upper = max(upper, palette.geometry().bottom() + 12)
        command_bar = getattr(window, "command_bar", None)
        lower = (command_bar.y() - 12 if command_bar is not None and command_bar.isVisible()
                 else window.height() - margin - 90)
        self.move(window.width() - margin - self.width() - 24,
                  max(upper, round((upper + lower - self.height()) / 2)))
        self.raise_()


class WeldSnapIndicator(QWidget):
    """A mouse-transparent overlay; hovering does not repaint model linework."""
    def __init__(self, workspace):
        super().__init__(workspace)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(24, 24)
        self.symbol = None
        self.hide()

    def show_snap(self, point, symbol):
        self.symbol = symbol
        self.move(round(point.x() - self.width() / 2), round(point.y() - self.height() / 2))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, event):
        if self.symbol is not None:
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self.symbol)
            painter.end()


class WeldTool(QObject):
    """Owns interaction without coupling welding settings to model geometry."""
    def __init__(self, window, workspace):
        super().__init__(window)
        self.window, self.workspace = window, workspace
        self.panel = WeldPanel(window)
        self.panel.changed.connect(self.edit)
        self.active = False
        self.view_index = None
        self.selected = None
        self.drag = None
        self.hits = {}
        self._drag_background = None
        self._drag_picture = None
        self._capturing_drag = False
        self.snap = None
        self.snap_indicator = WeldSnapIndicator(workspace)
        workspace.installEventFilter(self)
        window.installEventFilter(self)
        workspace.selection_changed.connect(self._view_selected)

    def _view_selected(self, *args):
        if not self.active:
            self._clear_drag_cache()
            self.selected = self.drag = None
            self.panel.hide()

    def start(self):
        if getattr(self.window, "_command_mode", None) is not None:
            self.window.cancel_member_placement()
        self.window.command_session.cancel()
        self.window._command_mode = "project_sheet_weld"
        self.workspace.set_member_break_mode(False)
        for name in ("_annotation_mode", "_element_visibility_mode"):
            setattr(self.workspace, name, None)
        for name in ("_dimension_mode", "_identification_mode", "_detail_identifier_mode", "_elevation_identifier_mode"):
            setattr(self.workspace, name, False)
        self._clear_snap()
        self.active = True
        self.selected = self.view_index = None
        self.workspace.select_view(None)
        self.workspace._annotation_background = None
        self._hide_other_panels()
        self.panel.show()
        self.panel.reposition()
        QApplication.instance().installEventFilter(self)
        self.workspace.setCursor(Qt.CursorShape.CrossCursor)
        self.workspace.setFocus()
        self.workspace.update()

    def finish(self):
        self._clear_snap()
        self._clear_drag_cache()
        self.active = False
        self.selected = self.view_index = self.drag = None
        self.panel.hide()
        QApplication.instance().removeEventFilter(self)
        if getattr(self.window, "_command_mode", None) == "project_sheet_weld":
            self.window._command_mode = None
        if getattr(self.window, "_command_mode", None) is None:
            self.workspace.unsetCursor()
        self.workspace.update()

    def reset(self):
        self._clear_snap()
        self._clear_drag_cache()
        if self.active:
            self.finish()
        self.selected = self.drag = None
        self.hits.clear()
        self.panel.hide()

    def edit(self, properties):
        if self.selected is not None:
            self._clear_drag_cache()
            vi, mi = self.selected
            self.workspace._sheet_views[vi]["weld_marks"][mi].update(properties)
            self.workspace._annotation_background = None
            self.workspace.update()
            self.workspace.layout_changed.emit()

    def draw(self, painter, index):
        preserved_hit = self.hits.get(self.selected)
        bounds = QRectF()
        for key in tuple(self.hits):
            if key[0] == index:
                del self.hits[key]
        for mi, mark in enumerate(self.workspace._sheet_views[index].get("weld_marks", ())):
            if self._capturing_drag and self.selected == (index, mi):
                if preserved_hit is not None:
                    self.hits[index, mi] = preserved_hit
                    bounds = bounds.united(preserved_hit.boundingRect())
                continue
            anchor = self.workspace._screen_point(index, mark["point"])
            if anchor is None:
                continue
            hit = draw_weld(painter, anchor, mark, self.workspace._sheet_pixels_per_mm,
                            self.selected == (index, mi), self.workspace._project_settings)
            self.hits[index, mi] = hit
            bounds = bounds.united(hit.boundingRect())
        return bounds

    def _clear_snap(self):
        self.snap = None
        self.snap_indicator.hide()

    def _snap_at(self, position):
        ws = self.workspace
        if self.view_index is None or ws._stamp_rect.contains(position):
            return None
        bounds = ws._view_hit_rects.get(self.view_index, QRectF())
        if not bounds.adjusted(-12, -12, 12, 12).contains(position):
            return None
        # Reuse the same visible-linework index and snap preferences as dimensions.
        return ws._dimension_snap_at(position, self.view_index)

    def _hover_snap(self, position):
        self.workspace._ensure_navigation_geometry()
        self.snap = self._snap_at(position)
        if self.snap is None:
            self.snap_indicator.hide()
        else:
            self.snap_indicator.show_snap(self.snap[3], self.workspace._snap_symbol_pixmaps[self.snap[4]])
        self.workspace.setCursor(Qt.CursorShape.PointingHandCursor if self.snap is not None
                                 else Qt.CursorShape.CrossCursor)

    def _hide_other_panels(self):
        for frame in self.window.findChildren(QFrame):
            if frame is not self.panel and frame.objectName() == "propertyPanel":
                frame.hide()

    def _clear_drag_cache(self):
        self._drag_background = None
        self._drag_picture = None

    def _begin_drag_cache(self):
        """Capture the complete sheet once, omitting only the dragged weld.

        Retain its old bounds while capturing so view titles, frames, axes,
        clipped detail geometry and all other annotations stay in place.
        """
        ws = self.workspace
        self._clear_drag_cache()
        ws._finish_navigation()
        ws._annotation_background = None
        ws._navigation_picture_dirty = True
        background = QPixmap(ws.size() * ws.devicePixelRatioF())
        background.setDevicePixelRatio(ws.devicePixelRatioF())
        background.fill(QColor("#f6f8fa"))
        self._capturing_drag = True
        try:
            ws.render(background, QPoint(), QRegion(), QWidget.RenderFlag.DrawWindowBackground)
        finally:
            self._capturing_drag = False
            ws._navigation_picture_dirty = True
        self._drag_background = background
        self._drag_navigation = (ws.size(), ws._zoom_factor, QPointF(ws._pan_offset), ws.devicePixelRatioF())
        self._refresh_drag_picture()

    def _refresh_drag_picture(self):
        if self.selected is None:
            return
        ws = self.workspace
        vi, mi = self.selected
        mark = ws._sheet_views[vi]["weld_marks"][mi]
        anchor = ws._screen_point(vi, mark["point"])
        if anchor is None:
            return
        old = self.hits.get(self.selected)
        picture = QPicture()
        painter = QPainter(picture)
        painter.setFont(ws.font())
        hit = draw_weld(painter, anchor, mark, ws._sheet_pixels_per_mm, True, ws._project_settings)
        painter.end()
        self._drag_picture = picture
        self.hits[self.selected] = hit
        dirty = hit.boundingRect()
        if old is not None:
            dirty = dirty.united(old.boundingRect())
        # Bypass the workspace update override: only the cached overlay changed.
        QWidget.update(ws, dirty.adjusted(-6, -6, 6, 6).toAlignedRect())

    def paint_drag(self):
        ws = self.workspace
        if self._drag_background is None or self._capturing_drag:
            return False
        current = (ws.size(), ws._zoom_factor, ws._pan_offset, ws.devicePixelRatioF())
        if self._drag_navigation != current or self.selected is None:
            self._clear_drag_cache()
            return False
        painter = QPainter(ws)
        painter.drawPixmap(QPoint(), self._drag_background)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QRegion(ws._drawing_area.toAlignedRect())
        if ws._settings.get("title_block_visible", True):
            clip = clip.subtracted(QRegion(ws._stamp_rect.toAlignedRect()))
        painter.setClipRegion(clip)
        if self._drag_picture is not None:
            painter.drawPicture(QPointF(), self._drag_picture)
        painter.end()
        return True

    def eventFilter(self, watched, event):
        ws = getattr(self, "workspace", None)
        if ws is None:
            return False
        et = event.type()
        if et == QEvent.Type.ShortcutOverride:
            keys = ((Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter) if self.active
                    else (Qt.Key.Key_Escape, Qt.Key.Key_Delete) if self.selected is not None and watched is ws else ())
            if event.key() in keys:
                event.accept()
                return True
        if watched is self.window and et == QEvent.Type.Resize and self.panel.isVisible():
            QTimer.singleShot(0, self.panel.reposition)
        if watched is ws and et == QEvent.Type.Hide:
            self.reset()
        if self.active and getattr(self.window, "_command_mode", None) != "project_sheet_weld":
            self.finish()
        if self.active and et == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.finish()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True
        if watched is not ws:
            return False
        if et in (QEvent.Type.Wheel, QEvent.Type.Resize, QEvent.Type.Leave):
            self._clear_snap()
            if et != QEvent.Type.Leave:
                self._clear_drag_cache()
        if not self.active and self.selected is not None and getattr(self.window, "_command_mode", None):
            self.selected = self.drag = None
            self.panel.hide()
        if et == QEvent.Type.KeyPress and self.selected is not None:
            if event.key() == Qt.Key.Key_Delete:
                vi, mi = self.selected
                ws._sheet_views[vi]["weld_marks"].pop(mi)
                self.reset()
                ws.update()
                ws.layout_changed.emit()
                return True
            if event.key() == Qt.Key.Key_Escape:
                if self.drag:
                    vi, mi = self.selected
                    ws._sheet_views[vi]["weld_marks"][mi]["offset_mm"] = self.drag[1]
                self.reset()
                ws.update()
                return True
        if self.active and et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            self._clear_snap()
            return False
        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            if self.active:
                ws._ensure_navigation_geometry()
                if self.view_index is None:
                    self.view_index = ws._annotation_view_at(pos)
                    if self.view_index is not None:
                        ws.select_view(self.view_index)
                        self._hide_other_panels()
                else:
                    ws._ensure_navigation_geometry()
                    snap = self._snap_at(pos)
                    inside = ws._view_hit_rects.get(self.view_index, QRectF()).contains(pos)
                    point = (snap[2] if snap is not None else ws._projected_point_at(self.view_index, pos)
                             if inside and not ws._stamp_rect.contains(pos) else None)
                    if point is not None:
                        mark = self.panel.values()
                        mark.update(point=point, offset_mm=(18.0 if mark["direction"] == "right" else -18.0, -16.0))
                        ws._sheet_views[self.view_index].setdefault("weld_marks", []).append(mark)
                        self._clear_snap()
                        ws._annotation_background = None
                        ws.update()
                        ws.layout_changed.emit()
                return True
            if not any((ws._annotation_mode, ws._dimension_mode, ws._identification_mode,
                        ws._detail_identifier_mode, ws._elevation_identifier_mode,
                        ws._element_visibility_mode, ws._member_break_mode)):
                hit = next((key for key, shape in reversed(tuple(self.hits.items())) if shape.contains(pos)), None)
                if hit is not None:
                    ws.select_view(hit[0])
                    self.selected = hit
                    mark = ws._sheet_views[hit[0]]["weld_marks"][hit[1]]
                    self.drag = (QPointF(pos), tuple(mark["offset_mm"]))
                    self.panel.load(mark)
                    self._hide_other_panels()
                    self.panel.show()
                    self.panel.reposition()
                    ws.setFocus()
                    ws._annotation_background = None
                    self._begin_drag_cache()
                    ws.update()
                    return True
                self.selected = None
                self.panel.hide()
        if self.active and et == QEvent.Type.MouseMove:
            if ws._pan_anchor is not None and event.buttons() & Qt.MouseButton.MiddleButton:
                self._clear_snap()
                return False
            self._hover_snap(event.position())
            return True
        if self.active and et == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.MiddleButton:
                ws.mouseReleaseEvent(event)
                ws._ensure_navigation_geometry()
                ws.setCursor(Qt.CursorShape.CrossCursor)
            return True
        if et == QEvent.Type.MouseMove and self.drag and event.buttons() & Qt.MouseButton.LeftButton:
            delta = (event.position() - self.drag[0]) / max(ws._sheet_pixels_per_mm, 0.01)
            vi, mi = self.selected
            ws._sheet_views[vi]["weld_marks"][mi]["offset_mm"] = (self.drag[1][0] + delta.x(), self.drag[1][1] + delta.y())
            self._refresh_drag_picture()
            return True
        if et == QEvent.Type.MouseButtonRelease and self.drag and event.button() == Qt.MouseButton.LeftButton:
            self._clear_drag_cache()
            self.drag = None
            ws.update()
            ws.layout_changed.emit()
            return True
        return False
