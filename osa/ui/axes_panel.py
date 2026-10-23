import math

from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QTableWidget, QTableWidgetItem

from osa.model import ReferenceAxis

from .common import *
from .window_frame import WindowFrame


class AxisLabelDelegate(QStyledItemDelegate):
    """Limit axis labels to uppercase letters and numbers."""

    def createEditor(self, parent, _option, _index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet(
            "QLineEdit { border: 0; background: #ffffff; padding: 0; color: #24292f; "
            "selection-background-color: #0969da; selection-color: #ffffff; }"
        )
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9]*"), editor))
        editor.textEdited.connect(lambda text, field=editor: self._uppercase(field, text))
        return editor

    @staticmethod
    def _uppercase(editor: QLineEdit, text: str) -> None:
        uppercase = text.upper()
        if uppercase == text:
            return
        cursor_position = editor.cursorPosition()
        editor.setText(uppercase)
        editor.setCursorPosition(cursor_position)

    def setModelData(self, editor, model, index) -> None:
        model.setData(index, editor.text().upper())


class AxisValueDelegate(QStyledItemDelegate):
    """Edit axis coordinates as plain decimal values with up to three places."""

    def createEditor(self, parent, _option, _index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setStyleSheet(
            "QLineEdit { border: 0; background: #ffffff; padding: 0; color: #24292f; "
            "selection-background-color: #0969da; selection-color: #ffffff; }"
        )
        editor.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[+-]?(?:\d+(?:\.\d{0,3})?)?"), editor)
        )
        return editor

    def setEditorData(self, editor, index) -> None:
        editor.setText(str(index.data() or ""))

    def setModelData(self, editor, model, index) -> None:
        value = editor.text()
        if not value or value in ("+", "-"):
            model.setData(index, "")
            return
        model.setData(index, self._format(float(value)))

    def displayText(self, value, _locale) -> str:
        if value in (None, ""):
            return ""
        try:
            return self._format(float(value))
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _format(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")


class AxesPanel(QFrame):
    """Floating placeholder for configuring the structural reference axes."""

    visibility_changed = Signal(bool)
    axis_selection_changed = Signal(object)

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)

        title = QLabel("Eixos")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)

        self._axis_lists: dict[str, QTableWidget] = {}
        for axis in ("X", "Y", "Z"):
            layout.addWidget(self._axis_header(axis))
            axes_list = self._create_axis_list()
            self._axis_lists[axis] = axes_list
            axes_list.itemChanged.connect(
                lambda _item, direction=axis: self._sort_axis_rows(direction)
            )
            axes_list.itemSelectionChanged.connect(
                lambda direction=axis: self._emit_axis_selection(direction)
            )
            layout.addWidget(axes_list)

        self.adjustSize()
        self._loaded = False
        self.hide()

    def _axis_header(self, axis: str) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(f"Eixos {axis}")
        label.setObjectName("propertySection")
        layout.addWidget(label)
        layout.addStretch(1)
        for icon, tooltip, callback in (
            (
                "map-pin-plus.svg",
                f"Definir eixo {axis} pelo modelo 3D",
                lambda _checked=False, axis=axis: self.window.start_reference_axis_placement(axis),
            ),
            ("plus.svg", f"Adicionar eixo {axis}", lambda _checked=False, axis=axis: self._add_axis_row(axis)),
            ("minus.svg", f"Remover eixo {axis}", lambda _checked=False, axis=axis: self._remove_axis_rows(axis)),
        ):
            button = QToolButton()
            button.setFixedSize(26, 26)
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon)))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.clicked.connect(callback)
            button.setStyleSheet(
                "QToolButton { border: 0; border-radius: 5px; background: transparent; padding: 2px; }"
                "QToolButton:hover { background: #eaeef2; }"
                "QToolButton:pressed { background: #d0d7de; }"
            )
            layout.addWidget(button)
        return header

    @staticmethod
    def _create_axis_list() -> QTableWidget:
        axes_list = QTableWidget(0, 2)
        axes_list.setObjectName("axisList")
        axes_list.setFixedHeight(80)
        axes_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        axes_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        axes_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        axes_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        axes_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        axes_list.verticalHeader().setVisible(False)
        axes_list.horizontalHeader().setVisible(False)
        axes_list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        axes_list.setItemDelegateForColumn(0, AxisLabelDelegate(axes_list))
        axes_list.setItemDelegateForColumn(1, AxisValueDelegate(axes_list))
        axes_list.setStyleSheet(
            "QTableWidget#axisList { border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; "
            "gridline-color: #eaeef2; }"
            "QTableWidget#axisList::item { padding: 4px 8px; }"
            "QTableWidget#axisList::item:selected, QTableWidget#axisList::item:selected:active, "
            "QTableWidget#axisList::item:selected:!active { background: #ffffff; color: #24292f; "
            "font-weight: 700; }"
            "QHeaderView::section { background: #f6f8fa; border: 0; border-bottom: 1px solid #d0d7de; "
            "padding: 5px 8px; color: #57606a; font-weight: 600; }"
        )
        return axes_list

    def _add_axis_row(self, axis: str) -> None:
        axes_list = self._axis_lists[axis]
        row = axes_list.rowCount()
        axes_list.insertRow(row)
        axes_list.setRowHeight(row, 28)
        label = QTableWidgetItem()
        axes_list.setItem(row, 0, label)
        axes_list.setItem(row, 1, QTableWidgetItem())
        axes_list.setCurrentCell(row, 0)
        axes_list.editItem(label)

    def _remove_axis_rows(self, axis: str) -> None:
        axes_list = self._axis_lists[axis]
        rows = sorted({item.row() for item in axes_list.selectedItems()}, reverse=True)
        for row in rows:
            axes_list.removeRow(row)

    def _sort_axis_rows(self, direction: str) -> None:
        """Keep numeric coordinates ascending and incomplete rows at the end."""
        axes_list = self._axis_lists[direction]
        current_item = axes_list.currentItem()
        current_column = axes_list.currentColumn()
        selected_items = {id(item) for item in axes_list.selectedItems()}
        rows = []
        for row in range(axes_list.rowCount()):
            label_item = axes_list.takeItem(row, 0)
            value_item = axes_list.takeItem(row, 1)
            value_text = value_item.text().strip() if value_item is not None else ""
            try:
                sort_value = float(value_text)
                if not math.isfinite(sort_value):
                    sort_value = math.inf
            except ValueError:
                sort_value = math.inf
            rows.append((sort_value, row, label_item, value_item))

        rows.sort(key=lambda entry: (entry[0], entry[1]))
        was_blocked = axes_list.blockSignals(True)
        axes_list.setRowCount(0)
        for new_row, (_sort_value, _old_row, label_item, value_item) in enumerate(rows):
            axes_list.insertRow(new_row)
            axes_list.setRowHeight(new_row, 28)
            if label_item is not None:
                axes_list.setItem(new_row, 0, label_item)
            if value_item is not None:
                axes_list.setItem(new_row, 1, value_item)
            if current_item is label_item or current_item is value_item:
                axes_list.setCurrentCell(new_row, max(0, current_column))
            if id(label_item) in selected_items or id(value_item) in selected_items:
                axes_list.selectRow(new_row)
        axes_list.blockSignals(was_blocked)
        self._emit_axis_selection(direction)

    def _emit_axis_selection(self, direction: str) -> None:
        axes_list = self._axis_lists[direction]
        selected_rows = {item.row() for item in axes_list.selectedItems()}
        if not selected_rows:
            self.axis_selection_changed.emit(None)
            return
        row = axes_list.currentRow()
        if row not in selected_rows:
            row = max(selected_rows)
        label_item = axes_list.item(row, 0)
        label = label_item.text().strip() if label_item is not None else ""
        self.axis_selection_changed.emit((direction, label) if label else None)

    def add_axis_from_point(self, direction: str, point: object) -> bool:
        """Append a uniquely named axis using the matching coordinate of a 3D point."""
        axes_list = self._axis_lists[direction]
        coordinate_index = {"X": 0, "Y": 1, "Z": 2}[direction]
        value = round(float(point[coordinate_index]), 3)
        labels: set[str] = set()
        values: set[float] = set()
        for row in range(axes_list.rowCount()):
            label_item = axes_list.item(row, 0)
            value_item = axes_list.item(row, 1)
            if label_item is not None:
                labels.add(label_item.text().strip().upper())
            if value_item is not None:
                try:
                    values.add(round(float(value_item.text()), 3))
                except ValueError:
                    continue
        if value in values:
            return False

        if direction == "X":
            number = 1
            while str(number) in labels:
                number += 1
            label = str(number)
        elif direction == "Y":
            label_index = 1
            while True:
                remainder = label_index
                letters = ""
                while remainder:
                    remainder, digit = divmod(remainder - 1, 26)
                    letters = chr(ord("A") + digit) + letters
                if letters not in labels:
                    label = letters
                    break
                label_index += 1
        else:
            label = str(round(value * 100))
            if label in labels:
                return False
        row = axes_list.rowCount()
        axes_list.insertRow(row)
        axes_list.setRowHeight(row, 28)
        axes_list.setItem(row, 0, QTableWidgetItem(label))
        axes_list.setItem(row, 1, QTableWidgetItem(AxisValueDelegate._format(value)))
        axes_list.setCurrentCell(row, 0)
        self._commit_valid_axes(refresh_scene=False)
        return True

    def showEvent(self, event) -> None:
        self._load_axes()
        self._loaded = True
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        self.axis_selection_changed.emit(None)
        if self._loaded:
            self._commit_valid_axes()
            self._loaded = False
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def discard(self) -> None:
        """Hide stale table values before replacing or clearing the model."""
        self._loaded = False
        self.hide()

    def _load_axes(self) -> None:
        for direction, axes_list in self._axis_lists.items():
            axes_list.setRowCount(0)
            for axis in self.window.model.axes[direction]:
                row = axes_list.rowCount()
                axes_list.insertRow(row)
                axes_list.setRowHeight(row, 28)
                axes_list.setItem(row, 0, QTableWidgetItem(axis.label))
                axes_list.setItem(row, 1, QTableWidgetItem(AxisValueDelegate._format(axis.value)))
            self._sort_axis_rows(direction)

    def _commit_valid_axes(self, *, refresh_scene: bool = True) -> None:
        for direction in self._axis_lists:
            self._sort_axis_rows(direction)
        axes: dict[str, tuple[ReferenceAxis, ...]] = {}
        for direction, axes_list in self._axis_lists.items():
            labels: set[str] = set()
            values: set[float] = set()
            valid: list[ReferenceAxis] = []
            for row in range(axes_list.rowCount()):
                label_item = axes_list.item(row, 0)
                value_item = axes_list.item(row, 1)
                label = label_item.text().strip().upper() if label_item is not None else ""
                value_text = value_item.text().strip() if value_item is not None else ""
                if not label or not value_text or not label.isascii() or not label.isalnum():
                    continue
                try:
                    value = round(float(value_text), 3)
                except ValueError:
                    continue
                if label in labels or value in values:
                    continue
                labels.add(label)
                values.add(value)
                valid.append(ReferenceAxis(label, value))
            axes[direction] = tuple(valid)

        if axes != self.window.model.axes:
            self.window.model_service.set_reference_axes(axes)
            if refresh_scene:
                self.window.refresh_scene()

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move(
            self.window.width() - margin - self.width() - 24,
            (self.window.height() - self.height()) // 2,
        )
        self.raise_()
