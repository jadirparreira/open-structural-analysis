"""Reviewed rolled-family connection inputs and analysis-data integrity."""
import pytest

from osa.domain import AnalysisResult
from osa.model import StructuralModel
from osa.ui.verification_worker import verify_model


def rolled(family, axial=-1., geometry=None):
    model = StructuralModel()
    model.add_node("A", 0., 0., 0.)
    model.add_node("B", 0., 0., 3.)
    for node in ("A", "B"):
        model.update_node_supports(node, (True,)*6)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", family)
    model.update_bar_material("B1", "ASTM A36", model.materials["ASTM A36"])
    if geometry is None:
        geometry = {"b": 100., "t": 10.} if family == "L Laminado" else {"d": 203., "bf": 102., "tw": 5.8, "tf": 6.5}
    model.update_member_profile("B1", "Perfil de teste", geometry)
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"B1": {"samples": [{
        "x": 0., "axial": axial, "moment_y": 0., "moment_z": 0., "shear_y": 0., "shear_z": 0., "torque": 0.,
    }]}})]
    return model


def result(model):
    return verify_model(model)["results"]["bar:B1"]


@pytest.mark.parametrize("family", ["W Laminado", "HP Laminado", "I Laminado", "U Laminado", "L Laminado", "T Laminado"])
def test_all_rolled_tension_requires_connection_data_and_uses_manual_net_area(family):
    model = rolled(family)
    initial = result(model)
    assert initial["checks"]["axial_tension"]["status"] == "not_checked"
    assert "An" in initial["detail"]
    for key, value in (("An", 1.), ("Ct", .8)):
        model.update_bar_calculation_property("B1", key, value)
    tension = result(model)["checks"]["axial_tension"]
    assert tension["status"] == "checked"
    assert tension["parameters"]["An_cm2"] == 1.
    assert tension["parameters"]["Ae_cm2"] == .8
    assert tension["parameters"]["Nt_Rd2_kn"] == pytest.approx(.8*40/1.35)


@pytest.mark.parametrize("field", ["x", "axial", "moment_y", "moment_z", "shear_y", "shear_z", "torque"])
def test_missing_sample_field_prevents_worker_approval(field):
    model = rolled("W Laminado", axial=1.)
    del model.analysis_results[0].member_results["B1"]["samples"][0][field]
    item = result(model)
    assert item["status"] == "not_checked"
    assert item["checks"]["input_data"]["status"] == "not_checked"


def test_stale_results_do_not_approve_laminated_members():
    model = rolled("W Laminado", axial=1.)
    model.revision += 1
    assert result(model)["status"] == "not_checked"


def test_i_fla_uses_distinct_reference_and_respects_scope():
    model = rolled("I Laminado", axial=0., geometry={"d":455., "bf":150., "tw":3., "tf":10.})
    model.analysis_results[0].member_results["B1"]["samples"][0]["moment_y"] = 1.
    check = result(model)["checks"]["flexion_y"]
    assert check["status"] == "checked"
    p = check["parameters"]
    assert p["lambda_p_fla"] < p["lambda_fla"] < p["lambda_r_fla"]
    assert p["Mr_fla_kn_cm"] == pytest.approx(p["Wy_cm3"]*p["fy_kn_cm2"])
    model = rolled("I Laminado", axial=0., geometry={"d":700., "bf":150., "tw":3., "tf":10.})
    model.analysis_results[0].member_results["B1"]["samples"][0]["moment_y"] = 1.
    assert result(model)["checks"]["flexion_y"]["status"] == "not_checked"


@pytest.mark.parametrize("family", ["I Laminado", "U Laminado"])
def test_rolled_i_and_u_automatically_calculate_cb_from_the_adopted_lb(family):
    model = rolled(family, axial=0.)
    model.analysis_results[0].member_results["B1"]["samples"] = [{
        "x": 3.0 * index / 20,
        "axial": 0.0,
        "moment_y": 1.0 - abs(index / 10 - 1.0),
        "moment_z": 0.0,
        "shear_y": 0.0,
        "shear_z": 0.0,
        "torque": 0.0,
    } for index in range(21)]

    check = result(model)["checks"]["flexion_y"]
    assert check["parameters"]["Cb"] == pytest.approx(12.5 / 9.5)
    assert check["parameters"]["Cb_method"].startswith("automático")
    assert check["parameters"]["Cb_interval_m"] == pytest.approx((0.0, 3.0))


def test_strength_checks_use_elu_combinations_and_report_missing_design_results():
    from osa.domain import LoadCombination

    model = rolled("W Laminado", axial=1.)
    design = model.analysis_results[0]
    model.load_combinations = {
        "ELU": LoadCombination("ELU", (), limit_state="ELU"),
        "ELS": LoadCombination("ELS", (), limit_state="ELS"),
    }
    service = {**design.member_results["B1"]["samples"][0], "axial": 1.e9}
    model.analysis_results.append(AnalysisResult(model.revision, "ELS", member_results={"B1": {"samples": [service]}}))
    item = result(model)
    assert item["status"] == "checked" and item["utilization"] < 1.
    assert item["checks"]["axial_compression"]["critical_combination"] == "ELU"
    model.load_combinations["ELU2"] = LoadCombination("ELU2", (), limit_state="ELU")
    assert "ELU2" in result(model)["detail"]
    model.load_combinations = {"ELS": model.load_combinations["ELS"]}
    assert result(model)["status"] == "not_checked"
    assert "classificada como ELU" in result(model)["detail"]


@pytest.mark.parametrize(("fy", "fu"), [(460000., 600000.), (250000., 280000.)])
def test_8800_material_outside_nominal_limits_is_not_approved(fy, fu):
    model = rolled("W Laminado", axial=1.)
    values = list(model.materials["ASTM A36"])
    values[4], values[5] = fy, fu
    model.materials["ASTM A36"] = tuple(values)
    item = result(model)
    assert item["status"] == "not_checked"
    assert "4.6.2.2.1" in item["detail"]


def test_nonfinite_geometry_cannot_be_presented_as_a_checked_resistance():
    model = rolled("W Laminado", axial=1., geometry={"d": float("nan"), "bf": 100., "tw": 6., "tf": 8.})
    item = result(model)
    assert item["status"] == "not_checked"
    assert "não finitas" in item["detail"]
    assert "utilization" not in item


def test_laminated_memorial_reports_the_actual_governing_member_and_position():
    from osa.memorial_data import calculation_memory
    from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog

    model = rolled("W Laminado", axial=1.)
    base = model.analysis_results[0].member_results["B1"]["samples"][0]
    samples = [{**base, "x": .25, "axial": 10., "moment_y": 1.},
               {**base, "x": 1.75, "axial": 30., "moment_z": .3}]
    model.analysis_results[0].member_results["B1"]["samples"] = samples
    summary = result(model)
    assert summary["checks"]["axial_compression"]["critical_position_m"] == 1.75
    assert summary["checks"]["flexion_y"]["critical_position_m"] == .25
    assert summary["checks"]["flexion_z"]["critical_position_m"] == 1.75
    interaction = summary["checks"]["flexocompressao"]
    actual = next(sample for sample in samples if sample["x"] == interaction["critical_position_m"])
    assert interaction["applied_kn"] == abs(actual["axial"])
    assert interaction["applied_my_kn_cm"] == abs(actual["moment_y"])*100
    assert interaction["applied_mz_kn_cm"] == abs(actual["moment_z"])*100
    model.verification_results = {"bar:B1": summary}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("B1",)), {})
    assert "barra B1; x = 1,75 m" in html
    assert "barra B1; x = 0,25 m" in html
