"""Structured steel check results, sampled forces and calculation steps."""

from __future__ import annotations

from math import isfinite

FIELDS = ("x", "axial", "moment_y", "moment_z", "shear_y", "shear_z", "torque")
OPTIONAL_FIELDS = ("bimoment", "torque_sc", "generalized_torque_sc", "saint_venant_torque", "warping_torque", "twist", "centroid_slope_y", "centroid_slope_z")
NAMES = {
    "axial_tension": "Tração axial", "axial_compression": "Compressão axial",
    "flexion_y": "Flexão Y", "flexion_z": "Flexão Z",
    "shear_y": "Cortante Y", "shear_z": "Cortante Z",
    "flexao_obliqua": "Flexão oblíqua", "flexotracao": "Flexotração",
    "flexocompressao": "Flexocompressão", "torsion": "Torção",
    "torsion_interaction": "Interação com torção",
}


def valid_sample(row, member_data):
    """A claimed coupled solve requires its complete force/kinematic record."""
    try:
        coupled = bool(member_data.get("warping_analysis"))
        fields = (*FIELDS, *(OPTIONAL_FIELDS if coupled else (key for key in OPTIONAL_FIELDS if key in row)))
        if any(key not in row or not isfinite(float(row[key])) for key in fields):
            return False
        if coupled:
            torque, sv, warp = (float(row[key]) for key in ("torque_sc", "saint_venant_torque", "warping_torque"))
            tolerance = 1e-9+1e-7*max(abs(torque), abs(sv), abs(warp))
            if abs(float(row["torque"])+torque) > tolerance or abs(torque-sv-warp) > tolerance:
                return False
            if (member_data["warping_analysis"].get("normal_mode_count") == 3 and
                    (abs(float(row["bimoment"])) > 1e-9 or abs(warp) > tolerance)):
                return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def number(value):
    return f"{value:.6g}".replace(".", "{,}")


def step(symbol, formula, substitution, value, unit, reference):
    return {"symbol": symbol, "formula": formula, "substitution": substitution,
            "value": value, "unit": unit, "reference": reference}


def context(element, model, results, families, section_reader):
    members = [model.bars[name] for name in element.member_names]
    if not members or any(m.section not in families for m in members):
        raise ValueError("A rotina requer elementos de uma família suportada.")
    if len({(m.section, tuple(sorted(m.geometry_dict().items())), m.material, m.section_mirrored) for m in members}) != 1:
        raise ValueError("Grupo com geometrias ou materiais diferentes.")
    material = model.materials.get(members[0].material, ())
    if len(material) < 6:
        raise ValueError("Propriedades do material indisponíveis.")
    e, g, fy, fu = (float(material[i]) / 10000 for i in (0, 1, 4, 5))
    if not all(isfinite(v) and v > 0 for v in (e, g, fy, fu)):
        raise ValueError("Propriedades do material inválidas.")
    if not results:
        raise ValueError("Resultados de análise indisponíveis.")
    samples = []
    for result in results:
        if result.model_revision != model.revision:
            raise ValueError("Resultados de análise desatualizados.")
        for member in members:
            data = result.member_results.get(member.name, {})
            rows = data.get("samples", ())
            if not rows:
                raise ValueError(f"Resultados amostrados ausentes para {member.name} em {result.load_reference}.")
            for row in rows:
                if not valid_sample(row, data):
                    raise ValueError(f"Amostra incompleta ou inválida de {member.name} em {result.load_reference}.")
                samples.append((result.load_reference, member.name, row))
    return members, section_reader(members[0]), e, g, fy, fu, samples


def check(key, samples, demand, capacity, parameters, steps, reference, error=None):
    base = {"critical_check": NAMES[key], "reference": reference,
            "parameters": parameters, "steps": steps, "combinations": []}
    rows = [(combo, member, sample, demand(sample)) for combo, member, sample in samples]
    rows = [row for row in rows if row[3] > 1e-6]
    if not rows:
        return {**base, "status": "not_applicable", "detail": "Sem solicitação aplicável."}
    if error:
        return {**base, "status": "not_checked", "detail": error}
    if capacity is None or not isfinite(capacity) or capacity <= 0:
        return {**base, "status": "not_checked", "detail": "Resistência indisponível ou inválida."}
    combinations = []
    for combo, member, sample, applied in rows:
        combinations.append({"combination": combo, "member": member,
                             "position_m": sample["x"], "applied": applied,
                             "utilization": applied / capacity,
                             "status": "APROVADO" if applied <= capacity else "REPROVADO"})
    critical = max(combinations, key=lambda row: row["utilization"])
    return {**base, "status": "checked", "detail": "", "capacity": capacity,
            "utilization": critical["utilization"], "critical_combination": critical["combination"],
            "critical_member": critical["member"], "critical_position_m": critical["position_m"],
            "applied": critical["applied"], "combinations": combinations}


