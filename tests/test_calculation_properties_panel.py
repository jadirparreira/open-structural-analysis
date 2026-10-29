import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QToolButton, QWidget

from osa.model import StructuralModel
import osa.ui.calculation_properties_panel as calculation_properties_panel
from osa.ui.calculation_properties_panel import CalculationPropertiesPanel
from osa.ui.main_window import MainWindow


class _PanelContext(QWidget):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.palette = SimpleNamespace(active_group="Memorial")
        self.verification_panel = SimpleNamespace(status=QLabel(), summary=QLabel())

    def refresh_scene(self):
        pass

    def refresh_selected_property_panel(self, _section):
        pass


def _model(section="Barra Retangular"):
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 1.25)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", section)
    return model


def test_calculation_properties_panel_saves_and_resets_manual_override():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model())
    panel = CalculationPropertiesPanel(window)
    window.refresh_selected_property_panel = lambda _section: panel.configure_for(("B1",))
    panel.configure_for(("B1",))

    assert panel._inputs["Ct"].isEnabled()
    assert panel._inputs["Cb"].isEnabled()
    initial_revision = window.model.calculation_properties_revision
    window.verification_panel.summary.setText("resumo existente")
    panel._inputs["Lb"].editingFinished.emit()
    assert window.model.calculation_properties_revision == initial_revision
    assert not window.model.bars["B1"].calculation_property_overrides
    assert window.verification_panel.summary.text() == "resumo existente"

    panel._inputs["Lb"].setValue(2.5)
    panel._inputs["Lb"].editingFinished.emit()
    assert dict(window.model.bars["B1"].calculation_property_overrides)["Lb"] == 2.5
    assert window.model.calculation_properties_revision == initial_revision + 1
    assert window.verification_panel.summary.text() == "resumo existente"
    assert not panel._reset_buttons["Lb"].isHidden()

    panel._reset_buttons["Lb"].click()
    assert "Lb" not in dict(window.model.bars["B1"].calculation_property_overrides)
    assert panel._reset_buttons["Lb"].isHidden()
    panel.close()
    window.close()
    del app


def test_calculation_properties_panel_uses_memorial_unbraced_lengths(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model())
    memory = {
        "geometric_parameters": {
            "Ly_cm": 114.3,
            "Lz_cm": 800.0,
            "Lt_cm": 114.3,
            "Lb_cm": 114.3,
        }
    }
    monkeypatch.setattr(
        calculation_properties_panel,
        "calculation_memory",
        lambda _model, _member_names: memory,
    )
    panel = CalculationPropertiesPanel(window)

    panel.configure_for(("B1",))

    assert panel._inputs["Ly"].value() == 1.143
    assert panel._inputs["Lz"].value() == 8.0
    assert panel._inputs["Lt"].value() == 1.143
    assert panel._inputs["Lb"].value() == 1.143

    panel.close()
    window.close()
    del app


def test_changing_member_calculation_property_preserves_other_verification_results():
    model = _model()
    model.add_node("C", 0, 0, 2.5)
    model.add_bar("B2", "B", "C")
    model.verification_results = {
        "bar:B1": {"status": "checked"},
        "bar:B2": {"status": "checked"},
    }

    model.update_bar_calculation_property("B1", "Cb", 1.5)

    assert "bar:B1" not in model.verification_results
    assert model.verification_results["bar:B2"] == {"status": "checked"}


def test_invalid_cb_edit_is_rejected_without_raising_from_qt_signal():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model())
    panel = CalculationPropertiesPanel(window)
    panel.configure_for(("B1",))
    spin = panel._inputs["Cb"]
    # Simulate an invalid value reaching the commit path despite the widget's
    # normal range validator.
    spin.setRange(0.1, 2.5)
    spin.setValue(0.5)

    spin.editingFinished.emit()

    assert spin.value() == 1.0
    assert "Cb" not in dict(window.model.bars["B1"].calculation_property_overrides)
    assert "Cb deve estar entre 1,0 e 2,5" in window.verification_panel.status.text()
    panel.close()
    window.close()
    del app


def test_calculation_properties_panel_disables_cb_when_section_routine_does_not_use_it():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model("Barra Circular"))
    panel = CalculationPropertiesPanel(window)
    panel.configure_for(("B1",))

    assert panel._inputs["Ct"].isEnabled()
    assert not panel._inputs["Cb"].isEnabled()
    assert not panel._inputs["Lb"].isEnabled()
    assert not panel._inputs["Lt"].isEnabled()
    panel.close()
    window.close()
    del app


def test_calculation_properties_panel_sizes_to_show_its_fields():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model())
    window.resize(900, 700)
    window.properties = SimpleNamespace(
        x=lambda: 700,
        y=lambda: 100,
        height=lambda: 500,
    )
    panel = CalculationPropertiesPanel(window)
    panel.configure_for(("B1",))

    assert [panel._labels[name].text() for name, *_ in panel._FIELDS] == [
        "L<sub>y</sub>", "L<sub>z</sub>", "L<sub>t</sub>",
        "L<sub>b</sub>", "C<sub>t</sub>", "C<sub>b</sub>",
    ]
    assert not panel.findChildren(QCheckBox)
    assert panel._unit_labels["Ly"].text() == "m"
    assert not panel._unit_labels["Ly"].isHidden()
    assert panel._unit_labels["Ct"].isHidden()
    assert all(panel._labels[name].toolTip() for name, *_ in panel._FIELDS)
    assert all(panel._inputs[name].toolTip() for name, *_ in panel._FIELDS)
    assert "NBR 8800:2024" in panel._labels["Lz"].toolTip()
    window.show()

    panel.reposition()
    panel.show()
    app.processEvents()

    assert panel.width() == CalculationPropertiesPanel.WIDTH
    assert panel.height() > 200
    fields_grid = panel.layout().itemAt(1).layout()
    assert [fields_grid.getItemPosition(index)[:2] for index in range(6)] == [
        (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1),
    ]
    assert all(
        spin.mapTo(panel, spin.rect().bottomRight()).y() < panel.height()
        for spin in panel._inputs.values()
    )
    assert panel.y() >= 0
    assert panel.y() + panel.height() <= window.height()

    panel.close()
    window.close()
    del app


def test_calculation_properties_button_opens_panel_for_selected_bar():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    panel = QWidget(window)
    panel.hide()
    panel.configure_for = lambda names: setattr(panel, "configured_names", names)
    panel.reposition = lambda: None
    button = QToolButton(window)
    button.setCheckable(True)
    properties = SimpleNamespace(
        _selected_names=lambda kind: ["B1"] if kind == "bar" else [],
        _calculation_properties_button=button,
        _section_settings_button=QToolButton(window),
        _displacement_settings_button=QToolButton(window),
        close_color_palette=lambda: None,
    )
    window.calculation_properties_panel = panel
    window.properties = properties
    # The visible button is the source of truth for this action. Session state
    # may have changed while the selected inspector is still showing Memorial.
    window.palette = SimpleNamespace(active_group="Geometria")
    window.close_section_panel = lambda *_args: None
    window.close_displacement_panel = lambda *_args: None
    window.close_calculation_properties_panel = lambda *_args: panel.hide()
    button.clicked.connect(lambda: MainWindow.toggle_calculation_properties_panel(window, button))
    window.show()

    button.click()
    app.processEvents()

    assert panel.isVisible()
    assert panel.configured_names == ["B1"]
    assert button.isChecked()

    window.close()
    del app
