"""Attach a sampled location to legacy checks without recalculating resistance."""
from math import isclose


def annotate_governing_sample(key, check, results):
    if check.get("status") != "checked":
        return None
    combo, owner = check.get("critical_combination"), check.get("critical_member")
    row = next((item for item in check.get("combinations", ())
                if item.get("combination") == combo and item.get("member") == owner), {})
    position = next((value for value in (check.get("critical_position_m"), check.get("position_m"),
                                         row.get("position_m")) if value is not None), None)
    if position is not None:
        check["critical_position_m"] = position
        return None
    if not combo or not owner:
        return "Caso governante sem identificação de combinação ou barra."
    source = {**check, **row}
    expected = {}
    if key in {"axial_tension", "axial_compression"}:
        expected["axial"] = source.get("applied_kn")
    elif key in {"flexion_y", "flexion_z"}:
        expected["moment_"+key[-1]] = source.get("applied_kn_cm")
    elif key in {"shear_y", "shear_z"}:
        expected[key] = source.get("applied_kn")
    elif key in {"flexao_obliqua", "flexotracao", "flexocompressao"}:
        expected = {"axial": source.get("applied_kn"), "moment_y": source.get("applied_my_kn_cm"),
                    "moment_z": source.get("applied_mz_kn_cm")}
    else:
        return None
    if any(value is None for value in expected.values()):
        return "Solicitações do caso governante não foram registradas integralmente."
    samples = [sample for result in results if result.load_reference == combo
               for sample in result.member_results.get(owner, {}).get("samples", ())]
    for sample in samples:
        values = {"axial": abs(sample["axial"]), "moment_y": abs(sample["moment_y"])*100,
                  "moment_z": abs(sample["moment_z"])*100,
                  "shear_y": abs(sample["shear_y"]), "shear_z": abs(sample["shear_z"])}
        if key in {"axial_tension", "flexotracao"} and sample["axial"] >= 0:
            continue
        if key in {"axial_compression", "flexocompressao"} and sample["axial"] <= 0:
            continue
        if key == "flexao_obliqua" and abs(sample["axial"]) < .001:
            values["axial"] = 0.
        bending_sign = source.get("bending_sign")
        if (key == "flexion_y" and bending_sign in {"web_end_tension", "web_end_compression"}
                and (sample["moment_y"] >= 0) != (bending_sign == "web_end_tension")):
            continue
        if all(isclose(values[field], float(value), rel_tol=1e-8, abs_tol=1e-6)
               for field, value in expected.items()):
            check["critical_position_m"] = sample["x"]
            row["position_m"] = sample["x"]
            return None
    return "As solicitações registradas não correspondem a uma amostra concomitante da combinação e barra governantes."
