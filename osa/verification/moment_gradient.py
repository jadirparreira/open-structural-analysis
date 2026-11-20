"""Moment-gradient factor helpers for rolled steel member checks."""

from __future__ import annotations

from itertools import pairwise
from math import isfinite

from osa.domain.member_axes import member_basis
from osa.verification.restraints import MemberChainRestraints

_TOL = 1e-8


def _interpolate_magnitude(stations, target):
    """Interpolate signed moment, then take its absolute value at the station."""
    exact = [abs(value) for position, value in stations if abs(position - target) <= _TOL]
    if exact:
        return max(exact)
    for (x0, m0), (x1, m1) in pairwise(stations):
        if x0 < target < x1:
            if x1 - x0 <= _TOL:
                return max(abs(m0), abs(m1))
            ratio = (target - x0) / (x1 - x0)
            return abs(m0 + ratio * (m1 - m0))
    return None


def moment_gradient_calculation(stations, start, end, *, r_m=1.0):
    """Return the NBR 8800:2024, 5.4.2.3(a) inputs for one interval."""
    if not isfinite(start) or not isfinite(end) or end - start <= _TOL:
        return None
    stations = sorted(
        (float(position), float(moment))
        for position, moment in stations
        if isfinite(float(position)) and isfinite(float(moment))
        and start - _TOL <= float(position) <= end + _TOL
    )
    if len({position for position, _ in stations}) < 4:
        return None
    if stations[0][0] > start + _TOL or stations[-1][0] < end - _TOL:
        return None
    quarter = [
        _interpolate_magnitude(stations, start + (end - start) * fraction)
        for fraction in (0.25, 0.50, 0.75)
    ]
    m_max = max(
        [abs(value) for position, value in stations]
        + [value for value in (_interpolate_magnitude(stations, start),
                               _interpolate_magnitude(stations, end), *quarter)
           if value is not None]
    )
    if m_max <= 0.0:
        return {"Cb": 1.0, "Mmax": 0.0, "MA": 0.0, "MB": 0.0, "MC": 0.0,
                "Rm": r_m}
    denominator = 2.5 * m_max + 3.0 * quarter[0] + 4.0 * quarter[1] + 3.0 * quarter[2]
    if denominator <= 0.0 or not isfinite(denominator):
        return None
    return {"Cb": 12.5 * m_max / denominator * r_m,
            "Mmax": m_max, "MA": quarter[0], "MB": quarter[1], "MC": quarter[2],
            "Rm": r_m}


def moment_gradient_factor(stations, start, end, *, r_m=1.0):
    calculation = moment_gradient_calculation(stations, start, end, r_m=r_m)
    return calculation["Cb"] if calculation is not None else None


def rolled_member_cb(model, element, results, field, restraint_data, override=None):
    """Return the manual Cb or conservative automatic Cb for the current Lb.

    A single Cb is used by the existing rolled-section resistance routines.
    When load combinations produce different factors, the minimum is used so
    that no combination receives a less conservative resistance.
    """
    if override is not None:
        value = float(override)
        if not isfinite(value) or value <= 0.0:
            raise ValueError("Cb manual deve ser positivo e finito.")
        return {"value": value, "source": "manual", "by_combination": {}, "governing": None}

    mode = restraint_data.modes.get("Lb", {})
    # A scalar manual Lb does not identify where the segment lies on the
    # moment diagram. Keep the user's manual Cb control, and otherwise use
    # the conservative NBR baseline until the segment location is explicit.
    if mode.get("manual_override"):
        return {"value": 1.0, "source": "fallback Lb definido manualmente; localização do trecho não informada",
                "by_combination": {}, "governing": None}
    interval = mode.get("governing_interval_m")
    if not interval or len(interval) != 2:
        return {"value": 1.0, "source": "fallback sem intervalo destravado",
                "by_combination": {}, "governing": None}
    start_interval, end_interval = map(float, interval)

    try:
        first = model.bars[min(element.member_names)]
        first_start = model.nodes[first.start_node]
        first_end = model.nodes[first.end_node]
        basis = member_basis(first_start, first_end, first.rotation)
        if basis is None:
            raise ValueError("eixo do elemento inválido")
        axis = basis[0]
        origin = (first_start.x, first_start.y, first_start.z)
        topology = MemberChainRestraints(model)
        chain_bars, _stations, _length, _target, _component = topology._connected_collinear_chain(
            element, basis, origin,
        )
        end_positions = [
            sum((point - base) * direction for point, base, direction in zip(
                (node.x, node.y, node.z), origin, axis,
            ))
            for bar in chain_bars
            for node in (model.nodes[bar.start_node], model.nodes[bar.end_node])
        ]
        chain_origin = min(end_positions)
    except (KeyError, TypeError, ValueError, IndexError):
        return {"value": 1.0, "source": "fallback sem geometria compatível",
                "by_combination": {}, "governing": None}

    by_combination = {}
    for result in results:
        stations = []
        for bar in chain_bars:
            member_result = result.member_results.get(bar.name)
            if not member_result:
                continue
            start_node = model.nodes[bar.start_node]
            end_node = model.nodes[bar.end_node]
            bar_basis = member_basis(start_node, end_node, bar.rotation)
            if bar_basis is None:
                continue
            orientation = sum(a * b for a, b in zip(bar_basis[0], axis))
            bar_start = sum(
                (coordinate - base) * direction
                for coordinate, base, direction in zip(
                    (start_node.x, start_node.y, start_node.z), origin, axis,
                )
            ) - chain_origin
            for sample in member_result.get("samples", ()):
                try:
                    local_x = float(sample["x"])
                    moment = float(sample[field])
                except (KeyError, TypeError, ValueError):
                    continue
                stations.append((bar_start + orientation * local_x, moment))
        calculation = moment_gradient_calculation(stations, start_interval, end_interval)
        by_combination[result.load_reference] = calculation or {
            "Cb": 1.0, "Mmax": None, "MA": None, "MB": None, "MC": None,
            "Rm": 1.0, "fallback": "amostras insuficientes no intervalo",
        }

    demanded = [item for item in by_combination.values()
                if item.get("Mmax") is None or item["Mmax"] > 1e-12]
    governing = min(demanded, key=lambda item: item["Cb"], default=None)
    value = governing["Cb"] if governing else 1.0
    source = "automático NBR 8800:2024, 5.4.2.3(a)" if by_combination else "fallback sem amostras"
    return {
        "value": value,
        "source": source,
        "interval_m": (start_interval, end_interval),
        "by_combination": by_combination,
        "governing": governing,
    }
