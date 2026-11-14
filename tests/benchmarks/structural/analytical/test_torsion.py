"""Analytical benchmark for Saint-Venant torsion of a cantilever."""

from __future__ import annotations

from osa.services import ActionService

from ..helpers import (
    analyze,
    assert_close,
    cantilever_model,
    rectangular_torsion_constant,
)


def test_torsion_matches_tip_rotation_torque_and_reaction():
    length_m = 2.0
    width_mm = 100.0
    height_mm = 200.0
    torque_kn_m = 10.0
    shear_modulus_kn_m2 = 76_900_000.0
    torsion_constant_m4 = rectangular_torsion_constant(width_mm, height_mm)

    model = cantilever_model(
        length_m=length_m,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    ActionService(model).add_node_moment("B", "Z", torque_kn_m, "Caso")
    result = analyze(model)

    expected_rotation_rad = torque_kn_m * length_m / (shear_modulus_kn_m2 * torsion_constant_m4)
    member = result.member_results["B1"]
    assert_close(result.node_results["B"]["RZ"], expected_rotation_rad)
    assert_close(result.node_results["A"]["RXN_MZ"], -torque_kn_m)
    assert_close(member["start"]["torque"], -torque_kn_m)
    assert_close(member["end"]["torque"], -torque_kn_m)
