"""Stair components in the project-sheet detail selection workflow."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QWidget

from osa.domain.entities import NodeComponentAssignment
from osa.model import StructuralModel
from osa.services.base_plate_details import component_identifier
from osa.ui.dialogs import ComponentDetailsDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def stair_model(**parameters):
    model = StructuralModel()
    model.add_node("N", 1, 2, 3)
    model.update_node_component("N", NodeComponentAssignment("stair_plate", tuple(parameters.items())))
    return model


@pytest.mark.parametrize("wood", [True, False])
def test_six_views_use_stair_geometry_and_actual_thickness(wood):
    model = stair_model(madeira_ativa=wood, rotacao_deg=37, espessura_mm=6.3)
    views = ComponentDetailsDialog._build_group_views(model, .05, {
        "component_id": "stair_plate", "nodes": ["N"],
        "parameters": dict(model.nodes["N"].component.parameters),
    })
    assert set(views) == {"top", "bottom", "east", "west", "north", "south"}
    for direction, view in views.items():
        assert view["segments"]
        assert len(view["segments"]) == len(view["segment_owners"])
        assert len(view["dimensions"]) == (4 if wood else 2)
        dimensions = view["dimensions"]
        lengths = [sum((a-b)**2 for a, b in zip(d["start"], d["end"]))**.5 * 1000
                   for d in dimensions]
        assert lengths[:2] == pytest.approx([200, 300] if direction in {"top", "bottom"}
                                           else [300 if direction in {"east", "west"} else 200, 6.3], abs=1e-3)
    assert component_identifier(model, "component_plate", "N") == ("CH 6,3", 0)


def test_dialog_groups_stairs_and_reopens_saved_views(app, monkeypatch):
    # Run preview generation synchronously to exercise the complete dialog workflow.
    monkeypatch.setattr(QThreadPool, "start", lambda self, worker: worker.run())
    model = stair_model()
    model.add_node("N2", 0, 0, 0)
    model.update_node_component("N2", model.nodes["N"].component)
    model.add_node("BASE", 0, 0, 1)
    model.update_node_component("BASE", NodeComponentAssignment("base_plate"))
    parent = QWidget()
    parent.model = model
    parent.scene = SimpleNamespace(_marker_radius_current=.05)
    dialog = ComponentDetailsDialog(parent)
    assert len(dialog._groups) == 2
    key = next(k for k, g in dialog._groups.items() if g["component_id"] == "stair_plate")
    dialog._select_group(key)
    assert dialog._groups[key]["nodes"] == ["N", "N2"]
    assert dialog._groups[key]["component_label"] == "Chapa de degrau · 2 nós"
    dialog._cards["superior"][0].setChecked(True)
    dialog._cards["oeste"][0].setChecked(True)
    dialog._rotate_preview("top")
    dialog._accept_selected_views()
    views = dialog.result_views
    assert len(views) == 2
    assert all(v["detail_view_key"].startswith("component:stair_plate:") for v in views)
    assert all("paper_offset_mm" in v["component_detail_group"] for v in views)
    assert all(not v.get("weld_marks") for v in views)
    group_id = views[0]["component_detail_group"]["id"]
    editing = ComponentDetailsDialog(parent, editing_group_id=group_id, existing_views=views)
    assert len(editing._groups) == 1
    assert editing._cards["superior"][0].isChecked()
    assert editing._cards["oeste"][0].isChecked()
    editing._cards["inferior"][0].setChecked(True)
    editing._accept_selected_views()
    assert len(editing.result_views) == 3
    assert editing.result_views[0]["component_detail_group"]["preview_rotation_degrees"] == 90
    assert all(v["component_detail_group"]["component_id"] == "stair_plate" for v in editing.result_views)
    editing.close()
    dialog.close()
    parent.close()


@pytest.mark.parametrize("rotation", [0, 90])
def test_worker_hide_wood_reveals_plate_and_preserves_detail_frame(rotation):
    from threading import Event

    from osa.ui.detailing_preview import _ModelSnapshot
    from osa.ui.detailing_viewport import _DetachedDetailingScene
    from osa.ui.project_sheet_refresh import SheetLineworkTask

    model = stair_model(rotacao_deg=37)
    # Unrelated distant geometry must never enter this component detail.
    model.add_node("OTHER", 10, 10, 10)
    model.update_node_component("OTHER", NodeComponentAssignment("stair_plate"))
    group = {"component_id": "stair_plate", "nodes": ["N"],
             "parameters": dict(model.nodes["N"].component.parameters)}
    generated = ComponentDetailsDialog._build_group_views(model, .05, group)
    data = ComponentDetailsDialog._rotate_component_view_data(generated["top"], rotation)
    assert "componente:chapa_degrau:0" not in data["segment_owners"]
    view = {"segments": data["segments"], "component_detail_group": {
        "component_id": "stair_plate", "members": ["N"], "direction": "Superior",
        "preview_rotation_degrees": rotation,
    }}
    projection = {"plane": "custom", "coordinate": data["coordinate"],
                  "upper_offset_cm": 0, "lower_offset_cm": 0}
    source = _DetachedDetailingScene(SimpleNamespace(_marker_radius_current=.05))

    def refresh(hidden):
        results = []
        task = SheetLineworkTask(
            SimpleNamespace(finished=SimpleNamespace(emit=lambda *args: results.append(args))),
            _ModelSnapshot(model), source, model.revision, model.verification_group_revision,
            [("Sheet", view, projection, True, hidden)], Event(),
        )
        task.run()
        assert len(results) == 1
        assert results[0][-1] is True
        return results[0][-3:-1]

    segments, owners = refresh(("componente:chapa_degrau:1",))
    assert len(segments) == 4
    assert set(owners) == {"componente:chapa_degrau:0"}
    # Expected plate rectangle, in the original detail's local coordinates.
    points = {tuple(round(v, 5) for v in p) for line in segments for p in line}
    xs, ys = ((.15, .1) if rotation else (.1, .15))
    assert points == {(x, y) for x in (-xs, xs) for y in (-ys, ys)}
    restored_segments, restored_owners = refresh(())
    assert restored_segments == tuple(data["segments"])
    assert restored_owners == tuple(data["segment_owners"])
    assert refresh(("componente:chapa_degrau:0", "componente:chapa_degrau:1")) == ((), ())


def test_generated_dimensions_can_be_selected_and_deleted_in_sheet(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from osa.ui.project_sheet import ProjectSheetWorkspace

    model = stair_model()
    generated = ComponentDetailsDialog._build_group_views(model, .05, {
        "component_id": "stair_plate", "nodes": ["N"],
        "parameters": dict(model.nodes["N"].component.parameters),
    })
    data = generated["west"]
    view = {"name": "Degrau - Oeste", "segments": data["segments"],
            "segment_owners": data["segment_owners"], "dimensions": data["dimensions"],
            "scale_denominator": 10., "projection": {"plane": "custom", "coordinate": data["coordinate"]},
            "component_detail_group": {"id": "stair", "component_id": "stair_plate", "members": ["N"],
                                       "direction": "Oeste", "group_position": (.5, .5)}}
    assert isinstance(view["dimensions"], tuple)
    sheet = ProjectSheetWorkspace()
    sheet.resize(1400, 1000)
    sheet.set_sheet_views([view])
    sheet.show()
    app.processEvents()
    sheet.select_view(0)
    sheet.grab()
    original_dimensions = list(view["dimensions"])
    changed = []
    sheet.layout_changed.connect(lambda: changed.append(True))
    try:
        center = sheet._dimension_text_hit_rects[(0, 0)].center().toPoint()
        QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=center)
        assert sheet._selected_dimension == (0, 0)
        QTest.keyClick(sheet, Qt.Key.Key_Delete)
        assert view["dimensions"] == original_dimensions[1:]
        assert sheet._selected_dimension is None
        assert changed
        # Reloading the same detail must preserve the deletion and allow edits.
        sheet.set_sheet_views([view])
        assert view["dimensions"] == original_dimensions[1:]
        view["dimensions"].append(original_dimensions[0])
        assert len(view["dimensions"]) == len(original_dimensions)
    finally:
        sheet.close()
        app.processEvents()
