"""Perpendicular capture targets actual member segments, independently of guides."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from osa.domain import StructuralModel
from osa.rendering.scene_batched import StructureScene
from osa.ui.dialogs import ProgramSettingsDialog


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance() or QApplication([])
    scene = StructureScene()
    scene.resize(800, 600)
    scene.plotter.resize(800, 600)
    yield scene
    scene.plotter.close()
    scene.hide()
    scene.deleteLater()
    app.processEvents()


@pytest.fixture
def scene(viewport, monkeypatch):
    scene = viewport
    scene.set_member_placement_mode(False)
    scene._model = StructuralModel()
    scene._model.add_node("A", -5, 0, 0)
    scene._model.add_node("B", 5, 0, 0)
    scene._model.add_bar("existing", "A", "B")
    scene._snap_enabled = True
    scene._snap_types = dict.fromkeys(scene._snap_types, True)
    scene._pointer_position = None
    scene._reference_plane_mode = "XY"
    scene._grid_visible = False
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetParallelProjection(True)
    camera.SetPosition(0, 0, 30)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, 1, 0)
    camera.SetParallelScale(10)
    camera.SetClippingRange(0.1, 100)
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, *_args, **_kwargs: np.ones(len(screens), bool))
    return scene


def point_at(scene, point):
    screen, visible = scene._world_to_screen(np.asarray(point, dtype=float))
    assert visible
    scene._pointer_position = tuple(screen)


@pytest.mark.parametrize("operation", ["member", "rigid", "measurement"])
def test_second_point_captures_perpendicular_on_member_for_all_operations(scene, operation):
    start = (1, 4, 2)
    if operation == "measurement":
        scene.set_measurement_mode(True)
        scene.set_measurement_start(start)
    else:
        # Add Member and Add Rigid Bar share this graphical placement path.
        scene.set_member_placement_mode(True)
        scene.set_member_preview_start(start)
    point_at(scene, (1, 0, 0))
    resolver = scene._measurement_target if operation == "measurement" else scene._placement_target
    target, kind = resolver(np.asarray((1.02, 0.02, 0)))
    assert kind == "perpendicular"
    np.testing.assert_allclose(target, (1, 0, 0))
    assert np.dot(target - start, (1, 0, 0)) == pytest.approx(0)
    scene._position_snap_marker(target, kind)
    assert scene._snap_marker._kind == "perpendicular"
    assert scene._snap_marker._renderers["perpendicular"].isValid()


def test_second_point_captures_perpendicular_on_rigid_bar(scene):
    scene._model = StructuralModel()
    scene._model.add_node("R1", -5, 0, 0)
    scene._model.add_node("R2", 5, 0, 0)
    scene._model.add_rigid_bar("R1", "R2")
    scene._snap_types.update(endpoint=False, center=False, intersection=False)
    scene.set_member_placement_mode(True)
    start = (1, 4, 2)
    scene.set_member_preview_start(start)
    target = np.asarray((1, 0, 0))
    point_at(scene, target)

    snapped, kind = scene._placement_target(np.asarray((1.02, 0.02, 0)))

    assert kind == "perpendicular"
    np.testing.assert_allclose(snapped, target)
    assert np.dot(snapped - start, (1, 0, 0)) == pytest.approx(0)
    assert scene._placement_snap_element == ("rigid_bar", "R1-R2")


@pytest.mark.parametrize(("snap_kind", "target"), [
    ("endpoint", (-5, 0, 0)),
    ("center", (0, 0, 0)),
])
def test_placement_endpoint_and_center_snaps_work_on_rigid_bar(scene, snap_kind, target):
    scene._model = StructuralModel()
    scene._model.add_node("R1", -5, 0, 0)
    scene._model.add_node("R2", 5, 0, 0)
    scene._model.add_rigid_bar("R1", "R2")
    scene._snap_types.update(
        endpoint=snap_kind == "endpoint",
        center=snap_kind == "center",
        intersection=False,
        perpendicular=False,
    )
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0, 4, 0))
    point_at(scene, target)

    snapped, kind = scene._placement_target(np.asarray(target, dtype=float))

    assert kind == snap_kind
    np.testing.assert_allclose(snapped, target)
    if snap_kind == "center":
        assert scene._placement_snap_element == ("rigid_bar", "R1-R2")
    else:
        assert scene._placement_snap_element is None


@pytest.mark.parametrize("plane", ["XY", "XZ", "YZ"])
def test_oblique_3d_member_uses_world_perpendicular_independently_of_plane(scene, plane):
    scene._model = StructuralModel()
    scene._model.add_node("A", 0, 0, 0)
    scene._model.add_node("B", 4, 4, 4)
    scene._model.add_bar("existing", "A", "B")
    scene._reference_plane_mode = plane
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((2, 0, 3))
    expected = np.full(3, 5 / 3)
    point_at(scene, expected)
    target = scene._perpendicular_snap_target()
    np.testing.assert_allclose(target, expected)
    assert np.dot(target - (2, 0, 3), (4, 4, 4)) == pytest.approx(0)


@pytest.mark.parametrize("start, foot", [((8, 4, 0), (8, 0, 0)), ((0, 0, 0), (0, 0, 0))])
def test_projection_outside_segment_or_zero_length_connection_is_not_captured(scene, start, foot):
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start(start)
    point_at(scene, foot)
    assert scene._perpendicular_snap_target() is None


@pytest.mark.parametrize("operation", ["member", "measurement", "node"])
def test_no_perpendicular_without_a_fixed_initial_point(scene, operation):
    if operation == "measurement":
        scene.set_measurement_mode(True)
    elif operation == "node":
        scene.set_node_placement_mode(True)
    else:
        scene.set_member_placement_mode(True)
    point_at(scene, (0, 0, 0))
    assert scene._perpendicular_snap_target() is None


def test_cursor_tolerance_and_individual_snap_switches_with_master_always_active(scene):
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0, 4, 0))
    point_at(scene, (0, 0, 0))
    pointer = np.asarray(scene._pointer_position)
    scene._pointer_position = tuple(pointer + (scene._snap_tolerance_pixels + 1, 0))
    assert scene._perpendicular_snap_target() is None
    scene._pointer_position = tuple(pointer + (1, 0))
    assert scene._perpendicular_snap_target() is not None
    scene.set_snap_type_enabled("orthogonal", False)
    assert scene._perpendicular_snap_target() is not None
    scene.set_snap_type_enabled("perpendicular", False)
    assert scene._perpendicular_snap_target() is None
    scene.set_snap_type_enabled("perpendicular", True)
    scene.set_snap_enabled(False)
    assert scene._perpendicular_snap_target() is not None


def test_endpoint_has_priority_when_its_screen_position_matches_perpendicular(scene, monkeypatch):
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0, 4, 0))
    point_at(scene, (0, 0, 0))
    endpoint = np.asarray((0.0, 0.0, 0.0))
    perpendicular = np.asarray((0.0, 0.0, 2.0))
    endpoint_screen, endpoint_visible = scene._world_to_screen(endpoint)
    assert endpoint_visible
    perpendicular_screen, perpendicular_visible = scene._world_to_screen(perpendicular)
    assert perpendicular_visible
    np.testing.assert_allclose(endpoint_screen, perpendicular_screen)

    monkeypatch.setattr(scene, "_perpendicular_snap_target", lambda **_kwargs: perpendicular)
    monkeypatch.setattr(scene, "_perpendicular_snap_member_name", "existing")
    monkeypatch.setattr(
        scene,
        "_projected_snap_points",
        lambda *_args: (
            np.asarray([endpoint]), np.asarray([endpoint_screen]), np.asarray([True]),
            np.empty((0, 3)), np.empty((0, 2)), np.empty(0, dtype=bool),
            np.empty(0, dtype=object),
        ),
    )
    scene._snap_types.update(intersection=False, endpoint=True, center=False)

    target, kind = scene._snap_position(endpoint)

    assert kind == "endpoint"
    np.testing.assert_allclose(target, endpoint)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_orthogonal_controls_all_three_axis_guides_without_perpendicular(scene, monkeypatch, axis):
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0, 4, 0))
    scene._snap_types["perpendicular"] = False
    expected = np.eye(3)[axis]
    monkeypatch.setattr(scene, "_line_snap_candidate",
                        lambda direction: (expected, 0) if np.array_equal(direction, expected) else None)
    target, kind = scene._placement_guide_target()
    assert kind == "orthogonal"
    np.testing.assert_allclose(target, expected)
    scene._update_normal_guide()
    scene._update_orthogonal_guide()
    assert scene._normal_guide_actor.GetVisibility()
    assert scene._orthogonal_guide_actor.GetVisibility()
    scene._snap_types["orthogonal"] = False
    scene._snap_types["perpendicular"] = True
    assert scene._placement_guide_target() is None
    scene._update_normal_guide()
    scene._update_orthogonal_guide()
    assert not scene._normal_guide_actor.GetVisibility()
    assert not scene._orthogonal_guide_actor.GetVisibility()


def test_member_filter_and_cache_follow_changes_without_rebuilding_on_pointer_or_camera_motion(scene, monkeypatch):
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0, 4, 0))
    point_at(scene, (0, 0, 0))
    original = scene._scene_filtered_model
    rebuilds = []

    def tracked_model():
        rebuilds.append(True)
        return original()

    monkeypatch.setattr(scene, "_scene_filtered_model", tracked_model)
    assert scene._perpendicular_snap_target() is not None
    scene._pointer_position = tuple(np.asarray(scene._pointer_position) + (1, 0))
    assert scene._perpendicular_snap_target() is not None
    scene.plotter.renderer.GetActiveCamera().Dolly(1.1)
    assert scene._perpendicular_snap_target() is not None
    assert len(rebuilds) == 1
    scene._model.add_scene_view("Floor")
    scene._model.set_scene_members_hidden({"existing"}, True)
    assert scene._perpendicular_snap_target() is None
    scene._model.set_scene_members_hidden({"existing"}, False)
    assert scene._perpendicular_snap_target() is not None
    scene._model.remove_bar("existing")
    assert scene._perpendicular_snap_target() is None


def test_measurement_does_not_capture_an_occluded_perpendicular(scene, monkeypatch):
    scene.set_measurement_mode(True)
    scene.set_measurement_start((0, 4, 0))
    point_at(scene, (0, 0, 0))
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, *_args, **_kwargs: np.zeros(len(screens), bool))
    assert scene._perpendicular_snap_target() is None


def test_midpoint_capture_and_marker_refer_to_the_actual_final_node(scene):
    scene.set_member_placement_mode(True, point_mode="midpoint")
    scene.set_member_preview_start((0, 4, 0))
    point_at(scene, (0, 0, 0))
    assert scene._perpendicular_snap_target() is None  # a pair must first be started
    scene._member_midpoint_anchor = np.asarray((-2, 0, 0))
    point_at(scene, (2, 0, 0))
    target, kind = scene._placement_target(np.asarray((2.02, 0, 0)))
    assert kind == "perpendicular"
    np.testing.assert_allclose(target, (2, 0, 0))
    np.testing.assert_allclose((target + scene._member_midpoint_anchor) / 2, (0, 0, 0))
    scene._position_snap_marker(target, kind)
    screen, _visible = scene._world_to_screen(np.zeros(3))
    assert abs(scene._snap_marker.geometry().center().x() - screen[0]) <= 1
    scene._update_member_preview(target)
    mesh = scene._member_preview_actor.GetMapper().GetInput()
    np.testing.assert_allclose(mesh.GetPoint(1), (0, 0, 0))


def test_settings_use_the_new_perpendicular_asset():
    option = next(item for item in ProgramSettingsDialog._snap_options if item[0] == "perpendicular")
    assert option == ("perpendicular", "Perpendicular", "perpendicular.svg")
