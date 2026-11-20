"""Concurrent NBR 8800:2024 axial/bending/torsion interactions."""

from .structured_checks import check, number, step


def interactions(samples, parameters, nt, nc, moments, shears, torsion,
                 tension_error=None, compression_error=None):
    output = {}
    for key, sign in (("flexao_obliqua", 0), ("flexotracao", -1), ("flexocompressao", 1)):
        rows = [(c, m, s) for c, m, s in samples
                if abs(s["moment_y"])+abs(s["moment_z"]) > 1e-6
                and (abs(s["axial"]) <= 1e-6 if sign == 0 else s["axial"]*sign > 1e-6)
                and abs(s["torque"])*100 <= .2*torsion]
        nr = nt if sign == -1 else nc if sign == 1 else None
        error = tension_error if sign == -1 else compression_error if sign == 1 else None
        if any(abs(s[f"moment_{a}"]) > 1e-6 and moments[a] is None for _, _, s in rows for a in ("y", "z")):
            error = "Resistência à flexão indisponível para a interação."
        terms = []
        for combo, member, s in rows:
            n = abs(s["axial"])/nr if sign and nr else 0.
            my, mz = [abs(s[f"moment_{a}"])*100/moments[a]
                      if moments[a] and abs(s[f"moment_{a}"]) > 1e-6 else 0. for a in ("y", "z")]
            eta = n+8/9*(my+mz) if n >= .2 else n/2+my+mz
            terms.append((combo, member, {**s, "eta": eta, "terms": (n, my, mz)}))
        out = check(key, terms, lambda s, pending=bool(error): 1. if pending else s["eta"], 1., parameters.copy(), [],
                    "ABNT NBR 8800:2024, 5.5.1.2", error)
        if out["status"] == "checked":
            s = next(s for c, m, s in terms if c == out["critical_combination"] and
                     m == out["critical_member"] and s["x"] == out["critical_position_m"])
            n, my, mz = s["terms"]
            formula = r"\dfrac{N_{Sd}}{N_{Rd}}+\dfrac{8}{9}\left(\dfrac{M_{y,Sd}}{M_{y,Rd}}+\dfrac{M_{z,Sd}}{M_{z,Rd}}\right)" if n >= .2 else r"\dfrac{N_{Sd}}{2N_{Rd}}+\dfrac{M_{y,Sd}}{M_{y,Rd}}+\dfrac{M_{z,Sd}}{M_{z,Rd}}"
            substitution = f"{number(n)}+(8/9)({number(my)}+{number(mz)})" if n >= .2 else f"{number(n)}/2+{number(my)}+{number(mz)}"
            if not sign:
                formula = r"\dfrac{M_{y,Sd}}{M_{y,Rd}}+\dfrac{M_{z,Sd}}{M_{z,Rd}}"
                substitution = f"{number(my)}+{number(mz)}"
            out["steps"] = [step(r"\eta_{int}", formula, substitution, out["utilization"], "", "5.5.1.2")]
        output[key] = out

    rows = [(c, m, s) for c, m, s in samples if abs(s["torque"])*100 > .2*torsion and
            any(abs(s[k]) > 1e-6 for k in ("axial", "moment_y", "moment_z", "shear_y", "shear_z"))]
    error, terms = None, []
    for combo, member, s in rows:
        axes = [a for a in ("y", "z") if abs(s[f"moment_{a}"]) > 1e-6]
        if len(axes) > 1:
            error = "Torção combinada com flexão biaxial requer o procedimento de tensões de 5.5.2.3."
            break
        axis = axes[0] if axes else "y" if abs(s["shear_z"]) > 1e-6 else "z"
        shear_axis = "z" if axis == "y" else "y"
        if abs(s[f"shear_{axis}"]) > 1e-6:
            error = "Solicitação fora do campo uniaxial da interação de torção de 5.5.2.2."
            break
        nr = nt if s["axial"] < 0 else nc
        if (abs(s["axial"]) > 1e-6 and nr is None) or (abs(s[f"moment_{axis}"]) > 1e-6 and moments[axis] is None) or (abs(s[f"shear_{shear_axis}"]) > 1e-6 and shears[shear_axis] is None):
            error = "Resistência axial, à flexão ou ao cortante indisponível para a interação com torção."
            break
        n = abs(s["axial"])/nr if abs(s["axial"]) > 1e-6 else 0.
        m = abs(s[f"moment_{axis}"])*100/moments[axis] if abs(s[f"moment_{axis}"]) > 1e-6 else 0.
        v = abs(s[f"shear_{shear_axis}"])/shears[shear_axis] if abs(s[f"shear_{shear_axis}"]) > 1e-6 else 0.
        t = abs(s["torque"])*100/torsion
        terms.append((combo, member, {**s, "eta": n+m+(v+t)**2, "terms": (n, m, v, t)}))
    out = check("torsion_interaction", rows if error else terms, lambda s: s.get("eta", 1.), 1.,
                parameters.copy(), [], "ABNT NBR 8800:2024, 5.5.2.2", error)
    if out["status"] == "checked":
        s = next(s for c, m, s in terms if c == out["critical_combination"] and
                 m == out["critical_member"] and s["x"] == out["critical_position_m"])
        n, m, v, t = s["terms"]
        out["steps"] = [step(r"\eta_T", r"\dfrac{N_{Sd}}{N_{Rd}}+\dfrac{M_{Sd}}{M_{Rd}}+\left(\dfrac{V_{Sd}}{V_{Rd}}+\dfrac{T_{Sd}}{T_{Rd}}\right)^2",
                             f"{number(n)}+{number(m)}+({number(v)}+{number(t)})^2", out["utilization"], "", "5.5.2.2")]
    output["torsion_interaction"] = out
    return output
