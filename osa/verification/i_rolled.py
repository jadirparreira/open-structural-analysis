"""Axial tension check for rolled I sections."""

from __future__ import annotations

from math import pi, sqrt, tan

from osa.sections.contours import i_contour_points, polygon_properties
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
    points = i_contour_points(
        d, bf, tw, tf,
        float(geometry.get("r1", geometry.get("r1_mm", 0.0))) or None,
        float(geometry.get("r2", geometry.get("r2_mm", 0.0))) or None,
        float(geometry.get("flange_angle_deg", 2.0)),
    )
    area_mm2, *_ = polygon_properties(points)
    return area_mm2 / 100.0


def verify_i_tension(element, model, results) -> dict:
    """Check gross-section yielding and effective-net-section rupture only."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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


def verify_i_slenderness(element, model, results) -> dict:
    """Report the recommended member slenderness limits for rolled I sections."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
    if any(not member.section_geometry for member in members):
        return {"status": "not_checked", "detail": "geometria da seção incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}

    try:
        from osa.memorial_data import _i_properties

        member = members[0]
        geometry = _i_properties(member)
        area_cm2 = geometry["area"]
        iy_cm4, iz_cm4 = geometry["Iy"], geometry["Iz"]
        if min(area_cm2, iy_cm4, iz_cm4) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para a esbeltez")
        lengths = restraint_lengths(
            model, element, results or (), {"Iy": iz_cm4, "tw": geometry["tw"] / 10.0},
        )
        ly_cm = lengths.lengths_m["Ly"] * 100.0
        lz_cm = lengths.lengths_m["Lz"] * 100.0
        ry_cm = sqrt(iy_cm4 / area_cm2)
        rz_cm = sqrt(iz_cm4 / area_cm2)
        if min(ly_cm, lz_cm, ry_cm, rz_cm) <= 0.0:
            raise ValueError("comprimentos destravados ou raios de giração inválidos")
        lambda_y, lambda_z = ly_cm / ry_cm, lz_cm / rz_cm
        has_tension = any(
            float(sample.get("axial", 0.0)) <= -MIN_SIGNIFICANT_TENSION_KN
            for result in results or () for name in element.member_names
            for sample in result.member_results.get(name, {}).get("samples", ())
        )
        has_compression = any(
            float(sample.get("axial", 0.0)) >= MIN_SIGNIFICANT_COMPRESSION_KN
            for result in results or () for name in element.member_names
            for sample in result.member_results.get(name, {}).get("samples", ())
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    return {
        "status": "checked",
        "has_tension": has_tension,
        "has_compression": has_compression,
        "parameters": {
            "Ly_cm": ly_cm, "Lz_cm": lz_cm,
            "ry_cm": ry_cm, "rz_cm": rz_cm,
            "lambda_y": lambda_y, "lambda_z": lambda_z,
            "lambda_tension_max": max(lambda_y, lambda_z),
            "tension_limit": 300.0,
            "compression_limit": 200.0,
        },
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


def verify_i_flexion_y(element, model, results) -> dict:
    """Check major-axis flexion of rolled I sections per NBR 8800:2024, 5.4."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        from osa.memorial_data import _i_properties

        member = members[0]
        geometry = _i_properties(member)
        # Flexão Y in the application follows the section's major axis properties.
        # I-section properties come from the I contour in the memorial helper.
        iy_cm4 = geometry["Iy"]
        wy_cm3 = geometry["Wy"]
        zy_cm3 = geometry["Zy"]
        rz_cm = geometry["rz"]
        it_cm4 = geometry["It"]
        cw_cm6 = geometry["Cw"]
        bf_mm, tf_mm, tw_mm, di_mm = (geometry[key] for key in ("bf", "tf", "tw", "d"))
        di_mm -= 2.0 * tf_mm
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

        lambda_flm = bf_cm / (2.0 * tf_cm)
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
        if lambda_fla <= lambda_p_fla:
            mn_fla_kn_cm = mp_kn_cm
        else:
            # Keep the extended interpolation defined in the supplied routine.
            mn_fla_kn_cm = max(0.0, min(
                mp_kn_cm,
                mp_kn_cm - (mp_kn_cm - mr_kn_cm)
                * ((lambda_fla - lambda_p_fla) / (lambda_r_fla - lambda_p_fla)),
            ))
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


def verify_i_flexion_z(element, model, results) -> dict:
    """Check weak-axis flexion of rolled I sections per NBR 8800:2024, Anexo D."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        from osa.memorial_data import _i_properties

        geometry = _i_properties(members[0])
        wz_cm3, zz_cm3 = geometry["Wz"], geometry["Zz"]
        bf_cm, tf_cm = geometry["bf"] / 10.0, geometry["tf"] / 10.0
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        gamma_a1 = GAMMA_A1
        sigma_r_kn_cm2 = 0.30 * fy_kn_cm2
        if min(wz_cm3, zz_cm3, tf_cm) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para Flexão Z")

        mp_kn_cm = zz_cm3 * fy_kn_cm2
        mr_kn_cm = (fy_kn_cm2 - sigma_r_kn_cm2) * wz_cm3
        lambda_flm_z = bf_cm / (2.0 * tf_cm)
        lambda_p_flm_z = 0.38 * sqrt(elastic_kn_cm2 / fy_kn_cm2)
        lambda_r_flm_z = 0.83 * sqrt(elastic_kn_cm2 / (fy_kn_cm2 - sigma_r_kn_cm2))
        mcr_flm_z_kn_cm = 0.69 * elastic_kn_cm2 * wz_cm3 / lambda_flm_z**2

        if lambda_flm_z <= lambda_p_flm_z:
            mn_flm_z_kn_cm = mp_kn_cm
        elif lambda_flm_z <= lambda_r_flm_z:
            mn_flm_z_kn_cm = min(
                mp_kn_cm - (mp_kn_cm - mr_kn_cm)
                * ((lambda_flm_z - lambda_p_flm_z)
                   / (lambda_r_flm_z - lambda_p_flm_z)),
                mp_kn_cm,
            )
        else:
            mn_flm_z_kn_cm = min(mcr_flm_z_kn_cm, mp_kn_cm)
        mrd_flm_z_kn_cm = mn_flm_z_kn_cm / gamma_a1

        # NBR 8800:2024, 5.4.2.2 limits MRd to 1.50 W fy / gamma_a1.
        mrd_limit_kn_cm = 1.50 * wz_cm3 * fy_kn_cm2 / gamma_a1
        mz_rd_kn_cm = min(mrd_flm_z_kn_cm, mrd_limit_kn_cm)
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
        "sigma_r_kn_cm2": sigma_r_kn_cm2, "gamma_a1": gamma_a1,
        "Wz_cm3": wz_cm3, "Zz_cm3": zz_cm3,
        "bf_cm": bf_cm, "tf_cm": tf_cm,
        "Mp_z_kn_cm": mp_kn_cm, "Mr_z_kn_cm": mr_kn_cm,
        "lambda_flm_z": lambda_flm_z,
        "lambda_p_flm_z": lambda_p_flm_z,
        "lambda_r_flm_z": lambda_r_flm_z,
        "Mcr_flm_z_kn_cm": mcr_flm_z_kn_cm,
        "Mn_flm_z_kn_cm": mn_flm_z_kn_cm,
        "Mrd_flm_z_kn_cm": mrd_flm_z_kn_cm,
        "Mrd_limit_kn_cm": mrd_limit_kn_cm,
        "Mrd_z_kn_cm": mz_rd_kn_cm,
        "governing": "FLM-Z" if mrd_flm_z_kn_cm <= mrd_limit_kn_cm else "Limite 5.4.2.2",
    }
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou momento fletor em Z",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Flexão Z — " + parameters["governing"] if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn_cm": critical["applied_kn_cm"] if critical else None,
        "parameters": parameters, "combinations": combinations,
    }


def verify_i_shear_y(element, model, results) -> dict:
    """Check shear along local Y of rolled I sections per NBR 8800:2024, 5.4.3.5."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        from osa.memorial_data import _i_properties

        geometry = _i_properties(members[0])
        bf_cm, tf_cm = geometry["bf"] / 10.0, geometry["tf"] / 10.0
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        gamma_a1 = GAMMA_A1
        kv_y = 1.2
        if min(bf_cm, tf_cm) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para Cortante Y")

        aw_cm2 = 2.0 * bf_cm * tf_cm
        vp_y_kn = 0.60 * aw_cm2 * fy_kn_cm2
        lambda_y = (bf_cm / 2.0) / tf_cm
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


def verify_i_shear_z(element, model, results) -> dict:
    """Check shear along local Z of rolled I sections per NBR 8800:2024, 5.4.3.1."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        from osa.memorial_data import _i_properties

        geometry = _i_properties(members[0])
        section_geometry = members[0].geometry_dict()
        radius_mm = float(section_geometry.get(
            "r1", section_geometry.get("r1_mm", geometry["tf"]),
        ))
        d_cm = geometry["d"] / 10.0
        tw_cm = geometry["tw"] / 10.0
        h_cm = (geometry["d"] - 2.0 * geometry["tf"] - 2.0 * radius_mm) / 10.0
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


def _verify_i_combined_actions(element, model, results, mode: str,
                               axial_check: dict | None,
                               flexion_y_check: dict | None,
                               flexion_z_check: dict | None) -> dict:
    """Evaluate one NBR 8800:2024, 5.5.1.2 interaction at concurrent stations."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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

                if mode != "flexao_obliqua" and (nrd_kn is None or nrd_kn <= 0.0):
                    axial_label = "compressão" if mode == "flexocompression" else "tração"
                    return {
                        "status": "not_checked",
                        "detail": f"resistência axial de cálculo à {axial_label} indisponível",
                    }
                if has_my and (myrd_kn_cm is None or float(myrd_kn_cm) <= 0.0):
                    return {"status": "not_checked", "detail": "resistência à flexão em Y indisponível"}
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
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if any_applicable else detail,
        "utilization": critical["utilization"] if critical else None,
        "critical_check": critical_name if critical else "N/A",
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


def verify_i_biaxial_shear(element, model, results) -> dict:
    """Check simultaneous shear in both principal axes for rolled I sections."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        return {"status": "not_checked", "detail": "propriedades do material não definidas"}
    elastic_kn_m2, poisson, fy_kn_m2 = (
        float(material_values[index]) for index in (0, 2, 4)
    )
    if min(elastic_kn_m2, fy_kn_m2) <= 0.0 or not -1.0 < poisson < 0.5:
        return {"status": "not_checked", "detail": "propriedades do material inválidas"}

    try:
        from osa.memorial_data import _i_properties

        geometry = _i_properties(members[0])
        bf_cm, tf_cm = geometry["bf"] / 10.0, geometry["tf"] / 10.0
        tw_cm, d_cm = geometry["tw"] / 10.0, geometry["d"] / 10.0
        raw_geometry = members[0].geometry_dict()
        r1_mm = float(raw_geometry.get("r1", raw_geometry.get("r1_mm", 0.0))) or geometry["tf"]
        r2_mm = float(raw_geometry.get("r2", raw_geometry.get("r2_mm", 0.0))) or max(
            0.75, 0.8 * geometry["tf"],
        )
        flange_angle = float(raw_geometry.get("flange_angle_deg", 2.0))
        free_half_flange = max(0.0, bf_cm * 5.0 - tw_cm * 5.0 - r1_mm - r2_mm)
        flange_rise_cm = free_half_flange * tan(flange_angle * pi / 180.0) / 10.0
        web_height_cm = d_cm - 2.0 * tf_cm - 2.0 * r1_mm / 10.0 - 2.0 * flange_rise_cm
        iy_cm4, iz_cm4 = geometry["Iy"], geometry["Iz"]
        elastic_kn_cm2 = elastic_kn_m2 / 10_000.0
        fy_kn_cm2 = fy_kn_m2 / 10_000.0
        if min(bf_cm, tf_cm, tw_cm, web_height_cm, iy_cm4, iz_cm4, fy_kn_cm2) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para cortantes simultâneos")

        # Estimate the flange-root shear using half of the symmetric flange;
        # recover the web first moment from the actual I-section contour.
        r1_cm = r1_mm / 10.0
        fillet_area_cm2 = (1.0 - pi / 4.0) * r1_cm**2
        q_flange_cm3 = (
            (bf_cm / 2.0 * tf_cm) * ((d_cm - tf_cm) / 2.0)
            + fillet_area_cm2 * (d_cm / 2.0 - tf_cm - r1_cm / 3.0)
        )
        points = i_contour_points(
            geometry["d"], geometry["bf"], geometry["tw"], geometry["tf"],
            r1_mm, r2_mm, flange_angle,
        )
        upper = []
        previous = points[-1]
        previous_inside = previous[1] >= 0.0
        for current in points:
            current_inside = current[1] >= 0.0
            if current_inside != previous_inside:
                fraction = -previous[1] / (current[1] - previous[1])
                upper.append((
                    previous[0] + fraction * (current[0] - previous[0]),
                    0.0,
                ))
            if current_inside:
                upper.append(current)
            previous, previous_inside = current, current_inside
        upper_area_mm2, _, upper_centroid_z_mm, *_ = polygon_properties(tuple(upper))
        q_web_cm3 = upper_area_mm2 * upper_centroid_z_mm / 1000.0
        tau_y_per_kn = q_flange_cm3 / (iz_cm4 * tf_cm)
        tau_z_per_kn = q_web_cm3 / (iy_cm4 * tw_cm)

        poisson_factor = 12.0 * (1.0 - poisson**2)
        tau_e_y_kn_cm2 = (
            1.2 * pi**2 * elastic_kn_cm2 / poisson_factor
            * (tf_cm / (bf_cm / 2.0))**2
        )
        tau_e_z_kn_cm2 = (
            5.34 * pi**2 * elastic_kn_cm2 / poisson_factor
            * (tw_cm / web_height_cm)**2
        )
        lambda0_y = sqrt(0.60 * fy_kn_cm2 / tau_e_y_kn_cm2)
        lambda0_z = sqrt(0.60 * fy_kn_cm2 / tau_e_z_kn_cm2)
        chi_y = 0.658 ** (lambda0_y**2) if lambda0_y <= 1.5 else 0.877 / lambda0_y**2
        chi_z = 0.658 ** (lambda0_z**2) if lambda0_z <= 1.5 else 0.877 / lambda0_z**2
        chi = min(chi_y, chi_z)
        tau_rd_kn_cm2 = 0.60 * chi * fy_kn_cm2 / GAMMA_A1
        if min(tau_y_per_kn, tau_z_per_kn, tau_rd_kn_cm2) <= 0.0:
            raise ValueError("tensão resistente de cálculo não positiva")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error) or "geometria inválida"}

    combinations = []
    critical = None
    for result in results:
        combination_critical = None
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                vy_kn = abs(float(sample.get("shear_y", 0.0)))
                vz_kn = abs(float(sample.get("shear_z", 0.0)))
                if min(vy_kn, vz_kn) < MIN_SIGNIFICANT_SHEAR_KN:
                    continue
                tau_y = vy_kn * tau_y_per_kn
                tau_z = vz_kn * tau_z_per_kn
                tau_sd = sqrt(tau_y**2 + tau_z**2)
                utilization = tau_sd / tau_rd_kn_cm2
                item = {
                    "combination": result.load_reference,
                    "member": member_name,
                    "position_m": float(sample.get("x", 0.0)),
                    "shear_y_kn": vy_kn, "shear_z_kn": vz_kn,
                    "tau_y_kn_cm2": tau_y, "tau_z_kn_cm2": tau_z,
                    "tau_sd_kn_cm2": tau_sd,
                    "utilization": utilization,
                    "status": "APROVADO" if utilization <= 1.0 else "REPROVADO",
                }
                if combination_critical is None or utilization > combination_critical["utilization"]:
                    combination_critical = item
        if combination_critical is None:
            combinations.append({
                "combination": result.load_reference,
                "member": None, "utilization": 0.0, "status": "N/A",
            })
        else:
            combinations.append(combination_critical)
            if critical is None or combination_critical["utilization"] > critical["utilization"]:
                critical = combination_critical

    return {
        "status": "checked" if critical else "not_applicable",
        "detail": (
            "verificação de cortantes simultâneos em Y e Z concluída"
            if critical else
            "nenhuma combinação apresentou cortantes simultâneos significativos"
        ),
        "utilization": critical["utilization"] if critical else None,
        "critical_check": "Cortantes simultâneos em Y e Z" if critical else "N/A",
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "position_m": critical["position_m"] if critical else None,
        "applied_shear_y_kn": critical["shear_y_kn"] if critical else None,
        "applied_shear_z_kn": critical["shear_z_kn"] if critical else None,
        "tau_y_kn_cm2": critical["tau_y_kn_cm2"] if critical else None,
        "tau_z_kn_cm2": critical["tau_z_kn_cm2"] if critical else None,
        "tau_sd_kn_cm2": critical["tau_sd_kn_cm2"] if critical else None,
        "parameters": {
            "bf_cm": bf_cm, "tf_cm": tf_cm, "tw_cm": tw_cm,
            "d_cm": d_cm, "h_cm": web_height_cm,
            "Iy_cm4": iy_cm4, "Iz_cm4": iz_cm4,
            "Q_flange_cm3": q_flange_cm3, "Q_web_cm3": q_web_cm3,
            "tau_y_per_kn": tau_y_per_kn, "tau_z_per_kn": tau_z_per_kn,
            "fy_kn_cm2": fy_kn_cm2, "gamma_a1": GAMMA_A1,
            "E_kn_cm2": elastic_kn_cm2, "poisson": poisson,
            "tau_e_y_kn_cm2": tau_e_y_kn_cm2,
            "tau_e_z_kn_cm2": tau_e_z_kn_cm2,
            "lambda0_y": lambda0_y, "lambda0_z": lambda0_z,
            "chi_y": chi_y, "chi_z": chi_z, "chi": chi,
            "tau_rd_kn_cm2": tau_rd_kn_cm2,
            "stress_method": "Q/(I t), máximos de mesa e alma combinados conservadoramente",
            "criterion": "NBR 8800:2024, 5.5.1.3 e 5.5.2.3(b), (d)",
        },
        "combinations": combinations,
    }


def verify_i_oblique_bending(element, model, results,
                             flexion_y_check: dict | None,
                             flexion_z_check: dict | None) -> dict:
    """Check biaxial bending without axial force per NBR 8800:2024, 5.5.1.2."""
    return _verify_i_combined_actions(
        element, model, results, "flexao_obliqua", None,
        flexion_y_check, flexion_z_check,
    )


def verify_i_flexotension(element, model, results, tension_check: dict | None,
                          flexion_y_check: dict | None,
                          flexion_z_check: dict | None) -> dict:
    """Check axial tension with bending per NBR 8800:2024, 5.5.1.2."""
    return _verify_i_combined_actions(
        element, model, results, "flexotension", tension_check,
        flexion_y_check, flexion_z_check,
    )


def verify_i_flexocompression(element, model, results, compression_check: dict | None,
                              flexion_y_check: dict | None,
                              flexion_z_check: dict | None) -> dict:
    """Check axial compression with bending per NBR 8800:2024, 5.5.1.2."""
    return _verify_i_combined_actions(
        element, model, results, "flexocompression", compression_check,
        flexion_y_check, flexion_z_check,
    )


def _compression_effective_area(geometry: dict[str, float], elastic_kn_cm2: float,
                                fy_kn_cm2: float, chi: float) -> dict[str, float]:
    d, bf, tw, tf = (float(geometry[key]) for key in ("d", "bf", "tw", "tf"))
    # Table 4: I rolled flange outstands are AL (group 4), and the web is AA (group 2).
    # Table 4, group 4: for a rolled I flange, b runs from the web axis to
    # the flange edge, so each outstand has width bf/2.
    flange_width = bf / 2.0
    web_width = d - 2.0 * tf
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
    aef_cm2 = ag_cm2 - 4.0 * (flange_width - flange_effective) * tf / 100.0
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


def verify_i_compression(element, model, results) -> dict:
    """Check axial compression per NBR 8800:2024, 5.3 for rolled I sections."""
    members = [model.bars[name] for name in element.member_names if name in model.bars]
    if not members or len(members) != len(element.member_names):
        return {"status": "not_checked", "detail": "barra não encontrada no modelo"}
    if any(member.section != "I Laminado" for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis I laminados"}
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
        area_mm2, *_ = polygon_properties(i_contour_points(
            d, bf, tw, tf,
            float(geom.get("r1", geom.get("r1_mm", 0.0))) or None,
            float(geom.get("r2", geom.get("r2_mm", 0.0))) or None,
            float(geom.get("flange_angle_deg", 2.0)),
        ))
        iy_cm4 = float(geom.get("Iy_cm4", 0.0))
        iz_cm4 = float(geom.get("Iz_cm4", 0.0))
        # Properties are calculated from the same rounded contour used for Ag.
        if iy_cm4 <= 0.0 or iz_cm4 <= 0.0:
            from osa.memorial_data import _i_properties
            section_properties = _i_properties(member)
            iy_cm4, iz_cm4 = section_properties["Iy"], section_properties["Iz"]
            it_cm4, cw_cm6 = section_properties["It"], section_properties["Cw"]
        else:
            section_properties = None
            it_cm4 = cw_cm6 = 0.0
        if section_properties is None:
            from osa.memorial_data import _i_properties
            section_properties = _i_properties(member)
            it_cm4, cw_cm6 = section_properties["It"], section_properties["Cw"]
        ag_cm2 = area_mm2 / 100.0
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
        r0_squared_cm2 = ry2_cm2 + rz2_cm2
        ne_y_kn = pi**2 * material_elastic_kn_cm2 * iy_cm4 / ly_cm**2
        ne_z_kn = pi**2 * material_elastic_kn_cm2 * iz_cm4 / lz_cm**2
        ne_t_kn = (
            pi**2 * material_elastic_kn_cm2 * cw_cm6 / lt_cm**2
            + material_shear_kn_cm2 * it_cm4
        ) / r0_squared_cm2
        ne_kn = min(ne_y_kn, ne_z_kn, ne_t_kn)
        if ne_kn <= 0.0:
            raise ValueError("força axial de flambagem inválida")

        # NBR 8800:2024, 5.3.3.2 uses gross area Ag in lambda_0.
        lambda0 = sqrt(ag_cm2 * fy_kn_cm2 / ne_kn)
        chi = (0.658 ** (lambda0**2)) if lambda0 <= 1.5 else 0.877 / lambda0**2
        effective = _compression_effective_area(
            {"d": d, "bf": bf, "tw": tw, "tf": tf, "Ag_cm2": ag_cm2},
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
        "r0_cm": sqrt(r0_squared_cm2), "It_cm4": it_cm4, "Cw_cm6": cw_cm6,
        "Ney_kn": ne_y_kn, "Nez_kn": ne_z_kn, "Net_kn": ne_t_kn,
        "Ne_kn": ne_kn, "Ne_governing": min(
            ((ne_y_kn, "Flambagem por flexão em Y"),
             (ne_z_kn, "Flambagem por flexão em Z"),
             (ne_t_kn, "Flambagem por torção")), key=lambda item: item[0],
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
