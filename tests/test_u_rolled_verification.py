import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import _u_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.verification_worker import verify_model


@pytest.mark.parametrize("family", ("U Laminado", "U Inclinado Laminado"))
def test_catalog_u_profile_without_optional_radii_is_verified(family):
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 3.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", family)
    model.update_member_profile(
        "U1", "U 76 x 6.1", {"d": 76.2, "bf": 35.81, "tw": 4.32, "tf": 6.93},
    )
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU",
        member_results={"U1": {"samples": [{
            "x": 0.0,
            "axial": 10.0,
            "moment_y": 1.0,
            "moment_z": 0.5,
            "shear_y": 1.0,
            "shear_z": 1.0,
        }]}},
    )]

    properties = _u_properties(model.bars["U1"])
    result = verify_model(model)
    element = result["results"]["bar:U1"]

    assert properties["area"] > 0.0
    assert properties["Zz"] > 0.0
    assert result["summary"]["with_routine"] == 1
    assert result["summary"]["unverified"] == 0
    assert element["status"] == "checked"
    assert all(
        check["status"] != "not_checked"
        for check in element["checks"].values()
    )
    weak_axis = element["checks"]["flexion_z"]["parameters"]
    assert weak_axis["Mrd_flm_z_kn_cm"] > 0.0
    assert weak_axis["Mrd_fla_z_kn_cm"] > 0.0
    assert weak_axis["Mrd_z_kn_cm"] == pytest.approx(min(
        weak_axis["Mrd_flm_z_kn_cm"],
        weak_axis["Mrd_fla_z_kn_cm"],
        weak_axis["Mrd_limit_kn_cm"],
    ))


def test_slender_web_u_is_rejected_without_explanatory_memorial_comments():
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 3.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", "U Laminado")
    model.update_member_profile(
        "U1", "U esbelto", {"d": 1000.0, "bf": 100.0, "tw": 2.0, "tf": 10.0},
    )
    model.analysis_results = [
        AnalysisResult(
            model.revision,
            "ELU-compressão",
            member_results={"U1": {"samples": [{
                "x": 0.0, "axial": 10.0, "moment_y": 1.0, "moment_z": 0.5,
            }]}},
        ),
        AnalysisResult(
            model.revision,
            "ELU-tração",
            member_results={"U1": {"samples": [{
                "x": 0.0, "axial": -10.0, "moment_y": 1.0, "moment_z": 0.5,
            }]}},
        ),
        AnalysisResult(
            model.revision,
            "ELU-flexão biaxial",
            member_results={"U1": {"samples": [{
                "x": 0.0, "axial": 0.0, "moment_y": 1.0, "moment_z": 0.5,
            }]}},
        ),
    ]

    verification = verify_model(model)
    element = verification["results"]["bar:U1"]
    result = element["checks"]["flexion_y"]

    assert result["status"] == "checked"
    assert result["utilization"] > 1.0
    assert result["combinations"][0]["status"] == "REPROVADO"
    assert "Anexo E não abrange perfis U laminados" in result["detail"]
    for check_name in ("flexao_obliqua", "flexotracao", "flexocompressao"):
        combined = element["checks"][check_name]
        assert combined["status"] == "checked"
        assert combined["utilization"] > 1.0
        assert combined["parameters"]["slender_web_rejected"]
    assert verification["summary"]["rejected"] == 1

    model.verification_results = verification["results"]
    equation_objects = {}
    memorial = CalculationMemorialDialog._render(
        calculation_memory(model, ("U1",)), equation_objects,
    )
    assert "REPROVADO" in memorial or any(
        "REPROVADO" in str(equation) for equation in equation_objects.values()
    )
    assert "Verificação combinada reprovada" not in memorial
    assert "Anexo E" not in memorial
    assert "excede o limite de esbeltez" not in memorial
    assert "Não verificado" not in memorial
    assert equation_objects
