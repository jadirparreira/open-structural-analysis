"""Static elastic portal frame compared with an OpenSees reference case."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from osa.model import StructuralModel
from osa.services import ActionService

from ...helpers import analyze, assert_close, assert_global_equilibrium

REFERENCE_PATH = Path(__file__).with_name("fixtures") / "elastic_portal_frame.json"


def _reference() -> dict[str, Any]:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


def _portal_frame_model() -> StructuralModel:
    """Build a 3D OpenSA model equivalent to the OpenSees 2D frame."""
    model = StructuralModel()
    for name, x, z in (
        ("A", 0.0, 0.0),
        ("B", 4.0, 0.0),
        ("C", 0.0, 3.0),
        ("D", 4.0, 3.0),
    ):
        model.add_node(name, x, 0.0, z)

    for name, start, end in (("C1", "A", "C"), ("C2", "B", "D"), ("B1", "C", "D")):
        model.add_bar(name, start, end)
        model.update_bar_material(name, "ASTM A36", model.materials["ASTM A36"])
        model.update_bar_section(name, "Retangular")
        # A square section makes the 2D OpenSees inertia unambiguous for both
        # columns and beam when embedded in the X-Z plane.
        model.update_member_profile(name, "PORTAL 200 x 200", {"b": 200.0, "h": 200.0})

    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    # Keep only the in-plane X-Z translation and rotation about global Y free.
    for name in ("C", "D"):
        model.update_node_supports(name, (False, True, False, True, False, True))

    actions = ActionService(model)
    for name in ("C", "D"):
        actions.add_node_force(name, "X", 10.0, "Caso")
        actions.add_node_force(name, "Z", -20.0, "Caso")
    return model


def test_elastic_portal_frame_matches_opensees_displacements_reactions_and_beam_forces():
    reference = _reference()
    model = _portal_frame_model()
    result = analyze(model)

    for node_name in ("C", "D"):
        node = result.node_results[node_name]
        expected = reference["nodes"][node_name]
        assert_close(node["DX"], expected["horizontal_displacement_m"])
        assert_close(node["DZ"], expected["vertical_displacement_m"])
        # OpenSees 2D rotation is about +Y in its local plane; the equivalent
        # OpenSA X-Z plane uses the opposite right-hand rotation sign about Y.
        assert_close(node["RY"], -expected["rotation_rad"])

    for node_name in ("A", "B"):
        node = result.node_results[node_name]
        expected = reference["supports"][node_name]
        assert_close(node["RXN_FX"], expected["horizontal_reaction_kN"])
        assert_close(node["RXN_FZ"], expected["vertical_reaction_kN"])
        assert_close(node["RXN_MY"], -expected["moment_kN_m"])

    beam_start = result.member_results["B1"]["start"]
    expected_beam = reference["beam_start"]
    assert_close(beam_start["shear_z"], expected_beam["shear_kN"])
    assert_close(beam_start["moment_y"], expected_beam["moment_kN_m"])
    assert_global_equilibrium(model, result)
