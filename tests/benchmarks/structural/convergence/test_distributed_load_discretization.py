"""Check distributed-load results as a cantilever is subdivided."""

from __future__ import annotations

import pytest

from osa.services import ActionService

from ..helpers import (
    analyze,
    assert_close,
    rectangular_major_inertia,
    segmented_cantilever_model,
)


@pytest.mark.parametrize("member_count", (1, 2, 4, 8))
def test_uniform_load_matches_closed_form_after_member_subdivision(member_count: int):
    length_m = 2.0
    width_mm = 100.0
    height_mm = 200.0
    load_kn_per_m = -5.0
    elastic_modulus_kn_m2 = 200_000_000.0
    inertia_m4 = rectangular_major_inertia(width_mm, height_mm)

    model = segmented_cantilever_model(
        member_count,
        length_m=length_m,
        width_mm=width_mm,
        height_mm=height_mm,
    )
    actions = ActionService(model)
    for index in range(member_count):
        actions.add_member_distributed_force(
            f"B{index + 1}",
            "Y",
            load_kn_per_m,
            load_kn_per_m,
            "Caso",
        )

    result = analyze(model)
    tip = result.node_results[f"N{member_count}"]
    base = result.member_results["B1"]["start"]
    expected_tip_displacement_m = load_kn_per_m * length_m**4 / (
        8.0 * elastic_modulus_kn_m2 * inertia_m4
    )
    expected_base_moment_kn_m = -load_kn_per_m * length_m**2 / 2.0
    expected_base_shear_kn = -load_kn_per_m * length_m

    assert_close(tip["DY"], expected_tip_displacement_m)
    assert_close(base["moment_y"], expected_base_moment_kn_m)
    assert_close(base["shear_z"], expected_base_shear_kn)
