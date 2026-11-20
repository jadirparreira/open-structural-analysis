"""Circular hollow steel members: NBR 8800:2024 (corrected 2025).

Uses the general compression curve, without assuming the heat treatment
required by the optional NBR 16239:2013 curve. Net area and Ct are explicit.
All internal resistance calculations use kN and cm; samples use kN and m.
"""

from __future__ import annotations

from math import dist, isfinite, pi, sqrt

from osa.sections.properties import calculate_section_properties
from osa.verification.calculation_properties import calculation_property
from osa.verification.restraints import restraint_lengths
from osa.verification.steel_interactions import interactions
from osa.verification.structured_checks import NAMES, context, number, step
from osa.verification.structured_checks import check as _check

FAMILY = "Tubular Circular"


def section(member):
    geometry = member.geometry_dict()
    d, t = (float(geometry[key]) for key in ("D", "t"))
    if not all(isfinite(v) and v > 0 for v in (d, t)) or d <= 2 * t:
        raise ValueError("O tubular circular requer dimensões finitas, D > 2t e t > 0.")
    props = calculate_section_properties(FAMILY, geometry)
    return {"D_mm": d, "t_mm": t, "Ag_cm2": props.area_cm2,
            "Iy_cm4": props.iy_cm4, "Iz_cm4": props.iz_cm4,
            "Wy_cm3": props.iy_mm4 / (d / 2) / 1000,
            "Wz_cm3": props.iy_mm4 / (d / 2) / 1000,
            "Zy_cm3": (d**3 - (d - 2 * t)**3) / 6000,
            "Zz_cm3": (d**3 - (d - 2 * t)**3) / 6000,
            "It_cm4": props.j_cm4, "Cw_cm6": 0.,
            "ry_cm": sqrt(props.iy_cm4 / props.area_cm2),
            "rz_cm": sqrt(props.iz_cm4 / props.area_cm2)}


def _context(element, model, results):
    return context(element, model, results, {FAMILY}, section)


def verify(element, model, results):
    try:
        members, p, e, g, fy, fu, samples = _context(element, model, results)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {key: {"status": "not_checked", "detail": str(exc), "critical_check": name}
                for key, name in NAMES.items()}
    ag, w, z = p["Ag_cm2"], p["Wy_cm3"], p["Zy_cm3"]
    ratio = p["D_mm"] / p["t_mm"]
    parameters = {**p, "E_kn_cm2": e, "G_kn_cm2": g, "fy_kn_cm2": fy, "fu_kn_cm2": fu,
                  "D_t": ratio, "gamma_a1": 1.1, "gamma_a2": 1.35}
    checks = {}

    # NBR 8800, 5.2.2–5.2.5: no implicit gross-to-net or Ct assumption.
    tension_error, nt, tension_steps = None, None, []
    try:
        an = calculation_property(model, element, "An", None)
        ct = calculation_property(model, element, "Ct", None)
        if an is None or ct is None:
            raise ValueError("Informe An (cm²) e Ct, conforme os furos e a transmissão de força da ligação.")
        if not 0 < an <= ag or not 0 < ct <= 1:
            raise ValueError("An deve estar entre zero e Ag; Ct deve estar entre zero e 1.")
        nt = min(ag * fy / 1.1, ct * an * fu / 1.35)
        parameters.update(An_cm2=an, Ct=ct, Nt_Rd_kn=nt)
        tension_steps = [
            step("N_{t,Rd1}", r"A_g f_y/1{,}10", f"{number(ag)}\\cdot {number(fy)}/1{{,}}10", ag * fy / 1.1, "kN", "5.2.2(a)"),
            step("N_{t,Rd2}", r"C_t A_n f_u/1{,}35", f"{number(ct)}\\cdot {number(an)}\\cdot {number(fu)}/1{{,}}35", ct * an * fu / 1.35, "kN", "5.2.2(b); 5.2.3"),
            step("N_{t,Rd}", r"\min(N_{t,Rd1};N_{t,Rd2})", f"\\min({number(ag*fy/1.1)};{number(ct*an*fu/1.35)})", nt, "kN", "5.2.2"),
        ]
    except (ValueError, TypeError) as exc:
        tension_error = str(exc)
    checks["axial_tension"] = _check("axial_tension", samples, lambda s: max(0., -s["axial"]), nt,
                                      parameters.copy(), tension_steps, "ABNT NBR 8800:2024, 5.2", tension_error)

    nc, compression_error, compression_steps = None, None, []
    try:
        if ratio > .45 * e / fy:
            raise ValueError("D/t excede 0,45 E/fy: fora do campo de aplicação de 5.3.4.3.")
        lengths = restraint_lengths(model, element, results, {"Iy": p["Iy_cm4"], "tw": p["t_mm"] / 10})
        ly, lz, lt = (lengths.lengths_m[k] * 100 for k in ("Ly", "Lz", "Lt"))
        if min(ly, lz, lt) <= 0:
            raise ValueError("Comprimentos de flambagem inválidos.")
        ney, nez = pi*pi*e*p["Iy_cm4"]/ly**2, pi*pi*e*p["Iz_cm4"]/lz**2
        net = g*p["It_cm4"] / ((p["Iy_cm4"]+p["Iz_cm4"])/ag)
        ne = min(ney, nez, net)
        lam = sqrt(ag * fy / ne)
        chi = .658**(lam*lam) if lam <= 1.5 else .877/lam**2
        aef = ag if ratio <= .11*e/fy else ag*(.038*e/(ratio*fy)+2/3)
        nc = chi*aef*fy/1.1
        slenderness = max(ly / p["ry_cm"], lz / p["rz_cm"])
        advisories = []
        if any(s["axial"] > 1e-6 for _, _, s in samples) and slenderness > 200:
            advisories.append("L/r supera 200; conferir o limite recomendado de 5.3.7 e os critérios de serviço definidos pelo responsável técnico.")
        if any(s["axial"] < -1e-6 for _, _, s in samples) and slenderness > 300:
            advisories.append("L/r supera 300; conferir o limite recomendado de 5.2.8 e os critérios de serviço definidos pelo responsável técnico.")
        parameters.update(Ly_cm=ly, Lz_cm=lz, Lt_cm=lt, Ne_kn=ne, lambda0=lam,
                          Lb_cm=lengths.lengths_m["Lb"] * 100,
                          chi=chi, Aef_cm2=aef, Nc_Rd_kn=nc,
                          restraint_notes=tuple(lengths.notes), restraint_issues=tuple(lengths.issues),
                          advisories=tuple(advisories))
        compression_steps = [
            step(r"\lambda_y", "L_y/r_y", f"{number(ly)}/{number(p['ry_cm'])}", ly/p["ry_cm"], "", "5.2.8.1; 5.3.7.1"),
            step(r"\lambda_z", "L_z/r_z", f"{number(lz)}/{number(p['rz_cm'])}", lz/p["rz_cm"], "", "5.2.8.1; 5.3.7.1"),
            step("N_{ey}", r"\pi^2EI_y/L_y^2", f"\\pi^2\\cdot {number(e)}\\cdot {number(p['Iy_cm4'])}/{number(ly)}^2", ney, "kN", "5.3.5.1"),
            step("N_{ez}", r"\pi^2EI_z/L_z^2", f"\\pi^2\\cdot {number(e)}\\cdot {number(p['Iz_cm4'])}/{number(lz)}^2", nez, "kN", "5.3.5.1"),
            step("N_{et}", r"\dfrac{GJ}{(I_y+I_z)/A_g}", rf"\dfrac{{{number(g)}\cdot {number(p['It_cm4'])}}}{{({number(p['Iy_cm4'])}+{number(p['Iz_cm4'])})/{number(ag)}}}", net, "kN", "5.3.5.1; Cw=0"),
            step("N_e", r"\min(N_{ey};N_{ez};N_{et})", f"\\min({number(ney)};{number(nez)};{number(net)})", ne, "kN", "5.3.5.1"),
            step(r"\lambda_0", r"\sqrt{A_g f_y/N_e}", f"\\sqrt{{{number(ag)}\\cdot {number(fy)}/{number(ne)}}}", lam, "", "5.3.3.2"),
            step(r"\chi", r"0{,}658^{\lambda_0^2}" if lam <= 1.5 else r"0{,}877/\lambda_0^2", f"0{{,}}658^{{{number(lam)}^2}}" if lam <= 1.5 else f"0{{,}}877/{number(lam)}^2", chi, "", "5.3.3.1"),
            step("A_{ef}", "A_g" if ratio <= .11*e/fy else r"[0{,}038E/((D/t)f_y)+2/3]A_g", number(ag) if ratio <= .11*e/fy else f"[0{{,}}038\\cdot {number(e)}/({number(ratio)}\\cdot {number(fy)})+2/3]\\cdot {number(ag)}", aef, "cm^2", "5.3.4.3"),
            step("N_{c,Rd}", r"\chi A_{ef}f_y/1{,}10", f"{number(chi)}\\cdot {number(aef)}\\cdot {number(fy)}/1{{,}}10", nc, "kN", "5.3.2"),
        ]
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        compression_error = str(exc)
    checks["axial_compression"] = _check("axial_compression", samples, lambda s: max(0., s["axial"]), nc,
                                          parameters.copy(), compression_steps, "ABNT NBR 8800:2024, 5.3", compression_error)

    mr, flexion_error, flexion_steps = None, None, []
    if ratio > .45*e/fy:
        flexion_error = "D/t excede 0,45 E/fy: fora do campo de aplicação de D.2.6."
    else:
        lp, lr = .07*e/fy, .31*e/fy
        if ratio <= lp:
            mn, formula, sub = z*fy, r"Zf_y", f"{number(z)}\\cdot {number(fy)}"
        elif ratio <= lr:
            mn = (.021*e/ratio+fy)*w
            formula, sub = r"[0{,}021E/(D/t)+f_y]W", f"[0{{,}}021\\cdot {number(e)}/{number(ratio)}+{number(fy)}]\\cdot {number(w)}"
        else:
            mn = .33*e*w/ratio
            formula, sub = r"0{,}33EW/(D/t)", f"0{{,}}33\\cdot {number(e)}\\cdot {number(w)}/{number(ratio)}"
        mr = min(mn, 1.5*w*fy)/1.1
        parameters.update(lambda_p=lp, lambda_r=lr, MRd_kn_cm=mr)
        flexion_steps = [step(r"\lambda", "D/t", f"{number(p['D_mm'])}/{number(p['t_mm'])}", ratio, "", "Anexo D, D.2.6"),
                         step(r"\lambda_p", r"0{,}07E/f_y", f"0{{,}}07\\cdot {number(e)}/{number(fy)}", lp, "", "Anexo D, D.2.6"),
                         step(r"\lambda_r", r"0{,}31E/f_y", f"0{{,}}31\\cdot {number(e)}/{number(fy)}", lr, "", "Anexo D, D.2.6"),
                         step("M_n", formula, sub, mn, "kN\\,cm", "Anexo D, D.2.6"),
                         step("M_{Rd}", r"\min(M_n;1{,}5Wf_y)/1{,}10", f"\\min({number(mn)};{number(1.5*w*fy)})/1{{,}}10", mr, "kN\\,cm", "5.4.2.2; D.2.6")]
    for axis in ("y", "z"):
        checks[f"flexion_{axis}"] = _check(f"flexion_{axis}", samples,
            lambda s, a=axis: abs(s[f"moment_{a}"])*100, mr, parameters.copy(), flexion_steps,
            "ABNT NBR 8800:2024, Anexo D, D.2.6", flexion_error)

    vrs = {}
    for axis in ("y", "z"):
        shear_error, vr, shear_steps, lv = None, None, [], None
        tau2 = .78*e/ratio**1.5
        try:
            lv = calculation_property(model, element, f"Lv{axis.upper()}", None)
            if tau2 < .6*fy and lv is None:
                raise ValueError(f"Informe Lv{axis.upper()} (m), distância entre as seções de cortante máximo e nulo.")
            tau1 = 0. if lv is None else 1.60*e/(sqrt(lv*1000/p["D_mm"])*ratio**1.25)
            tau = min(.6*fy, max(tau1, tau2))
            vr = .5*tau*ag/1.1
            shear_steps = [step(r"\tau_{cr}", r"0{,}60f_y\quad(\tau_{cr2}\geq0{,}60f_y)" if lv is None else r"\min(0{,}60f_y;\max(\tau_{cr1};\tau_{cr2}))", f"0{{,}}60\\cdot {number(fy)}" if lv is None else f"\\min({number(.6*fy)};\\max({number(tau1)};{number(tau2)}))", tau, "kN/cm^2", "5.4.3.6"),
                           step("V_{Rd}", r"0{,}5\tau_{cr}A_g/1{,}10", f"0{{,}}5\\cdot {number(tau)}\\cdot {number(ag)}/1{{,}}10", vr, "kN", "5.4.3.6")]
            shear_steps.insert(0, step(r"\tau_{cr2}", r"0{,}78E/(D/t)^{3/2}", f"0{{,}}78\\cdot {number(e)}/{number(ratio)}^{{3/2}}", tau2, "kN/cm^2", "5.4.3.6"))
            if lv is not None:
                shear_steps.insert(0, step(r"\tau_{cr1}", r"1{,}60E/[\sqrt{L_v/D}(D/t)^{5/4}]", f"1{{,}}60\\cdot {number(e)}/[\\sqrt{{{number(lv*1000)}/{number(p['D_mm'])}}}\\cdot {number(ratio)}^{{5/4}}]", tau1, "kN/cm^2", "5.4.3.6"))
        except (ValueError, TypeError, ArithmeticError) as exc:
            shear_error = str(exc)
        vrs[axis] = vr
        checks[f"shear_{axis}"] = _check(f"shear_{axis}", samples, lambda s, a=axis: abs(s[f"shear_{a}"]),
            vr, {**parameters, "Lv_m": lv}, shear_steps, "ABNT NBR 8800:2024, 5.4.3.6", shear_error)

    # Pure torsion capacity, using the actual length of the verification element.
    length = sum(dist(tuple(getattr(model.nodes[m.start_node], k) for k in ("x", "y", "z")),
                      tuple(getattr(model.nodes[m.end_node], k) for k in ("x", "y", "z"))) for m in members)
    wt = pi*(p["D_mm"]-p["t_mm"])**2*p["t_mm"]/2000
    t1 = 1.23*wt*e/(ratio**1.25*sqrt(length*1000/p["D_mm"]))
    t2 = .60*wt*e/ratio**1.5
    tr = min(max(t1, t2), .60*wt*fy)/1.1
    torsion_steps = [step("W_T", r"\pi(D-t)^2t/2", f"\\pi({number(p['D_mm']/10)}-{number(p['t_mm']/10)})^2\\cdot {number(p['t_mm']/10)}/2", wt, "cm^3", "5.5.2.1.2"),
                     step("T_{n1}", r"\dfrac{1{,}23W_TE}{(D/t)^{5/4}\sqrt{L/D}}", rf"\dfrac{{1{{,}}23\cdot {number(wt)}\cdot {number(e)}}}{{{number(ratio)}^{{5/4}}\sqrt{{{number(length*1000)}/{number(p['D_mm'])}}}}}", t1, "kN\\,cm", "5.5.2.1.2"),
                     step("T_{n2}", r"0{,}60W_TE/(D/t)^{3/2}", f"0{{,}}60\\cdot {number(wt)}\\cdot {number(e)}/{number(ratio)}^{{3/2}}", t2, "kN\\,cm", "5.5.2.1.2"),
                     step("T_{Rd}", r"\min(\max(T_{n1};T_{n2});0{,}60W_Tf_y)/1{,}10", f"\\min(\\max({number(t1)};{number(t2)});{number(.6*wt*fy)})/1{{,}}10", tr, "kN\\,cm", "5.5.2.1.2")]
    checks["torsion"] = _check("torsion", samples, lambda s: abs(s["torque"])*100, tr,
                                {**parameters, "length_m": length, "WT_cm3": wt}, torsion_steps,
                                "ABNT NBR 8800:2024, 5.5.2.1.2")

    checks.update(interactions(samples, parameters, nt, nc, {"y": mr, "z": mr}, vrs, tr,
                               tension_error, compression_error))
    return checks
