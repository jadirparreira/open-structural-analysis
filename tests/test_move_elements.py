import pytest

from osa.model import StructuralModel


def test_move_shared_nodes_once_and_follow_connected_members_and_plate():
    model = StructuralModel()
    plate = model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))
    first, second = plate.vertex_nodes[:2]
    model.add_node('N9', -2, 0, 0)
    model.add_bar('B1', first, second)
    model.add_bar('B2', first, 'N9')

    moved = model.move_elements([('node', first), ('bar', 'B1'), ('plate', plate.name)], (0, 0, 2))

    assert len(moved) == 4
    assert model.nodes[first].z == 2
    assert model.nodes['N9'].z == 0
    assert all(point[2] == 2 for point in model.plates[plate.name].contour)
    assert model.bars['B2'].start_node == first


def test_invalid_move_leaves_all_geometry_unchanged():
    model = StructuralModel()
    plate = model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))
    nodes = dict(model.nodes)
    plates = dict(model.plates)
    with pytest.raises(ValueError):
        model.move_elements([('node', plate.vertex_nodes[0])], (0, 0, 1))
    assert model.nodes == nodes
    assert model.plates == plates


def test_move_rigid_bar_with_shared_node_updates_connected_bar_once():
    model = StructuralModel()
    model.add_node('N1', 0, 0, 0)
    model.add_node('N2', 2, 0, 0)
    model.add_node('N3', 4, 0, 0)
    rigid = model.add_rigid_bar('N1', 'N2')
    model.add_bar('B1', 'N2', 'N3')

    moved = model.move_elements([('rigid_bar', rigid.name), ('node', 'N2')], (0, 3, 0))

    assert set(moved) == {'N1', 'N2'}
    assert model.nodes['N1'].y == 3
    assert model.nodes['N2'].y == 3
    assert model.nodes['N3'].y == 0
    assert model.rigid_bars[rigid.name] == rigid
    assert model.bars['B1'].start_node == 'N2'
