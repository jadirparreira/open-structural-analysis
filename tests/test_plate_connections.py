import numpy as np
import pytest

from osa.analysis.pynite.model_builder import ModelBuilder
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer


def slab(state):
    model = StructuralModel()
    plate = model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)),
                            edge_connections=tuple((edge, state) for edge in range(4)))
    for index, start in enumerate(plate.vertex_nodes):
        end = plate.vertex_nodes[(index + 1) % 4]
        name = f"B{index + 1}"
        model.add_bar(name, start, end)
        model.update_bar_material(name, "Concreto C30", model.materials["Concreto C30"])
        model.update_bar_section(name, "Retangular")
        model.update_member_profile(name, "Retangular", {"b": 200, "h": 400})
        model.update_node_supports(start, (True,) * 6)
    return model


def test_connections_persist_and_old_files_keep_full_compatibility():
    model = slab("supported")
    data = ProjectSerializer().dump(model)
    restored = StructuralModel()
    ProjectSerializer().load_into(restored, data)
    assert restored.plates["P1"].edge_connections == model.plates["P1"].edge_connections
    del data["plates"][0]["edge_connections"]
    ProjectSerializer().load_into(restored, data)
    assert restored.plates["P1"].edge_connections == ()


def test_new_plate_defaults_to_supported_and_explicit_connections_are_preserved():
    model = StructuralModel()
    contour = ((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0))
    plate = model.add_plate(contour)
    assert plate.edge_connections == tuple((edge, "supported") for edge in range(4))
    model.update_plate(plate.name, thickness_mm=150)
    assert model.plates[plate.name].edge_connections == plate.edge_connections
    explicit = model.add_plate(contour, edge_connections=((0, "free"), (1, "fixed")))
    assert explicit.edge_connections == ((0, "free"), (1, "fixed"))


@pytest.mark.parametrize("state", ["fixed", "supported", "free"])
def test_free_disconnects_and_supported_only_transmits_translations(state):
    target = ModelBuilder().build(slab(state))
    edge_nodes = {name for nodes in target._osa_plate_edges.values() for name, _ in nodes}
    beam_nodes = {node.name for member in target.members.values() for node in (member.i_node, member.j_node)}
    if state == "fixed":
        assert edge_nodes <= beam_nodes
        assert not target.springs
    else:
        assert edge_nodes.isdisjoint(beam_nodes)
        assert bool(target.springs) == (state == "supported")
        for link in target.springs.values():
            stiffness = link.Ke()
            assert np.all(stiffness[3:6] == 0)
            assert np.all(stiffness[9:12] == 0)
            np.testing.assert_allclose(stiffness @ np.tile([1, 2, 3, 0, 0, 0], 2), 0, atol=1e-3)


def solve_slab(state, free_edge=False):
    model = slab(state)
    if free_edge:
        model.update_plate("P1", edge_connections=((0, "free"), (1, state), (2, state), (3, state)))
    target = ModelBuilder().build(model)
    target.add_load_combo("Caso", {"Carga": 1})
    for name in target.quads:
        target.add_quad_surface_pressure(name, -1, "Carga")
    target.analyze_linear(check_statics=True)
    reaction = sum(node.RxnFZ["Caso"] for node in target.nodes.values())
    displacement = max(abs(node.DZ["Caso"]) for node in target.nodes.values())
    assert reaction == pytest.approx(12, rel=1e-5)
    for link in target.springs.values():
        for dof in ("DX", "DY", "DZ"):
            assert abs(getattr(link.i_node, dof)["Caso"] - getattr(link.j_node, dof)["Caso"]) < 1e-8
    if free_edge:
        assert target.members["B1"].max_moment("My", "Caso") == pytest.approx(0, abs=1e-7)
        assert target.members["B1"].max_moment("Mz", "Caso") == pytest.approx(0, abs=1e-7)
    return displacement


def test_articulated_and_free_edges_change_structural_response_and_balance_loads():
    fixed = solve_slab("fixed")
    supported = solve_slab("supported")
    released = solve_slab("supported", free_edge=True)
    assert supported > fixed * 1.05
    assert released != pytest.approx(supported, rel=0.05)


def test_split_and_join_preserve_connections_on_the_original_boundary():
    model = slab("supported")
    first, second = model.split_plate("P1", (2, 0, 0), (2, 3, 0))
    for plate in (first, second):
        for edge in range(len(plate.contour)):
            if model.plate_edge_bars(plate.name, edge):
                assert dict(plate.edge_connections).get(edge, "fixed") == "supported"
    merged = model.join_plates(first.name, second.name)
    assert all(state == "supported" for _, state in merged.edge_connections)
    assert len(merged.edge_connections) == len(merged.contour)


def test_supported_plate_does_not_stiffen_rotations_of_articulated_beam_nodes():
    from dataclasses import replace

    model = slab("supported")
    for name, member in tuple(model.bars.items()):
        releases = list(member.releases)
        for index in (8, 9, 10, 11):
            releases[index] = True
        model.bars[name] = replace(member, releases=tuple(releases))
    for name in model.nodes:
        model.update_node_supports(name, (True, True, True, False, False, False))
    target = ModelBuilder().build(model)
    for name in model.nodes:
        node = target.nodes[name]
        assert node.support_RX and node.support_RY and node.support_RZ
    target.add_load_combo("Caso", {"Carga": 1})
    for name in target.quads:
        target.add_quad_surface_pressure(name, -1, "Carga")
    target.analyze_linear()
    assert sum(node.RxnFZ["Caso"] for node in target.nodes.values()) == pytest.approx(12, rel=1e-5)
