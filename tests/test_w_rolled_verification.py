import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import _w_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.verification_worker import verify_model
from osa.verification.w_rolled import _compression_effective_area


def make_w_model(geometry=None, sample=None, length=3.0):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("W1", "A", "B")
    model.update_bar_material("W1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("W1", "W Laminado")
    model.update_member_profile(
        "W1", "W perfil de teste",
        geometry or {"d": 203.0, "bf": 102.0, "tw": 5.8, "tf": 6.5},
    )
    model.analysis_results = [AnalysisResult(
        model.revision, "ELU", member_results={
            "W1": {"samples": [sample or {
                "x": 0.0, "axial": 0.0, "moment_y": 1.0,
                "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0,
                "torque": 0.0,
            }]}
        },
    )]
    return model


def test_fla_has_its_own_mr_and_memorial_displays_it():
    model = make_w_model(
        {"d": 455.0, "bf": 150.0, "tw": 3.0, "tf": 10.0, "r": 10.0},
    )
    result = verify_model(model)["results"]["bar:W1"]
    flexion_y = result["checks"]["flexion_y"]
    p = flexion_y["parameters"]

    assert p["lambda_p_fla"] < p["lambda_fla"] < p["lambda_r_fla"]
    assert p["Mr_fla_kn_cm"] == pytest.approx(p["Wy_cm3"] * p["fy_kn_cm2"])
    assert p["Mr_fla_kn_cm"] != pytest.approx(p["Mr_kn_cm"])

    model.verification_results = result and {"bar:W1": result}
    memory = calculation_memory(model, ("W1",))
    equations = {}
    latex = {}
    html = CalculationMemorialDialog._render(memory, equations, equation_latex=latex)
    assert "M_{r,FLA}" in str(latex.values())
    assert "Mr_fla_kn_cm" not in html


def test_fla_above_lambda_r_is_not_reported_as_checked():
    model = make_w_model(
        {"d": 1000.0, "bf": 100.0, "tw": 2.0, "tf": 10.0, "r": 10.0},
    )
    flexion_y = verify_model(model)["results"]["bar:W1"]["checks"]["flexion_y"]

    assert flexion_y["status"] == "not_checked"
    assert flexion_y["parameters"]["lambda_fla"] > flexion_y["parameters"]["lambda_r_fla"]
    assert "não se aplica" in flexion_y["detail"]


def test_compression_effective_web_width_excludes_both_fillets():
    props = _compression_effective_area(
        {"d": 203.0, "bf": 102.0, "tw": 5.8, "tf": 6.5,
         "r": 10.0, "Ag_cm2": 28.0},
        elastic_kn_cm2=2000.0, fy_kn_cm2=25.0, chi=0.8,
    )
    assert props["web_width_mm"] == pytest.approx(170.0)


def test_rolled_cb_is_calculated_from_moments_in_the_adopted_unbraced_interval():
    from osa.verification.moment_gradient import moment_gradient_factor

    stations = [(x, 1.0 - abs(2.0 * x - 1.0)) for x in (0., .25, .5, .75, 1.)]
    assert moment_gradient_factor(stations, 0., 1.) == pytest.approx(12.5 / 9.5)
    reversing = [(0., 1.), (.3, -1.), (.7, -1.), (1., 1.)]
    assert moment_gradient_factor(reversing, 0., 1.) == pytest.approx(12.5 / 10.5)

    model = make_w_model(length=3.0)
    samples = [{
        "x": 3.0 * index / 20,
        "axial": 0.0,
        "moment_y": 1.0 - abs(index / 10 - 1.0),
        "moment_z": 0.0,
        "shear_y": 0.0,
        "shear_z": 0.0,
        "torque": 0.0,
    } for index in range(21)]
    model.analysis_results = [AnalysisResult(
        model.revision, "ELU", member_results={"W1": {"samples": samples}},
    )]
    checks = verify_model(model)["results"]["bar:W1"]["checks"]
    flexion = checks["flexion_y"]
    assert flexion["parameters"]["Cb"] > 1.0
    assert flexion["parameters"]["Cb_method"].startswith("automático")
    assert flexion["parameters"]["Cb_interval_m"] == pytest.approx((0.0, 3.0))

    model.update_bar_calculation_property("W1", "Cb", 1.25)
    manual = verify_model(model)["results"]["bar:W1"]["checks"]["flexion_y"]
    assert manual["parameters"]["Cb"] == pytest.approx(1.25)
    assert manual["parameters"]["Cb_method"] == "manual"

    model.update_bar_calculation_property("W1", "Cb", None)
    model.update_bar_calculation_property("W1", "Lb", 2.0)
    manual_lb = verify_model(model)["results"]["bar:W1"]["checks"]["flexion_y"]
    assert manual_lb["parameters"]["Cb"] == pytest.approx(1.0)
    assert manual_lb["parameters"]["Cb_method"].startswith("fallback Lb definido manualmente")


def test_rolled_cb_expression_is_shown_in_the_calculation_memorial():
    from osa.memorial_data import calculation_memory

    model = make_w_model(length=3.0)
    samples = [{
        "x": 3.0 * index / 20,
        "axial": 0.0,
        "moment_y": 1.0 - abs(index / 10 - 1.0),
        "moment_z": 0.0,
        "shear_y": 0.0,
        "shear_z": 0.0,
        "torque": 0.0,
    } for index in range(21)]
    model.analysis_results = [AnalysisResult(
        model.revision, "ELU", member_results={"W1": {"samples": samples}},
    )]
    model.verification_results = verify_model(model)["results"]
    equations = {}
    CalculationMemorialDialog._render(
        calculation_memory(model, ("W1",)), equation_latex=equations,
    )
    assert any("C_b" in str(latex) for latex in equations.values())


def test_flexion_z_resistance_is_available_when_z_moment_is_zero():
    model = make_w_model()
    result = verify_model(model)["results"]["bar:W1"]
    flexion_z = result["checks"]["flexion_z"]

    assert flexion_z["status"] == "not_applicable"
    assert flexion_z["parameters"]["Mrd_z_kn_cm"] > 0.0
    assert result["checks"]["flexocompressao"]["parameters"]["Mz_Rd_kn_cm"] > 0.0


def test_simultaneous_w_shears_do_not_add_an_unverified_status():
    model = make_w_model(sample={
        "x": 0.0, "axial": 0.0, "moment_y": 1.0, "moment_z": 0.0,
        "shear_y": 10.0, "shear_z": 10.0, "torque": 0.0,
    })
    result = verify_model(model)
    element = result["results"]["bar:W1"]
    assert element["status"] == "checked"
    assert result["summary"]["unverified"] == 0
    assert "scope_warnings" not in element


def test_small_shear_solver_residuals_do_not_mark_w_member_as_unverified():
    model = make_w_model(sample={
        "x": 0.0, "axial": 0.0, "moment_y": 0.0, "moment_z": 0.0,
        "shear_y": 0.12, "shear_z": 0.28, "torque": 0.0,
    })
    element = verify_model(model)["results"]["bar:W1"]

    assert element["status"] == "checked"
    assert "scope_warnings" not in element


@pytest.mark.parametrize("moment_y, rejected", [(1.0, False), (10000.0, True)])
def test_torsion_does_not_change_member_approval_or_rejection(moment_y, rejected):
    sample = {
        "x": 1.0, "axial": 0.0, "moment_y": moment_y, "moment_z": 0.0,
        "shear_y": 0.0, "shear_z": 0.0, "torque": 0.0,
    }
    without_torsion = make_w_model(sample=sample)
    baseline = verify_model(without_torsion)

    with_torsion = make_w_model(sample={**sample, "torque": 20.0})
    verification = verify_model(with_torsion)
    element = verification["results"]["bar:W1"]
    reference = baseline["results"]["bar:W1"]

    assert element["status"] == reference["status"]
    assert element["torsion_summary"]["has_torsion"]
    assert "torção não verificada" not in element["detail"]
    assert verification["summary"]["approved"] == baseline["summary"]["approved"]
    assert verification["summary"]["unverified"] == baseline["summary"]["unverified"]
    assert verification["summary"]["rejected"] == baseline["summary"]["rejected"]
    assert verification["summary"]["rejected"] == int(rejected)


def test_recommended_slenderness_limit_does_not_change_the_check_status():
    model = make_w_model(length=10.0, sample={
        "x": 0.0, "axial": 1.0, "moment_y": 1.0, "moment_z": 0.0,
        "shear_y": 0.0, "shear_z": 0.0, "torque": 0.0,
    })
    result = verify_model(model)
    element = result["results"]["bar:W1"]

    assert element["checks"]["axial_compression"]["parameters"]["slenderness_z"] > 200.0
    assert element["status"] == "checked"
    assert result["summary"]["unverified"] == 0
    assert "advisory_warnings" not in element


def test_memorial_shows_the_w_rolled_radius():
    model = make_w_model()
    model.verification_results = verify_model(model)["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("W1",)), {})

    assert "Raio de concordância adotado (r)" in html
    assert _w_properties(model.bars["W1"])["r"] == 10.0
