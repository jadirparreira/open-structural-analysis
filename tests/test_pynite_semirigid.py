import numpy as np
import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.pynite.semirigid import _condense_stiffness
from osa.model import StructuralModel
from osa.services.action_service import ActionService


def test_semirigid_condensation_reduces_the_selected_end_stiffness():
    base_stiffness = np.eye(12) * 100.0

    condensed = _condense_stiffness(
        base_stiffness,
        tuple(index for index in range(12) if index != 3),
        (3,),
        np.array([[100.0]]),
    )

    assert condensed[3, 3] == pytest.approx(50.0)
    assert np.allclose(condensed, condensed.T)


def test_member_rotation_flexibility_changes_the_pynite_response():
    displacements = {
        percent: _cantilever_tip_displacement(percent)
        for percent in (0, 50, 99)
    }

    assert abs(displacements[0]) < abs(displacements[50]) < abs(displacements[99])
    assert displacements[50] == pytest.approx(-0.0116666667)


@pytest.mark.parametrize(
    ("rotation", "expected_y", "expected_z"),
    ((0, 0.0, -0.0066666667), (90, 0.0, -0.0266666667)),
)
def test_member_deflections_are_reported_in_global_axes(rotation, expected_y, expected_z):
    result = _cantilever_tip_result(rotation=rotation)
    node = result.node_results["N2"]
    member_end = result.member_results["B1"]["end"]

    assert node["DY"] == pytest.approx(expected_y)
    assert node["DZ"] == pytest.approx(expected_z)
    assert member_end["deflection_y"] == pytest.approx(expected_y)
    assert member_end["deflection_z"] == pytest.approx(expected_z)


def _cantilever_tip_displacement(percent: int) -> float:
    return _cantilever_tip_result(percent=percent).node_results["N2"]["DZ"]


def _cantilever_tip_result(percent: int = 0, rotation: int = 0):
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 4.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    model.update_node_supports("N1", (True, True, True, True, True, True))

    material = "Concreto Estrutural"
    model.update_bar_material("B1", material, model.materials[material])
    model.update_bar_section("B1", "Retangular")
    model.update_member_profile("B1", "Retangular", {"b": 200.0, "h": 400.0})
    model.update_member_rotation("B1", rotation)
    # Rya is the local bending rotation at end A in the persisted A/B order.
    model.update_member_rotation_flexibility_percent("B1", (0, 0, percent, 0, 0, 0))
    ActionService(model).add_node_force("N2", "Z", -10.0, "Caso")

    return PyniteAdapter().run(model, AnalysisRequest())[0]
