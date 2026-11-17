"""Sheet tables, shared between the drawing canvas and insertion previews."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

TABLE_TITLES = {
    "sheet_revisions": "Revisões da folha",
    "project_revisions": "Revisões do projeto",
    "steel_profiles": "Lista de perfis de aço",
    "steel_plates": "Lista de chapas de aço",
    "accessories": "Lista de acessórios",
}
REVISION_COLUMNS = ("#", "Alteração", "Responsável", "Data")


def default_revision_rows() -> list[dict]:
    return [
        {"number": "01", "change": "Alteração na forma do pavimento", "responsible": "Jadir", "date": "02/11/2026"},
        {"number": "02", "change": "Mudança na posição da chapa de base", "responsible": "Jadir", "date": "06/11/2026"},
        {"number": "03", "change": "Ajuste nos perfis do projeto", "responsible": "Jadir", "date": "13/11/2026"},
    ]


def initial_revision_rows() -> list[dict]:
    return [{"number": "01", "change": "Emissão inicial", "responsible": "", "date": ""}]


def revision_rows_for(sheet_settings: dict, project_settings: dict, kind: str) -> list[dict]:
    scope = project_settings if kind == "project_revisions" else sheet_settings
    rows = scope.get(kind)
    return rows if isinstance(rows, list) else default_revision_rows()


def steel_profile_rows(model) -> list[dict]:
    """Aggregate actual steel bars by section geometry and assigned material."""
    from osa.sections.properties import calculate_section_properties

    grouped = {}
    for member in model.bars.values():
        if model.material_types.get(member.material) != "Aço":
            continue
        geometry = tuple(sorted(member.section_geometry))
        key = (member.section, member.profile, geometry, member.material, tuple(member.material_values))
        if key not in grouped:
            try:
                density = member.material_values[3] / 9.80665e-3
                mass = calculate_section_properties(member.section, dict(geometry), density).mass_kg_m
            except (ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
                mass = None
            grouped[key] = {
                "profile": member.profile or member.section or "Indefinido",
                "family": member.section, "geometry": geometry,
                "material": member.material, "linear_mass": mass, "length": 0.0,
            }
        a = model.nodes[member.start_node]
        b = model.nodes[member.end_node]
        grouped[key]["length"] += math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
    rows = sorted(grouped.values(), key=lambda row: (row["profile"].casefold(), row["material"].casefold(), row["geometry"]))
    for row in rows:
        row["total_mass"] = row["linear_mass"] * row["length"] if row["linear_mass"] is not None else None
    return rows


def _table_number(value) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


class RevisionTableLayout:
    """Physical layout at a fixed DPI: zoom never changes row heights or wrapping."""

    def __init__(self, kind: str, rows: list[dict], width_mm: float, font: QFont):
        self.width_mm = width_mm
        self._device = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        self._device.setDotsPerMeterX(round(96.0 / 0.0254))
        self._device.setDotsPerMeterY(round(96.0 / 0.0254))
        self._units = self._device.logicalDpiY() / 25.4
        self._font = QFont(font)
        self._font.setPointSizeF(4.0 * 72.0 / 25.4)
        self._padding = 1.2
        self._widths = [width_mm * ratio for ratio in (0.08, 0.50, 0.22, 0.20)]
        self._title = self._document(TABLE_TITLES[kind].upper(), width_mm, Qt.AlignCenter)
        self._title_height = max(8.0, self._title.size().height() / self._units + 2 * self._padding)
        values = [REVISION_COLUMNS] + [
            tuple(str(row.get(key, "")) for key in ("number", "change", "responsible", "date"))
            for row in rows
        ]
        self._rows = []
        for row in values:
            docs = [self._document(value, width, Qt.AlignLeft if index == 1 else Qt.AlignCenter)
                    for index, (value, width) in enumerate(zip(row, self._widths))]
            height = max(8.0, max(doc.size().height() / self._units for doc in docs) + 2 * self._padding)
            self._rows.append((height, docs))
        self.height_mm = self._title_height + sum(height for height, _docs in self._rows)

    def _document(self, text: str, width: float, alignment) -> QTextDocument:
        doc = QTextDocument()
        doc.documentLayout().setPaintDevice(self._device)
        doc.setUseDesignMetrics(True)
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self._font)
        option = doc.defaultTextOption()
        option.setAlignment(alignment)
        doc.setDefaultTextOption(option)
        doc.setPlainText(text)
        doc.setTextWidth(max(1.0, (width - 2 * self._padding) * self._units))
        return doc

    def draw(self, painter: QPainter, origin: QPointF, pixels_per_mm: float) -> None:
        painter.save()
        painter.translate(origin)
        painter.scale(pixels_per_mm, pixels_per_mm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(QRectF(0, 0, self.width_mm, self.height_mm), QColor("#ffffff"))
        pen = QPen(QColor("#000000"), 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, self.width_mm, self.height_mm))

        def text(doc, x, y, width, height):
            painter.save()
            painter.setClipRect(QRectF(x, y, width, height))
            painter.translate(x + self._padding, y + (height - doc.size().height() / self._units) / 2)
            painter.scale(1 / self._units, 1 / self._units)
            doc.drawContents(painter)
            painter.restore()

        text(self._title, 0, 0, self.width_mm, self._title_height)
        y = self._title_height
        for row_index, (height, docs) in enumerate(self._rows):
            painter.drawLine(QPointF(0, y), QPointF(self.width_mm, y))
            x = 0.0
            for column, (width, doc) in enumerate(zip(self._widths, docs)):
                leading = getattr(self, "_cell_leading", {}).get((row_index, column), 0.0)
                text(doc, x + leading, y, width - leading, height)
                x += width
            y += height
        x = 0.0
        for width in self._widths[:-1]:
            x += width
            painter.drawLine(QPointF(x, self._title_height), QPointF(x, self.height_mm - getattr(self, "_footer_height", 0.0)))
        painter.restore()


class AccessoriesTableLayout(RevisionTableLayout):
    """Accessory names and integer counts, sharing the sheet table grid."""

    def __init__(self, rows: list[dict], width_mm: float, font: QFont):
        super().__init__("accessories", [], width_mm, font)
        self._widths = [width_mm * 0.8, width_mm * 0.2]
        values = [("NOME", "QUANTIDADE")]
        values.extend((row["name"], str(row["quantity"])) for row in rows)
        self._rows = []
        for row in values:
            docs = [self._document(value, width, Qt.AlignLeft if column == 0 else Qt.AlignCenter)
                    for column, (value, width) in enumerate(zip(row, self._widths))]
            height = max(8.0, max(doc.size().height() / self._units for doc in docs) + 2 * self._padding)
            self._rows.append((height, docs))
        self.height_mm = self._title_height + sum(height for height, _docs in self._rows)


class SteelProfilesTableLayout(RevisionTableLayout):
    """The same physical table grid, with existing section contours and totals."""

    _kind = "steel_profiles"
    _name_key = "profile"
    _name_heading = "PERFIL"
    _show_icons = True

    def __init__(self, rows: list[dict], width_mm: float, font: QFont):
        from osa.sections.geometry import section_shape

        super().__init__(self._kind, [], width_mm, font)
        self._widths = [width_mm * ratio for ratio in (0.30, 0.17, 0.17, 0.19, 0.17)]
        self._rows = []
        self._cell_leading = {}
        self._icons = []
        values = [(self._name_heading, "MATERIAL", "PESO LINEAR\nkg/m", "COMPRIMENTO\nm", "PESO TOTAL\nkg")]
        values.extend((row[self._name_key], row["material"], _table_number(row["linear_mass"]),
                       _table_number(row["length"]), _table_number(row["total_mass"])) for row in rows)
        for row_index, values_row in enumerate(values):
            docs = []
            for column, (value, width) in enumerate(zip(values_row, self._widths)):
                leading = 6.0 if self._show_icons and row_index > 0 and column == 0 else 0.0
                self._cell_leading[row_index, column] = leading
                docs.append(self._document(value, width - leading,
                                           Qt.AlignLeft if row_index > 0 and column == 0 else Qt.AlignCenter))
            height = max(8.0, max(doc.size().height() / self._units for doc in docs) + 2 * self._padding)
            self._rows.append((height, docs))
        for row in rows if self._show_icons else ():
            try:
                shape = section_shape(row["family"], dict(row["geometry"]))
            except (ValueError, KeyError, ZeroDivisionError):
                shape = None
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            if shape is not None:
                for loop in shape.loops:
                    if not loop:
                        continue
                    path.moveTo(loop[0][0], -loop[0][1])
                    for x, y in loop[1:]:
                        path.lineTo(x, -y)
                    path.closeSubpath()
            self._icons.append(path)
        total = sum(row["total_mass"] for row in rows if row["total_mass"] is not None)
        # An undefined section must not produce a misleading complete total.
        if any(row["total_mass"] is None for row in rows):
            total = None
        self._footer_label = self._document("PESO GLOBAL\nkg", sum(self._widths[:-1]), Qt.AlignRight)
        self._footer_total = self._document(_table_number(total), self._widths[-1], Qt.AlignCenter)
        self._footer_height = max(8.0, max(doc.size().height() for doc in
                                         (self._footer_label, self._footer_total)) / self._units + 2 * self._padding)
        self.height_mm = self._title_height + sum(height for height, _docs in self._rows) + self._footer_height

    def draw(self, painter: QPainter, origin: QPointF, pixels_per_mm: float) -> None:
        super().draw(painter, origin, pixels_per_mm)
        painter.save()
        painter.translate(origin)
        painter.scale(pixels_per_mm, pixels_per_mm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        pen = QPen(QColor("#000000"), 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        footer_y = self.height_mm - self._footer_height
        split = sum(self._widths[:-1])
        painter.drawLine(QPointF(0, footer_y), QPointF(self.width_mm, footer_y))
        painter.drawLine(QPointF(split, footer_y), QPointF(split, self.height_mm))
        for doc, x in ((self._footer_label, 0), (self._footer_total, split)):
            painter.save()
            painter.translate(x + self._padding,
                              footer_y + (self._footer_height - doc.size().height() / self._units) / 2)
            painter.scale(1 / self._units, 1 / self._units)
            doc.drawContents(painter)
            painter.restore()
        y = self._title_height + self._rows[0][0]
        for path, (height, _docs) in zip(self._icons, self._rows[1:]):
            bounds = path.boundingRect()
            if not bounds.isEmpty():
                factor = min(4.5 / bounds.width(), 4.5 / bounds.height())
                painter.save()
                painter.translate(self._padding + 2.25, y + height / 2)
                painter.scale(factor, factor)
                painter.translate(-bounds.center())
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor("#000000"))
                painter.drawPath(path)
                painter.restore()
            y += height
        painter.restore()


class SteelPlatesTableLayout(SteelProfilesTableLayout):
    """Plate quantities with the same width, columns and global total as profiles."""

    _kind = "steel_plates"
    _name_key = "plate"
    _name_heading = "CHAPA"
    _show_icons = False


DIALOG_STYLE = (
    "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0; }"
    "QFrame#titleBar { background: #e1e4e8; border-bottom: 1px solid #d0d7de; }"
    "QLabel#windowTitle { color: #24292f; font-size: 14px; font-weight: 600; }"
    "QLabel { color: #57606a; }"
    "QListWidget { background: #f6f8fa; border: 0; padding: 8px; }"
    "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #57606a; }"
    "QListWidget::item:hover { background: #eaeef2; color: #24292f; }"
    "QListWidget::item:selected { background: #d0d7de; color: #24292f; }"
    "QListWidget:focus { outline: none; border: 0; }"
    "QComboBox { min-height: 32px; padding: 2px 9px; border: 1px solid #d0d7de; "
    "border-radius: 6px; background: #ffffff; color: #24292f; }"
    "QPushButton { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de; "
    "border-radius: 7px; background: #f6f8fa; color: #24292f; }"
    "QPushButton:hover { background: #eaeef2; }"
    "QPushButton#primaryAction { background: #0969da; border-color: #0969da; color: #ffffff; }"
    "QPushButton#primaryAction:hover { background: #0550ae; }"
    "QPushButton#primaryAction:disabled { background: #d0d7de; border-color: #d0d7de; color: #8c959f; }"
    "QTableWidget { border: 1px solid #d0d7de; background: #ffffff; gridline-color: #d0d7de; "
    "selection-background-color: #ddf4ff; selection-color: #24292f; color: #24292f; }"
    "QHeaderView::section { background: #f6f8fa; color: #24292f; padding: 8px; "
    "border: 0; border-right: 1px solid #d0d7de; border-bottom: 1px solid #d0d7de; }"
    "QTableWidget::item { padding: 6px 8px; }"
    "QTableWidget QLineEdit { min-height: 0; max-height: 400px; margin: 0; "
    "border: 0; border-radius: 0; padding: 6px 8px; background: #ffffff; color: #24292f; }"
    "QTableWidget QLineEdit:focus { background: #ddf4ff; }"
)


def dialog_shell(dialog: QDialog, title: str) -> QVBoxLayout:
    dialog.setWindowTitle(title)
    dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    dialog.setStyleSheet(DIALOG_STYLE)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    bar = QFrame(dialog)
    bar.setObjectName("titleBar")
    bar.setFixedHeight(40)
    row = QHBoxLayout(bar)
    row.setContentsMargins(12, 6, 8, 6)
    label = QLabel(title, bar)
    label.setObjectName("windowTitle")
    row.addWidget(label)
    row.addStretch()
    outer.addWidget(bar)
    return outer


class _TablePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout_data = None
        self.setMinimumSize(500, 260)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        if self.layout_data is not None:
            layout = self.layout_data
            scale = min((self.width() - 32) / layout.width_mm, (self.height() - 32) / layout.height_mm)
            layout.draw(painter, QPointF((self.width() - layout.width_mm * scale) / 2,
                                        (self.height() - layout.height_mm * scale) / 2), scale)
        else:
            painter.setPen(QColor("#57606a"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Não há perfis de aço no modelo.")
        painter.end()


class _TableTypeButton(QPushButton):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        # Import after the sheet modules are loaded: home also uses the palettes.
        from .home import ScrollingNameLabel

        self.setObjectName("tableTypeButton")
        self.setAccessibleName(title)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        self.name_label = ScrollingNameLabel(title, self)
        self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.name_label)
        self.toggled.connect(self._update_label)
        self._update_label()

    def _update_label(self, *_):
        selected = self.isChecked()
        self.name_label.setStyleSheet(
            f"color: {'#24292f' if selected else '#57606a'}; background: transparent;"
        )
        self.name_label.set_fade_color(
            "#d0d7de" if selected else "#eaeef2" if self.underMouse() else "#f6f8fa"
        )

    def enterEvent(self, event):
        super().enterEvent(event)
        self._update_label()
        self.name_label.start_scrolling()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._update_label()
        self.name_label.stop_scrolling()


class InsertSheetTableDialog(QDialog):
    def __init__(self, parent, sheet_names, active_sheet, sheet_settings, project_settings,
                 steel_rows=None, plate_rows=None, accessory_rows=None):
        super().__init__(parent)
        self.resize(1040, 600)
        self.result_table = None
        self._steel_rows = steel_rows or []
        self._plate_rows = plate_rows or []
        self._accessory_rows = accessory_rows or []
        self._settings = sheet_settings
        self._project_settings = project_settings
        self._sheet_name = active_sheet if active_sheet in sheet_names else next(iter(sheet_names), "")
        outer = dialog_shell(self, "Inserir tabela")
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        self.types = QListWidget(self)
        self.types.setObjectName("tableTypeList")
        self.types.setFixedWidth(220)
        self.types.setSpacing(8)
        self.types.setFocusPolicy(Qt.NoFocus)
        self.types.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.types.setStyleSheet(
            "QListWidget#tableTypeList::item { padding: 0; }"
            "QPushButton#tableTypeButton { min-height: 0; padding: 0; border: 0; "
            "border-radius: 6px; background: transparent; }"
            "QPushButton#tableTypeButton:hover { background: #eaeef2; }"
            "QPushButton#tableTypeButton:checked { background: #d0d7de; }"
        )
        self._type_buttons = []
        for index, (kind, title) in enumerate(TABLE_TITLES.items()):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, kind)
            item.setSizeHint(QSize(0, 42))
            self.types.addItem(item)
            button = _TableTypeButton(title, self.types)
            button.clicked.connect(lambda _checked=False, row=index: self.types.setCurrentRow(row))
            self.types.setItemWidget(item, button)
            self._type_buttons.append(button)
        content.addWidget(self.types)
        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 14)
        body.setSpacing(12)
        self.preview = _TablePreview(self)
        body.addWidget(self.preview, 1)
        self.scope_hint = QLabel(self)
        self.scope_hint.setWordWrap(True)
        body.addWidget(self.scope_hint)
        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addStretch()
        close = QPushButton("Fechar", self)
        close.clicked.connect(self.reject)
        self.insert_button = QPushButton("Inserir tabela", self)
        self.insert_button.setObjectName("primaryAction")
        self.insert_button.clicked.connect(self._insert)
        footer.addWidget(close)
        footer.addWidget(self.insert_button)
        body.addLayout(footer)
        content.addLayout(body, 1)
        outer.addLayout(content, 1)
        self.types.currentRowChanged.connect(self._update_preview)
        self.types.setCurrentRow(0)

    def _update_preview(self, *_):
        current = self.types.currentItem()
        if current is None or not self._sheet_name:
            self.insert_button.setEnabled(False)
            return
        for index, button in enumerate(self._type_buttons):
            button.setChecked(index == self.types.currentRow())
        kind = current.data(Qt.UserRole)
        self.insert_button.setEnabled(True)
        if kind == "steel_profiles":
            self.preview.layout_data = SteelProfilesTableLayout(self._steel_rows, 175.0, self.font())
            self.scope_hint.setText("Perfis de aço do modelo, agrupados por perfil e material. Comprimentos em metros e pesos em quilogramas.")
        elif kind == "steel_plates":
            self.preview.layout_data = SteelPlatesTableLayout(self._plate_rows, 175.0, self.font())
            self.scope_hint.setText(
                "Chapas de aço das placas e dos componentes do modelo, agrupadas por dimensão, espessura e material. "
                "Comprimentos em metros e pesos em quilogramas. Placas não retangulares usam comprimento equivalente pela área."
            )
        elif kind == "accessories":
            self.preview.layout_data = AccessoriesTableLayout(self._accessory_rows, 175.0, self.font())
            self.scope_hint.setText(
                "Acessórios dos componentes do modelo, agrupados pelo nome. "
                "Fixadores usam a identidade informada ou uma descrição automática com dimensões e material."
            )
        else:
            rows = revision_rows_for(self._settings[self._sheet_name], self._project_settings, kind)
            self.preview.layout_data = RevisionTableLayout(kind, rows, 175.0, self.font())
            self.scope_hint.setText(
                "As revisões do projeto são compartilhadas entre todas as folhas que usam esta tabela."
                if kind == "project_revisions" else f"As revisões desta tabela pertencem somente à folha {self._sheet_name}."
            )
        self.preview.update()

    def _insert(self):
        item = self.types.currentItem()
        kind = item.data(Qt.UserRole) if item is not None else None
        if self._sheet_name and kind in TABLE_TITLES:
            self.result_table = (self._sheet_name, kind)
            self.accept()


class RevisionTableEditor(QDialog):
    def __init__(self, parent, kind: str, rows: list[dict], sheet_name: str):
        super().__init__(parent)
        self.resize(900, 430)
        self.result_rows = None
        outer = dialog_shell(self, TABLE_TITLES[kind])
        body = QVBoxLayout()
        body.setContentsMargins(18, 16, 18, 14)
        body.setSpacing(12)
        body.addWidget(QLabel(
            "Alterações compartilhadas entre todas as folhas com esta tabela."
            if kind == "project_revisions" else f"Folha: {sheet_name}", self))
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(REVISION_COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 60)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 150)
        self.table.setWordWrap(True)
        body.addWidget(self.table, 1)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        add = QPushButton("Adicionar revisão", self)
        remove = QPushButton("Remover revisão", self)
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        actions.addWidget(add)
        actions.addWidget(remove)
        actions.addStretch()
        close = QPushButton("Fechar", self)
        close.clicked.connect(self.reject)
        apply = QPushButton("Aplicar", self)
        apply.setObjectName("primaryAction")
        apply.clicked.connect(self._apply)
        actions.addWidget(close)
        actions.addWidget(apply)
        body.addLayout(actions)
        outer.addLayout(body, 1)
        for row in copy.deepcopy(rows):
            self._append(row)
        self.table.itemChanged.connect(self._resize_rows)
        self._resize_rows()

    def _append(self, row: dict):
        index = self.table.rowCount()
        self.table.insertRow(index)
        for column, key in enumerate(("number", "change", "responsible")):
            item = QTableWidgetItem(str(row.get(key, "")))
            item.setTextAlignment(Qt.AlignCenter if column == 0 else Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(index, column, item)
        date_input = QLineEdit(str(row.get("date", "")), self.table)
        date_input.setPlaceholderText("dd/mm/aaaa")
        date_input.setMaxLength(10)
        date_input.setAlignment(Qt.AlignCenter)
        self.table.setCellWidget(index, 3, date_input)

    def _add(self):
        numbers = [int(self.table.item(i, 0).text()) for i in range(self.table.rowCount())
                   if self.table.item(i, 0) and self.table.item(i, 0).text().isdigit()]
        self._append({"number": f"{max(numbers, default=0) + 1:02d}", "change": "",
                      "responsible": "", "date": ""})
        self._resize_rows()
        self.table.setCurrentCell(self.table.rowCount() - 1, 1)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 1))

    def _remove(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def _resize_rows(self, *_):
        self.table.resizeRowsToContents()
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, max(42, self.table.rowHeight(row)))

    def _apply(self):
        # Closing the active delegate commits a cell currently being edited.
        self.table.setFocus()
        self.result_rows = [
            {"number": self.table.item(i, 0).text(), "change": self.table.item(i, 1).text(),
             "responsible": self.table.item(i, 2).text(),
             "date": self.table.cellWidget(i, 3).text().strip()}
            for i in range(self.table.rowCount())
        ]
        self.accept()
