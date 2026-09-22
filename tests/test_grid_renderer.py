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

    np.testing.assert_allclose(grid.mesh.bounds, (5.0, 15.0, 15.0, 25.0, 0.0, 0.0))


def test_grid_elevation_changes_without_rebuilding_the_xy_footprint():
    grid = GridRenderer()
    grid.update(())
    bounds = grid.mesh.bounds

    grid.set_elevation(8.0)

    np.testing.assert_allclose(grid.mesh.bounds, (*bounds[:4], 8.0, 8.0))
