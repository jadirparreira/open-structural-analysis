import numpy as np
import pytest

from osa.model import ReferenceAxis, StructuralModel
from osa.rendering.reference_axes_renderer import ReferenceAxesRenderer


def test_reference_axes_reject_duplicate_labels_or_values_within_one_direction():
    model = StructuralModel()

    with pytest.raises(ValueError, match="repetidos"):
        model.set_reference_axes({"X": (ReferenceAxis("A", 5.0), ReferenceAxis("A", 10.0))})

    with pytest.raises(ValueError, match="repetidos"):
        model.set_reference_axes({"Y": (ReferenceAxis("A", 5.0), ReferenceAxis("B", 5.0))})

    model.set_reference_axes({
        "X": (ReferenceAxis("A", 5.0),),
        "Y": (ReferenceAxis("A", 5.0),),
    })
    assert model.axes["X"] == (ReferenceAxis("A", 5.0),)
    assert model.axes["Y"] == (ReferenceAxis("A", 5.0),)


def test_reference_axis_renderer_draws_x_and_y_at_z_zero_but_not_z_axes():
    renderer = ReferenceAxesRenderer()
    mesh = renderer.build({
        "X": (ReferenceAxis("A", 5.0),),
        "Y": (ReferenceAxis("1", 2.0),),
        "Z": (ReferenceAxis("NIVEL", 3.0),),
    }, (-5.0, 15.0, -5.0, 25.0))

    assert mesh.n_cells > 2
    assert np.allclose(mesh.points[:, 2], 0.0)
    assert np.any(np.isclose(mesh.points[:, 0], 5.0))
    assert np.any(np.isclose(mesh.points[:, 1], 2.0))

    label_positions, labels = renderer.labels({
        "X": (ReferenceAxis("A", 5.0),),
        "Y": (ReferenceAxis("1", 2.0),),
    }, (-5.0, 15.0, -5.0, 25.0))
    np.testing.assert_allclose(label_positions, ((5.45, -3.0, 0.0), (5.45, 7.0, 0.0),
                                                 (0.0, 2.45, 0.0), (10.0, 2.45, 0.0)))
    assert labels == ("A", "A", "1", "1")


def test_reference_axis_elevation_moves_lines_and_labels_together():
    renderer = ReferenceAxesRenderer()
    axes = {"X": (ReferenceAxis("A", 5.0),)}
    renderer.mesh = renderer.build(axes, (-5.0, 5.0, -5.0, 5.0))

    renderer.set_elevation(12.0)
    positions, _labels = renderer.labels(axes, (-5.0, 5.0, -5.0, 5.0), elevation=12.0)

    assert np.allclose(renderer.mesh.points[:, 2], 12.0)
    assert np.allclose(positions[:, 2], 12.0)


def test_reference_axes_renderer_uses_x_and_z_on_xz_plane():
    renderer = ReferenceAxesRenderer()
    axes = {
        "X": (ReferenceAxis("1", 5.0),),
        "Y": (ReferenceAxis("A", 2.0),),
        "Z": (ReferenceAxis("N1", 8.0),),
    }

    mesh = renderer.build(axes, (-5.0, 15.0, -5.0, 25.0), plane="XZ", offset=2.0)

    assert np.allclose(mesh.points[:, 1], 2.0)
    assert np.any(np.isclose(mesh.points[:, 0], 5.0))
    assert np.any(np.isclose(mesh.points[:, 2], 8.0))
    positions, labels = renderer.labels(axes, (-5.0, 15.0, -5.0, 25.0), plane="XZ", offset=2.0)
    np.testing.assert_allclose(positions, ((5.45, 2.0, 3.0), (5.45, 2.0, 13.0),
                                           (0.0, 2.0, 8.45), (10.0, 2.0, 8.45)))
    assert labels == ("1", "1", "N1", "N1")


def test_reference_axes_renderer_uses_y_and_z_on_yz_plane():
    renderer = ReferenceAxesRenderer()
    axes = {
        "X": (ReferenceAxis("1", 2.0),),
        "Y": (ReferenceAxis("A", 5.0),),
        "Z": (ReferenceAxis("N1", 8.0),),
    }

    mesh = renderer.build(axes, (-5.0, 15.0, -5.0, 25.0), plane="YZ", offset=2.0)

    assert np.allclose(mesh.points[:, 0], 2.0)
    assert np.any(np.isclose(mesh.points[:, 1], 5.0))
    assert np.any(np.isclose(mesh.points[:, 2], 8.0))
    positions, labels = renderer.labels(axes, (-5.0, 15.0, -5.0, 25.0), plane="YZ", offset=2.0)
    np.testing.assert_allclose(positions, ((2.0, 5.45, 3.0), (2.0, 5.45, 13.0),
                                           (2.0, 0.0, 8.45), (2.0, 10.0, 8.45)))
    assert labels == ("A", "A", "N1", "N1")
