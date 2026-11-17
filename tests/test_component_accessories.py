"""Accessory names/counts, existing identity compatibility and sheet integration."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from osa.domain.entities import NodeComponentAssignment
from osa.domain.node_components import base_plate_anchor_offsets
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.services.component_accessories import component_accessory_rows
from osa.ui.main_window import MainWindow
from osa.ui.node_components_dialog import NodeComponentsDialog
from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.sheet_tables import AccessoriesTableLayout, InsertSheetTableDialog, SteelPlatesTableLayout


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def add_component(model, name, parameters=(), kind="base_plate"):
    model.add_node(name, len(model.nodes), 0, 0)
    return model.update_node_component(name, NodeComponentAssignment(kind, tuple(dict(parameters).items())))


def names_and_counts(model):
    return {row["name"]: row["quantity"] for row in component_accessory_rows(model)}


def test_straight_name_matches_dimensions_material_and_nominal_diameters():
    model = StructuralModel()
    add_component(model, "N", {"diametro_mm": 12.5, "comprimento_fixador_mm": 160, "embutimento_mm": 100})
    assert names_and_counts(model) == {
        "Barra Redonda Ø 12.5 x 160 SAE1020": 4,
        "Porca Sextavada Ø 12,5": 4,
        "Arruela Lisa Ø 12,5": 4,
    }


def test_hook_name_uses_both_segments_and_material():
    model = StructuralModel()
    add_component(model, "N", {"fixador": "Gancho", "diametro_mm": 10, "comprimento_fixador_mm": 400,
                               "perna_mm": 200, "material_fixador": "ASTM A36"})
    assert names_and_counts(model) == {
        "Barra Redonda Ø 10.0 x 400 x 200 ASTM A36": 4,
        "Porca Sextavada Ø 10,0": 4,
        "Arruela Lisa Ø 10,0": 4,
    }


@pytest.mark.parametrize(("count_a", "count_b"), ((2, 2), (2, 3), (4, 6)))
def test_quantity_counts_perimeter_without_repeating_corners(count_a, count_b):
    model = StructuralModel()
    node = add_component(model, "N", {"fixadores_lado_a": count_a, "fixadores_lado_b": count_b})
    expected = len(base_plate_anchor_offsets(dict(node.component.parameters)))
    assert expected == 2 * (count_a + count_b) - 4
    assert all(row["quantity"] == expected for row in component_accessory_rows(model))


def test_custom_identity_overrides_auto_name_and_combines_matching_names():
    model = StructuralModel()
    add_component(model, "N1", {"identificacao_fixador": "F-01"})
    add_component(model, "N2", {"identificacao_fixador": " F-01 ", "fixador": "Gancho", "fixadores_lado_a": 3})
    add_component(model, "N3", kind="stair_plate")
    rows = names_and_counts(model)
    assert rows == {"F-01": 10, "Porca Sextavada Ø 16,0": 10, "Arruela Lisa Ø 16,0": 10}
    serializer = ProjectSerializer()
    restored = StructuralModel()
    serializer.load_into(restored, json.loads(json.dumps(serializer.dump(model))))
    assert names_and_counts(restored) == rows


def test_automatic_descriptions_keep_different_lengths_legs_and_materials_separate():
    model = StructuralModel()
    add_component(model, "N1")
    add_component(model, "N2", {"comprimento_fixador_mm": 400})
    add_component(model, "N3", {"material_fixador": "ASTM A36"})
    add_component(model, "N4", {"fixador": "Gancho", "perna_mm": 100})
    add_component(model, "N5", {"fixador": "Gancho", "perna_mm": 200})
    rows = names_and_counts(model)
    assert len(rows) == 7
    assert rows["Porca Sextavada Ø 16,0"] == 20
    assert rows["Arruela Lisa Ø 16,0"] == 20
    assert all(quantity == 4 for name, quantity in rows.items() if name.startswith("Barra Redonda"))


def test_blank_identity_and_legacy_component_defaults():
    model = StructuralModel()
    model.add_node("N", 0, 0, 0)
    # Legacy stored assignment with no newly introduced identity/material fields.
    from dataclasses import replace

    model.nodes["N"] = replace(model.nodes["N"], component=NodeComponentAssignment("base_plate"))
    expected = names_and_counts(model)
    assert expected["Barra Redonda Ø 16.0 x 300 SAE1020"] == 4
    add_component(model, "N2", {"identificacao_fixador": "   "})
    assert names_and_counts(model)["Barra Redonda Ø 16.0 x 300 SAE1020"] == 8


def test_live_table_cache_updates_when_identity_or_quantity_changes():
    model = StructuralModel()
    add_component(model, "N")
    window = SimpleNamespace(model=model)
    original = MainWindow._accessory_table_rows(window)
    revision = model.revision
    model.update_node_component("N", NodeComponentAssignment("base_plate", (
        ("identificacao_fixador", "F-02"), ("fixadores_lado_a", 3),
    )))
    assert model.revision == revision
    updated = MainWindow._accessory_table_rows(window)
    assert original != updated
    assert {row["name"]: row["quantity"] for row in updated}["F-02"] == 6


def test_identity_field_label_keeps_existing_saved_text(app):
    window = QWidget()
    window.model = StructuralModel()
    add_component(window.model, "N", {"identificacao_fixador": "F-01"})
    dialog = NodeComponentsDialog(window, "N")
    try:
        field = dialog._inputs["identificacao_fixador"]
        assert field.accessibleName() == "Identidade do fixador"
        assert field.text() == "F-01"
    finally:
        dialog.reject()
        window.close()


def test_table_has_only_name_and_quantity_and_supports_insertion_and_snap(app):
    model = StructuralModel()
    add_component(model, "N")
    rows = component_accessory_rows(model)
    layout = AccessoriesTableLayout(rows, 175, QFont())
    assert [doc.toPlainText() for doc in layout._rows[0][1]] == ["NOME", "QUANTIDADE"]
    assert len(layout._rows) == 1 + len(rows)
    assert not hasattr(layout, "_footer_total")
    assert layout.width_mm == SteelPlatesTableLayout([], 175, QFont()).width_mm
    dialog = InsertSheetTableDialog(None, ["Sheet"], "Sheet", {"Sheet": {}}, {}, accessory_rows=rows)
    index = next(i for i in range(dialog.types.count()) if dialog.types.item(i).data(Qt.UserRole) == "accessories")
    dialog.types.setCurrentRow(index)
    assert isinstance(dialog.preview.layout_data, AccessoriesTableLayout)
    dialog._insert()
    assert dialog.result_table == ("Sheet", "accessories")
    sheet = ProjectSheetWorkspace()
    sheet.resize(1100, 800)
    sheet.accessory_rows_provider = lambda: rows
    sheet._settings["tables"] = [{"kind": "accessories", "position": (.05, .05)},
                                {"kind": "steel_plates", "position": (.55, .4)}]
    try:
        image = QImage(sheet.size(), QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        sheet.render(painter, QPoint())
        painter.end()
        assert len(sheet._sheet_table_hit_rects) == 2
        first, second = (sheet._sheet_table_hit_rects[i] for i in (0, 1))
        assert first.width() == pytest.approx(second.width())
        sheet._drag_sheet_table = 0
        snapped = sheet._snap_table_bounds(QRectF(second).translated(3, 4), sheet._table_snap_segments())
        assert snapped.left() == pytest.approx(second.left())
        assert snapped.top() == pytest.approx(second.top())
    finally:
        sheet.close()
