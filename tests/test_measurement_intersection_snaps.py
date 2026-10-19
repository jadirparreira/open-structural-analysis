"""Measurement features and real intersections of the visible scene geometry."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from osa.domain import ReferenceAxis, StructuralModel
from osa.rendering.scene_batched import StructureScene
from osa.rendering.snap_geometry import segment_intersections
from osa.ui.dialogs import ProgramSettingsDialog


@pytest.mark.parametrize("second, expected", [
    (((0, -1, 0), (0, 1, 0)), [(0, 0, 0)]),
    (((0, -1, 1), (0, 1, 1)), []),  # apparent crossing at a different depth
    (((-1, 1, 0), (1, 1, 0)), []),  # parallel
    (((0, -2, 0), (0, -1, 0)), []),  # supporting lines cross outside the segments
    (((-0.5, 0, 0), (0.5, 0, 0)), []),  # collinear overlap has no unique crossing
    (((1, 0, 0), (1, 1, 0)), [(1, 0, 0)]),
    (((0, 0, 0), (0, 0, 0)), []),
])
def test_intersections_are_finite_and_three_dimensional(second, expected):
    segments = np.asarray((((-1, 0, 0), (1, 0, 0)), second), dtype=float)
    actual = segment_intersections(segments[:, 0], segments[:, 1], 1e-9)
    np.testing.assert_allclose(actual, np.asarray(expected, dtype=float).reshape((-1, 3)))


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance() or QApplication([])
    scene = StructureScene()
    scene.resize(800, 600)
    scene.plotter.resize(800, 600)
    scene.plotter.render_window.SetSize(800, 600)
    yield scene
    scene.plotter.close()
    scene.hide()
    scene.deleteLater()
    app.processEvents()


@pytest.fixture
def scene(viewport):
    scene = viewport
    scene.set_measurement_mode(False)
    scene._pointer_position = None
    scene._camera_interacting = False
    scene._reference_plane_mode = "XY"
    scene._reference_plane_z = 0.0
    scene._grid_visible = False
    scene._reference_axes_visible = False
    scene._solid_members_visible = False
    scene._snap_types = dict.fromkeys(scene._snap_types, True)
    yield scene
    scene._measurement_refresh_timer.stop()


def render(scene, model, *, solid=False, front=False):
    scene._solid_members_visible = solid
    scene.render_model(model, preserve_camera=False)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetParallelProjection(True)
    camera.SetPosition((2, -10, 5) if front else (0, 0, 20))
    camera.SetFocalPoint((2, 0, 0) if front else (0, 0, 0))
    camera.SetViewUp(0, 0, 1) if front else camera.SetViewUp(0, 1, 0)
    camera.SetParallelScale(4)
    camera.SetClippingRange(0.1, 100)
    scene.plotter.render()


def point_at(scene, point):
    screen, visible = scene._world_to_screen(np.asarray(point, dtype=float))
    assert visible
    scene._pointer_position = tuple(screen)


def add_line(model, prefix, first, last, *, rigid=False):
    model.add_node(prefix + "1", *first)
    model.add_node(prefix + "2", *last)
    if rigid:
        model.add_rigid_bar(prefix + "1", prefix + "2")
    else:
        model.add_bar(prefix, prefix + "1", prefix + "2")


@pytest.mark.parametrize("pair", ["members", "rigid", "grid", "axes", "grid_axes", "axes_rigid"])
@pytest.mark.parametrize("operation", ["measurement", "member"])
def test_intersection_sources_and_settings(scene, pair, operation):
    model = StructuralModel()
    crossing = np.asarray((0.3, 0.2, 0.0))
    if pair in {"members", "rigid", "grid"}:
        add_line(model, "B", (-2, 0.2, 0), (3, 0.2, 0))
    if pair in {"members", "rigid", "axes_rigid"}:
        add_line(model, "C", (0.3, -2, 0), (0.3, 2, 0), rigid=pair != "members")
    if pair == "grid":
        crossing[0] = 1.0
    if pair in {"axes", "grid_axes", "axes_rigid"}:
        model.set_reference_axes({
            "X": (ReferenceAxis("A", 0.3),) if pair == "axes" else (),
            "Y": (ReferenceAxis("1", 0.2),),
        })
        scene._reference_axes_visible = True
    if pair in {"grid", "grid_axes"}:
        scene._grid_visible = True
        crossing[0] = 1.0
    render(scene, model)
    if operation == "measurement":
        scene.set_measurement_mode(True)
        resolver = scene._measurement_target
    else:
        scene.set_member_placement_mode(True)
        resolver = scene._placement_target
    point_at(scene, crossing)

    target, kind = resolver(np.zeros(3))

    assert kind == "intersection"
    np.testing.assert_allclose(target, crossing)
    scene._position_snap_marker(target, kind)
    assert scene._snap_marker._kind == "intersection"
    assert scene._snap_marker._renderers["intersection"].isValid()
    cached = scene._intersection_snap_cache
    resolver(np.zeros(3))
    assert scene._intersection_snap_cache is cached
    scene.set_snap_type_enabled("intersection", False)
    assert resolver(np.zeros(3))[1] is None


def test_measurement_shows_only_deltas_after_the_initial_click(scene, monkeypatch):
    render(scene, StructuralModel())
    scene.set_measurement_mode(True)
    point_at(scene, (1, 1, 0))
    monkeypatch.setattr(scene, "_cursor_world_position", lambda: np.asarray((1, 1, 0)))
    scene._update_coordinate_readout()
    scene._update_measurement_readout()
    assert scene._coordinate_readout.isHidden()
    assert scene._measurement_readout.isHidden()

    scene.set_measurement_start((0, 0, 0))
    assert scene._coordinate_readout.isHidden()
    assert not scene._measurement_readout.isHidden()
    assert [label.text() for label in scene._measurement_value_labels] == [
        "1.414 m", "1.000 m", "1.000 m", "0.000 m",
    ]


def rectangular_member():
    model = StructuralModel()
    add_line(model, "B", (0, 0, 0), (4, 0, 0))
    model.update_bar_section("B", "Barra Retangular")
    model.update_member_profile("B", "1000 x 1000", {"b": 1000, "h": 1000})
    return model


@pytest.mark.parametrize("point, kind", [((0, -0.5, 0.5), "endpoint"), ((2, -0.5, 0.5), "center")])
def test_measurement_snaps_to_visible_solid_edge_features(scene, point, kind):
    render(scene, rectangular_member(), solid=True, front=True)
    scene.set_measurement_mode(True)
    scene._snap_types["intersection"] = False
    point_at(scene, point)

    target, actual_kind = scene._measurement_target(np.zeros(3))

    assert actual_kind == kind
    np.testing.assert_allclose(target, point, atol=1e-9)
    scene.set_snap_type_enabled(kind, False)
    assert scene._measurement_target(np.zeros(3))[1] is None
    scene.set_snap_type_enabled(kind, True)
    scene.set_solid_members_visible(False)
    assert scene._measurement_target(np.zeros(3))[1] is None


def test_measurement_edge_perpendicular_requires_initial_point_and_does_not_snap_freely(scene):
    render(scene, rectangular_member(), solid=True, front=True)
    scene.set_measurement_mode(True)
    scene._snap_types["intersection"] = False
    foot = np.asarray((1, -0.5, 0.5))
    point_at(scene, foot)
    assert scene._measurement_target(np.zeros(3))[1] is None

    start = (1, -1.5, 0.5)
    scene.set_measurement_start(start)
    target, kind = scene._measurement_target(np.zeros(3))
    assert kind == "perpendicular"
    np.testing.assert_allclose(target, foot)
    assert np.dot(target - start, (1, 0, 0)) == pytest.approx(0)
    scene.set_snap_type_enabled("perpendicular", False)
    assert scene._measurement_target(np.zeros(3))[1] is None


def test_solid_edge_intersection_with_a_rigid_bar_tracks_representation(scene):
    model = rectangular_member()
    add_line(model, "R", (1.3, -1, 0.5), (1.3, 1, 0.5), rigid=True)
    render(scene, model, solid=True, front=True)
    scene.set_measurement_mode(True)
    crossing = np.asarray((1.3, -0.5, 0.5))
    point_at(scene, crossing)

    target, kind = scene._measurement_target(np.zeros(3))

    assert kind == "intersection"
    np.testing.assert_allclose(target, crossing)
    scene.set_solid_members_visible(False)
    assert scene._measurement_target(np.zeros(3))[1] is None


def test_edge_features_work_with_the_construction_plane_edge_on(scene):
    render(scene, rectangular_member(), solid=True, front=True)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(2, -10, 0)
    camera.SetViewUp(0, 0, 1)
    scene.set_measurement_mode(True)
    scene._snap_types["intersection"] = False
    target = np.asarray((2, -0.5, 0.5))
    point_at(scene, target)

    np.testing.assert_allclose(scene._cursor_world_position(), target)


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
def test_intersection_uses_actual_construction_plane_and_offset(scene, plane):
    scene._reference_plane_mode = plane
    scene._reference_plane_z = 2.0
    scene._grid_visible = True

    def world(point):
        return scene._reference_axes_renderer._world_point(point, plane, 2.0)

    model = StructuralModel()
    model.set_reference_axes({{"XY": "Z", "XZ": "Y", "YZ": "X"}[plane]: (ReferenceAxis("N2", 2.0),)})
    add_line(model, "B", world((-2, 0.2)), world((3, 0.2)))
    render(scene, model)
    assert scene._reference_plane_levels() == (2.0,)
    assert scene._reference_plane_z == 2.0
    camera = scene.plotter.renderer.GetActiveCamera()
    normal = np.eye(3)[{"XY": 2, "XZ": 1, "YZ": 0}[plane]]
    camera.SetPosition(*(world((0, 0)) + normal * 20))
    camera.SetFocalPoint(*world((0, 0)))
    camera.SetViewUp(0, 1, 0) if plane == "XY" else camera.SetViewUp(0, 0, 1)
    scene.set_measurement_mode(True)
    crossing = world((1, 0.2))
    point_at(scene, crossing)

    point, kind = scene._measurement_target(np.zeros(3))

    assert kind == "intersection"
    np.testing.assert_allclose(point, crossing)


def test_scene_does_not_snap_to_apparent_crossings_at_different_depths(scene):
    model = StructuralModel()
    add_line(model, "A", (-1, 0, 0), (1, 0, 0))
    add_line(model, "B", (0, -1, 1), (0, 1, 1))
    render(scene, model)
    scene.set_measurement_mode(True)
    scene._snap_types.update(endpoint=False, center=False)
    point_at(scene, (0, 0, 0))

    assert scene._measurement_target(np.zeros(3))[1] is None


def test_hidden_solid_edges_do_not_offer_features_or_perpendiculars(scene):
    render(scene, rectangular_member(), solid=True, front=True)
    scene.set_measurement_mode(True)
    scene._snap_types["intersection"] = False
    point_at(scene, (2, 0.5, -0.5))
    assert scene._measurement_target(np.zeros(3))[1] is None

    scene.set_measurement_start((1, 1.5, -0.5))
    point_at(scene, (1, 0.5, -0.5))
    assert scene._measurement_target(np.zeros(3))[1] is None


def test_hiding_reference_axes_removes_their_intersections(scene):
    model = StructuralModel()
    model.set_reference_axes({"X": (ReferenceAxis("A", 0.3),), "Y": (ReferenceAxis("1", 0.2),)})
    scene._reference_axes_visible = True
    render(scene, model)
    scene.set_measurement_mode(True)
    point_at(scene, (0.3, 0.2, 0))
    assert scene._measurement_target(np.zeros(3))[1] == "intersection"

    scene.set_reference_axes_visible(False)
    assert scene._measurement_target(np.zeros(3))[1] is None


def test_intersection_settings_reuse_the_cross_icon():
    assert ProgramSettingsDialog._snap_options[0] == ("intersection", "Interseção", "x.svg")
