import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyvista as pv
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.rendering.batched_renderer import BatchedMemberRenderer
from osa.ui.detailing_preview import DetailingViewPreview
from osa.ui.detailing_viewport import (
    DetailingViewViewport,
    _DetachedDetailingScene,
    _ViewportGeometryBuilder,
)


def _model():
    model = StructuralModel()
    for index in range(4):
        model.add_node(f"N{index}", index * 2, index % 2, index * .25)
    for index in range(3):
        name = f"B{index}"
        model.add_bar(name, f"N{index}", f"N{index + 1}")
        model.update_bar_section(name, "Barra Retangular")
        model.update_member_profile(name, name, {"b": 100, "h": 200})
        model.update_member_rotation(name, index * 15)
    return model


def test_detached_member_solids_match_original_vtk_extraction():
    model = _model()
    batch = BatchedMemberRenderer().build(model, 0.05)
    source = _DetachedDetailingScene(SimpleNamespace())
    solids = dict(source.detailing_view_solid_meshes(model))
    assert solids.keys() == batch.face_cell_ranges.keys()
    for name, (start, end) in batch.face_cell_ranges.items():
        old = batch.faces.extract_cells(np.arange(start, end)).extract_surface(
            algorithm="dataset_surface"
        ).triangulate().clean()
        new = solids[name]
        assert new.n_cells == old.n_cells
        assert new.n_points == old.n_points
        np.testing.assert_allclose(new.bounds, old.bounds)
        np.testing.assert_allclose(new.area, old.area)
        np.testing.assert_allclose(new.volume, old.volume)


def test_depth_clip_fast_paths_preserve_bounds_and_intersections():
    mesh = pv.Cube().triangulate()
    clip = DetailingViewPreview._clip_to_depth_range
    assert clip(mesh, (0, 0, 1), 2, -1, 1) is mesh
    assert clip(mesh, (0, 0, 1), 2, 2, 3) is None
    crossing = clip(mesh, (0, 0, 1), 2, -.25, .25)
    assert crossing is not None
    np.testing.assert_allclose(crossing.bounds[4:], (-.25, .25))


def test_viewport_returns_immediately_and_discards_stale_previews(monkeypatch):
    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    calls, displayed = [], []

    def build(_self, _model, plane, _coordinate, _settings):
        calls.append(plane)
        if plane == "XY":
            entered.set()
            assert release.wait(5)
        return object(), object()

    monkeypatch.setattr(_ViewportGeometryBuilder, "_build_scene_meshes", build)
    widget = DetailingViewViewport()
    monkeypatch.setattr(widget, "_clear_view", lambda: None)
    monkeypatch.setattr(widget, "_show_scene", lambda _a, _b, plane, _c, _s: displayed.append(plane))
    model = _model()
    try:
        widget.request_view(model, "XY", 0.0)
        assert widget._render_pending
        assert entered.wait(5)
        widget.request_view(model, "XZ", 0.0)
        release.set()
        for _ in range(500):
            app.processEvents()
            if not widget._render_pending:
                break
            QTest.qWait(5)
        assert calls == ["XY", "XZ"]
        assert displayed == ["XZ"]
        assert not widget._render_pending
    finally:
        release.set()
        widget.shutdown()
        widget.close()


def test_detached_scene_preserves_plate_positioning_and_subtractions():
    from osa.rendering.scene_batched import StructureScene
    from osa.ui.detailing_preview import _ModelSnapshot

    app = QApplication.instance() or QApplication([])
    model = _model()
    model.add_plate(((-1, -1, 0), (3, -1, 0), (3, 2, 0), (-1, 2, 0)),
                    name="P1", positioning_displacement=0.02)
    model.add_detail_subtraction("plate", "P1", "bar", "B0")
    scene = StructureScene()
    scene._detail_subtraction_meshes = {}
    scene._detail_subtraction_failures = set()
    try:
        expected = dict(scene.detailing_view_solid_meshes(model))
        detached = _DetachedDetailingScene(scene)
        actual = dict(detached.detailing_view_solid_meshes(_ModelSnapshot(model)))
        assert actual.keys() == expected.keys()
        for name, reference in expected.items():
            np.testing.assert_allclose(actual[name].bounds, reference.bounds)
            np.testing.assert_allclose(actual[name].volume, reference.volume)
            assert actual[name].n_cells == reference.n_cells
    finally:
        scene.close()
        app.processEvents()


def test_closing_viewport_while_preparing_does_not_apply_result(monkeypatch):
    app = QApplication.instance() or QApplication([])
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    shown = []

    def build(_self, *_args):
        entered.set()
        assert release.wait(5)
        finished.set()
        return object(), object()

    monkeypatch.setattr(_ViewportGeometryBuilder, "_build_scene_meshes", build)
    widget = DetailingViewViewport()
    monkeypatch.setattr(widget, "_clear_view", lambda: None)
    monkeypatch.setattr(widget, "_show_scene", lambda *_args: shown.append(True))
    try:
        widget.request_view(_model(), "XY", 0.0)
        assert entered.wait(5)
        widget.shutdown()
        release.set()
        assert finished.wait(5)
        QTest.qWait(20)
        app.processEvents()
        assert not shown
    finally:
        release.set()
        widget.shutdown()
        widget.close()


def test_reopened_view_reuses_preview_and_group_changes_invalidate_it(monkeypatch):
    app = QApplication.instance() or QApplication([])
    calls = []

    def build(_self, _model, plane, _coordinate, _settings):
        calls.append(plane)
        return object(), object()

    monkeypatch.setattr(_ViewportGeometryBuilder, "_build_scene_meshes", build)
    model = _model()
    first, second = DetailingViewViewport(), DetailingViewViewport()
    for widget in (first, second):
        monkeypatch.setattr(widget, "_clear_view", lambda: None)
        monkeypatch.setattr(widget, "_show_scene", lambda *_args: None)
    try:
        first.request_view(model, "XY", 0.0)
        for _ in range(300):
            app.processEvents()
            if not first._render_pending:
                break
            QTest.qWait(5)
        assert calls == ["XY"]
        second.request_view(model, "XY", 0.0)
        assert not second._render_pending
        assert calls == ["XY"]
        model.verification_group_revision += 1
        second.request_view(model, "XY", 0.0)
        for _ in range(300):
            app.processEvents()
            if not second._render_pending:
                break
            QTest.qWait(5)
        assert calls == ["XY", "XY"]
    finally:
        for widget in (first, second):
            widget.shutdown()
            widget.close()


def test_curve_transition_edges_appear_in_isometric_and_section_linework():
    from osa.ui.detailing_preview import _ViewGeometryCalculator

    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 4)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", "W Laminado")
    model.update_member_profile("B1", "W", {"d": 251, "bf": 101, "tw": 4.8, "tf": 5.3})
    for plane in ("YZ", "ISO-SE"):
        calc = _ViewGeometryCalculator()
        DetailingViewPreview.set_view(calc, model, plane, 0, upper_offset_cm=1000, lower_offset_cm=1000)
        restored = set(calc._segments_2d)
        assert set(calc._segment_sources) == {"bar:B1"}
        assert calc._ensure_model_curve_edges(model)["B1"].n_lines == 8
        DetailingViewPreview._shared_model_edge_meshes.pop(model, None)
        old = _ViewGeometryCalculator()
        old._ensure_model_curve_edges = lambda *_args: {}
        DetailingViewPreview.set_view(old, model, plane, 0, upper_offset_cm=1000, lower_offset_cm=1000)
        previous = set(old._segments_2d)
        assert previous.issubset(restored)
        assert len(restored - previous) >= 2


def test_curve_edges_are_clipped_to_the_view_depth():
    edges = pv.PolyData(np.array([[0., 0., -2.], [0., 0., 2.]]), lines=np.array([2, 0, 1]))
    clipped = DetailingViewPreview._clip_curve_edges(edges, 2, -.5, .5)
    assert clipped.n_lines == 1
    np.testing.assert_allclose(clipped.bounds[4:], (-.5, .5))
    assert DetailingViewPreview._clip_curve_edges(edges, 2, 3, 4).n_lines == 0


def test_sheet_linework_upgrade_keeps_annotation_and_rejects_stale_results():
    from unittest.mock import MagicMock

    from osa.ui.detailing_preview import DETAILING_LINEWORK_VERSION
    from osa.ui.main_window import MainWindow

    model = _model()
    view = {"model_revision": model.revision, "projection": {"plane": "YZ", "coordinate": 0},
            "segments": (((0, 0), (1, 1)),), "identifications": [{"text": "B1"}],
            "dimensions": [{"start": (0, 0), "end": (1, 1)}]}
    workspace = MagicMock()
    window = SimpleNamespace(
        model=model, _sheet_linework_pending={(id(view), model.revision, model.verification_group_revision)},
        project_sheet_workspace=workspace,
        project_sheets_palette=SimpleNamespace(_sheet_views={"Sheet": [view]}, sheet_selector=MagicMock()),
        _store_detailing_state=MagicMock(),
    )
    window.project_sheets_palette.sheet_selector.currentText.return_value = "Sheet"
    projection = dict(view["projection"])
    segments, owners = (((0, 0), (2, 2)),), ("bar:B1",)
    MainWindow._sheet_linework_upgraded(window, "Sheet", view, model.revision,
                                       model.verification_group_revision, projection, segments, owners, True)
    assert view["segments"] == segments
    assert view["linework_version"] == DETAILING_LINEWORK_VERSION
    assert view["identifications"] == [{"text": "B1"}]
    assert view["dimensions"] == [{"start": (0, 0), "end": (1, 1)}]
    workspace._dimension_snap_cache.clear.assert_called_once()
    window._store_detailing_state.assert_called_once()
    # A late result must not overwrite a view that has since changed.
    view["projection"] = {"plane": "XZ", "coordinate": 0}
    MainWindow._sheet_linework_upgraded(window, "Sheet", view, model.revision,
                                       model.verification_group_revision, projection, (), (), True)
    assert view["segments"] == segments


def test_detailing_state_snapshot_shares_read_only_linework_but_copies_annotations():
    from osa.ui.main_window import MainWindow

    segments = tuple(((float(index), 0.0), (float(index + 1), 0.0)) for index in range(1000))
    owners = tuple("bar:B1" for _ in segments)
    identification = {"text": "B1", "properties": {"show_name": True}}
    view = {
        "segments": segments,
        "segment_owners": owners,
        "identifications": [identification],
        "dimensions": [{"start": (0.0, 0.0), "end": (1.0, 0.0)}],
    }
    palette = SimpleNamespace(
        _sheet_names=["01"],
        sheet_selector=SimpleNamespace(currentText=lambda: "01"),
        _sheet_settings={"01": {}},
        _project_settings={},
        _sheet_views={"01": [view]},
    )
    context = SimpleNamespace(model=StructuralModel(), project_sheets_palette=palette)

    snapshot = MainWindow._detailing_state_snapshot(context)["sheets"]["sheet_views"]["01"][0]

    assert snapshot["segments"] is segments
    assert snapshot["segment_owners"] is owners
    assert snapshot["identifications"] is not view["identifications"]
    assert snapshot["dimensions"] is not view["dimensions"]
    identification["properties"]["show_name"] = False
    assert snapshot["identifications"][0]["properties"]["show_name"] is True


def test_viewport_scene_includes_curved_profile_transitions(monkeypatch):
    from osa.ui.detailing_preview import _ViewGeometryCalculator

    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 4)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", "W Laminado")
    model.update_member_profile("B1", "W", {"d": 251, "bf": 101, "tw": 4.8, "tf": 5.3})
    builder = _ViewportGeometryBuilder(None)
    for plane in ("YZ", "ISO-SE"):
        DetailingViewPreview._shared_model_edge_meshes.pop(model, None)
        with monkeypatch.context() as patch:
            patch.setattr(_ViewGeometryCalculator, "_ensure_model_curve_edges", lambda *_args: {})
            _surface, old_edges = builder._build_scene_meshes(model, plane, 0, {
                "upper_offset_cm": 1000, "lower_offset_cm": 1000,
            })
        DetailingViewPreview._shared_model_edge_meshes.pop(model, None)
        _surface, restored_edges = builder._build_scene_meshes(model, plane, 0, {
            "upper_offset_cm": 1000, "lower_offset_cm": 1000,
        })
        assert restored_edges.n_lines >= old_edges.n_lines + 8


def test_curve_edges_use_the_existing_hidden_line_rules():
    from osa.rendering.detailing_2d import visible_segments_from_meshes

    cube = pv.Cube().triangulate().clean()
    behind = pv.Line((-0.3, 0, -.5), (.3, 0, -.5))
    front = pv.Line((-0.3, 0, .5), (.3, 0, .5))
    base = set(visible_segments_from_meshes((cube,), (0, 0, 1), (0, 1, 0)))
    hidden = set(visible_segments_from_meshes(
        (cube,), (0, 0, 1), (0, 1, 0), extra_feature_edge_meshes=(behind,),
    ))
    visible = set(visible_segments_from_meshes(
        (cube,), (0, 0, 1), (0, 1, 0), extra_feature_edge_meshes=(front,),
    ))
    assert hidden == base
    assert len(visible - base) == 1


def test_curve_transitions_do_not_add_faceting_to_round_or_rectangular_bars():
    from osa.ui.detailing_preview import _ViewGeometryCalculator

    model = StructuralModel()
    for index in range(4):
        model.add_node(f"T{index}", index, 0, 0)
    model.add_bar("B1", "T0", "T1")
    model.update_bar_section("B1", "Barra Retangular")
    model.update_member_profile("B1", "R", {"b": 100, "h": 200})
    model.add_bar("B2", "T2", "T3")
    model.update_bar_section("B2", "Tubular Circular")
    model.update_member_profile("B2", "C", {"D": 100, "t": 3})
    calc = _ViewGeometryCalculator()
    calc._ensure_model_meshes(model)
    assert calc._ensure_model_curve_edges(model) == {}
