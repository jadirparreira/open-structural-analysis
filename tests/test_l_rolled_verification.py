import math

import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import _l_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.verification_worker import verify_model


def _model(b=100.0, t=10.0, length=3.0, loads=None):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("L1", "A", "B")
    model.update_bar_material("L1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("L1", "L Laminado")
    model.update_member_profile("L1", f"L {b:g} x {t:g}", {"b": b, "t": t})
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU",
        member_results={"L1": {"samples": [loads or {
            "x": 0.0, "axial": 10.0, "moment_y": 1.0, "moment_z": 0.5,
            "shear_y": 1.0, "shear_z": 1.0,
        }]}},
    )]
    return model


def test_equal_leg_l_section_runs_all_checks_and_produces_l_memorial():
    model = _model()
    props = _l_properties(model.bars["L1"])
    result = verify_model(model)
    element = result["results"]["bar:L1"]

    assert props["area"] > 0.0
    assert props["Imajor_cm4"] > props["Iminor_cm4"] > 0.0
    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    assert result["summary"]["unverified"] == 0
    assert element["status"] == "checked"
    assert all(check["status"] != "not_checked" for check in element["checks"].values())
    for key in ("axial_compression", "flexion_y", "flexion_z", "shear_y", "shear_z"):
        capacity_keys = {
            "axial_compression": "Nc_Rd_kn", "flexion_y": "MRd_kn_cm",
            "flexion_z": "MRd_kn_cm", "shear_y": "VRd_kn", "shear_z": "VRd_kn",
        }
        value = element["checks"][key]["parameters"][capacity_keys[key]]
        assert value > 0.0 and math.isfinite(value)

    model.verification_results = result["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {})
    assert "L Laminado" in html
    assert "Flexão em Y" in html
    assert "Flexão em Z" in html
    assert "Cortante em Y" in html
    assert "Cortante em Z" in html
    assert "resistência estimada para cantoneira isolada" not in html
    assert "cantoneira simples" not in html.lower()
    assert "interação preliminar com capacidades estimadas" not in html
    assert "não implementada" not in html.lower()


@pytest.mark.parametrize(("b", "t", "length"), ((25.4, 3.17, 0.5), (152.4, 19.0, 8.0), (100.0, 2.0, 15.0)))
def test_l_section_limit_geometries_do_not_crash_or_return_nonfinite_resistance(b, t, length):
    model = _model(b=b, t=t, length=length)
    result = verify_model(model)
    element = result["results"]["bar:L1"]

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    assert result["summary"]["unverified"] == 0
    for check_name in ("axial_compression", "flexion_y", "flexion_z", "shear_y", "shear_z"):
        check = element["checks"][check_name]
        assert check["status"] in {"checked", "not_applicable"}
        if check["status"] == "checked":
            assert math.isfinite(check["utilization"])
            assert check["utilization"] >= 0.0


def test_missing_l_dimensions_are_reported_as_input_error_without_exception():
    model = _model()
    model.update_member_profile("L1", "L sem dimensões", {})
    result = verify_model(model)

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["unverified"] == 1
    assert result["results"]["bar:L1"]["checks"]["axial_compression"]["status"] == "not_checked"
    model.verification_results = result["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {})
    assert "L Laminado" in html
    assert "geometria da seção incompleta" in html


def test_nonzero_torsion_does_not_add_commentary_to_l_memorial():
    model = _model(loads={"x": 0.0, "axial": 0.0, "moment_y": 0.0,
                          "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0,
                          "torque": 0.25})
    result = verify_model(model)
    model.verification_results = result["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {})

    assert "momento torsor solicitante" not in html
    assert "5.5.2.3" not in html
    assert "não deve ser interpretado como aprovação" not in html
    assert "Flexão em Y" in html
    assert "4. Verificações" in html
