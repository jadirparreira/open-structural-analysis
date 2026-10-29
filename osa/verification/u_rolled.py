"""Axial tension check for rolled U sections."""

from __future__ import annotations

from math import pi, sqrt

from osa.sections.contours import polygon_properties, u_contour_points
from osa.verification.calculation_properties import calculation_property
from osa.verification.restraints import restraint_lengths

GAMMA_A1 = 1.10
GAMMA_A2 = 1.35
CT_INITIAL = 1.0
MIN_SIGNIFICANT_TENSION_KN = 0.001
MIN_SIGNIFICANT_COMPRESSION_KN = 0.001
MIN_SIGNIFICANT_BENDING_KN_M = 0.001
MIN_SIGNIFICANT_SHEAR_KN = 0.001
CB_INITIAL = 1.0


def _gross_area_cm2(member) -> float:
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        value = geometry.get(name, geometry.get(f"{name}_mm"))
        if value is None:
            raise ValueError(f"dimensão '{name}' ausente na seção")
        return float(value)

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    radius = float(geometry.get("r", geometry.get("r_mm", 0.0))) or max(2.0, 1.5 * tf)
    tip_radius = float(geometry.get("r1", geometry.get("r1_mm", 0.0))) or None
    flange_angle = float(geometry.get("flange_angle_deg", geometry.get("angle", 2.0)))
    points = u_contour_points(d, bf, tw, tf, radius, tip_radius, flange_angle)
    area_mm2, *_ = polygon_properties(points)
    return area_mm2 / 100.0


def verify_u_tension(element, model, results) -> dict:
    """Check gross-section yielding and effective-net-section rupture only."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
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
        ct = calculation_property(model, element, "Ct", CT_INITIAL)
        ae_cm2 = ct * an_cm2
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
                # OSA verification convention: negative axial force is tension.
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
            "Ct": ct, "fy_kn_m2": fy_kn_m2, "fu_kn_m2": fu_kn_m2,
            "fy_kn_cm2": fy_kn_cm2, "fu_kn_cm2": fu_kn_cm2,
            "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
            "Nt_Rd1_kn": nt_rd1_kn, "Nt_Rd2_kn": nt_rd2_kn,
            "Nt_Rd_kn": nt_rd_kn, "governing": controlling,
        },
        "combinations": combinations,
    }


def _compression_local_width(width_mm: float, thickness_mm: float, limit: float,
                             chi: float, c1: float, c2: float, fy_kn_cm2: float) -> float:
    slenderness = width_mm / thickness_mm
    reduced_limit = limit / sqrt(max(chi, 1e-12))
    if slenderness <= reduced_limit:
        return width_mm
    sigma_el = (c2 * limit / slenderness) ** 2 * fy_kn_cm2
    ratio = sigma_el / (chi * fy_kn_cm2)
    effective = width_mm * max(0.0, 1.0 - c1 * sqrt(ratio)) * sqrt(ratio)
    return min(width_mm, effective)


def verify_u_flexion_y(element, model, results) -> dict:
    """Check major-axis flexion of rolled U sections per NBR 8800:2024, 5.4."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    has_bending = any(
        abs(float(sample.get("moment_y", 0.0))) >= MIN_SIGNIFICANT_BENDING_KN_M
        for result in results for member_name in element.member_names
        for sample in result.member_results[member_name].get("samples", ())
    )
    if not has_bending:
        return {"status": "not_applicable", "detail": "nenhuma combinação apresentou momento fletor em Y"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, shear_kn_m2 = float(material_values[0]), float(material_values[1])
    fy_kn_m2 = float(material_values[4])
    if min(elastic_kn_m2, shear_kn_m2, fy_kn_m2) <= 0.0:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    try:
        from osa.memorial_data import _u_properties

        member = members[0]
        geometry = _u_properties(member)
        # Flexão Y in the application follows the section's major axis properties.
        # U-section properties come from the U contour in the memorial helper.
        iy_cm4 = geometry["Iy"]
        wy_cm3 = geometry["Wy"]
        zy_cm3 = geometry["Zy"]
        rz_cm = geometry["rz"]
        it_cm4 = geometry["It"]
        cw_cm6 = geometry["Cw"]
        bf_mm, tf_mm, tw_mm = (geometry[key] for key in ("bf", "tf", "tw"))
        di_mm = geometry["h"]
        bf_cm, tf_cm, tw_cm, di_cm = (value / 10.0 for value in (bf_mm, tf_mm, tw_mm, di_mm))

        # Material values are stored in kN/m²; convert to kN/cm² for moments in kN·cm.
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        shear_kn_cm2 = shear_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        tr_kn_cm2 = 0.30 * fy_kn_cm2
        gamma_a1 = GAMMA_A1
        cb = calculation_property(model, element, "Cb", CB_INITIAL)
        mp_kn_cm = zy_cm3 * fy_kn_cm2
        mr_kn_cm = 0.70 * wy_cm3 * fy_kn_cm2

        lengths = restraint_lengths(
            model, element, results, {"Iy": geometry["Iz"], "tw": tw_cm}, cb=cb,
        )
        lb_m = lengths.lengths_m["Lb"]
        restraint_parameters = {
            "Lb_cm": lb_m * 100.0,
            "Cb": cb,
            "restraint_issues": list(lengths.issues),
            "restraint_modes": lengths.modes,
            "restraint_notes": list(lengths.notes),
        }
        # Use the Lb adopted for the profile memory as the design parameter.
        # Restraint diagnostics do not suppress the flexion verification.
        lb_cm = lb_m * 100.0
        if lb_cm <= 0.0 or not all(value > 0.0 for value in
                                   (iy_cm4, wy_cm3, zy_cm3, rz_cm, it_cm4, cw_cm6)):
            raise ValueError("propriedades geométricas ou comprimento Lb inválidos")

        lambda_flt = lb_cm / rz_cm
        lambda_p_flt = 1.76 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        beta1 = ((fy_kn_cm2 - tr_kn_cm2) * wy_cm3) / (elastic_kn_cm2 * it_cm4)
        lambda_r_flt = (
            (1.38 * cb * sqrt(iy_cm4 * it_cm4)) /
            (rz_cm * it_cm4 * beta1)
            * sqrt(1.0 + sqrt(1.0 + 27.0 * cw_cm6 * beta1**2 / (cb**2 * iy_cm4)))
        )
        # NBR 8800:2024, D.2.8-a. Units remain kN·cm.
        mcr_flt_kn_cm = (
            cb * pi**2 * elastic_kn_cm2 * iy_cm4 / lb_cm**2
            * sqrt((cw_cm6 / iy_cm4) * (1.0 + 0.039 * it_cm4 * lb_cm**2 / cw_cm6))
        )
        if lambda_flt <= lambda_p_flt:
            mn_flt_kn_cm = mp_kn_cm
        elif lambda_flt <= lambda_r_flt:
            mn_flt_kn_cm = mp_kn_cm - (mp_kn_cm - mr_kn_cm) * (
                (lambda_flt - lambda_p_flt) / (lambda_r_flt - lambda_p_flt)
            )
        else:
            mn_flt_kn_cm = min(mcr_flt_kn_cm, mp_kn_cm)
        mrd_flt_kn_cm = mn_flt_kn_cm / gamma_a1

        lambda_flm = bf_cm / tf_cm
        lambda_p_flm = 0.38 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        lambda_r_flm = 0.83 * sqrt(elastic_kn_cm2 / (fy_kn_cm2 - tr_kn_cm2))
        mcr_flm_kn_cm = 0.69 * elastic_kn_cm2 * wy_cm3 / lambda_flm**2
        if lambda_flm <= lambda_p_flm:
            mn_flm_kn_cm = mp_kn_cm
        elif lambda_flm <= lambda_r_flm:
            mn_flm_kn_cm = mp_kn_cm - (mp_kn_cm - mr_kn_cm) * (
                (lambda_flm - lambda_p_flm) / (lambda_r_flm - lambda_p_flm)
            )
        else:
            mn_flm_kn_cm = min(mcr_flm_kn_cm, mp_kn_cm)
        mrd_flm_kn_cm = mn_flm_kn_cm / gamma_a1

        lambda_fla = di_cm / tw_cm
        lambda_p_fla = 3.76 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        lambda_r_fla = 5.70 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        mr_fla_kn_cm = wy_cm3 * fy_kn_cm2
        if lambda_fla > lambda_r_fla:
            slenderness_ratio = lambda_fla / lambda_r_fla
            rejected_combinations = []
            critical = None
            for result in results:
                demand = None
                for member_name in element.member_names:
                    for sample in result.member_results[member_name].get("samples", ()):
                        moment_kn_cm = abs(float(sample.get("moment_y", 0.0))) * 100.0
                        if demand is None or moment_kn_cm > demand[0]:
                            demand = (moment_kn_cm, member_name, sample.get("x"))
                item = {
                    "combination": result.load_reference,
                    "member": demand[1] if demand else None,
                    "position_m": demand[2] if demand else None,
                    "applied_kn_cm": demand[0] if demand else 0.0,
                    "utilization": slenderness_ratio,
                    "status": "REPROVADO",
                }
                rejected_combinations.append(item)
                if critical is None or item["applied_kn_cm"] > critical["applied_kn_cm"]:
                    critical = item
            return {
                "status": "checked",
                "detail": (
                    "reprovado: esbeltez da alma excede o limite aplicável da Tabela D.1; "
                    "o Anexo E não abrange perfis U laminados"
                ),
                "utilization": slenderness_ratio,
                "critical_check": "Flexão Y — FLA (limite de esbeltez)",
                "critical_combination": critical["combination"] if critical else "N/A",
                "critical_member": critical["member"] if critical else None,
                "applied_kn_cm": critical["applied_kn_cm"] if critical else 0.0,
                "parameters": {
                    "slender_web_rejected": True,
                    "lambda_fla": lambda_fla,
                    "lambda_r_fla": lambda_r_fla,
                    "di_cm": di_cm,
                    "tw_cm": tw_cm,
                    "E_kn_cm2": elastic_kn_cm2,
                    "fy_kn_cm2": fy_kn_cm2,
                    "slenderness_ratio": slenderness_ratio,
                    **restraint_parameters,
                },
                "combinations": rejected_combinations,
            }
        if lambda_fla <= lambda_p_fla:
            mn_fla_kn_cm = mp_kn_cm
        else:
            mn_fla_kn_cm = min(
                mp_kn_cm,
                mp_kn_cm - (mp_kn_cm - mr_fla_kn_cm)
                * ((lambda_fla - lambda_p_fla) / (lambda_r_fla - lambda_p_fla)),
            )
        mrd_fla_kn_cm = mn_fla_kn_cm / gamma_a1

        mrd_limit_kn_cm = 1.50 * wy_cm3 * fy_kn_cm2 / gamma_a1
        capacities = {
            "FLT": min(mrd_flt_kn_cm, mrd_limit_kn_cm),
            "FLM": min(mrd_flm_kn_cm, mrd_limit_kn_cm),
            "FLA": min(mrd_fla_kn_cm, mrd_limit_kn_cm),
        }
        governing = min(capacities, key=capacities.get)
        my_rd_kn_cm = capacities[governing]
        if my_rd_kn_cm <= 0.0:
            raise ValueError("momento resistente de cálculo não positivo")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        result = {"status": "not_checked", "detail": str(error) or "geometria ou contenções inválidas"}
        if "restraint_parameters" in locals():
            result["parameters"] = restraint_parameters
        return result

    combinations = []
    critical = None
    for result in results:
        demand = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                moment_kn_cm = abs(float(sample.get("moment_y", 0.0))) * 100.0
                if demand is None or moment_kn_cm > demand[0]:
                    demand = (moment_kn_cm, member_name, sample.get("x"))
        if demand is None or demand[0] < MIN_SIGNIFICANT_BENDING_KN_M * 100.0:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "applied_kn_cm": 0.0, "utilization": 0.0, "status": "N/A",
            })
            continue
        applied_kn_cm, member_name, position_m = demand
        utilization = applied_kn_cm / my_rd_kn_cm if my_rd_kn_cm > 0.0 else float("inf")
        item = {
            "combination": result.load_reference, "member": member_name,
            "position_m": position_m, "applied_kn_cm": applied_kn_cm,
            "utilization": utilization,
            "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
        }
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    parameters = {
        **restraint_parameters,
        "E_kn_cm2": elastic_kn_cm2, "G_kn_cm2": shear_kn_cm2,
        "fy_kn_cm2": fy_kn_cm2, "sigma_r_kn_cm2": tr_kn_cm2,
        "gamma_a1": gamma_a1, "Iy_cm4": iy_cm4, "Wy_cm3": wy_cm3,
        "Zy_cm3": zy_cm3, "rz_cm": rz_cm, "It_cm4": it_cm4,
        "Cw_cm6": cw_cm6, "bf_cm": bf_cm, "tf_cm": tf_cm,
        "tw_cm": tw_cm, "di_cm": di_cm,
        "Cb": cb, "Mp_kn_cm": mp_kn_cm, "Mr_kn_cm": mr_kn_cm,
        "beta1": beta1,
        "lambda_flt": lambda_flt, "lambda_p_flt": lambda_p_flt,
        "lambda_r_flt": lambda_r_flt, "Mcr_flt_kn_cm": mcr_flt_kn_cm,
        "Mn_flt_kn_cm": mn_flt_kn_cm,
        "Mrd_flt_nominal_kn_cm": mrd_flt_kn_cm, "Mrd_flt_kn_cm": capacities["FLT"],
        "lambda_flm": lambda_flm, "lambda_p_flm": lambda_p_flm,
        "lambda_r_flm": lambda_r_flm, "Mcr_flm_kn_cm": mcr_flm_kn_cm,
        "Mn_flm_kn_cm": mn_flm_kn_cm,
        "Mrd_flm_nominal_kn_cm": mrd_flm_kn_cm, "Mrd_flm_kn_cm": capacities["FLM"],
        "lambda_fla": lambda_fla, "lambda_p_fla": lambda_p_fla,
        "lambda_r_fla": lambda_r_fla,
        "Mr_fla_kn_cm": mr_fla_kn_cm,
        "Mn_fla_kn_cm": mn_fla_kn_cm,
        "Mrd_fla_nominal_kn_cm": mrd_fla_kn_cm, "Mrd_fla_kn_cm": capacities["FLA"],
        "Mrd_limit_kn_cm": mrd_limit_kn_cm, "Mrd_kn_cm": my_rd_kn_cm,
        "governing": governing,
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou momento fletor em Y",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Flexão Y — " + governing if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn_cm": critical["applied_kn_cm"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }


def verify_u_flexion_z(element, model, results) -> dict:
    """Check weak-axis flexion of rolled U sections per NBR 8800:2024, Anexo D."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    has_bending = any(
        abs(float(sample.get("moment_z", 0.0))) >= MIN_SIGNIFICANT_BENDING_KN_M
        for result in results for member_name in element.member_names
        for sample in result.member_results[member_name].get("samples", ())
    )
    if not has_bending:
        return {"status": "not_applicable", "detail": "nenhuma combinação apresentou momento fletor em Z"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, fy_kn_m2 = float(material_values[0]), float(material_values[4])
    if min(elastic_kn_m2, fy_kn_m2) <= 0.0:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    try:
        from osa.memorial_data import _u_properties

        geometry = _u_properties(members[0])
        wz_cm3, zz_cm3 = geometry["Wz"], geometry["Zz"]
        bf_cm, tf_cm = geometry["bf"] / 10.0, geometry["tf"] / 10.0
        h_cm, tw_cm = geometry["h"] / 10.0, geometry["tw"] / 10.0
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        gamma_a1 = GAMMA_A1
        if min(wz_cm3, zz_cm3, tf_cm, h_cm, tw_cm) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para Flexão Z")

        mp_kn_cm = zz_cm3 * fy_kn_cm2
        # Table D.1 / D.2.8-c: weak-axis FLM applies when a free flange edge
        # is compressed. Use the rolled-U limits from D.2.8-f and h.
        lambda_flm_z = bf_cm / tf_cm
        sigma_r_kn_cm2 = 0.30 * fy_kn_cm2
        lambda_p_flm_z = 0.38 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        lambda_r_flm_z = 0.83 * sqrt(
            elastic_kn_cm2 / (fy_kn_cm2 - sigma_r_kn_cm2)
        )
        mr_flm_z_kn_cm = (fy_kn_cm2 - sigma_r_kn_cm2) * wz_cm3
        mcr_flm_z_kn_cm = 0.69 * elastic_kn_cm2 * wz_cm3 / lambda_flm_z**2
        if lambda_flm_z <= lambda_p_flm_z:
            mn_flm_z_kn_cm = mp_kn_cm
        elif lambda_flm_z <= lambda_r_flm_z:
            mn_flm_z_kn_cm = mp_kn_cm - (mp_kn_cm - mr_flm_z_kn_cm) * (
                (lambda_flm_z - lambda_p_flm_z) /
                (lambda_r_flm_z - lambda_p_flm_z)
            )
        else:
            mn_flm_z_kn_cm = min(mcr_flm_z_kn_cm, mp_kn_cm)
        mrd_flm_z_kn_cm = mn_flm_z_kn_cm / gamma_a1
        lambda_fla_z = h_cm / tw_cm
        lambda_p_fla_z = 1.12 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        lambda_r_fla_z = 1.40 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        web_limit = 1.49 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        web_sigma_el = (1.31 * web_limit / lambda_fla_z) ** 2 * fy_kn_cm2
        web_effective = _compression_local_width(
            h_cm * 10.0, tw_cm * 10.0, web_limit, 1.0, 0.18, 1.31, fy_kn_cm2,
        )
        removed_area_cm2 = (h_cm * 10.0 - web_effective) * (tw_cm * 10.0) / 100.0
        area_cm2 = geometry["area"]
        x_centroid_cm = geometry["cx_mm"] / 10.0
        x_web_cm = (-geometry["bf"] / 2.0 + geometry["tw"] / 2.0) / 10.0
        area_effective_cm2 = area_cm2 - removed_area_cm2
        if area_effective_cm2 <= 0.0:
            raise ValueError("área efetiva inválida para FLA em Z")
        x_centroid_effective_cm = (
            area_cm2 * x_centroid_cm - removed_area_cm2 * x_web_cm
        ) / area_effective_cm2
        iz_effective_cm4 = wz_cm3 * max(
            (geometry["cx_mm"] + geometry["bf"] / 2.0) / 10.0,
            (geometry["bf"] / 2.0 - geometry["cx_mm"]) / 10.0,
        )
        iz_effective_cm4 = (
            iz_effective_cm4 + area_cm2 * x_centroid_cm**2
            - removed_area_cm2 * x_web_cm**2
            - area_effective_cm2 * x_centroid_effective_cm**2
            - (h_cm * 10.0 - web_effective) / 10.0 * tw_cm**3 / 12.0
        )
        max_distance_effective_cm = max(
            abs(x_centroid_effective_cm + geometry["bf"] / 20.0),
            abs(geometry["bf"] / 20.0 - x_centroid_effective_cm),
        )
        w_effective_cm3 = iz_effective_cm4 / max_distance_effective_cm
        mr_kn_cm = fy_kn_cm2 * w_effective_cm3
        mcr_fla_z_kn_cm = w_effective_cm3**2 / wz_cm3 * fy_kn_cm2

        if lambda_fla_z <= lambda_p_fla_z:
            mn_fla_z_kn_cm = mp_kn_cm
        elif lambda_fla_z <= lambda_r_fla_z:
            mn_fla_z_kn_cm = mp_kn_cm - (mp_kn_cm - mr_kn_cm) * (
                (lambda_fla_z - lambda_p_fla_z) /
                (lambda_r_fla_z - lambda_p_fla_z)
            )
        else:
            mn_fla_z_kn_cm = min(mcr_fla_z_kn_cm, mp_kn_cm)
        mrd_fla_z_kn_cm = mn_fla_z_kn_cm / gamma_a1

        # NBR 8800:2024, 5.4.2.2 limits MRd to 1.50 W fy / gamma_a1.
        mrd_limit_kn_cm = 1.50 * wz_cm3 * fy_kn_cm2 / gamma_a1
        mz_rd_kn_cm = min(mrd_flm_z_kn_cm, mrd_fla_z_kn_cm, mrd_limit_kn_cm)
        if mz_rd_kn_cm <= 0.0:
            raise ValueError("momento resistente de cálculo não positivo")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    combinations = []
    critical = None
    for result in results:
        demand = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                moment_kn_cm = abs(float(sample.get("moment_z", 0.0))) * 100.0
                if demand is None or moment_kn_cm > demand[0]:
                    demand = (moment_kn_cm, member_name, sample.get("x"))
        if demand is None or demand[0] < MIN_SIGNIFICANT_BENDING_KN_M * 100.0:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "applied_kn_cm": 0.0, "utilization": 0.0, "status": "N/A",
            })
            continue
        applied_kn_cm, member_name, position_m = demand
        utilization = applied_kn_cm / mz_rd_kn_cm
        item = {
            "combination": result.load_reference, "member": member_name,
            "position_m": position_m, "applied_kn_cm": applied_kn_cm,
            "utilization": utilization,
            "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
        }
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    parameters = {
            "E_kn_cm2": elastic_kn_cm2, "fy_kn_cm2": fy_kn_cm2,
            "sigma_r_kn_cm2": 0.0, "gamma_a1": gamma_a1,
            "Wz_cm3": wz_cm3, "Zz_cm3": zz_cm3,
            "Wef_z_cm3": w_effective_cm3,
            "Iz_ef_cm4": iz_effective_cm4,
            "cmax_ef_cm": max_distance_effective_cm,
            "bf_cm": bf_cm, "tf_cm": tf_cm,
            "h_cm": h_cm, "tw_cm": tw_cm,
            "web_limit_AA": web_limit,
            "web_sigma_el_AA_kn_cm2": web_sigma_el,
            "web_effective_width_mm": web_effective,
            "Mp_z_kn_cm": mp_kn_cm, "Mr_z_kn_cm": mr_kn_cm,
            "lambda_flm_z": lambda_flm_z,
            "lambda_p_flm_z": lambda_p_flm_z,
            "lambda_r_flm_z": lambda_r_flm_z,
            "lambda_fla_z": lambda_fla_z,
            "lambda_p_fla_z": lambda_p_fla_z,
            "lambda_r_fla_z": lambda_r_fla_z,
            "sigma_r_flm_z_kn_cm": sigma_r_kn_cm2,
            "Mr_flm_z_kn_cm": mr_flm_z_kn_cm,
            "Mcr_flm_z_kn_cm": mcr_flm_z_kn_cm,
            "Mn_flm_z_kn_cm": mn_flm_z_kn_cm,
            "Mrd_flm_z_kn_cm": mrd_flm_z_kn_cm,
            "Mcr_fla_z_kn_cm": mcr_fla_z_kn_cm,
            "Mn_fla_z_kn_cm": mn_fla_z_kn_cm,
            "Mrd_fla_z_kn_cm": mrd_fla_z_kn_cm,
        "Mrd_limit_kn_cm": mrd_limit_kn_cm,
        "Mrd_z_kn_cm": mz_rd_kn_cm,
        "governing": "FLM-Z" if mrd_flm_z_kn_cm <= mrd_limit_kn_cm else "Limite 5.4.2.2",
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou momento fletor em Z",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Flexão Z — FLM/FLA" if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn_cm": critical["applied_kn_cm"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }


def verify_u_shear_y(element, model, results) -> dict:
    """Check shear along local Y of rolled U sections per NBR 8800:2024, 5.4.3.5."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    has_shear = any(
        abs(float(sample.get("shear_y", 0.0))) >= MIN_SIGNIFICANT_SHEAR_KN
        for result in results for member_name in element.member_names
        for sample in result.member_results[member_name].get("samples", ())
    )
    if not has_shear:
        return {"status": "not_applicable", "detail": "nenhuma combinação apresentou força cortante em Y"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, fy_kn_m2 = float(material_values[0]), float(material_values[4])
    if min(elastic_kn_m2, fy_kn_m2) <= 0.0:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    try:
        from osa.memorial_data import _u_properties

        geometry = _u_properties(members[0])
        bf_cm, tf_cm = geometry["bf"] / 10.0, geometry["tf"] / 10.0
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        gamma_a1 = GAMMA_A1
        kv_y = 1.2
        if min(bf_cm, tf_cm) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para Cortante Y")

        aw_cm2 = 2.0 * bf_cm * tf_cm
        vp_y_kn = 0.60 * aw_cm2 * fy_kn_cm2
        lambda_y = bf_cm / tf_cm
        slenderness_factor = sqrt(kv_y * elastic_kn_cm2 / fy_kn_cm2)
        lambda_p_y = 1.10 * slenderness_factor
        lambda_r_y = 1.37 * slenderness_factor
        if lambda_y <= lambda_p_y:
            vrd_y_kn = vp_y_kn / gamma_a1
            governing = "Escoamento por cisalhamento"
        elif lambda_y <= lambda_r_y:
            vrd_y_kn = (lambda_p_y / lambda_y) * vp_y_kn / gamma_a1
            governing = "Flambagem inelástica por cisalhamento"
        else:
            vrd_y_kn = 1.24 * (lambda_p_y / lambda_y) ** 2 * vp_y_kn / gamma_a1
            governing = "Flambagem elástica por cisalhamento"
        if vrd_y_kn <= 0.0:
            raise ValueError("força cortante resistente de cálculo não positiva")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    combinations = []
    critical = None
    for result in results:
        demand = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                shear_kn = abs(float(sample.get("shear_y", 0.0)))
                if demand is None or shear_kn > demand[0]:
                    demand = (shear_kn, member_name, sample.get("x"))
        if demand is None or demand[0] < MIN_SIGNIFICANT_SHEAR_KN:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "applied_kn": 0.0, "utilization": 0.0, "status": "N/A",
            })
            continue
        applied_kn, member_name, position_m = demand
        utilization = applied_kn / vrd_y_kn
        item = {
            "combination": result.load_reference, "member": member_name,
            "position_m": position_m, "applied_kn": applied_kn,
            "utilization": utilization,
            "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
        }
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    parameters = {
        "E_kn_cm2": elastic_kn_cm2, "fy_kn_cm2": fy_kn_cm2,
        "gamma_a1": gamma_a1, "bf_cm": bf_cm, "tf_cm": tf_cm,
        "Aw_cm2": aw_cm2, "kv_y": kv_y, "Vp_y_kn": vp_y_kn,
        "lambda_y": lambda_y, "lambda_p_y": lambda_p_y,
        "lambda_r_y": lambda_r_y, "Vrd_y_kn": vrd_y_kn,
        "governing": governing,
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou força cortante em Y",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Cortante Y — " + governing if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied_kn"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }


def verify_u_shear_z(element, model, results) -> dict:
    """Check shear along local Z of rolled U sections per NBR 8800:2024, 5.4.3.1."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    has_shear = any(
        abs(float(sample.get("shear_z", 0.0))) >= MIN_SIGNIFICANT_SHEAR_KN
        for result in results for member_name in element.member_names
        for sample in result.member_results[member_name].get("samples", ())
    )
    if not has_shear:
        return {"status": "not_applicable", "detail": "nenhuma combinação apresentou força cortante em Z"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, fy_kn_m2 = float(material_values[0]), float(material_values[4])
    if min(elastic_kn_m2, fy_kn_m2) <= 0.0:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    try:
        from osa.memorial_data import _u_properties

        geometry = _u_properties(members[0])
        section_geometry = members[0].geometry_dict()
        radius_mm = geometry["r"]
        d_cm = geometry["d"] / 10.0
        tw_cm = geometry["tw"] / 10.0
        h_cm = geometry["h"] / 10.0
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        gamma_a1 = GAMMA_A1
        kv_z = 5.34  # NBR 8800:2024, 5.4.3.1.1: alma sem enrijecedores transversais, a/h > 3.
        if min(d_cm, h_cm, tw_cm, elastic_kn_cm2, fy_kn_cm2) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para Cortante Z")

        aw_cm2 = d_cm * tw_cm
        vp_z_kn = 0.60 * aw_cm2 * fy_kn_cm2
        lambda_z = h_cm / tw_cm
        slenderness_factor = sqrt(kv_z * elastic_kn_cm2 / fy_kn_cm2)
        lambda_p_z = 1.10 * slenderness_factor
        lambda_r_z = 1.37 * slenderness_factor
        if lambda_z <= lambda_p_z:
            vrd_z_kn = vp_z_kn / gamma_a1
            governing = "Escoamento por cisalhamento"
        elif lambda_z <= lambda_r_z:
            vrd_z_kn = (lambda_p_z / lambda_z) * vp_z_kn / gamma_a1
            governing = "Flambagem inelástica por cisalhamento"
        else:
            vrd_z_kn = 1.24 * (lambda_p_z / lambda_z) ** 2 * vp_z_kn / gamma_a1
            governing = "Flambagem elástica por cisalhamento"
        if vrd_z_kn <= 0.0:
            raise ValueError("força cortante resistente de cálculo não positiva")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    combinations = []
    critical = None
    for result in results:
        demand = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                shear_kn = abs(float(sample.get("shear_z", 0.0)))
                if demand is None or shear_kn > demand[0]:
                    demand = (shear_kn, member_name, sample.get("x"))
        if demand is None or demand[0] < MIN_SIGNIFICANT_SHEAR_KN:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "applied_kn": 0.0, "utilization": 0.0, "status": "N/A",
            })
            continue
        applied_kn, member_name, position_m = demand
        utilization = applied_kn / vrd_z_kn
        item = {
            "combination": result.load_reference, "member": member_name,
            "position_m": position_m, "applied_kn": applied_kn,
            "utilization": utilization,
            "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
        }
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    parameters = {
        "E_kn_cm2": elastic_kn_cm2, "fy_kn_cm2": fy_kn_cm2,
        "gamma_a1": gamma_a1, "d_cm": d_cm, "h_cm": h_cm,
        "tw_cm": tw_cm, "Aw_cm2": aw_cm2, "kv_z": kv_z,
        "Vp_z_kn": vp_z_kn, "lambda_z": lambda_z,
        "lambda_p_z": lambda_p_z, "lambda_r_z": lambda_r_z,
        "Vrd_z_kn": vrd_z_kn, "governing": governing,
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou força cortante em Z",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Cortante Z — " + governing if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied_kn"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }


def _verify_u_combined_actions(element, model, results, mode: str,
                               axial_check: dict | None,
                               flexion_y_check: dict | None,
                               flexion_z_check: dict | None) -> dict:
    """Evaluate one NBR 8800:2024, 5.5.1.2 interaction at concurrent stations."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}

    axial_parameters = (axial_check or {}).get("parameters") or {}
    if mode == "flexotension":
        nrd_kn = axial_parameters.get("Nt_Rd_kn")
    elif mode == "flexocompression":
        nrd_kn = axial_parameters.get("Nc_Rd_kn")
    else:
        nrd_kn = None
    flexion_y_parameters = (flexion_y_check or {}).get("parameters") or {}
    flexion_z_parameters = (flexion_z_check or {}).get("parameters") or {}
    slender_web_rejected = bool(flexion_y_parameters.get("slender_web_rejected"))
    slenderness_ratio = float(flexion_y_parameters.get("slenderness_ratio", 1.0))
    myrd_kn_cm = flexion_y_parameters.get("Mrd_kn_cm")
    mzrd_kn_cm = flexion_z_parameters.get("Mrd_z_kn_cm")

    nrd_kn = float(nrd_kn) if nrd_kn is not None else None

    combinations = []
    critical = None
    any_applicable = False
    for result in results:
        combination_critical = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                axial_signed_kn = float(sample.get("axial", 0.0))
                moment_y_kn_cm = abs(float(sample.get("moment_y", 0.0))) * 100.0
                moment_z_kn_cm = abs(float(sample.get("moment_z", 0.0))) * 100.0
                has_my = moment_y_kn_cm >= MIN_SIGNIFICANT_BENDING_KN_M * 100.0
                has_mz = moment_z_kn_cm >= MIN_SIGNIFICANT_BENDING_KN_M * 100.0

                if mode == "flexao_obliqua":
                    applicable = (
                        abs(axial_signed_kn) < MIN_SIGNIFICANT_TENSION_KN
                        and has_my and has_mz
                    )
                    axial_kn = 0.0
                elif mode == "flexotension":
                    applicable = (
                        axial_signed_kn <= -MIN_SIGNIFICANT_TENSION_KN
                        and (has_my or has_mz)
                    )
                    axial_kn = abs(axial_signed_kn)
                else:
                    applicable = (
                        axial_signed_kn >= MIN_SIGNIFICANT_COMPRESSION_KN
                        and (has_my or has_mz)
                    )
                    axial_kn = axial_signed_kn
                if not applicable:
                    continue

                if has_my and (myrd_kn_cm is None or float(myrd_kn_cm) <= 0.0):
                    if slender_web_rejected:
                        item = {
                            "combination": result.load_reference,
                            "member": member_name,
                            "position_m": sample.get("x"),
                            "axial_signed_kn": axial_signed_kn,
                            "applied_kn": axial_kn,
                            "applied_my_kn_cm": moment_y_kn_cm,
                            "applied_mz_kn_cm": moment_z_kn_cm,
                            "utilization": slenderness_ratio,
                            "status": "REPROVADO",
                            "slender_web_rejected": True,
                        }
                        if (
                            combination_critical is None
                            or item["utilization"] > combination_critical["utilization"]
                        ):
                            combination_critical = item
                        continue
                    return {"status": "not_checked", "detail": "resistência à flexão em Y indisponível"}
                if mode != "flexao_obliqua" and (nrd_kn is None or nrd_kn <= 0.0):
                    axial_label = "compressão" if mode == "flexocompression" else "tração"
                    return {
                        "status": "not_checked",
                        "detail": f"resistência axial de cálculo à {axial_label} indisponível",
                    }
                if has_mz and (mzrd_kn_cm is None or float(mzrd_kn_cm) <= 0.0):
                    return {"status": "not_checked", "detail": "resistência à flexão em Z indisponível"}
                myrd = float(myrd_kn_cm) if myrd_kn_cm is not None else None
                mzrd = float(mzrd_kn_cm) if mzrd_kn_cm is not None else None
                axial_ratio = axial_kn / nrd_kn if nrd_kn else 0.0
                moment_y_ratio = moment_y_kn_cm / myrd if has_my and myrd else 0.0
                moment_z_ratio = moment_z_kn_cm / mzrd if has_mz and mzrd else 0.0

                if mode == "flexao_obliqua":
                    interaction = moment_y_ratio + moment_z_ratio
                    interaction_case = "biaxial"
                elif axial_ratio >= 0.2:
                    interaction = axial_ratio + (8.0 / 9.0) * (moment_y_ratio + moment_z_ratio)
                    interaction_case = "Nsd/Nrd >= 0,2"
                else:
                    interaction = axial_ratio / 2.0 + moment_y_ratio + moment_z_ratio
                    interaction_case = "Nsd/Nrd < 0,2"

                item = {
                    "combination": result.load_reference,
                    "member": member_name,
                    "position_m": sample.get("x"),
                    "axial_signed_kn": axial_signed_kn,
                    "applied_kn": axial_kn,
                    "applied_my_kn_cm": moment_y_kn_cm,
                    "applied_mz_kn_cm": moment_z_kn_cm,
                    "axial_ratio": axial_ratio,
                    "moment_y_ratio": moment_y_ratio,
                    "moment_z_ratio": moment_z_ratio,
                    "interaction_case": interaction_case,
                    "utilization": interaction,
                    "status": "APROVADO" if interaction <= 1.0 else "REPROVADO",
                }
                if combination_critical is None or interaction > combination_critical["utilization"]:
                    combination_critical = item

        if combination_critical is None:
            combinations.append({
                "combination": result.load_reference, "member": None,
                "utilization": 0.0, "status": "N/A",
            })
        else:
            any_applicable = True
            combinations.append(combination_critical)
            if critical is None or combination_critical["utilization"] > critical["utilization"]:
                critical = combination_critical

    if mode == "flexao_obliqua":
        label = "Flexão oblíqua"
        detail = "nenhuma combinação apresentou flexão simultânea nos dois eixos sem esforço axial"
        critical_name = "Flexão oblíqua"
    elif mode == "flexotension":
        label = "Flexotração"
        detail = "nenhuma combinação apresentou tração axial simultânea com momento fletor"
        critical_name = "Flexotração"
    else:
        label = "Flexocompressão"
        detail = "nenhuma combinação apresentou compressão axial simultânea com momento fletor"
        critical_name = "Flexocompressão"

    parameters = {
        "N_Rd_kn": nrd_kn,
        "My_Rd_kn_cm": float(myrd_kn_cm) if myrd_kn_cm is not None else None,
        "Mz_Rd_kn_cm": float(mzrd_kn_cm) if mzrd_kn_cm is not None else None,
        "criterion": "NBR 8800:2024, 5.5.1.2",
    }
    if slender_web_rejected:
        parameters.update({
            "slender_web_rejected": True,
            "lambda_fla": flexion_y_parameters.get("lambda_fla"),
            "lambda_r_fla": flexion_y_parameters.get("lambda_r_fla"),
            "di_cm": flexion_y_parameters.get("di_cm"),
            "tw_cm": flexion_y_parameters.get("tw_cm"),
            "E_kn_cm2": flexion_y_parameters.get("E_kn_cm2"),
            "fy_kn_cm2": flexion_y_parameters.get("fy_kn_cm2"),
            "slenderness_ratio": slenderness_ratio,
        })
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": (
            "reprovado por exceder o limite de esbeltez da alma na verificação de flexão Y"
            if critical and critical.get("slender_web_rejected") else
            "" if any_applicable else detail
        ),
        "utilization": critical["utilization"] if critical else None,
        "critical_check": (
            critical_name + " — reprovação por esbeltez da alma"
            if critical and critical.get("slender_web_rejected") else
            critical_name if critical else "N/A"
        ),
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "position_m": critical["position_m"] if critical else None,
        "applied_kn": critical.get("applied_kn") if critical else None,
        "applied_my_kn_cm": critical.get("applied_my_kn_cm") if critical else None,
        "applied_mz_kn_cm": critical.get("applied_mz_kn_cm") if critical else None,
        "interaction_case": critical.get("interaction_case") if critical else None,
        "parameters": parameters,
        "combinations": combinations,
    }


def verify_u_oblique_bending(element, model, results,
                             flexion_y_check: dict | None,
                             flexion_z_check: dict | None) -> dict:
    """Check biaxial bending without axial force per NBR 8800:2024, 5.5.1.2."""
    return _verify_u_combined_actions(
        element, model, results, "flexao_obliqua", None,
        flexion_y_check, flexion_z_check,
    )


def verify_u_flexotension(element, model, results, tension_check: dict | None,
                          flexion_y_check: dict | None,
                          flexion_z_check: dict | None) -> dict:
    """Check axial tension with bending per NBR 8800:2024, 5.5.1.2."""
    return _verify_u_combined_actions(
        element, model, results, "flexotension", tension_check,
        flexion_y_check, flexion_z_check,
    )


def verify_u_flexocompression(element, model, results, compression_check: dict | None,
                              flexion_y_check: dict | None,
                              flexion_z_check: dict | None) -> dict:
    """Check axial compression with bending per NBR 8800:2024, 5.5.1.2."""
    return _verify_u_combined_actions(
        element, model, results, "flexocompression", compression_check,
        flexion_y_check, flexion_z_check,
    )


def _compression_effective_area(geometry: dict[str, float], elastic_kn_cm2: float,
                                fy_kn_cm2: float, chi: float) -> dict[str, float]:
    d, bf, tw, tf = (float(geometry[key]) for key in ("d", "bf", "tw", "tf"))
    radius = float(geometry.get("r", max(2.0, 1.5 * tf)))
    # NBR 8800:2024, Table 4: U flanges are AL (group 4); the web is AA (group 2).
    flange_width = bf
    web_width = d - 2.0 * tf - 2.0 * radius
    flange_limit = 0.56 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
    web_limit = 1.49 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
    flange_sigma_el = (1.49 * flange_limit / (flange_width / tf)) ** 2 * fy_kn_cm2
    web_sigma_el = (1.31 * web_limit / (web_width / tw)) ** 2 * fy_kn_cm2
    flange_effective = _compression_local_width(
        flange_width, tf, flange_limit, chi, 0.22, 1.49, fy_kn_cm2,
    )
    web_effective = _compression_local_width(
        web_width, tw, web_limit, chi, 0.18, 1.31, fy_kn_cm2,
    )
    ag_cm2 = float(geometry["Ag_cm2"])
    # Keep the rolled fillets in Ag; subtract only the ineffective flat portions.
    aef_cm2 = ag_cm2 - 2.0 * (flange_width - flange_effective) * tf / 100.0
    aef_cm2 -= (web_width - web_effective) * tw / 100.0
    return {
        "flange_width_mm": flange_width, "flange_effective_mm": flange_effective,
        "flange_slenderness": flange_width / tf, "flange_limit": flange_limit,
        "flange_reduced_limit": flange_limit / sqrt(max(chi, 1e-12)),
        "flange_is_slender": flange_width / tf > flange_limit / sqrt(max(chi, 1e-12)),
        "flange_sigma_el_kn_cm2": flange_sigma_el,
        "web_width_mm": web_width, "web_effective_mm": web_effective,
        "web_slenderness": web_width / tw, "web_limit": web_limit,
        "web_reduced_limit": web_limit / sqrt(max(chi, 1e-12)),
        "web_is_slender": web_width / tw > web_limit / sqrt(max(chi, 1e-12)),
        "web_sigma_el_kn_cm2": web_sigma_el,
        "Aef_cm2": max(0.0, min(ag_cm2, aef_cm2)),
    }


def verify_u_compression(element, model, results) -> dict:
    """Check axial compression per NBR 8800:2024, 5.3 for rolled U sections."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section not in {"U Laminado", "U Inclinado Laminado"} for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis U laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(
        member_name not in result.member_results
        for result in results for member_name in element.member_names
    ):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}
    has_compression = any(
        float(sample.get("axial", 0.0)) >= MIN_SIGNIFICANT_COMPRESSION_KN
        for result in results for member_name in element.member_names
        for sample in result.member_results[member_name].get("samples", ())
    )
    if not has_compression:
        return {"status": "not_applicable", "detail": "nenhuma combinação apresentou compressão axial"}

    material_values = model.materials.get(members[0].material, ())
    if len(material_values) < 6:
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, shear_kn_m2 = float(material_values[0]), float(material_values[1])
    fy_kn_m2 = float(material_values[4])
    if min(elastic_kn_m2, shear_kn_m2, fy_kn_m2) <= 0.0:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    restraint_parameters = {}
    try:
        member = members[0]
        geom = member.geometry_dict()
        def dim(name: str) -> float:
            value = geom.get(name, geom.get(f"{name}_mm"))
            if value is None:
                raise ValueError(f"dimensão '{name}' ausente na seção")
            return float(value)
        d, bf, tw, tf = (dim(key) for key in ("d", "bf", "tw", "tf"))
        from osa.memorial_data import _u_properties
        section_properties = _u_properties(member)
        radius = section_properties["r"]
        iy_cm4, iz_cm4 = section_properties["Iy"], section_properties["Iz"]
        it_cm4, cw_cm6 = section_properties["It"], section_properties["Cw"]
        x0_cm = section_properties["x0"]
        ag_cm2 = section_properties["area"]
        material_elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        material_shear_kn_cm2 = shear_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        lengths = restraint_lengths(
            model, element, results, {"Iy": iz_cm4, "tw": tw / 10.0},
        )
        restraint_parameters = {
            "Ly_cm": lengths.lengths_m["Ly"] * 100.0,
            "Lz_cm": lengths.lengths_m["Lz"] * 100.0,
            "Lt_cm": lengths.lengths_m["Lt"] * 100.0,
            "Lb_cm": lengths.lengths_m["Lb"] * 100.0,
            "restraint_issues": list(lengths.issues),
            "restraint_modes": lengths.modes,
            "restraint_notes": list(lengths.notes),
        }
        # These are the Ly, Lz, Lt and Lb parameters shown in the profile
        # memory. Their restraint diagnostics do not suppress compression.
        ly_cm, lz_cm, lt_cm = (lengths.lengths_m[name] * 100.0 for name in ("Ly", "Lz", "Lt"))
        if min(ly_cm, lz_cm, lt_cm) <= 0.0:
            raise ValueError("comprimentos destravados não determinados")
        ry2_cm2, rz2_cm2 = iy_cm4 / ag_cm2, iz_cm4 / ag_cm2
        r0_squared_cm2 = ry2_cm2 + rz2_cm2 + x0_cm**2
        ne_y_kn = pi**2 * material_elastic_kn_cm2 * iy_cm4 / ly_cm**2
        ne_z_kn = pi**2 * material_elastic_kn_cm2 * iz_cm4 / lz_cm**2
        ne_t_kn = (
            pi**2 * material_elastic_kn_cm2 * cw_cm6 / lt_cm**2
            + material_shear_kn_cm2 * it_cm4
        ) / r0_squared_cm2
        h_flexotorsion = 1.0 - x0_cm**2 / r0_squared_cm2
        if h_flexotorsion <= 0.0:
            raise ValueError("parâmetro de flexo-torção inválido")
        radical = 1.0 - (
            4.0 * ne_y_kn * ne_t_kn * h_flexotorsion
            / (ne_y_kn + ne_t_kn) ** 2
        )
        ne_yt_kn = (
            (ne_y_kn + ne_t_kn) / (2.0 * h_flexotorsion)
            * (1.0 - sqrt(max(0.0, radical)))
        )
        ne_kn = min(ne_z_kn, ne_yt_kn)
        if ne_kn <= 0.0:
            raise ValueError("força axial de flambagem inválida")

        # NBR 8800:2024, 5.3.3.2 uses gross area Ag in lambda_0.
        lambda0 = sqrt(ag_cm2 * fy_kn_cm2 / ne_kn)
        chi = (0.658 ** (lambda0**2)) if lambda0 <= 1.5 else 0.877 / lambda0**2
        effective = _compression_effective_area(
            {"d": d, "bf": bf, "tw": tw, "tf": tf, "r": radius, "Ag_cm2": ag_cm2},
            material_elastic_kn_cm2, fy_kn_cm2, chi,
        )
        ncrd_kn = chi * effective["Aef_cm2"] * fy_kn_cm2 / GAMMA_A1
        slenderness_y = ly_cm / sqrt(ry2_cm2)
        slenderness_z = lz_cm / sqrt(rz2_cm2)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        result = {
            "status": "not_checked",
            "detail": str(error) or "geometria ou contenções inválidas",
        }
        if restraint_parameters:
            result["parameters"] = restraint_parameters
        return result

    combinations = []
    critical = None
    for result in results:
        governing = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                # OSA verification convention: positive axial force is compression.
                axial_kn = float(sample.get("axial", 0.0))
                if axial_kn >= MIN_SIGNIFICANT_COMPRESSION_KN:
                    compression_kn = axial_kn
                    if governing is None or compression_kn > governing[0]:
                        governing = (compression_kn, member_name)
        if governing is None:
            combinations.append({"combination": result.load_reference, "member": None,
                                 "applied_kn": 0.0, "utilization": 0.0, "status": "N/A"})
            continue
        applied_kn, member_name = governing
        utilization = applied_kn / ncrd_kn if ncrd_kn > 0.0 else float("inf")
        item = {"combination": result.load_reference, "member": member_name,
                "applied_kn": applied_kn, "utilization": utilization,
                "status": "APROVADO" if utilization <= 1.0 else "REPROVADO"}
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item

    parameters = {
        **restraint_parameters,
        "Ag_cm2": ag_cm2, "Aef_cm2": effective["Aef_cm2"],
        "tf_mm": tf, "tw_mm": tw,
        "fy_kn_m2": fy_kn_m2, "fy_kn_cm2": fy_kn_cm2,
        "E_kn_m2": elastic_kn_m2, "G_kn_m2": shear_kn_m2,
        "E_kn_cm2": material_elastic_kn_cm2, "G_kn_cm2": material_shear_kn_cm2,
        "gamma_a1": GAMMA_A1, "Iy_cm4": iy_cm4, "Iz_cm4": iz_cm4,
        "ry_cm": sqrt(ry2_cm2), "rz_cm": sqrt(rz2_cm2),
        "r0_cm": sqrt(r0_squared_cm2), "x0_cm": x0_cm,
        "H_flexotorsion": h_flexotorsion,
        "It_cm4": it_cm4, "Cw_cm6": cw_cm6,
        "Ney_kn": ne_y_kn, "Nez_kn": ne_z_kn, "Net_kn": ne_t_kn,
        "Neyt_kn": ne_yt_kn, "Ne_kn": ne_kn, "Ne_governing": min(
            ((ne_z_kn, "Flambagem por flexão em Z"),
             (ne_yt_kn, "Flambagem por flexo-torção em Y")), key=lambda item: item[0],
        )[1],
        "lambda0": lambda0, "chi": chi, "Nc_Rd_kn": ncrd_kn,
        "flange_width_mm": effective["flange_width_mm"],
        "flange_effective_mm": effective["flange_effective_mm"],
        "flange_slenderness": effective["flange_slenderness"],
        "flange_limit": effective["flange_limit"],
        "flange_reduced_limit": effective["flange_reduced_limit"],
        "flange_is_slender": effective["flange_is_slender"],
        "flange_sigma_el_kn_cm2": effective["flange_sigma_el_kn_cm2"],
        "web_width_mm": effective["web_width_mm"],
        "web_effective_mm": effective["web_effective_mm"],
        "web_slenderness": effective["web_slenderness"],
        "web_limit": effective["web_limit"],
        "web_reduced_limit": effective["web_reduced_limit"],
        "web_is_slender": effective["web_is_slender"],
        "web_sigma_el_kn_cm2": effective["web_sigma_el_kn_cm2"],
        "slenderness_y": slenderness_y, "slenderness_z": slenderness_z,
        "slenderness_limit": 200.0,
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou compressão axial",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Compressão axial" if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied_kn"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }
