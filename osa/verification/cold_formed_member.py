"""Open cold-formed members, ABNT NBR 14762:2010.

Global criticals use supplied effective lengths or an external analysis.
Local and distortional criticals use the elastic finite-strip solver, unless
an external override or a justified modal absence is present. Boundary
conditions are explicit; no Euler surrogate replaces plate buckling.
"""
from __future__ import annotations

from math import isfinite, pi, sqrt, tan

from osa.analysis.vlasov import VLASOV_ALGORITHM
from osa.sections.geometry import section_shape
from osa.sections.properties import calculate_section_properties
from osa.sections.thin_walled import open_sheet
from osa.verification.calculation_properties import calculation_property
from osa.verification.cold_formed import direct_resistance, tension_resistance
from osa.verification.cold_formed_fsm import critical_minimum
from osa.verification.cold_formed_global import bending_critical, compression_critical, global_section
from osa.verification.cold_formed_local import bearing_checks, web_shear_shares
from osa.verification.cold_formed_service import service_checks, shear_center_offsets
from osa.verification.cold_formed_stability import stability_procedure
from osa.verification.restraints import restraint_lengths
from osa.verification.structured_checks import NAMES, check, context, number, step

FAMILIES = frozenset({"U Formado", "C Formado", "Z Formado", "Z45 Formado", "Z90 Formado",
                      "L Formado", "Cartola Formado"})
REFERENCE = "ABNT NBR 14762:2010"


def section(member):
    geometry = member.geometry_dict()
    props = calculate_section_properties(member.section, geometry, mirror_z=member.section_mirrored)
    shape = section_shape(member.section, geometry, arc_steps=64, mirror_z=member.section_mirrored)
    if shape is None:
        raise ValueError("Contorno indisponível.")
    det = props.iy_mm4*props.iz_mm4 - props.iyz_mm4**2
    points = shape.loops[0]
    # Full unsymmetrical elastic bending; Iyz cannot be discarded for Z/L.
    wy = det/max(abs(props.iz_mm4*z - props.iyz_mm4*y) for y, z in points)
    wz = det/max(abs(props.iy_mm4*y - props.iyz_mm4*z) for y, z in points)
    return {**{key+"_mm": float(value) for key, value in geometry.items()},
            "r_mm": float(geometry["r"]) if member.section in {"Z45 Formado", "Z90 Formado"} else float(geometry["t"]),
            "Ag_cm2": props.area_cm2, "Iy_cm4": props.iy_cm4, "Iz_cm4": props.iz_cm4,
            "Iyz_cm4": props.iyz_mm4/10000, "I1_cm4": props.i_major_mm4/10000,
            "I2_cm4": props.i_minor_mm4/10000, "alpha_deg": props.principal_axis_angle_deg,
            "Wy_cm3": wy/1000, "Wz_cm3": wz/1000, "It_cm4": props.j_cm4,
            "ry_cm": sqrt(props.iy_cm4/props.area_cm2), "rz_cm": sqrt(props.iz_cm4/props.area_cm2)}


def _torsional_demand(row, depth_m):
    # Opposing Saint-Venant/warping torques may cancel in total T while
    # their shear stresses remain nonzero; B alone is also a real action.
    return max(*(abs(row.get(key, 0.)) for key in
                 ('torque', 'torque_sc', 'saint_venant_torque', 'warping_torque', 'unresolved_eccentric_torque')),
               abs(row.get('bimoment', 0.))/depth_m)


def _width_scope(member, p, *, bending=False):
    """Maximum plate slenderness before MRD, NBR 14762 9.1.2/Table 4.

    The model contains no transverse web stiffeners. Simple Z compression
    shares the conservative supported range of the unstiffened channel web;
    extending that range requires a specific plate-restraint justification.
    """
    t, d, bf = p["t_mm"], p["d_mm"], p["bf_mm"]
    r = p.get("r_mm", t)
    web = d-2*(r+t)
    family = member.section
    if family == "L Formado":
        plates = [("aba vertical AL", d-2*t, 60), ("aba horizontal AL", bf-2*t, 60)]
    elif family == "Cartola Formado":
        plates = [("alma", web, 200 if bending else 90),
                  ("mesa central AA", bf-4*t, 500), ("aba livre AL", p["c_mm"]-t, 60)]
    else:
        stiffened = family in {"C Formado", "Z45 Formado", "Z90 Formado"}
        web_limit = 200 if bending else 500 if stiffened else 90
        if family in {"Z45 Formado", "Z90 Formado"}:
            angle = pi/4 if family == "Z45 Formado" else pi/2
            radius = r+t/2
            bm = bf-t/sqrt(2) if family == "Z45 Formado" else bf-t
            cm = p["c_mm"]-(sqrt(2)-1)*t/2 if family == "Z45 Formado" else p["c_mm"]-t/2
            flange = bm-radius*(1+tan(angle/2))
            lip = cm-radius*tan(angle/2)
        else:
            flange = bf-r if family == "Z Formado" else bf-4*t if stiffened else bf-2*t
            lip = p.get("c_mm", 0)-t
        plates = [("alma", web, web_limit), ("mesa", flange, 60)]
        if stiffened:
            plates.append(("enrijecedor de borda", lip, 60))
    exceeded = [f"{name}: b/t={number(width/t).replace('{,}', ',')} > {limit}"
                for name, width, limit in plates if width/t > limit]
    if exceeded:
        return "Fora do intervalo de relações largura/espessura coberto pela rotina (9.1.2, Tabela 4): " + "; ".join(exceeded) + ". Não se extrapola o MRD além desse intervalo."
    return None


def _mrd_steps(result, yield_load, criticals, bending, factor, fy):
    n = number
    letter, unit, ref = ("M", "kN·cm", "C.4") if bending else ("N", "kN", "C.3")
    y = letter+"_y"
    re, rl, rd = (letter+"_{Re}", letter+"_{Rl}", letter+"_{Rdist}")
    s = [step(y, "W f_y" if bending else "A_g f_y", rf"{n(factor)}\cdot {n(fy)}", yield_load, unit, ref)]
    for sub, value in zip(("e", "l", "dist"), criticals, strict=True):
        if value is not None:
            symbol = letter+"_{"+sub+"}"
            s.append(step(symbol, symbol, n(value), value, unit, "C.2 — análise elástica geral"))
    l0, ll, ld = result.lambda_global, result.lambda_local, result.lambda_distortional
    terms, values = [y], [yield_load]
    if criticals[0] is not None:
        s.append(step(r"\lambda_0", rf"\sqrt{{{y}/{letter}_e}}", rf"\sqrt{{{n(yield_load)}/{n(criticals[0])}}}", l0, "", ref+".1"))
        if bending:
            formula, sub = ((y, n(yield_load)) if l0 <= .6 else
                (rf"1{{,}}11(1-0{{,}}278\lambda_0^2){y}", rf"1{{,}}11(1-0{{,}}278\cdot {n(l0)}^2)\cdot {n(yield_load)}") if l0 < 1.336 else
                (rf"{y}/\lambda_0^2", rf"{n(yield_load)}/{n(l0)}^2"))
        else:
            formula, sub = ((rf"0{{,}}658^{{\lambda_0^2}}{y}", rf"0{{,}}658^{{{n(l0)}^2}}\cdot {n(yield_load)}") if l0 <= 1.5 else
                (rf"0{{,}}877 {y}/\lambda_0^2", rf"0{{,}}877\cdot {n(yield_load)}/{n(l0)}^2"))
        s.append(step(re, formula, sub, result.global_characteristic, unit, ref+".1"))
        terms.append(re)
        values.append(result.global_characteristic)
    if criticals[1] is not None:
        baseline = re if criticals[0] is not None else y
        s.append(step(r"\lambda_l", rf"\sqrt{{{baseline}/{letter}_l}}", rf"\sqrt{{{n(result.global_characteristic)}/{n(criticals[1])}}}", ll, "", ref+".2"))
        s.append(step(rl, baseline if ll <= .776 else rf"(1-0{{,}}15/\lambda_l^{{0{{,}}8}}){baseline}/\lambda_l^{{0{{,}}8}}",
                      n(result.global_characteristic) if ll <= .776 else rf"(1-0{{,}}15/{n(ll)}^{{0{{,}}8}}){n(result.global_characteristic)}/{n(ll)}^{{0{{,}}8}}",
                      result.local_characteristic, unit, ref+".2"))
        terms.append(rl)
        values.append(result.local_characteristic)
    if criticals[2] is not None:
        limit, coefficient, exponent = (.673, .22, 1) if bending else (.561, .25, 1.2)
        s.append(step(r"\lambda_{dist}", rf"\sqrt{{{y}/{letter}_{{dist}}}}", rf"\sqrt{{{n(yield_load)}/{n(criticals[2])}}}", ld, "", ref+".3"))
        exp = n(exponent)
        s.append(step(rd, y if ld <= limit else rf"(1-{n(coefficient)}/\lambda_{{dist}}^{{{exp}}}){y}/\lambda_{{dist}}^{{{exp}}}",
                      n(yield_load) if ld <= limit else rf"(1-{n(coefficient)}/{n(ld)}^{{{exp}}}){n(yield_load)}/{n(ld)}^{{{exp}}}",
                      result.distortional_characteristic, unit, ref+".3"))
        terms.append(rd)
        values.append(result.distortional_characteristic)
    gamma = 1.1 if bending else 1.2
    s.append(step(letter+"_{Rd}", r"\min("+";".join(terms)+")/"+n(gamma),
                  r"\min("+";".join(n(v) for v in values)+")/"+n(gamma), result.resistance, unit, ref))
    return s


def _slenderness(element, model, results, samples, p, tension_check):
    """Check 9.7.4 independently of MRD; attach 9.6.3 as an advisory.

    Effective compression lengths are supplied in the principal axes. The
    geometric restraint estimates do not determine K and cannot replace KL.
    """
    r1, r2 = (sqrt(p[key] / p["Ag_cm2"]) for key in ("I1_cm4", "I2_cm4"))
    params = {**p, "r1_cm": r1, "r2_cm": r2}
    radius_steps = [step("r_"+axis, r"\sqrt{I_"+axis+r"/A_g}",
                         rf"\sqrt{{{number(p['I'+axis+'_cm4'])}/{number(p['Ag_cm2'])}}}",
                         radius, "cm", "9.7.4") for axis, radius in (("1", r1), ("2", r2))]
    applied, error, steps = None, None, radius_steps.copy()
    has_compression = any(s["axial"] > 1e-6 for _, _, s in samples)
    if has_compression:
        try:
            lengths = [calculation_property(model, element, "KL"+axis, None) for axis in ("1", "2")]
            if any(value is None for value in lengths):
                raise ValueError("Informe K₁L₁ e K₂L₂ (m), comprimentos efetivos nos eixos principais, para KL/r ≤ 200 (9.7.4). O comprimento geométrico não determina K.")
            if not all(isfinite(value) and value > 0 for value in lengths):
                raise ValueError("K₁L₁ e K₂L₂ devem ser finitos e positivos.")
            ratios = [length*100/radius for length, radius in zip(lengths, (r1, r2), strict=True)]
            applied = max(ratios)
            params.update(KL1_m=lengths[0], KL2_m=lengths[1], lambda_1=ratios[0], lambda_2=ratios[1])
            for axis, length, radius, ratio in zip(("1", "2"), lengths, (r1, r2), ratios, strict=True):
                steps.extend([
                    step("K_"+axis+"L_"+axis, "K_"+axis+"L_"+axis, number(length*100), length*100, "cm", "9.7.4"),
                    step(r"\lambda_"+axis, "K_"+axis+"L_"+axis+"/r_"+axis,
                         f"{number(length*100)}/{number(radius)}", ratio, "", "9.7.4"),
                ])
        except (TypeError, ValueError) as exc:
            error = str(exc)
    compression = check("axial_compression", samples,
        lambda s: (applied if applied is not None else 1.) if s["axial"] > 1e-6 else 0.,
        200., params, steps, REFERENCE+", 9.7.4", error)
    compression["critical_check"] = "Esbeltez de compressão"

    if any(s["axial"] < -1e-6 for _, _, s in samples):
        advisories = []
        try:
            lengths = restraint_lengths(model, element, results, {})
            ly, lz = (lengths.lengths_m[key]*100 for key in ("Ly", "Lz"))
            if not all(isfinite(value) and value > 0 for value in (ly, lz)):
                raise ValueError("Comprimentos destravados inválidos.")
            # When the principal axes are inclined, directional geometric
            # restraints cannot be projected into principal restraints.
            inclined = abs(p["Iyz_cm4"]) > 1e-9*sqrt(p["Iy_cm4"]*p["Iz_cm4"])
            ratio = (max(ly, lz)/r2 if inclined else max(ly/p["ry_cm"], lz/p["rz_cm"]))
            tension_check["parameters"].update(tension_slenderness=ratio, tension_slenderness_limit=300.,
                                              tension_Ly_cm=ly, tension_Lz_cm=lz)
            formula = r"\max(L_y;L_z)/r_2" if inclined else r"\max(L_y/r_y;L_z/r_z)"
            substitution = (rf"\max({number(ly)};{number(lz)})/{number(r2)}" if inclined else
                            rf"\max({number(ly)}/{number(p['ry_cm'])};{number(lz)}/{number(p['rz_cm'])})")
            tension_check["steps"].append(step(r"\lambda_t", formula, substitution, ratio, "", "9.6.3"))
            advisories.append(f"Recomendação de tração (9.6.3): L/r = {ratio:.6g}; limite recomendado 300. "
                              + ("Acima do recomendado; não altera a resistência à tração." if ratio > 300 else "Dentro do recomendado."))
            if inclined:
                advisories.append("Eixos principais inclinados: L/r estimado conservadoramente com max(Ly,Lz)/r₂; contenções geométricas não são convertidas em contenções principais.")
            advisories.append("Comprimentos destravados estimados geometricamente ou informados em Ly/Lz; a estimativa não verifica rigidez, resistência ou ancoragem das contenções.")
        except (TypeError, ValueError) as exc:
            advisories.append("Recomendação de esbeltez de tração não avaliada: " + str(exc))
        tension_check["parameters"]["advisories"] = tuple(advisories)
    return compression


def _automatic_mode_critical(family, geometry, E_kn_cm2, mirrored, load, mode, *, nu=.3):
    """Return an elastic critical load/moment from the mode signature curve.

    Axial results are returned in kN, moments in kN·m. Bending envelopes
    include both signs because the formed section and restraint may be
    asymmetric.
    """
    governing = critical_minimum(family, geometry, E=E_kn_cm2*10., nu=nu, mirror=mirrored, load=load, mode=mode)
    if governing is None:
        return None
    return (governing.value / (1000.0 if load == "N" else 1_000_000.0),
            governing.half_wave_mm)


def verify(element, model, results, *, stability_check=None):
    try:
        members, p, e, g, fy, fu, samples = context(element, model, results, FAMILIES, section)
        for result in results:
            for member in members:
                analysis = result.member_results.get(member.name, {}).get('warping_analysis', {})
                if model.warping_analysis or analysis:
                    basis = 'rounded-angle-saint-venant-v1' if member.section == 'L Formado' else 'rounded-mean-line-v1'
                    if analysis.get('status') != 'solved' or analysis.get('geometry_basis') != basis or analysis.get('algorithm') != VLASOV_ALGORITHM:
                        raise ValueError('O modelo requer a solução 7GL com a base geométrica atual; processe novamente a análise com empenamento.')
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return {key: {"status": "not_checked", "detail": str(exc), "critical_check": name}
                for key, name in NAMES.items()}
    if fu/fy < 1.08:
        return {key: {"status": "not_checked", "detail": "fu/fy inferior a 1,08: material fora do requisito de 4.1.1 da NBR 14762:2010.", "critical_check": name}
                for key, name in NAMES.items()}
    parameters = {**p, "E_kn_cm2": e, "fy_kn_cm2": fy, "fu_kn_cm2": fu}
    methods = {}
    for result in results:
        for member in members:
            info = result.member_results.get(member.name, {}).get('structural_analysis')
            if info:
                methods[result.load_reference+' / '+member.name] = info
    parameters['analysis_methods'] = methods
    checks = {}
    nt, tension_error, tension_steps = None, None, []
    try:
        an, an0, ct = (calculation_property(model, element, key, None) for key in ("An", "An0", "Ct"))
        if any(value is None for value in (an, an0, ct)):
            raise ValueError("Informe An, An0 (cm²) e Ct conforme os furos e a ligação (9.6.2).")
        tension = tension_resistance(gross_area_cm2=p["Ag_cm2"], net_outside_cm2=an0,
            net_connection_cm2=an, fy_kn_cm2=fy, fu_kn_cm2=fu, ct=ct)
        nt = tension.resistance_kn
        parameters.update(An_cm2=an, An0_cm2=an0, Ct=ct, tension_governing=tension.governing)
        tension_steps = [
            step("N_{t,Rd1}", "A_g f_y/1{,}10", rf"{number(p['Ag_cm2'])}\cdot {number(fy)}/1{{,}}10", tension.gross_yield_kn, "kN", "9.6.2(a)"),
            step("N_{t,Rd2}", "A_{n0} f_u/1{,}35", rf"{number(an0)}\cdot {number(fu)}/1{{,}}35", tension.net_outside_connection_kn, "kN", "9.6.2(b)"),
            step("N_{t,Rd3}", "C_t A_n f_u/1{,}65", rf"{number(ct)}\cdot {number(an)}\cdot {number(fu)}/1{{,}}65", tension.net_at_connection_kn, "kN", "9.6.2(c)"),
            step("N_{t,Rd}", r"\min(N_{t,Rd1};N_{t,Rd2};N_{t,Rd3})", rf"\min({number(tension.gross_yield_kn)};{number(tension.net_outside_connection_kn)};{number(tension.net_at_connection_kn)})", nt, "kN", "9.6.2")]
    except (TypeError, ValueError) as exc:
        tension_error = str(exc)
    checks["axial_tension"] = check("axial_tension", samples, lambda s: max(-s["axial"], 0), nt,
        parameters.copy(), tension_steps, REFERENCE+", 9.6.2", tension_error)
    resistances, errors = {}, {}
    for mode, keys, yield_load, demand, bending in (
        ("axial_compression", ("NcrG", "NcrL", "NcrD"), p["Ag_cm2"]*fy, lambda s: max(s["axial"], 0), False),
        ("flexion_y", ("McrGy", "McrLy", "McrDy"), p["Wy_cm3"]*fy, lambda s: abs(s["moment_y"])*100, True),
        ("flexion_z", ("McrGz", "McrLz", "McrDz"), p["Wz_cm3"]*fy, lambda s: abs(s["moment_z"])*100, True),
    ):
        resistance, error, steps = None, None, []
        params = parameters.copy()
        if not any(demand(sample) > 1e-6 for _, _, sample in samples):
            checks[mode] = check(mode, samples, demand, None, params, [], REFERENCE,
                                 "Sem solicitação aplicável.")
            resistances[mode], errors[mode] = None, None
            continue
        try:
            geometry_error = _width_scope(members[0], p, bending=bending)
            if geometry_error:
                raise ValueError(geometry_error)
            values = [calculation_property(model, element, key, None) for key in keys]
            automatic_values = {}
            automatic_absence = {}
            if values[0] is None:
                kl = [calculation_property(model, element, key, None) for key in ("KL1", "KL2", "KLt")]
                if all(value is not None for value in kl):
                    physical = global_section(members[0].section, members[0].geometry_dict(), mirror=members[0].section_mirrored)
                    if not bending:
                        global_value, components = compression_critical(physical, e*10., g*10., *(value*1000 for value in kl))
                        values[0] = global_value/1000.
                        automatic_values[keys[0]] = {"value": values[0], "source": "estabilidade global por flexão, torção e flexo-torção (9.7.2)", **components}
                    elif calculation_property(model, element, "ForkSupports", None) == 1.:
                        global_value, sign = bending_critical(physical, e*10., g*10., kl[0]*1000, kl[2]*1000,
                            lb2=kl[1]*1000, moment_y=float(mode == "flexion_y"), moment_z=float(mode == "flexion_z"))
                        values[0] = global_value/1e6
                        automatic_values[keys[0]] = {"value": values[0], "sign": sign,
                            "source": "estabilidade elástica de Vlasov; garfos, empenamento livre e momento uniforme no centro de torção (C.2)"}
            if values[2] is None and open_sheet(members[0].section, members[0].geometry_dict()).distortional_dimension == 0:
                # 9.3 explicitly excludes distortional buckling for isolated
                # unstiffened channels. Panel restraint is a different model.
                values[2] = -1.
                automatic_absence["distorcional"] = ("U simples isolado: dispensado por 9.3; não se considera vínculo com painel."
                    if members[0].section == "U Formado" else
                    "Seção isolada sem graus de liberdade distorcionais no modelo de placas: dimensão GBT n_principais−4 nula (C.2). Não se considera vínculo com painel.")
            if values[1] is None or values[2] is None:
                load = "N" if not bending else "My" if mode == "flexion_y" else "Mz"
                geometry = members[0].geometry_dict()
                for index, mode_name in ((1, "local"), (2, "distorcional")):
                    if values[index] is None:
                        calculated = _automatic_mode_critical(
                            members[0].section, geometry, e, members[0].section_mirrored,
                            load, mode_name,
                            nu=float(model.materials[members[0].material][2]),
                        )
                        if calculated is not None:
                            values[index] = calculated[0]
                            automatic_values[keys[index]] = {
                                "value": calculated[0], "half_wave_mm": calculated[1],
                                "source": "assinatura elástica por faixas finitas",
                            }
            if any(v is None for v in values):
                missing = [key for key, value in zip(keys, values, strict=True) if value is None]
                missing_auto = [key for key in missing if key != keys[0]]
                messages = []
                if missing_auto:
                    messages.append(
                        "A análise automática por faixas finitas não identificou " + ", ".join(missing_auto)
                    )
                if keys[0] in missing:
                    messages.append(keys[0] + ": informe o crítico global ou KL1/KL2/KLt" + (" e confirme os vínculos de garfo para FLT" if bending else ""))
                raise ValueError("; ".join(messages) + ". É necessária análise geral de estabilidade elástica (Anexo C, C.2).")
            criticals = tuple(None if v == -1 else v*100 if bending else v for v in values)
            result = direct_resistance(yield_load, *criticals, bending=bending)
            resistance = result.resistance
            steps = _mrd_steps(result, yield_load, criticals, bending, p["Wy_cm3"] if mode == "flexion_y" else p["Wz_cm3"] if bending else p["Ag_cm2"], fy)
            params.update(zip(keys, values, strict=True))
            params["automatic_elastic_criticals"] = automatic_values
            absent_modes = [name for name, value in zip(("global", "local", "distorcional"), criticals, strict=True) if value is None]
            params.update(governing=result.governing, gamma=1.1 if bending else 1.2,
                          advisories=tuple(automatic_absence.get(name, "Modo "+name+" declarado ausente por análise geral de estabilidade elástica (C.2).") for name in absent_modes))
        except (TypeError, ValueError) as exc:
            error = str(exc)
        resistances[mode], errors[mode] = resistance, error
        checks[mode] = check(mode, samples, demand, resistance, params, steps,
                             REFERENCE+(", Anexo C, C.4" if bending else ", Anexo C, C.3"), error)
    # Single longitudinal web, no transverse stiffeners. Horizontal outstands
    # cannot inherit kv=5 from a web supported on both longitudinal edges.
    d, t = p["d_mm"]/10, p["t_mm"]/10
    radius = p.get("r_mm", p["t_mm"])/10
    h = d-2*(radius+t)
    v, vsteps, verror = None, [], None
    if members[0].section == "L Formado":
        verror = "A aba livre da cantoneira não pode ser tratada como alma apoiada nas duas bordas com kv=5."
    elif h <= 0:
        verror = "Largura plana da alma inválida."
    elif h/t > 200:
        verror = "h/t supera 200 para alma de viga sem enrijecedores transversais (9.1.2, Tabela 4)."
    else:
        ratio, lp, lr = h/t, 1.08*sqrt(5*e/fy), 1.4*sqrt(5*e/fy)
        if ratio <= lp:
            v, formula, sub = .6*fy*h*t/1.1, "0{,}6 f_y h t/1{,}10", rf"0{{,}}6\cdot {number(fy)}\cdot {number(h)}\cdot {number(t)}/1{{,}}10"
        elif ratio <= lr:
            v, formula, sub = .65*t*t*sqrt(5*fy*e)/1.1, r"0{,}65 t^2\sqrt{k_v f_y E}/1{,}10", rf"0{{,}}65\cdot {number(t)}^2\sqrt{{5\cdot {number(fy)}\cdot {number(e)}}}/1{{,}}10"
        else:
            v, formula, sub = .905*e*5*t**3/h/1.1, r"0{,}905 E k_v t^3/(h\cdot 1{,}10)", rf"0{{,}}905\cdot {number(e)}\cdot5\cdot {number(t)}^3/({number(h)}\cdot1{{,}}10)"
        vsteps = [step("h", "d-2(r+t)", rf"{number(d)}-2({number(radius)}+{number(t)})", h, "cm", "9.8.3"),
                  step(r"\lambda_v", "h/t", f"{number(h)}/{number(t)}", ratio, "", "9.8.3"),
                  step(r"\lambda_{p,v}", r"1{,}08\sqrt{E k_v/f_y}", rf"1{{,}}08\sqrt{{{number(e)}\cdot5/{number(fy)}}}", lp, "", "9.8.3"),
                  step(r"\lambda_{r,v}", r"1{,}40\sqrt{E k_v/f_y}", rf"1{{,}}40\sqrt{{{number(e)}\cdot5/{number(fy)}}}", lr, "", "9.8.3"),
                  step("V_{Rd}", formula, sub, v, "kN", "9.8.3")]
    if members[0].section == 'Cartola Formado' and v is not None:
        try:
            if any(abs(row['shear_z']) > 1e-6 and (abs(row['shear_y']) > 1e-6 or _torsional_demand(row, p['d_mm']/1000) > 1e-6) for _, _, row in samples):
                raise ValueError('A cartola com cortante Y ou torção concomitante exige superpor o fluxo correspondente e o empenamento antes de verificar cada alma. A partilha automática atual cobre Vz sem essas parcelas.')
            shares = web_shear_shares(members[0].section, tuple(sorted(members[0].geometry_dict().items())), members[0].section_mirrored)
            if len(shares) != 2 or any(abs(item.flat_height_mm-h*10) > 1e-7 for item in shares):
                raise ValueError('Geometria das almas incompatível com a distribuição de cortante.')
            if abs(sum(item.vertical_per_shear_z for item in shares)-1.) > 1e-8:
                raise ValueError('A distribuição de cortante não recuperou a resultante vertical.')
            fraction = max(abs(item.vertical_per_shear_z) for item in shares)
            if fraction <= 0:
                raise ValueError('Parcela de cortante por alma inválida.')
            per_web, v = v, v/fraction
            distribution = [{'plate': item.plate, 'flat_height_mm': item.flat_height_mm,
                'vertical_fraction': item.vertical_per_shear_z, 'per_web_resistance_kn': per_web}
                for item in shares]
            parameters['shear_web_distribution'] = distribution
            parameters['shear_distribution_scope'] = 'Integração do fluxo elástico em cada alma: carregamento Vz no plano de simetria, sem Vy ou torção concomitante. Os esforços das zonas de dobra são atribuídos às almas; a resistência usa somente sua largura plana.'
            vsteps[-1] = {**vsteps[-1], 'symbol': 'V_{Rd,w}'}
            vsteps.append(step('V_{Rd}', r'\min_i(V_{Rd,w,i}/|a_i|)',
                r'\min('+ ';'.join(number(per_web)+'/'+number(abs(item.vertical_per_shear_z)) for item in shares)+')', v, 'kN', '9.8.3 — parcela de cada alma'))
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            verror = str(exc)
    checks["shear_z"] = check("shear_z", samples, lambda s: abs(s["shear_z"]), v, parameters.copy(), vsteps, REFERENCE+", 9.8.3", verror)
    checks["shear_y"] = check("shear_y", samples, lambda s: abs(s["shear_y"]), None, parameters.copy(), [], REFERENCE+", 9.8.3", "O cortante Y em abas livres requer procedimento específico; kv=5 da alma não é aplicável.")
    torsion_samples, unresolved = [], []
    member_map = {member.name: member for member in members}
    result_map = {result.load_reference: result for result in results}
    for combination, name, row in samples:
        analysis = result_map[combination].member_results.get(name, {}).get('warping_analysis', {})
        if analysis.get('status') != 'solved':
            ysc, zsc = shear_center_offsets(member_map[name])
            estimated = row['torque']+zsc*row['shear_y']-ysc*row['shear_z']
            if abs(estimated) > 1e-6:
                row = {**row, 'unresolved_eccentric_torque': estimated}
                unresolved.append({'combination': combination, 'member': name, 'position_m': row['x'],
                    'estimated_torque_magnitude_kn_m': abs(estimated)})
        torsion_samples.append((combination, name, row))
    torsion_error = 'Torção ou bimomento solicitante em seção aberta: a recuperação elástica está disponível na análise 7GL; a resistência com empenamento e suas interações ainda não são abrangidas pela rotina MRD de compressão/flexão.'
    if unresolved:
        torsion_error = 'O torque referido ao centroide não comprova ausência de torção no centro de torção: há cortante excêntrico sem solução de empenamento. Declare os vínculos A/B e processe a análise 7GL; a resistência à torção/bimomento continua sendo uma verificação própria.'
    checks['torsion'] = check('torsion', torsion_samples, lambda row: _torsional_demand(row, p['d_mm']/1000),
        None, parameters.copy(), [], REFERENCE, torsion_error)
    if unresolved:
        checks['torsion']['parameters']['unresolved_eccentric_torsion'] = unresolved
    if any('bimoment' in row for _, _, row in samples):
        effects = []
        for combination, member in dict.fromkeys((c, m) for c, m, _row in samples):
            rows = [row for c, m, row in samples if c == combination and m == member]
            bending_warp = max(rows, key=lambda row: abs(row.get('bimoment', 0.)))
            total_torque = max(rows, key=lambda row: abs(row.get('torque_sc', -row['torque'])))
            effects.append({'combination': combination, 'member': member,
                'bimoment_kn_m2': bending_warp.get('bimoment', 0.), 'bimoment_position_m': bending_warp['x'],
                'torque_sc_kn_m': total_torque.get('torque_sc', -total_torque['torque']),
                'torque_position_m': total_torque['x']})
        checks['torsion']['parameters']['elastic_warping_effects'] = effects
    # Same sample, same combination; no independent maxima. NBR 14762 9.9
    # requires constant axial load along each bar.
    for key, axial_sign in (("flexao_obliqua", 0), ("flexotracao", -1), ("flexocompressao", 1)):
        selected = [(c, m, s) for c, m, s in samples if
            (abs(s["moment_y"])+abs(s["moment_z"]) > 1e-6 and
            (abs(s["axial"]) <= 1e-6 if axial_sign == 0 else s["axial"]*axial_sign > 1e-6) and
            (abs(s["moment_y"]) > 1e-6 and abs(s["moment_z"]) > 1e-6 if axial_sign == 0 else True))]
        needed = {"flexion_"+axis for _, _, s in selected for axis in ("y", "z") if abs(s["moment_"+axis]) > 1e-6}
        if axial_sign > 0:
            needed.add("axial_compression")
        error = next((errors[k] for k in needed if errors[k]), None)
        if axial_sign < 0:
            error = error or tension_error
        if axial_sign:
            for combo, member, _ in selected:
                forces = [s["axial"] for c, m, s in samples if c == combo]
                if max(forces)-min(forces) > 1e-6*max(1, max(abs(n) for n in forces)):
                    error = "A força normal varia na barra; a expressão de 9.9 requer normal constante."
        def utilization(s, axial_sign=axial_sign):
            total = 0.
            if axial_sign:
                nr = nt if axial_sign < 0 else resistances["axial_compression"]
                total += abs(s["axial"])/(nr or 1)
            return total+sum(abs(s["moment_"+axis])*100/(resistances["flexion_"+axis] or 1) for axis in ("y", "z"))
        item = check(key, selected, utilization, 1., parameters.copy(), [], REFERENCE+", 9.9", error)
        if item["status"] == "checked":
            s = next(s for c, m, s in selected if c == item["critical_combination"] and m == item["critical_member"] and s["x"] == item["critical_position_m"])
            parts = [f"{number(abs(s['moment_'+a])*100)}/{number(resistances['flexion_'+a])}" for a in ("y", "z") if abs(s['moment_'+a]) > 1e-6]
            if axial_sign:
                parts.insert(0, f"{number(abs(s['axial']))}/{number(nt if axial_sign < 0 else resistances['axial_compression'])}")
            item["steps"] = [step(r"\eta", r"N_{Sd}/N_{Rd}+M_{y,Sd}/M_{y,Rd}+M_{z,Sd}/M_{z,Rd}", "+".join(parts), item["utilization"], "", "9.9")]
        checks[key] = item
    # Mandatory M-V interaction (separate directions), not a Vy/Vz interaction.
    samples_mv = [(c, m, s) for c, m, s in samples if abs(s["moment_y"]) > 1e-6 and abs(s["shear_z"]) > 1e-6]
    error = errors["flexion_y"] or verror
    item = check("flexao_obliqua", samples_mv, lambda s: (abs(s["moment_y"])*100/(resistances["flexion_y"] or 1))**2+(abs(s["shear_z"])/(v or 1))**2,
                 1., parameters.copy(), [], REFERENCE+", 9.8.4", error)
    item["critical_check"] = "Interação de momento Y e cortante Z"
    if item["status"] == "checked":
        sample = next(s for c, m, s in samples_mv if c == item["critical_combination"] and m == item["critical_member"] and s["x"] == item["critical_position_m"])
        sub = f"({number(abs(sample['moment_y'])*100)}/{number(resistances['flexion_y'])})^2+({number(abs(sample['shear_z']))}/{number(v)})^2"
        item["steps"] = [step(r"\eta_{MV}", r"(M_{Sd}/M_{Rd})^2+(V_{Sd}/V_{Rd})^2", sub, item["utilization"], "", "9.8.4")]
    checks["moment_shear_y"] = item
    checks["compression_slenderness"] = _slenderness(
        element, model, results, samples, p, checks["axial_tension"],
    )
    checks["stability_procedure"] = stability_procedure(model, results) if stability_check is None else stability_check
    checks.update(service_checks(element, model))
    checks.update(bearing_checks(element, model, fy*10))
    return checks
