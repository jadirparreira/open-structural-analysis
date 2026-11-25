"""Visual component changes invalidate project views without structural edits."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from osa.domain.entities import NodeComponentAssignment
from osa.domain.node_components import node_component_geometry_signature
from osa.model import StructuralModel
from osa.ui.detailing_preview import DETAILING_LINEWORK_VERSION, DetailingViewPreview, _ViewGeometryCalculator
from osa.ui.detailing_viewport import _DetachedDetailingScene
from osa.ui.main_window import MainWindow


def test_switch_to_project_refreshes_stair_wood_changes_only(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        model = window.model
        model.add_node("N", 0, 0, 0)
        model.update_node_component("N", NodeComponentAssignment("stair_plate", ()))
        view = {"model_revision": model.revision, "linework_version": DETAILING_LINEWORK_VERSION,
                "component_geometry_signature": node_component_geometry_signature(model),
                "projection": {"plane": "XY", "coordinate": 0}, "segments": (((0, 0), (1, 0)),)}
        palette = window.project_sheets_palette
        sheet_name = palette.sheet_selector.currentText()
        palette._sheet_views[sheet_name] = [view]
        queued = []
        monkeypatch.setattr(window, "_queue_sheet_linework_upgrade", lambda jobs: queued.extend(jobs))
        monkeypatch.setattr(window, "_refresh_project_view_identifications", lambda _view: False)
        window.set_detailing_project_mode(True)
        assert queued == []
        # Sheet annotation changes must not force expensive geometry regeneration.
        model.view_revision += 1
        window.refresh_project_sheet_views()
        assert queued == []
        window.set_detailing_project_mode(False)
        revision = model.revision
        params = dict(model.nodes["N"].component.parameters)
        params["madeira_ativa"] = False
        model.update_node_component("N", NodeComponentAssignment("stair_plate", tuple(params.items())))
        assert model.revision == revision
        window.set_detailing_project_mode(True)
        assert len(queued) == 1
        assert queued[0][1] is view
    finally:
        window._saved_revision = window.model.revision
        window._saved_view_revision = window.model.view_revision
        window.scene.plotter.close()
        window.close()
        app.processEvents()


def test_projection_cache_removes_wood_without_structural_revision_change():
    model = StructuralModel()
    model.add_node("N", 0, 0, 0)
    model.update_node_component("N", NodeComponentAssignment("stair_plate", ()))
    calc = _ViewGeometryCalculator()
    calc._detail_scene = _DetachedDetailingScene(SimpleNamespace(_marker_radius_current=0.05))
    DetailingViewPreview.set_view(calc, model, "XY", 0, upper_offset_cm=100, lower_offset_cm=100)
    assert any("wood" in owner for owner in calc._segment_sources)
    revision = model.revision
    model.update_node_component("N", NodeComponentAssignment("stair_plate", (("madeira_ativa", False),)))
    assert model.revision == revision
    DetailingViewPreview.set_view(calc, model, "XY", 0, upper_offset_cm=100, lower_offset_cm=100)
    assert calc._segments_2d
    assert not any("wood" in owner for owner in calc._segment_sources)


def test_component_change_during_worker_requeues_instead_of_accepting_old_geometry():
    from unittest.mock import MagicMock

    model = StructuralModel()
    model.add_node("N", 0, 0, 0)
    model.update_node_component("N", NodeComponentAssignment("stair_plate", ()))
    original_signature = node_component_geometry_signature(model)
    projection = {"plane": "XY", "coordinate": 0}
    view = {"projection": projection, "segments": (((0, 0), (1, 0)),), "member_breaks": []}
    key = (id(view), model.revision, model.verification_group_revision, ())
    window = SimpleNamespace(
        model=model, _sheet_linework_pending={key},
        _sheet_linework_component_signatures={key: original_signature},
        project_sheet_workspace=MagicMock(), _sheet_views_updating_dialog=MagicMock(),
        project_sheets_palette=SimpleNamespace(_sheet_views={"Sheet": [view]}, sheet_selector=MagicMock()),
        _queue_sheet_linework_upgrade=MagicMock(), _store_detailing_state=MagicMock(),
    )
    model.update_node_component("N", NodeComponentAssignment("stair_plate", (("madeira_ativa", False),)))
    MainWindow._sheet_linework_upgraded(window, "Sheet", view, model.revision,
                                       model.verification_group_revision, projection, (), (), (), True)
    window._queue_sheet_linework_upgrade.assert_called_once()
    assert view["segments"] == (((0, 0), (1, 0)),)
    window._store_detailing_state.assert_not_called()


def test_refresh_preserves_component_detail_crop():
    from threading import Event

    from osa.ui.detailing_preview import _ModelSnapshot
    from osa.ui.project_sheet_refresh import SheetLineworkTask

    model = StructuralModel()
    model.add_node("N", 0, 0, 0)
    model.add_node("T", 0, 0, 2)
    model.add_bar("B", "N", "T")
    model.update_bar_section("B", "Tubular Quadrado")
    model.update_member_profile("B", "TQ100x3", {"b": 100.0, "t": 3.0})
    model.update_node_component("N", NodeComponentAssignment("base_plate", ()))
    projection = {"plane": "custom", "coordinate": ((0, 0, 0), (0, -1, 0), (0, 0, 1)),
                  "upper_offset_cm": 0, "lower_offset_cm": 0}
    view = {"component_detail_group": {"component_id": "base_plate", "members": ["N"], "direction": "Oeste"}}
    results = []
    source = _DetachedDetailingScene(SimpleNamespace(_marker_radius_current=0.05))
    task = SheetLineworkTask(SimpleNamespace(finished=SimpleNamespace(emit=lambda *args: results.append(args))),
                            _ModelSnapshot(model), source, model.revision, model.verification_group_revision,
                            [("Sheet", view, projection, True, ())], Event())
    task.run()
    assert len(results) == 1
    assert results[0][-1] is True
    segments, owners = results[0][-3:-1]
    assert "B" in owners
    bar_points = [point for segment, owner in zip(segments, owners) if owner == "B" for point in segment]
    assert max(p[1] for p in bar_points) <= 0.500001
