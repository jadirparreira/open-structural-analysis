import numpy as np

from osa.rendering.label_overlay import project_world_to_screen


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
