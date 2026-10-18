import os
import zlib
from base64 import b64encode
from dataclasses import replace
from struct import pack

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
import numpy as np
import pytest
import pyvista as pv
from PySide6.QtWidgets import QApplication

from osa.domain.drawing_reference import DrawingReference, ReferenceGeometry
from osa.importers.drawing_reference import import_drawing_reference
from osa.model import StructuralModel
from osa.persistence.drawing_reference import dump_reference, load_reference
from osa.rendering.drawing_reference_renderer import DrawingReferenceRenderer
from osa.rendering.label_overlay import project_world_to_screen
from osa.rendering.scene_batched import StructureScene


def _points(buffer):
    return np.frombuffer(buffer, dtype="<f8").reshape(-1, 2)


def _import(document, tmp_path):
    filename = tmp_path / "features.dxf"
    document.units = 6
    document.saveas(filename)
    return import_drawing_reference(filename).reference


def _line_geometry():
    return ReferenceGeometry(
        pack("<dddd", 2, 3, 6, 3), b"", pack("<dddd", 2, 3, 6, 3), pack("<dd", 4, 3),
    )


def test_cad_features_ignore_dashes_hatch_strokes_and_text(tmp_path):
    document = ezdxf.new()
    document.linetypes.new("DASHED", dxfattribs={"pattern": [1, 0.6, -0.4]})
    space = document.modelspace()
    space.add_line((2, 3), (6, 3), dxfattribs={"linetype": "DASHED"})
    hatch = space.add_hatch()
    hatch.set_pattern_fill("ANSI31", scale=0.1)
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    space.add_text("ABC", dxfattribs={"height": 1})
    geometry = _import(document, tmp_path).geometry
    assert len(geometry.lines) // 32 > 10
    np.testing.assert_allclose(_points(geometry.snap_endpoints), [[2, 3], [6, 3]])
    np.testing.assert_allclose(_points(geometry.snap_centers), [[4, 3]])


def test_curves_and_bulged_polylines_keep_semantic_features(tmp_path):
    document = ezdxf.new()
    space = document.modelspace()
    space.add_arc((0, 0), 2, 0, 90)
    space.add_circle((10, 10), 3)
    space.add_ellipse((20, 20), major_axis=(3, 0), ratio=0.5)
    space.add_lwpolyline([(30, 0, 1), (34, 0, 0)], format="xyb")
    geometry = _import(document, tmp_path).geometry
    endpoints, centers = _points(geometry.snap_endpoints), _points(geometry.snap_centers)
    assert len(endpoints) == 4  # 2 arc ends, 2 polyline ends; closed curves have none.
    for point in ((0, 0), (10, 10), (20, 20), (32, 0)):
        assert np.any(np.all(np.isclose(centers, point), axis=1))
    assert np.any(np.all(np.isclose(endpoints, (2, 0)), axis=1))
    assert np.any(np.all(np.isclose(endpoints, (0, 2)), axis=1))


def test_visible_block_features_follow_nested_transform_and_units(tmp_path):
    document = ezdxf.new()
    document.units = 4
    document.layers.new("HIDDEN").off()
    block = document.blocks.new("ROOM")
    block.add_line((0, 0), (2, 0))
    block.add_line((500, 500), (600, 600), dxfattribs={"layer": "HIDDEN"})
    document.modelspace().add_blockref("ROOM", (4, 3), dxfattribs={"rotation": 90, "xscale": 2})
    filename = tmp_path / "block.dxf"
    document.saveas(filename)
    geometry = import_drawing_reference(filename).reference.geometry
    np.testing.assert_allclose(_points(geometry.snap_endpoints), [[.004, .003], [.004, .007]], atol=1e-12)
    np.testing.assert_allclose(_points(geometry.snap_centers), [[.004, .005]], atol=1e-12)


def test_features_roundtrip_and_legacy_geometry_remains_readable():
    reference = DrawingReference("reference", "CAD", _line_geometry(), origin=(10, 20, 30), plane="XZ")
    restored = load_reference(dump_reference(reference))
    assert restored.geometry.snap_endpoints == reference.geometry.snap_endpoints
    assert restored.geometry.snap_centers == reference.geometry.snap_centers
    data = dump_reference(reference)
    data["geometry"] = {
        "encoding": "xy-f64le-zlib-v1", "line_bytes": len(reference.geometry.lines),
        "data": b64encode(zlib.compress(reference.geometry.lines)).decode("ascii"),
    }
    legacy = load_reference(data)
    assert legacy.geometry.snap_endpoints is None
    endpoints, centers = DrawingReferenceRenderer().snap_points({legacy.id: legacy})
    np.testing.assert_allclose(endpoints, [[12, 20, 33], [16, 20, 33]])
    np.testing.assert_allclose(centers, [[14, 20, 33]])


def test_hatch_only_references_have_no_snaps(tmp_path):
    document = ezdxf.new()
    hatch = document.modelspace().add_hatch()
    hatch.set_pattern_fill("ANSI31", scale=.1)
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)], is_closed=True)
    reference = _import(document, tmp_path)
    restored = load_reference(dump_reference(reference))
    endpoints, centers = DrawingReferenceRenderer().snap_points({restored.id: restored})
    assert not len(endpoints) and not len(centers)


def test_highlight_and_visual_origin_follow_selection_without_touching_geometry():
    references = {name: DrawingReference(name, name, _line_geometry(), origin=origin) for name, origin in (
        ("first", (10, 20, 30)), ("second", (50, 60, 70)),
    )}
    plotter = pv.Plotter(off_screen=True)
    try:
        renderer = DrawingReferenceRenderer()
        renderer.sync(plotter, references)
        first = renderer.actors["first"]
        mesh = first.GetMapper().GetInput()
        renderer.set_selected(plotter, references, "first")
        assert first.GetProperty().GetColor() == pv.Color("#0969da").float_rgb
        assert first.GetProperty().GetLineWidth() > renderer.actors["second"].GetProperty().GetLineWidth()
        origin = renderer.origin_actor
        assert origin.GetPosition() == (10, 20, 30)
        assert origin.GetVisibility() and not origin.GetPickable()
        assert origin.GetMapper().GetInput().bounds[5] == pytest.approx(.05)
        references["first"] = replace(references["first"], origin=(1, 2, 3), plane="YZ")
        renderer.sync(plotter, references)
        assert first.GetMapper().GetInput() is mesh
        assert renderer.origin_actor is origin and origin.GetPosition() == (1, 2, 3)
        renderer.set_selected(plotter, references, "second")
        assert first.GetProperty().GetColor() == pv.Color("#8c959f").float_rgb
        assert origin.GetPosition() == (50, 60, 70)
        references["second"] = replace(references["second"], visible=False)
        renderer.sync(plotter, references)
        assert not origin.GetVisibility()
        renderer.set_selected(plotter, references, None)
        assert not origin.GetVisibility()
        assert renderer.actors["second"].GetProperty().GetLineWidth() == 1
    finally:
        plotter.close()


def test_reference_feature_cache_only_rebuilds_after_placement_visibility_or_geometry_changes():
    reference = DrawingReference("CAD", "CAD", _line_geometry())
    renderer = DrawingReferenceRenderer()
    endpoints, centers = renderer.snap_points({reference.id: reference})
    again = renderer.snap_points({reference.id: reference})
    assert endpoints is again[0] and centers is again[1]
    moved = replace(reference, origin=(10, 20, 30), plane="YZ")
    new_endpoints, new_centers = renderer.snap_points({moved.id: moved})
    np.testing.assert_allclose(new_endpoints, [[10, 22, 33], [10, 26, 33]])
    np.testing.assert_allclose(new_centers, [[10, 24, 33]])
    hidden = replace(moved, visible=False)
    assert not len(renderer.snap_points({hidden.id: hidden})[0])


@pytest.fixture
def reference_scene():
    app = QApplication.instance() or QApplication([])
    model = StructuralModel()
    reference = DrawingReference("CAD", "CAD", _line_geometry(), origin=(0, 0, 4))
    model.add_reference(reference)
    scene = StructureScene()
    scene.plotter.resize(800, 600)
    scene.render_model(model)
    scene.set_grid_visible(False)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(20, 20, 20)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, 0, 1)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(12)
    scene.plotter.reset_camera_clipping_range()
    yield scene, model, reference
    scene.close()
    app.processEvents()


def _point_cursor_at(scene, point):
    matrix, width, height = scene._measurement_projection_context()
    screens, visible = project_world_to_screen(np.asarray([point], dtype=float), matrix, width, height)
    assert visible[0]
    scene._pointer_position = tuple(screens[0])


@pytest.mark.parametrize("mode", ["member", "measure"])
@pytest.mark.parametrize("kind,point", [("endpoint", (2, 3, 4)), ("center", (4, 3, 4))])
def test_reference_features_are_targets_for_both_tools(reference_scene, monkeypatch, mode, kind, point):
    scene, model, reference = reference_scene
    if mode == "member":
        scene.set_member_placement_mode(True)
    else:
        scene.set_measurement_mode(True)
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, worlds, *a, **kw: np.ones(len(worlds), bool))
    _point_cursor_at(scene, point)
    resolve = scene._placement_target if mode == "member" else scene._measurement_target
    target, actual_kind = resolve(np.zeros(3))
    assert actual_kind == kind
    np.testing.assert_allclose(target, point)
    # The origin is visual only and cannot become a target by selecting the reference.
    scene.set_selected_drawing_reference(reference.id)
    _point_cursor_at(scene, reference.origin)
    assert resolve(np.asarray(reference.origin))[1] is None
    assert not model.nodes and not model.bars
    _point_cursor_at(scene, point)
    scene.set_snap_type_enabled(kind, False)
    assert resolve(np.zeros(3))[1] != kind
    scene.set_snap_type_enabled(kind, True)
    model.update_reference(reference.id, visible=False)
    assert resolve(np.zeros(3))[1] is None
    model.update_reference(reference.id, origin=(1, 2, 3), plane="YZ", visible=True)
    moved = (1, 4, 6) if kind == "endpoint" else (1, 6, 6)
    _point_cursor_at(scene, moved)
    target, actual_kind = resolve(np.zeros(3))
    assert actual_kind == kind
    np.testing.assert_allclose(target, moved)
    scene.set_snap_enabled(False)
    assert resolve(np.zeros(3))[1] == kind
    scene.set_snap_type_enabled(kind, False)
    assert resolve(np.zeros(3))[1] is None


def test_references_do_not_add_edge_snaps_or_participate_in_node_placement(reference_scene, monkeypatch):
    scene, _model, _reference = reference_scene
    scene.set_measurement_mode(True)
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, worlds, *a, **kw: np.ones(len(worlds), bool))
    # A point on the line that is well away from an endpoint or its midpoint.
    scene._snap_tolerance_pixels = 1
    _point_cursor_at(scene, (3, 3, 4))
    assert scene._measurement_target(np.zeros(3))[1] is None
    scene.set_node_placement_mode(True)
    _point_cursor_at(scene, (2, 3, 4))
    assert scene._snap_position(np.zeros(3)) is None


@pytest.mark.parametrize("mode", ["member", "measure"])
def test_reference_snaps_work_when_camera_is_parallel_to_construction_plane(reference_scene, monkeypatch, mode):
    scene, model, reference = reference_scene
    model.update_reference(reference.id, plane="YZ", origin=(0, 0, 0))
    scene.refresh_drawing_references(model)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(20, 4, 3)
    camera.SetFocalPoint(0, 4, 3)
    camera.SetViewUp(0, 0, 1)
    scene.plotter.reset_camera_clipping_range()
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, worlds, *a, **kw: np.ones(len(worlds), bool))
    if mode == "member":
        scene.set_member_placement_mode(True)
    else:
        scene.set_measurement_mode(True)
    _point_cursor_at(scene, (0, 2, 3))
    np.testing.assert_allclose(scene._placement_world_position(), (0, 2, 3))
