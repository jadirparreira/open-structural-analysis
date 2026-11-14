"""Global equilibrium checks for nodal actions and reactions."""

from __future__ import annotations

from osa.domain import AnalysisResult
from osa.model import StructuralModel

from .assertions import assert_close


def assert_global_equilibrium(
    model: StructuralModel,
    result: AnalysisResult,
    *,
    abs_tol: float = 1e-8,
) -> None:
    """Check force and moment balance for nodal actions and reactions.

    The moment balance is taken about the global origin and includes the
    moment of each nodal force, so the check is meaningful for arbitrary node
    positions rather than only for a support at the origin.
    """
    external_force = [0.0, 0.0, 0.0]
    external_moment = [0.0, 0.0, 0.0]
    for action in model.actions.values():
        if action.target not in model.nodes:
            raise AssertionError(
                f"Benchmark equilibrium helper only supports nodal actions: {action.target!r}"
            )
        node = model.nodes[action.target]
        if action.kind.startswith("node_force_"):
            axis = "XYZ".index(action.kind.rsplit("_", 1)[1])
            force = [0.0, 0.0, 0.0]
            force[axis] = action.components[0]
            external_force = [left + right for left, right in zip(external_force, force)]
            position = (node.x, node.y, node.z)
            external_moment[0] += position[1] * force[2] - position[2] * force[1]
            external_moment[1] += position[2] * force[0] - position[0] * force[2]
            external_moment[2] += position[0] * force[1] - position[1] * force[0]
        elif action.kind.startswith("node_moment_"):
            axis = "XYZ".index(action.kind.rsplit("_", 1)[1])
            external_moment[axis] += action.components[0]
        else:
            raise AssertionError(f"Unsupported action in equilibrium helper: {action.kind!r}")

    reaction_force = [0.0, 0.0, 0.0]
    reaction_moment = [0.0, 0.0, 0.0]
    for name, values in result.node_results.items():
        node = model.nodes[name]
        force = [values["RXN_FX"], values["RXN_FY"], values["RXN_FZ"]]
        reaction_force = [left + right for left, right in zip(reaction_force, force)]
        reaction_moment[0] += values["RXN_MX"] + node.y * force[2] - node.z * force[1]
        reaction_moment[1] += values["RXN_MY"] + node.z * force[0] - node.x * force[2]
        reaction_moment[2] += values["RXN_MZ"] + node.x * force[1] - node.y * force[0]

    for actual, expected in zip(reaction_force, (-value for value in external_force)):
        assert_close(actual, expected, abs_tol=abs_tol)
    for actual, expected in zip(reaction_moment, (-value for value in external_moment)):
        assert_close(actual, expected, abs_tol=abs_tol)
