"""Primeira rotina de verificação para perfis W laminados."""

from __future__ import annotations

from math import pi, sqrt

from osa.sections.contours import polygon_properties, w_contour_points
from .elements import VerificationElement

E_KN_CM2 = 20_000.0
G_KN_CM2 = 7_690.0
GAMMA_A1 = 1.10


def _geometry_properties(member):
    g = member.geometry_dict()
    def dimension(name: str) -> float:
        return float(g.get(name, g.get(f"{name}_mm")))
    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    r = float(g.get("r", g.get("r_mm", 10.0)))
    points = w_contour_points(d, bf, tw, tf, r)
    area_mm2, _cy, _cz, iy_mm4, iz_mm4, _iyz = polygon_properties(points)
    area = area_mm2 / 100.0
    iy = iy_mm4 / 1e4
    iz = iz_mm4 / 1e4
    d_cm, bf_cm, tw_cm, tf_cm, r_cm = (v / 10.0 for v in (d, bf, tw, tf, r))
    # The fillets are represented in A and I. J follows the thin-wall open-section model.
    j = (2.0 * bf_cm * tf_cm**3 + (d_cm - 2.0 * tf_cm) * tw_cm**3) / 3.0
    cw = iz * (d_cm - tf_cm) ** 2 / 4.0
    z_major = 2.0 * (bf_cm * tf_cm * (d_cm - tf_cm) / 2.0 + tw_cm * (d_cm / 2.0 - tf_cm) ** 2 / 4.0)
    # Plastic modulus for minor-axis bending, using the symmetric half-section.
    z_minor = (tf_cm * bf_cm**2 / 4.0 + (d_cm - 2.0 * tf_cm) * tw_cm**2 / 4.0) * 2.0
    return {
        "d": d_cm, "bf": bf_cm, "tw": tw_cm, "tf": tf_cm, "r": r_cm,
        "A": area, "Ix": iy, "Iy": iz, "J": j, "Cw": cw,
        "Wx": iy / (d_cm / 2.0), "Wy": iz / (bf_cm / 2.0),
        "Zx": z_major, "Zy": z_minor,
    }


def _shear_capacity(h: float, t: float, area: float, kv: float, fy: float) -> float:
    lam = h / t
    lp = 1.10 * sqrt(kv * E_KN_CM2 / fy)
    lr = 1.37 * sqrt(kv * E_KN_CM2 / fy)
    vpl = 0.60 * area * fy
    if lam <= lp:
        return vpl / GAMMA_A1
    if lam <= lr:
        return (lp / lam) * vpl / GAMMA_A1
    return 1.24 * (lp / lam) ** 2 * vpl / GAMMA_A1


def _flexural_capacities(p: dict[str, float], span_cm: float, fy: float) -> tuple[float, float]:
    d, bf, tw, tf, r = p["d"], p["bf"], p["tw"], p["tf"], p["r"]
    e = E_KN_CM2
    # FLM and FLA per the piecewise limits for rolled I/H sections.
    lam_f = max(0.0, (bf - tw - 2.0 * r) / 2.0) / tf
    lp_f = 0.38 * sqrt(e / fy)
    lr_f = 0.83 * sqrt(e / (fy - 0.30 * fy))
    mpl_x = p["Zx"] * fy
    mr_x = 0.70 * fy * p["Wx"]
    mcr_flm = 0.69 * e * p["Wx"] / max(lam_f**2, 1e-12)
    if lam_f <= lp_f:
        m_flm = mpl_x
    elif lam_f <= lr_f:
        m_flm = mpl_x - (mpl_x - mr_x) * (lam_f - lp_f) / (lr_f - lp_f)
    else:
        m_flm = mcr_flm

    h = d - 2.0 * (tf + r)
    lam_w = h / tw
    lp_w = 3.76 * sqrt(e / fy)
    lr_w = 5.70 * sqrt(e / fy)
    mr_w = fy * p["Wx"]
    if lam_w > lr_w:
        raise ValueError("alma esbelta exige verificação adicional")
    m_fla = mpl_x if lam_w <= lp_w else mpl_x - (mpl_x - mr_w) * (lam_w - lp_w) / (lr_w - lp_w)

    # Elastic critical moment for a doubly symmetric I section; Cb is fixed at 1.0.
    mcr = (pi**2 * e * p["Iy"] / span_cm**2) * sqrt(
        max(0.0, p["Cw"] / p["Iy"] * (1.0 + 0.039 * p["J"] * span_cm**2 / p["Cw"]))
    )
    lp_lt = 1.76 * sqrt(e / fy)
    lr_lt = 1.76 * sqrt(e / (fy - 0.30 * fy))
    mr_lt = (fy - 0.30 * fy) * p["Wx"]
    lam_lt = sqrt(mpl_x / mcr) if mcr > 0.0 else float("inf")
    if lam_lt <= lp_lt:
        m_flt = mpl_x
    elif lam_lt <= lr_lt:
        m_flt = mpl_x - (mpl_x - mr_lt) * (lam_lt - lp_lt) / (lr_lt - lp_lt)
    else:
        m_flt = mcr
    return min(m_flm, m_fla, m_flt) / GAMMA_A1, p["Zy"] * fy / GAMMA_A1


def verify_w_element(element: VerificationElement, model, results) -> dict:
    members = [model.bars[name] for name in element.member_names]
    if any(not (member.profile or "").lower().startswith("w") for member in members):
        return {"status": "not_checked", "detail": "a rotina atende apenas perfis W laminados"}
    if any(member.section_geometry == () or member.start_node not in model.nodes or member.end_node not in model.nodes
           for member in members):
        return {"status": "not_checked", "detail": "seção ou geometria incompleta"}
    if len({(member.profile, member.section_geometry, member.material) for member in members}) != 1:
        return {"status": "not_checked", "detail": "grupo com seções ou materiais diferentes"}
    if not results or any(name not in result.member_results for result in results for name in element.member_names):
        return {"status": "not_checked", "detail": "resultados de análise indisponíveis"}
    try:
        p = _geometry_properties(members[0])
        material_values = model.materials.get(members[0].material, ())
        if len(material_values) < 6 or material_values[4] <= 0.0 or material_values[5] <= 0.0:
            return {"status": "not_checked", "detail": "resistências do material não definidas"}
        fy_kn_m2, fu_kn_m2 = float(material_values[4]), float(material_values[5])
        fy = fy_kn_m2 / 10_000.0  # kN/m² to kN/cm²
        lengths_cm = [result.member_results[name]["length"] * 100.0
                      for result in results for name in element.member_names]
        span_cm = sum(lengths_cm) / len(results)
        if span_cm <= 0:
            return {"status": "not_checked", "detail": "vão inválido"}
        nx = pi**2 * E_KN_CM2 * p["Ix"] / span_cm**2
        ny = pi**2 * E_KN_CM2 * p["Iy"] / span_cm**2
        r0_sq = (p["Ix"] + p["Iy"]) / p["A"]
        nt = (pi**2 * E_KN_CM2 * p["Cw"] / span_cm**2 + G_KN_CM2 * p["J"]) / r0_sq
        ne = min(nx, ny, nt)
        lam0 = sqrt(p["A"] * fy / ne)
        chi = 0.658 ** (lam0**2) if lam0 <= 1.5 else 0.877 / lam0**2
        nrd_t = p["A"] * fy / GAMMA_A1
        nrd_c = chi * p["A"] * fy / GAMMA_A1
        mrd_x, mrd_y = _flexural_capacities(p, span_cm, fy)
        if mrd_x <= 0.0 or mrd_y <= 0.0:
            return {"status": "not_checked", "detail": "capacidade à flexão fora do domínio implementado"}
        vrd_x = _shear_capacity(p["d"] - 2 * p["tf"], p["tw"], p["d"] * p["tw"], 5.34, fy)
        vrd_y = _shear_capacity(p["bf"] / 2.0, p["tf"], 2 * p["bf"] * p["tf"], 1.2, fy)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        detail = str(error).strip() or "não foi possível obter propriedades da seção"
        return {"status": "not_checked", "detail": detail}

    critical = (0.0, "Sem solicitação", results[0].load_reference, "")
    for result in results:
        combo = result.load_reference
        for member_name in element.member_names:
            for sample in result.member_results[member_name].get("samples", ()):
                axial = float(sample.get("axial", 0.0))
                if axial < 0.0:
                    flange_slenderness = (p["bf"] - p["tw"] - 2.0 * p["r"]) / (2.0 * p["tf"])
                    web_slenderness = (p["d"] - 2.0 * (p["tf"] + p["r"])) / p["tw"]
                    if (flange_slenderness > 0.56 * sqrt(E_KN_CM2 / fy)
                            or web_slenderness > 1.49 * sqrt(E_KN_CM2 / fy)):
                        return {"status": "not_checked", "detail": "flambagem local em compressão ainda não está incluída"}
                torque = abs(float(sample.get("torque", 0.0)))
                if torque > 1e-6:
                    return {"status": "not_checked", "detail": "torção ainda não está incluída na verificação"}
                # PyNite reports member axial force positive in tension.
                n_ratio = axial / nrd_t if axial >= 0 else -axial / nrd_c
                mx = abs(float(sample.get("moment_y", 0.0))) * 100.0
                my = abs(float(sample.get("moment_z", 0.0))) * 100.0
                vx = abs(float(sample.get("shear_y", 0.0)))
                vy = abs(float(sample.get("shear_z", 0.0)))
                if vx > 0.50 * vrd_x or vy > 0.50 * vrd_y:
                    return {"status": "not_checked", "detail": "interação entre cisalhamento elevado e flexão ainda não está incluída"}
                rx, ry = mx / mrd_x, my / mrd_y
                # NBR 8800 interaction equation for axial force and biaxial bending.
                interaction = n_ratio + (8.0 / 9.0) * (rx + ry) if n_ratio >= 0.20 else n_ratio / 2.0 + rx + ry
                checks = (
                    (n_ratio, "Compressão" if axial < 0 else "Tração"),
                    (rx, "Flexão X-X"), (ry, "Flexão Y-Y"),
                    (vx / vrd_x, "Cisalhamento X-X"), (vy / vrd_y, "Cisalhamento Y-Y"),
                    (interaction, "Esforços combinados"),
                )
                for utilization, check_name in checks:
                    if utilization > critical[0]:
                        critical = (utilization, check_name, combo, member_name)
    utilization, check_name, combo, _member = critical
    return {
        "status": "approved" if utilization <= 1.0 else "rejected",
        "utilization": utilization,
        "critical_check": check_name,
        "critical_combination": combo,
        "detail": f"{utilization:.0%} · {check_name}",
        "assumptions": f"{members[0].material} · Kx=Ky=Kz=1,0 · Cb=1,0",
        "material_strengths": {"fy_kn_m2": fy_kn_m2, "fu_kn_m2": fu_kn_m2},
    }
