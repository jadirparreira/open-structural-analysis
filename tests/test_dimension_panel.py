"""Individual dimension inspector edits and inherited units."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from osa.ui.dimension_panel import ProjectSheetDimensionPanel
from osa.ui.dimension_properties import dimension_unit, dimension_value
from osa.ui.project_sheet import ProjectSheetWorkspace


@pytest.fixture
def inspector():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.resize(1400, 1000)
    ws = ProjectSheetWorkspace(window)
    ws.resize(1000, 800)
    dimensions = [{"start": (0., 0.), "end": (.2, 0.), "offset": (0., -.1)},
                  {"start": (0., 0.), "end": (.3, 0.), "offset": (0., -.2)}]
    ws.set_sheet_views([{"segments": (((0., 0.), (.2, 0.)),), "dimensions": dimensions}])
    ws._project_settings["dimension_unit"] = "cm"
    ws._selected_dimension = (0, 0)
    panel = ProjectSheetDimensionPanel(window, ws)
    window.show()
    panel.show_for((0, 0))
    yield app, ws, panel, dimensions
    window.close()
    app.processEvents()


def test_value_unit_override_default_and_reset(inspector):
    _app, ws, panel, dimensions = inspector
    first, second = dimensions
    assert panel.value_input.text() == "20"
    assert panel.unit_input.currentText() == "Padrão (cm)"
    panel.unit_input.setCurrentIndex(panel.unit_input.findData("mm"))
    assert first["unit"] == "mm"
    assert panel.value_input.text() == "200"
    panel.value_input.setText("215,5")
    panel.value_input.editingFinished.emit()
    assert first["value_override"] == pytest.approx(.2155)
    assert "unit" not in second and "value_override" not in second
    assert first["end"] == (.2, 0.)
    panel.unit_input.setCurrentIndex(0)
    assert "unit" not in first
    assert panel.value_input.text() == "21,55"
    ws._project_settings["dimension_unit"] = "m"
    panel.show_for((0, 0))
    assert panel.value_input.text() == "0,2155"
    assert dimension_unit(first, ws._project_settings) == "m"
    assert dimension_value(ws, 0, json.loads(json.dumps(first))) == pytest.approx(.2155)
    panel.value_input.clear()
    panel.value_input.editingFinished.emit()
    assert "value_override" not in first
    assert panel.value_input.text() == "0,2"


def test_invalid_value_and_deselection_do_not_mutate_dimension(inspector):
    _app, ws, panel, dimensions = inspector
    for text in ("abc", "nan", "inf"):
        panel.value_input.setText(text)
        panel.value_input.editingFinished.emit()
        assert panel.value_input.text() == "20"
        assert "value_override" not in dimensions[0]
    ws._selected_dimension = None
    panel.value_input.setText("123")
    panel.value_input.editingFinished.emit()
    assert "value_override" not in dimensions[0]


def test_main_window_dimension_selection_and_delete_in_value_field():
    from osa.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        window.show()
        window.set_detailing_project_mode(True)
        ws = window.project_sheet_workspace
        window.view_stack.setCurrentWidget(ws)
        app.processEvents()
        dimension = {"start": (0., 0.), "end": (.2, 0.), "offset": (0., -.1)}
        ws.set_sheet_views([{"dimensions": [dimension]}])
        ws.select_view(0)
        ws._selected_dimension = (0, 0)
        app.processEvents()
        panel = window.project_sheet_dimension_panel
        assert panel.isVisible()
        assert not window.project_sheet_view_panel.isVisible()
        panel.value_input.setFocus()
        window.delete_selected()
        assert ws._sheet_views[0]["dimensions"] == [dimension]
        ws.setFocus()
        QTest.keyClick(ws, Qt.Key.Key_Delete)
        app.processEvents()
        assert ws._sheet_views[0]["dimensions"] == []
        assert not panel.isVisible()
    finally:
        window._saved_revision = window.model.revision
        window._saved_view_revision = window.model.view_revision
        window.scene.plotter.close()
        window.close()
        app.processEvents()


def test_overridden_value_is_drawn_in_selected_unit(inspector):
    from PySide6.QtGui import QImage, QPainter

    _app, ws, panel, dimensions = inspector

    class TextPainter(QPainter):
        def drawText(self, *args):
            texts.extend(arg for arg in args if isinstance(arg, str))
            return super().drawText(*args)

    ws._view_draw_data = {0: (0., 0., 300., 300., 1000.)}
    ws._sheet_pixels_per_mm = 2.
    dimension = dimensions[0]
    dimension.update(unit="mm", value_override=.215)
    panel.show_for((0, 0))
    panel.decimal_places_input.setCurrentIndex(panel.decimal_places_input.findData(1))
    texts = []
    image = QImage(800, 800, QImage.Format.Format_ARGB32)
    painter = TextPainter(image)
    try:
        assert ws._draw_dimension(painter, 0, dimension) is not None
    finally:
        painter.end()
    assert "215.0" in texts


@pytest.mark.parametrize(("kind", "default"), [(None, 0), ("angular", 1), ("level", 3)])
def test_decimal_places_override_and_inherit_settings(inspector, kind, default):
    _app, ws, panel, dimensions = inspector
    dimension = dimensions[0]
    if kind:
        dimension["kind"] = kind
        dimension["value_override"] = 12.345678
    panel.show_for((0, 0))
    assert panel.decimal_places_input.currentText() == f"Padrão ({default})"
    panel.decimal_places_input.setCurrentIndex(panel.decimal_places_input.findData(4))
    assert dimension["decimal_places"] == 4
    assert "decimal_places" not in dimensions[1]
    assert json.loads(json.dumps(dimension))["decimal_places"] == 4
    panel.show_for((0, 0))
    assert panel.decimal_places_input.currentData() == 4
    panel.decimal_places_input.setCurrentIndex(0)
    assert "decimal_places" not in dimension
    key = f"{kind}_dimension_decimal_places" if kind else "dimension_decimal_places"
    ws._project_settings[key] = 2
    panel.show_for((0, 0))
    assert panel.decimal_places_input.currentText() == "Padrão (2)"
