"""Resistance checks for rolled T sections."""

from __future__ import annotations

from math import pi, sqrt

from osa.verification.restraints import restraint_lengths

GAMMA_A1 = 1.10
GAMMA_A2 = 1.35
EPS = 1e-9
MIN_TENSION_KN = 0.001
MIN_COMPRESSION_KN = 0.001
MIN_BENDING_KN_M = 0.001
MIN_SHEAR_KN = 0.001


def _section(member) -> dict[str, float]:
    """Return T-section properties from its four catalog dimensions."""
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        value = geometry.get(name, geometry.get(f"{name}_mm"))
        if value is None:
            raise ValueError(f"dimensão '{name}' ausente na seção")
        return float(value)

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    if min(d, bf, tw, tf) <= 0.0 or d <= tf or bf <= tw:
        raise ValueError("geometria T inválida")

    flange_area = bf * tf
    web_area = tw * (d - tf)
    area = flange_area + web_area
    zc = (flange_area * tf / 2.0 + web_area * (d + tf) / 2.0) / area
    iy = (
        bf * tf**3 / 12.0 + flange_area * (tf / 2.0 - zc)**2
        + tw * (d - tf)**3 / 12.0 + web_area * ((d + tf) / 2.0 - zc)**2
    )
    iz = tf * bf**3 / 12.0 + (d - tf) * tw**3 / 12.0
    j = (bf * tf**3 + (d - tf) * tw**3) / 3.0
    # The shear center of the idealized thin-walled T is at the flange/web
    # junction. Its warping constant is zero for this three-branch model.
    x0 = abs(zc - tf / 2.0)
    r0_sq = iy / area + iz / area + x0**2
    wy = iy / max(zc, d - zc)
    wz = iz / (bf / 2.0)
    zy = _plastic_modulus_y(d, bf, tw, tf)
    zz = tf * bf**2 / 4.0 + (d - tf) * tw**2 / 4.0
    return {
        "d_mm": d, "bf_mm": bf, "tw_mm": tw, "tf_mm": tf,
        "Ag_cm2": area / 100.0, "zc_mm": zc,
        "Iy_cm4": iy / 1e4, "Iz_cm4": iz / 1e4,
        "Wy_cm3": wy / 1e3, "Wz_cm3": wz / 1e3,
        "Zy_cm3": zy / 1e3, "Zz_cm3": zz / 1e3,
        "ry_cm": sqrt(iy / area) / 10.0,
        "rz_cm": sqrt(iz / area) / 10.0,
        "It_cm4": j / 1e4, "Cw_cm6": 0.0,
        "x0_cm": x0 / 10.0, "r0_cm": sqrt(r0_sq) / 10.0,
    }


def _plastic_modulus_y(d: float, bf: float, tw: float, tf: float) -> float:
    """Plastic modulus about the horizontal centroidal axis, in mm³."""
    aa, aw = bf * tf, tw * (d - tf)
    total = aa + aw
    lo, hi = 0.0, d
    for _ in range(64):
        cut = (lo + hi) / 2.0
        area_below = bf * max(0.0, min(tf, cut)) + tw * max(0.0, cut - tf)
        if area_below < total / 2.0:
            lo = cut
        else:
            hi = cut
    pna = (lo + hi) / 2.0

    def first_moment(rect_lo: float, rect_hi: float, width: float) -> float:
        if pna <= rect_lo:
            return width * (rect_hi - rect_lo) * ((rect_lo + rect_hi) / 2.0 - pna)
        if pna >= rect_hi:
            return width * (rect_hi - rect_lo) * (pna - (rect_lo + rect_hi) / 2.0)
        lower = width * (pna - rect_lo) * (pna - rect_lo) / 2.0
        upper = width * (rect_hi - pna) * (rect_hi - pna) / 2.0
        return lower + upper

    return first_moment(0.0, tf, bf) + first_moment(tf, d, tw)


def _members(element, model):
    members = [model.bars.get(name) for name in element.member_names]
    if not members or any(member is None for member in members):
        raise ValueError("barra não encontrada no modelo")
    if any(member.section != "T Laminado" for member in members):
        raise ValueError("a rotina atende apenas perfis T laminados")
    if any(not member.section_geometry for member in members):
        raise ValueError("geometria da seção incompleta")
    if len({(m.profile, m.section_geometry, m.material) for m in members}) != 1:
        raise ValueError("grupo com seções ou materiais diferentes")
    return members


def _base(element, model, results):
    members = _members(element, model)
    if not results or any(
        member.name not in result.member_results
        for result in results for member in members
    ):
        raise ValueError("resultados de análise indisponíveis")
    values = model.materials.get(members[0].material, ())
    if len(values) < 6:
        raise ValueError("propriedades do material não definidas")
    e, g, fy, fu = (float(values[i]) / 10000.0 for i in (0, 1, 4, 5))
    if min(e, g, fy, fu) <= 0.0:
        raise ValueError("propriedades do material inválidas")
    return members, _section(members[0]), e, g, fy, fu


def _samples(results, members):
    for result in results:
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                yield result, member.name, sample


def _result(name: str, results, members, field: str, capacity: float,
            scale: float = 1.0, threshold: float = 0.0):
    combinations, critical = [], None
    for load_result in results:
        demand, owner = 0.0, None
        for member in members:
            for sample in load_result.member_results[member.name].get("samples", ()):
                value = abs(float(sample.get(field, 0.0))) * scale
                if value > demand:
                    demand, owner = value, member.name
        if demand < threshold:
            combinations.append({"combination": load_result.load_reference, "member": None,
                                 "applied": 0.0, "utilization": 0.0, "status": "N/A"})
            continue
        utilization = demand / capacity if capacity > EPS else float("inf")
        item = {"combination": load_result.load_reference, "member": owner,
                "applied": demand, "utilization": utilization,
                "status": "APROVADO" if utilization <= 1.0 else "REPROVADO"}
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou solicitação neste modo",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": name,
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied"] if critical else None,
        "applied_kn_cm": critical["applied"] if critical and field.startswith("moment") else None,
        "parameters": {}, "combinations": combinations,
    }


def verify_t_tension(element, model, results):
    try:
        members, p, _, _, fy, fu = _base(element, model, results)
        n_yield = p["Ag_cm2"] * fy / GAMMA_A1
        n_rupture = p["Ag_cm2"] * fu / GAMMA_A2
        cap = min(n_yield, n_rupture)
        out = _result("Tração axial", results, members, "axial", cap,
                      threshold=MIN_TENSION_KN)
        combinations, critical = [], None
        for result in results:
            demand, owner = 0.0, None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    value = max(0.0, -float(sample.get("axial", 0.0)))
                    if value > demand:
                        demand, owner = value, member.name
            if demand < MIN_TENSION_KN:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "applied_kn": 0.0, "utilization": 0.0, "status": "N/A"})
                continue
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn": demand, "utilization": demand / cap,
                    "status": "APROVADO" if demand <= cap else "REPROVADO"}
            combinations.append(item)
            if critical is None or item["utilization"] > critical["utilization"]:
                critical = item
        out.update({
            "status": "checked" if critical else "not_applicable",
            "detail": "" if critical else "nenhuma combinação apresentou tração axial",
            "utilization": critical["utilization"] if critical else None,
            "critical_combination": critical["combination"] if critical else "N/A",
            "critical_member": critical["member"] if critical else None,
            "applied_kn": critical["applied_kn"] if critical else None,
            "combinations": combinations,
            "parameters": {
                "Ag_cm2": p["Ag_cm2"], "An_cm2": p["Ag_cm2"],
                "Ae_cm2": p["Ag_cm2"], "Ct": 1.0,
                "fy_kn_cm2": fy, "fu_kn_cm2": fu,
                "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
                "Nt_Rd1_kn": n_yield, "Nt_Rd2_kn": n_rupture, "Nt_Rd_kn": cap,
            },
        })
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_t_compression(element, model, results):
    try:
        members, p, e, g, fy, _ = _base(element, model, results)
        lengths = restraint_lengths(
            model, element, results, {"Iy": p["Iz_cm4"], "tw": p["tw_mm"] / 10.0},
        )
        ly, lz, lt = (lengths.lengths_m[key] * 100.0 for key in ("Ly", "Lz", "Lt"))
        if min(ly, lz, lt) <= 0.0:
            raise ValueError("comprimentos destravados inválidos")
        area, iy, iz, it = p["Ag_cm2"], p["Iy_cm4"], p["Iz_cm4"], p["It_cm4"]
        x0, r0 = p["x0_cm"], p["r0_cm"]
        ney = pi**2 * e * iy / ly**2
        nez = pi**2 * e * iz / lz**2
        net = g * it / r0**2
        h = 1.0 - x0**2 / r0**2
        radical = max(0.0, 1.0 - 4.0 * nez * net * h / (nez + net)**2)
        ne_flexotorsion = (nez + net) / (2.0 * h) * (1.0 - sqrt(radical))
        ne = min(ney, ne_flexotorsion)
        lambda0 = sqrt(area * fy / ne)
        chi = 0.658**(lambda0**2) if lambda0 <= 1.5 else 0.877 / lambda0**2

        b_flange = (p["bf_mm"] - p["tw_mm"]) / 2.0
        lambda_flange_limit = 0.56 * sqrt(e / fy)
        lambda_web_limit = 0.75 * sqrt(e / fy)
        flange_eff = _effective_width(b_flange, p["tf_mm"], lambda_flange_limit, chi, fy)
        web_width = p["d_mm"] - p["tf_mm"]
        web_eff = _effective_width(web_width, p["tw_mm"], lambda_web_limit, chi, fy)
        effective_area = area - (
            2.0 * (b_flange - flange_eff) * p["tf_mm"]
            + (web_width - web_eff) * p["tw_mm"]
        ) / 100.0
        effective_area = max(0.0, min(area, effective_area))
        cap = chi * effective_area * fy / GAMMA_A1
        out = _result("Compressão axial", results, members, "axial", cap,
                      threshold=MIN_COMPRESSION_KN)
        combinations, critical = [], None
        for result in results:
            demand, owner = 0.0, None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    value = max(0.0, float(sample.get("axial", 0.0)))
                    if value > demand:
                        demand, owner = value, member.name
            if demand < MIN_COMPRESSION_KN:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "applied_kn": 0.0, "utilization": 0.0, "status": "N/A"})
                continue
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn": demand, "utilization": demand / cap,
                    "status": "APROVADO" if demand <= cap else "REPROVADO"}
            combinations.append(item)
            if critical is None or item["utilization"] > critical["utilization"]:
                critical = item
        out.update({
            "status": "checked" if critical else "not_applicable",
            "detail": "" if critical else "nenhuma combinação apresentou compressão axial",
            "utilization": critical["utilization"] if critical else None,
            "critical_combination": critical["combination"] if critical else "N/A",
            "critical_member": critical["member"] if critical else None,
            "applied_kn": critical["applied_kn"] if critical else None,
            "combinations": combinations,
            "parameters": {
                **lengths.memory(), "Ly_cm": ly, "Lz_cm": lz, "Lt_cm": lt,
                "Ag_cm2": area, "Aef_cm2": effective_area,
                "Iy_cm4": iy, "Iz_cm4": iz, "It_cm4": it, "Cw_cm6": 0.0,
                "x0_cm": x0, "r0_cm": r0, "E_kn_cm2": e, "G_kn_cm2": g,
                "fy_kn_cm2": fy, "H_flexotorsion": h,
                "Ney_kn": ney, "Nez_kn": nez, "Net_kn": net,
                "Ne_flexotorsao_kn": ne_flexotorsion, "Ne_kn": ne,
                "lambda0": lambda0, "chi": chi, "Nc_Rd_kn": cap,
                "flange_width_mm": b_flange, "flange_effective_mm": flange_eff,
                "flange_slenderness": b_flange / p["tf_mm"],
                "flange_limit": lambda_flange_limit,
                "web_width_mm": web_width, "web_effective_mm": web_eff,
                "web_slenderness": web_width / p["tw_mm"],
                "web_limit": lambda_web_limit,
                "gamma_a1": GAMMA_A1,
            },
        })
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _effective_width(width, thickness, limit, chi, fy):
    slenderness = width / thickness
    reduced = limit / sqrt(max(chi, 1e-12))
    if slenderness <= reduced:
        return width
    sigma_el = (1.49 * limit / slenderness) ** 2 * fy
    ratio = sigma_el / (chi * fy)
    effective = width * max(0.0, 1.0 - 0.22 * sqrt(ratio)) * sqrt(ratio)
    return min(width, effective)


def verify_t_flexion_y(element, model, results):
    """Bending perpendicular to the web, per NBR 8800:2024 D.2.3."""
    try:
        members, p, e, _, fy, _ = _base(element, model, results)
        lengths = restraint_lengths(
            model, element, results, {"Iy": p["Iz_cm4"], "tw": p["tw_mm"] / 10.0},
        )
        lb = lengths.lengths_m["Lb"] * 100.0
        if lb <= 0.0:
            raise ValueError("comprimento destravado à flexão inválido")
        d, tw, bf, tf = p["d_mm"] / 10.0, p["tw_mm"] / 10.0, p["bf_mm"] / 10.0, p["tf_mm"] / 10.0
        iy, iz, j = p["Iy_cm4"], p["Iz_cm4"], p["It_cm4"]
        wy, zy = p["Wy_cm3"], p["Zy_cm3"]
        mpl = zy * fy
        sigma_r = 0.30 * fy

        # Local buckling of the free web end, applicable when it is compressed.
        lam_fla = p["d_mm"] / p["tw_mm"]
        lp_fla, lr_fla = 0.84 * sqrt(e / fy), 1.52 * sqrt(e / fy)
        if lam_fla <= lp_fla:
            m_fla = wy * fy / GAMMA_A1
        elif lam_fla <= lr_fla:
            m_fla = (1.43 - 0.515 * lam_fla * sqrt(fy / e)) * wy * fy / GAMMA_A1
        else:
            m_fla = 1.52 * e * wy / lam_fla**2 / GAMMA_A1

        # Local buckling of the compressed flange, per D.2.3 and D.2.8-e/f.
        lam_flm = p["bf_mm"] / (2.0 * p["tf_mm"])
        lp_flm = 0.38 * sqrt(e / fy)
        lr_flm = 0.83 * sqrt(e / max(fy - sigma_r, EPS))
        wxc = wy
        wxt = wy
        mr_flm = min((fy - sigma_r) * wxc, fy * wxt)
        mcr_flm = 0.69 * e * wxc / lam_flm**2
        m_flm = _local_buckling_capacity(lam_flm, lp_flm, lr_flm, mpl, mr_flm, mcr_flm)

        # Lateral-torsional buckling, treating both signs of bending. The smaller
        # capacity governs so that the result does not depend on solver sign.
        # The monosymmetric T FLT expression uses the radius/inertia about
        # the symmetry axis, which is the weak (z) axis in OSA's section data.
        r_lat = p["rz_cm"]
        lam_flt = lb / r_lat
        lp_flt = 1.76 * sqrt(e / fy)
        lr_flt = (
            1.95 * e / (r_lat * fy)
            * sqrt(iz * j) / wy
            * sqrt(2.36 * fy * d * wy / (e * j) + 1.0)
        )
        b_flt = 2.3 * d / lb * sqrt(iz / j)
        mcr_tension = 1.95 * e / lb * sqrt(iz * j) * (b_flt + sqrt(1.0 + b_flt**2))
        mcr_compression = 1.95 * e / lb * sqrt(iz * j) * (-b_flt + sqrt(1.0 + b_flt**2))
        mr_flt = fy * wy
        m_flt_tension = _local_buckling_capacity(
            lam_flt, lp_flt, lr_flt, mpl, mr_flt, mcr_tension,
        )
        m_flt_compression = min(mcr_compression / GAMMA_A1, fy * wy / GAMMA_A1)
        cap_compression = min(m_fla, m_flt_compression)
        cap_tension = min(m_flm, m_flt_tension)
        combinations, critical = [], None
        for load_result in results:
            governing = None
            for member in members:
                for sample in load_result.member_results[member.name].get("samples", ()):
                    moment = float(sample.get("moment_y", 0.0))
                    demand = abs(moment) * 100.0
                    if demand < MIN_BENDING_KN_M * 100.0:
                        continue
                    capacity = cap_tension if moment >= 0.0 else cap_compression
                    item = {
                        "combination": load_result.load_reference, "member": member.name,
                        "position_m": sample.get("x"), "applied_kn_cm": demand,
                        "bending_sign": "web_end_tension" if moment >= 0.0 else "web_end_compression",
                        "MRd_kn_cm": capacity, "utilization": demand / max(capacity, EPS),
                        "status": "APROVADO" if demand <= capacity else "REPROVADO",
                    }
                    if governing is None or item["utilization"] > governing["utilization"]:
                        governing = item
            if governing is None:
                combinations.append({"combination": load_result.load_reference,
                                     "member": None, "applied_kn_cm": 0.0,
                                     "utilization": 0.0, "status": "N/A"})
            else:
                combinations.append(governing)
                if critical is None or governing["utilization"] > critical["utilization"]:
                    critical = governing
        cap = critical["MRd_kn_cm"] if critical else min(cap_compression, cap_tension)
        out = {
            "status": "checked" if critical else "not_applicable",
            "detail": "" if critical else "nenhuma combinação apresentou flexão em Y",
            "utilization": critical["utilization"] if critical else None,
            "critical_check": "Flexão Y",
            "critical_combination": critical["combination"] if critical else "N/A",
            "critical_member": critical["member"] if critical else None,
            "applied_kn_cm": critical["applied_kn_cm"] if critical else None,
            "parameters": {}, "combinations": combinations,
        }
        out["parameters"] = {
            **lengths.memory(), "Lb_cm": lb, "d_mm": p["d_mm"],
            "bf_mm": p["bf_mm"], "tw_mm": p["tw_mm"], "tf_mm": p["tf_mm"],
            "E_kn_cm2": e, "fy_kn_cm2": fy, "gamma_a1": GAMMA_A1,
            "Ag_cm2": p["Ag_cm2"], "Iy_cm4": iy, "Iz_cm4": iz,
            "It_cm4": j, "Wy_cm3": wy, "Zy_cm3": zy,
            "Mn_kn_cm": cap * GAMMA_A1, "MRd_kn_cm": cap,
            "Mpl_kn_cm": mpl, "sigma_r_kn_cm2": sigma_r,
            "lambda_fla": lam_fla, "lambda_p_fla": lp_fla,
            "lambda_r_fla": lr_fla, "Mrd_fla_kn_cm": m_fla,
            "lambda_flm": lam_flm, "lambda_p_flm": lp_flm,
            "lambda_r_flm": lr_flm, "Mr_flm_kn_cm": mr_flm,
            "Mcr_flm_kn_cm": mcr_flm, "Mrd_flm_kn_cm": m_flm,
            "lambda_flt": lam_flt, "lambda_p_flt": lp_flt,
            "lambda_r_flt": lr_flt, "B_flt": b_flt,
            "Mcr_flt_tension_kn_cm": mcr_tension,
            "Mcr_flt_compression_kn_cm": mcr_compression,
            "Mrd_flt_tension_kn_cm": m_flt_tension,
            "Mrd_flt_compression_kn_cm": m_flt_compression,
            "MRd_compression_kn_cm": cap_compression,
            "MRd_tension_kn_cm": cap_tension,
            "bending_sign": critical["bending_sign"] if critical else "both_signs",
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _local_buckling_capacity(lam, lp, lr, mpl, mr, mcr):
    if lam <= lp:
        return mpl / GAMMA_A1
    if lam <= lr and lr > lp:
        return (mpl - (mpl - mr) * (lam - lp) / (lr - lp)) / GAMMA_A1
    return max(0.0, mcr / GAMMA_A1)


def verify_t_flexion_z(element, model, results):
    """Check the second-axis flange-buckling resistance used by the T reference."""
    try:
        members, p, e, _, fy, _ = _base(element, model, results)
        lam = p["bf_mm"] / p["tf_mm"]
        sigma_r = 0.30 * fy
        lp = 0.38 * sqrt(e / fy)
        lr = 0.83 * sqrt(e / max(fy - sigma_r, EPS))
        mpl = p["Zz_cm3"] * fy
        w_comp = p["Wz_cm3"]
        mr = min((fy - sigma_r) * w_comp, fy * w_comp)
        mcr = 0.69 * e * w_comp / lam**2
        cap = _local_buckling_capacity(lam, lp, lr, mpl, mr, mcr)
        out = _result("Flexão Z", results, members, "moment_z", cap, 100.0,
                      threshold=MIN_BENDING_KN_M * 100.0)
        out["applied_kn_cm"] = out.pop("applied_kn", None)
        out["parameters"] = {
            "Ag_cm2": p["Ag_cm2"], "bf_mm": p["bf_mm"], "tf_mm": p["tf_mm"],
            "lambda_flm": lam, "lambda_p_flm": lp, "lambda_r_flm": lr,
            "sigma_r_kn_cm2": sigma_r, "fy_kn_cm2": fy, "E_kn_cm2": e,
            "gamma_a1": GAMMA_A1, "Zz_cm3": p["Zz_cm3"],
            "Wzc_cm3": w_comp, "Mpl_kn_cm": mpl, "Mr_kn_cm": mr,
            "Mcr_kn_cm": mcr, "MRd_kn_cm": cap,
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _shear(element, model, results, axis):
    try:
        members, p, e, _, fy, _ = _base(element, model, results)
        field = "shear_y" if axis == "y" else "shear_z"
        demand = max((
            abs(float(sample.get(field, 0.0)))
            for _, _, sample in _samples(results, members)
        ), default=0.0)
        if demand < MIN_SHEAR_KN:
            return {"status": "not_applicable", "detail": f"nenhuma solicitação em {axis.upper()}",
                    "parameters": {"VRd_kn": 0.0}}
        if axis == "z":
            # Flange shear plate model used by the supplied T-section reference.
            lam = p["bf_mm"] / p["tf_mm"]
            kv = 5.0
            aw = (p["bf_mm"] - p["tw_mm"]) * p["tf_mm"] / 100.0
        else:
            lam = (p["d_mm"] - p["tf_mm"]) / p["tw_mm"]
            kv = 1.2
            aw = 2.0 * p["d_mm"] * p["tw_mm"] / 100.0
        lp = 1.10 * sqrt(kv * e / fy)
        lr = 1.37 * sqrt(kv * e / fy)
        vpl = 0.60 * aw * fy
        if lam <= lp:
            vn = vpl
        elif lam <= lr:
            vn = lp / lam * vpl
        else:
            vn = 1.24 * (lp / lam)**2 * vpl
        cap = vn / GAMMA_A1
        scope_fail = axis == "y" and lam > 260.0
        effective_cap = cap if not scope_fail else min(cap, demand / (1.0 + 1e-9))
        out = _result(f"Cortante {axis.upper()}", results, members, field, effective_cap,
                      threshold=MIN_SHEAR_KN)
        out["parameters"] = {
            "d_mm": p["d_mm"], "tw_mm": p["tw_mm"], "lambda": lam,
            "kv": kv, "lambda_p": lp, "lambda_r": lr,
            "Aw_cm2": aw, "Vp_kn": vpl, "Vn_kn": vn,
            "VRd_kn": effective_cap, "VRd_calculated_kn": cap,
            "gamma_a1": GAMMA_A1, "fy_kn_cm2": fy, "E_kn_cm2": e,
            "scope_rejected": scope_fail,
        }
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _unsupported_shear_result(results, members, p, axis):
    combinations, critical = [], None
    for result in results:
        demand, owner = 0.0, None
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                value = abs(float(sample.get("shear_z", 0.0)))
                if value > demand:
                    demand, owner = value, member.name
        if demand < MIN_SHEAR_KN:
            continue
        item = {"combination": result.load_reference, "member": owner,
                "applied_kn": demand, "utilization": float("inf"), "status": "REPROVADO"}
        combinations.append(item)
        if critical is None or demand > critical["applied_kn"]:
            critical = item
    return {
        "status": "checked", "detail": "", "utilization": float("inf"),
        "critical_check": f"Cortante {axis.upper()}",
        "critical_combination": critical["combination"],
        "critical_member": critical["member"], "applied_kn": critical["applied_kn"],
        "parameters": {"Aw_cm2": 0.0, "VRd_kn": 0.0, "outside_t_shear_case": True},
        "combinations": combinations,
    }


def verify_t_shear_y(element, model, results):
    return _shear(element, model, results, "y")


def verify_t_shear_z(element, model, results):
    return _shear(element, model, results, "z")


def _interaction(element, model, results, tension, compression, flex_y, flex_z, mode):
    try:
        members, _, _, _, _, _ = _base(element, model, results)
        nt = float((tension.get("parameters") or {}).get("Nt_Rd_kn", 0.0))
        nc = float((compression.get("parameters") or {}).get("Nc_Rd_kn", 0.0))
        myr = float((flex_y.get("parameters") or {}).get("MRd_kn_cm", 0.0))
        mzr = float((flex_z.get("parameters") or {}).get("MRd_kn_cm", 0.0))
        axial_capacity = nt if mode == "tension" else nc
        critical, combinations = None, []
        for result in results:
            governing = None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    n_raw = float(sample.get("axial", 0.0))
                    n = max(0.0, -n_raw) if mode == "tension" else max(0.0, n_raw)
                    my = abs(float(sample.get("moment_y", 0.0))) * 100.0
                    mz = abs(float(sample.get("moment_z", 0.0))) * 100.0
                    if n < MIN_TENSION_KN and my < MIN_BENDING_KN_M * 100.0 and mz < MIN_BENDING_KN_M * 100.0:
                        continue
                    ratio_n = n / max(axial_capacity, EPS) if mode != "oblique" else 0.0
                    ratio_my = my / max(myr, EPS)
                    ratio_mz = mz / max(mzr, EPS)
                    if mode == "oblique":
                        candidate_utilization = ratio_my + ratio_mz
                    elif ratio_n >= 0.2:
                        candidate_utilization = ratio_n + (8.0 / 9.0) * (ratio_my + ratio_mz)
                    else:
                        candidate_utilization = ratio_n / 2.0 + ratio_my + ratio_mz
                    if governing is None or candidate_utilization > governing[4]:
                        governing = (n, my, mz, member.name, candidate_utilization)
            if governing is None:
                combinations.append({"combination": result.load_reference, "member": None,
                                     "utilization": 0.0, "status": "N/A"})
                continue
            n, my, mz, owner, interaction = governing
            ratio_n = n / max(axial_capacity, EPS) if mode != "oblique" else 0.0
            ratio_my = my / max(myr, EPS)
            ratio_mz = mz / max(mzr, EPS)
            item = {"combination": result.load_reference, "member": owner,
                    "applied_kn": n, "applied_my_kn_cm": my,
                    "applied_mz_kn_cm": mz, "utilization": interaction,
                    "axial_ratio": ratio_n, "moment_y_ratio": ratio_my,
                    "moment_z_ratio": ratio_mz,
                    "interaction_case": "NBR 8800:2024, 5.5.1.2",
                    "status": "APROVADO" if interaction <= 1.0 else "REPROVADO"}
            combinations.append(item)
            if critical is None or item["utilization"] > critical["utilization"]:
                critical = item
        return {
            "status": "checked" if critical else "not_applicable",
            "detail": "" if critical else "nenhum esforço combinado aplicável",
            "utilization": critical["utilization"] if critical else None,
            "critical_check": {"oblique": "Flexão oblíqua", "tension": "Flexotração",
                               "compression": "Flexocompressão"}[mode],
            "critical_combination": critical["combination"] if critical else "N/A",
            "critical_member": critical["member"] if critical else None,
            "applied_kn": critical["applied_kn"] if critical else None,
            "applied_my_kn_cm": critical["applied_my_kn_cm"] if critical else None,
            "applied_mz_kn_cm": critical["applied_mz_kn_cm"] if critical else None,
            "parameters": {"Nt_Rd_kn": nt, "Nc_Rd_kn": nc,
                           "My_Rd_kn_cm": myr, "Mz_Rd_kn_cm": mzr},
            "combinations": combinations,
        }
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_t_oblique_bending(element, model, results, flex_y, flex_z):
    return _interaction(element, model, results, {}, {}, flex_y, flex_z, "oblique")


def verify_t_flexotension(element, model, results, tension, flex_y, flex_z):
    return _interaction(element, model, results, tension, {}, flex_y, flex_z, "tension")


def verify_t_flexocompression(element, model, results, compression, flex_y, flex_z):
    return _interaction(element, model, results, {}, compression, flex_y, flex_z, "compression")
