import math

import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.property_panel import PropertyPanel
from osa.ui.verification_worker import verify_model


def _model(b=10.0, h=20.0, length=0.5, loads=None):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("R1", "A", "B")
    model.update_bar_material("R1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("R1", "Barra Retangular")
    model.update_member_profile("R1", f"RET {b:g} x {h:g}", {"b": b, "h": h})
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU",
        member_results={"R1": {"samples": [loads or {
            "x": 0.0, "axial": 10.0, "moment_y": 0.1, "moment_z": 0.1,
            "shear_y": 1.0, "shear_z": 1.0,
        }]}},
    )]
    return model


def test_rectangular_bar_runs_checks_and_renders_its_own_memorial():
    model = _model()
    result = verify_model(model)
    element = result["results"]["bar:R1"]

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    assert result["summary"]["unverified"] == 0
    assert element["status"] == "checked"
    assert all(check["status"] != "not_checked" for check in element["checks"].values())
    assert element["checks"]["flexion_y"]["parameters"]["strong_axis"] is True
    assert element["checks"]["flexion_z"]["parameters"]["strong_axis"] is False
    assert math.isclose(element["checks"]["axial_compression"]["parameters"]["Ney_kn"],
                        52.64, rel_tol=2e-3)
    assert math.isclose(element["checks"]["axial_compression"]["parameters"]["Nez_kn"],
                        13.16, rel_tol=2e-3)
    assert math.isclose(element["checks"]["axial_compression"]["parameters"]["Nc_Rd_kn"],
                        10.49, rel_tol=2e-3)
    for key, capacity in (("axial_tension", "Nt_Rd_kn"),
                          ("axial_compression", "Nc_Rd_kn"),
                          ("flexion_y", "MRd_kn_cm"), ("flexion_z", "MRd_kn_cm"),
                          ("shear_y", "VRd_kn"), ("shear_z", "VRd_kn")):
        value = element["checks"][key]["parameters"][capacity]
        assert value > 0.0 and math.isfinite(value)

    model.verification_results = result["results"]
    panel_context = type("Context", (), {"window": type("Window", (), {"model": model})()})()
    assert PropertyPanel._has_verification_routine(panel_context, ("R1",))
    html = CalculationMemorialDialog._render(calculation_memory(model, ("R1",)), {})
    assert "Barra Retangular" in html
    assert "5.5.2.3-b" in html
    assert "Flexão em Y" in html
    assert "Flexão em Z" in html
    assert "Cortante em Y" in html
    assert "Cortante em Z" in html
    assert "não implementada" not in html.lower()


def test_rectangular_bar_swapped_dimensions_assign_flt_to_the_strong_axis():
    for b, h in ((10.0, 20.0), (20.0, 10.0)):
        model = _model(b=b, h=h, loads={
            "x": 0.0, "axial": 0.0, "moment_y": 0.2, "moment_z": 0.2,
            "shear_y": 0.0, "shear_z": 0.0,
        })
        checks = verify_model(model)["results"]["bar:R1"]["checks"]
        assert checks["flexion_y"]["parameters"]["strong_axis"] is (h >= b)
        assert checks["flexion_z"]["parameters"]["strong_axis"] is (b > h)
        assert checks["flexion_y"]["status"] == "checked"
        assert checks["flexion_z"]["status"] == "checked"


def test_rectangular_bar_invalid_dimensions_are_reported_without_crashing():
    model = _model()
    model.update_member_profile("R1", "RET sem dimensões", {})
    result = verify_model(model)

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["unverified"] == 1
    assert result["results"]["bar:R1"]["checks"]["axial_compression"]["status"] == "not_checked"


def test_moment_gradient_factor_uses_nbr_quarter_points_for_a_constant_moment():
    from osa.verification.rectangular_bar import _moment_gradient_factor

    samples = [{"x": position, "moment_y": 1.0}
               for position in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert math.isclose(_moment_gradient_factor(samples, "moment_y"), 1.0)

    parabolic = [{"x": 0.0, "moment_y": 0.0}, {"x": 0.25, "moment_y": 0.75},
                 {"x": 0.5, "moment_y": 1.0}, {"x": 0.75, "moment_y": 0.75},
                 {"x": 1.0, "moment_y": 0.0}]
    assert math.isclose(_moment_gradient_factor(parabolic, "moment_y"), 12.5 / 11.0)


def test_rectangular_bar_extreme_aspect_ratios_keep_finite_capacities():
    for b, h, length in ((2.0, 100.0, 0.2), (100.0, 2.0, 6.0), (500.0, 25.0, 12.0)):
        result = verify_model(_model(b=b, h=h, length=length))
        checks = result["results"]["bar:R1"]["checks"]
        assert result["summary"]["unverified"] == 0
        for name in ("axial_compression", "flexion_y", "flexion_z", "shear_y", "shear_z"):
            check = checks[name]
            assert check["status"] in {"checked", "not_applicable"}
            if check["status"] == "checked":
                assert math.isfinite(check["utilization"])
                assert check["utilization"] >= 0.0


def test_axial_only_case_does_not_become_unverified_due_to_no_bending_demand():
    model = _model(loads={"x": 0.0, "axial": 5.0, "moment_y": 0.0,
                          "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0})
    result = verify_model(model)

    assert result["summary"]["unverified"] == 0
    checks = result["results"]["bar:R1"]["checks"]
    assert checks["flexion_y"]["status"] == "not_applicable"
    assert checks["flexion_z"]["status"] == "not_applicable"
    assert checks["flexocompressao"]["status"] == "checked"


def test_manual_calculation_properties_override_automatic_lengths_ct_and_cb():
    model = _model()
    model.update_bar_calculation_property("R1", "Ly", 1.25)
    model.update_bar_calculation_property("R1", "Lb", 1.5)
    model.update_bar_calculation_property("R1", "Ct", 0.75)
    model.update_bar_calculation_property("R1", "Cb", 1.8)

    checks = verify_model(model)["results"]["bar:R1"]["checks"]

    assert math.isclose(checks["axial_compression"]["parameters"]["Ly_cm"], 125.0)
    assert math.isclose(checks["flexion_y"]["parameters"]["Lb_cm"], 150.0)
    assert math.isclose(checks["axial_tension"]["parameters"]["Ct"], 0.75)
    assert math.isclose(checks["flexion_y"]["parameters"]["Cb"], 1.8)


def test_manual_calculation_property_validation_and_reset_to_automatic():
    model = _model()
    original_revision = model.revision
    original_result_revision = model.analysis_results[0].model_revision

    model.update_bar_calculation_property("R1", "Lb", 1.25)
    assert model.revision == original_revision
    assert model.analysis_results[0].model_revision == original_result_revision
    model.update_bar_calculation_property("R1", "Lb", None)
    assert "Lb" not in dict(model.bars["R1"].calculation_property_overrides)

    with pytest.raises(ValueError):
        model.update_bar_calculation_property("R1", "Cb", 0.5)
