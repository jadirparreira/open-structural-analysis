from osa.commands import CommandSession
from osa.model import StructuralModel
from osa.services.action_service import ActionService
from osa.services import ModelService
from osa.ui.color_palette import MEMBER_COLOR_CELLS


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


def test_load_command_validates_target_before_asking_for_its_type():
    model, commands = session()
    model.add_node("N3", 0, 0, 0)
    model.add_node("N4", 1, 0, 0)
    model.add_bar("B3", "N3", "N4")

    assert commands.submit("load").message == "Informe a identidade do nó ou do membro."
    response = commands.submit("n3")
    assert response.message == "Informe o tipo de ação: Força ou Momento."
    assert commands.pending == "load_type"
    assert commands.load_target == ("node", ("N3",))

    commands.cancel()
    commands.submit("load")
    response = commands.submit("b3")
    assert response.message == "Informe o tipo de ação: Força ou Momento."
    assert commands.load_target == ("member", ("B3",))


def test_load_command_repeats_when_target_does_not_exist():
    model, commands = session()
    commands.submit("load")

    response = commands.submit("N99")

    assert response.level == "error"
    assert response.message == "Não existe nó ou membro chamado 'N99'."
    assert commands.pending == "load_target"
    model.add_node("N99", 0, 0, 0)
    assert commands.submit("N99").message == "Informe o tipo de ação: Força ou Momento."


def test_member_distributed_force_command_flow():
    model, commands = session()
    model.add_node("N3", 0, 0, 0)
    model.add_node("N4", 4, 0, 0)
    model.add_bar("B3", "N3", "N4")

    commands.submit("load")
    commands.submit("B3")
    assert commands.submit("Força").message == "Informe o sistema de direção: Global ou Local."
    assert commands.submit("Global").message == "Informe a direção global: X, Y ou Z."
    assert commands.submit("Y").message == "Informe a força linear no membro (kN/m)."
    response = commands.submit("-2,5;1.25")

    assert response.level == "success"
    assert len(response.distributed_member_forces) == 1
    load = response.distributed_member_forces[0]
    assert load.target == "B3"
    assert load.direction == "Y"
    assert load.initial == -2.5
    assert load.final == 1.25
    assert load.reference == "global"
    assert commands.pending is None


def test_member_distributed_force_can_use_the_local_direction():
    model, commands = session()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 4, 0, 0)
    model.add_bar("B1", "N1", "N2")

    commands.submit("load")
    commands.submit("B1")
    commands.submit("força")
    assert commands.submit("local").message == "Informe a direção local: X, Y ou Z."
    assert commands.submit("Z").message == "Informe a força linear no membro (kN/m)."
    response = commands.submit("1,5")

    load = response.distributed_member_forces[0]
    assert load.direction == "Z"
    assert load.reference == "local"
    assert load.initial == load.final == 1.5


def test_force_replaces_the_same_direction_only_within_its_action():
    model = StructuralModel()
    service = ActionService(model)

    service.add_member_distributed_force("B3", "Y", -2, -2, "Peso próprio")
    service.add_member_distributed_force("B3", "Y", -5, -3, "Peso próprio")
    service.add_member_distributed_force("B3", "Y", -1, -1, "Ação variável")
    service.add_member_distributed_force("B3", "Z", -1, -1, "Peso próprio")

    assert len(model.actions) == 3
    own_weight_y = next(action for action in model.actions.values() if action.load_case == "Peso próprio" and action.kind.endswith("Y"))
    assert own_weight_y.components == (-5.0, -3.0)


def test_member_moment_is_uniform_and_uses_the_selected_local_direction():
    model, commands = session()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 4, 0, 0)
    model.add_bar("B1", "N1", "N2")

    commands.submit("load")
    commands.submit("B1")
    assert commands.submit("Momento").message == "Informe a direção local: X, Y ou Z."
    assert commands.submit("Z").message == "Informe o momento (kNm/m)."
    response = commands.submit("-12,5")

    assert response.level == "success"
    assert len(response.member_moments) == 1
    moment = response.member_moments[0]
    assert moment.target == "B1"
    assert moment.direction == "Z"
    assert moment.value == -12.5
    assert commands.pending is None


def test_load_command_applies_a_variable_force_to_multiple_members():
    model, commands = session()
    for name, x in (("N1", 0), ("N2", 1), ("N3", 2), ("N4", 3), ("N5", 4), ("N6", 5)):
        model.add_node(name, x, 0, 0)
    for name, start, end in (("B1", "N1", "N2"), ("B2", "N3", "N4"), ("B3", "N5", "N6")):
        model.add_bar(name, start, end)

    commands.submit("load")
    commands.submit("b1,B2,b3")
    commands.submit("força")
    commands.submit("global")
    commands.submit("Z")
    response = commands.submit("1,25;3.4")

    assert [load.target for load in response.distributed_member_forces] == ["B1", "B2", "B3"]
    assert all((load.initial, load.final) == (1.25, 3.4) for load in response.distributed_member_forces)


def test_load_command_repeats_when_nodes_and_members_are_mixed():
    model, commands = session()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")
    commands.submit("load")

    response = commands.submit("N1,B1")

    assert response.level == "error"
    assert response.message == "Os elementos informados devem ser todos nós ou todos membros."
    assert commands.pending == "load_target"
    assert commands.submit("N1,N2").message == "Informe o tipo de ação: Força ou Momento."


def test_load_command_applies_a_point_force_to_multiple_nodes():
    model, commands = session()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)

    commands.submit("load")
    commands.submit("N1,n2")
    commands.submit("força")
    assert commands.submit("X").message == "Informe a força no nó (kN)."
    response = commands.submit("-12,5")

    assert [(force.target, force.direction, force.value) for force in response.node_forces] == [
        ("N1", "X", -12.5), ("N2", "X", -12.5),
    ]


def test_load_command_applies_a_node_moment_in_the_global_direction():
    model, commands = session()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)

    commands.submit("load")
    commands.submit("N1,n2")
    assert commands.submit("momento").message == "Informe a direção global: X, Y ou Z."
    assert commands.submit("Z").message == "Informe o momento no nó (kNm)."
    response = commands.submit("-8,5")

    assert [(moment.target, moment.direction, moment.value) for moment in response.node_moments] == [
        ("N1", "Z", -8.5), ("N2", "Z", -8.5),
    ]


def test_member_moment_replaces_only_the_previous_moment_in_same_action_and_direction():
    model = StructuralModel()
    service = ActionService(model)

    service.add_member_distributed_force("B1", "X", 1, 1, "Peso próprio")
    service.add_member_moment("B1", "X", 10, "Peso próprio")
    service.add_member_moment("B1", "X", -8, "Peso próprio")
    service.add_member_moment("B1", "Y", 4, "Peso próprio")

    assert len(model.actions) == 3
    moment = next(action for action in model.actions.values() if action.kind == "member_moment_X")
    assert moment.components == (-8.0,)


def test_galpao_does_not_leave_a_pending_command():
    model, commands = session()
    assert commands.submit("galpao").model_changed
    assert commands.pending is None
    assert len(model.nodes) == 408
    assert len(model.bars) == 839
    available_colors = {color for color, _, _ in MEMBER_COLOR_CELLS}

    def assert_member_color(members, color):
        assert members
        assert {member.color for member in members} == {color}
        assert color in available_colors

    coordinates = {(node.x, node.y, node.z) for node in model.nodes.values()}
    assert coordinates == {
        *((x, y, 0.0) for x in (0.0, 12.0) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((x, y, 3.0) for x in (0.0, 12.0) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((-0.4, y, 3.04) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((-2.0, y, 3.2) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((x, start_y + 5.0 * part / 3.0, z)
          for x, z in ((-0.4, 3.04), (-2.0, 3.2))
          for start_y in (0.0, 5.0, 10.0, 15.0)
          for part in (1, 2)),
        *((index * 0.5, y, 6.0)
          for index in range(25) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((index * 0.5, y, 6.5 + 0.05 * min(index * 0.5, 12.0 - index * 0.5))
          for index in range(25) for y in (0.0, 5.0, 10.0, 15.0, 20.0)),
        *((float(x), start_y + 5.0 * part / 3.0, 6.5 + 0.05 * min(x, 12.0 - x))
          for x in range(0, 13, 2)
          for start_y in (0.0, 5.0, 10.0, 15.0)
          for part in (1, 2)),
        *((float(x), start_y + 5.0 * fraction, 6.5 + 0.05 * min(x, 12.0 - x))
          for x in range(0, 13, 2)
          for start_y in (0.0, 5.0, 10.0, 15.0)
          for fraction in (0.12, 0.88)),
    }
    assert all(
        node.supports[:3] == (True, True, True)
        for node in model.nodes.values()
        if node.z == 0.0
    )
    concrete_members = [member for member in model.bars.values()
                        if member.material == "Concreto Estrutural"]
    assert len(concrete_members) == 44
    assert all(
        member.section == "Retangular"
        for member in concrete_members
    )
    column_segments = [
        member for member in concrete_members
        if model.nodes[member.start_node].x == model.nodes[member.end_node].x
        and model.nodes[member.start_node].y == model.nodes[member.end_node].y
    ]
    longitudinal_beams = [member for member in concrete_members if member not in column_segments]
    assert len(column_segments) == 20
    assert len(longitudinal_beams) == 24
    assert all(
        member.profile == "R 250 x 500"
        and member.geometry_dict() == {"b": 250.0, "h": 500.0}
        for member in column_segments
    )
    assert_member_color(column_segments, "#6e7781")
    assert all(
        member.profile == "R 200 x 400"
        and member.geometry_dict() == {"b": 200.0, "h": 400.0}
        for member in longitudinal_beams
    )
    assert_member_color(longitudinal_beams, "#6e7781")
    assert all(
        abs(abs(model.nodes[member.start_node].z - model.nodes[member.end_node].z) - 3.0) < 1e-9
        and member.rotation == 90
        for member in column_segments
    )
    assert all(
        model.nodes[member.start_node].x == model.nodes[member.end_node].x
        and model.nodes[member.start_node].y != model.nodes[member.end_node].y
        and model.nodes[member.start_node].z == model.nodes[member.end_node].z
        and abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y) - 5.0) < 1e-9
        and member.rotation == 0
        for member in longitudinal_beams
    )

    cantilevers = [member for member in model.bars.values()
                   if member.profile == "W 200 x 15.0"]
    assert len(cantilevers) == 10
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "W Laminado"
        and member.geometry_dict() == {"d": 200.0, "bf": 100.0, "tw": 4.3, "tf": 5.2}
        for member in cantilevers
    )
    assert_member_color(cantilevers, "#6e7781")
    cantilever_layout = {
        frozenset((
            (model.nodes[member.start_node].x, model.nodes[member.start_node].y,
             model.nodes[member.start_node].z),
            (model.nodes[member.end_node].x, model.nodes[member.end_node].y,
             model.nodes[member.end_node].z),
        ))
        for member in cantilevers
    }
    assert cantilever_layout == {
        frozenset(((start_x, y, start_z), (end_x, y, end_z)))
        for y in (0.0, 5.0, 10.0, 15.0, 20.0)
        for start_x, start_z, end_x, end_z in (
            (0.0, 3.0, -0.4, 3.04),
            (-0.4, 3.04, -2.0, 3.2),
        )
    }
    cantilever_node_names = {
        node_name
        for member in cantilevers
        for node_name in (member.start_node, member.end_node)
    }

    truss_members = [member for member in model.bars.values()
                     if member.profile == "U 100 x 50 x 3"]
    assert len(truss_members) == 485
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "U Formado"
        and member.profile == "U 100 x 50 x 3"
        and member.geometry_dict() == {"d": 100.0, "bf": 50.0, "t": 3.0}
        for member in truss_members
    )

    def endpoints(member):
        return model.nodes[member.start_node], model.nodes[member.end_node]

    bottom_chords = [
        member for member in truss_members
        if endpoints(member)[0].z == endpoints(member)[1].z == 6.0
        and endpoints(member)[0].x != endpoints(member)[1].x
    ]
    top_chords = [
        member for member in truss_members
        if endpoints(member)[0].z > 6.0 and endpoints(member)[1].z > 6.0
        and endpoints(member)[0].x != endpoints(member)[1].x
    ]
    verticals = [
        member for member in truss_members
        if endpoints(member)[0].x == endpoints(member)[1].x
    ]
    assert len(bottom_chords) == 120
    assert len(top_chords) == 120
    assert len(verticals) == 125
    assert all(member.rotation == 90 for member in bottom_chords)
    assert all(member.rotation == 270 for member in top_chords)
    assert_member_color(bottom_chords, "#6e7781")
    assert_member_color(top_chords, "#6e7781")
    assert_member_color(verticals, "#6e7781")
    assert all(
        member.rotation == (180 if endpoints(member)[0].x > 6.0 else 0)
        for member in verticals
    )

    diagonals = [
        member for member in truss_members
        if model.nodes[member.start_node].x != model.nodes[member.end_node].x
        and model.nodes[member.start_node].z != model.nodes[member.end_node].z
        and min(model.nodes[member.start_node].z, model.nodes[member.end_node].z) == 6.0
    ]
    assert len(diagonals) == 120
    assert all(member.rotation == 270 for member in diagonals)
    assert_member_color(diagonals, "#6e7781")
    assert all(
        abs(abs(model.nodes[member.start_node].x - model.nodes[member.end_node].x) - 0.5) < 1e-9
        and 0.5 <= abs(model.nodes[member.start_node].z - model.nodes[member.end_node].z) <= 0.8
        for member in diagonals
    )

    purlins = [member for member in model.bars.values()
               if member.profile == "C Laminado 127 x 50 x 17 x 3.00"]
    assert len(purlins) == 164
    roof_purlins = [member for member in purlins
                    if model.nodes[member.start_node].x >= 0.0]
    overhang_purlins = [member for member in purlins
                        if model.nodes[member.start_node].x < 0.0]
    assert len(roof_purlins) == 140
    assert len(overhang_purlins) == 24
    assert_member_color(purlins, "#6e7781")
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "C Formado"
        and member.profile == "C Laminado 127 x 50 x 17 x 3.00"
        and member.geometry_dict() == {"d": 127.0, "bf": 50.0, "c": 17.0, "t": 3.0}
        for member in purlins
    )
    assert all(
        model.nodes[member.start_node].x == model.nodes[member.end_node].x
        and model.nodes[member.start_node].y != model.nodes[member.end_node].y
        and model.nodes[member.start_node].z == model.nodes[member.end_node].z
        for member in purlins
    )
    assert {
        round(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y), 9)
        for member in roof_purlins
    } == {0.6, round(5.0 / 3.0 - 0.6, 9), round(5.0 / 3.0, 9)}
    assert all(
        abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y)
            - 5.0 / 3.0) < 1e-9
        for member in overhang_purlins
    )
    assert {model.nodes[member.start_node].x for member in roof_purlins} == set(range(0, 13, 2))
    assert all(
        member.rotation == (357 if model.nodes[member.start_node].x < 6.0
                            else 183 if model.nodes[member.start_node].x > 6.0
                            else 0)
        for member in roof_purlins
    )
    assert all(
        member.rotation == 186
        and model.nodes[member.start_node].x == model.nodes[member.end_node].x
        and model.nodes[member.start_node].x in {-0.4, -2.0}
        and abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y)
                - 5.0 / 3.0) < 1e-9
        for member in overhang_purlins
    )
    upper_chord_nodes = {
        node_name
        for member in top_chords
        for node_name in (member.start_node, member.end_node)
    }
    assert all(
        node_name in upper_chord_nodes
        for member in roof_purlins
        for node_name in (member.start_node, member.end_node)
        if model.nodes[node_name].y in (0.0, 5.0, 10.0, 15.0, 20.0)
    )
    assert all(
        node_name in cantilever_node_names
        for member in overhang_purlins
        for node_name in (member.start_node, member.end_node)
        if model.nodes[node_name].y in (0.0, 5.0, 10.0, 15.0, 20.0)
    )

    round_bars = [member for member in model.bars.values()
                  if member.profile == "Barra Redonda Ø10 mm"]
    braces = [member for member in round_bars
              if abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y) - 5.0) < 1e-9]
    ridge_braces = [member for member in round_bars
                    if abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y)
                           - 5.0 / 3.0) < 1e-9]
    purlin_ties = [member for member in round_bars
                   if model.nodes[member.start_node].y == model.nodes[member.end_node].y]
    assert len(braces) == 24
    assert len(ridge_braces) == 16
    assert len(purlin_ties) == 32
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "Barra Circular"
        and member.profile == "Barra Redonda Ø10 mm"
        and member.geometry_dict() == {"d": 10.0}
        for member in round_bars
    )
    assert_member_color(round_bars, "#6e7781")
    brace_layout = {
        frozenset((
            (model.nodes[member.start_node].x, model.nodes[member.start_node].y),
            (model.nodes[member.end_node].x, model.nodes[member.end_node].y),
        ))
        for member in braces
    }
    brace_layout_expected = set()
    for y1, y2 in ((0.0, 5.0), (15.0, 20.0)):
        for x1, x2 in zip(range(0, 13, 2), range(2, 13, 2)):
            brace_layout_expected.add(frozenset(((x1, y1), (x2, y2))))
            brace_layout_expected.add(frozenset(((x2, y1), (x1, y2))))
    assert brace_layout == brace_layout_expected
    purlin_tie_layout = {
        frozenset((
            (model.nodes[member.start_node].x, model.nodes[member.start_node].y),
            (model.nodes[member.end_node].x, model.nodes[member.end_node].y),
        ))
        for member in purlin_ties
    }
    assert purlin_tie_layout == {
        frozenset(((start_x, y), (end_x, y)))
        for start_x, end_x in ((4.0, 2.0), (2.0, 0.0), (8.0, 10.0), (10.0, 12.0))
        for y in {
            start_y + 5.0 * part / 3.0
            for start_y in (0.0, 5.0, 10.0, 15.0)
            for part in (1, 2)
        }
    }
    ridge_brace_layout = {
        frozenset((
            (model.nodes[member.start_node].x, model.nodes[member.start_node].y),
            (model.nodes[member.end_node].x, model.nodes[member.end_node].y),
        ))
        for member in ridge_braces
    }
    expected_ridge_brace_layout = set()
    for frame_index, frame_y in enumerate((0.0, 5.0, 10.0, 15.0, 20.0)):
        adjacent_y_positions = []
        if frame_index > 0:
            previous_y = (0.0, 5.0, 10.0, 15.0, 20.0)[frame_index - 1]
            adjacent_y_positions.append(previous_y + (frame_y - previous_y) * 2.0 / 3.0)
        if frame_index < 4:
            next_y = (0.0, 5.0, 10.0, 15.0, 20.0)[frame_index + 1]
            adjacent_y_positions.append(frame_y + (next_y - frame_y) / 3.0)
        for x in (4.0, 8.0):
            for adjacent_y in adjacent_y_positions:
                expected_ridge_brace_layout.add(
                    frozenset(((6.0, frame_y), (x, adjacent_y)))
                )
    assert ridge_brace_layout == expected_ridge_brace_layout

    l_braces = [member for member in model.bars.values()
                if member.profile == "L Formado 30 x 30 x 3.00"]
    assert len(l_braces) == 64
    assert all(
        member.material == "Aço Estrutural"
        and member.section == "L Formado"
        and member.geometry_dict() == {"d": 30.0, "bf": 30.0, "t": 3.0}
        for member in l_braces
    )
    assert_member_color(l_braces, "#6e7781")
    roof_l_braces = [member for member in l_braces
                     if model.nodes[member.start_node].x >= 0.0
                     and model.nodes[member.end_node].x >= 0.0]
    marquee_l_braces = [member for member in l_braces
                        if model.nodes[member.start_node].x < 0.0
                        and model.nodes[member.end_node].x < 0.0]
    assert len(roof_l_braces) == 56
    assert len(marquee_l_braces) == 8
    knee_braces = [
        member for member in roof_l_braces
        if model.nodes[member.start_node].y != model.nodes[member.end_node].y
    ]
    rigid_roof_braces = [
        member for member in roof_l_braces
        if model.nodes[member.start_node].y == model.nodes[member.end_node].y
    ]
    assert len(knee_braces) == 40
    assert len(rigid_roof_braces) == 16
    assert all(
        model.nodes[member.start_node].y == model.nodes[member.end_node].y
        and {model.nodes[member.start_node].x, model.nodes[member.end_node].x} in (
            {4.0, 6.0}, {6.0, 8.0}
        )
        for member in rigid_roof_braces
    )
    assert {model.nodes[member.start_node].y for member in rigid_roof_braces} == {
        start_y + 5.0 * part / 3.0
        for start_y in (0.0, 5.0, 10.0, 15.0)
        for part in (1, 2)
    }
    knee_brace_layout = {
        frozenset((
            (model.nodes[member.start_node].x, model.nodes[member.start_node].y),
            (model.nodes[member.end_node].x, model.nodes[member.end_node].y),
        ))
        for member in knee_braces
    }
    assert knee_brace_layout == {
        frozenset(((x, brace_y), (x, support_y)))
        for x in map(float, range(2, 12, 2))
        for start_y, end_y in zip((0.0, 5.0, 10.0, 15.0), (5.0, 10.0, 15.0, 20.0))
        for brace_y, support_y in ((start_y + 0.6, start_y), (end_y - 0.6, end_y))
    }
    assert all(
        abs(abs(model.nodes[member.start_node].y - model.nodes[member.end_node].y) - 0.6) < 1e-9
        and {model.nodes[member.start_node].z, model.nodes[member.end_node].z}
        == {6.0, 6.5 + 0.05 * min(model.nodes[member.start_node].x,
                                  12.0 - model.nodes[member.start_node].x)}
        for member in knee_braces
    )
    assert {
        frozenset((model.nodes[member.start_node].x, model.nodes[member.end_node].x))
        for member in marquee_l_braces
    } == {frozenset((-0.4, -2.0))}
    assert {model.nodes[member.start_node].y for member in marquee_l_braces} == {
        start_y + 5.0 * part / 3.0
        for start_y in (0.0, 5.0, 10.0, 15.0)
        for part in (1, 2)
    }

    for y in (0.0, 5.0, 10.0, 15.0, 20.0):
        roof_heights = {
            node.x: node.z
            for node in model.nodes.values()
            if node.y == y and node.z == 6.5 + 0.05 * min(node.x, 12.0 - node.x)
        }
        assert roof_heights[0.0] == roof_heights[12.0] == 6.5
        assert roof_heights[6.0] == 6.8
        assert abs((roof_heights[6.0] - roof_heights[0.0]) / 6.0 - 0.05) < 1e-9
        assert abs((roof_heights[12.0] - roof_heights[6.0]) / 6.0 + 0.05) < 1e-9


def test_portico_is_not_a_command_and_does_not_change_the_model():
    model, commands = session()

    response = commands.submit("portico")

    assert response.level == "error"
    assert not response.model_changed
    assert commands.pending is None
    assert not model.nodes
    assert not model.bars


def test_mezanino_creates_three_steel_modules_with_catalogued_w_profiles():
    model, commands = session()

    response = commands.submit("mezanino")

    assert response.model_changed
    assert commands.pending is None
    assert len(model.nodes) == 34
    assert len(model.bars) == 54
    assert {(node.x, node.y, node.z) for node in model.nodes.values()} == {
        *((x, y, z) for x in (0.0, 7.0, 14.0, 21.0) for y in (0.0, 4.0) for z in (0.0, 4.0)),
        *((x, y, 4.0) for x in (7.0 / 3, 14.0 / 3, 28.0 / 3, 35.0 / 3, 49.0 / 3, 56.0 / 3)
          for y in (0.0, 4.0)),
        *((x, 2.0, 4.0) for x in (0.0, 21.0)),
        *((x, y, 3.0) for x in (7.0, 14.0) for y in (1.0, 3.0)),
    }
    assert all(
        node.supports[:3] == (True, True, True)
        for node in model.nodes.values()
        if node.z == 0.0
    )
    assert all(member.material == "Aço Estrutural" for member in model.bars.values())
    profiles = {profile: [member for member in model.bars.values() if member.profile == profile]
                for profile in ("W 250 x 44.8", "W 310 x 44.5", "W 200 x 22.5", "BC 10.0")}
    assert {profile: len(members) for profile, members in profiles.items()} == {
        "W 250 x 44.8": 8,
        "W 310 x 44.5": 18,
        "W 200 x 22.5": 12,
        "BC 10.0": 16,
    }
    columns = profiles["W 250 x 44.8"]
    assert all(member.rotation == 90 for member in columns)
    assert all(member.releases == (False,) * 8 + (True,) * 4
               for member in profiles["W 200 x 22.5"])
    for member in profiles["W 310 x 44.5"]:
        start_x = model.nodes[member.start_node].x
        end_x = model.nodes[member.end_node].x
        is_middle_module = 7.0 < (start_x + end_x) / 2 < 14.0
        start_on_column = not is_middle_module and start_x in (0.0, 7.0, 14.0, 21.0)
        end_on_column = not is_middle_module and end_x in (0.0, 7.0, 14.0, 21.0)
        assert member.releases == (False,) * 8 + (
            start_on_column, end_on_column, start_on_column, end_on_column,
        )
    braces = profiles["BC 10.0"]
    assert all(
        member.section == "Barra Circular"
        and member.geometry_dict() == {"d": 10.0}
        and member.releases == (False,) * 6 + (True,) * 6
        for member in braces
    )
    assert all(model.nodes[member.start_node].x == model.nodes[member.end_node].x
               for member in braces)
    assert {
        frozenset(((model.nodes[member.start_node].y, model.nodes[member.start_node].z),
                   (model.nodes[member.end_node].y, model.nodes[member.end_node].z)))
        for member in braces
        if model.nodes[member.start_node].x in (0.0, 21.0)
    } == {
        frozenset(((0.0, 0.0), (2.0, 4.0))),
        frozenset(((4.0, 0.0), (2.0, 4.0))),
    }
    assert {
        frozenset(((model.nodes[member.start_node].y, model.nodes[member.start_node].z),
                   (model.nodes[member.end_node].y, model.nodes[member.end_node].z)))
        for member in braces
        if model.nodes[member.start_node].x in (7.0, 14.0)
    } == {
        frozenset((corner, hub))
        for hub, corners in (
            ((1.0, 3.0), ((0.0, 0.0), (0.0, 4.0), (4.0, 4.0))),
            ((3.0, 3.0), ((4.0, 0.0), (0.0, 4.0), (4.0, 4.0))),
        )
        for corner in corners
    }
    assert [(axis.label, axis.value) for axis in model.axes["X"]] == [("A", 0.0), ("B", 4.0)]
    assert [(axis.label, axis.value) for axis in model.axes["Y"]] == [
        ("1", 0.0), ("2", 7.0), ("3", 14.0), ("4", 21.0),
    ]
    assert [(axis.label, axis.value) for axis in model.axes["Z"]] == [("0", 0.0), ("400", 4.0)]
