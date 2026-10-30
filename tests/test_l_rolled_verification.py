import math
from zipfile import ZipFile

import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import _l_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.memorial_docx_export import export_calculation_memorial_docx
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
    assert "Flexão em Y — hipótese para cantoneira simples" in html
    assert "interação preliminar com capacidades estimadas" not in html
    assert "não implementada" not in html.lower()


@pytest.mark.parametrize(("b", "t", "length"), ((25.4, 3.17, 0.5), (152.4, 19.0, 8.0), (100.0, 2.0, 15.0)))
def test_l_section_limit_geometries_do_not_crash_or_return_nonfinite_resistance(b, t, length):
    model = _model(b=b, t=t, length=length)
    result = verify_model(model)
    element = result["results"]["bar:L1"]

    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["without_routine"] == 0
    for check_name in ("axial_compression", "flexion_y", "flexion_z", "shear_y", "shear_z"):
        check = element["checks"][check_name]
        assert check["status"] in {"checked", "not_applicable", "not_checked"}
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


def test_mcalc_plastic_example_for_both_axes_with_independent_section_values():
    # L 100x10 mm: split into non-overlapping rectangles, with the plastic
    # neutral axis at 9.5 mm from the outside edge; Z = 45.475 cm³.
    checks = verify_model(_model())["results"]["bar:L1"]["checks"]
    for axis in ("y", "z"):
        flex = checks[f"flexion_{axis}"]["parameters"]
        shear = checks[f"shear_{axis}"]["parameters"]
        assert flex["Z_cm3"] == pytest.approx(45.475)
        assert flex["W_cm3"] == pytest.approx(25.24046740467405)
        assert flex["lambda_p"] == pytest.approx(1.12 * math.sqrt(20000 / 25))
        assert flex["lambda_r"] == pytest.approx(1.40 * math.sqrt(20000 / 25))
        assert flex["Mpl_kn_cm"] == pytest.approx(45.475 * 25)
        assert flex["MRd_kn_cm"] == pytest.approx(45.475 * 25 / 1.1)
        assert flex["Mcr_kn_cm"] == pytest.approx(.69 * 20000 * flex["W_cm3"] / 10**2)
        assert shear["kv"] == 5.0
        assert shear["Aw_cm2"] == 10.0
        assert shear["VRd_kn"] == pytest.approx(.60 * 10 * 25 / 1.1)


def test_isolated_axes_keep_their_demands_and_memorial_moment_units():
    model = _model(loads={"x": 0., "moment_y": -2., "moment_z": .25,
                          "shear_y": 3., "shear_z": -1.})
    checks = verify_model(model)["results"]["bar:L1"]["checks"]
    assert checks["flexion_y"]["applied_kn_cm"] == 200.
    assert checks["flexion_z"]["applied_kn_cm"] == 25.
    assert checks["flexion_y"]["utilization"] == pytest.approx(8 * checks["flexion_z"]["utilization"])
    assert checks["shear_y"]["utilization"] == pytest.approx(3 * checks["shear_z"]["utilization"])


def test_unknown_nonplastic_regimes_do_not_report_a_resistance():
    checks = verify_model(_model(t=1.))["results"]["bar:L1"]["checks"]
    for kind in ("flexion", "shear"):
        for axis in ("y", "z"):
            check = checks[f"{kind}_{axis}"]
            assert check["status"] == "not_checked"
            assert "não disponíveis" in check["detail"]
            assert "MRd_kn_cm" not in check["parameters"]
            assert "VRd_kn" not in check["parameters"]
    for kind in ("oblique_bending", "flexotension", "flexocompression"):
        if kind in checks:
            assert checks[kind]["status"] == "not_checked"


def test_l_memorial_documents_mcalc_and_exposes_limitations():
    model = _model()
    model.verification_results = verify_model(model)["results"]
    latex = {}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {}, equation_latex=latex)
    equations = "\n".join(latex.values())
    assert "Flexão em Y — hipótese para cantoneira simples" in html
    assert "Cortante em Y — hipótese para cantoneira simples" in html
    assert "MCalc" not in html
    assert "aplicado por analogia" not in html
    assert "Flexocompressão — critério da ABNT NBR 8800:2024, 5.5.1.2" in html
    assert "AISC" not in html
    assert r"M_{pl}" in equations
    assert r"M_{Rk}" in equations
    assert r"V_{Rk}" in equations
    flexion = html.split("Flexão em Y — hipótese para cantoneira simples", 1)[1].split("Flexão em Z —", 1)[0]
    assert "Anexo D" not in flexion


def test_l_memorial_docx_exports_mcalc_equations(tmp_path):
    model = _model()
    model.verification_results = verify_model(model)["results"]
    latex = {}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {}, equation_latex=latex)
    path = export_calculation_memorial_docx(html, latex, tmp_path / "L-memorial.docx")
    with ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml").decode()
    assert "MCalc" not in document_xml
    assert "AISC" not in document_xml
    assert document_xml.count("<m:oMath>") >= 20


def test_old_l_results_request_reverification_instead_of_crashing_the_memorial():
    model = _model()
    model.verification_results = verify_model(model)["results"]
    checks = model.verification_results["bar:L1"]["checks"]
    for axis in ("y", "z"):
        checks[f"flexion_{axis}"]["parameters"].pop("method_version")
        checks[f"shear_{axis}"]["parameters"].pop("method_version")
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {})
    assert "atualizar os resultados de flexão do L Laminado" in html
    assert "atualizar os resultados de cortante do L Laminado" in html


def test_compression_principal_axes_and_flexotorsion_with_independent_values():
    # L 100x10, E=20000, G=7692.3077 kN/cm², fy=25. Principal
    # inertias are obtained from the two rectangles forming the L.
    model = _model(length=3.)
    p = verify_model(model)["results"]["bar:L1"]["checks"]["axial_compression"]["parameters"]
    assert p["Iy_cm4"] == pytest.approx(286.5833333333333)
    assert p["Iz_cm4"] == pytest.approx(73.42543859649123)
    assert p["Ney_kn"] == pytest.approx(math.pi**2 * 20000 * 286.5833333333333 / 300**2)
    assert p["Nez_kn"] == pytest.approx(math.pi**2 * 20000 * 73.42543859649123 / 300**2)
    summed = p["Ney_kn"] + p["Net_kn"]
    coupled = summed / (2 * p["H_flexotorsion"]) * (
        1 - math.sqrt(1 - 4 * p["Ney_kn"] * p["Net_kn"] * p["H_flexotorsion"] / summed**2)
    )
    assert p["Ne_flexotorsao_kn"] == pytest.approx(coupled)
    assert p["Ne_kn"] == pytest.approx(min(p["Nez_kn"], coupled))
    assert p["lambda0"] == pytest.approx(math.sqrt(19 * 25 / p["Ne_kn"]))
    assert p["chi"] == pytest.approx(.877 / p["lambda0"]**2)
    assert p["Aef_cm2"] == pytest.approx(19.)
    assert p["Nc_Rd_kn"] == pytest.approx(p["chi"] * 19 * 25 / 1.1)


def test_compression_uses_each_supplied_length_and_reduces_slender_leg_area():
    model = _model(t=5., length=.2)
    model.update_bar_calculation_property("L1", "Ly", .2)
    model.update_bar_calculation_property("L1", "Lz", .4)
    model.update_bar_calculation_property("L1", "Lt", .3)
    p = verify_model(model)["results"]["bar:L1"]["checks"]["axial_compression"]["parameters"]
    assert (p["Ly_cm"], p["Lz_cm"], p["Lt_cm"]) == pytest.approx((20., 40., 30.))
    assert p["Ney_kn"] == pytest.approx(math.pi**2 * p["E_kn_cm2"] * p["Iy_cm4"] / 20**2)
    assert p["Nez_kn"] == pytest.approx(math.pi**2 * p["E_kn_cm2"] * p["Iz_cm4"] / 40**2)
    assert p["Net_kn"] == pytest.approx(p["G_kn_cm2"] * p["It_cm4"] / p["r0_cm"]**2)
    assert p["lambda0"] < 1.5
    assert p["chi"] == pytest.approx(.658**p["lambda0"]**2)
    sigma = (1.49 * p["leg_limit"] / p["leg_slenderness"])**2 * p["fy_kn_cm2"]
    ratio = sigma / (p["chi"] * p["fy_kn_cm2"])
    bef = p["b_mm"] * (1 - .22 * math.sqrt(ratio)) * math.sqrt(ratio)
    assert p["leg_effective_width_mm"] == pytest.approx(bef)
    assert p["Aef_cm2"] == pytest.approx(p["Ag_cm2"] - 2 * (p["b_mm"] - bef) * p["t_mm"] / 100)
    assert p["Aef_cm2"] < p["Ag_cm2"]


def test_compression_memorial_shows_actual_branches_and_principal_axes():
    model = _model(t=5., length=.2)
    model.verification_results = verify_model(model)["results"]
    latex = {}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("L1",)), {}, equation_latex=latex)
    section = html.split("Compressão axial —", 1)[1].split("Flexão em Y —", 1)[0]
    equations = "\n".join(latex.values())
    assert "Na formulação adotada" not in section
    assert r"I_{principal,\mathrm{simetria}}" in equations
    assert r"N_{pl}" in equations
    assert r"0,658^{\lambda_0^2}" in equations
    assert r"\dfrac{\sigma_{el}}{\chi f_y}" in equations
    assert "MCalc" not in section
