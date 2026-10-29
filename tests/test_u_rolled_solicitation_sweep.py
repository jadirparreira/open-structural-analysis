"""Deterministic integration sweep for varied U-rolled member solicitations."""

import json
import random
from pathlib import Path

from osa.domain import AnalysisResult
from osa.memorial_data import calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.verification_worker import verify_model


def test_two_thousand_distinct_solicitations_across_the_u_profile_catalog():
    catalog_path = Path(__file__).parents[1] / "osa/data/sections_steel.json"
    catalogs = json.loads(catalog_path.read_text(encoding="utf-8"))
    u_catalog = next(item for item in catalogs["families"] if item["name"] == "U Laminado")
    profiles = u_catalog["profiles"]
    assert len(profiles) == 12

    # 8 sections receive 167 combinations and 4 receive 166: exactly 2,000.
    per_profile = [167] * 8 + [166] * 4
    rng = random.Random(8800)
    all_signatures = set()
    total_cases = 0
    torsion_cases = 0
    representative_model = None
    representative_verification = None

    for profile_index, (profile, case_count) in enumerate(zip(profiles, per_profile)):
        model = StructuralModel()
        model.add_node("A", 0.0, 0.0, 0.0)
        model.add_node("B", 0.0, 0.0, 3.0)
        model.update_node_supports("A", (True,) * 6)
        model.update_node_supports("B", (True,) * 6)
        member_name = f"U{profile_index + 1}"
        model.add_bar(member_name, "A", "B")
        model.update_bar_material(member_name, "ASTM A36", model.materials["ASTM A36"])
        model.update_bar_section(member_name, "U Laminado")
        model.update_member_profile(member_name, profile["name"], {
            "d": profile["d_mm"], "bf": profile["bf_mm"],
            "tw": profile["tw_mm"], "tf": profile["tf_mm"],
        })

        load_results = []
        for local_index in range(case_count):
            global_index = sum(per_profile[:profile_index]) + local_index
            action_type = global_index % 10
            scale = 1.0 + (global_index % 23) / 7.0
            # Mix isolated actions, sign changes, simultaneous actions and broad
            # deterministic random demands. The tiny axial code keeps every
            # six-component request vector distinct without crossing load
            # significance thresholds by itself.
            axial = rng.uniform(-1800.0, 1800.0)
            moment_y = rng.uniform(-180.0, 180.0)
            moment_z = rng.uniform(-180.0, 180.0)
            shear_y = rng.uniform(-900.0, 900.0)
            shear_z = rng.uniform(-900.0, 900.0)
            torque = rng.uniform(-80.0, 80.0)
            if action_type == 0:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            elif action_type == 1:
                axial, moment_y, moment_z, shear_y, shear_z, torque = -250.0 * scale, 0.0, 0.0, 0.0, 0.0, 0.0
            elif action_type == 2:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 250.0 * scale, 0.0, 0.0, 0.0, 0.0, 0.0
            elif action_type == 3:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 30.0 * scale, 0.0, 0.0, 0.0, 0.0
            elif action_type == 4:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 30.0 * scale, 0.0, 0.0, 0.0
            elif action_type == 5:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 0.0, 30.0 * scale, 0.0, 0.0
            elif action_type == 6:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 0.0, 0.0, 30.0 * scale, 0.0
            elif action_type == 7:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 0.0, 35.0 * scale, -42.0 * scale, 0.0
            elif action_type == 8:
                axial, moment_y, moment_z, shear_y, shear_z, torque = 0.0, 0.0, 0.0, 0.0, 0.0, 2.0 * scale

            axial += global_index * 1e-5
            vector = (axial, moment_y, moment_z, shear_y, shear_z, torque)
            all_signatures.add(vector)
            load_results.append(AnalysisResult(
                model.revision,
                f"ELU-U-{global_index:04d}",
                member_results={member_name: {"samples": [{
                    "x": (local_index % 11) * 0.25,
                    "axial": axial,
                    "moment_y": moment_y,
                    "moment_z": moment_z,
                    "shear_y": shear_y,
                    "shear_z": shear_z,
                    "torque": torque,
                }]}},
            ))

        model.analysis_results = load_results
        verification = verify_model(model)
        element = verification["results"][f"bar:{member_name}"]
        assert verification["summary"]["with_routine"] == 1
        assert {
            "axial_tension", "axial_compression", "slenderness", "flexion_y",
            "flexion_z", "shear_y", "shear_z", "flexao_obliqua",
            "flexotracao", "flexocompressao", "biaxial_shear",
        }.issubset(element["checks"])
        if element.get("torsion_summary", {}).get("has_torsion"):
            torsion_cases += 1
            assert "torsion" not in element["checks"]
        for check in element["checks"].values():
            assert check["status"] in {"checked", "not_checked", "not_applicable"}
            if check.get("combinations"):
                assert len(check["combinations"]) == case_count

        total_cases += case_count
        if representative_model is None:
            representative_model = model
            representative_verification = verification

    assert total_cases == 2000
    assert len(all_signatures) == 2000
    assert torsion_cases == len(profiles)

    representative_model.verification_results = representative_verification["results"]
    memorial = CalculationMemorialDialog._render(
        calculation_memory(representative_model, ("U1",)), {},
    )
    assert "Esbeltez na tra" in memorial
    assert "Esbeltez na compress" in memorial
    assert "Torção" in memorial
    assert "Cortantes simultâneos" in memorial
    assert "Premissa da seção líquida" not in memorial
    assert "Estimativa conservadora:" not in memorial
    assert "não co-localizados" not in memorial
    assert "torção não está incluída" not in memorial
