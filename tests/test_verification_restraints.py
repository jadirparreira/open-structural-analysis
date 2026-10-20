"""Restraints must come from external load paths, not subdivision topology."""

from dataclasses import replace
from math import sqrt

import pytest

from osa.domain import AnalysisResult
from osa.domain.member_axes import member_basis
from osa.model import StructuralModel
from osa.verification.elements import VerificationElement
from osa.verification.restraints import AnalyticalRestraints
from osa.verification.w_rolled import _geometry_properties, verify_w_element


def add_w(model, name, start, end, rotation=0):
    model.add_bar(name, start, end)
    model.update_bar_material(name, "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section(name, "W Laminado")
    model.update_member_profile(name, "W 200 x 19,3", {"d": 200, "bf": 100, "tw": 6, "tf": 8})
    model.update_member_rotation(name, rotation)


def chain(*, rotation=0, split=True):
    model = StructuralModel()
    for name, x in (("A", 0), ("C", 2), ("B", 6)):
        model.add_node(name, x, 0, 0)
    if split:
        add_w(model, "B1", "A", "C", rotation)
        add_w(model, "B2", "C", "B", rotation)
        element = VerificationElement("group:B1|B2", "Grupo", ("B1", "B2"))
    else:
        add_w(model, "B1", "A", "B", rotation)
        element = VerificationElement("bar:B1", "B1", ("B1",))
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    return model, element


def result(model, element, *, axial=-10, moment=0):
    return AnalysisResult(model.revision, "ELU", member_results={
        name: {"samples": [{"axial": axial, "moment_y": moment}]}
        for name in element.member_names
    })


def lengths(model, element, **forces):
    return AnalyticalRestraints(model).lengths(
        element, [result(model, element, **forces)], _geometry_properties(model.bars[element.member_names[0]])
    )


def brace(model, *, anchored=True, hinged=True):
    model.add_node("D", 2, 3, 0)
    add_w(model, "BR", "C", "D")
    if anchored:
        model.update_node_supports("D", (True,) * 6)
    if hinged:
        # One torsional release suffices; releasing both torsional ends creates
        # a singular local condensation block in the existing frame solver.
        model.update_member_releases("BR", (False,) * 6 + (True, False, True, True, True, True))


def test_subdivision_does_not_reduce_lengths():
    model, element = chain()
    values = lengths(model, element)
    assert values.lengths_m == {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6}
    assert not values.issues


@pytest.mark.parametrize("split", [True, False])
def test_anchored_axial_brace_reduces_only_corresponding_bending_length(split):
    model, element = chain(split=split)
    brace(model)
    values = lengths(model, element)
    assert values.lengths_m == {"Ly": 6, "Lz": 4, "Lt": 6, "Lb": 6}
    assert values.modes["Lz"]["governing_interval_m"] == (2, 6)


def test_rotated_section_swaps_bending_restraints():
    model, element = chain(rotation=90)
    brace(model)
    values = lengths(model, element)
    assert values.lengths_m["Ly"] == 4
    assert values.lengths_m["Lz"] == 6


@pytest.mark.parametrize("axis", [(0, 0, 1), (1 / sqrt(3),) * 3])
def test_vertical_and_inclined_elements_follow_their_local_axes(axis):
    model, element = chain()
    for name, node in tuple(model.nodes.items()):
        model.nodes[name] = replace(node, x=node.x * axis[0], y=node.x * axis[1], z=node.x * axis[2])
    _x, local_y, _z = member_basis(model.nodes["A"], model.nodes["C"])
    centre = model.nodes["C"]
    model.add_node("D", *(coord + 3 * direction for coord, direction in zip(
        (centre.x, centre.y, centre.z), local_y, strict=True)))
    add_w(model, "BR", "C", "D")
    model.update_node_supports("D", (True,) * 6)
    values = lengths(model, element)
    # The branch is rigidly connected, so its flexural stiffness also restrains
    # motion perpendicular to its axial direction.
    assert values.lengths_m["Ly"] == pytest.approx(4)
    assert values.lengths_m["Lz"] == pytest.approx(4)


def test_unanchored_branch_is_not_a_restraint():
    model, element = chain()
    brace(model, anchored=False, hinged=False)
    assert lengths(model, element).lengths_m == {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6}


def test_crossing_without_an_analytical_node_is_not_a_restraint():
    model, element = chain(split=False)
    del model.nodes["C"]
    model.add_node("D1", 2, -3, 0)
    model.add_node("D2", 2, 3, 0)
    add_w(model, "BR", "D1", "D2")
    for name in ("D1", "D2"):
        model.update_node_supports(name, (True,) * 6)
    assert lengths(model, element).lengths_m == {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6}


def test_brace_axial_release_removes_its_translational_restraint():
    model, element = chain()
    brace(model)
    releases = list(model.bars["BR"].releases)
    releases[0] = True
    model.update_member_releases("BR", tuple(releases))
    assert lengths(model, element).lengths_m["Lz"] == 6


def test_weak_spring_fails_minimum_stiffness_and_strong_spring_passes():
    model, element = chain()
    model.update_node_supports("C", (False, True, False, False, False, False))
    model.update_node_support_stiffness("C", (0, 0.01, 0, 0, 0, 0))
    assert lengths(model, element).lengths_m["Lz"] == 6
    model.update_node_support_stiffness("C", (0, 10000, 0, 0, 0, 0))
    assert lengths(model, element).lengths_m["Lz"] == 4


def test_rigid_rotation_support_reduces_lt_and_lb():
    model, element = chain()
    model.update_node_supports("C", (False, False, False, True, False, False))
    values = lengths(model, element, moment=1)
    assert values.lengths_m["Lt"] == 4
    assert values.lengths_m["Lb"] == 4
    assert values.lengths_m["Ly"] == values.lengths_m["Lz"] == 6


def test_elastic_torsional_brace_screened_for_flt_and_not_assumed_for_compression():
    model, element = chain()
    brace(model, hinged=False)
    values = lengths(model, element, moment=0.1)
    assert values.lengths_m["Lb"] == 4
    assert values.lengths_m["Lt"] == 6
    assert any("empenhamento" in note or "empenamento" in note for note in values.notes)
    assert lengths(model, element, moment=10000).lengths_m["Lb"] == 6


def test_target_torsion_release_disconnects_fixed_support():
    model, element = chain()
    model.update_member_releases("B1", (False,) * 6 + (True,) + (False,) * 5)
    values = lengths(model, element)
    assert any("Lt" in issue for issue in values.issues)


def test_target_semirigid_connection_does_not_become_an_ideal_rotation_support():
    model, element = chain()
    model.update_member_rotation_flexibility_percent("B1", (50, 0, 0, 0, 0, 0))
    values = lengths(model, element)
    first = next(p for p in values.modes["Lt"]["points"] if p["node"] == "A")
    assert 0 < first["stiffness"] < float("inf")
    assert not first["accepted"]


def test_internal_hinge_without_a_lateral_restraint_is_not_checked_as_continuous():
    model, element = chain()
    for name, index in (("B1", 9), ("B2", 8)):
        releases = list(model.bars[name].releases)
        releases[index] = True
        model.update_member_releases(name, tuple(releases))
    evaluation = verify_w_element(element, model, [result(model, element)])
    assert evaluation["status"] == "not_checked"
    assert "Ly: ligação interna" in evaluation["detail"]


def test_free_end_requires_special_stability_analysis():
    model, element = chain()
    model.update_node_supports("B", (False,) * 6)
    evaluation = verify_w_element(element, model, [result(model, element, moment=1)])
    assert evaluation["status"] == "not_checked"
    assert "extremidades" in evaluation["detail"]
    assert "calculation_memory" in evaluation


def test_group_order_does_not_change_lengths_and_rotation_mismatch_is_rejected():
    model, element = chain()
    brace(model)
    reverse = replace(element, member_names=tuple(reversed(element.member_names)))
    assert lengths(model, reverse).lengths_m == lengths(model, element).lengths_m
    model.update_member_rotation("B2", 90)
    evaluation = verify_w_element(element, model, [result(model, element)])
    assert evaluation["status"] == "not_checked"
    assert "eixos locais" in evaluation["detail"]


def test_memory_uses_local_names_and_analytical_lengths():
    model, element = chain()
    brace(model)
    evaluation = verify_w_element(element, model, [result(model, element)])
    assert evaluation["status"] in {"approved", "rejected"}
    assert evaluation["calculation_memory"]["lengths_cm"] == {"Ly": 600, "Lz": 400, "Lt": 600, "Lb": 600}
    assert "Lx" not in evaluation["assumptions"]
    assert evaluation["calculation_memory"]["restraints"]["notes"]
