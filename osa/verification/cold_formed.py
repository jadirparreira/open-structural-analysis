"""NBR 14762:2010 calculation primitives for cold-formed members.

The connection and holes are not represented by the current member model.
Inputs therefore have to be supplied explicitly; this module does not infer
net areas or shear-lag coefficients from the gross section geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt


@dataclass(frozen=True, slots=True)
class TensionResistance:
    gross_yield_kn: float
    net_outside_connection_kn: float
    net_at_connection_kn: float
    resistance_kn: float
    governing: str


def tension_resistance(*, gross_area_cm2: float, net_outside_cm2: float,
                       net_connection_cm2: float, fy_kn_cm2: float,
                       fu_kn_cm2: float, ct: float) -> TensionResistance:
    """Calculate the three tensile resistances of NBR 14762:2010, 9.6.2.

    Net areas must already account for the specific hole patterns, cuts and
    connection type. This calculation excludes the slenderness check in 9.6.3
    and checks of the connections themselves.
    """
    values = (gross_area_cm2, net_outside_cm2, net_connection_cm2, fy_kn_cm2, fu_kn_cm2, ct)
    if not all(isfinite(value) and value > 0 for value in values):
        raise ValueError("As áreas, resistências e Ct devem ser finitos e positivos.")
    if ct > 1:
        raise ValueError("Ct não pode ser superior a 1,0.")
    if net_outside_cm2 > gross_area_cm2 or net_connection_cm2 > gross_area_cm2:
        raise ValueError("A área líquida informada não pode superar a área bruta.")
    capacities = {
        "escoamento da seção bruta": gross_area_cm2 * fy_kn_cm2 / 1.10,
        "ruptura fora da ligação": net_outside_cm2 * fu_kn_cm2 / 1.35,
        "ruptura na ligação": ct * net_connection_cm2 * fu_kn_cm2 / 1.65,
    }
    governing = min(capacities, key=capacities.get)
    return TensionResistance(
        gross_yield_kn=capacities["escoamento da seção bruta"],
        net_outside_connection_kn=capacities["ruptura fora da ligação"],
        net_at_connection_kn=capacities["ruptura na ligação"],
        resistance_kn=capacities[governing], governing=governing,
    )


@dataclass(frozen=True, slots=True)
class DirectResistance:
    global_characteristic: float
    local_characteristic: float
    distortional_characteristic: float
    resistance: float
    lambda_global: float
    lambda_local: float
    lambda_distortional: float
    governing: str


def direct_resistance(yield_load: float, global_critical: float | None,
                      local_critical: float | None, distortional_critical: float | None,
                      *, bending: bool = False) -> DirectResistance:
    """NBR 14762:2010, C.3/C.4, all loads in one consistent unit.

    Critical values must come from a general elastic stability analysis (C.2),
    for the actual geometry, restraints, loading and bending direction/sign.
    None explicitly denotes a mode proved absent by that analysis (C.2).
    No mode is silently omitted or estimated.
    """
    if not isfinite(yield_load) or yield_load <= 0 or not all(
            isfinite(v) and v > 0 for v in
            (global_critical, local_critical, distortional_critical) if v is not None):
        raise ValueError("Os esforços críticos e o esforço de escoamento devem ser finitos e positivos.")
    l0 = sqrt(yield_load / global_critical) if global_critical is not None else 0.
    if bending:
        re = (yield_load if l0 <= .6 else
              1.11 * (1 - .278*l0*l0) * yield_load if l0 < 1.336 else
              yield_load / (l0*l0))
    else:
        re = yield_load * (.658**(l0*l0) if l0 <= 1.5 else .877/(l0*l0))
    ll = sqrt(re/local_critical) if local_critical is not None else 0.
    rl = re if ll <= .776 else (1-.15/ll**.8)*re/ll**.8
    ld = sqrt(yield_load/distortional_critical) if distortional_critical is not None else 0.
    if bending:
        rd = yield_load if ld <= .673 else (1-.22/ld)*yield_load/ld
    else:
        rd = yield_load if ld <= .561 else (1-.25/ld**1.2)*yield_load/ld**1.2
    capacities = {"escoamento": yield_load}
    capacities.update({key: value for key, value, critical in (
        ("global", re, global_critical), ("local", rl, local_critical),
        ("distorcional", rd, distortional_critical)) if critical is not None})
    governing = min(capacities, key=capacities.get)
    return DirectResistance(re, rl, rd, capacities[governing]/(1.1 if bending else 1.2),
                            l0, ll, ld, governing)
