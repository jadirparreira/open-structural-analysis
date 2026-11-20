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


def test_tubular_net_area_and_ct_start_unspecified_and_are_saved_explicitly():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model("Tubular Circular"))
    panel = CalculationPropertiesPanel(window)
    window.refresh_selected_property_panel = lambda _section: panel.configure_for(("B1",))
    panel.configure_for(("B1",))
    assert panel._inputs["Ct"].value() == 0.
    assert panel._inputs["Ct"].specialValueText() == "Informar"
    assert panel._inputs["An"].value() == 0.
    assert not window.model.bars["B1"].calculation_property_overrides
    panel._inputs["An"].setValue(8.)
    panel._inputs["An"].editingFinished.emit()
    panel._inputs["Ct"].setValue(1.)
    panel._inputs["Ct"].editingFinished.emit()
    overrides = dict(window.model.bars["B1"].calculation_property_overrides)
    assert overrides == {"An": 8., "Ct": 1.}
    panel.close()
    window.close()
    app.processEvents()


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
    spin.setRange(0.1, 10.0)
    spin.setValue(0.5)

    spin.editingFinished.emit()

    assert spin.value() == 1.0
    assert "Cb" not in dict(window.model.bars["B1"].calculation_property_overrides)
    assert "Cb deve ser maior ou igual a 1,0" in window.verification_panel.status.text()
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


def test_l_panel_disables_lb_and_cb_when_flexion_model_does_not_use_them():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model("L Laminado"))
    panel = CalculationPropertiesPanel(window)
    panel.configure_for(("B1",))
    assert not panel._inputs["Lb"].isEnabled()
    assert not panel._inputs["Cb"].isEnabled()
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

    assert [panel._labels[name].text() for name, *_ in panel._FIELDS[:6]] == [
        "L<sub>y</sub>", "L<sub>z</sub>", "L<sub>t</sub>",
        "L<sub>b</sub>", "C<sub>t</sub>", "C<sub>b</sub>",
    ]
    assert all(widget.isHidden() for widget in panel.findChildren(QCheckBox))
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
    fields_grid = panel.layout().itemAt(1).widget().widget().layout()
    assert [fields_grid.getItemPosition(index)[:2] for index in range(6)] == [
        (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1),
    ]
    assert all(
        spin.mapTo(panel, spin.rect().bottomRight()).y() < panel.height()
        for name, spin in panel._inputs.items() if name in {"Ly", "Lz", "Lt", "Lb", "Ct", "Cb"}
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


def test_mrd_mode_absence_is_explicit_and_can_be_cleared():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model("C Formado"))
    panel = CalculationPropertiesPanel(window)
    window.refresh_selected_property_panel = lambda _section: panel.configure_for(("B1",))
    panel.configure_for(("B1",))
    button = panel._absent_buttons["NcrD"]
    assert not button.isChecked()
    assert panel._inputs["NcrD"].specialValueText() == "Automático"
    assert "NcrD" not in dict(window.model.bars["B1"].calculation_property_overrides)
    button.click()
    assert dict(window.model.bars["B1"].calculation_property_overrides)["NcrD"] == -1.
    assert panel._inputs["NcrD"].specialValueText() == "Ausente"
    assert not panel._inputs["NcrD"].isEnabled()
    button.click()
    assert "NcrD" not in dict(window.model.bars["B1"].calculation_property_overrides)
    assert panel._inputs["NcrD"].isEnabled()
    assert panel._inputs["NcrD"].specialValueText() == "Automático"
    panel.close()
    window.close()
    del app


def test_restoring_automatic_lengths_does_not_erase_required_connection_or_mrd_data():
    model = _model("C Formado")
    model.update_bar_material("B1", "ASTM A36", model.materials["ASTM A36"])
    model.update_member_profile("B1", "C de teste", {"d": 100., "bf": 50., "c": 15., "t": 2.})
    model.add_node("C", 0, 0, 3)
    model.add_bar("B2", "B", "C")
    model.update_bar_section("B2", "W Laminado")
    model.update_bar_material("B2", "ASTM A36", model.materials["ASTM A36"])
    model.update_member_profile("B2", "W de teste", {"d": 203., "bf": 102., "tw": 5.8, "tf": 6.5})
    required = {"Ct": .8, "An": 2., "An0": 2., "KL1": 2., "KL2": 1., "NcrG": 100., "NcrL": 50., "NcrD": 80.}
    for name, value in required.items():
        model.update_bar_calculation_property("B1", name, value)
    context = SimpleNamespace(model=model)
    assert not MainWindow._has_calculation_property_overrides(context)
    model.update_bar_calculation_property("B2", "Lb", 1.)
    assert MainWindow._has_calculation_property_overrides(context)
    MainWindow._reset_calculation_property_overrides(context)
    assert dict(model.bars["B1"].calculation_property_overrides) == required
    assert model.bars["B2"].calculation_property_overrides == ()


def test_effective_lengths_only_appear_for_cold_formed_and_have_no_automatic_default():
    app = QApplication.instance() or QApplication([])
    window = _PanelContext(_model("C Formado"))
    panel = CalculationPropertiesPanel(window)
    window.refresh_selected_property_panel = lambda _section: panel.configure_for(("B1",))
    panel.configure_for(("B1",))
    for name in ("KL1", "KL2"):
        assert panel._inputs[name].isEnabled()
        assert panel._inputs[name].value() == 0
        assert panel._inputs[name].specialValueText() == "Informar"
        assert "principal" in panel._labels[name].toolTip()
        assert not panel._inputs[name].parentWidget().parentWidget().isHidden()
    assert panel._inputs["Ly"].isEnabled()
    assert "tração" in panel._inputs["Ly"].toolTip()
    panel._inputs["KL1"].setValue(2.)
    panel._inputs["KL1"].editingFinished.emit()
    assert dict(window.model.bars["B1"].calculation_property_overrides)["KL1"] == 2.
    panel._reset_buttons["KL1"].click()
    assert "KL1" not in dict(window.model.bars["B1"].calculation_property_overrides)
    window.model.update_bar_section("B1", "W Laminado")
    window.model.update_member_profile("B1", "W de teste", {"d": 203., "bf": 102., "tw": 5.8, "tf": 6.5})
    panel.configure_for(("B1",))
    assert panel._inputs["KL1"].parentWidget().parentWidget().isHidden()
    panel.close()
    window.close()
    del app
