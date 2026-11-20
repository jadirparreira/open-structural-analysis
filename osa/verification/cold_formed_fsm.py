"""Elastic finite-strip stability analysis for open cold-formed sections.

The analysis uses an explicit thin-wall centreline with rounded bends
and solves the plate-strip
eigenproblem for a logarithmic range of longitudinal half-wavelengths.
Mode shapes receive a geometric screen; ambiguous mixed modes are explicit.
This screen is not a quantitative constrained-FSM decomposition.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from math import isfinite, pi

import numpy as np
from scipy.linalg import eigh, qr
from scipy.optimize import minimize_scalar

from osa.sections.properties import calculate_section_properties
from osa.sections.thin_walled import open_sheet

# Cubic Hermite deflections squared times linear prestress have degree 7.
# Four Gauss points integrate both elastic and geometric matrices exactly.
_GAUSS_X = (0.0694318442029737, 0.330009478207572, 0.669990521792428, 0.930568155797026)
_GAUSS_W = (0.173927422568727, 0.326072577431273, 0.326072577431273, 0.173927422568727)
_DOF_PER_NODE = 4


@dataclass(frozen=True, slots=True)
class ElasticCritical:
    value: float
    half_wave_mm: float
    mode: str
    sign: int
    assessment: ModeShapeAssessment | None = None


def _centerline(family, geometry, mirror=False, divisions=8):
    return open_sheet(family, geometry, mirror=mirror).mesh(divisions=divisions)[0]


def _fold_nodes(points):
    folds = []
    for i in range(1, len(points) - 1):
        p, q, r = points[i - 1:i + 2]
        a = np.asarray(q - p); b = np.asarray(r - q)
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na <= 1e-12 or nb <= 1e-12:
            continue
        angle = np.arccos(np.clip(float(a @ b) / (na * nb), -1.0, 1.0))
        if angle >= np.deg2rad(12.0):
            folds.append(i)
    return folds


@dataclass(frozen=True, slots=True)
class ModeShapeAssessment:
    """Geometric screening indicators, not cFSM modal participation factors."""
    mode: str
    rigid_residual: float
    fold_ratio: float
    fold_nonrigid_residual: float


def _transverse_metric(points):
    """L² of the actual strip displacement (linear tangent/cubic normal).

    Arc chords keep their own rotations. Unlike an unweighted nodal norm,
    straight-panel subdivision does not change this displacement measure.
    """
    n = len(points)
    metric = np.zeros((8*(n-1), 4*n))
    for i, (a, b) in enumerate(pairwise(points)):
        width = float(np.linalg.norm(b-a))
        c, s = (b-a)/width
        for j, (xi, weight) in enumerate(zip(_GAUSS_X, _GAUSS_W, strict=True)):
            row = 8*i+2*j
            scale = np.sqrt(width*weight)
            h = (1-3*xi**2+2*xi**3, width*(xi-2*xi**2+xi**3),
                 3*xi**2-2*xi**3, width*(xi**3-xi**2))
            # Tangent/normal coordinates preserve the Euclidean norm.
            for node, linear, transverse, rotation in ((i, 1-xi, h[0], h[1]), (i+1, xi, h[2], h[3])):
                metric[row, 4*node+1:4*node+3] = scale*linear*np.array((c, s))
                metric[row+1, 4*node+1:4*node+3] = scale*transverse*np.array((-s, c))
                metric[row+1, 4*node+3] = scale*rotation
    rigid = np.zeros((4*n, 3))
    center = np.mean(points, axis=0)
    rigid[1::4, 0], rigid[2::4, 1] = 1., 1.
    rigid[1::4, 2], rigid[2::4, 2] = -(points[:, 1]-center[1]), points[:, 0]-center[0]
    rigid[3::4, 2] = 1.
    basis = qr(metric@rigid, mode='economic')[0]
    return metric, basis


def assess_mode(points, vector, *, folds=None, metric=None):
    """Screen rigid, panel-local and fold-distortional transverse motion.

    The full-section fit is authoritative for a global label: rigid fold
    motion alone cannot hide a deforming panel. Ambiguous combinations are
    exposed as mixed; these indicators are not a constrained-FSM basis.
    """
    vector = np.asarray(vector, dtype=float).reshape(-1)
    if vector.shape != (4*len(points),) or not np.all(np.isfinite(vector)):
        raise ValueError('Deformada modal incompleta ou não finita.')
    amplitude = float(np.max(abs(vector), initial=0.))
    if amplitude == 0:
        return ModeShapeAssessment('indeterminado', 1., 0., 1.)
    vector = vector/amplitude
    nodal = vector.reshape((-1, 4))
    disp = nodal[:, (1, 2)]
    metric, rigid_basis = _transverse_metric(points) if metric is None else metric
    target = metric@vector
    norm = float(np.linalg.norm(target))
    if norm == 0:
        return ModeShapeAssessment('indeterminado', 1., 0., 1.)
    residual = float(np.linalg.norm(target-rigid_basis@(rigid_basis.T@target))/norm)
    if residual < .12:
        return ModeShapeAssessment('global', residual, 1., 0.)
    folds = _fold_nodes(points) if folds is None else list(folds)
    if not len(folds):
        return ModeShapeAssessment('indeterminado', residual, 0., 1.)
    maximum = norm/np.sqrt(float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()))
    if maximum == 0:
        return ModeShapeAssessment('local', residual, 0., 1.)
    fold_ratio = float(np.linalg.norm(disp[folds], axis=1).max(initial=0.))/maximum
    if fold_ratio < .18:
        return ModeShapeAssessment('local', residual, fold_ratio, 1.)
    xy, values = points[folds], disp[folds]
    center = xy.mean(axis=0)
    design = np.zeros((2*len(folds), 3))
    design[0::2, 0], design[1::2, 1] = 1., 1.
    design[0::2, 2], design[1::2, 2] = -(xy[:, 1]-center[1]), xy[:, 0]-center[0]
    target = values.reshape(-1)
    coefficients = np.linalg.lstsq(design, target, rcond=None)[0]
    fold_residual = float(np.linalg.norm(target-design@coefficients)/np.linalg.norm(target))
    mode = 'misto' if fold_residual < .18 else 'distorcional'
    return ModeShapeAssessment(mode, residual, fold_ratio, fold_residual)


def _classify(points, vector):
    return assess_mode(points, vector).mode


def _transform(c, s):
    # local [u1,v1,u2,v2,w1,theta1,w2,theta2] from global nodal
    # [u,Y,Z,theta], with (v,w) tangent/normal to the strip.
    t = np.zeros((8, 8))
    t[0, 0] = 1.0
    t[1, 1], t[1, 4] = c, s
    t[2, 2] = 1.0
    t[3, 3], t[3, 6] = c, s
    t[4, 1], t[4, 4] = -s, c
    t[5, 5] = 1.0
    t[6, 3], t[6, 6] = -s, c
    t[7, 7] = 1.0
    return t


def _strip_matrices(b, t, E, nu, sigma_a, sigma_b, k):
    km = np.zeros((8, 8)); kg = np.zeros((8, 8))
    dm = E * t / (1.0 - nu * nu) * np.array(((1.0, nu, 0.0), (nu, 1.0, 0.0), (0.0, 0.0, (1.0 - nu) / 2.0)))
    d0 = E * t**3 / (12.0 * (1.0 - nu * nu))
    db = d0 * np.array(((1.0, nu, 0.0), (nu, 1.0, 0.0), (0.0, 0.0, (1.0 - nu) / 2.0)))
    for xi, weight in zip(_GAUSS_X, _GAUSS_W, strict=True):
        n = np.array((1.0 - xi, xi))
        dn = np.array((-1.0 / b, 1.0 / b))
        bm = np.zeros((3, 4))
        bm[0, (0, 2)] = k * n
        bm[1, (1, 3)] = dn
        bm[2, (0, 2)] = dn
        bm[2, (1, 3)] = -k * n
        km[:4, :4] += b * weight * bm.T @ dm @ bm

        n2 = xi*xi; n3 = n2*xi
        nw = np.array((1-3*n2+2*n3, b*(xi-2*n2+n3), 3*n2-2*n3, b*(n3-n2)))
        dnw = np.array(((-6*xi+6*n2)/b, 1-4*xi+3*n2, (6*xi-6*n2)/b, 3*n2-2*xi))
        d2nw = np.array(((-6+12*xi)/(b*b), (-4+6*xi)/b, (6-12*xi)/(b*b), (6*xi-2)/b))
        bb = np.zeros((3, 4))
        bb[0] = d2nw
        bb[1] = -(k*k) * nw
        bb[2] = 2.0 * k * dnw
        km[4:, 4:] += b * weight * bb.T @ db @ bb

        sigma = sigma_a + xi * (sigma_b - sigma_a)
        # Initial-stress stiffness includes the longitudinal variation of
        # all three translational components (longitudinal, in-plane and
        # plate-normal). The common k² factor is applied in the eigenvalue.
        gu = np.array((1-xi, 0.0, xi, 0.0))
        gv = np.array((0.0, 1-xi, 0.0, xi))
        kg[:4, :4] += b * weight * t * sigma * (np.outer(gu, gu) + np.outer(gv, gv))
        kg[4:, 4:] += b * weight * t * sigma * np.outer(nw, nw)
    return km, kg


class FiniteStripSection:
    """Finite-strip eigen solver for one open, uniform-thickness section."""

    def __init__(self, family, geometry, E=200000.0, nu=0.3, mirror=False, divisions=8):
        self.family = family
        self.geometry = dict(geometry)
        self.points = _centerline(family, self.geometry, mirror, divisions)
        self.thickness = float(self.geometry["t"])
        self.E = float(E)  # N/mm²
        self.nu = float(nu)
        if not isfinite(self.E) or self.E <= 0 or not isfinite(self.nu) or not -1 < self.nu < .5:
            raise ValueError("A análise elástica exige E>0 e −1<ν<0,5, finitos.")
        self.props = calculate_section_properties(family, self.geometry, mirror_z=mirror)
        # The outline is already centroidal. Its recovered, discretized
        # centreline has slightly different integrals: use those same strip
        # integrals to centre the mesh and equilibrate the reference loads.
        weights = np.linalg.norm(np.diff(self.points, axis=0), axis=1) * self.thickness
        self.area_mm2 = float(weights.sum())
        self.centerline_centroid_mm = np.sum(
            weights[:, None] * (self.points[:-1] + self.points[1:]) / 2, axis=0,
        ) / self.area_mm2
        self.points = self.points - self.centerline_centroid_mm
        # B=[1,z,-y] gives the resultants [N,My,Mz]. Integrate B Bᵀ
        # exactly on each straight strip (a quadratic polynomial).
        self.stress_basis = np.column_stack((np.ones(len(self.points)), self.points[:, 1], -self.points[:, 0]))
        a, b = self.stress_basis[:-1], self.stress_basis[1:]
        self.resultant_matrix = np.einsum('i,ij,ik->jk', weights / 6, a, 2*a+b)
        self.resultant_matrix += np.einsum('i,ij,ik->jk', weights / 6, b, a+2*b)
        self.n = len(self.points)
        self.size = 4 * self.n
        self.fold_nodes = open_sheet(family, self.geometry, mirror=mirror).mesh(divisions=divisions)[2]
        self._transverse_metric = _transverse_metric(self.points)

    def _stresses(self, load):
        if load not in {"N", "My", "My+", "My-", "Mz", "Mz+", "Mz-"}:
            raise ValueError("Carregamento de referência inválido: use N, My ou Mz.")
        sign = -1.0 if load.endswith("-") else 1.0
        axis = load.rstrip("+-")
        resultant = np.zeros(3)
        resultant[{"N": 0, "My": 1, "Mz": 2}[axis]] = sign
        return self.stress_basis @ np.linalg.solve(self.resultant_matrix, resultant)

    def _matrices(self, half_wave, stress):
        k = pi / half_wave
        K = np.zeros((self.size, self.size)); G = np.zeros_like(K)
        for i, (a, b) in enumerate(zip(self.points, self.points[1:])):
            delta = b-a; width = float(np.linalg.norm(delta))
            if width <= 1e-9:
                continue
            km, kg = _strip_matrices(width, self.thickness, self.E, self.nu, stress[i], stress[i+1], k)
            c, s = delta / width
            T = _transform(float(c), float(s))
            kg = T.T @ kg @ T; km = T.T @ km @ T
            ids = np.array((4*i, 4*i+1, 4*(i+1), 4*(i+1)+1, 4*i+2, 4*i+3, 4*(i+1)+2, 4*(i+1)+3))
            K[np.ix_(ids, ids)] += km
            G[np.ix_(ids, ids)] += kg
        return K, G

    def modes(self, half_wave, load):
        if not isfinite(half_wave) or half_wave <= 0:
            raise ValueError("A meia-onda deve ser positiva e finita.")
        K, G = self._matrices(half_wave, self._stresses(load))
        n = len(K)
        # MRD uses low elastic criticals, which correspond to the extreme
        # generalized eigenvalues. Solving only the spectral ends avoids
        # computing the many high-order plate modes irrelevant to the minima.
        tail = min(12, n)
        if load == "N":
            values, vectors = eigh(G, K, check_finite=False, driver="gvx",
                                  subset_by_index=(n-tail, n-1))
        else:
            low_v, low_q = eigh(G, K, check_finite=False, driver="gvx",
                                subset_by_index=(0, tail-1))
            high_v, high_q = eigh(G, K, check_finite=False, driver="gvx",
                                  subset_by_index=(n-tail, n-1))
            values = np.concatenate((low_v, high_v))
            vectors = np.column_stack((low_q, high_q))
        tolerance = max(float(np.max(np.abs(values))), 1.0) * 1e-10
        out = []
        for index, mu in enumerate(values):
            if abs(mu) <= tolerance:
                continue
            sign = 1 if mu > 0 else -1
            critical = 1.0 / (abs(float(mu)) * (pi / half_wave) ** 2)
            vector = vectors[:, index]
            assessment = assess_mode(self.points, vector, folds=self.fold_nodes, metric=self._transverse_metric)
            out.append(ElasticCritical(critical, half_wave, assessment.mode, sign, assessment))
        return out

    def signature(self, load, count=32):
        lengths = np.geomspace(self.thickness * 1.5,
            20.0 * max(float(np.ptp(self.points[:, 0])), float(np.ptp(self.points[:, 1]))), count)
        branches = {mode: [] for mode in ("global", "local", "distorcional", "misto", "indeterminado")}
        for length in lengths:
            by_class = {mode: [] for mode in branches}
            for item in self.modes(float(length), load):
                if item.mode in by_class:
                    by_class[item.mode].append(item)
            for mode, values in branches.items():
                if by_class[mode]:
                    values.append(min(by_class[mode], key=lambda item: item.value))
                else:
                    values.append(None)
        return tuple(float(x) for x in lengths), branches


@lru_cache(maxsize=256)
def _cached_signature(family, geometry_items, E, nu, mirror, load):
    section = FiniteStripSection(family, dict(geometry_items), E, nu, mirror)
    return section.signature(load)


def critical_signature(family, geometry, *, E=200000.0, nu=0.3, mirror=False, load="N"):
    return _cached_signature(family, tuple(sorted((str(k), float(v)) for k, v in geometry.items())),
                             float(E), float(nu), bool(mirror), load)


@lru_cache(maxsize=256)
def _cached_minimum(family, geometry_items, E, nu, mirror, load, mode):
    lengths, branches = _cached_signature(family, geometry_items, E, nu, mirror, load)
    values = branches[mode]
    seeds = []
    # Require an actual neighbouring value in each direction; missing mode
    # samples do not form a bracket and are never bridged silently.
    for index in range(1, len(lengths)-1):
        a, b, c = values[index-1:index+2]
        if all(item is not None for item in (a, b, c)) and b.value <= min(a.value, c.value):
            seeds.append((b.value, index, b))
    if not seeds:
        return None
    section = FiniteStripSection(family, dict(geometry_items), E, nu, mirror)
    best = min(seeds, key=lambda item: item[0])[2]
    for _, index, seed in sorted(seeds)[:4]:
        def objective(log_length, penalty=seed.value*1e6):
            candidates = [item for item in section.modes(float(np.exp(log_length)), load) if item.mode == mode]
            return min((item.value for item in candidates), default=penalty)
        result = minimize_scalar(objective, bounds=(np.log(lengths[index-1]), np.log(lengths[index+1])),
                                 method="bounded", options={"xatol": .001, "maxiter": 18})
        if result.success and np.isfinite(result.fun) and result.fun <= seed.value:
            candidates = [item for item in section.modes(float(np.exp(result.x)), load) if item.mode == mode]
            refined = min(candidates, key=lambda item: item.value)
            if refined.value < best.value:
                best = refined
    ambiguous = [item for name in ('misto', 'indeterminado') for item in branches[name] if item is not None]
    if ambiguous and min(item.value for item in ambiguous) < best.value*(1-1e-6):
        witness = min(ambiguous, key=lambda item: item.value)
        raise ValueError('Modo misto/não identificado abaixo do crítico '+mode+
            f' (meia-onda {witness.half_wave_mm:.6g} mm). A triagem geométrica não separa a participação modal; '+
            'é necessária decomposição modal ou crítico externo de análise geral (Anexo C, C.2).')
    return best


def critical_minimum(family, geometry, *, E=200000., nu=.3, mirror=False, load="N", mode="local"):
    """Refine a bracketed signature minimum in logarithmic wavelength."""
    if mode not in {"local", "distorcional"}:
        raise ValueError("A busca de mínimo requer modo local ou distorcional.")
    return _cached_minimum(family, tuple(sorted((str(k), float(v)) for k, v in geometry.items())),
                           float(E), float(nu), bool(mirror), load, mode)
