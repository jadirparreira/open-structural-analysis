import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pyvista as pv
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.domain import DetailEndCut, NodeComponentAssignment
from osa.rendering.batched_renderer import (
    BatchedMemberRenderer,
    _boolean_difference_mesh,
    _clip_line_mesh_outside_cutters,
)
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


def test_end_cut_uses_a_closed_face_plane_cutter_with_boolean_difference():
    from osa.rendering.scene_batched import StructureScene

    target = pv.Cube().triangulate()
    cut = DetailEndCut("cut-1", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), "Face de referência")
    cutter = StructureScene._detail_end_cut_mesh(target, cut)
    result = _boolean_difference_mesh(target, cutter)

    assert result is not None
    assert result.volume == pytest.approx(target.volume / 2.0, rel=1e-6)
    assert result.bounds[5] <= 1e-6


def test_multi_face_end_cut_removes_only_the_common_half_space_region():
    from osa.rendering.scene_batched import StructureScene

    target = pv.Cube(
        center=(0.5, 0.0, 0.0), x_length=1.0, y_length=1.0, z_length=1.0,
    ).triangulate()
    cut = DetailEndCut(
        "cut-multi", (0.4, 0.2, 0.0), (1.0, 0.0, 0.0),
        "Interseção das faces", (
            ((0.4, 0.0, 0.0), (1.0, 0.0, 0.0)),
            ((0.0, 0.2, 0.0), (0.0, 1.0, 0.0)),
        ),
    )

    cutter = StructureScene._detail_end_cut_mesh(target, cut)
    result = _boolean_difference_mesh(target, cutter)

    assert result is not None
    assert result.volume == pytest.approx(0.82, rel=1e-5)
    assert result.bounds[1] == pytest.approx(1.0)
    assert result.bounds[3] == pytest.approx(0.5)


def test_end_cut_is_included_for_a_member_without_standard_subtractions():
    from osa.rendering.scene_batched import StructureScene

    model = _model()
    model.add_detail_end_cut(
        "B0", "cut-1", (0.5, 0.0, 0.0), (1.0, 0.0, 0.0), "Face de referência",
    )
    cutter = pv.Cube()
    scene_state = SimpleNamespace(
        _detailing_session_active=True,
        _solid_members_visible=True,
        _detail_subtraction_meshes={("end_cut", "cut-1"): cutter},
    )

    mapped = StructureScene._detail_subtractions_by_target(scene_state, model)

    assert mapped[("bar", "B0")] == ((('end_cut', 'cut-1'), cutter),)


def test_member_profile_edges_remain_on_both_sides_of_a_subtraction():
    source_edges = pv.PolyData(
        np.asarray(((-2.0, 0.0, 0.0), (2.0, 0.0, 0.0))),
        lines=np.asarray((2, 0, 1)),
    )

    clipped = _clip_line_mesh_outside_cutters(source_edges, (pv.Cube(),))

    assert clipped.n_lines == 2
    np.testing.assert_allclose(clipped.bounds, (-2.0, 2.0, 0.0, 0.0, 0.0, 0.0))
    for cell in clipped.lines.reshape((-1, 3)):
        endpoints = clipped.points[cell[1:]]
        assert abs(endpoints.mean(axis=0)[0]) >= 0.5 - 1e-9


@pytest.mark.parametrize("reference", [("end_cut", "cut"), ("bar", "B1")])
def test_cut_tubular_members_keep_their_section_profile_edges(reference):
    from osa.rendering.scene_batched import StructureScene

    model = StructuralModel()
    model.add_node("N0", 0, 0, 0)
    model.add_node("N1", 2, 0, 0)
    model.add_bar("B0", "N0", "N1")
    model.update_bar_section("B0", "Tubular Quadrado")
    model.update_member_profile("B0", "TQ 100 x 3", {"b": 100, "t": 3})
    renderer = BatchedMemberRenderer()
    original = renderer.build(model, 0.05)
    first, last = original.face_cell_ranges["B0"]
    target = original.faces.extract_cells(np.arange(first, last)).extract_surface(
        algorithm="dataset_surface",
    ).triangulate().clean()
    cutter = StructureScene._detail_end_cut_mesh(
        target, DetailEndCut("cut", (1.0, 0.0, 0.0), (1.0, 0.0, 0.0), "Face"),
    )

    cut = renderer.build(
        model, 0.05, subtraction_meshes={("bar", "B0"): ((reference, cutter),)},
    )

    edge_start, edge_end = cut.edge_cell_ranges["B0"]
    face_start, face_end = cut.face_cell_ranges["B0"]
    cut_surface = cut.faces.extract_cells(np.arange(face_start, face_end)).extract_surface(
        algorithm="dataset_surface",
    ).triangulate().clean()
    boolean_edges = cut_surface.extract_feature_edges(
        boundary_edges=True, feature_edges=True,
        manifold_edges=False, non_manifold_edges=False, feature_angle=25.0,
    )
    assert edge_end - edge_start > boolean_edges.n_cells


def test_adding_end_cut_rebuilds_the_rendered_member_solid():
    from osa.rendering.scene_batched import StructureScene

    app = QApplication.instance() or QApplication([])
    model = _model()
    scene = StructureScene()
    try:
        scene.render_model(model)
        scene.set_detailing_session_active(True)
        scene.set_solid_members_visible(True)
        model.add_detail_end_cut(
            "B0", "cut-1", (0.5, 0.0, 0.0), (1.0, 0.0, 0.0), "Face de referência",
        )
        scene.refresh_model_changes(model)

        start, end = scene._member_batch.face_cell_ranges["B0"]
        member = scene._member_batch.faces.extract_cells(np.arange(start, end)).extract_surface(
            algorithm="dataset_surface",
        ).triangulate().clean()
        assert member.bounds[1] <= 0.5 + 1e-6
        app.processEvents()
    finally:
        scene.close()


def test_managed_view_geometry_builds_with_multi_face_end_cut():
    from osa.ui.detailing_viewport import _ViewportGeometryBuilder, _DetachedDetailingScene

    model = StructuralModel()
    model.add_node("N0", 0, 0, 0)
    model.add_node("N1", 2, 0, 0)
    model.add_bar("B0", "N0", "N1")
    model.update_bar_section("B0", "Tubular Quadrado")
    model.update_member_profile("B0", "TQ 100 x 3", {"b": 100, "t": 3})
    model.update_node_component("N0", NodeComponentAssignment("base_plate"))
    model.add_detail_end_cut(
        "B0", "cut-managed-view", (0.8, 0.0, 0.0), (1.0, 0.0, 0.0),
        "Interseção das faces",
        planes=(
            ((0.8, 0.0, 0.0), (1.0, -0.4, 0.0)),
            ((0.8, 0.0, 0.0), (1.0, 0.0, -0.4)),
        ),
    )

    source = _DetachedDetailingScene(SimpleNamespace())
    surfaces, edges = _ViewportGeometryBuilder(source)._build_scene_meshes(
        model, "ISO-SE", None, {},
    )

    assert surfaces is not None and surfaces.n_cells > 0
    assert edges is not None and edges.n_cells > 0
    solid_names = {name for name, _mesh in source.detailing_view_solid_meshes(model)}
    assert any(name.startswith("component:N0:") for name in solid_names)


def test_viewport_adds_silhouette_lines_to_round_fasteners():
    import numpy as np
    import pyvista as pv
    from osa.ui.detailing_viewport import _ViewportGeometryBuilder

    rod = pv.Cylinder(
        center=(0, 0, 0), direction=(0, 0, 1), radius=0.05, height=1.0,
        resolution=32,
    ).triangulate()

    silhouettes = _ViewportGeometryBuilder._view_silhouette_edges(
        [rod], np.asarray((1.0, 0.0, 0.0)), np.asarray((0.0, 0.0, 1.0)),
    )

    assert silhouettes[0].n_lines >= 2
    line_cells = silhouettes[0].lines
    cursor = 0
    longitudinal_contours = 0
    while cursor < len(line_cells):
        count = int(line_cells[cursor])
        point_ids = line_cells[cursor + 1:cursor + count + 1]
        points = silhouettes[0].points[point_ids]
        if len(points) >= 2 and abs(points[-1, 2] - points[0, 2]) >= 0.99:
            longitudinal_contours += 1
        cursor += count + 1
    assert longitudinal_contours >= 2


def test_viewport_removes_group_interface_edges_with_boolean_mesh_tolerance():
    import numpy as np
    import pyvista as pv
    from osa.ui.detailing_viewport import _ViewportGeometryBuilder

    # The boolean cut can leave vertices a fraction of a micron off the
    # original joint plane. Both ends of the seam should still be filtered.
    edge_mesh = pv.PolyData(
        np.asarray(((1.0 + 2e-7, 0, 0), (1.0 + 2e-7, 1, 0), (0, 0, 0), (0, 1, 0))),
        lines=np.asarray((2, 0, 1, 2, 2, 3)),
    )
    filtered = _ViewportGeometryBuilder._without_group_interface_edges(
        edge_mesh, ((np.asarray((1.0, 0, 0)), np.asarray((1.0, 0, 0)), 1e-6),),
    )

    assert filtered.n_lines == 1


def test_profile_transition_edges_are_clipped_by_end_cut_in_managed_views():
    from osa.ui.detailing_preview import DetailingViewPreview, _ViewGeometryCalculator
    from osa.ui.detailing_viewport import _DetachedDetailingScene

    model = StructuralModel()
    model.add_node("N0", 0, 0, 0)
    model.add_node("N1", 2, 0, 0)
    model.add_bar("B0", "N0", "N1")
    model.update_bar_section("B0", "Tubular Quadrado")
    model.update_member_profile("B0", "TQ 100 x 3", {"b": 100, "t": 3})
    model.add_detail_end_cut(
        "B0", "cut-transition", (1.5, 0.0, 0.0), (1.0, 0.0, 0.0),
        "Interseção das faces",
        planes=(
            ((1.5, 0.0, 0.0), (1.0, -0.4, 0.0)),
            ((1.5, 0.0, 0.0), (1.0, 0.0, -0.4)),
        ),
    )

    calculator = _ViewGeometryCalculator()
    calculator._mesh_cache_owner = model
    calculator._detail_scene = _DetachedDetailingScene(SimpleNamespace())
    DetailingViewPreview._ensure_model_meshes(calculator, model)
    transitions = calculator._ensure_model_curve_edges(model)

    assert transitions["B0"].n_lines > 0
    assert transitions["B0"].bounds[1] < 1.7


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
        assert restored_edges.n_lines >= old_edges.n_lines + 4


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
