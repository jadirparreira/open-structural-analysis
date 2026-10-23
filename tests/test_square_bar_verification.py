import math

from osa.domain import AnalysisResult
from osa.memorial_data import calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.property_panel import PropertyPanel
from osa.ui.verification_worker import verify_model


def _model(side=20.0, length=0.5, loads=None):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("S1", "A", "B")
    model.update_bar_material("S1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("S1", "Barra Quadrada")
    model.update_member_profile("S1", f"QUA {side:g}", {"b": side})
    model.analysis_results = [AnalysisResult(
        model.revision, "ELU", member_results={"S1": {"samples": [loads or {
            "x": 0.0, "axial": 10.0, "moment_y": 0.1, "moment_z": 0.1,
            "shear_y": 1.0, "shear_z": 1.0,
        }]}}
    )]
    return model


def test_square_bar_runs_symmetric_checks_and_renders_its_memorial():
    model = _model()
    result = verify_model(model)
    element = result["results"]["bar:S1"]
    checks = element["checks"]

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    assert result["summary"]["unverified"] == 0
    assert element["status"] == "checked"
    assert all(check["status"] != "not_checked" for check in checks.values())
    assert checks["flexion_y"]["parameters"]["strong_axis"] is True
    assert checks["flexion_z"]["parameters"]["strong_axis"] is True
    assert math.isclose(checks["flexion_y"]["parameters"]["MRd_kn_cm"],
                        checks["flexion_z"]["parameters"]["MRd_kn_cm"], rel_tol=1e-12)
    assert math.isclose(checks["shear_y"]["parameters"]["VRd_kn"],
                        checks["shear_z"]["parameters"]["VRd_kn"], rel_tol=1e-12)
    assert math.isclose(checks["axial_compression"]["parameters"]["Ney_kn"],
                        checks["axial_compression"]["parameters"]["Nez_kn"], rel_tol=1e-12)
    for key, capacity in (("axial_tension", "Nt_Rd_kn"),
                          ("axial_compression", "Nc_Rd_kn"),
                          ("flexion_y", "MRd_kn_cm"), ("flexion_z", "MRd_kn_cm"),
                          ("shear_y", "VRd_kn"), ("shear_z", "VRd_kn")):
        assert math.isfinite(checks[key]["parameters"][capacity])
        assert checks[key]["parameters"][capacity] > 0.0

    model.verification_results = result["results"]
    panel_context = type("Context", (), {"window": type("Window", (), {"model": model})()})()
    assert PropertyPanel._has_verification_routine(panel_context, ("S1",))
    html = CalculationMemorialDialog._render(calculation_memory(model, ("S1",)), {})
    assert "Barra Quadrada" in html
    assert "Lado (b)" in html
    assert "Flexão em Y" in html and "Flexão em Z" in html
    assert "Cortante em Y" in html and "Cortante em Z" in html
    assert "não implementada" not in html.lower()


def test_square_bar_missing_side_is_not_checked_without_crashing():
    model = _model()
    model.update_member_profile("S1", "QUA sem dimensão", {})

    result = verify_model(model)

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["unverified"] == 1
    assert result["results"]["bar:S1"]["checks"]["axial_compression"]["status"] == "not_checked"
