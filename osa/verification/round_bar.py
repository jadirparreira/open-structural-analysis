"""NBR 8800:2024 checks for solid circular steel bars."""

from __future__ import annotations

from math import pi, sqrt

from osa.verification.calculation_properties import calculation_property
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
        diameter = float(geometry.get("d", geometry.get("d_mm")))
    except (TypeError, ValueError) as error:
        raise ValueError("diâmetro da barra circular não foi definido") from error
    if diameter <= 0.0:
        raise ValueError("diâmetro da barra circular deve ser positivo")
    area = pi * diameter**2 / 4.0
    inertia = pi * diameter**4 / 64.0
    polar = 2.0 * inertia
    elastic_modulus = inertia / (diameter / 2.0)
    plastic_modulus = diameter**3 / 6.0
    return {
        "d_mm": diameter,
        "Ag_cm2": area / 100.0,
        "Iy_cm4": inertia / 10_000.0,
        "Iz_cm4": inertia / 10_000.0,
        "It_cm4": polar / 10_000.0,
        "Wy_cm3": elastic_modulus / 1_000.0,
        "Wz_cm3": elastic_modulus / 1_000.0,
        "Zy_cm3": plastic_modulus / 1_000.0,
        "Zz_cm3": plastic_modulus / 1_000.0,
        "ry_cm": diameter / 40.0,
        "rz_cm": diameter / 40.0,
        "r0_cm": diameter / (20.0 * sqrt(2.0)),
    }


def _members(element, model):
    members = [model.bars.get(name) for name in element.member_names]
    if not members or any(member is None for member in members):
        raise ValueError("barra não encontrada no modelo")
    if any(member.section != "Barra Circular" for member in members):
        raise ValueError("a rotina atende apenas à seção Barra Circular")
    if any(not member.section_geometry for member in members):
        raise ValueError("geometria da seção incompleta")
    if len({(m.profile, m.section_geometry, m.material) for m in members}) != 1:
        raise ValueError("grupo com seções ou materiais diferentes")
    return members


def _base(element, model, results):
    members = _members(element, model)
    if not results or any(member.name not in result.member_results
                          for result in results for member in members):
        raise ValueError("resultados de análise indisponíveis")
    material = model.materials.get(members[0].material, ())
    if len(material) < 6:
        raise ValueError("propriedades do material não definidas")
    e, g, fy, fu = (float(material[i]) / 10_000.0 for i in (0, 1, 4, 5))
    if min(e, g, fy, fu) <= 0.0:
        raise ValueError("propriedades do material inválidas")
    return members, _section(members[0]), e, g, fy, fu


def _axial_result(results, members, compression: bool, capacity: float):
    sign = 1.0 if compression else -1.0
    combinations, critical = [], None
    for result in results:
        demand, owner = 0.0, None
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                value = float(sample.get("axial", 0.0)) * sign
                if value > demand:
                    demand, owner = value, member.name
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


def verify_round_bar_tension(element, model, results):
    try:
        members, p, _, _, fy, fu = _base(element, model, results)
        gross = p["Ag_cm2"] * fy / GAMMA_A1
        ct = calculation_property(model, element, "Ct", 1.0)
        ae = p["Ag_cm2"] * ct
        rupture = ae * fu / GAMMA_A2
        capacity = min(gross, rupture)
        out = _axial_result(results, members, False, capacity)
        out["parameters"] = {
            "Ag_cm2": p["Ag_cm2"], "An_cm2": p["Ag_cm2"], "Ae_cm2": ae,
            "Ct": ct, "fy_kn_cm2": fy, "fu_kn_cm2": fu,
            "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
            "Nt_Rd1_kn": gross, "Nt_Rd2_kn": rupture, "Nt_Rd_kn": capacity,
            "d_mm": p["d_mm"],
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_round_bar_compression(element, model, results):
    try:
        members, p, e, g, fy, _ = _base(element, model, results)
        lengths = restraint_lengths(model, element, results,
                                    {"Iy": p["Iy_cm4"], "tw": p["d_mm"] / 10.0})
        ly, lz = (lengths.lengths_m[key] * 100.0 for key in ("Ly", "Lz"))
        if min(ly, lz) <= 0.0:
            raise ValueError("comprimentos destravados inválidos")
        area = p["Ag_cm2"]
        inertia = p["Iy_cm4"]
        ney = pi**2 * e * inertia / ly**2
        nez = pi**2 * e * inertia / lz**2
        r0_sq = p["r0_cm"] ** 2
        net = g * p["It_cm4"] / r0_sq
        ne = min(ney, nez, net)
        lambda0 = sqrt(area * fy / ne)
        chi = 0.658 ** (lambda0**2) if lambda0 <= 1.5 else 0.877 / lambda0**2
        capacity = chi * area * fy / GAMMA_A1
        out = _axial_result(results, members, True, capacity)
        out["parameters"] = {
            "d_mm": p["d_mm"], "Ag_cm2": area, "Aef_cm2": area,
            "Iy_cm4": inertia, "Iz_cm4": inertia, "It_cm4": p["It_cm4"],
            "r0_cm": p["r0_cm"], "E_kn_cm2": e, "G_kn_cm2": g,
            "fy_kn_cm2": fy, "Ly_cm": ly, "Lz_cm": lz,
            "Ney_kn": ney, "Nez_kn": nez, "Net_kn": net, "Ne_kn": ne,
            "lambda0": lambda0, "chi": chi, "gamma_a1": GAMMA_A1,
            "Nc_Rd_kn": capacity,
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _flexion(element, model, results, axis: str):
    try:
        members, p, _, _, fy, _ = _base(element, model, results)
        # NBR 8800:2024, Annex D, D.2.5; 5.4.2.2 caps elastic analysis.
        mp = p["Zy_cm3"] * fy
        cap_analysis = 1.50 * p["Wy_cm3"] * fy
        capacity = min(mp, cap_analysis) / GAMMA_A1
        field = "moment_y" if axis == "y" else "moment_z"
        governing = None
        combinations = []
        for result in results:
            candidate = None
            for member in members:
                demand = max((abs(float(sample.get(field, 0.0))) * 100.0
                              for sample in result.member_results[member.name].get("samples", ())),
                             default=0.0)
                if demand < MIN_MOMENT_KN_M * 100.0:
                    continue
                utilization = demand / max(capacity, EPS)
                if candidate is None or utilization > candidate[2]:
                    candidate = (demand, member.name, utilization)
            if candidate is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            demand, owner, utilization = candidate
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn_cm": demand, "utilization": utilization,
                    "status": "APROVADO" if utilization <= 1.0 else "REPROVADO"}
            combinations.append(item)
            if governing is None or utilization > governing["utilization"]:
                governing = item
        p_out = {
            "axis": axis.upper(), "d_mm": p["d_mm"], "Ag_cm2": p["Ag_cm2"],
            "Wy_cm3": p["Wy_cm3"], "Wz_cm3": p["Wz_cm3"],
            "Zy_cm3": p["Zy_cm3"], "Zz_cm3": p["Zz_cm3"],
            "fy_kn_cm2": fy, "Mpl_kn_cm": mp, "Mcap_kn_cm": cap_analysis,
            "Mn_kn_cm": min(mp, cap_analysis), "MRd_kn_cm": capacity,
            "gamma_a1": GAMMA_A1,
        }
        if governing is None:
            return {"status": "not_applicable", "detail": f"nenhuma solicitação de flexão em {axis.upper()}",
                    "parameters": p_out}
        return {
            "status": "checked", "detail": "", "utilization": governing["utilization"],
            "critical_check": f"Flexão {axis.upper()}",
            "critical_combination": governing["combination"],
            "critical_member": governing["member"],
            "applied_kn_cm": governing["applied_kn_cm"],
            "parameters": p_out, "combinations": combinations,
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_round_bar_flexion_y(element, model, results):
    return _flexion(element, model, results, "y")


def verify_round_bar_flexion_z(element, model, results):
    return _flexion(element, model, results, "z")


def _shear(element, model, results, axis: str):
    try:
        members, p, _, _, fy, _ = _base(element, model, results)
        capacity = 0.60 * fy / GAMMA_A1 * p["Ag_cm2"] / (4.0 / 3.0)
        governing = None
        combinations = []
        for result in results:
            candidate = None
            for member in members:
                samples = result.member_results[member.name].get("samples", ())
                # A circular bar has equal shear resistance about both axes.
                # Use the vector resultant so concurrent Vy and Vz are captured.
                demand = max((sqrt(float(sample.get("shear_y", 0.0)) ** 2
                                   + float(sample.get("shear_z", 0.0)) ** 2)
                              for sample in samples), default=0.0)
                if demand < MIN_SHEAR_KN:
                    continue
                utilization = demand / max(capacity, EPS)
                if candidate is None or utilization > candidate[2]:
                    candidate = (demand, member.name, utilization)
            if candidate is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            demand, owner, utilization = candidate
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn": demand, "utilization": utilization,
                    "status": "APROVADO" if utilization <= 1.0 else "REPROVADO"}
            combinations.append(item)
            if governing is None or utilization > governing["utilization"]:
                governing = item
        p_out = {
            "axis": axis.upper(), "d_mm": p["d_mm"], "Ag_cm2": p["Ag_cm2"],
            "fy_kn_cm2": fy, "tau_max_kn_cm2": None,
            "tau_Rd_kn_cm2": 0.60 * fy / GAMMA_A1,
            "VRd_kn": 0.60 * fy / GAMMA_A1 * p["Ag_cm2"] / (4.0 / 3.0),
            "gamma_a1": GAMMA_A1,
        }
        if governing is None:
            return {"status": "not_applicable", "detail": f"nenhuma solicitação de cortante em {axis.upper()}",
                    "parameters": p_out}
        p_out["tau_max_kn_cm2"] = (4.0 / 3.0) * governing["applied_kn"] / p["Ag_cm2"]
        return {
            "status": "checked", "detail": "", "utilization": governing["utilization"],
            "critical_check": f"Cortante {axis.upper()}",
            "critical_combination": governing["combination"],
            "critical_member": governing["member"], "applied_kn": governing["applied_kn"],
            "parameters": p_out, "combinations": combinations,
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_round_bar_shear_y(element, model, results):
    return _shear(element, model, results, "y")


def verify_round_bar_shear_z(element, model, results):
    return _shear(element, model, results, "z")


def _interaction(element, model, results, tension, compression, flex_y, flex_z, mode):
    try:
        members, p, _, _, fy, fu = _base(element, model, results)
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
            candidate = None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    raw = float(sample.get("axial", 0.0))
                    n = max(0.0, -raw) if mode == "tension" else max(0.0, raw)
                    my = abs(float(sample.get("moment_y", 0.0))) * 100.0
                    mz = abs(float(sample.get("moment_z", 0.0))) * 100.0
                    if (n < MIN_FORCE_KN and my < MIN_MOMENT_KN_M * 100.0
                            and mz < MIN_MOMENT_KN_M * 100.0):
                        continue
                    rn = n / (nt if mode == "tension" else nc) if mode != "oblique" else 0.0
                    ry, rz = my / myr, mz / mzr
                    ratio = ry + rz if mode == "oblique" else (
                        rn + 8.0 / 9.0 * (ry + rz) if rn >= 0.2 else rn / 2.0 + ry + rz
                    )
                    item = (n, my, mz, member.name, ratio, rn, ry, rz)
                    if candidate is None or ratio > candidate[4]:
                        candidate = item
            if candidate is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            n, my, mz, owner, ratio, rn, ry, rz = candidate
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


def verify_round_bar_oblique(element, model, results, flex_y, flex_z):
    return _interaction(element, model, results, {}, {}, flex_y, flex_z, "oblique")


def verify_round_bar_flexotension(element, model, results, tension, flex_y, flex_z):
    return _interaction(element, model, results, tension, {}, flex_y, flex_z, "tension")


def verify_round_bar_flexocompression(element, model, results, compression, flex_y, flex_z):
    return _interaction(element, model, results, {}, compression, flex_y, flex_z, "compression")
