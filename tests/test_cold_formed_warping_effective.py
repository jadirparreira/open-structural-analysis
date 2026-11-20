"""Four-field MLE: equilibrium, coupling, symmetry and stress extrema."""
from itertools import pairwise

import numpy as np
import pytest
from scipy.integrate import quad

from osa.sections.thin_walled import OpenSheet, WallPiece, open_sheet, rounded_sectorial_field
from osa.verification.cold_formed_effective import effective_section, maximum_fiber_stress
from osa.verification.cold_formed_warping_effective import effective_warping_section, maximum_warping_fiber_stress

FAMILIES = ('U Formado', 'C Formado', 'Z Formado', 'Z45 Formado', 'Z90 Formado', 'L Formado', 'Cartola Formado')
GEOMETRY = {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.}


@pytest.mark.parametrize('family', FAMILIES)
def test_full_effective_section_matches_normal_mle_when_sectorial_stress_is_absent(family):
    sheet = open_sheet(family, GEOMETRY)
    loads = (-100., 100., -100.)
    normal = effective_section(sheet, 200_000., loads)
    result = effective_warping_section(sheet, 200_000., (*loads, 0.))
    matrix = np.asarray(result.normal_matrix)
    assert result.intervals == normal.intervals
    assert result.stress_coefficients[:3] == pytest.approx(normal.stress_coefficients, abs=1e-10)
    assert result.stress_coefficients[3] == pytest.approx(0., abs=1e-10)
    assert matrix[0, 0] == pytest.approx(normal.area_mm2)
    assert result.maximum_stress_mpa == pytest.approx(maximum_fiber_stress(sheet, normal.stress_coefficients, result.field.centroid_mm), rel=1e-10)


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mirror', (False, True))
def test_extrema_include_all_stationary_points_on_both_faces(family, mirror):
    field = rounded_sectorial_field(open_sheet(family, GEOMETRY, mirror=mirror))
    coefficients = np.array((30., 2., -1., .02))
    expected = maximum_warping_fiber_stress(field, coefficients)
    dense = []
    for index, piece in enumerate(field.sheet.pieces):
        for fraction in np.linspace(0., 1., 301):
            normal = np.array((-piece.tangent(fraction)[1], piece.tangent(fraction)[0]))
            mid = field.basis(index, fraction)@coefficients
            offset = np.array((-coefficients[2], coefficients[1]))@normal*field.sheet.thickness/2
            dense.extend((mid-offset, mid+offset))
    assert expected >= max(abs(np.asarray(dense)))*(1-1e-12)
    assert expected == pytest.approx(max(abs(np.asarray(dense))), rel=2e-6)


def slender(mirror=False):
    return open_sheet('C Formado', {'d': 300., 'bf': 100., 'c': 25., 't': 1.5}, mirror=mirror)


def test_reduced_coupled_section_recovers_all_four_concomitant_resultants():
    loads = np.array((2000., 2e5, -5e5, 1e8))
    result = effective_warping_section(slender(), 200_000., loads, nominal_lip=26.5)
    matrix = np.asarray(result.normal_matrix)
    field = result.field
    basis, weights = field.quadrature()
    gross = basis.T@(weights[:, None]*basis)
    assert matrix[0, 0] < .99*gross[0, 0]
    assert max(abs(matrix[:3, 3])) > 1.
    # Independent adaptive integration of the final physical stress field.
    recovered = np.zeros(4)
    for index, piece in enumerate(field.sheet.pieces):
        intervals = ((0., 1.),) if piece.center is not None else result.intervals[piece.plate]
        for a, b in intervals:
            for mode in range(4):
                def integrand(fraction, index=index, mode=mode, piece=piece):
                    row = field.basis(index, fraction)
                    return row[mode]*(row@result.stress_coefficients)*piece.length*field.sheet.thickness
                recovered[mode] += quad(integrand, a, b, epsabs=1e-7)[0]
    assert recovered == pytest.approx(loads, rel=1e-9)
    diagonal = np.sqrt(np.diag(gross))
    assert min(np.linalg.eigvalsh((gross-matrix)/np.outer(diagonal, diagonal))) >= -1e-12
    assert min(np.linalg.eigvalsh(matrix/np.outer(diagonal, diagonal))) > 0.


def test_mirrored_loads_produce_mirrored_coupled_effective_matrix_and_identical_stress():
    loads = np.array((2000., 2e5, -5e5, 1e8))
    reflection = np.diag((1., 1., -1., -1.))
    normal = effective_warping_section(slender(), 200_000., loads, nominal_lip=26.5)
    mirrored = effective_warping_section(slender(True), 200_000., reflection@loads, nominal_lip=26.5)
    assert np.asarray(mirrored.normal_matrix) == pytest.approx(reflection@normal.normal_matrix@reflection, rel=1e-8, abs=1e-6)
    assert mirrored.maximum_stress_mpa == pytest.approx(normal.maximum_stress_mpa, rel=1e-10)


def test_four_field_section_reproduces_the_sharp_manual_eccentric_tension_example():
    actual = open_sheet('Z Formado', {'d': 203., 'bf': 48.5, 't': 3.})
    pieces = tuple(WallPiece(a, b, role, i) for i, (a, b, role) in enumerate(zip(actual.vertices, actual.vertices[1:], actual.roles, strict=False)))
    sheet = OpenSheet(actual.vertices, pieces, actual.thickness, 0., actual.roles)
    result = effective_warping_section(sheet, 200_000., (-100_000., 0., 0., -1e9/12))
    assert result.maximum_stress_mpa == pytest.approx(148.148148148, rel=1e-10)
    assert all(portions == ((0., 1.),) for portions in result.intervals.values())


def test_nonconvergence_never_returns_an_approved_last_iterate():
    with pytest.raises(ValueError, match='não convergiu'):
        effective_warping_section(slender(), 200_000., (2000., 2e5, -5e5, 1e8), maximum_iterations=1)


def test_normal_origin_change_preserves_stress_and_transforms_all_resultants_consistently():
    sheet = slender()
    loads = np.array((2000., 2e5, -5e5, 1e8))
    normal = effective_warping_section(sheet, 200_000., loads)
    shift = np.array((7.3, -2.1))
    transform = np.eye(4)
    transform[1, 0], transform[2, 0] = -shift[1], shift[0]
    shifted = effective_warping_section(sheet, 200_000., transform@loads,
        normal_origin=tuple(np.asarray(normal.field.centroid_mm)+shift))
    assert np.asarray(shifted.normal_matrix) == pytest.approx(transform@normal.normal_matrix@transform.T, rel=1e-8, abs=1e-6)
    assert shifted.maximum_stress_mpa == pytest.approx(normal.maximum_stress_mpa, rel=1e-8)
    assert shifted.field.cw_mm6 == pytest.approx(normal.field.cw_mm6)


def test_common_effective_envelope_is_order_independent_and_retains_previous_reductions():
    from osa.verification.cold_formed_warping_effective import effective_warping_envelope

    patterns = [(0., 2e5, -5e5, 1e8), (0., -1e5, 2e5, -2e7)]
    normal = effective_warping_envelope(slender(), 200_000., patterns)
    reversed_order = effective_warping_envelope(slender(), 200_000., patterns[::-1])
    assert np.asarray(normal.normal_matrix) == pytest.approx(np.asarray(reversed_order.normal_matrix), rel=1e-10)
    relaxed = effective_warping_envelope(slender(), 200_000., np.asarray(patterns)/10, retained_limit=normal.intervals)
    assert np.asarray(relaxed.normal_matrix) == pytest.approx(np.asarray(normal.normal_matrix), rel=1e-10)
    assert relaxed.intervals == normal.intervals
    for values, loads in zip(normal.stress_coefficients, patterns, strict=True):
        assert np.asarray(normal.normal_matrix)@values == pytest.approx(loads, rel=1e-10, abs=1e-7)


@pytest.mark.parametrize('mode_count', (3, 4))
def test_coupled_retained_section_shear_flow_preserves_resultants_and_the_total_variation_bound(mode_count):
    from scipy.integrate import solve_ivp

    from osa.sections.thin_walled import effective_shear_center
    from osa.verification.cold_formed_warping_effective import _solve, effective_warping_envelope

    if mode_count == 4:
        envelope = effective_warping_envelope(slender(), 200_000., [(0., 2e5, -5e5, 1e8)])
        pole = envelope.field.shear_center_mm
    else:
        envelope = effective_warping_envelope(open_sheet('L Formado', GEOMETRY), 200_000., [(0., 0., 0.)],
            retained_limit={0: ((.4, 1.),), 1: ((0., .65),)}, sectorial_mode=False)
        pole = effective_shear_center(envelope.field, envelope.intervals)
    field = envelope.field
    # Plotted shears have the opposite positive-face force sign. Bc'=-Tw.
    vy, vz, tw = 456., 123., 789. if mode_count == 4 else 0.
    derivative = _solve(np.asarray(envelope.normal_matrix), np.array((0., vz, -vy, -tw))[:mode_count])
    state, largest, variation_bound = np.zeros(4), 0., 0.
    for index, piece in enumerate(field.sheet.pieces):
        retained = ((0., 1.),) if piece.center is not None else envelope.intervals[piece.plate]
        stops = sorted({0., 1., *(value for pair in retained for value in pair)})
        area = sum(b-a for a, b in retained)*piece.length*field.sheet.thickness
        maximum = maximum_warping_fiber_stress(field, derivative if mode_count == 4 else (*derivative, 0.), piece_indices=(index,), include_faces=False)
        variation_bound += area*maximum
        for a, b in pairwise(stops):
            active = any(lo <= (a+b)/2 <= hi for lo, hi in retained)
            def differential(fraction, current, index=index, piece=piece, active=active):
                tangent = piece.tangent(fraction)
                relative = piece.point(fraction)-pole
                flow_gradient = (field.basis(index, fraction)[:mode_count]@derivative)*field.sheet.thickness if active else 0.
                return piece.length*np.array((flow_gradient, current[0]*tangent[0], current[0]*tangent[1],
                    current[0]*(relative[0]*tangent[1]-relative[1]*tangent[0])))
            solution = solve_ivp(differential, (a, b), state, rtol=1e-10, atol=1e-10, dense_output=True)
            assert solution.success
            largest = max(largest, max(abs(solution.sol(np.linspace(a, b, 51))[0])))
            state = solution.y[:, -1]
    assert state[0] == pytest.approx(0., abs=1e-8)
    assert state[1:] == pytest.approx((-vy, -vz, tw), rel=1e-8, abs=1e-7)
    assert largest <= variation_bound/2*(1+1e-10)
