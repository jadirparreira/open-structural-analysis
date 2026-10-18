import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from struct import pack

import ezdxf
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMessageBox, QPushButton, QToolButton

from osa.domain.drawing_reference import DrawingReference, ReferenceGeometry
from osa.importers import dwg_converter
from osa.ui import home
from osa.ui.main_window import MainWindow


@pytest.mark.parametrize("extension", ["dxf", "dwg"])
def test_import_configure_save_and_reset_reference(monkeypatch, tmp_path, extension):
    class Store:
        def items(self):
            return []

        def add(self, path):
            pass

    monkeypatch.setattr(home, "RecentProjectStore", Store)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.show_editor()
    try:
        document = ezdxf.new()
        document.units = 6
        document.modelspace().add_line((0, 0), (10, 10))
        filename = tmp_path / f"planta.{extension}"
        if extension == "dwg":
            filename.write_bytes(b"AC1032-test")
            monkeypatch.setattr(dwg_converter, "converter_path", lambda: tmp_path / "dwg2dxf")

            def convert(args, **kwargs):
                if not filename.read_bytes().startswith(b"AC1032"):
                    return SimpleNamespace(returncode=1)
                document.saveas(args[args.index("-o") + 1])
                return SimpleNamespace(returncode=0)

            monkeypatch.setattr(dwg_converter.subprocess, "run", convert)
        else:
            document.saveas(filename)
        filters = []

        def select_file(*args):
            filters.append(args[-1])
            return str(filename), ""

        monkeypatch.setattr(QFileDialog, "getOpenFileName", select_file)
        warnings = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
        window.import_reference()
        app.processEvents()
        assert not warnings
        assert "*.dwg" in filters[0] and "*.dxf" in filters[0]
        assert len(window.model.references) == 1
        panel = window.reference_panel
        assert panel.isVisible()
        reference_id = next(iter(window.model.references))
        actor = window.scene._drawing_reference_renderer.actors[reference_id]
        camera = window.scene._camera_state()
        panel.coordinates[0].setValue(12.5)
        panel.coordinates[2].setValue(-4)
        panel.plane.setCurrentText("XZ")
        panel.list.itemWidget(panel.list.item(0)).checkbox.setChecked(False)
        reference = window.model.references[reference_id]
        assert reference.origin == (12.5, 0, -4)
        assert reference.plane == "XZ"
        assert not actor.GetVisibility()
        assert window.scene._drawing_reference_renderer.actors[reference_id] is actor
        assert window.scene._camera_state() == camera
        assert window._has_unsaved_changes()
        panel.list.itemWidget(panel.list.item(0)).checkbox.setChecked(True)
        assert actor.GetVisibility()

        # Failure leaves the existing reference and its placement intact.
        filename.write_text("not a valid DXF")
        window.import_reference()
        assert warnings
        assert len(window.model.references) == 1
        assert window.model.references[reference_id].origin == (12.5, 0, -4)

        output = tmp_path / "project.osa"
        window._save_model_to(output)
        assert not window._has_unsaved_changes()
        window.toggle_axes_panel()
        assert not panel.isVisible()
        window.toggle_reference_panel()
        assert not window.axes_panel.isVisible()
        assert panel.isVisible()
        panel._remove()
        assert not window.model.references
        assert not window.scene._drawing_reference_renderer.actors
        assert not panel.form.isEnabled()
        window._reset_model_state()
        assert not panel.isVisible()
    finally:
        window._saved_revision = window.model.revision
        window._saved_view_revision = window.model.view_revision
        window.close()


@pytest.fixture
def reference_window(monkeypatch):
    class Store:
        def items(self):
            return []

        def add(self, path):
            pass

    monkeypatch.setattr(home, "RecentProjectStore", Store)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.show_editor()
    geometry = ReferenceGeometry(pack("<dddd", 0, 0, 1, 1))
    for reference_id in ("first", "second"):
        window.model.add_reference(DrawingReference(reference_id, f"{reference_id}.dxf", geometry))
    window.scene.refresh_drawing_references(window.model)
    yield app, window
    window._saved_revision = window.model.revision
    window._saved_view_revision = window.model.view_revision
    window.close()


def test_reference_panel_dismissal_and_palette_states(reference_window):
    app, window = reference_window
    panel = window.reference_panel
    button = window.top_icon_palette.configure_reference_button
    axes = window.top_icon_palette.configure_axes_button
    assert button.isCheckable() and axes.isCheckable()
    assert not button.isChecked() and not axes.isChecked()

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert panel.isVisible() and button.isChecked()
    QTest.mouseClick(panel.coordinates[0], Qt.MouseButton.LeftButton)
    assert panel.isVisible() and button.isChecked()

    # A combo's popup extends outside the panel and must not dismiss it.
    panel.plane.showPopup()
    app.processEvents()
    view = panel.plane.view()
    index = panel.plane.model().index(1, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center())
    assert panel.isVisible() and panel.plane.currentText() == "XZ"

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert not panel.isVisible() and not button.isChecked()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.command_bar.input, Qt.MouseButton.LeftButton)
    assert not panel.isVisible() and not button.isChecked()

    axes.click()
    assert axes.isChecked() and window.axes_panel.isVisible()
    button.click()
    assert not axes.isChecked() and not window.axes_panel.isVisible()
    assert button.isChecked() and panel.isVisible()
    panel.hide()
    assert not button.isChecked()
    axes.click()
    window.axes_panel.discard()
    assert not axes.isChecked()


def test_reference_row_checkbox_hover_remove_and_parameter_layout(reference_window):
    _app, window = reference_window
    window.toggle_reference_panel()
    panel = window.reference_panel
    assert panel.width() == window.properties.width() == 300
    assert not panel.findChildren(QPushButton)
    assert all(button.accessibleName().startswith("Remover referência") for button in panel.findChildren(QToolButton))
    assert "Parâmetros" in [label.text() for label in panel.findChildren(QLabel)]
    form = panel.form.layout()
    assert form.labelForField(panel.plane).text() == "Plano"
    for axis, field in zip("XYZ", panel.coordinates):
        assert form.labelForField(field.parentWidget()).text() == axis
        assert [label.text() for label in field.parentWidget().findChildren(QLabel)] == ["m"]

    row = panel.list.itemWidget(panel.list.item(1))
    assert not row.remove_button.isVisible()
    QApplication.sendEvent(row, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert row.remove_button.isVisible()
    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    assert not row.remove_button.isVisible()
    QTest.mouseClick(row.checkbox, Qt.MouseButton.LeftButton)
    assert not window.model.references["second"].visible
    assert panel.list.currentRow() == 1
    # Remove a different row than the selected one.
    panel.list.setCurrentRow(0)
    QApplication.sendEvent(row, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    QTest.mouseClick(row.remove_button, Qt.MouseButton.LeftButton)
    assert set(window.model.references) == {"first"}
    assert panel.isVisible()


def test_axes_command_controls_visibility_and_configaxes_opens_editor(reference_window):
    _app, window = reference_window
    button = window.top_icon_palette._visibility_buttons["reference-axes"]
    assert button.accessibleName() == "Eixos"
    assert "AXES" in button.toolTip() and "REFERENCEAXES" not in button.toolTip()
    assert window._handle_interface_command("AXES")
    assert not window.scene._reference_axes_visible
    assert not button.isChecked()
    assert not window.axes_panel.isVisible()
    assert window._handle_interface_command("AXES")
    assert window.scene._reference_axes_visible
    assert window._handle_interface_command("CONFIGAXES")
    assert window.axes_panel.isVisible()
    assert window.top_icon_palette.configure_axes_button.isChecked()
    assert not window._handle_interface_command("REFERENCEAXES")


def test_reference_selection_highlight_and_origin_follow_inspector(reference_window):
    _app, window = reference_window
    scene = window.scene
    renderer = scene._drawing_reference_renderer
    window.toggle_reference_panel()
    panel = window.reference_panel
    assert renderer.selected_id == "first"
    first_width = renderer.actors["first"].GetProperty().GetLineWidth()
    assert first_width > renderer.actors["second"].GetProperty().GetLineWidth()
    assert renderer.origin_actor.GetVisibility()
    panel.list.setCurrentRow(1)
    assert renderer.selected_id == "second"
    assert renderer.actors["second"].GetProperty().GetLineWidth() == first_width
    assert renderer.actors["first"].GetProperty().GetLineWidth() == 1
    panel.coordinates[0].setValue(3)
    panel.coordinates[1].setValue(4)
    panel.coordinates[2].setValue(5)
    panel.plane.setCurrentText("YZ")
    assert renderer.origin_actor.GetPosition() == (3, 4, 5)
    assert not renderer.origin_actor.GetPickable()
    assert not window.model.nodes and not window.model.bars
    panel.hide()
    assert renderer.selected_id is None
    assert not renderer.origin_actor.GetVisibility()
    assert all(actor.GetProperty().GetLineWidth() == 1 for actor in renderer.actors.values())
    window.toggle_reference_panel()
    assert renderer.selected_id == "second"
    panel._remove()
    assert renderer.selected_id == "first"
