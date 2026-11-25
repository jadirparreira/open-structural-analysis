import numpy as np
import pytest

from osa.model import StructuralModel
from osa.rendering.plate_connection_symbols import plate_connection_symbols


def edge_model(state, *, vertical=False):
    contour = ((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0))
    if vertical:
        contour = tuple((x, z, y) for x, y, z in contour)
    model = StructuralModel()
    plate = model.add_plate(contour, edge_connections=((0, state),))
    model.add_bar("B1", *plate.vertex_nodes[:2])
    return model, plate


@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("solid", [False, True])
def test_supported_dashes_follow_the_edge_in_the_plate_plane(vertical, solid):
    model, plate = edge_model("supported", vertical=vertical)
    mesh = plate_connection_symbols(model, plate, solid=solid)
    assert mesh.n_lines > 1
    assert mesh.n_verts == 0
    normal_axis = 1 if vertical else 2
    assert np.ptp(mesh.points[:, normal_axis]) < 1e-12
    if solid:
        assert mesh.points[:, normal_axis].min() > plate.thickness_mm / 2000
    segments = mesh.points[mesh.lines.reshape(-1, 3)[:, 1:]]
    for start, end in segments:
        assert end[0] > start[0]
        np.testing.assert_allclose((end - start)[1:], 0, atol=1e-12)
    assert np.all(segments[1:, 0, 0] > segments[:-1, 1, 0])


def test_fixed_line_is_continuous_and_free_edges_have_no_marks():
    model, plate = edge_model("fixed")
    mesh = plate_connection_symbols(model, plate)
    assert mesh.n_lines == 1
    assert mesh.lines[0] == 2
    assert np.ptp(mesh.points[:, 2]) < 1e-12
    for start, end in mesh.points[mesh.lines.reshape(-1, 3)[:, 1:]]:
        assert end[0] > start[0]
        np.testing.assert_allclose((end - start)[1:], 0, atol=1e-12)
    model.update_plate(plate.name, edge_connections=((0, "free"),))
    assert plate_connection_symbols(model, model.plates[plate.name]).n_cells == 0
    model.remove_bar("B1")
    assert plate_connection_symbols(model, plate).n_cells == 0


def test_partial_edge_support_limits_marks_to_the_bar_span():
    model, plate = edge_model("supported")
    model.add_node("N10", 1, 0, 0)
    model.add_node("N11", 2, 0, 0)
    model.update_bar("B1", "N10", "N11")
    mesh = plate_connection_symbols(model, plate)
    assert mesh.points[:, 0].min() >= 1
    assert mesh.points[:, 0].max() <= 2
