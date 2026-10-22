"""Estimate unbraced lengths from connected, collinear members and restraints.

The geometric rule used here is intentionally simple: a connected transverse
bar is treated as a restraint in the local direction of its axis. The bar
chain being checked may continue through collinear members outside its
verification group; a point interrupts only the direction it restrains.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import inf, radians, sin

import numpy as np

from osa.domain.member_axes import member_basis


_GEOMETRY_TOL = 1e-8
_DEFAULT_MIN_BRACE_ANGLE_DEGREES = 30.0


@dataclass
class RestraintLengths:
    lengths_m: dict[str, float]
    modes: dict[str, dict]
    issues: tuple[str, ...]
    notes: tuple[str, ...]

    def memory(self) -> dict:
        return {"modes": self.modes, "issues": self.issues, "notes": self.notes}


def restraint_lengths(model, element, results, properties, cb=1.0) -> RestraintLengths:
    """Share topology-derived lengths between checks and the calculation memorial."""
    results = tuple(results)
    min_brace_angle = float(getattr(
        model, "minimum_bar_restraint_angle_degrees", _DEFAULT_MIN_BRACE_ANGLE_DEGREES,
    ))
    min_brace_angle = min(90.0, max(1.0, min_brace_angle))
    token = (model.revision, tuple(id(result) for result in results), min_brace_angle)
    cache = getattr(model, "_restraint_lengths_cache", None)
    if cache is None or cache["token"] != token:
        cache = {"token": token, "results": results, "lengths": {}}
        model._restraint_lengths_cache = cache
    key = (tuple(sorted(element.member_names)), tuple(sorted(properties.items())), cb)
    if key not in cache["lengths"]:
        cache["lengths"][key] = MemberChainRestraints(model, min_brace_angle).lengths(element)
    return cache["lengths"][key]


class MemberChainRestraints:
    """Find directional restraint points along a connected member chain.

    For Ly/Lz, a directly connected bar counts as a directional restraint
    when its angle to the verified member axis is at least the configured
    minimum. The rule is topological/geometric and does not
    assess brace strength, stiffness, connection capacity, or anchorage.
    """

    def __init__(self, model, min_brace_angle_degrees: float = _DEFAULT_MIN_BRACE_ANGLE_DEGREES) -> None:
        self.model = model
        self._min_brace_angle_degrees = min(90.0, max(1.0, min_brace_angle_degrees))
        self._min_brace_direction_component = sin(radians(self._min_brace_angle_degrees))

    @staticmethod
    def _point(node) -> np.ndarray:
        return np.array((node.x, node.y, node.z), dtype=float)

    @staticmethod
    def _node_position(node, origin: np.ndarray, axis: np.ndarray) -> float:
        return float((MemberChainRestraints._point(node) - origin) @ axis)

    def _element_chain(self, element):
        """Validate that the verified members form one straight, joined line."""
        bars = [self.model.bars[name] for name in sorted(element.member_names)]
        if not bars or len(bars) != len(element.member_names):
            raise ValueError("elemento sem barras")
        first = bars[0]
        start = self.model.nodes[first.start_node]
        end = self.model.nodes[first.end_node]
        basis = member_basis(start, end, first.rotation)
        if basis is None:
            raise ValueError("elemento com comprimento nulo")
        axis, local_y, local_z = (np.asarray(vector, dtype=float) for vector in basis)
        origin = self._point(start)
        bounds = []
        member_nodes = set()
        for bar in bars:
            other_basis = member_basis(
                self.model.nodes[bar.start_node], self.model.nodes[bar.end_node], bar.rotation,
            )
            if other_basis is None:
                raise ValueError("elemento com comprimento nulo")
            other_axis, other_y, other_z = (
                np.asarray(vector, dtype=float) for vector in other_basis
            )
            if (
                abs(float(other_axis @ axis)) < 1.0 - _GEOMETRY_TOL
                or abs(float(other_y @ local_y)) < 1.0 - _GEOMETRY_TOL
                or abs(float(other_z @ local_z)) < 1.0 - _GEOMETRY_TOL
            ):
                raise ValueError("grupo com eixos locais incompatíveis")
            stations = []
            for name in (bar.start_node, bar.end_node):
                node = self.model.nodes[name]
                delta = self._point(node) - origin
                station = float(delta @ axis)
                if np.linalg.norm(delta - station * axis) > _GEOMETRY_TOL * max(1.0, np.linalg.norm(delta)):
                    raise ValueError("grupo de verificação não colinear")
                stations.append(station)
                member_nodes.add(name)
            bounds.append(sorted(stations))
        bounds.sort()
        lo, hi = bounds[0]
        for left, right in bounds[1:]:
            if abs(left - hi) > _GEOMETRY_TOL:
                raise ValueError("grupo com lacunas ou barras sobrepostas")
            hi = right
        target_interval = (lo, hi)
        return bars, basis, origin, target_interval

    def _connected_collinear_chain(self, element, basis, origin):
        """Expand the verified line through connected bars outside its group."""
        axis, local_y, local_z = (np.asarray(vector, dtype=float) for vector in basis)
        eligible = {}
        bounds_by_bar = {}
        nodes_by_bar = {}

        for name, bar in self.model.bars.items():
            other_basis = member_basis(
                self.model.nodes[bar.start_node], self.model.nodes[bar.end_node], bar.rotation,
            )
            if other_basis is None:
                continue
            other_axis, other_y, other_z = (
                np.asarray(vector, dtype=float) for vector in other_basis
            )
            if (
                abs(float(other_axis @ axis)) < 1.0 - _GEOMETRY_TOL
                or abs(float(other_y @ local_y)) < 1.0 - _GEOMETRY_TOL
                or abs(float(other_z @ local_z)) < 1.0 - _GEOMETRY_TOL
            ):
                continue
            names = (bar.start_node, bar.end_node)
            stations = []
            collinear = True
            for node_name in names:
                delta = self._point(self.model.nodes[node_name]) - origin
                station = float(delta @ axis)
                if np.linalg.norm(delta - station * axis) > _GEOMETRY_TOL * max(1.0, np.linalg.norm(delta)):
                    collinear = False
                    break
                stations.append(station)
            if not collinear:
                continue
            eligible[name] = bar
            bounds_by_bar[name] = tuple(sorted(stations))
            nodes_by_bar[name] = names

        target_names = set(element.member_names)
        if not target_names.issubset(eligible):
            raise ValueError("não foi possível localizar as barras do elemento na cadeia")

        bars_at_node: dict[str, list[str]] = {}
        for name, node_names in nodes_by_bar.items():
            for node_name in node_names:
                bars_at_node.setdefault(node_name, []).append(name)

        component = set()
        pending = list(target_names)
        while pending:
            name = pending.pop()
            if name in component:
                continue
            component.add(name)
            for node_name in nodes_by_bar[name]:
                pending.extend(bars_at_node.get(node_name, ()))

        intervals = [bounds_by_bar[name] for name in component]
        intervals.sort()
        lo, hi = intervals[0]
        for left, right in intervals[1:]:
            if left > hi + _GEOMETRY_TOL:
                raise ValueError("cadeia colinear conectada possui uma lacuna")
            hi = max(hi, right)

        stations = {}
        for name in component:
            for node_name in nodes_by_bar[name]:
                node = self.model.nodes[node_name]
                stations[node_name] = min(
                    hi - lo,
                    max(0.0, self._node_position(node, origin, axis) - lo),
                )
        target_positions = [
            value - lo
            for name in target_names
            for value in bounds_by_bar[name]
        ]
        target_interval = (min(target_positions), max(target_positions))
        return (
            [eligible[name] for name in component],
            stations,
            hi - lo,
            target_interval,
            component,
        )

    @staticmethod
    def _mode(stations, length, target_interval, restraints, mode_name: str) -> dict:
        """Return the longest uninterrupted interval overlapping the target."""
        accepted = {
            node: data for node, data in restraints.items()
            if _GEOMETRY_TOL < data["position_m"] < length - _GEOMETRY_TOL
        }
        points = sorted({0.0, length, *(data["position_m"] for data in accepted.values())})
        gaps = [
            (left, right) for left, right in pairwise(points)
            if right - left > _GEOMETRY_TOL
            and right > target_interval[0] + _GEOMETRY_TOL
            and left < target_interval[1] - _GEOMETRY_TOL
        ]
        governing = max(gaps, key=lambda item: item[1] - item[0], default=target_interval)
        endpoints = [
            any(abs(data["position_m"] - position) <= _GEOMETRY_TOL for data in accepted.values())
            for position in target_interval
        ]
        return {
            "length_m": governing[1] - governing[0],
            "governing_interval_m": governing,
            "endpoints_restrained": all(endpoints),
            "compression_supported": all(endpoints),
            "boundary_condition": "intervalo_geométrico",
            "points": [
                {
                    "node": node,
                    "position_m": position,
                    "stiffness": inf if node in accepted else 0.0,
                    "accepted": node in accepted,
                    "required_stiffness": 0.0,
                    "reason": accepted[node]["reason"] if node in accepted
                    else "sem travamento identificado neste eixo",
                }
                for node, position in sorted(
                    stations.items(), key=lambda item: (item[1], item[0]),
                )
            ],
        }

    def lengths(self, element) -> RestraintLengths:
        _bars, basis, origin, _element_interval = self._element_chain(element)
        axis, local_y, local_z = (np.asarray(vector, dtype=float) for vector in basis)
        _chain_bars, stations, length, target_interval, component_names = (
            self._connected_collinear_chain(element, basis, origin)
        )

        # Use the instructed OSA convention for this routine: a transverse
        # bar aligned with local Y splits Ly, and one aligned with local Z
        # splits Lz. Each bar affects only the matching directional length.
        mode_specs = {
            "Ly": (local_y, 0, 1),
            "Lz": (local_z, 0, 2),
        }
        restraints: dict[str, dict[str, dict]] = {"Ly": {}, "Lz": {}}
        for mode, (direction, support_offset, _connection_dof) in mode_specs.items():
            for node_name, position in stations.items():
                node = self.model.nodes[node_name]
                if self._direction_locked(node, direction, support_offset):
                    restraints[mode][node_name] = {
                        "position_m": position,
                        "accepted": True,
                        "reason": "apoio nodal rígido explícito",
                    }

        for node_name, position in stations.items():
            for bar_name, brace in self.model.bars.items():
                if bar_name in component_names or node_name not in (brace.start_node, brace.end_node):
                    continue
                brace_basis = member_basis(
                    self.model.nodes[brace.start_node],
                    self.model.nodes[brace.end_node],
                    brace.rotation,
                )
                if brace_basis is None:
                    continue
                brace_axis = np.asarray(brace_basis[0], dtype=float)
                for mode, (direction, _offset, _dof) in mode_specs.items():
                    component = abs(float(brace_axis @ direction))
                    if component + _GEOMETRY_TOL < self._min_brace_direction_component:
                        continue
                    restraints[mode][node_name] = {
                        "position_m": position,
                        "accepted": True,
                        "reason": (
                            f"barra diagonal conectada ({bar_name}); componente local "
                            f"{component:.2f}"
                        ),
                    }

        modes = {
            mode: self._mode(stations, length, target_interval, restraints[mode], mode)
            for mode in ("Ly", "Lz")
        }

        # The simplified bar rule does not infer torsional restraint from a
        # transverse member. Keep these lengths finite and based on the full
        # collinear chain unless explicit nodal twist supports split it.
        torsional_restraints = {}
        for node_name, position in stations.items():
            node = self.model.nodes[node_name]
            if self._direction_locked(node, axis, 3):
                torsional_restraints[node_name] = {
                    "position_m": position,
                    "accepted": True,
                    "reason": "apoio nodal rígido explícito à torção",
                }
        modes["Lt"] = self._mode(
            stations, length, target_interval, torsional_restraints, "Lt",
        )
        modes["Lb"] = self._mode(
            stations, length, target_interval, torsional_restraints, "Lb",
        )

        notes = (
            "Comprimentos calculados percorrendo barras colineares conectadas, mesmo fora do grupo de verificação.",
            f"Barra conectada conta como travamento direcional quando atende ao ângulo mínimo de {self._min_brace_angle_degrees:g}°; o nó não divide os outros comprimentos.",
            "A regra é geométrica e simplificada: não verifica rigidez ou resistência da barra de travamento, ligações, ancoragens nem a contenção da mesa comprimida.",
            "Lt e Lb não são reduzidos apenas pela presença de uma barra transversal; são mantidos finitos pelo comprimento da cadeia, salvo apoio nodal explícito à torção.",
        )
        return RestraintLengths(
            {mode: data["length_m"] for mode, data in modes.items()},
            modes,
            (),
            notes,
        )

    @staticmethod
    def _direction_locked(node, direction, offset: int) -> bool:
        """Whether all components of a local direction have rigid support."""
        for index, component in enumerate(direction):
            if abs(float(component)) <= _GEOMETRY_TOL:
                continue
            dof = offset + index
            if not node.supports[dof] or float(node.support_stiffness[dof]) > 0.0:
                return False
        return True
