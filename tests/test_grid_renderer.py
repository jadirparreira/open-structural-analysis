from types import SimpleNamespace

import numpy as np

from osa.model import ReferenceAxis, StructuralModel
from osa.rendering.grid_renderer import GridRenderer


def test_grid_expands_five_metres_past_the_structural_xy_footprint():
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 10.0, 20.0, 5.0)

    grid = GridRenderer()
    grid.update(model.nodes.values())

    np.testing.assert_allclose(grid.mesh.bounds, (-5.0, 15.0, -5.0, 25.0, 0.0, 0.0))
    rgba = grid.mesh.point_data["rgba"]
    assert rgba.shape == (grid.mesh.n_points, 4)
    assert rgba[:, 3].min() == 0
    assert rgba[:, 3].max() == 255


def test_empty_model_keeps_the_default_ten_metre_grid_at_the_origin():
    grid = GridRenderer()
    grid.update(())

    np.testing.assert_allclose(grid.mesh.bounds, (-5.0, 5.0, -5.0, 5.0, 0.0, 0.0))


def test_grid_uses_axis_positions_without_using_their_line_extensions():
    grid = GridRenderer()
    grid.update((), {
        "X": (ReferenceAxis("A", 20.0),),
        "Y": (ReferenceAxis("1", 10.0),),
    })

    np.testing.assert_allclose(grid.mesh.bounds, (15.0, 25.0, 5.0, 15.0, 0.0, 0.0))


def test_grid_stays_registered_to_the_origin_and_uses_one_metre_steps():
    model = StructuralModel()
    model.add_node("N1", 0.2, 0.3, 0.0)
    model.add_node("N2", 10.2, 20.3, 5.0)

    grid = GridRenderer()
    grid.update(model.nodes.values())

    np.testing.assert_allclose(grid.mesh.bounds, (-5.0, 16.0, -5.0, 26.0, 0.0, 0.0))
    points = grid.mesh.points
    assert np.any(np.all(np.isclose(points[:, :2], (0.0, 0.0)), axis=1))
    np.testing.assert_allclose(np.diff(np.unique(points[:, 0])), 1.0)
    np.testing.assert_allclose(np.diff(np.unique(points[:, 1])), 1.0)


def test_grid_window_moves_only_when_model_crosses_a_full_metre():
    nodes = [
        SimpleNamespace(x=0.2, y=0.2, z=0.0),
        SimpleNamespace(x=10.2, y=10.2, z=0.0),
    ]

    grid = GridRenderer()
    grid.update(nodes)
    initial_bounds = grid.bounds

    nodes[0].x = 0.8
    nodes[0].y = 0.8
    grid.update(nodes)
    assert grid.bounds == initial_bounds

    nodes[0].x = 1.2
    nodes[0].y = 1.2
    grid.update(nodes)
    assert grid.bounds == (-4.0, 16.0, -4.0, 16.0)


def test_grid_elevation_changes_without_rebuilding_the_xy_footprint():
    grid = GridRenderer()
    grid.update(())
    bounds = grid.mesh.bounds

    grid.set_elevation(8.0)

    np.testing.assert_allclose(grid.mesh.bounds, (*bounds[:4], 8.0, 8.0))


def test_grid_xz_uses_x_and_z_axis_positions():
    grid = GridRenderer()
    grid.update((), {
        "X": (ReferenceAxis("1", 10.0),),
        "Y": (ReferenceAxis("A", 99.0),),
        "Z": (ReferenceAxis("N1", 20.0),),
    }, plane="XZ", offset=3.0)

    np.testing.assert_allclose(grid.bounds, (5.0, 15.0, 15.0, 25.0))
    np.testing.assert_allclose(grid.mesh.bounds, (5.0, 15.0, 3.0, 3.0, 15.0, 25.0))


def test_grid_yz_uses_y_and_z_axis_positions():
    grid = GridRenderer()
    grid.update((), {
        "X": (ReferenceAxis("1", 99.0),),
        "Y": (ReferenceAxis("A", 20.0),),
        "Z": (ReferenceAxis("N1", 30.0),),
    }, plane="YZ", offset=4.0)

    np.testing.assert_allclose(grid.bounds, (15.0, 25.0, 25.0, 35.0))
    np.testing.assert_allclose(grid.mesh.bounds, (4.0, 4.0, 15.0, 25.0, 25.0, 35.0))
