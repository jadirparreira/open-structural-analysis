import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import _u_properties, calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.verification_worker import verify_model


def test_catalog_u_profile_without_optional_radii_is_verified():
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 3.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", "U Laminado")
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
    model.verification_results = result["results"]
    memorial = CalculationMemorialDialog._render(
        calculation_memory(model, ("U1",)), {},
    )
    assert "Torção — ABNT NBR 8800:2024, 5.5.2.3" in memorial
    assert "Nenhuma combinação analisada apresentou solicitação de torção" in memorial


def test_slender_web_u_is_unverified_when_annex_e_has_no_u_procedure():
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

    assert result["status"] == "not_checked"
    assert "utilization" not in result
    assert result["combinations"] == []
    assert "Anexo E não fornece procedimento de resistência para perfis U laminados" in result["detail"]
    assert result["parameters"]["slender_web_not_verified"]
    for check_name in ("flexao_obliqua", "flexotracao", "flexocompressao"):
        combined = element["checks"][check_name]
        assert combined["status"] == "not_checked"
        assert combined["parameters"]["slender_web_not_verified"]
    assert verification["summary"]["rejected"] == 0
    assert verification["summary"]["unverified"] == 1

    model.verification_results = verification["results"]
    equation_objects = {}
    memorial = CalculationMemorialDialog._render(
        calculation_memory(model, ("U1",)), equation_objects,
    )
    assert "Verificação combinada reprovada" not in memorial
    assert "Anexo E" in memorial
    assert "Não verificado" in memorial
    assert equation_objects


def test_significant_torsion_is_informational_and_does_not_count_as_unverified():
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 3.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", "U Laminado")
    model.update_member_profile(
        "U1", "U 76 x 6.1", {"d": 76.2, "bf": 35.81, "tw": 4.32, "tf": 6.93},
    )
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU-torção",
        member_results={"U1": {"samples": [{"x": 1.5, "torque": 0.2}]}},
    )]

    verification = verify_model(model)
    element = verification["results"]["bar:U1"]

    assert element["status"] == "not_applicable"
    assert "torsion" not in element["checks"]
    assert element["torsion_summary"]["has_torsion"]
    assert verification["summary"]["approved"] == 0
    assert verification["summary"]["unverified"] == 0

    model.verification_results = verification["results"]
    memorial = CalculationMemorialDialog._render(
        calculation_memory(model, ("U1",)), {},
    )
    assert "Foi detectado uma torção de 0,2 kN·m" in memorial
    assert "Solicitação não verificada" in memorial


def test_u_simultaneous_shear_is_not_a_separate_check():
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 3.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", "U Laminado")
    model.update_member_profile(
        "U1", "U 203,20 × 17,10",
        {"d": 203.2, "bf": 57.4, "tw": 5.59, "tf": 9.5},
    )
    model.analysis_results = [AnalysisResult(
        model.revision,
        "Combinação 02",
        member_results={"U1": {"samples": [{
            "x": 0.0,
            "shear_y": 12.9830991405,
            "shear_z": 3.4848091440,
        }]}},
    )]

    verification = verify_model(model)
    element = verification["results"]["bar:U1"]
    assert "shear_y" in element["checks"]
    assert "shear_z" in element["checks"]
    assert "biaxial_shear" not in element["checks"]
    assert "biaxial_shear_summary" not in element

    model.verification_results = verification["results"]
    equation_objects = {}
    memorial = CalculationMemorialDialog._render(
        calculation_memory(model, ("U1",)), equation_objects,
    )
    assert "cortantes simultâneos" not in memorial.lower()


def test_u_member_slenderness_is_reported_but_does_not_decide_approval():
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, 30.0)
    model.update_node_supports("A", (True,) * 6)
    model.update_node_supports("B", (True,) * 6)
    model.add_bar("U1", "A", "B")
    model.update_bar_material("U1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("U1", "U Laminado")
    model.update_member_profile(
        "U1", "U 76 x 6.1", {"d": 76.2, "bf": 35.81, "tw": 4.32, "tf": 6.93},
    )
    model.analysis_results = [AnalysisResult(
        model.revision,
        "ELU-sem-esforcos",
        member_results={"U1": {"samples": [{
            "x": 0.0, "axial": 0.0, "moment_y": 0.0, "moment_z": 0.0,
            "shear_y": 0.0, "shear_z": 0.0, "torque": 0.0,
        }]}},
    )]

    verification = verify_model(model)
    element = verification["results"]["bar:U1"]
    slenderness = element["checks"]["slenderness"]

    assert slenderness["parameters"]["lambda_z"] > slenderness["parameters"]["compression_limit"]
    assert element["status"] == "not_applicable"
    assert verification["summary"]["rejected"] == 0
    assert verification["summary"]["unverified"] == 0
