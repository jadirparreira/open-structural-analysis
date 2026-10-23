"""NBR 8800 resistance checks for solid rectangular steel bars."""

from __future__ import annotations

from itertools import pairwise
from math import pi, sqrt

from osa.verification.restraints import restraint_lengths

GAMMA_A1 = 1.10
GAMMA_A2 = 1.35
EPS = 1e-12
MIN_FORCE_KN = 0.001
MIN_MOMENT_KN_M = 0.001
MIN_SHEAR_KN = 0.001


def _section(member) -> dict[str, float]:
    geometry = member.geometry_dict()
    try:
        b = float(geometry.get("b", geometry.get("b_mm")))
        h_value = geometry.get("h", geometry.get("h_mm"))
        h = b if member.section == "Barra Quadrada" and h_value is None else float(h_value)
    except (TypeError, ValueError) as error:
        raise ValueError("dimensões b e h da barra não foram definidas") from error
    if min(b, h) <= 0.0:
        raise ValueError("dimensões da barra retangular devem ser positivas")
    if member.section == "Barra Quadrada" and abs(b - h) > EPS * max(b, h):
        raise ValueError("a barra quadrada deve ter lados iguais")
    area = b * h
    iy = b * h**3 / 12.0
    iz = h * b**3 / 12.0
    long_side, short_side = max(b, h), min(b, h)
    ratio = short_side / long_side
    it = long_side * short_side**3 * (1.0 / 3.0 - 0.21 * ratio * (1.0 - ratio**4 / 12.0))
    wy, wz = iy / (h / 2.0), iz / (b / 2.0)
    zy, zz = b * h**2 / 4.0, h * b**2 / 4.0
    return {
        "b_mm": b, "h_mm": h, "Ag_cm2": area / 100.0,
        "Iy_cm4": iy / 1e4, "Iz_cm4": iz / 1e4,
        "Wy_cm3": wy / 1e3, "Wz_cm3": wz / 1e3,
        "Zy_cm3": zy / 1e3, "Zz_cm3": zz / 1e3,
        "ry_cm": sqrt(iy / area) / 10.0,
        "rz_cm": sqrt(iz / area) / 10.0,
        "It_cm4": it / 1e4,
        "r0_cm": sqrt(iy / area + iz / area) / 10.0,
    }


def _members(element, model, family="Barra Retangular"):
    members = [model.bars.get(name) for name in element.member_names]
    if not members or any(member is None for member in members):
        raise ValueError("barra não encontrada no modelo")
    if any(member.section != family for member in members):
        raise ValueError(f"a rotina atende apenas a seção {family}")
    if any(not member.section_geometry for member in members):
        raise ValueError("geometria da seção incompleta")
    if len({(m.profile, m.section_geometry, m.material) for m in members}) != 1:
        raise ValueError("grupo com seções ou materiais diferentes")
    return members


def _base(element, model, results, family="Barra Retangular"):
    members = _members(element, model, family)
    if not results or any(member.name not in result.member_results
                          for result in results for member in members):
        raise ValueError("resultados de análise indisponíveis")
    material = model.materials.get(members[0].material, ())
    if len(material) < 6:
        raise ValueError("propriedades do material não definidas")
    e, g, fy, fu = (float(material[i]) / 10000.0 for i in (0, 1, 4, 5))
    if min(e, g, fy, fu) <= 0.0:
        raise ValueError("propriedades do material inválidas")
    return members, _section(members[0]), e, g, fy, fu


def _samples(results, members):
    for result in results:
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                yield result, member.name, sample


def _axial_result(results, members, compression: bool, capacity: float):
    field_sign = 1.0 if compression else -1.0
    combinations, critical = [], None
    for result in results:
        demand, owner = 0.0, None
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                raw = float(sample.get("axial", 0.0)) * field_sign
                if raw > demand:
                    demand, owner = raw, member.name
        if demand < MIN_FORCE_KN:
            combinations.append({"combination": result.load_reference, "member": None,
                                 "applied_kn": 0.0, "utilization": 0.0, "status": "N/A"})
            continue
        utilization = demand / max(capacity, EPS)
        item = {"combination": result.load_reference, "member": owner,
                "applied_kn": demand, "utilization": utilization,
                "status": "APROVADO" if utilization <= 1.0 else "REPROVADO"}
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou solicitação neste modo",
        "utilization": critical["utilization"] if critical else None,
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied_kn"] if critical else None,
        "parameters": {}, "combinations": combinations,
    }


def verify_rectangular_bar_tension(element, model, results, family="Barra Retangular"):
    try:
        members, p, _, _, fy, fu = _base(element, model, results, family)
        gross = p["Ag_cm2"] * fy / GAMMA_A1
        rupture = p["Ag_cm2"] * fu / GAMMA_A2
        capacity = min(gross, rupture)
        out = _axial_result(results, members, False, capacity)
        out["parameters"] = {
            "Ag_cm2": p["Ag_cm2"], "An_cm2": p["Ag_cm2"], "Ae_cm2": p["Ag_cm2"],
            "Ct": 1.0, "fy_kn_cm2": fy, "fu_kn_cm2": fu,
            "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
            "Nt_Rd1_kn": gross, "Nt_Rd2_kn": rupture, "Nt_Rd_kn": capacity,
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_rectangular_bar_compression(element, model, results, family="Barra Retangular"):
    try:
        members, p, e, g, fy, _ = _base(element, model, results, family)
        lengths = restraint_lengths(
            model, element, results, {"Iy": p["Iy_cm4"], "tw": min(p["b_mm"], p["h_mm"]) / 10.0},
        )
        ly, lz, lt, lb = (lengths.lengths_m[key] * 100.0 for key in ("Ly", "Lz", "Lt", "Lb"))
        if min(ly, lz, lt, lb) <= 0.0:
            raise ValueError("comprimentos destravados inválidos")
        area = p["Ag_cm2"]
        iy, iz, it = p["Iy_cm4"], p["Iz_cm4"], p["It_cm4"]
        ney = pi**2 * e * iy / ly**2
        nez = pi**2 * e * iz / lz**2
        r0_sq = iy / area + iz / area
        net = g * it / r0_sq
        ne = min(ney, nez, net)
        lambda0 = sqrt(area * fy / ne)
        chi = 0.658 ** (lambda0**2) if lambda0 <= 1.5 else 0.877 / lambda0**2
        capacity = chi * area * fy / GAMMA_A1
        out = _axial_result(results, members, True, capacity)
        out["parameters"] = {
            "Ag_cm2": area, "Aef_cm2": area, "Iy_cm4": iy, "Iz_cm4": iz,
            "It_cm4": it, "r0_cm": sqrt(r0_sq), "E_kn_cm2": e,
            "fy_kn_cm2": fy, "G_kn_cm2": g,
            "Ly_cm": ly, "Lz_cm": lz, "Lt_cm": lt, "Lb_cm": lb,
            "Ney_kn": ney, "Nez_kn": nez, "Net_kn": net, "Ne_kn": ne,
            "lambda0": lambda0, "chi": chi, "gamma_a1": GAMMA_A1,
            "Nc_Rd_kn": capacity,
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _moment_gradient_factor(samples, field: str) -> float:
    """Return Cb from NBR 8800:2024, 5.4.2.3 when station data allow it."""
    stations = sorted((float(sample["x"]), abs(float(sample.get(field, 0.0))))
                      for sample in samples if sample.get("x") is not None)
    if len({position for position, _ in stations}) < 4:
        return 1.0
    start, end = stations[0][0], stations[-1][0]
    if end - start <= EPS:
        return 1.0

    def value_at(fraction: float) -> float:
        target = start + fraction * (end - start)
        for (x0, m0), (x1, m1) in pairwise(stations):
            if x0 <= target <= x1:
                if x1 - x0 <= EPS:
                    return max(m0, m1)
                return m0 + (m1 - m0) * (target - x0) / (x1 - x0)
        return stations[0][1] if target < start else stations[-1][1]

    mmax = max(moment for _, moment in stations)
    if mmax <= EPS:
        return 1.0
    ma, mb, mc = (value_at(part) for part in (0.25, 0.50, 0.75))
    factor = 12.5 * mmax / (2.5 * mmax + 3.0 * ma + 4.0 * mb + 3.0 * mc)
    return min(2.5, max(1.0, factor))


def _flexion(element, model, results, axis: str, family="Barra Retangular"):
    try:
        members, p, e, _, fy, _ = _base(element, model, results, family)
        iy, iz = p["Iy_cm4"], p["Iz_cm4"]
        strong_axis = iy >= iz
        is_strong = family == "Barra Quadrada" or (strong_axis if axis == "y" else not strong_axis)
        w = p["Wy_cm3"] if axis == "y" else p["Wz_cm3"]
        z = p["Zy_cm3"] if axis == "y" else p["Zz_cm3"]
        mp = z * fy
        if is_strong:
            lengths = restraint_lengths(
                model, element, results, {"Iy": iz, "tw": min(p["b_mm"], p["h_mm"]) / 10.0},
            )
            lb = lengths.lengths_m["Lb"] * 100.0
            if lb <= 0.0:
                raise ValueError("comprimento destravado à flexão inválido")
            lam = lb / sqrt(min(iy, iz) / p["Ag_cm2"])
            ja = p["It_cm4"] * p["Ag_cm2"]
            lambda_p = 0.13 * e * sqrt(ja) / max(mp, EPS)
            mr = fy * w
            def strength(cb_value):
                lambda_r_value = 2.0 * cb_value * e * sqrt(ja) / max(mr, EPS)
                mcr_value = 2.0 * e * cb_value * sqrt(ja) / lam
                if lam <= lambda_p:
                    mn_value = mp
                elif lam <= lambda_r_value:
                    mn_value = mp - (mp - mr) * (lam - lambda_p) / max(lambda_r_value - lambda_p, EPS)
                else:
                    mn_value = mcr_value
                return min(mp, max(0.0, mn_value)), lambda_r_value, mcr_value
        else:
            # ABNT NBR 8800:2024, Anexo D, D.2.5.
            mr = mp
            def strength(cb_value):
                return mp, None, None
        field = "moment_y" if axis == "y" else "moment_z"
        demand, combination, owner, governing = 0.0, None, None, None
        combinations = []
        for result in results:
            combo_governing = None
            for member in members:
                samples = list(result.member_results[member.name].get("samples", ()))
                cb_value = _moment_gradient_factor(samples, field) if is_strong else 1.0
                mn_value, lambda_r_value, mcr_value = strength(cb_value)
                capacity_value = mn_value / GAMMA_A1
                member_demand = max((abs(float(sample.get(field, 0.0))) * 100.0
                                     for sample in samples), default=0.0)
                if member_demand < MIN_MOMENT_KN_M * 100.0:
                    continue
                utilization_value = member_demand / max(capacity_value, EPS)
                candidate = (member_demand, member.name, utilization_value,
                             cb_value, mn_value, lambda_r_value, mcr_value)
                if combo_governing is None or utilization_value > combo_governing[2]:
                    combo_governing = candidate
            if combo_governing is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            combo_demand, combo_owner, combo_utilization, cb, mn, lambda_r, mcr = combo_governing
            combo = {"combination": result.load_reference, "member": combo_owner,
                     "applied_kn_cm": combo_demand, "utilization": combo_utilization,
                     "status": "APROVADO" if combo_utilization <= 1.0 else "REPROVADO"}
            combinations.append(combo)
            if governing is None or combo_utilization > governing["utilization"]:
                governing = {**combo, "Cb": cb, "Mn_kn_cm": mn,
                             "lambda_r_flt": lambda_r, "Mcr_kn_cm": mcr}
        if governing is None:
            capacity = strength(1.0)[0] / GAMMA_A1
            return {"status": "not_applicable", "detail": f"nenhuma solicitação de flexão em {axis.upper()}",
                    "parameters": {"MRd_kn_cm": capacity}}
        demand = governing["applied_kn_cm"]
        combination, owner = governing["combination"], governing["member"]
        cb = governing["Cb"]
        mn = governing["Mn_kn_cm"]
        capacity = mn / GAMMA_A1
        lambda_r = governing["lambda_r_flt"]
        mcr = governing["Mcr_kn_cm"]
        calc = {"lambda_flt": lam if is_strong else None,
                "lambda_p_flt": lambda_p if is_strong else None,
                "lambda_r_flt": lambda_r, "Mcr_kn_cm": mcr,
                "Lb_cm": lb if is_strong else None, "Cb": cb if is_strong else None}
        utilization = governing["utilization"]
        return {
            "status": "checked", "detail": "", "utilization": utilization,
            "critical_check": f"Flexão {axis.upper()}", "critical_combination": combination,
            "critical_member": owner, "applied_kn_cm": demand,
            "parameters": {
                "axis": axis.upper(), "strong_axis": is_strong,
                "b_mm": p["b_mm"], "h_mm": p["h_mm"],
                "Ag_cm2": p["Ag_cm2"], "Iy_cm4": iy, "Iz_cm4": iz,
                "Wy_cm3": p["Wy_cm3"], "Wz_cm3": p["Wz_cm3"],
                "Zy_cm3": p["Zy_cm3"], "Zz_cm3": p["Zz_cm3"],
                "ry_cm": p["ry_cm"], "rz_cm": p["rz_cm"],
                "E_kn_cm2": e, "fy_kn_cm2": fy, "Mpl_kn_cm": mp,
                "Mr_kn_cm": mr if is_strong else mp, "Mn_kn_cm": mn,
                "MRd_kn_cm": capacity, "gamma_a1": GAMMA_A1,
                "It_cm4": p["It_cm4"], **calc,
            },
            "combinations": combinations,
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_rectangular_bar_flexion_y(element, model, results, family="Barra Retangular"):
    return _flexion(element, model, results, "y", family)


def verify_rectangular_bar_flexion_z(element, model, results, family="Barra Retangular"):
    return _flexion(element, model, results, "z", family)


def _shear(element, model, results, axis: str, family="Barra Retangular"):
    try:
        members, p, _, _, fy, _ = _base(element, model, results, family)
        field = "shear_y" if axis == "y" else "shear_z"
        demand, combination, owner = 0.0, None, None
        for result in results:
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    value = abs(float(sample.get(field, 0.0)))
                    if value > demand:
                        demand, combination, owner = value, result.load_reference, member.name
        if demand < MIN_SHEAR_KN:
            return {"status": "not_applicable", "detail": f"nenhuma solicitação de cortante em {axis.upper()}",
                    "parameters": {"VRd_kn": 0.0}}
        # Solid rectangular-section elastic shear stress: tau_max = 1.5 V/A.
        # NBR 8800:2024, 5.5.2.3-b), with no thin wall subject to shear buckling.
        area = p["Ag_cm2"]
        tau_allow = 0.60 * fy / GAMMA_A1
        capacity = tau_allow * area / 1.5
        utilization = demand / max(capacity, EPS)
        return {
            "status": "checked", "detail": "", "utilization": utilization,
            "critical_check": f"Cortante {axis.upper()}", "critical_combination": combination,
            "critical_member": owner, "applied_kn": demand,
            "parameters": {"Ag_cm2": area, "tau_max_kn_cm2": 1.5 * demand / area,
                           "tau_Rd_kn_cm2": tau_allow, "VRd_kn": capacity,
                           "gamma_a1": GAMMA_A1, "fy_kn_cm2": fy},
            "combinations": [{"combination": combination, "member": owner,
                              "applied_kn": demand, "utilization": utilization,
                              "status": "APROVADO" if utilization <= 1 else "REPROVADO"}],
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_rectangular_bar_shear_y(element, model, results, family="Barra Retangular"):
    return _shear(element, model, results, "y", family)


def verify_rectangular_bar_shear_z(element, model, results, family="Barra Retangular"):
    return _shear(element, model, results, "z", family)


def _interaction(element, model, results, tension, compression, flex_y, flex_z, mode,
                 family="Barra Retangular"):
    try:
        members, p, _, _, fy, fu = _base(element, model, results, family)
        nt = min(p["Ag_cm2"] * fy / GAMMA_A1, p["Ag_cm2"] * fu / GAMMA_A2)
        nc = (compression.get("parameters") or {}).get("Nc_Rd_kn")
        myr = (flex_y.get("parameters") or {}).get("MRd_kn_cm")
        mzr = (flex_z.get("parameters") or {}).get("MRd_kn_cm")
        required = (myr, mzr) if mode == "oblique" else (
            (nt, myr, mzr) if mode == "tension" else (nc, myr, mzr)
        )
        if any(value is None or value <= 0.0 for value in required):
            raise ValueError("resistências necessárias à interação indisponíveis")
        combinations, critical = [], None
        for result in results:
            governing = None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    raw = float(sample.get("axial", 0.0))
                    n = max(0.0, -raw) if mode == "tension" else max(0.0, raw)
                    my = abs(float(sample.get("moment_y", 0.0))) * 100.0
                    mz = abs(float(sample.get("moment_z", 0.0))) * 100.0
                    if n < MIN_FORCE_KN and my < MIN_MOMENT_KN_M * 100 and mz < MIN_MOMENT_KN_M * 100:
                        continue
                    rn = n / (nt if mode == "tension" else nc) if mode != "oblique" else 0.0
                    ry, rz = my / myr, mz / mzr
                    ratio = ry + rz if mode == "oblique" else (
                        rn + 8.0 / 9.0 * (ry + rz) if rn >= 0.2 else rn / 2.0 + ry + rz
                    )
                    if governing is None or ratio > governing[4]:
                        governing = (n, my, mz, member.name, ratio, rn, ry, rz)
            if governing is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            n, my, mz, owner, ratio, rn, ry, rz = governing
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn": n, "applied_my_kn_cm": my, "applied_mz_kn_cm": mz,
                    "utilization": ratio, "axial_ratio": rn,
                    "moment_y_ratio": ry, "moment_z_ratio": rz,
                    "status": "APROVADO" if ratio <= 1.0 else "REPROVADO"}
            combinations.append(item)
            if critical is None or ratio > critical["utilization"]:
                critical = item
        return {
            "status": "checked" if critical else "not_applicable",
            "detail": "" if critical else "nenhum esforço combinado aplicável",
            "utilization": critical["utilization"] if critical else None,
            "critical_check": {"oblique": "Flexão oblíqua", "tension": "Flexotração",
                               "compression": "Flexocompressão"}[mode],
            "critical_combination": critical["combination"] if critical else "N/A",
            "critical_member": critical["member"] if critical else None,
            "applied_kn": critical.get("applied_kn") if critical else None,
            "applied_my_kn_cm": critical.get("applied_my_kn_cm") if critical else None,
            "applied_mz_kn_cm": critical.get("applied_mz_kn_cm") if critical else None,
            "parameters": {"Nt_Rd_kn": nt, "Nc_Rd_kn": nc,
                           "My_Rd_kn_cm": myr, "Mz_Rd_kn_cm": mzr},
            "combinations": combinations,
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_rectangular_bar_oblique(element, model, results, flex_y, flex_z,
                                   family="Barra Retangular"):
    return _interaction(element, model, results, {}, {}, flex_y, flex_z, "oblique", family)


def verify_rectangular_bar_flexotension(element, model, results, tension, flex_y, flex_z,
                                        family="Barra Retangular"):
    return _interaction(element, model, results, tension, {}, flex_y, flex_z, "tension", family)


def verify_rectangular_bar_flexocompression(element, model, results, compression, flex_y, flex_z,
                                            family="Barra Retangular"):
    return _interaction(element, model, results, {}, compression, flex_y, flex_z,
                         "compression", family)
