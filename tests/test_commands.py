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
    assert len(model.nodes) == 8
    assert len(model.bars) == 8
    assert all(model.nodes[f"N{i}"].supports[:3] == (True, True, True) for i in range(1, 5))
