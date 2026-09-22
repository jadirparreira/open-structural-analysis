from osa.commands import CommandSession
from osa.model import StructuralModel
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


def test_portico_does_not_leave_a_pending_command():
    model, commands = session()
    assert commands.submit("portico").model_changed
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
