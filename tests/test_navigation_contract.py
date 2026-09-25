"""Navigation invariants for the structural viewport."""

from __future__ import annotations

import os

import numpy as np
import pytest

# Qt needs an explicit headless backend in the test runner.  This is set before
# the first QApplication is created and does not affect a normal desktop run.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.rendering.scene_batched import StructureScene


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _camera_pose(scene: StructureScene) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    camera = scene.plotter.renderer.GetActiveCamera()
    return (
        np.asarray(camera.GetPosition(), dtype=float),
        np.asarray(camera.GetFocalPoint(), dtype=float),
        np.asarray(camera.GetViewUp(), dtype=float),
        float(camera.GetParallelScale()),
    )


def _assert_same_pose(before, after) -> None:
    for before_value, after_value in zip(before[:3], after[:3]):
        assert np.allclose(before_value, after_value)
    assert np.isclose(before[3], after[3])


def _sample_model() -> StructuralModel:
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 4.0, 0.0, 0.0)
    model.add_node("N3", 4.0, 4.0, 3.0)
    model.add_bar("B1", "N1", "N2")
    model.add_bar("B2", "N2", "N3")
    return model


def test_model_refresh_and_reference_planes_preserve_camera_pose(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(10.0, 8.0, 7.0)
    camera.SetFocalPoint(1.0, 2.0, 0.5)
    camera.SetViewUp(0.0, 0.0, 1.0)
    camera.SetParallelScale(6.0)

    before = _camera_pose(scene)
    scene.render_model(_sample_model())
    _assert_same_pose(before, _camera_pose(scene))
    assert scene.plotter.camera_set
    assert scene.plotter.iren.style.GetClassName() == "vtkInteractorStyleTerrain"

    scene.set_reference_plane_mode("XZ")
    _assert_same_pose(before, _camera_pose(scene))


def test_wheel_zoom_changes_scale_without_reframing(qt_app):
    scene = StructureScene()
    scene.render_model(_sample_model(), preserve_camera=False)
    before = _camera_pose(scene)
    interactor = scene.plotter.iren.interactor
    interactor.SetEventInformation(400, 300, 0, 0, "a", 0, None)
    interactor.MouseWheelForwardEvent()
    after = _camera_pose(scene)

    for before_value, after_value in zip(before[:3], after[:3]):
        assert np.allclose(before_value, after_value)
    assert after[3] < before[3]
    assert scene.plotter.camera_set


def test_hidden_construction_plane_is_not_a_snap_target(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene._pointer_position = (100.0, 100.0)
    grid_point = np.asarray((1.0, 2.0, 0.0))
    monkeypatch.setattr(
        scene,
        "_nearest_grid_candidate",
        lambda _position: (grid_point, 0.0),
    )

    snap = scene._snap_position(np.zeros(3))
    assert snap is not None
    assert snap[1] == "grid"
    assert np.allclose(snap[0], grid_point)

    scene.set_grid_visible(False)

    assert scene._snap_position(np.zeros(3)) is None
    assert scene._snap_to_grid(np.zeros(3)) is None


@pytest.mark.parametrize(
    ("mode", "constrained_axis"),
    [("XY", 2), ("XZ", 1), ("YZ", 0)],
)
def test_second_member_point_stays_on_first_point_plane(
    qt_app, monkeypatch, mode, constrained_axis,
):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode(mode)
    scene.set_member_preview_start((10.0, 20.0, 30.0))
    monkeypatch.setattr(scene, "_snap_position", lambda _position: None)

    target, snap_kind = scene._placement_target(np.asarray((1.0, 2.0, 3.0)))

    assert snap_kind is None
    assert target[constrained_axis] == (10.0, 20.0, 30.0)[constrained_axis]


def test_second_member_point_keeps_snap_coordinates(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode("XY")
    scene.set_member_preview_start((10.0, 20.0, 30.0))
    snapped = np.asarray((4.0, 5.0, 6.0))
    monkeypatch.setattr(scene, "_snap_position", lambda _position: (snapped, "endpoint"))

    target, snap_kind = scene._placement_target(np.asarray((1.0, 2.0, 3.0)))

    assert snap_kind == "endpoint"
    assert np.allclose(target, snapped)


@pytest.mark.parametrize(
    ("mode", "normal_axis"),
    [("XY", 2), ("XZ", 1), ("YZ", 0)],
)
def test_member_point_can_snap_to_perpendicular_guide(
    qt_app, monkeypatch, mode, normal_axis,
):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode(mode)
    scene.set_member_preview_start((10.0, 20.0, 30.0))
    first_point = np.asarray((10.0, 20.0, 30.0))
    scene._pointer_position = (100.0, 100.0 + (first_point[normal_axis] + 2.0) * 5.0)
    monkeypatch.setattr(scene, "_snap_position", lambda _position: None)

    def project(point):
        # Give the normal a visible vertical screen direction in every plane.
        return np.asarray((100.0, 100.0 + point[normal_axis] * 5.0)), True

    monkeypatch.setattr(scene, "_world_to_screen", project)
    target, snap_kind = scene._placement_target(np.asarray((1.0, 2.0, 3.0)))

    assert snap_kind == "perpendicular"
    assert np.isclose(target[normal_axis], first_point[normal_axis] + 2.0)
    plane_axes = [axis for axis in range(3) if axis != normal_axis]
    assert np.allclose(target[plane_axes], np.asarray((10.0, 20.0, 30.0))[plane_axes])


def test_perpendicular_guide_respects_snap_toggle(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_preview_start((10.0, 20.0, 30.0))
    scene._pointer_position = (100.0, 250.0)
    monkeypatch.setattr(scene, "_snap_position", lambda _position: None)
    monkeypatch.setattr(
        scene,
        "_world_to_screen",
        lambda point: (np.asarray((100.0, point[2] * 5.0)), True),
    )

    scene.set_snap_enabled(False)

    target, snap_kind = scene._placement_target(np.asarray((1.0, 2.0, 3.0)))
    assert snap_kind is None
    assert target[2] == 30.0


def test_perpendicular_guide_wins_over_ambiguous_grid_projection(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_preview_start((2.0, 2.0, 0.0))
    scene._pointer_position = (100.0, 200.0)
    grid_point = np.asarray((0.0, 0.0, 0.0))
    perpendicular_point = np.asarray((2.0, 2.0, 5.0))
    monkeypatch.setattr(
        scene,
        "_snap_position",
        lambda _position: (grid_point, "grid"),
    )
    monkeypatch.setattr(
        scene,
        "_placement_guide_target",
        lambda: (perpendicular_point, "perpendicular"),
    )

    target, snap_kind = scene._placement_target(np.zeros(3))

    assert snap_kind == "perpendicular"
    assert np.allclose(target, perpendicular_point)


def test_perpendicular_guide_is_dashed_and_fades_like_grid(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((2.0, 2.0, 0.0))
    scene._update_perpendicular_guide()

    mesh = scene._perpendicular_guide_actor.GetMapper().GetInput()
    rgba = np.asarray(mesh.GetPointData().GetArray("rgba"))

    assert mesh.GetNumberOfLines() > 10
    assert rgba.shape[1] == 4
    assert np.all(rgba[:, :3] == np.asarray((208, 215, 222)))
    assert rgba[:, 3].min() < rgba[:, 3].max()


def test_orthogonal_guides_are_solid_and_faded(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((2.0, 2.0, 0.0))
    scene._update_orthogonal_guide()

    mesh = scene._orthogonal_guide_actor.GetMapper().GetInput()
    rgba = np.asarray(mesh.GetPointData().GetArray("rgba"))

    assert mesh.GetNumberOfLines() == 2
    assert np.all(rgba[:, :3] == np.asarray((208, 215, 222)))
    assert rgba[:, 3].min() < rgba[:, 3].max()


def test_orthogonal_guide_snaps_along_active_plane_axis(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode("XY")
    scene.set_member_preview_start((2.0, 2.0, 0.0))
    scene._pointer_position = (30.0, 10.0)
    monkeypatch.setattr(
        scene,
        "_world_to_screen",
        lambda point: (np.asarray((point[0] * 5.0, point[1] * 5.0)), True),
    )

    target = scene._orthogonal_snap_target()

    assert target is not None
    assert np.allclose(target, np.asarray((6.0, 2.0, 0.0)))


def test_perpendicular_guide_has_five_units_on_each_side(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((2.0, 2.0, 0.0))

    direction = scene._perpendicular_direction()
    length = scene._perpendicular_guide_length()
    mesh = scene._perpendicular_guide_mesh(
        scene._member_preview_start, direction, length,
    )
    points = np.asarray(mesh.points)
    distances = np.dot(points - np.asarray((2.0, 2.0, 0.0)), direction)

    assert np.isclose(distances.min(), -5.0)
    assert np.isclose(distances.max(), 5.0)


def test_perpendicular_snap_extends_to_ten_units_beyond_visible_guide(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((2.0, 2.0, 0.0))
    monkeypatch.setattr(scene, "_snap_position", lambda _position: None)
    monkeypatch.setattr(
        scene,
        "_world_to_screen",
        lambda point: (np.asarray((100.0, point[2] * 5.0)), True),
    )

    scene._pointer_position = (100.0, 40.0)
    upper_target = scene._perpendicular_snap_target()
    scene._pointer_position = (100.0, 55.0)
    outside_target = scene._perpendicular_snap_target()

    assert upper_target is not None
    assert np.isclose(upper_target[2], 8.0)
    assert outside_target is None


@pytest.mark.parametrize(
    ("mode", "endpoint", "expected"),
    [
        ("XY", (3.0, 3.0, 0.0), 45.0),
        ("XZ", (3.0, 0.0, 1.0), 45.0),
        ("YZ", (0.0, 3.0, 1.0), 45.0),
    ],
)
def test_preview_angle_is_measured_in_active_plane(qt_app, mode, endpoint, expected):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode(mode)
    scene.set_member_preview_start((2.0, 2.0, 0.0))

    assert np.isclose(scene._preview_angle_degrees(np.asarray(endpoint)), expected)


def test_preview_angle_is_hidden_for_perpendicular_member(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode("XY")
    scene.set_member_preview_start((2.0, 2.0, 0.0))

    assert scene._preview_angle_degrees(np.asarray((2.0, 2.0, 5.0))) is None


def test_coordinate_and_angle_readouts_share_width(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())

    assert scene._coordinate_readout.width() == scene._angle_readout.width()
    assert [label.text() for label in scene._coordinate_value_labels] == [
        "0.000 m", "0.000 m", "0.000 m",
    ]
    assert all(label.width() == 78 for label in scene._coordinate_value_labels)
    assert scene._angle_editor.width() == 78
    assert scene._coordinate_readout.width() < 142


def test_tab_cycles_coordinate_fields_and_wraps_without_angle(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene._last_display_position = np.asarray((1.0, 2.0, 3.0))

    scene._cycle_coordinate_edit()
    assert scene._manual_edit_index == 0
    scene._coordinate_value_labels[0].setText("5")
    scene._cycle_coordinate_edit()
    assert scene._manual_edit_target[0] == 5.0
    assert scene._manual_edit_index == 1
    scene._coordinate_value_labels[1].setText("7")
    scene._cycle_coordinate_edit()
    scene._coordinate_value_labels[2].setText("9")
    scene._cycle_coordinate_edit()

    assert np.allclose(scene._manual_edit_target, np.asarray((5.0, 7.0, 9.0)))
    assert scene._manual_edit_index == 0


def test_node_placement_has_only_coordinate_fields_and_emits_one_point(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_node_placement_mode(True)
    scene._last_display_position = np.asarray((1.0, 2.0, 3.0))
    points: list[object] = []
    scene.placement_point_clicked.connect(points.append)

    assert scene._placement_active()
    assert scene._member_preview_start is None
    assert scene._editable_coordinate_fields() == scene._coordinate_value_labels

    scene._cycle_coordinate_edit()
    scene._coordinate_value_labels[0].setText("4")
    scene._finish_coordinate_edit()
    scene._emit_member_placement_point()

    assert points == [(4.0, 2.0, 3.0)]
    assert scene._manual_edit_target is None


def test_tab_reaches_angle_and_manual_mouse_motion_cancels_edit(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_reference_plane_mode("XY")
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((0.0, 0.0, 0.0))
    scene._last_display_position = np.asarray((1.0, 1.0, 0.0))
    for editor, value in zip(scene._coordinate_value_labels, ("1", "1", "0")):
        editor.setText(value)

    for _ in range(4):
        scene._cycle_coordinate_edit()
    assert scene._manual_edit_index == 3
    scene._angle_editor.setText("90")
    scene._finish_coordinate_edit()
    assert np.isclose(scene._preview_angle_degrees(scene._manual_edit_target), 90.0)

    scene._cycle_coordinate_edit()
    assert scene._manual_edit_target is not None
    scene._cancel_coordinate_edit()
    assert scene._manual_edit_target is None
    assert scene._manual_edit_index is None


@pytest.mark.parametrize(
    ("entered", "expected"),
    [("@4", 2.0), ("@-3", -5.0)],
)
def test_relative_coordinate_edit_is_offset_from_member_start(qt_app, entered, expected):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene.set_member_preview_start((-2.0, 1.0, 0.0))
    scene._last_display_position = np.asarray((0.0, 2.0, 0.0))

    scene._cycle_coordinate_edit()
    scene._coordinate_value_labels[0].setText(entered)
    scene._finish_coordinate_edit()

    assert np.isclose(scene._manual_edit_target[0], expected)


def test_second_enter_confirms_the_manually_edited_point(qt_app):
    scene = StructureScene()
    scene.render_model(StructuralModel())
    scene.set_member_placement_mode(True)
    scene._last_display_position = np.asarray((1.0, 2.0, 3.0))
    points: list[object] = []
    scene.placement_point_clicked.connect(points.append)

    scene._cycle_coordinate_edit()
    scene._coordinate_value_labels[0].setText("4")
    scene._finish_coordinate_edit()

    assert points == []
    assert scene._manual_edit_confirmable
    event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.NoModifier,
    )
    assert scene.eventFilter(scene.plotter, event)
    assert points == [(4.0, 2.0, 3.0)]
    assert scene._manual_edit_target is None


def _mouse_event(event_type, x: float, y: float, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        QPointF(x, y),
        QPointF(x, y),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_member_placement_clicks_do_not_consume_revit_orbit_drags(qt_app, monkeypatch):
    scene = StructureScene()
    scene.render_model(_sample_model(), preserve_camera=False)
    scene.set_member_placement_mode(True)
    monkeypatch.setattr(scene._orientation_widget, "is_pointer_over", lambda *_args: False)
    monkeypatch.setattr(
        scene,
        "_placement_world_position",
        lambda: np.asarray((1.0, 2.0, 3.0)),
    )
    points: list[object] = []
    scene.placement_point_clicked.connect(points.append)

    assert not scene.eventFilter(
        scene.plotter,
        _mouse_event(
            QEvent.Type.MouseButtonPress, 100.0, 100.0,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        ),
    )
    assert not scene.eventFilter(
        scene.plotter,
        _mouse_event(
            QEvent.Type.MouseButtonRelease, 100.0, 100.0,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        ),
    )
    qt_app.processEvents()
    assert points == [(1.0, 2.0, 3.0)]

    points.clear()
    scene.eventFilter(
        scene.plotter,
        _mouse_event(
            QEvent.Type.MouseButtonPress, 100.0, 100.0,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        ),
    )
    scene.eventFilter(
        scene.plotter,
        _mouse_event(
            QEvent.Type.MouseMove, 120.0, 100.0,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        ),
    )
    scene.eventFilter(
        scene.plotter,
        _mouse_event(
            QEvent.Type.MouseButtonRelease, 120.0, 100.0,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        ),
    )
    qt_app.processEvents()
    assert points == []


def test_explicit_view_controls_are_the_only_controls_that_reframe(qt_app):
    scene = StructureScene()
    scene.render_model(_sample_model(), preserve_camera=False)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(11.0, 8.0, 7.0)
    camera.SetFocalPoint(1.0, 1.0, 1.0)
    camera.SetViewUp(0.0, 0.0, 1.0)
    camera.SetParallelScale(5.0)
    before_roll = _camera_pose(scene)

    scene._orientation_widget._animation_duration = 0.001
    scene.rotate_camera_clockwise()
    scene._orientation_widget._animate_camera()
    after_roll = _camera_pose(scene)
    assert np.allclose(before_roll[0], after_roll[0])
    assert np.allclose(before_roll[1], after_roll[1])
    assert np.isclose(before_roll[3], after_roll[3])
    assert not np.allclose(before_roll[2], after_roll[2])

    scene.view_isometric()
    assert scene.plotter.camera_set
    scene.reset_camera()
    assert scene.plotter.camera_set
