"""Effective widths and iterative open-sheet properties, NBR 14762 9.2.

Compression is positive. Dimensions are mm and stress is N/mm². Retained
intervals are geometric portions of each flat plate; bends remain effective.
The MRD resistance path does not apply these reductions a second time.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, isfinite, pi, sin, sqrt

import numpy as np

from osa.sections.thin_walled import OpenSheet


@dataclass(frozen=True)
class EffectivePlate:
    intervals: tuple[tuple[float, float], ...]
    coefficient: float
    slenderness: float
    effective_width: float
    reference: str


def _merged(intervals, width):
    clipped = sorted((max(0., a), min(width, b)) for a, b in intervals if b > a)
    result = []
    for a, b in clipped:
        if b <= a:
            continue
        if result and a <= result[-1][1]+1e-10:
            result[-1] = result[-1][0], max(b, result[-1][1])
        else:
            result.append((a, b))
    return tuple(result)


def width_reduction(slenderness):
    if not isfinite(slenderness) or slenderness < 0:
        raise ValueError("Esbeltez de placa inválida.")
    return 1. if slenderness <= .673 else (1-.22/slenderness)/slenderness


def effective_plate(width, thickness, E, stress_start, stress_end, *, supported_both=True, free_start=False):
    """Tables 5/6: return actual retained intervals measured from start."""
    if not all(isfinite(value) and value > 0 for value in (width, thickness, E)):
        raise ValueError("Largura, espessura e E devem ser positivos e finitos.")
    if not all(isfinite(value) for value in (stress_start, stress_end)):
        raise ValueError("Tensões de placa inválidas.")
    maximum = max(stress_start, stress_end)
    reference = "9.2.2, Tabela "+("5" if supported_both else "6")
    if maximum <= 0:
        return EffectivePlate(((0., width),), 0., 0., width, reference)
    if supported_both:
        reverse = stress_end > stress_start
        other = min(stress_start, stress_end)
        psi = other/maximum
        k = 4.+2*(1-psi)+2*(1-psi)**3
        slenderness = width/thickness/(.95*sqrt(k*E/maximum))
        effective = width*width_reduction(slenderness)
        compressed = width if psi >= 0 else width/(1-psi)
        first = min(compressed, effective/(3-psi))
        second = min(compressed-first, effective-first if psi > -.236 else .5*effective)
        intervals = [(0., first), ((width if psi >= 0 else compressed)-second,
                                  width if psi >= 0 else compressed)]
        if psi < 0:
            intervals.append((compressed, width))
        if reverse:
            intervals = [(width-b, width-a) for a, b in intervals]
    else:
        # Orient s from connected to free edge; the effective compressed
        # width stays adjacent to the connected/tension-effective portion.
        root, tip = (stress_end, stress_start) if free_start else (stress_start, stress_end)
        other = min(root, tip)
        psi = other/maximum
        maximum_at_free = tip > root
        if psi < -1:
            # The tabulated AL gradient stops at -1. A full-width uniform
            # compression field at the maximum compression gives a lower
            # elastic plate bound; retain the tensioned portion in full.
            k = .43
            reference += "; limite conservador de compressão uniforme para ψ<−1"
        elif abs(root-tip) <= 1e-9*max(1., maximum):
            k = .43
        elif maximum_at_free:
            k = .57-.21*psi+.07*psi*psi
        elif psi >= 0:
            k = .578/(psi+.34)
        else:
            k = 1.7-5*psi+17.1*psi*psi
        slenderness = width/thickness/(.95*sqrt(k*E/maximum))
        compressed = width if psi >= 0 else width/(1-psi)
        effective = compressed*width_reduction(slenderness)
        if maximum_at_free and psi < 0:
            tensile = width-compressed
            intervals = [(0., tensile+effective)]
        else:
            intervals = [(0., effective)]
            if psi < 0:
                intervals.append((compressed, width))
        if free_start:
            intervals = [(width-b, width-a) for a, b in intervals]
    retained = _merged(intervals, width)
    return EffectivePlate(retained, k, slenderness, sum(b-a for a, b in retained), reference)


def stiffened_flange(width, lip_width, nominal_lip, thickness, angle, E, stress, lip_effective):
    """Uniformly compressed simple edge stiffener, 9.2.3.1 (angle radians)."""
    if not 40*np.pi/180 <= angle <= 140*np.pi/180:
        raise ValueError("Enrijecedor de borda fora de 40°≤θ≤140°.")
    lp0 = width/thickness/(.623*sqrt(E/stress))
    if lp0 <= .673:
        return ((width/2, width/2), lip_effective, {"lambda_p0": lp0, "Is_Ia": 1., "k": 4.})
    if nominal_lip/width > .8:
        raise ValueError("Enrijecedor de borda fora de D/b≤0,8.")
    inertia = thickness*lip_width**3*sin(angle)**2/12
    required = min(399*thickness**4*(.487*lp0-.328)**3, thickness**4*(56*lp0+5))
    ratio = min(1., inertia/required) if required > 0 else 1.
    exponent = max(.582-.122*lp0, 1/3)
    base = 3.57 if nominal_lip/width <= .25 else 4.82-5*nominal_lip/width
    k = min(4., base*ratio**exponent+.43)
    lp = width/thickness/(.95*sqrt(k*E/stress))
    effective = width*width_reduction(lp)
    first = ratio*effective/2
    return ((first, effective-first), ratio*lip_effective,
            {"lambda_p0": lp0, "Is_Ia": ratio, "Is_mm4": inertia, "Ia_mm4": required, "k": k})


@dataclass(frozen=True)
class EffectiveSection:
    area_mm2: float
    centroid_mm: tuple[float, float]
    iy_mm4: float
    iz_mm4: float
    iyz_mm4: float
    intervals: dict
    stress_coefficients: tuple[float, float, float]
    load_factor: float
    iterations: int
    notes: tuple[str, ...]


def _points_weights(sheet, intervals, origin):
    xi, wi = np.polynomial.legendre.leggauss(8)
    points, weights = [], []
    for piece in sheet.pieces:
        portions = ((0., 1.),) if piece.center is not None else intervals[piece.plate]
        for start, end in portions:
            for fraction, weight in zip(start+(xi+1)/2*(end-start), wi/2*(end-start), strict=True):
                points.append(piece.point(fraction)-origin)
                weights.append(weight*piece.length*sheet.thickness)
    return np.asarray(points), np.asarray(weights)


def _intervals(sheet, coefficients, origin, E, nominal_lip, *, plate_coefficients=None):
    flat = {piece.plate: piece for piece in sheet.pieces if piece.center is None}
    intervals, effective, stresses = {}, {}, {}
    notes = []
    for index, piece in flat.items():
        a, b = np.asarray(piece.start)-origin, np.asarray(piece.end)-origin
        local_coefficients = coefficients if plate_coefficients is None else plate_coefficients[index]
        sa, sb = (float(np.array((1., p[1], -p[0]))@local_coefficients) for p in (a, b))
        normal = np.array((-piece.tangent(0.)[1], piece.tangent(0.)[0]))
        thickness_stress = abs(np.array((-local_coefficients[2], local_coefficients[1]))@normal)*sheet.thickness/2
        sa, sb = sa+thickness_stress, sb+thickness_stress
        al = index in {0, len(sheet.roles)-1}
        # Under a flange gradient the simple-stiffener formula 9.2.3 does
        # not apply: conservatively ignore the favourable lip restraint.
        adjacent_lip = (index > 0 and sheet.roles[index-1] == 'lip') or (index+1 < len(sheet.roles) and sheet.roles[index+1] == 'lip')
        if adjacent_lip:
            al = True
        free_start = index == 0 or (adjacent_lip and sheet.roles[index-1] == 'lip')
        result = effective_plate(piece.length, sheet.thickness, E, sa, sb,
                                 supported_both=not al, free_start=free_start)
        intervals[index] = tuple((a/piece.length, b/piece.length) for a, b in result.intervals)
        effective[index], stresses[index] = result, (sa, sb)
    if nominal_lip is not None:
        for index, piece in flat.items():
            if piece.role != 'flange':
                continue
            lip_index = index-1 if index > 0 and sheet.roles[index-1] == 'lip' else index+1
            if lip_index not in flat or flat[lip_index].role != 'lip':
                continue
            sa, sb = stresses[index]
            if max(sa, sb) <= 0:
                continue
            if abs(sa-sb) > 1e-5*max(abs(sa), abs(sb), 1.) or min(stresses[lip_index]) < 0:
                notes.append("Mesa com gradiente de tensão: contribuição favorável do enrijecedor de borda desprezada; mesa tratada como AL.")
                continue
            lip = flat[lip_index]
            v, u = np.asarray(piece.end)-piece.start, np.asarray(lip.end)-lip.start
            angle = np.arccos(np.clip(abs(v@u)/(np.linalg.norm(v)*np.linalg.norm(u)), -1., 1.))
            try:
                (b1, b2), ds, _ = stiffened_flange(piece.length, lip.length, nominal_lip, sheet.thickness,
                                                  angle, E, max(sa, sb), effective[lip_index].effective_width)
            except ValueError:
                notes.append("Enrijecedor fora do domínio de 9.2.3: contribuição favorável desprezada; mesa tratada como AL.")
                continue
            if lip_index > index:
                b1, b2 = b2, b1
            intervals[index] = tuple((a/piece.length, b/piece.length) for a, b in _merged(
                [(0., b1), (piece.length-b2, piece.length)], piece.length))
            intervals[lip_index] = ((1-ds/lip.length, 1.),) if lip_index == 0 else ((0., ds/lip.length),)
    return intervals, tuple(dict.fromkeys(notes))


def maximum_fiber_stress(sheet, coefficients, origin):
    """Exact extrema on both faces of the circular/straight sheet pieces."""
    gradient = np.array((-coefficients[2], coefficients[1]))
    values = []
    for piece in sheet.pieces:
        fractions = [0., 1.]
        if piece.center is not None and np.linalg.norm(gradient) > 0:
            start = atan2(piece.start[1]-piece.center[1], piece.start[0]-piece.center[0])
            direction = atan2(gradient[1], gradient[0])
            for angle in (direction, direction+pi):
                delta = ((angle-start) % (2*pi)) if piece.turn > 0 else -((start-angle) % (2*pi))
                fraction = delta/piece.turn
                if 0 < fraction < 1:
                    fractions.append(fraction)
        for fraction in fractions:
            point, tangent = piece.point(fraction)-origin, piece.tangent(fraction)
            normal = np.array((-tangent[1], tangent[0]))
            mid = coefficients[0]+gradient@point
            values.extend((mid+sheet.thickness/2*(gradient@normal), mid-sheet.thickness/2*(gradient@normal)))
    return max(abs(value) for value in values)


def effective_section(sheet: OpenSheet, E, forces, *, yield_stress=None, nominal_lip=None,
                      uniform_stress=None, bending_plane=None, tolerance=1e-6, maximum_iterations=150):
    """Iterate effective properties under actual service resultants or yield.

    forces=[N,My,Mz], in N and N mm, refer to the gross centroid. A supplied
    yield_stress scales that load pattern to first yield. uniform_stress is
    the separate uniform-compression construction used by 9.7.2(a).
    """
    if not isfinite(E) or E <= 0:
        raise ValueError("Módulo E inválido para seção efetiva.")
    loads = np.asarray(forces, dtype=float)
    if loads.shape != (3,) or not np.all(np.isfinite(loads)):
        raise ValueError("Informe N, My e Mz finitos para a seção efetiva.")
    if bending_plane not in (None, 'y', 'z'):
        raise ValueError("Plano de flexão inválido.")
    if bending_plane is not None and loads[2 if bending_plane == 'y' else 1] != 0:
        raise ValueError("O plano impedido não pode receber um momento independente.")
    gross_points, gross_weights = sheet.quadrature()
    origin = np.sum(gross_weights[:, None]*gross_points, axis=0)/sum(gross_weights)
    flat = {piece.plate: piece for piece in sheet.pieces if piece.center is None}
    intervals = dict.fromkeys(flat, ((0., 1.),))
    coefficients = np.zeros(3)
    factor, notes = 1., ()
    if yield_stress is not None and (not isfinite(yield_stress) or yield_stress <= 0 or not np.any(loads)):
        raise ValueError("Escoamento exige tensão positiva e padrão de esforços não nulo.")
    if uniform_stress is not None and (not isfinite(uniform_stress) or uniform_stress < 0):
        raise ValueError("A tensão uniforme deve ser finita e não negativa.")
    for iteration in range(1, maximum_iterations+1):
        points, weights = _points_weights(sheet, intervals, origin)
        basis = np.column_stack((np.ones(len(points)), points[:, 1], -points[:, 0]))
        matrix = basis.T@(weights[:, None]*basis)
        if uniform_stress is not None:
            new_coefficients = np.array((uniform_stress, 0., 0.))
        elif bending_plane is not None:
            # A physically restrained bending plane can develop the other
            # moment as a reaction. This option is explicit, never inferred.
            ids = (0, 1 if bending_plane == 'y' else 2)
            new_coefficients = np.zeros(3)
            new_coefficients[list(ids)] = np.linalg.solve(matrix[np.ix_(ids, ids)], loads[list(ids)])
        else:
            new_coefficients = np.linalg.solve(matrix, loads)
        if yield_stress is not None:
            factor = yield_stress/maximum_fiber_stress(sheet, new_coefficients, origin)
            new_coefficients *= factor
        relaxed = new_coefficients if iteration == 1 else .5*(coefficients+new_coefficients)
        updated, notes = _intervals(sheet, relaxed, origin, E, nominal_lip)
        old_area = float(weights.sum())
        next_points, next_weights = _points_weights(sheet, updated, origin)
        error = abs(next_weights.sum()/old_area-1)
        stress_error = np.linalg.norm(relaxed-coefficients)/max(1., np.linalg.norm(relaxed))
        intervals, coefficients = updated, relaxed
        if error < tolerance and stress_error < tolerance:
            break
    else:
        raise ValueError("A seção efetiva não convergiu; não se utiliza o último iterado como resistência.")
    area = float(next_weights.sum())
    centroid = np.sum(next_points*next_weights[:, None], axis=0)/area
    coordinates = next_points-centroid
    return EffectiveSection(area, tuple(centroid+origin),
        float(next_weights@(coordinates[:, 1]**2)), float(next_weights@(coordinates[:, 0]**2)),
        float(next_weights@(coordinates[:, 0]*coordinates[:, 1])), intervals, tuple(coefficients),
        float(factor), iteration, notes)
