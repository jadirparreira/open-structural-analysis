"""Restraints must come from external load paths, not subdivision topology."""

from dataclasses import replace
from math import inf, pi, sqrt

import pytest

from osa.domain import AnalysisResult
from osa.domain.member_axes import member_basis
from osa.memorial_data import _w_properties, calculation_memory
from osa.model import StructuralModel
from osa.verification.elements import VerificationElement
from osa.verification.restraints import AnalyticalRestraints
from osa.verification.w_rolled import verify_w_compression


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


def result(model, element, *, axial=10, moment=0):
    return AnalysisResult(model.revision, "ELU", member_results={
        name: {"samples": [{"axial": axial, "moment_y": moment}]}
        for name in element.member_names
    })


def lengths(model, element, **forces):
    properties = _w_properties(model.bars[element.member_names[0]])
    return AnalyticalRestraints(model).lengths(
        element, [result(model, element, **forces)],
        {"Iy": properties["Iz"], "tw": properties["tw"] / 10.0},
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
    values = lengths(model, element)
    assert values.lengths_m["Lz"] == 6
    weak = next(p for p in values.modes["Lz"]["points"] if p["node"] == "C")
    assert weak["required_stiffness"] > weak["stiffness"]
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
    first = next(p for p in values.modes["Lt"]["points"] if p["node"] == "A")
    assert not first["accepted"]
    assert first["stiffness"] == 0
    assert values.lengths_m["Lt"] == inf
    assert not values.issues
    assert values.modes["Lt"]["boundary_condition"] == "warping_ignored"


def test_target_semirigid_connection_does_not_become_an_ideal_rotation_support():
    model, element = chain()
    model.update_member_rotation_flexibility_percent("B1", (50, 0, 0, 0, 0, 0))
    values = lengths(model, element)
    first = next(p for p in values.modes["Lt"]["points"] if p["node"] == "A")
    assert 0 < first["stiffness"] < float("inf")
    assert not first["accepted"]


def test_group_order_does_not_change_calculated_lengths():
    model, element = chain()
    brace(model)
    reverse = replace(element, member_names=tuple(reversed(element.member_names)))
    assert lengths(model, reverse).lengths_m == lengths(model, element).lengths_m


def test_intermediate_brace_minimum_is_not_applied_to_end_supports():
    model, element = chain()
    model.update_node_support_stiffness("B", (0, 0.01, 0, 0, 0, 0))
    values = lengths(model, element, axial=10000)
    assert values.lengths_m["Lz"] == 6
    assert not values.issues
    end = next(p for p in values.modes["Lz"]["points"] if p["node"] == "B")
    assert end["accepted"]
    assert end["required_stiffness"] == 0


def test_unreleased_terminal_connection_transfers_external_torsional_restraint():
    model, element = chain()
    model.update_node_supports("B", (True, True, True, False, False, False))
    model.add_node("E", 6, 3, 0)
    add_w(model, "END_BRACE", "B", "E")
    model.update_node_supports("E", (True,) * 6)
    values = lengths(model, element)
    end = next(p for p in values.modes["Lt"]["points"] if p["node"] == "B")
    assert 0 < end["stiffness"] < inf
    assert end["accepted"]
    assert values.lengths_m["Lt"] == 6
    assert not values.issues


def test_unreleased_connection_alone_does_not_invent_torsional_anchorage():
    model, element = chain()
    model.update_node_supports("B", (True, True, True, False, False, False))
    values = lengths(model, element)
    end = next(p for p in values.modes["Lt"]["points"] if p["node"] == "B")
    assert end["stiffness"] == 0
    assert not end["accepted"]
    assert values.lengths_m["Lt"] == inf
    assert not values.issues
    check = verify_w_compression(element, model, [result(model, element)])
    assert check["status"] == "checked"
    p = check["parameters"]
    assert p["Net_kn"] == pytest.approx(p["G_kn_cm2"] * p["It_cm4"] / p["r0_cm"]**2)
    assert any("sem contribuição do empenamento" in note for note in p["restraint_notes"])


def test_discarding_warping_does_not_increase_compression_resistance():
    model, element = chain()
    restrained = verify_w_compression(element, model, [result(model, element)])
    model.update_node_supports("B", (True, True, True, False, False, False))
    conservative = verify_w_compression(element, model, [result(model, element)])
    assert restrained["status"] == conservative["status"] == "checked"
    assert conservative["parameters"]["Net_kn"] < restrained["parameters"]["Net_kn"]
    assert conservative["parameters"]["Nc_Rd_kn"] <= restrained["parameters"]["Nc_Rd_kn"]


@pytest.mark.parametrize("rotation", [0, 90])
def test_cantilever_compression_uses_double_length_and_uniform_torsion_bound(rotation):
    model, element = chain(rotation=rotation)
    model.update_node_supports("B", (False,) * 6)
    check = verify_w_compression(element, model, [result(model, element)])
    assert check["status"] == "checked"
    p = check["parameters"]
    assert p["Ly_cm"] == p["Lz_cm"] == 1200
    assert p["Lt_cm"] == inf
    assert p["Ney_kn"] == pytest.approx(pi**2 * p["E_kn_cm2"] * p["Iy_cm4"] / 1200**2)
    assert p["Net_kn"] == pytest.approx(p["G_kn_cm2"] * p["It_cm4"] / p["r0_cm"]**2)


def test_rotational_release_at_base_is_not_treated_as_a_cantilever_clamp():
    model, element = chain()
    model.update_node_supports("B", (False,) * 6)
    releases = list(model.bars["B1"].releases)
    releases[8] = True
    model.update_member_releases("B1", tuple(releases))
    values = lengths(model, element)
    assert any(issue.startswith("Ly:") and "B" in issue for issue in values.issues)
    assert not values.modes["Ly"]["compression_supported"]
    assert values.modes["Lz"]["compression_supported"]


def test_internal_rotational_hinge_without_lateral_brace_still_blocks_that_mode():
    model, element = chain()
    releases = list(model.bars["B1"].releases)
    releases[9] = True
    model.update_member_releases("B1", tuple(releases))
    values = lengths(model, element)
    assert any(issue.startswith("Ly:") and "C" in issue for issue in values.issues)
    assert not any(issue.startswith(("Lz:", "Lt:")) for issue in values.issues)


def test_terminal_bending_hinges_do_not_remove_translation_or_torsion_restraints():
    model, element = chain()
    for name, indices in (("B1", (8, 10)), ("B2", (9, 11))):
        releases = list(model.bars[name].releases)
        for index in indices:
            releases[index] = True
        model.update_member_releases(name, tuple(releases))
    values = lengths(model, element)
    assert not values.issues
    assert values.lengths_m == {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6}


def test_pure_compression_does_not_require_beam_bracing_properties():
    model, element = chain()
    model.update_node_supports("C", (False, False, False, True, False, False))
    values = AnalyticalRestraints(model).lengths(element, [result(model, element)], {})
    assert not values.issues
    assert values.lengths_m["Lt"] == 4


def test_no_external_translation_restraint_still_blocks_compression_with_node_details():
    model, element = chain()
    for name in ("A", "B"):
        model.update_node_supports(name, (False,) * 6)
    check = verify_w_compression(element, model, [result(model, element)])
    assert check["status"] == "not_checked"
    assert "Ly: extremidade A" in check["detail"]
    assert "Lz: extremidade B" in check["detail"]


def test_semirigid_internal_connection_with_lateral_support_does_not_block_compression():
    model, element = chain()
    model.update_member_rotation_flexibility_percent("B1", (0, 0, 0, 50, 0, 0))
    model.update_node_supports("C", (False, False, True, False, False, False))
    check = verify_w_compression(element, model, [result(model, element)])
    assert check["status"] == "checked"
    assert check["parameters"]["Ly_cm"] == 400


@pytest.mark.parametrize("memorial_first", [True, False])
def test_memorial_and_compression_reuse_lengths_in_either_order(monkeypatch, memorial_first):
    model, element = chain()
    model.analysis_results = [result(model, element)]
    original = AnalyticalRestraints.lengths
    calls = []

    def tracked(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AnalyticalRestraints, "lengths", tracked)
    if memorial_first:
        calculation_memory(model, element.member_names)
    check = verify_w_compression(element, model, model.analysis_results)
    memory = calculation_memory(model, element.member_names)
    assert check["status"] == "checked"
    assert len(calls) == 1
    assert memory["geometric_parameters"]["Lt_cm"] == check["parameters"]["Lt_cm"]

    model.analysis_results = [result(model, element, axial=20)]
    verify_w_compression(element, model, model.analysis_results)
    assert len(calls) == 2
    model.update_node_supports("C", (False, False, False, True, False, False))
    model.analysis_results = [result(model, element)]
    memory = calculation_memory(model, element.member_names)
    assert len(calls) == 3
    assert memory["geometric_parameters"]["Lt_cm"] == 400


def test_cantilever_memorial_renders_the_infinite_lt_limit_with_display_fractions(monkeypatch):
    from osa.ui import calculation_memorial_dialog as memorial

    model, element = chain()
    model.group_verification_elements(element.member_names)
    model.update_node_supports("B", (False,) * 6)
    model.analysis_results = [result(model, element)]
    check = verify_w_compression(element, model, model.analysis_results)
    model.verification_results[element.key] = {"checks": {"axial_compression": check}}
    original = memorial.equation_svg
    rendered = []

    def checked_equation(latex):
        assert r"\frac" not in latex
        svg = original(latex)
        assert svg is not None, latex
        rendered.append(latex)
        return svg

    monkeypatch.setattr(memorial, "equation_svg", checked_equation)
    memory = calculation_memory(model, element.member_names)
    objects = {}
    html = memorial.CalculationMemorialDialog._render(memory, objects)
    assert "∞ cm" in html
    assert any(r"\infty" in latex and "N_{et}" in latex for latex in rendered)
    assert "sem contribuição do empenamento" in html
    assert len(objects) == len(rendered)
