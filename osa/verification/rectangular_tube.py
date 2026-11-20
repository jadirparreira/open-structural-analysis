"""NBR 8800:2024 checks for rounded rectangular and square hollow sections."""

from __future__ import annotations

from math import isfinite, pi, sqrt

from osa.sections.properties import calculate_section_properties
from osa.verification.calculation_properties import calculation_property
from osa.verification.restraints import restraint_lengths
from osa.verification.steel_interactions import interactions
from osa.verification.structured_checks import NAMES, check, context, number, step

FAMILIES = {"Tubular Quadrado", "Tubular Retangular"}


def _plastic(width, height, radius):
    # Exact integral of |z| over a centered rounded rectangle.
    return width*height**2/4 - (4-pi)*height*radius**2/2 - (pi-10/3)*radius**3


def section(member):
    geom = member.geometry_dict()
    b, t = float(geom["b"]), float(geom["t"])
    h = b if member.section == "Tubular Quadrado" else float(geom["h"])
    if not all(isfinite(v) and v > 0 for v in (b, h, t)) or min(b, h) <= 4*t:
        raise ValueError("O tubular retangular requer b e h maiores que 4t, com dimensões finitas e positivas.")
    props = calculate_section_properties(member.section, geom)
    return {"b_mm": b, "h_mm": h, "t_mm": t, "Ag_cm2": props.area_cm2,
            "Iy_cm4": props.iy_cm4, "Iz_cm4": props.iz_cm4, "It_cm4": props.j_cm4,
            "Wy_cm3": props.iy_mm4/(h/2)/1000, "Wz_cm3": props.iz_mm4/(b/2)/1000,
            "Zy_cm3": (_plastic(b, h, 2*t)-_plastic(b-2*t, h-2*t, t))/1000,
            "Zz_cm3": (_plastic(h, b, 2*t)-_plastic(h-2*t, b-2*t, t))/1000,
            "ry_cm": sqrt(props.iy_cm4/props.area_cm2), "rz_cm": sqrt(props.iz_cm4/props.area_cm2)}


def effective_width(width, t, e, fy, chi):
    limit = 1.4*sqrt(e/fy)
    ratio = width/t
    if ratio <= limit/sqrt(chi):
        return width
    elastic = (1.38*limit/ratio)**2 * fy
    reduction = sqrt(elastic/(chi*fy))
    return min(width, max(0., width*(1-.2*reduction)*reduction))


def width_steps(width, t, e, fy, chi, symbol):
    limit, ratio = 1.4*sqrt(e/fy), width/t
    effective = effective_width(width, t, e, fy, chi)
    output = [step(rf"\lambda_{symbol}", f"{symbol}/t", f"{number(width)}/{number(t)}", ratio, "", "5.3.4.2"),
              step(rf"\lambda_{{lim,{symbol}}}", r"1{,}40\sqrt{E/f_y}", f"1{{,}}40\\sqrt{{{number(e)}/{number(fy)}}}", limit, "", "Tabela 4, grupo 1")]
    if ratio <= limit/sqrt(chi):
        output.append(step(f"{symbol}_{{ef}}", symbol, number(width), effective, "cm", "5.3.4.2, elemento integralmente efetivo"))
    else:
        elastic = (1.38*limit/ratio)**2*fy
        output.extend([step(rf"\sigma_{{el,{symbol}}}", rf"[1{{,}}38\lambda_{{lim,{symbol}}}/\lambda_{symbol}]^2f_y", f"[1{{,}}38\\cdot {number(limit)}/{number(ratio)}]^2\\cdot {number(fy)}", elastic, "kN/cm^2", "5.3.4.2; Tabela 5"),
                       step(f"{symbol}_{{ef}}", rf"{symbol}(1-0{{,}}20\sqrt{{\sigma_{{el,{symbol}}}/(\chi f_y)}})\sqrt{{\sigma_{{el,{symbol}}}/(\chi f_y)}}", f"{number(width)}(1-0{{,}}20\\sqrt{{{number(elastic)}/({number(chi)}\\cdot {number(fy)})}})\\sqrt{{{number(elastic)}/({number(chi)}\\cdot {number(fy)})}}", effective, "cm", "5.3.4.2; Tabela 5")])
    return output


def verify(element, model, results):
    try:
        _, p, e, g, fy, fu, samples = context(element, model, results, FAMILIES, section)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {key: {"status": "not_checked", "detail": str(exc), "critical_check": name}
                for key, name in NAMES.items()}
    b, h, t = (p[k]/10 for k in ("b_mm", "h_mm", "t_mm"))
    flat_b, flat_h, ag = b-4*t, h-4*t, p["Ag_cm2"]
    parameters = {**p, "E_kn_cm2": e, "G_kn_cm2": g, "fy_kn_cm2": fy, "fu_kn_cm2": fu,
                  "flat_b_cm": flat_b, "flat_h_cm": flat_h}
    checks = {}
    nt, tension_error, tension_steps = None, None, []
    try:
        an = calculation_property(model, element, "An", None)
        ct = calculation_property(model, element, "Ct", None)
        if an is None or ct is None:
            raise ValueError("Informe An (cm²) e Ct conforme os furos e a transmissão de força da ligação.")
        if not 0 < an <= ag or not 0 < ct <= 1:
            raise ValueError("An deve estar entre zero e Ag; Ct deve estar entre zero e 1.")
        nt = min(ag*fy/1.1, ct*an*fu/1.35)
        parameters.update(An_cm2=an, Ct=ct)
        tension_steps = [step("N_{t,Rd1}", r"A_gf_y/1{,}10", f"{number(ag)}\\cdot {number(fy)}/1{{,}}10", ag*fy/1.1, "kN", "5.2.2(a)"),
                         step("N_{t,Rd2}", r"C_tA_nf_u/1{,}35", f"{number(ct)}\\cdot {number(an)}\\cdot {number(fu)}/1{{,}}35", ct*an*fu/1.35, "kN", "5.2.2(b)"),
                         step("N_{t,Rd}", r"\min(N_{t,Rd1};N_{t,Rd2})", f"\\min({number(ag*fy/1.1)};{number(ct*an*fu/1.35)})", nt, "kN", "5.2.2")]
    except (ValueError, TypeError) as exc:
        tension_error = str(exc)
    checks["axial_tension"] = check("axial_tension", samples, lambda s: max(0., -s["axial"]), nt,
        parameters.copy(), tension_steps, "ABNT NBR 8800:2024, 5.2", tension_error)

    nc, compression_error, compression_steps, lengths = None, None, [], None
    try:
        lengths = restraint_lengths(model, element, results, {"Iy": p["Iy_cm4"], "tw": t})
        ly, lz = (lengths.lengths_m[k]*100 for k in ("Ly", "Lz"))
        if min(ly, lz) <= 0:
            raise ValueError("Comprimentos de flambagem inválidos.")
        ney, nez = pi*pi*e*p["Iy_cm4"]/ly**2, pi*pi*e*p["Iz_cm4"]/lz**2
        ne = min(ney, nez)
        net_lower = g*p["It_cm4"]/((p["Iy_cm4"]+p["Iz_cm4"])/ag)
        if net_lower < ne:
            raise ValueError("A parcela GJ/r0² é inferior à flambagem por flexão; é necessário determinar Cw para conferir a instabilidade por torção.")
        lam = sqrt(ag*fy/ne)
        chi = .658**lam**2 if lam <= 1.5 else .877/lam**2
        bef, hef = (effective_width(v, t, e, fy, chi) for v in (flat_b, flat_h))
        aef = ag-2*t*(flat_b-bef+flat_h-hef)
        nc = chi*aef*fy/1.1
        parameters.update(Aef_cm2=aef, chi=chi, lambda0=lam, Ne_kn=ne,
                          Ly_cm=ly, Lz_cm=lz, Lt_cm=lengths.lengths_m["Lt"]*100,
                          Lb_cm=lengths.lengths_m["Lb"]*100,
                          restraint_notes=tuple(lengths.notes), restraint_issues=tuple(lengths.issues))
        compression_steps = [step("N_{ey}", r"\pi^2EI_y/L_y^2", f"\\pi^2\\cdot {number(e)}\\cdot {number(p['Iy_cm4'])}/{number(ly)}^2", ney, "kN", "5.3.5.1"),
                             step("N_{ez}", r"\pi^2EI_z/L_z^2", f"\\pi^2\\cdot {number(e)}\\cdot {number(p['Iz_cm4'])}/{number(lz)}^2", nez, "kN", "5.3.5.1"),
                             step("N_e", r"\min(N_{ey};N_{ez})\quad(GJ/r_0^2\geq N_e)", f"\\min({number(ney)};{number(nez)})", ne, "kN", "5.3.5.1"),
                             step(r"\lambda_0", r"\sqrt{A_gf_y/N_e}", f"\\sqrt{{{number(ag)}\\cdot {number(fy)}/{number(ne)}}}", lam, "", "5.3.3.2"),
                             step(r"\chi", r"0{,}658^{\lambda_0^2}" if lam<=1.5 else r"0{,}877/\lambda_0^2", f"0{{,}}658^{{{number(lam)}^2}}" if lam<=1.5 else f"0{{,}}877/{number(lam)}^2", chi, "", "5.3.3.1"),
                             *width_steps(flat_b, t, e, fy, chi, "b"),
                             *width_steps(flat_h, t, e, fy, chi, "h"),
                             step("A_{ef}", r"A_g-2t[(b-b_{ef})+(h-h_{ef})]", f"{number(ag)}-2\\cdot {number(t)}[({number(flat_b)}-{number(bef)})+({number(flat_h)}-{number(hef)})]", aef, "cm^2", "5.3.4"),
                             step("N_{c,Rd}", r"\chi A_{ef}f_y/1{,}10", f"{number(chi)}\\cdot {number(aef)}\\cdot {number(fy)}/1{{,}}10", nc, "kN", "5.3.2")]
    except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
        compression_error = str(exc)
    checks["axial_compression"] = check("axial_compression", samples, lambda s: max(0., s["axial"]), nc,
        parameters.copy(), compression_steps, "ABNT NBR 8800:2024, 5.3", compression_error)

    moments = {}
    for axis, flange, web, depth in (("y", flat_b, flat_h, h), ("z", flat_h, flat_b, b)):
        mr, error, steps = None, None, []
        try:
            z, w, inertia = p[f"Z{axis}_cm3"], p[f"W{axis}_cm3"], p[f"I{axis}_cm4"]
            mp = z*fy
            lf, lw = flange/t, web/t
            lp, lr = 1.12*sqrt(e/fy), 1.4*sqrt(e/fy)
            steps.extend([step(r"\lambda_{FLM}", "b/t", f"{number(flange)}/{number(t)}", lf, "", "D.2.7"),
                          step(r"\lambda_{p,FLM}", r"1{,}12\sqrt{E/f_y}", f"1{{,}}12\\sqrt{{{number(e)}/{number(fy)}}}", lp, "", "D.2.7"),
                          step(r"\lambda_{r,FLM}", r"1{,}40\sqrt{E/f_y}", f"1{{,}}40\\sqrt{{{number(e)}/{number(fy)}}}", lr, "", "D.2.7")])
            if lf <= lp:
                mflm = mp
                flm_formula, flm_sub = "Zf_y", f"{number(z)}\\cdot {number(fy)}"
            elif lf <= lr:
                mflm = min(mp, mp-(mp-fy*w)*(3.57*lf*sqrt(fy/e)-4))
                flm_formula = r"M_{pl}-(M_{pl}-f_yW)(3{,}57\lambda\sqrt{f_y/E}-4)\leq M_{pl}"
                flm_sub = f"{number(mp)}-({number(mp)}-{number(fy*w)})(3{{,}}57\\cdot {number(lf)}\\sqrt{{{number(fy)}/{number(e)}}}-4)"
            else:
                effective = effective_width(flange, t, e, fy, 1.)
                removed = (flange-effective)*t
                area_eff = ag-removed
                offset = (depth-t)/2
                centroid = -removed*offset/area_eff
                inertia_eff = inertia-((flange-effective)*t**3/12+removed*offset**2)-area_eff*centroid**2
                wef = inertia_eff/(depth/2+abs(centroid))
                mflm = fy*wef
                flm_formula, flm_sub = "f_yW_{ef}", f"{number(fy)}\\cdot {number(wef)}"
                steps.extend(width_steps(flange, t, e, fy, 1., "b"))
                steps.extend([
                    step("A_{rem}", "(b-b_{ef})t", f"({number(flange)}-{number(effective)}){number(t)}", removed, "cm^2", "D.2.7"),
                    step("A_{ef}", "A_g-A_{rem}", f"{number(ag)}-{number(removed)}", area_eff, "cm^2", "D.2.7"),
                    step("z_{rem}", "(H-t)/2", f"({number(depth)}-{number(t)})/2", offset, "cm", "D.2.7"),
                    step("z_{ef}", "-A_{rem}z_{rem}/A_{ef}", f"-{number(removed)}\\cdot {number(offset)}/{number(area_eff)}", centroid, "cm", "D.2.7"),
                    step("I_{ef}", "I-(b-b_{ef})t^3/12-A_{rem}z_{rem}^2-A_{ef}z_{ef}^2",
                         f"{number(inertia)}-({number(flange)}-{number(effective)}){number(t)}^3/12-{number(removed)}\\cdot {number(offset)}^2-{number(area_eff)}\\cdot {number(centroid)}^2", inertia_eff, "cm^4", "D.2.7"),
                ])
                steps.append(step("W_{ef}", r"I_{ef}/c_{max}", f"{number(inertia_eff)}/{number(depth/2+abs(centroid))}", wef, "cm^3", "D.2.7; 5.3.4.2"))
            if lw > 5.70*sqrt(e/fy):
                raise ValueError("Alma esbelta: o procedimento do Anexo D não é aplicável; é necessária a verificação pelo Anexo E.")
            mfla = mp if lw <= 2.42*sqrt(e/fy) else min(mp, mp-(mp-fy*w)*(.305*lw*sqrt(fy/e)-.738))
            steps.extend([step(r"\lambda_{FLA}", "h/t", f"{number(web)}/{number(t)}", lw, "", "D.2.7"),
                          step(r"\lambda_{p,FLA}", r"2{,}42\sqrt{E/f_y}", f"2{{,}}42\\sqrt{{{number(e)}/{number(fy)}}}", 2.42*sqrt(e/fy), "", "D.2.7"),
                          step(r"\lambda_{r,FLA}", r"5{,}70\sqrt{E/f_y}", f"5{{,}}70\\sqrt{{{number(e)}/{number(fy)}}}", 5.7*sqrt(e/fy), "", "D.2.7")])
            fla_formula = "Zf_y" if lw <= 2.42*sqrt(e/fy) else r"M_{pl}-(M_{pl}-f_yW)(0{,}305\lambda\sqrt{f_y/E}-0{,}738)\leq M_{pl}"
            fla_sub = f"{number(z)}\\cdot {number(fy)}" if lw <= 2.42*sqrt(e/fy) else f"{number(mp)}-({number(mp)}-{number(fy*w)})(0{{,}}305\\cdot {number(lw)}\\sqrt{{{number(fy)}/{number(e)}}}-0{{,}}738)"
            mflt = mp
            if inertia >= p["Iz_cm4" if axis == "y" else "Iy_cm4"]:
                if lengths is None:
                    raise ValueError("Comprimento Lb indisponível para FLT.")
                lb = lengths.lengths_m["Lb"]*100
                rminor = p["rz_cm" if axis == "y" else "ry_cm"]
                cb = calculation_property(model, element, "Cb", 1.)
                slenderness = lb/rminor
                root = sqrt(p["It_cm4"]*ag)
                lpflt, lrflt = .13*e*root/mp, 2*e*cb*root/(.7*fy*w)
                if slenderness <= lpflt:
                    mflt = mp
                    flt_formula, flt_sub = "Zf_y", f"{number(z)}\\cdot {number(fy)}"
                elif slenderness <= lrflt:
                    mflt = mp-(mp-.7*fy*w)*(slenderness-lpflt)/(lrflt-lpflt)
                    flt_formula = r"M_{pl}-(M_{pl}-M_r)\dfrac{\lambda-\lambda_p}{\lambda_r-\lambda_p}"
                    flt_sub = rf"{number(mp)}-({number(mp)}-{number(.7*fy*w)})\dfrac{{{number(slenderness)}-{number(lpflt)}}}{{{number(lrflt)}-{number(lpflt)}}}"
                else:
                    mflt = 2*e*cb*root/slenderness
                    flt_formula = r"\dfrac{2EC_b\sqrt{JA_g}}{\lambda}"
                    flt_sub = rf"\dfrac{{2\cdot {number(e)}\cdot {number(cb)}\cdot {number(root)}}}{{{number(slenderness)}}}"
                steps.extend([step(r"\lambda_{FLT}", "L_b/r_{minor}", f"{number(lb)}/{number(rminor)}", slenderness, "", "Tabela D.1; D.2.8(g)"),
                              step(r"\lambda_{p,FLT}", r"0{,}13E\sqrt{JA_g}/M_{pl}", f"0{{,}}13\\cdot {number(e)}\\cdot {number(root)}/{number(mp)}", lpflt, "", "Tabela D.1"),
                              step(r"\lambda_{r,FLT}", r"2EC_b\sqrt{JA_g}/(0{,}70f_yW)", f"2\\cdot {number(e)}\\cdot {number(cb)}\\cdot {number(root)}/{number(.7*fy*w)}", lrflt, "", "Tabela D.1; D.2.8(e)"),
                              step("M_{n,FLT}", flt_formula, flt_sub, mflt, "kN\\,cm", "D.2.1; Tabela D.1")])
            capacities = {"FLM": mflm, "FLA": mfla, "FLT": mflt, "limite 1,5 W fy": 1.5*w*fy}
            mr = min(capacities.values())/1.1
            steps.extend([step("M_{n,FLM}", flm_formula, flm_sub, mflm, "kN\\,cm", "D.2.7"),
                          step("M_{n,FLA}", fla_formula, fla_sub, mfla, "kN\\,cm", "D.2.7"),
                          step("M_{Rd}", r"\dfrac{\min(M_{n,FLM};M_{n,FLA};M_{n,FLT};1{,}5Wf_y)}{1{,}10}", f"\\dfrac{{\\min({number(mflm)};{number(mfla)};{number(mflt)};{number(1.5*w*fy)})}}{{1{{,}}10}}", mr, "kN\\,cm", "5.4.2.2; D.2.7")])
        except (KeyError, ValueError, TypeError, ArithmeticError) as exc:
            error = str(exc)
        moments[axis] = mr
        checks[f"flexion_{axis}"] = check(f"flexion_{axis}", samples, lambda s, a=axis: abs(s[f"moment_{a}"])*100,
            mr, {**parameters, **({"governing": min(capacities, key=capacities.get)} if mr is not None else {})}, steps, "ABNT NBR 8800:2024, D.2.7; Tabela D.1", error)

    shears = {}
    for axis, web in (("y", flat_b), ("z", flat_h)):
        slenderness = web/t
        lp, lr = 1.10*sqrt(5*e/fy), 1.37*sqrt(5*e/fy)
        factor = 1. if slenderness<=lp else lp/slenderness if slenderness<=lr else 1.24*(lp/slenderness)**2
        aw = 2*web*t
        vr = .6*aw*fy*factor/1.1
        shears[axis] = vr
        steps = [step("A_w", "2ht", f"2\\cdot {number(web)}\\cdot {number(t)}", aw, "cm^2", "5.4.3.2"),
                 step(r"\lambda_v", "h/t", f"{number(web)}/{number(t)}", slenderness, "", "5.4.3.1.1"),
                 step(r"\lambda_{p,v}", r"1{,}10\sqrt{5E/f_y}", f"1{{,}}10\\sqrt{{5\\cdot {number(e)}/{number(fy)}}}", lp, "", "5.4.3.2"),
                 step(r"\lambda_{r,v}", r"1{,}37\sqrt{5E/f_y}", f"1{{,}}37\\sqrt{{5\\cdot {number(e)}/{number(fy)}}}", lr, "", "5.4.3.2"),
                 step(r"\rho_v", "1" if slenderness<=lp else r"\lambda_p/\lambda" if slenderness<=lr else r"1{,}24(\lambda_p/\lambda)^2", "1" if slenderness<=lp else f"{number(lp)}/{number(slenderness)}" if slenderness<=lr else f"1{{,}}24({number(lp)}/{number(slenderness)})^2", factor, "", "5.4.3.1.1"),
                 step("V_{Rd}", r"0{,}60A_wf_y\rho_v/1{,}10", f"0{{,}}60\\cdot {number(aw)}\\cdot {number(fy)}\\cdot {number(factor)}/1{{,}}10", vr, "kN", "5.4.3.1.1; 5.4.3.2")]
        checks[f"shear_{axis}"] = check(f"shear_{axis}", samples, lambda s, a=axis: abs(s[f"shear_{a}"]), vr,
            {**parameters, "lambda_v": slenderness, "lambda_p_v": lp, "lambda_r_v": lr}, steps,
            "ABNT NBR 8800:2024, 5.4.3.2")

    ht = max(flat_b, flat_h)/t
    wt = 2*(b-t)*(h-t)*t-4.5*(4-pi)*t**3
    if ht > 260:
        tn = None
        tn_formula = tn_sub = None
    elif ht <= 2.45*sqrt(e/fy):
        tn = .6*wt*fy
        tn_formula, tn_sub = r"0{,}60W_Tf_y", f"0{{,}}60\\cdot {number(wt)}\\cdot {number(fy)}"
    elif ht <= 3.07*sqrt(e/fy):
        tn = .6*wt*fy*2.45*sqrt(e/fy)/ht
        tn_formula = r"0{,}60W_Tf_y\dfrac{2{,}45\sqrt{E/f_y}}{h/t}"
        tn_sub = rf"0{{,}}60\cdot {number(wt)}\cdot {number(fy)}\dfrac{{2{{,}}45\sqrt{{{number(e)}/{number(fy)}}}}}{{{number(ht)}}}"
    else:
        tn = .46*pi*pi*wt*e/ht**2
        tn_formula = r"0{,}46\pi^2W_TE/(h/t)^2"
        tn_sub = f"0{{,}}46\\pi^2\\cdot {number(wt)}\\cdot {number(e)}/{number(ht)}^2"
    tr = tn/1.1 if tn is not None else None
    steps = [step("W_T", r"2(b-t)(h-t)t-4{,}5(4-\pi)t^3", f"2({number(b)}-{number(t)})({number(h)}-{number(t)}){number(t)}-4{{,}}5(4-\\pi){number(t)}^3", wt, "cm^3", "5.5.2.1.3")]
    if tn is not None:
        steps.extend([step("T_n", tn_formula, tn_sub, tn, "kN\\,cm", "5.5.2.1.3"),
             step("T_{Rd}", r"T_n/1{,}10", f"{number(tn)}/1{{,}}10", tr, "kN\\,cm", "5.5.2.1.3")])
    checks["torsion"] = check("torsion", samples, lambda s: abs(s["torque"])*100, tr, parameters.copy(), steps,
        "ABNT NBR 8800:2024, 5.5.2.1.3", "h/t supera 260: fora do campo de 5.5.2.1.3." if tr is None else None)
    checks.update(interactions(samples, parameters, nt, nc, moments, shears, tr if tr else float("inf"), tension_error, compression_error))
    return checks
