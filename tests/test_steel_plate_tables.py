"""Plate takeoff accuracy and integration with component inputs and sheet tables."""
import json
import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget

from osa.domain.entities import NodeComponentAssignment
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.services.steel_quantities import steel_plate_rows
from osa.ui.main_window import MainWindow
from osa.ui.node_components_dialog import NodeComponentsDialog
from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.sheet_tables import InsertSheetTableDialog, SteelPlatesTableLayout, SteelProfilesTableLayout


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def rectangle(width=.3, length=.2):
    return ((0, 0, 0), (width, 0, 0), (width, length, 0), (0, length, 0))


def test_combines_model_plates_and_both_components_without_fasteners_or_wood():
    model = StructuralModel()
    model.add_plate(rectangle(), thickness_mm=6.35, material="ASTM A36")
    model.add_plate(rectangle(), thickness_mm=6.35, material="Concreto C30")
    for name, x, component, width, length in (("N1", 1, "base_plate", 200, 300),
                                              ("N2", 2, "stair_plate", 300, 100)):
        model.add_node(name, x, 0, 0)
        model.update_node_component(name, NodeComponentAssignment(component, (
            ("largura_mm", width), ("comprimento_mm", length), ("espessura_mm", 6.35),
            ("madeira_ativa", False), ("material_fixador", "SAE 1020"),
        )))
    rows = steel_plate_rows(model)
    assert len(rows) == 1
    row = rows[0]
    assert row["plate"] == "CH 300 x 6.35"
    assert row["material"] == "ASTM A36"
    assert row["length"] == pytest.approx(.5)
    assert row["linear_mass"] == pytest.approx(.3 * .00635 * 7850)
    assert row["total_mass"] == pytest.approx(.3 * .00635 * 7850 * .5)


@pytest.mark.parametrize("angle", (0, 23, 90))
def test_rotated_and_translated_plate_uses_own_dimensions(angle):
    theta = math.radians(angle)
    # A rectangle lying in a vertical, rotated plane, away from the origin.
    u = np.array((math.cos(theta), math.sin(theta), 0))
    v = np.array((0, 0, 1))
    origin = np.array((13, -17, 4))
    points = [tuple(origin + x * u + y * v) for x, y, _ in rectangle()]
    model = StructuralModel()
    model.add_plate(points, thickness_mm=6.35, material="ASTM A36")
    row = steel_plate_rows(model)[0]
    assert row["plate"] == "CH 300 x 6.35"
    assert row["length"] == pytest.approx(.2)
    assert row["total_mass"] == pytest.approx(.3 * .2 * .00635 * 7850)


def test_nonrectangular_plate_weight_uses_actual_area():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (.3, 0, 0), (.3, .2, 0), (.1, .2, 0), (.1, .1, 0), (0, .1, 0)),
                    thickness_mm=10, material="ASTM A36")
    row = steel_plate_rows(model)[0]
    assert row["plate"] == "CH 300 x 10"
    assert row["total_mass"] == pytest.approx(.05 * .01 * 7850)
    assert row["linear_mass"] * row["length"] == pytest.approx(row["total_mass"])


def test_groups_materials_separately_and_uses_their_density():
    model = StructuralModel()
    model.materials["Aço especial"] = (200e6, 77e6, .3, 6000 * .00980665)
    model.material_types["Aço especial"] = "Aço"
    model.add_plate(rectangle(), thickness_mm=6.35, material="ASTM A36")
    model.add_plate(rectangle(), thickness_mm=6.35, material="Aço especial")
    rows = {row["material"]: row for row in steel_plate_rows(model)}
    assert len(rows) == 2
    assert rows["Aço especial"]["total_mass"] == pytest.approx(.3 * .2 * .00635 * 6000)


def test_component_material_and_dimensions_invalidate_live_table_cache():
    model = StructuralModel()
    model.add_node("N", 0, 0, 0)
    model.update_node_component("N", NodeComponentAssignment("stair_plate", ()))
    window = SimpleNamespace(model=model)
    original = MainWindow._steel_plate_table_rows(window)
    revision = model.revision
    model.update_node_component("N", NodeComponentAssignment("stair_plate", (
        ("material_chapa", "SAE 1020"), ("comprimento_mm", 500),
    )))
    updated = MainWindow._steel_plate_table_rows(window)
    assert model.revision == revision
    assert updated != original
    assert updated[0]["material"] == "SAE 1020"
    assert updated[0]["plate"] == "CH 500 x 6.3"


def test_component_material_controls_and_wheel_does_not_change_values(app):
    window = QWidget()
    window.model = StructuralModel()
    window.model.add_node("N", 0, 0, 0)
    dialog = NodeComponentsDialog(window, "N")
    try:
        dialog.component_list.setCurrentRow(1)
        field = dialog._inputs["material_fixador"]
        assert field.currentText() == "SAE 1020"

        def group(field):
            while field.parentWidget() is not dialog.parameters_widget:
                field = field.parentWidget()
            return field

        grid = dialog.parameters_layout
        border_row = grid.getItemPosition(grid.indexOf(group(dialog._inputs["distancia_a_mm"])))
        material_row = grid.getItemPosition(grid.indexOf(group(field)))
        assert border_row[0] == material_row[0]
        assert border_row[1] == 0 and material_row[1] == 1
        for key, control in dialog._inputs.items():
            if key == "identificacao_fixador":
                continue
            original = control.currentText() if hasattr(control, "currentText") else control.value()
            wheel = QWheelEvent(QPointF(4, 4), QPointF(4, 4), QPoint(), QPoint(0, 120),
                                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(control, wheel)
            current = control.currentText() if hasattr(control, "currentText") else control.value()
            assert current == original, key
        dialog._inputs["espessura_mm"].setValue(6.35)
        assert dialog._inputs["espessura_mm"].value() == 6.35
        dialog._inputs["material_fixador"].setCurrentText("ASTM A36")
        window.model.update_node_component("N", NodeComponentAssignment("base_plate", tuple(dialog._draft_parameters.items())))
        serializer = ProjectSerializer()
        restored = StructuralModel()
        serializer.load_into(restored, json.loads(json.dumps(serializer.dump(window.model))))
        assert dict(restored.nodes["N"].component.parameters)["material_fixador"] == "ASTM A36"
        dialog.component_list.setCurrentRow(2)
        assert dialog.details_title.text() == "Chapa de degrau"
        assert "material_chapa" in dialog._inputs
        dialog._inputs["material_chapa"].setCurrentText("SAE 1020")
        window.model.update_node_component("N", NodeComponentAssignment("stair_plate", tuple(dialog._draft_parameters.items())))
        serializer = ProjectSerializer()
        restored = StructuralModel()
        serializer.load_into(restored, json.loads(json.dumps(serializer.dump(window.model))))
        assert dict(restored.nodes["N"].component.parameters)["material_chapa"] == "SAE 1020"
    finally:
        dialog.reject()
        window.close()


def test_table_layout_insertion_and_snapping_to_other_tables(app):
    model = StructuralModel()
    model.add_plate(rectangle(), thickness_mm=6.35, material="ASTM A36")
    rows = steel_plate_rows(model)
    layout = SteelPlatesTableLayout(rows, 175, QFont())
    profiles = SteelProfilesTableLayout([], 175, QFont())
    assert layout.width_mm == profiles.width_mm
    assert layout._widths == profiles._widths
    assert layout._rows[0][1][0].toPlainText() == "CHAPA"
    assert layout._footer_total.toPlainText() == "2,99"
    workspace = ProjectSheetWorkspace()
    workspace.resize(1100, 800)
    workspace.steel_plate_rows_provider = lambda: rows
    workspace._settings["tables"] = [{"kind": "steel_plates", "position": (.05, .05)},
                                     {"kind": "steel_profiles", "position": (.55, .4)}]
    try:
        image = QImage(workspace.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        workspace.render(painter, QPoint())
        painter.end()
        assert len(workspace._sheet_table_hit_rects) == 2
        first, second = (workspace._sheet_table_hit_rects[i] for i in (0, 1))
        assert first.width() == pytest.approx(second.width())
        workspace._drag_sheet_table = 0
        segments = workspace._table_snap_segments()
        shifted = QRectF(second).translated(4, 3)
        snapped = workspace._snap_table_bounds(shifted, segments)
        assert snapped.left() == pytest.approx(second.left())
        assert snapped.top() == pytest.approx(second.top())
        dialog = InsertSheetTableDialog(None, ["Sheet"], "Sheet", {"Sheet": {}}, {}, [], rows)
        index = next(i for i in range(dialog.types.count()) if dialog.types.item(i).data(Qt.UserRole) == "steel_plates")
        dialog.types.setCurrentRow(index)
        assert isinstance(dialog.preview.layout_data, SteelPlatesTableLayout)
        dialog._insert()
        assert dialog.result_table == ("Sheet", "steel_plates")
    finally:
        workspace.close()
