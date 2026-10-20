"""Axial tension check for rolled W sections."""

from __future__ import annotations

from osa.sections.contours import polygon_properties, w_contour_points

GAMMA_A1 = 1.10
GAMMA_A2 = 1.35
CT_INITIAL = 1.0
MIN_SIGNIFICANT_TENSION_KN = 0.001


def _gross_area_cm2(member) -> float:
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        value = geometry.get(name, geometry.get(f"{name}_mm"))
        if value is None:
            raise ValueError(f"dimensão '{name}' ausente na seção")
        return float(value)

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    radius = float(geometry.get("r", geometry.get("r_mm", 10.0)))
    points = w_contour_points(d, bf, tw, tf, radius)
    area_mm2, *_ = polygon_properties(points)
    return area_mm2 / 100.0


def verify_w_tension(element, model, results) -> dict:
    """Check gross-section yielding and effective-net-section rupture only."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "W Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis W laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "resistências do material não definidas"}
    fy_kn_m2, fu_kn_m2 = float(material_values[4]), float(material_values[5])
    if fy_kn_m2 <= 0.0 or fu_kn_m2 <= 0.0:
        return {"status": "not_checked", "detail": "resistências do material inválidas"}

    try:
        ag_cm2 = _gross_area_cm2(members[0])
        # O modelo não contém furos ou recortes da ligação: An = Ag nesta etapa.
        an_cm2 = ag_cm2
        ae_cm2 = CT_INITIAL * an_cm2
        # Model strengths are stored in kN/m²; divide by 10 000 for kN/cm².
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        fu_kn_cm2 = fu_kn_m2 / 10_000.0
        nt_rd1_kn = ag_cm2 * fy_kn_cm2 / GAMMA_A1
        nt_rd2_kn = ae_cm2 * fu_kn_cm2 / GAMMA_A2
        nt_rd_kn = min(nt_rd1_kn, nt_rd2_kn)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    combinations = []
    critical = None
    for result in results:
        governing = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                # In OSA's verification convention, negative axial force is tension.
                axial_kn = float(sample.get("axial", 0.0))
                if axial_kn <= -MIN_SIGNIFICANT_TENSION_KN:
                    tension_kn = abs(axial_kn)
                    if governing is None or tension_kn > governing[0]:
                        governing = (tension_kn, member_name)
        if governing is None:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "applied_kn": 0.0, "utilization": 0.0, "status": "N/A",
            })
            continue
        applied_kn, member_name = governing
        utilization = applied_kn / nt_rd_kn if nt_rd_kn > 0.0 else float("inf")
        item = {
            "combination": result.load_reference, "member": member_name,
            "applied_kn": applied_kn, "utilization": utilization,
            "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
        }
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    controlling = "Escoamento da seção bruta" if nt_rd1_kn <= nt_rd2_kn else "Ruptura da seção líquida efetiva"
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou tração axial",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Tração axial" if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied_kn"] if critical else None,
        "parameters": {
            "Ag_cm2": ag_cm2, "An_cm2": an_cm2, "Ae_cm2": ae_cm2,
            "Ct": CT_INITIAL, "fy_kn_m2": fy_kn_m2, "fu_kn_m2": fu_kn_m2,
            "fy_kn_cm2": fy_kn_cm2, "fu_kn_cm2": fu_kn_cm2,
            "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
            "Nt_Rd1_kn": nt_rd1_kn, "Nt_Rd2_kn": nt_rd2_kn,
            "Nt_Rd_kn": nt_rd_kn, "governing": controlling,
        },
        "combinations": combinations,
    }
