import numpy as np
import vtk

from osa.rendering.label_overlay import project_world_to_screen
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
