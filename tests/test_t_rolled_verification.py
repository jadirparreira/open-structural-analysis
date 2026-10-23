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
        element["checks"]["shear_y"]["parameters"]["VRd_kn"], 87.98,
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
