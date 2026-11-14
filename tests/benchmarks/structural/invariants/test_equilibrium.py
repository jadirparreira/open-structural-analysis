"""Global equilibrium invariants for the analyzed structural model."""

from __future__ import annotations

from osa.services import ActionService

from ..helpers import analyze, assert_global_equilibrium, cantilever_model


def test_nodal_forces_and_moments_are_balanced_by_support_reactions():
    model = cantilever_model()
    actions = ActionService(model)
    actions.add_node_force("B", "Y", -10.0, "Caso")
    actions.add_node_force("B", "Z", 10.0, "Caso")
    actions.add_node_moment("B", "Z", 4.0, "Caso")

    result = analyze(model)

    assert_global_equilibrium(model, result)
