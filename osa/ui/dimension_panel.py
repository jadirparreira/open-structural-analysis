"""Property inspector for a single sheet dimension."""
import math

from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QLineEdit, QVBoxLayout

from .dimension_properties import UNIT_SCALES, dimension_unit, dimension_value
from .special_dimensions import SPECIAL_DIMENSION_DEFAULTS
from .window_frame import WindowFrame


class ProjectSheetDimensionPanel(QFrame):
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
        title = QLabel("Cota", self)
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("Valor", self))
        self.value_input = QLineEdit(self)
        self.value_input.setAccessibleName("Valor da cota")
        self.value_input.setToolTip("Apague o valor para restaurar a medida calculada")
        self.value_input.editingFinished.connect(self._commit_value)
        layout.addWidget(self.value_input)
        layout.addWidget(QLabel("Unidade", self))
        self.unit_input = QComboBox(self)
        self.unit_input.setAccessibleName("Unidade da cota")
        self.unit_input.currentIndexChanged.connect(self._commit_unit)
        layout.addWidget(self.unit_input)
        layout.addWidget(QLabel("Casas decimais", self))
        self.decimal_places_input = QComboBox(self)
        self.decimal_places_input.setAccessibleName("Casas decimais da cota")
        self.decimal_places_input.currentIndexChanged.connect(self._commit_decimal_places)
        layout.addWidget(self.decimal_places_input)
        self.hide()

    def show_for(self, selection):
        self._selection = selection
        if selection is None:
            self.hide()
            return
        view_index, dimension_index = selection
        dimension = self._workspace._sheet_views[view_index]["dimensions"][dimension_index]
        unit = dimension_unit(dimension, self._workspace._project_settings)
        self.unit_input.blockSignals(True)
        self.unit_input.clear()
        default = dimension_unit({"kind": dimension.get("kind")}, self._workspace._project_settings)
        self.unit_input.addItem(f"Padrão ({default})", None)
        for choice in (("°",) if dimension.get("kind") == "angular" else ("mm", "cm", "dm", "m")):
            self.unit_input.addItem(choice, choice)
        self.unit_input.setCurrentIndex(max(0, self.unit_input.findData(dimension.get("unit"))))
        self.unit_input.blockSignals(False)
        kind = dimension.get("kind")
        key = f"{kind}_dimension_decimal_places" if kind in {"angular", "level"} else "dimension_decimal_places"
        default_decimals = self._workspace._project_settings.get(key, SPECIAL_DIMENSION_DEFAULTS.get(key, 0))
        self.decimal_places_input.blockSignals(True)
        self.decimal_places_input.clear()
        self.decimal_places_input.addItem(f"Padrão ({default_decimals})", None)
        for decimals in range(9):
            self.decimal_places_input.addItem(str(decimals), decimals)
        self.decimal_places_input.setCurrentIndex(max(
            0, self.decimal_places_input.findData(dimension.get("decimal_places")),
        ))
        self.decimal_places_input.blockSignals(False)
        value = dimension_value(self._workspace, view_index, dimension) * UNIT_SCALES[unit]
        self._displayed_text = f"{value:.8f}".rstrip("0").rstrip(".").replace(".", ",")
        self.value_input.setText(self._displayed_text)
        self.adjustSize()
        self.show()
        self.reposition()

    def _dimension(self):
        if self._selection != self._workspace._selected_dimension or self._selection is None:
            return None
        vi, di = self._selection
        return self._workspace._sheet_views[vi]["dimensions"][di]

    def _commit_value(self):
        dimension = self._dimension()
        if dimension is None or self.value_input.text() == self._displayed_text:
            return
        text = self.value_input.text().strip()
        try:
            if text:
                value = float(text.replace(",", "."))
                if not math.isfinite(value):
                    raise ValueError
                unit = dimension_unit(dimension, self._workspace._project_settings)
                dimension["value_override"] = value / UNIT_SCALES[unit]
            else:
                dimension.pop("value_override", None)
        except ValueError:
            self.show_for(self._selection)
            return
        self._changed()

    def _commit_unit(self):
        dimension = self._dimension()
        if dimension is None:
            return
        unit = self.unit_input.currentData()
        if unit is None:
            dimension.pop("unit", None)
        else:
            dimension["unit"] = unit
        self._changed()

    def _commit_decimal_places(self):
        dimension = self._dimension()
        if dimension is None:
            return
        decimals = self.decimal_places_input.currentData()
        if decimals is None:
            dimension.pop("decimal_places", None)
        else:
            dimension["decimal_places"] = decimals
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
