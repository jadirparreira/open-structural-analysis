from osa.commands import CommandSession
from osa.model import StructuralModel
from osa.services import ModelService


def session():
    model = StructuralModel()
    return model, CommandSession(ModelService(model))


def test_node_command_flow():
    model, commands = session()
    assert commands.submit("node").message == "Informe as coordenadas do nó em X,Y,Z"
    response = commands.submit("0,5,8")
    assert response.model_changed
    assert (model.nodes["N1"].x, model.nodes["N1"].y, model.nodes["N1"].z) == (0, 5, 8)


def test_member_names_are_case_insensitive():
    model, commands = session()
    model.add_node("N1", 0, 0, 0); model.add_node("N2", 1, 0, 0)
    commands.submit("member")
    assert commands.submit("n1,N2").model_changed
    assert model.bars["B1"].start_node == "N1"


def test_portico_does_not_leave_a_pending_command():
    model, commands = session()
    assert commands.submit("portico").model_changed
    assert commands.pending is None
    assert len(model.nodes) == 220
    assert len(model.bars) == 415

    coordinates = {(node.x, node.y, node.z) for node in model.nodes.values()}
    assert coordinates == {
        *((x, y, 0.0) for x in (0.0, 10.0) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((x, y, z) for x in (index * 0.5 for index in range(21))
          for y in (0.0, 5.0, 10.0, 15.0, 20.0) for z in (6.0, 6.5)),
    }
    assert all(
        node.supports[:3] == (True, True, True)
        for node in model.nodes.values()
        if node.z == 0.0
    )
    assert all(
        member.material == "Concreto Estrutural"
        and member.section == "Retangular"
        and member.profile == "R 250 x 500"
        and member.geometry_dict() == {"b": 250.0, "h": 500.0}
        for member in list(model.bars.values())[:10]
    )
    assert all(
        {member.start_node, member.end_node}
        and model.nodes[member.start_node].x == model.nodes[member.end_node].x
        and model.nodes[member.start_node].y == model.nodes[member.end_node].y
        and {model.nodes[member.start_node].z, model.nodes[member.end_node].z} == {0.0, 6.0}
        for member in list(model.bars.values())[:10]
    )

    truss_members = list(model.bars.values())[10:]
    assert len(truss_members) == 405
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "U Formado"
        and member.profile == "U 100 x 50 x 3"
        and member.geometry_dict() == {"d": 100.0, "bf": 50.0, "t": 3.0}
        for member in truss_members
    )

    diagonals = [
        member for member in truss_members
        if model.nodes[member.start_node].x != model.nodes[member.end_node].x
        and model.nodes[member.start_node].z != model.nodes[member.end_node].z
    ]
    assert len(diagonals) == 100
    assert all(
        abs(abs(model.nodes[member.start_node].x - model.nodes[member.end_node].x) - 0.5) < 1e-9
        and abs(abs(model.nodes[member.start_node].z - model.nodes[member.end_node].z) - 0.5) < 1e-9
        for member in diagonals
    )
