import numpy as np
import vtk

from osa.rendering.label_overlay import project_world_to_screen
from osa.rendering.navigation_widget import CameraCubeWidget
from osa.rendering.scene_batched import StructureScene


def test_label_projection_is_vectorized_and_uses_qt_screen_coordinates():
    positions = np.asarray([
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (-1.0, -1.0, 0.0),
        (2.0, 0.0, 0.0),
    ])

    screen, visible = project_world_to_screen(positions, np.eye(4), 100, 80)

    np.testing.assert_allclose(
        screen[:3],
        np.asarray(((50.0, 40.0), (100.0, 0.0), (0.0, 80.0))),
    )
    assert visible.tolist() == [True, True, True, False]


def test_offscreen_endpoints_remain_projectable_for_crossing_members():
    positions = np.asarray([
        (-2.0, 0.0, 0.0),
        (2.0, 0.0, 0.0),
    ])

    screen, visible = project_world_to_screen(
        positions, np.eye(4), 100, 80, clip_to_viewport=False,
    )

    assert visible.tolist() == [True, True]
    np.testing.assert_allclose(screen, np.asarray(((-50.0, 40.0), (150.0, 40.0))))
    assert StructureScene._distance_to_segment_2d(
        np.asarray((50.0, 40.0)), screen[0], screen[1],
    ) == 0.0


def test_qt_pointer_is_normalized_to_the_current_vtk_render_buffer():
    assert StructureScene._qt_to_vtk_position(
        (0.0, 0.0), (100, 80), (200, 160),
    ) == (0.0, 159.0)
    assert StructureScene._qt_to_vtk_position(
        (99.0, 79.0), (100, 80), (200, 160),
    ) == (199.0, 0.0)


def test_navigation_cube_keeps_its_logical_size_when_window_is_restored():
    maximized = CameraCubeWidget._viewport_for_render_size((2048, 1200), 1.5)
    restored = CameraCubeWidget._viewport_for_render_size((1200, 900), 1.5)

    assert maximized == (0.02490234375, 0.0575, 0.15380859375, 0.195)
    assert restored == (0.0425, 0.07666666666666666, 0.2625, 0.26)


def test_default_isometric_view_matches_structural_axis_convention():
    camera = vtk.vtkCamera()
    camera.ParallelProjectionOn()
    camera.SetFocalPoint(0.0, 0.0, 0.0)
    camera.SetPosition(*StructureScene._default_view_direction)
    camera.SetViewUp(*StructureScene._default_view_up)
    vtk_matrix = camera.GetCompositeProjectionTransformMatrix(1.0, -1.0, 1.0)
    matrix = np.asarray([
        [vtk_matrix.GetElement(row, column) for column in range(4)]
        for row in range(4)
    ])
    positions = np.asarray([
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    ])

    screen, _visible = project_world_to_screen(positions, matrix, 100, 100)
    origin, positive_x, positive_y = screen

    assert positive_x[0] > origin[0] and positive_x[1] < origin[1]
    assert positive_y[0] < origin[0] and positive_y[1] < origin[1]
