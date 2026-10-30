import math
from types import SimpleNamespace

from osa.domain import AnalysisResult
from osa.memorial_data import _t_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.property_panel import PropertyPanel
from osa.ui.verification_worker import verify_model


def _model(d=50.8, bf=50.8, tw=6.35, tf=6.35, length=1.0, loads=None):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("T1", "A", "B")
    model.update_bar_material("T1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("T1", "T Laminado")
    model.update_member_profile(
        "T1", f"T {d:g} x {bf:g} x {tw:g} x {tf:g}",
        {"d": d, "bf": bf, "tw": tw, "tf": tf},
    )
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU",
        member_results={"T1": {"samples": [loads or {
            "x": 0.0, "axial": 10.0, "moment_y": 1.0, "moment_z": 0.0,
            "shear_y": 1.0, "shear_z": 0.0,
        }]}},
    )]
    return model


def test_t_profile_runs_checks_and_renders_its_own_memorial():
    model = _model()
    panel_context = SimpleNamespace(window=SimpleNamespace(model=model))
    properties = _t_properties(model.bars["T1"])
    result = verify_model(model)
    element = result["results"]["bar:T1"]

    assert properties["area"] > 0.0
    assert properties["Iy"] > properties["Iz"] > 0.0
    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    assert result["summary"]["unverified"] == 0
    assert math.isclose(
        element["checks"]["shear_y"]["parameters"]["VRd_kn"], 43.99,
        rel_tol=2e-3,
    )
    assert PropertyPanel._has_verification_routine(panel_context, ("T1",))
    assert element["status"] == "checked"
    assert all(check["status"] != "not_checked" for check in element["checks"].values())
    for name, capacity_key in (
        ("axial_tension", "Nt_Rd_kn"), ("axial_compression", "Nc_Rd_kn"),
        ("flexion_y", "MRd_kn_cm"), ("flexion_z", "MRd_kn_cm"),
        ("shear_y", "VRd_kn"), ("shear_z", "VRd_kn"),
    ):
        capacity = element["checks"][name]["parameters"][capacity_key]
        if element["checks"][name]["status"] == "checked":
            assert capacity > 0.0 and math.isfinite(capacity)

    model.verification_results = result["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
    assert "T Laminado" in html
    assert "5.4.1.1-c" in html
    assert "D.2.3" in html
    assert "5.4.3.3" in html
    assert "Memória de Cálculo - perfil t" not in html.lower()
    assert "mcalc" not in html.lower()


def test_t_second_axis_bending_and_shear_have_finite_resistances():
    model = _model(loads={
        "x": 0.0, "axial": 0.0, "moment_y": 0.0, "moment_z": 2.0,
        "shear_y": 0.0, "shear_z": 50.0,
    })
    result = verify_model(model)
    element = result["results"]["bar:T1"]
    model.verification_results = result["results"]
    equations = {}
    html = CalculationMemorialDialog._render(
        calculation_memory(model, ("T1",)), equations,
    )

    assert element["status"] == "checked"
    assert result["summary"]["rejected"] == 1
    assert element["checks"]["flexion_z"]["status"] == "checked"
    assert math.isfinite(element["checks"]["flexion_z"]["utilization"])
    assert element["checks"]["flexion_z"]["parameters"]["MRd_kn_cm"] > 0.0
    assert element["checks"]["shear_z"]["status"] == "checked"
    assert math.isfinite(element["checks"]["shear_z"]["utilization"])
    assert element["checks"]["shear_z"]["parameters"]["VRd_kn"] > 0.0
    assert math.isclose(element["checks"]["shear_z"]["parameters"]["VRd_kn"], 38.49,
                        rel_tol=2e-3)
    assert equations
    assert any(b"REPROVADO" in svg for svg in equations.values())
    assert "não inclui perfil T" not in html.lower()
    assert "não deve ser interpretado" not in html.lower()


def test_t_extreme_geometries_return_finite_resistances():
    for dimensions in ((15.88, 15.88, 3.18, 3.18), (127.0, 76.2, 6.0, 8.0),
                       (500.0, 100.0, 2.0, 5.0)):
        model = _model(*dimensions, length=8.0)
        result = verify_model(model)
        checks = result["results"]["bar:T1"]["checks"]
        for name in ("axial_compression", "flexion_y", "flexion_z", "shear_y", "shear_z"):
            check = checks[name]
            assert check["status"] in {"checked", "not_applicable"}
            if check["status"] == "checked":
                assert math.isfinite(check["utilization"])
                assert check["utilization"] >= 0.0


def test_t_web_shear_and_compression_use_the_current_nbr_dimensions():
    model = _model(loads={"x": 0., "axial": 10., "moment_y": 1., "moment_z": 0.,
                          "shear_y": 1., "shear_z": 0.})
    checks = verify_model(model)["results"]["bar:T1"]["checks"]
    shear = checks["shear_y"]["parameters"]
    compression = checks["axial_compression"]["parameters"]
    assert math.isclose(shear["lambda"], 8.0)
    assert math.isclose(shear["Aw_cm2"], 5.08 * .635)
    assert math.isclose(shear["VRd_kn"], .6 * 5.08 * .635 * 25 / 1.1)
    assert math.isclose(compression["flange_width_mm"], 50.8 / 2)
    assert math.isclose(compression["web_width_mm"], 50.8)
    assert math.isclose(compression["flange_slenderness"], 4.0)
    assert math.isclose(compression["web_slenderness"], 8.0)


def test_t_strong_flexure_respects_limit_and_flm_uses_compression_fiber():
    model = _model()
    p = verify_model(model)["results"]["bar:T1"]["checks"]["flexion_y"]["parameters"]
    assert p["Wxc_cm3"] > p["Wxt_cm3"]
    assert math.isclose(p["Mr_flm_kn_cm"], min(.7 * 25 * p["Wxc_cm3"], 25 * p["Wxt_cm3"]))
    assert math.isclose(p["Mcr_flm_kn_cm"], .7 * 20000 * p["Wxc_cm3"] / p["lambda_flm"]**2)
    assert math.isclose(p["MRd_limit_kn_cm"], 1.5 * p["Wy_cm3"] * 25 / 1.1)
    assert p["MRd_tension_kn_cm"] <= p["MRd_limit_kn_cm"]
    assert p["MRd_compression_kn_cm"] <= p["MRd_limit_kn_cm"]
    assert p["rz_cm"] > 0.


def test_t_combined_memory_matches_interaction_with_two_moments():
    model = _model(loads={"x": 0., "axial": 30., "moment_y": 1., "moment_z": 1.,
                          "shear_y": 1., "shear_z": 1.})
    model.verification_results = verify_model(model)["results"]
    check = model.verification_results["bar:T1"]["checks"]["flexocompressao"]
    p = check["parameters"]
    ratio_n = check["applied_kn"] / p["N_Rd_kn"]
    moments = check["applied_my_kn_cm"] / p["My_Rd_kn_cm"] + check["applied_mz_kn_cm"] / p["Mz_Rd_kn_cm"]
    expected = ratio_n + 8 / 9 * moments if ratio_n >= .2 else ratio_n / 2 + moments
    assert math.isclose(check["utilization"], expected)
    latex = {}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {}, equation_latex=latex)
    assert "hipótese com base na ABNT NBR 8800:2024" in html
    assert any(r"M_{z,Sd}" in equation and r"M_{y,Sd}" in equation for equation in latex.values())
    assert not any(r"\\infty" in equation for equation in latex.values())


def test_t_interaction_uses_moment_resistance_for_each_sample_sign():
    model = _model()
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"T1": {"samples": [
        {"x": 0., "axial": 0., "moment_y": 2., "moment_z": 0.},
        {"x": 1., "axial": 70., "moment_y": -1., "moment_z": 0.},
    ]}})]
    checks = verify_model(model)["results"]["bar:T1"]["checks"]
    p = checks["flexion_y"]["parameters"]
    check = checks["flexocompressao"]
    assert p["MRd_tension_kn_cm"] > p["MRd_compression_kn_cm"]
    assert check["applied_kn"] == 70.
    assert math.isclose(check["parameters"]["My_Rd_kn_cm"], p["MRd_compression_kn_cm"])


def test_t_slenderness_recommendations_are_shown():
    model = _model()
    model.verification_results = verify_model(model)["results"]
    p = model.verification_results["bar:T1"]["slenderness_summary"]["parameters"]
    assert math.isclose(p["lambda_y"], p["Ly_cm"] / p["ry_cm"])
    assert math.isclose(p["lambda_z"], p["Lz_cm"] / p["rz_cm"])
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
    assert "Esbeltez na tração" in html
    assert "Esbeltez na compressão" in html


def test_t_shear_outside_nbr_limit_is_not_verified():
    model = _model(d=600., bf=100., tw=2., tf=5.)
    check = verify_model(model)["results"]["bar:T1"]["checks"]["shear_y"]
    assert check["status"] == "not_checked"
    assert "260" in check["detail"]


def test_t_memorial_reports_absent_axial_forces():
    for axial, absent in ((0.0, ("tração", "compressão")),
                          (10.0, ("tração",)), (-10.0, ("compressão",))):
        model = _model(loads={"x": 0.0, "axial": axial, "moment_y": 0.0,
                              "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0})
        model.verification_results = verify_model(model)["results"]
        html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
        for name in absent:
            assert f"nenhuma combinação apresentou {name} axial" in html
        assert "A rotina atual de tração axial atende somente" not in html
        assert "A rotina atual de compressão axial atende somente" not in html


def test_t_memorial_reports_absent_bending_shear_and_combined_forces():
    model = _model(loads={"x": 0.0, "axial": 0.0, "moment_y": 0.0,
                          "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0})
    model.verification_results = verify_model(model)["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
    for mode in ("flexão em Y", "flexão em Z", "cortante em Y", "cortante em Z"):
        assert f"nenhuma combinação apresentou {mode}" in html
    assert html.count("nenhum esforço combinado aplicável") == 3
    assert "A rotina atual de flexão" not in html
    assert "A rotina atual de cortante" not in html


def test_t_memorial_reports_only_missing_directions():
    model = _model(loads={"x": 0.0, "axial": 0.0, "moment_y": 1.0,
                          "moment_z": 0.0, "shear_y": 0.0, "shear_z": 1.0})
    model.verification_results = verify_model(model)["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
    assert "nenhuma combinação apresentou flexão em Z" in html
    assert "nenhuma combinação apresentou cortante em Y" in html
    assert "nenhuma combinação apresentou flexão em Y" not in html
    assert "nenhuma combinação apresentou cortante em Z" not in html


def test_t_oblique_bending_is_not_applicable_under_axial_force_only():
    model = _model(loads={"x": 0.0, "axial": 10.0, "moment_y": 0.0,
                          "moment_z": 0.0, "shear_y": 0.0, "shear_z": 0.0})
    result = verify_model(model)
    check = result["results"]["bar:T1"]["checks"]["flexao_obliqua"]
    assert check["status"] == "not_applicable"
    assert check["detail"] == "nenhum esforço combinado aplicável"


def test_t_memorial_displays_specific_unchecked_shear_reason():
    model = _model(d=600., bf=100., tw=2., tf=5.)
    model.verification_results = verify_model(model)["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {})
    assert "d/tw excede 260" in html
    assert "A rotina atual de cortante em Y atende somente" not in html
