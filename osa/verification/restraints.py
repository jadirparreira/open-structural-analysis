"""Analytical restraint lengths in OSA's local x/y/z member frame.

NBR 8800:2024, 4.12 and 5.3.5.1. OSA's longitudinal axis is x:
normative Lx/Ly/Lz are reported as Ly/Lz/Lt, respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import inf, isfinite

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import lsmr

from osa.analysis.pynite.model_builder import ModelBuilder
from osa.analysis.pynite.semirigid import _spring_stiffnesses, install_semirigid_connections
from osa.domain.member_axes import member_basis

GAMMA_R = 1.35


@dataclass
class RestraintLengths:
    lengths_m: dict[str, float]
    modes: dict[str, dict]
    issues: tuple[str, ...]
    notes: tuple[str, ...]

    def memory(self) -> dict:
        return {"modes": self.modes, "issues": self.issues, "notes": self.notes}


class AnalyticalRestraints:
    """Reuse the solver's elastic stiffness, excluding the member being braced.

    Unit actions measure flexibility of the *surrounding* structure. Releasing
    all other DOFs prevents a loose branch, a subdivision node, or a mechanism
    from being mistaken for an anchorage. Artificial solver rotation supports
    are deliberately not included.
    """

    def __init__(self, model) -> None:
        from Pynite.Analysis import _prepare_model

        self.model = model
        target = ModelBuilder().build(model)
        self.connection_springs = {}
        for name, bar in model.bars.items():
            for endpoint, label in enumerate(("start", "end")):
                springs = _spring_stiffnesses(target.members[name], bar, label)
                for dof, stiffness in springs.items():
                    self.connection_springs[name, endpoint, dof % 6] = stiffness
        install_semirigid_connections(target, model)
        _prepare_model(target)
        self.node_indices = {name: node.ID * 6 for name, node in target.nodes.items()}
        self.size = 6 * len(target.nodes)
        self.blocks = {}
        for name, member in target.members.items():
            self.blocks[name] = []
            for part in member.sub_members.values():
                indices = np.array([
                    *(self.node_indices[part.i_node.name] + i for i in range(6)),
                    *(self.node_indices[part.j_node.name] + i for i in range(6)),
                ])
                self.blocks[name].append((indices, np.asarray(part.Ke(), dtype=float)))
        self.fixed = np.zeros(self.size, dtype=bool)
        self.springs = np.zeros(self.size)
        for name, node in model.nodes.items():
            offset = self.node_indices[name]
            for dof, supported in enumerate(node.supports):
                if supported:
                    spring = node.support_stiffness[dof]
                    self.fixed[offset + dof] = spring <= 0.0
                    if spring > 0.0:
                        self.springs[offset + dof] = spring
        self.spring_matrix = diags(self.springs)

    def _assemble(self, names):
        rows, cols, values = [], [], []
        for name in names:
            for indices, matrix in self.blocks[name]:
                rows.extend(np.repeat(indices, 12))
                cols.extend(np.tile(indices, 12))
                values.extend(matrix.ravel())
        return coo_matrix((values, (rows, cols)), shape=(self.size, self.size)).tocsr()

    def _external_matrix(self, excluded):
        # Assemble the external terms directly: subtracting a stiff target from
        # a global matrix can leave spurious tiny restraints through cancellation.
        return self._assemble(name for name in self.blocks if name not in excluded) + self.spring_matrix

    def _directional_stiffnesses(self, matrix, nodes, direction, rotation=False):
        """Return conservative coupled stiffnesses, zero for unanchored motions.

        The absolute row sum of the flexibility matrix includes the joint action
        of restraints sharing the same support structure, rather than checking
        each point with its neighbours artificially held fixed.
        """
        free = np.flatnonzero(~self.fixed)
        reduced = matrix[free][:, free]
        diagonal = reduced.diagonal()
        active = diagonal > 0.0
        scale = np.zeros(len(free))
        scale[active] = 1.0 / np.sqrt(diagonal[active])
        scaled = diags(scale) @ reduced @ diags(scale)
        forces, responses, stiffnesses = [], [], {}
        for name in nodes:
            load = np.zeros(self.size)
            offset = self.node_indices[name] + (3 if rotation else 0)
            load[offset:offset + 3] = direction
            load = load[free]
            if np.linalg.norm(load) < 1e-10:
                stiffnesses[name] = inf
                continue
            if np.linalg.norm(load[~active]) > 1e-10:
                stiffnesses[name] = 0.0
                continue
            rhs = scale * load
            solution = lsmr(scaled, rhs, atol=1e-12, btol=1e-12,
                            conlim=1e12, maxiter=max(100, 8 * len(free)))[0]
            residual = np.linalg.norm(scaled @ solution - rhs)
            if residual > 1e-7 * np.linalg.norm(rhs):
                stiffnesses[name] = 0.0
                continue
            displacement = scale * solution
            compliance = float(load @ displacement)
            if not isfinite(compliance) or compliance <= 0.0:
                stiffnesses[name] = 0.0
                continue
            forces.append((name, load))
            responses.append(displacement)
        if forces:
            flexibility = np.array([[load @ response for response in responses] for _, load in forces])
            # Round-off must not make the bound more favourable.
            flexibility = (flexibility + flexibility.T) / 2.0
            for index, (name, _load) in enumerate(forces):
                stiffnesses[name] = 1.0 / float(np.sum(np.abs(flexibility[index])))
        return stiffnesses

    def _chain(self, element):
        bars = [self.model.bars[name] for name in sorted(element.member_names)]
        first = bars[0]
        start, end = (self.model.nodes[name] for name in (first.start_node, first.end_node))
        basis = member_basis(start, end, first.rotation)
        if basis is None:
            raise ValueError("elemento com comprimento nulo")
        axis = np.asarray(basis[0])
        origin = np.array((start.x, start.y, start.z))
        bounds = []
        for bar in bars:
            other_basis = member_basis(self.model.nodes[bar.start_node], self.model.nodes[bar.end_node], bar.rotation)
            if other_basis is None or abs(np.dot(other_basis[1], basis[1])) < 1.0 - 1e-8:
                raise ValueError("grupo com eixos locais incompatíveis")
            stations = []
            for name in (bar.start_node, bar.end_node):
                node = self.model.nodes[name]
                delta = np.array((node.x, node.y, node.z)) - origin
                station = float(delta @ axis)
                if np.linalg.norm(delta - station * axis) > 1e-9 * max(1.0, np.linalg.norm(delta)):
                    raise ValueError("grupo de verificação não colinear")
                stations.append(station)
            bounds.append(sorted(stations))
        bounds.sort()
        lo, hi = bounds[0]
        for left, right in bounds[1:]:
            if abs(left - hi) > 1e-8:
                raise ValueError("grupo com lacunas ou barras sobrepostas")
            hi = right
        stations = {}
        for name, node in self.model.nodes.items():
            delta = np.array((node.x, node.y, node.z)) - origin
            station = float(delta @ axis)
            # Match the physical-member subdivision tolerance used by PyNite.
            tolerance = 1e-12 * (1.0 + hi - lo)
            if lo - tolerance <= station <= hi + tolerance and np.linalg.norm(delta - station * axis) <= tolerance:
                stations[name] = min(hi - lo, max(0.0, station - lo))
        return bars, basis, stations, hi - lo

    def _connection_stiffness(self, bars, name, dof):
        stiffness = inf
        for bar in bars:
            for endpoint, node in enumerate((bar.start_node, bar.end_node)):
                if node == name:
                    index = 2 * dof + endpoint
                    if bar.releases[index]:
                        return 0.0
                    if dof >= 3 and bar.rotation_flexibility_percent[2 * (dof - 3) + endpoint] >= 100:
                        return 0.0
                    stiffness = min(stiffness, self.connection_springs.get((bar.name, endpoint, dof), inf))
        return stiffness

    @staticmethod
    def _mode(stations, length, stiffnesses, minimum, allowed=None):
        accepted = {name for name, stiffness in stiffnesses.items()
                    if stiffness > 0.0 and (allowed is None or name in allowed)}
        # Removing an inadequate brace changes both the count and the spans.
        while True:
            points = sorted({0.0, length, *(stations[name] for name in accepted)})
            gaps = [(a, b) for a, b in pairwise(points) if b - a > 1e-10]
            greatest = max(gaps, key=lambda item: item[1] - item[0])
            count = len({stations[name] for name in accepted if 1e-9 < stations[name] < length - 1e-9})
            required = minimum(max(1, count), greatest[1] - greatest[0])
            removed = {name for name in accepted if stiffnesses[name] < required}
            if not removed:
                break
            accepted.difference_update(removed)
        boundary_nodes = [
            [name for name in accepted if abs(stations[name] - boundary) < 1e-9]
            for boundary in (0.0, length)
        ]
        return {
            "length_m": greatest[1] - greatest[0],
            "governing_interval_m": greatest,
            "endpoints_restrained": all(boundary_nodes),
            "points": [
                {"node": name, "position_m": stations[name], "stiffness": stiffnesses[name],
                 "accepted": name in accepted, "required_stiffness": required,
                 "reason": ("contenção considerada" if name in accepted
                            else "grau de liberdade liberado ou sem caminho de rigidez" if stiffnesses[name] <= 0.0
                            else "contenção elástica de torção em compressão não qualificada" if allowed is not None and name not in allowed
                            else "rigidez disponível inferior à necessária")}
                for name in sorted(stations, key=lambda name: (stations[name], name))
            ],
        }

    def lengths(self, element, results, properties, cb=1.0) -> RestraintLengths:
        bars, basis, stations, length = self._chain(element)
        matrix = self._external_matrix(set(element.member_names))
        # Bending about local y displaces local z; bending about z displaces y.
        stiffnesses = {
            "Ly": self._directional_stiffnesses(matrix, stations, basis[2]),
            "Lz": self._directional_stiffnesses(matrix, stations, basis[1]),
            "Lt": self._directional_stiffnesses(matrix, stations, basis[0], rotation=True),
        }
        for mode, dof in (("Ly", 2), ("Lz", 1), ("Lt", 3)):
            for name in stations:
                connection = self._connection_stiffness(bars, name, dof)
                if connection == 0.0:
                    stiffnesses[mode][name] = 0.0
                elif connection < inf:
                    external = stiffnesses[mode][name]
                    stiffnesses[mode][name] = 1.0 / (1.0 / external + 1.0 / connection) if external > 0.0 else 0.0
        samples = [sample for result in results for name in element.member_names
                   for sample in result.member_results[name].get("samples", ())]
        compression = max((max(0.0, -float(s.get("axial", 0.0))) for s in samples), default=0.0)
        major_moment = max((abs(float(s.get("moment_y", 0.0))) for s in samples), default=0.0)

        def column_minimum(count, span):
            return 2.0 * (4.0 - 2.0 / count) * GAMMA_R * compression / span

        modes = {mode: self._mode(stations, length, stiffnesses[mode], column_minimum)
                 for mode in ("Ly", "Lz")}
        # No warping DOF or column torsional-restraint qualification is present
        # in the frame model. Do not silently turn a finite rotation spring into
        # an ideal torsional brace for the compression formula of 5.3.5.1.
        ideal_twist = {name for name, stiffness in stiffnesses["Lt"].items() if stiffness == inf}
        modes["Lt"] = self._mode(stations, length, stiffnesses["Lt"], lambda _n, _l: 0.0,
                                 allowed=ideal_twist if compression > 0.0 else None)

        material = self.model.materials[bars[0].material]
        elastic = float(material[0])
        iy_minor_m4 = properties["Iy"] * 1e-8
        tw_m = properties["tw"] / 100.0
        # 4.12.3.6: no transverse stiffeners are defined in the current model.
        section_stiffness = 3.3 * elastic * 1.5 * tw_m**3 / 12.0

        def beam_minimum(count, _span):
            st = 2.4 * GAMMA_R * length * major_moment**2 / (count * elastic * iy_minor_m4 * cb**2)
            return st / (1.0 - st / section_stiffness) if st < section_stiffness else inf

        modes["Lb"] = self._mode(stations, length, stiffnesses["Lt"], beam_minimum)
        issues = []
        if compression > 0.0:
            for mode in ("Ly", "Lz", "Lt"):
                if not modes[mode]["endpoints_restrained"]:
                    issues.append(f"{mode}: contenção nas extremidades não comprovada para compressão")
        if major_moment > 0.0:
            if not modes["Lb"]["endpoints_restrained"]:
                issues.append("Lb: contenção de torção nos apoios não comprovada")
            lateral = self._mode(stations, length, stiffnesses["Lz"], lambda _n, _l: 0.0)
            if not lateral["endpoints_restrained"]:
                issues.append("Lb: contenção lateral nos apoios não comprovada")
        for mode, dof, applicable in (("Ly", 4, compression > 0.0), ("Lz", 5, compression > 0.0),
                                      ("Lt", 3, compression > 0.0), ("Lb", 3, major_moment > 0.0)):
            if not applicable:
                continue
            accepted = {point["node"] for point in modes[mode]["points"] if point["accepted"]}
            for name, position in stations.items():
                if name in accepted or not 1e-9 < position < length - 1e-9:
                    continue
                if self._connection_stiffness(bars, name, dof) < inf:
                    issues.append(f"{mode}: ligação interna liberada ou semirrígida em {name} sem contenção comprovada")
        notes = [
            "Resistência das contenções, ligações e ancoragens pendente de verificação (NBR 8800, 4.12).",
            "Lb considera contenções de torção. Ligações na mesa comprimida não são identificáveis pelo modelo de eixo central.",
            "Distorção da alma calculada sem enrijecedores transversais, que não estão definidos no modelo.",
            "Maior intervalo adotado separadamente para cada modo; um nó de subdivisão ou momento nulo não é contenção.",
            "Sistemas que contenham vários elementos exigem verificação conjunta da rigidez e da resistência das contenções.",
        ]
        if compression > 0.0 and any(0.0 < value < inf for value in stiffnesses["Lt"].values()):
            notes.append("Lt em compressão: molas de torção finitas não reduzem o comprimento; falta análise de estabilidade com empenamento.")
        return RestraintLengths({mode: data["length_m"] for mode, data in modes.items()},
                                modes, tuple(issues), tuple(notes))
