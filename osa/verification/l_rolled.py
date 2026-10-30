"""Resistance checks for equal-leg rolled L sections."""

from __future__ import annotations

from math import pi, sqrt

from osa.sections.contours import polygon_properties
from osa.verification.calculation_properties import calculation_property
from osa.verification.restraints import restraint_lengths

GAMMA_A1 = 1.10
GAMMA_A2 = 1.35
EPS = 1e-9
MIN_SIGNIFICANT_TENSION_KN = 0.001
MIN_SIGNIFICANT_COMPRESSION_KN = 0.001


def _section(member) -> dict[str, float]:
    g = member.geometry_dict()
    b = float(g.get("b", g.get("b_mm", 0.0)))
    t = float(g.get("t", g.get("t_mm", 0.0)))
    if b <= t or t <= 0:
        raise ValueError("geometria L inválida: b deve ser maior que t")
    # The L section catalog supplies only the outside leg and thickness. Match
    # the section-properties service, which models that input as two rectangles
    # with their common thickness overlap removed.
    half = b / 2.0
    points = ((-half, half), (-half + t, half), (-half + t, -half + t),
              (half, -half + t), (half, -half), (-half, -half))
    area, cy, cz, _, _, _ = polygon_properties(points)
    area, iy, iz, iyz = _second_moments(points, area, cy, cz)
    # Principal inertias and the symmetric axis for an equal-leg angle.
    mean = (iy + iz) / 2.0
    radius = sqrt(((iy - iz) / 2.0) ** 2 + iyz**2)
    i_major, i_minor = mean + radius, mean - radius
    # Elastic moduli about the member local axes use the actual extreme fibers.
    wy = iy / max(abs(z - cz) for _, z in points)
    wz = iz / max(abs(y - cy) for y, _ in points)
    zy = _plastic_modulus(points, 1, cz)
    zz = _plastic_modulus(points, 0, cy)
    # Thin-wall Saint-Venant torsion for the two legs, in mm^4.
    jt = (2.0 * b - t) * t**3 / 3.0
    # Equal-leg angles are monosymmetric. Their shear center is approximated at
    # the intersection of the leg mid-lines; Cw is zero for this idealized open
    # two-plate model, so the torsional buckling term contains GJ only.
    shear_center_coordinate = -half + t / 2.0
    shear_offset = sqrt((cy - shear_center_coordinate) ** 2 + (cz - shear_center_coordinate) ** 2)
    r0_sq = i_major / area + i_minor / area + shear_offset**2
    return {
        "b_mm": b, "t_mm": t, "Ag_cm2": area / 100.0,
        "cy_mm": cy, "cz_mm": cz, "Iy_cm4": iy / 1e4, "Iz_cm4": iz / 1e4,
        "Iyz_cm4": iyz / 1e4,
        "Imajor_cm4": i_major / 1e4, "Iminor_cm4": i_minor / 1e4,
        "Wy_cm3": wy / 1e3, "Wz_cm3": wz / 1e3,
        "Zy_cm3": zy / 1e3, "Zz_cm3": zz / 1e3,
        "ry_cm": sqrt(iy / area) / 10.0, "rz_cm": sqrt(iz / area) / 10.0,
        "rmajor_cm": sqrt(i_major / area) / 10.0,
        "rminor_cm": sqrt(i_minor / area) / 10.0,
        "It_cm4": jt / 1e4, "Cw_cm6": 0.0,
        "x0_cm": shear_offset / 10.0, "r0_cm": sqrt(r0_sq) / 10.0,
        "_points": points,
    }


def _second_moments(points, area: float, cy: float, cz: float):
    """Calculate centroidal inertias with the standard signed polygon sums."""
    cross = [a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])]
    signed_area = sum(cross) / 2.0
    if abs(signed_area) <= EPS:
        raise ValueError("contorno L sem área")
    sign = 1.0 if signed_area > 0 else -1.0
    iy0 = sign * sum(c * (a[1]**2 + a[1] * b[1] + b[1]**2)
                     for c, (a, b) in zip(cross, zip(points, points[1:] + points[:1]))) / 12.0
    iz0 = sign * sum(c * (a[0]**2 + a[0] * b[0] + b[0]**2)
                     for c, (a, b) in zip(cross, zip(points, points[1:] + points[:1]))) / 12.0
    iyz0 = sign * sum(c * (2*a[0]*a[1] + a[0]*b[1] + b[0]*a[1] + 2*b[0]*b[1])
                      for c, (a, b) in zip(cross, zip(points, points[1:] + points[:1]))) / 24.0
    return (area, iy0 - area * cz**2, iz0 - area * cy**2,
            iyz0 - area * cy * cz)


def _plastic_modulus(points, axis: int, centroid: float) -> float:
    # Equal-leg L has a plastic neutral axis at its symmetry line for the
    # corresponding bending direction only if the load follows that axis.
    # Binary search integrates the polygon area and its first moment robustly.
    coords = [point[axis] for point in points]
    low, high = min(coords), max(coords)
    section_min = low
    total = polygon_properties(points)[0]

    def area_below(cut: float) -> float:
        # Vertical/horizontal strips are integrated at contour breakpoints.
        breaks = sorted({section_min, cut, *(value for value in coords if section_min < value < cut)})
        area = 0.0
        for a, b in zip(breaks, breaks[1:]):
            if b <= a:
                continue
            area += _width(points, axis, (a + b) / 2.0) * (b - a)
        return area

    for _ in range(64):
        mid = (low + high) / 2.0
        if area_below(mid) < total / 2.0:
            low = mid
        else:
            high = mid
    pna = (low + high) / 2.0
    return _first_moment_abs(points, axis, pna)


def _width(points, axis: int, position: float) -> float:
    cross = []
    other = 1 - axis
    for p, q in zip(points, points[1:] + points[:1]):
        if min(p[axis], q[axis]) < position < max(p[axis], q[axis]):
            f = (position - p[axis]) / (q[axis] - p[axis])
            cross.append(p[other] + f * (q[other] - p[other]))
    cross.sort()
    return sum(cross[i + 1] - cross[i] for i in range(0, len(cross) - 1, 2))


def _first_moment_abs(points, axis: int, pna: float) -> float:
    # Integrate each side of the plastic neutral axis with midpoint strips.
    other = 1 - axis
    breaks = sorted({p[axis] for p in points} | {pna})
    result = 0.0
    for a, b in zip(breaks, breaks[1:]):
        if b - a <= EPS:
            continue
        # Width is piecewise linear between contour vertices; 4-point sampling
        # exactly integrates width times distance for the polygonal contour.
        for k, weight in ((0.0694318442, 0.1739274226), (0.3300094782, 0.3260725774),
                          (0.6699905218, 0.3260725774), (0.9305681558, 0.1739274226)):
            x = a + (b - a) * k
            result += weight * (b - a) * _width(points, axis, x) * abs(x - pna)
    return result


def _members(element, model):
    members = [model.bars.get(name) for name in element.member_names]
    if not members or any(member is None for member in members):
        raise ValueError("barra não encontrada no modelo")
    if any(member.section != "L Laminado" for member in members):
        raise ValueError("a rotina atende apenas perfis L laminados de abas iguais")
    if any(not member.section_geometry for member in members):
        raise ValueError("geometria da seção incompleta")
    if len({(m.profile, m.section_geometry, m.material) for m in members}) != 1:
        raise ValueError("grupo com seções ou materiais diferentes")
    return members


def _base(element, model, results):
    members = _members(element, model)
    if not results or any(m.name not in r.member_results for r in results for m in members):
        raise ValueError("resultados de análise indisponíveis")
    vals = model.materials.get(members[0].material, ())
    if len(vals) < 6:
        raise ValueError("propriedades do material não definidas")
    e, g, fy, fu = (float(vals[i]) / 10000.0 for i in (0, 1, 4, 5))
    if min(e, g, fy, fu) <= 0:
        raise ValueError("propriedades do material inválidas")
    geom = _section(members[0])
    return members, geom, e, g, fy, fu


def verify_l_slenderness(element, model, results) -> dict:
    """Report the recommended global slenderness limits for rolled L bars.

    NBR 8800:2024, 5.2.8.1 and 5.3.7.1 give service recommendations of 300
    in tension and 200 in compression. These recommendations do not alter the
    resistance-check approval status.
    """
    try:
        members = _members(element, model)
        props = _section(members[0])
        area_cm2 = props["Ag_cm2"]
        iy_cm4, iz_cm4 = props["Iy_cm4"], props["Iz_cm4"]
        if min(area_cm2, iy_cm4, iz_cm4) <= 0.0:
            raise ValueError("propriedades geométricas inválidas para a esbeltez")
        lengths = restraint_lengths(
            model, element, results or (), {"Iy": iz_cm4, "tw": props["t_mm"] / 10.0},
        )
        ly_cm = lengths.lengths_m["Ly"] * 100.0
        lz_cm = lengths.lengths_m["Lz"] * 100.0
        ry_cm = sqrt(iy_cm4 / area_cm2)
        rz_cm = sqrt(iz_cm4 / area_cm2)
        rminor_cm = props["rminor_cm"]
        if min(ly_cm, lz_cm, ry_cm, rz_cm, rminor_cm) <= 0.0:
            raise ValueError("comprimentos destravados ou raios de giração inválidos")
        lambda_y, lambda_z = ly_cm / ry_cm, lz_cm / rz_cm
        # The L's minimum-radius principal axis is inclined to local Y/Z. The
        # restraint model provides only those two lengths, so use the larger
        # one as a conservative estimate for that inclined direction.
        inclined_length_cm = max(ly_cm, lz_cm)
        lambda_minor = inclined_length_cm / rminor_cm
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
        "status": "checked", "has_tension": has_tension,
        "has_compression": has_compression,
        "parameters": {
            "Ly_cm": ly_cm, "Lz_cm": lz_cm,
            "ry_cm": ry_cm, "rz_cm": rz_cm,
            "inclined_length_cm": inclined_length_cm,
            "rminor_cm": rminor_cm, "lambda_minor": lambda_minor,
            "inclined_length_assumption": "max(Ly, Lz)",
            "lambda_y": lambda_y, "lambda_z": lambda_z,
            "lambda_tension_max": max(lambda_y, lambda_z, lambda_minor),
            "lambda_compression_max": max(lambda_y, lambda_z, lambda_minor),
            "tension_limit": 300.0, "compression_limit": 200.0,
        },
    }


def _finish(check_name, capacity, results, members, field, demand_scale=1.0):
    critical = None
    combinations = []
    for result in results:
        demand, owner = 0.0, None
        for member in members:
            for sample in result.member_results[member.name].get("samples", ()):
                value = abs(float(sample.get(field, 0.0))) * demand_scale
                if value > demand:
                    demand, owner = value, member.name
        if demand <= EPS:
            combinations.append({"combination": result.load_reference, "member": None,
                                 "applied": 0.0, "utilization": 0.0, "status": "N/A"})
            continue
        utilization = demand / capacity if capacity > 0 else float("inf")
        item = {"combination": result.load_reference, "member": owner, "applied": demand,
                "utilization": utilization, "status": "APROVADO" if utilization <= 1 else "REPROVADO"}
        combinations.append(item)
        if critical is None or utilization > critical["utilization"]:
            critical = item
    return {
        "status": "checked" if critical else "not_applicable",
        "detail": "" if critical else "nenhuma combinação apresentou solicitação neste modo",
        "utilization": critical["utilization"] if critical else None,
        "critical_check": check_name,
        "critical_combination": critical["combination"] if critical else "N/A",
        "critical_member": critical["member"] if critical else None,
        "applied_kn": critical["applied"] if critical else None,
        "applied_kn_cm": critical["applied"] if critical and field.startswith("moment") else None,
        "parameters": {}, "combinations": combinations,
    }


def verify_l_tension(element, model, results):
    try:
        members, geom, _, _, fy, fu = _base(element, model, results)
        n1 = geom["Ag_cm2"] * fy / GAMMA_A1
        ct = calculation_property(model, element, "Ct", 1.0)
        ae = geom["Ag_cm2"] * ct
        n2 = ae * fu / GAMMA_A2
        cap = min(n1, n2)
        out = _finish("Tração axial", cap, results, members, "axial")
        # O modelo não representa os detalhes de furos e ligação; An = Ag e Ct = 1.
        out["parameters"] = {"Ag_cm2": geom["Ag_cm2"], "An_cm2": geom["Ag_cm2"],
                             "Ae_cm2": ae, "Ct": ct, "fy_kn_cm2": fy,
                             "fu_kn_cm2": fu, "gamma_a1": GAMMA_A1, "gamma_a2": GAMMA_A2,
                             "Nt_Rd1_kn": n1, "Nt_Rd2_kn": n2, "Nt_Rd_kn": cap}
        # O sinal axial do solver é positivo em compressão.
        critical = None
        combinations = []
        for result in results:
            demand, owner = 0.0, None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    value = max(0.0, -float(sample.get("axial", 0.0)))
                    if value > demand: demand, owner = value, member.name
            util = demand / cap if cap > 0 else float("inf")
            item = {"combination": result.load_reference, "member": owner, "applied_kn": demand,
                    "utilization": util, "status": "APROVADO" if util <= 1 else "REPROVADO"}
            combinations.append(item)
            if demand > EPS and (critical is None or util > critical["utilization"]): critical = item
        out.update({"status": "checked" if critical else "not_applicable",
                    "detail": "" if critical else "nenhuma combinação apresentou tração axial",
                    "utilization": critical["utilization"] if critical else None,
                    "critical_combination": critical["combination"] if critical else "N/A",
                    "critical_member": critical["member"] if critical else None,
                    "applied_kn": critical["applied_kn"] if critical else None,
                    "combinations": combinations})
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_l_compression(element, model, results):
    try:
        members, p, e, g, fy, _ = _base(element, model, results)
        lengths = restraint_lengths(model, element, results, {"Iy": p["Iz_cm4"], "tw": p["t_mm"] / 10})
        ly, lz, lt = (lengths.lengths_m[key] * 100 for key in ("Ly", "Lz", "Lt"))
        if min(ly, lz, lt) <= 0: raise ValueError("comprimentos destravados inválidos")
        it = p["It_cm4"]
        area = p["Ag_cm2"]
        # 5.3.5.2: use the restraint length associated with each flexural
        # buckling axis and the torsional restraint length for the torsional
        # mode. For an equal-leg angle, the shear-center offset lies on the
        # symmetry (major principal) axis; its magnitude is |y0| in the
        # principal-axis coordinates used by the standard.
        ne_y = pi**2 * e * p["Imajor_cm4"] / ly**2
        ne_z = pi**2 * e * p["Iminor_cm4"] / lz**2
        r0sq = p["r0_cm"]**2
        cw = p["Cw_cm6"]
        ne_t = (pi**2 * e * cw / lt**2 + g * it) / r0sq
        h_flexotorsion = 1.0 - (p["x0_cm"]**2 / r0sq)
        if h_flexotorsion <= 0.0:
            raise ValueError("parâmetro H inválido para flambagem flexo-torcional")
        ne_sum = ne_y + ne_t
        # Algebraically identical to 5.3.5.2, without cancellation when the
        # two component loads have very different orders of magnitude.
        ne_ft = 2.0 * ne_y * ne_t / (
            ne_sum + sqrt(max(0.0, ne_sum**2 - 4.0 * ne_y * ne_t * h_flexotorsion))
        )
        ne = min(ne_z, ne_ft)
        lam = sqrt(area * fy / ne)
        chi = 0.658**lam**2 if lam <= 1.5 else 0.877 / lam**2
        # Both outstanding legs are AL elements, group 3 in Table 4 (5.3.4).
        limit = 0.45 * sqrt(e / fy)
        effective_widths = []
        for width in (p["b_mm"], p["b_mm"]):
            slender = width / p["t_mm"]
            if slender <= limit / sqrt(chi):
                be = width
            else:
                sig_el = (1.49 * limit / slender) ** 2 * fy
                ratio = sig_el / (chi * fy)
                be = width * max(0.0, 1 - 0.22 * sqrt(ratio)) * sqrt(ratio)
            effective_widths.append(be)
        removed_area = sum((p["b_mm"] - be) * p["t_mm"] for be in effective_widths) / 100.0
        aef = max(0.0, min(area, area - removed_area))
        cap = chi * aef * fy / GAMMA_A1
        out = _finish("Compressão axial", cap, results, members, "axial")
        # positive axial forces are compression
        comb, critical = [], None
        for result in results:
            demand, owner = 0.0, None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    value = max(0.0, float(sample.get("axial", 0.0)))
                    if value > demand: demand, owner = value, member.name
            util = demand / cap if cap > 0 else float("inf")
            item = {"combination": result.load_reference, "member": owner, "applied_kn": demand,
                    "utilization": util, "status": "APROVADO" if util <= 1 else "REPROVADO"}
            comb.append(item)
            if demand > EPS and (critical is None or util > critical["utilization"]): critical = item
        out.update({"status": "checked" if critical else "not_applicable",
                    "detail": "" if critical else "nenhuma combinação apresentou compressão axial",
                    "utilization": critical["utilization"] if critical else None,
                    "critical_combination": critical["combination"] if critical else "N/A",
                    "critical_member": critical["member"] if critical else None,
                    "applied_kn": critical["applied_kn"] if critical else None,
                    "combinations": comb,
                    "parameters": {"Ag_cm2": area, "Aef_cm2": aef, "fy_kn_cm2": fy,
                                   "E_kn_cm2": e, "G_kn_cm2": g, "gamma_a1": GAMMA_A1,
                                   "Iy_cm4": p["Imajor_cm4"], "Iz_cm4": p["Iminor_cm4"], "It_cm4": it,
                                   "Iy_geometric_cm4": p["Iy_cm4"], "Iz_geometric_cm4": p["Iz_cm4"],
                                   "Cw_cm6": cw, "y0_cm": p["x0_cm"], "r0_cm": p["r0_cm"],
                                   "Ney_kn": ne_y, "Nez_kn": ne_z, "Net_kn": ne_t,
                                   "H_flexotorsion": h_flexotorsion,
                                   "Ne_flexotorsao_kn": ne_ft, "Ne_kn": ne,
                                   "Npl_kn": area * fy, "lambda0": lam, "chi": chi, "Nc_Rd_kn": cap,
                                   "compression_version": "principal_axes_v1",
                                   "b_mm": p["b_mm"], "t_mm": p["t_mm"],
                                   "leg_slenderness": p["b_mm"] / p["t_mm"],
                                   "leg_limit": limit, "leg_reduced_limit": limit / sqrt(chi),
                                   "leg_effective_width_mm": effective_widths[0],
                                   "leg_effective_widths_mm": effective_widths,
                                   "leg_sigma_el_kn_cm2": ((1.49 * limit / (p["b_mm"] / p["t_mm"]))**2 * fy),
                                   "Ly_cm": ly, "Lz_cm": lz, "Lt_cm": lt,
                                   "restraint_issues": list(lengths.issues),
                                   "compression_method": "NBR 8800:2024, 5.3.5.2 (seção monossimétrica)"}})
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def _flexion(element, model, results, axis: int):
    """Reproduce the compact-section calculation shown in the MCalc example."""
    try:
        members, p, e, _, fy, _ = _base(element, model, results)
        key = "y" if axis == 1 else "z"
        b, t = p["b_mm"] / 10.0, p["t_mm"] / 10.0
        w, z = p[f"W{key}_cm3"], p[f"Z{key}_cm3"]
        slender = b / t
        lp, lr = 1.12 * sqrt(e / fy), 1.40 * sqrt(e / fy)
        mpl = z * fy
        mcr = 0.69 * e * w / slender**2
        parameters = {
            "Ag_cm2": p["Ag_cm2"], "Wy_cm3": p["Wy_cm3"], "Wz_cm3": p["Wz_cm3"],
            "Zy_cm3": p["Zy_cm3"], "Zz_cm3": p["Zz_cm3"],
            "b_cm": b, "t_cm": t, "W_cm3": w, "Z_cm3": z,
            "E_kn_cm2": e, "fy_kn_cm2": fy, "gamma_a1": GAMMA_A1,
            "sigma_r_kn_cm2": 0.30 * fy, "lambda_leg": slender,
            "lambda_p": lp, "lambda_r": lr, "Mpl_kn_cm": mpl,
            "Mcr_kn_cm": mcr, "criterion": "MCalc: exemplo fornecido; hipótese para cantoneira simples",
            "method_version": "mcalc_compact_v1",
        }
        if slender > lp:
            return {"status": "not_checked", "parameters": parameters,
                    "detail": "Regime não plástico: equações ainda não disponíveis."}
        parameters.update({"Mn_kn_cm": mpl, "MRd_kn_cm": mpl / GAMMA_A1})
        field = "moment_y" if axis == 1 else "moment_z"
        out = _finish(f"Flexão {key.upper()}", mpl / GAMMA_A1, results, members, field, 100.0)
        out["parameters"] = parameters
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_l_flexion_y(element, model, results): return _flexion(element, model, results, 1)
def verify_l_flexion_z(element, model, results): return _flexion(element, model, results, 0)


def _shear(element, model, results, axis: int):
    """Reproduce the plastic shear branch shown in the MCalc example."""
    try:
        members, p, e, _, fy, _ = _base(element, model, results)
        b, t = p["b_mm"] / 10.0, p["t_mm"] / 10.0
        kv, lam = 5.0, b / t
        lp, lr = 1.10 * sqrt(kv * e / fy), 1.37 * sqrt(kv * e / fy)
        vp = 0.60 * b * t * fy
        parameters = {"Aw_cm2": b * t, "lambda": lam, "lambda_p": lp,
                      "lambda_r": lr, "kv": kv, "b_cm": b, "t_cm": t,
                      "fy_kn_cm2": fy, "E_kn_cm2": e, "Vp_kn": vp,
                      "gamma_a1": GAMMA_A1, "method_version": "mcalc_plastic_v1",
                      "criterion": "MCalc: exemplo fornecido; hipótese para cantoneira simples"}
        if lam > lp:
            return {"status": "not_checked", "parameters": parameters,
                    "detail": "Regime não plástico: equações ainda não disponíveis."}
        parameters.update({"Vn_kn": vp, "VRd_kn": vp / GAMMA_A1})
        field = "shear_y" if axis == 1 else "shear_z"
        out = _finish(f"Cortante {('Y' if axis == 1 else 'Z')}", vp / GAMMA_A1, results, members, field)
        out["parameters"] = parameters
        return out
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_l_shear_y(element, model, results): return _shear(element, model, results, 1)
def verify_l_shear_z(element, model, results): return _shear(element, model, results, 0)


def _interaction(element, model, results, tension, compression, flex_y, flex_z, tension_case,
                 include_axial: bool = True):
    try:
        members, _, _, _, _, _ = _base(element, model, results)
        nt = float((tension.get("parameters") or {}).get("Nt_Rd_kn", 0.0))
        nc = float((compression.get("parameters") or {}).get("Nc_Rd_kn", 0.0))
        if any(check.get("status") == "not_checked" for check in (flex_y, flex_z)):
            return {"status": "not_checked", "detail": "Resistência à flexão indisponível para a interação."}
        myr = float((flex_y.get("parameters") or {}).get("MRd_kn_cm", 0.0))
        mzr = float((flex_z.get("parameters") or {}).get("MRd_kn_cm", 0.0))
        critical, combos = None, []
        for result in results:
            governing = None
            for member in members:
                for sample in result.member_results[member.name].get("samples", ()):
                    n = float(sample.get("axial", 0.0))
                    n = (max(0.0, -n) if tension_case else max(0.0, n)) if include_axial else 0.0
                    my, mz = abs(float(sample.get("moment_y", 0.0))) * 100, abs(float(sample.get("moment_z", 0.0))) * 100
                    if n <= EPS and my <= EPS and mz <= EPS:
                        continue
                    ratio_n = n / max(nt if tension_case else nc, EPS)
                    flex = my / max(myr, EPS) + mz / max(mzr, EPS)
                    # NBR 8800:2024, 5.5.1.2: the 8/9 factor multiplies
                    # the moment terms when N/N_Rd >= 0.2; below 0.2, the
                    # axial term is divided by 2. The standard's 5.4.1.1
                    # scope does not list a single L section, so this
                    # interaction is applied to L by analogy and must be
                    # identified as such in the engineering basis.
                    if ratio_n >= 0.2:
                        util = ratio_n + (8.0 / 9.0) * flex
                        interaction_case = "Nsd/Nrd >= 0,2"
                    else:
                        util = ratio_n / 2.0 + flex
                        interaction_case = "Nsd/Nrd < 0,2"
                    if governing is None or util > governing[4]:
                        governing = (n, my, mz, member.name, util, interaction_case)
            if governing is None:
                combos.append({"combination": result.load_reference, "member": None, "utilization": 0.0,
                               "status": "N/A"}); continue
            n, my, mz, owner, util, interaction_case = governing
            ratio_n = n / max(nt if tension_case else nc, EPS)
            item = {"combination": result.load_reference, "member": owner, "applied_kn": n,
                    "applied_my_kn_cm": my, "applied_mz_kn_cm": mz,
                    "utilization": util, "interaction_case": interaction_case,
                    "status": "APROVADO" if util <= 1 else "REPROVADO"}
            combos.append(item)
            if critical is None or util > critical["utilization"]: critical = item
        return {"status": "checked" if critical else "not_applicable",
                "detail": "" if critical else "nenhum esforço combinado aplicável",
                "utilization": critical["utilization"] if critical else None,
                "critical_check": "Flexotração" if tension_case else "Flexocompressão",
                "critical_combination": critical["combination"] if critical else "N/A",
                "critical_member": critical["member"] if critical else None,
                "applied_kn": critical["applied_kn"] if critical else None,
                "applied_my_kn_cm": critical["applied_my_kn_cm"] if critical else None,
                "applied_mz_kn_cm": critical["applied_mz_kn_cm"] if critical else None,
                "parameters": {"Nt_Rd_kn": nt, "Nc_Rd_kn": nc,
                               "N_Rd_kn": nt if tension_case else nc,
                               "My_Rd_kn_cm": myr,
                               "Mz_Rd_kn_cm": mzr}, "combinations": combos}
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        return {"status": "not_checked", "detail": str(error)}


def verify_l_oblique_bending(element, model, results, flex_y, flex_z):
    return _interaction(element, model, results, {}, {}, flex_y, flex_z, True, include_axial=False)


def verify_l_flexotension(element, model, results, tension, flex_y, flex_z):
    return _interaction(element, model, results, tension, {}, flex_y, flex_z, True)


def verify_l_flexocompression(element, model, results, compression, flex_y, flex_z):
    return _interaction(element, model, results, {}, compression, flex_y, flex_z, False)
