"""Analytical benchmark for transverse bending of a cantilever."""

from __future__ import annotations

from osa.services import ActionService

from ..helpers import (
    analyze,
    assert_close,
    cantilever_model,
    rectangular_major_inertia,
    rectangular_section_modulus,
)


def test_transverse_cantilever_matches_tip_displacement_reaction_moment_and_stress():
    length_m = 2.0
    width_mm = 100.0
    height_mm = 200.0
    force_kn = -10.0
    elastic_modulus_kn_m2 = 200_000_000.0
    inertia_m4 = rectangular_major_inertia(width_mm, height_mm)

    model = cantilever_model(
        length_m=length_m,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    ActionService(model).add_node_force("B", "Y", force_kn, "Caso")
    result = analyze(model)

    expected_displacement_m = force_kn * length_m**3 / (3.0 * elastic_modulus_kn_m2 * inertia_m4)
    expected_moment_kn_m = -force_kn * length_m
    member = result.member_results["B1"]
    assert_close(result.node_results["B"]["DY"], expected_displacement_m)
    assert_close(result.node_results["A"]["RXN_FY"], -force_kn)
    assert_close(result.node_results["A"]["RXN_MX"], force_kn * length_m)
    assert_close(member["start"]["moment_y"], expected_moment_kn_m)

    bending_stress_kn_m2 = abs(member["start"]["moment_y"]) / rectangular_section_modulus(
        width_mm,
        height_mm,
    )
    assert_close(bending_stress_kn_m2, abs(force_kn) * length_m / rectangular_section_modulus(width_mm, height_mm))
