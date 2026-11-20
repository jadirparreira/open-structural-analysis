"""Coupled four-field MLE section kernel on a continuous rounded mean line.

Positive forces produce compression: [N,My,Mz,Bc], with basis [1,z,-y,omega].
The tension-positive bimoment B=-ECw theta'' therefore supplies Bc=-B.
This kernel does not, by itself, approve an ELS from another geometry model.
"""
from dataclasses import dataclass
from math import asin, atan2, hypot, isfinite, pi

import numpy as np

from osa.sections.thin_walled import rounded_sectorial_field
from osa.verification.cold_formed_effective import _intervals, _merged


@dataclass(frozen=True)
class EffectiveWarpingSection:
    field: object
    normal_matrix: tuple[tuple[float, ...], ...]
    stress_coefficients: tuple[float, ...]
    intervals: dict
    iterations: int
    maximum_stress_mpa: float
    notes: tuple[str, ...]


def maximum_warping_fiber_stress(field, coefficients, *, piece_indices=None, include_faces=True):
    """Exact extrema of the thin-wall field at both normal bending faces.

    The sectorial stress is constant through thickness. Along a circular
    bend its derivative is A sin(theta)+B cos(theta)+C, so all stationary
    points are included explicitly, without relying on a plotting mesh.
    """
    coefficients = np.asarray(coefficients, dtype=float)
    if coefficients.shape != (4,) or not np.all(np.isfinite(coefficients)):
        raise ValueError('Coeficientes normais/setoriais inválidos.')
    gradient = np.array((-coefficients[2], coefficients[1]))
    cw = coefficients[3]
    values = []
    for index, piece in enumerate(field.sheet.pieces):
        if piece_indices is not None and index not in piece_indices:
            continue
        for face in ((-1., 1.) if include_faces else (0.,)):
            fractions = [0., 1.]
            if piece.center is not None:
                radius = np.linalg.norm(np.asarray(piece.start)-piece.center)
                cy, cz = piece.center
                gy, gz = gradient
                ay, az = field.affine[1:]
                side = 1 if piece.turn > 0 else -1
                a = radius*(-gy+cw*ay+cw*cz)+face*side*field.sheet.thickness/2*gy
                b = radius*(gz-cw*az+cw*cy)-face*side*field.sheet.thickness/2*gz
                c = cw*radius**2
                magnitude = hypot(a, b)
                if magnitude > 0 and abs(c) <= magnitude:
                    root, phase = asin(np.clip(-c/magnitude, -1., 1.)), atan2(b, a)
                    start = atan2(piece.start[1]-cz, piece.start[0]-cy)
                    for angle in (root-phase, pi-root-phase):
                        delta = ((angle-start) % (2*pi)) if piece.turn > 0 else -((start-angle) % (2*pi))
                        fraction = delta/piece.turn
                        if 0 < fraction < 1:
                            fractions.append(fraction)
            for fraction in fractions:
                tangent = piece.tangent(fraction)
                normal = np.array((-tangent[1], tangent[0]))
                values.append(float(field.basis(index, fraction)@coefficients+
                    face*field.sheet.thickness/2*(gradient@normal)))
    return max(abs(value) for value in values)


def _plate_coefficients(field, coefficients):
    output = {}
    origin = np.asarray(field.origin_mm)
    for index, piece in enumerate(field.sheet.pieces):
        if piece.center is not None:
            continue
        tangent = piece.tangent(0.)
        slope = (field.omega(index, 1.)-field.omega(index, 0.))/piece.length
        gradient = slope*tangent
        intercept = field.omega(index, 0.)-gradient@(np.asarray(piece.start)-origin)
        output[piece.plate] = coefficients[:3]+coefficients[3]*np.array((intercept, gradient[1], -gradient[0]))
    return output


def _solve(matrix, loads):
    diagonal = np.sqrt(np.diag(matrix))
    if not np.all(np.isfinite(diagonal)) or np.any(diagonal <= 0):
        raise ValueError('Seção sem rigidez normal/setorial suficiente.')
    scaled = matrix/np.outer(diagonal, diagonal)
    try:
        # Cholesky also rejects rank loss; no pseudoinverse silently drops B.
        factor = np.linalg.cholesky(scaled)
        if min(np.diag(factor)**2) <= 1e-12:
            raise ValueError('Rigidez normal/setorial numericamente singular.')
        return np.linalg.solve(factor.T, np.linalg.solve(factor, loads/diagonal))/diagonal
    except np.linalg.LinAlgError as exc:
        raise ValueError('Seção efetiva normal/setorial singular.') from exc



def normal_matrix_change(updated, previous):
    """Largest relative change of strain energy, invariant to normal units."""
    updated, previous = np.asarray(updated, dtype=float), np.asarray(previous, dtype=float)
    scale = np.sqrt(np.diag(previous))
    factor = np.linalg.cholesky(previous/np.outer(scale, scale))
    delta = (updated-previous)/np.outer(scale, scale)
    left = np.linalg.solve(factor, delta)
    normalized = np.linalg.solve(factor, left.T).T
    return float(max(abs(np.linalg.eigvalsh((normalized+normalized.T)/2))))

def effective_warping_section(sheet, E, forces, *, nominal_lip=None, normal_origin=None, tolerance=1e-7, maximum_iterations=200):
    """Iterate actual normal equilibrium including the sectorial resultant.

    Retained flats follow 9.2.2/9.2.3 using the full linear stress on each
    plate; mean-line bends remain effective. Couplings are retained in the
    complete Gram matrix, rather than replacing it by four independent
    inertias. All normal resultants refer to the gross centroid/pole datum.
    """
    loads = np.asarray(forces, dtype=float)
    if not isfinite(E) or E <= 0 or loads.shape != (4,) or not np.all(np.isfinite(loads)):
        raise ValueError('Informe E positivo e N, My, Mz e bimomento finitos.')
    if not isfinite(tolerance) or tolerance <= 0 or maximum_iterations < 1:
        raise ValueError('Critérios de convergência inválidos.')
    field = rounded_sectorial_field(sheet, normal_origin=normal_origin)
    intervals = {piece.plate: ((0., 1.),) for piece in sheet.pieces if piece.center is None}
    basis, weights = field.quadrature()
    gross = basis.T@(weights[:, None]*basis)
    scaling = np.sqrt(np.diag(gross))
    matrix, coefficients = gross.copy(), np.zeros(4)
    for iteration in range(1, maximum_iterations+1):
        new_coefficients = _solve(matrix, loads)
        relaxed = new_coefficients if iteration == 1 else .5*(coefficients+new_coefficients)
        updated, notes = _intervals(sheet, relaxed[:3], np.asarray(field.origin_mm), E, nominal_lip,
                                   plate_coefficients=_plate_coefficients(field, relaxed))
        retained, area_weights = field.quadrature(updated)
        next_matrix = retained.T@(area_weights[:, None]*retained)
        matrix_error = np.max(abs(next_matrix-matrix)/np.outer(scaling, scaling))
        stress_error = max(abs(basis@(relaxed-coefficients)))/max(1., max(abs(basis@relaxed)))
        intervals, matrix, coefficients = updated, next_matrix, relaxed
        if matrix_error < tolerance and stress_error < tolerance:
            # Return exact equilibrium for the final retained cross-section.
            coefficients = _solve(matrix, loads)
            return EffectiveWarpingSection(field, tuple(tuple(float(v) for v in row) for row in matrix),
                tuple(float(v) for v in coefficients), intervals, iteration,
                maximum_warping_fiber_stress(field, coefficients), notes)
    raise ValueError('A seção efetiva com empenamento não convergiu; o último iterado não é aprovado.')


@dataclass(frozen=True)
class EffectiveWarpingEnvelope:
    field: object
    normal_matrix: tuple[tuple[float, ...], ...]
    intervals: dict
    stress_coefficients: tuple[tuple[float, ...], ...]
    maximum_stress_mpa: float
    iterations: int
    notes: tuple[str, ...]


def _intersection(left, right):
    return _merged([(max(a, c), min(b, d)) for a, b in left for c, d in right if min(b, d) > max(a, c)+1e-14], 1.)


def effective_warping_envelope(sheet, E, patterns, *, normal_origin=None, nominal_lip=None,
                               retained_limit=None, tolerance=1e-7, maximum_iterations=200, sectorial_mode=True):
    """Common retained material for all concomitant patterns along a member.

    Material removed by any pattern stays removed. Intersecting actual
    intervals preserves a positive-semidefinite material reduction, including
    all normal/sectorial couplings, rather than taking unrelated minima of
    inertia entries. The optional limit retains the previous structural
    iteration's removed material when the forces redistribute.
    """
    loads = np.asarray(patterns, dtype=float)
    modes = 4 if sectorial_mode else 3
    if not isfinite(E) or E <= 0 or loads.ndim != 2 or loads.shape[1] != modes or len(loads) == 0 or not np.all(np.isfinite(loads)):
        raise ValueError('Padrões concomitantes de serviço inválidos.')
    if not isfinite(tolerance) or tolerance <= 0 or not isinstance(maximum_iterations, int) or maximum_iterations < 1:
        raise ValueError('Critérios de convergência inválidos.')
    field = rounded_sectorial_field(sheet, normal_origin=normal_origin)
    intervals = {piece.plate: ((0., 1.),) for piece in sheet.pieces if piece.center is None}
    if retained_limit is not None:
        if set(retained_limit) != set(intervals):
            raise ValueError('Limite de material efetivo incompatível com as paredes.')
        for index, full in intervals.items():
            previous = tuple(tuple(float(v) for v in pair) for pair in retained_limit[index])
            if any(len(pair) != 2 or not all(isfinite(v) for v in pair) or not 0 <= pair[0] < pair[1] <= 1 for pair in previous):
                raise ValueError('Intervalos efetivos inválidos.')
            intervals[index] = _intersection(full, previous)
    retained, weights = field.quadrature(intervals)
    retained = retained[:, :modes]
    matrix = retained.T@(weights[:, None]*retained)
    all_notes = []
    for iteration in range(1, maximum_iterations+1):
        coefficients = tuple(_solve(matrix, load) for load in loads)
        updated = dict(intervals)
        for values in coefficients:
            required, notes = _intervals(sheet, values[:3], np.asarray(field.origin_mm), E, nominal_lip,
                                        plate_coefficients=_plate_coefficients(field, values) if sectorial_mode else None)
            all_notes.extend(notes)
            updated = {index: _intersection(updated[index], required[index]) for index in updated}
        retained, weights = field.quadrature(updated)
        retained = retained[:, :modes]
        next_matrix = retained.T@(weights[:, None]*retained)
        error = normal_matrix_change(next_matrix, matrix)
        intervals, matrix = updated, next_matrix
        if error < tolerance:
            coefficients = tuple(tuple(float(v) for v in _solve(matrix, load)) for load in loads)
            return EffectiveWarpingEnvelope(field, tuple(tuple(float(v) for v in row) for row in matrix), intervals,
                coefficients, max(maximum_warping_fiber_stress(field, values if sectorial_mode else (*values, 0.)) for values in coefficients),
                iteration, tuple(dict.fromkeys(all_notes)))
    raise ValueError('A envoltória de seção efetiva com empenamento não convergiu.')


@dataclass(frozen=True)
class NormalWidthProposal:
    """One constitutive proposal; only a global solve can accept the state."""
    field: object
    normal_matrix: tuple[tuple[float, ...], ...]
    intervals: dict
    maximum_stress_mpa: float
    notes: tuple[str, ...]
    iterations: int = 1


def effective_normal_update(sheet, E, patterns, *, normal_origin=None, nominal_lip=None,
                            retained_limit=None, sectorial_mode=True):
    """Update widths once from the currently applied section/force state.

    Holding the forces fixed through a complete local iteration can miss
    redistribution imposed by joint restraints or other members. This
    function deliberately returns a proposal, without a checked status.
    """
    modes = 4 if sectorial_mode else 3
    loads = np.asarray(patterns, dtype=float)
    if not isfinite(E) or E <= 0 or loads.ndim != 2 or loads.shape[1] != modes or not len(loads) or not np.all(np.isfinite(loads)):
        raise ValueError('Padrões concomitantes de atualização inválidos.')
    field = rounded_sectorial_field(sheet, normal_origin=normal_origin)
    intervals = {piece.plate: ((0., 1.),) for piece in sheet.pieces if piece.center is None}
    if retained_limit is not None:
        if set(retained_limit) != set(intervals):
            raise ValueError('Limite de material efetivo incompatível com as paredes.')
        for index, full in intervals.items():
            previous = tuple(tuple(float(v) for v in pair) for pair in retained_limit[index])
            if any(len(pair) != 2 or not all(isfinite(v) for v in pair) or not 0 <= pair[0] < pair[1] <= 1 for pair in previous):
                raise ValueError('Intervalos efetivos inválidos.')
            intervals[index] = _intersection(full, previous)
    basis, weights = field.quadrature(intervals)
    normal = basis[:, :modes]
    matrix = normal.T@(weights[:, None]*normal)
    updated, notes, maximum = dict(intervals), [], 0.
    for load in loads:
        coefficients = _solve(matrix, load)
        stress = maximum_warping_fiber_stress(field, coefficients if sectorial_mode else (*coefficients, 0.))
        maximum = max(maximum, stress)
        required, advisories = _intervals(sheet, coefficients[:3], np.asarray(field.origin_mm), E, nominal_lip,
            plate_coefficients=_plate_coefficients(field, coefficients) if sectorial_mode else None)
        notes.extend(advisories)
        updated = {index: _intersection(updated[index], required[index]) for index in updated}
    basis, weights = field.quadrature(updated)
    normal = basis[:, :modes]
    matrix = normal.T@(weights[:, None]*normal)
    return NormalWidthProposal(field, tuple(map(tuple, matrix)), updated, maximum, tuple(dict.fromkeys(notes)))
