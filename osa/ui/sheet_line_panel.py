"""Appearance inspector for drawing lines on sheets and inserted views."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from .window_frame import WindowFrame

LINE_STYLES = {
    "continuous": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dash_dot": Qt.PenStyle.DashDotLine,
}


class ProjectSheetLinePanel(QFrame):
    def __init__(self, window, workspace):
        super().__init__(window)
        self._window = window
        self._workspace = workspace
        self._selection = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Linha de desenho", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Tipo de linha", self))
        self.style_input = QComboBox(self)
        self.style_input.setAccessibleName("Tipo da linha de desenho")
        for label, key in (("Contínua", "continuous"), ("Traço", "dash"), ("Traço e ponto", "dash_dot")):
            self.style_input.addItem(label, key)
        self.style_input.currentIndexChanged.connect(self._commit_style)
        layout.addWidget(self.style_input)
        layout.addWidget(QLabel("Cor", self))
        self.color_button = QToolButton(self)
        self.color_button.setFixedSize(34, 34)
        self.color_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_button.setAccessibleName("Cor da linha de desenho")
        self.color_button.clicked.connect(self._choose_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_button)
        color_row.addStretch()
        layout.addLayout(color_row)
        self.hide()

    def show_for(self, selection):
        self._selection = selection
        line = self._line()
        if line is None:
            self.hide()
            return
        self.style_input.blockSignals(True)
        self.style_input.setCurrentIndex(max(0, self.style_input.findData(line.get("line_style", "continuous"))))
        self.style_input.blockSignals(False)
        color = QColor(line.get("color", "#000000")).name()
        self.color_button.setToolTip(f"Selecionar cor da linha ({color.upper()})")
        self.color_button.setStyleSheet(
            f"QToolButton {{ background: {color}; border: 1px solid #d0d7de; border-radius: 6px; }} "
            "QToolButton:hover { border-color: #0969da; }"
        )
        self.adjustSize()
        self.show()
        self.reposition()

    def _line(self):
        if self._selection is None or self._selection != self._workspace._selected_sheet_line:
            return None
        view_index, line_index = self._selection
        collection = self._workspace._line_annotation_collection(None if view_index < 0 else view_index)
        return collection[line_index] if 0 <= line_index < len(collection) else None

    def _commit_style(self):
        line = self._line()
        if line is not None:
            line["line_style"] = self.style_input.currentData()
            self._changed()

    def _choose_color(self):
        line = self._line()
        if line is None:
            return
        from .dialogs import _DimensionColorDialog

        picker = _DimensionColorDialog(
            line.get("color", "#000000"),
            self._workspace._project_settings.get("sheet_line_custom_colors", ()), self,
        )
        if picker.exec() == QDialog.DialogCode.Accepted and self._line() is line:
            color = QColor(picker.selected_color)
            if color.isValid():
                line["color"] = color.name()
                self._workspace._project_settings["sheet_line_custom_colors"] = list(picker.custom_colors)
                self._changed()

    def _changed(self):
        self._workspace.update()
        self._workspace.layout_changed.emit()
        self.show_for(self._selection)

    def reposition(self):
        margin = 0 if self._window.isMaximized() else WindowFrame.MARGIN
        self.move(self._window.width() - margin - self.width() - 24,
                  (self._window.height() - self.height()) // 2)
        self.raise_()
