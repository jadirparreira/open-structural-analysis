import pytest
from osa.model import StructuralModel
from osa.services.action_service import ActionService


@pytest.mark.parametrize('start,end,blocked', [
    ((0, 0, 0), (4, 0, 0), True),
    ((4, 0, 0), (0, 0, 0), True),
    ((-1, 0, 0), (5, 0, 0), True),
    ((1, 0, 0), (3, 0, 0), True),
    ((0, 0, 1), (4, 0, 1), False),
    ((0, 0, 0), (0, -2, 0), False),
])
def test_only_collinear_overlapping_bar_blocks_edge_action(start, end, blocked):
    model = StructuralModel()
    plate = model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))
    for name, point in (('N10', start), ('N11', end)):
        existing = next((node.name for node in model.nodes.values() if (node.x, node.y, node.z) == point), None)
        if existing is None:
            model.add_node(name, *point)
    names = [next(node.name for node in model.nodes.values() if (node.x, node.y, node.z) == point) for point in (start, end)]
    model.add_bar('B8', *names)
    service = ActionService(model)
    if blocked:
        with pytest.raises(ValueError, match='B8'):
            service.add_plate_edge_action(plate.name, 0, 'force', 'Z', -2, -2, 'Caso')
        assert not model.actions
    else:
        assert service.add_plate_edge_action(plate.name, 0, 'force', 'Z', -2, -2, 'Caso')
