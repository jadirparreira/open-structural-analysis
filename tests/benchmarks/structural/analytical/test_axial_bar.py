"""Analytical benchmark for axial response of a cantilever bar."""

from __future__ import annotations

from osa.services import ActionService

from ..helpers import (
    analyze,
    assert_close,
    cantilever_model,
    rectangular_area,
)


def test_axial_bar_matches_force_displacement_reaction_and_normal_stress():
    length_m = 2.0
    width_mm = 100.0
    height_mm = 200.0
    force_kn = 10.0
    elastic_modulus_kn_m2 = 200_000_000.0
    area_m2 = rectangular_area(width_mm, height_mm)

    model = cantilever_model(
        length_m=length_m,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    ActionService(model).add_node_force("B", "Z", force_kn, "Caso")
    result = analyze(model)

    expected_displacement_m = force_kn * length_m / (elastic_modulus_kn_m2 * area_m2)
    member = result.member_results["B1"]
    assert_close(result.node_results["B"]["DZ"], expected_displacement_m)
    assert_close(result.node_results["A"]["RXN_FZ"], -force_kn)
    assert_close(member["start"]["axial"], -force_kn)

    normal_stress_kn_m2 = abs(member["start"]["axial"]) / area_m2
    assert_close(normal_stress_kn_m2, force_kn / area_m2)
