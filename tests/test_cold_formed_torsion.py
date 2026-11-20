"""Independent exact torsion solutions and sectional equilibrium."""
from math import sqrt

import numpy as np
import pytest
from scipy.integrate import simpson

from osa.sections.thin_walled import open_sheet, sectorial_properties
from osa.verification.cold_formed_torsion import prescribed_torque, thin_wall_stresses

PARAMS = {'E': 200_000., 'G': 77_000., 'J': 100., 'Cw': 1e8}


def test_uniform_torque_with_both_ends_free_to_warp_is_saint_venant():
    x = np.linspace(0., 3000., 31)
    state = prescribed_torque((0., 3000.), (1000., 1000.), positions=x, **PARAMS)
    assert state.bimoment_nmm2 == pytest.approx(np.zeros(len(x)), abs=1e-8)
    assert state.warping_torque_nmm == pytest.approx(np.zeros(len(x)), abs=1e-8)
    assert state.twist_rad == pytest.approx(1000*x/(PARAMS['G']*PARAMS['J']))


@pytest.mark.parametrize('end', ['free', 'blocked'])
def test_constant_torque_with_blocked_warping_matches_exact_hyperbolic_solution(end):
    L, T = 3000., 1000.
    k = sqrt(PARAMS['G']*PARAMS['J']/(PARAMS['E']*PARAMS['Cw']))
    x = np.linspace(0., L, 100)
    state = prescribed_torque((0., L), (T, T), warping_start='blocked', warping_end=end, positions=x, **PARAMS)
    if end == 'free':
        B = -T/k*np.sinh(k*(L-x))/np.cosh(k*L)
        Tw = T*np.cosh(k*(L-x))/np.cosh(k*L)
        total_rotation = T/(PARAMS['G']*PARAMS['J'])*(L-np.tanh(k*L)/k)
    else:
        B = T/k*np.sinh(k*(x-L/2))/np.cosh(k*L/2)
        Tw = T*np.cosh(k*(x-L/2))/np.cosh(k*L/2)
        total_rotation = T/(PARAMS['G']*PARAMS['J'])*(L-2*np.tanh(k*L/2)/k)
    assert state.bimoment_nmm2 == pytest.approx(B, abs=1e-7)
    assert state.warping_torque_nmm == pytest.approx(Tw)
    assert state.twist_rad[-1] == pytest.approx(total_rotation)
    assert state.twist_rate_per_mm[0] == pytest.approx(0., abs=1e-15)
    if end == 'blocked':
        assert state.twist_rate_per_mm[-1] == pytest.approx(0., abs=1e-15)


def test_linearly_varying_torque_and_subdivision_invariance():
    L, gradient = 3000., 1.
    k = sqrt(PARAMS['G']*PARAMS['J']/(PARAMS['E']*PARAMS['Cw']))
    x = np.linspace(0., L, 101)
    state = prescribed_torque((0., L), (0., gradient*L), positions=x, **PARAMS)
    expected = -gradient/k**2*(1-np.cosh(k*(x-L/2))/np.cosh(k*L/2))
    assert state.bimoment_nmm2 == pytest.approx(expected, abs=1e-6)
    divided = prescribed_torque(x, gradient*x, positions=x, **PARAMS)
    assert divided.bimoment_nmm2 == pytest.approx(expected, abs=1e-6)
    assert divided.twist_rad == pytest.approx(state.twist_rad, abs=1e-10)


def test_very_long_bar_has_no_hyperbolic_overflow():
    state = prescribed_torque((0., 1e9), (1000., 1000.), warping_start='blocked', warping_end='blocked', **PARAMS)
    assert np.all(np.isfinite(state.bimoment_nmm2))
    assert state.warping_torque_nmm == pytest.approx((1000., 1000.))


@pytest.mark.parametrize('family', ['U Formado', 'C Formado', 'Z Formado', 'Z45 Formado', 'Z90 Formado', 'Cartola Formado'])
@pytest.mark.parametrize('mirror', [False, True])
def test_shear_flow_recovers_both_shears_and_the_warping_torque(family, mirror):
    sheet = open_sheet(family, {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.}, mirror=mirror)
    values = thin_wall_stresses(sheet, shear_y=123., shear_z=-456., warping_torque=789., divisions=40)
    recovered = np.zeros(3)
    for i in range(len(sheet.vertices)-1):
        start, end = np.asarray(sheet.vertices[i]), np.asarray(sheet.vertices[i+1])
        vector = end-start
        local = slice(i*41, (i+1)*41)
        q = values.shear_flow_n_mm[local]
        integral = simpson(q, x=np.linspace(0., 1., 41))
        recovered += integral*np.r_[vector, start[0]*vector[1]-start[1]*vector[0]]
    sc = sectorial_properties(sheet)
    expected_torque = 789.+sc['shear_center_y_mm']*(-456.)-sc['shear_center_z_mm']*123.
    assert recovered == pytest.approx((123., -456., expected_torque), abs=1e-8)
    assert values.shear_flow_n_mm[[0, -1]] == pytest.approx((0., 0.), abs=1e-10)


def test_bimoment_normal_stress_is_orthogonal_to_axial_and_bending_resultants():
    sheet = open_sheet('C Formado', {'d': 100., 'bf': 50., 'c': 15., 't': 2.})
    sectorial = sectorial_properties(sheet)
    B = 1e6
    values = thin_wall_stresses(sheet, bimoment=B)
    assert values.normal_mpa == pytest.approx(B*values.omega_mm2/sectorial['Cw_mm6'])
    resultants = np.zeros(4)
    for i in range(len(sheet.vertices)-1):
        local = slice(i*41, (i+1)*41)
        points = values.positions_mm[local]
        basis = np.column_stack((np.ones(41), points[:, 1], -points[:, 0], values.omega_mm2[local]))
        ds = np.linspace(0., np.linalg.norm(points[-1]-points[0]), 41)
        resultants += sheet.thickness*simpson(values.normal_mpa[local, None]*basis, x=ds, axis=0)
    assert resultants == pytest.approx((0., 0., 0., B), abs=1e-7)


def test_saint_venant_surface_stress_is_included_with_both_signs():
    sheet = open_sheet('U Formado', {'d': 100., 'bf': 50., 't': 2.})
    field = thin_wall_stresses(sheet, saint_venant_torque=-1000., J=100.)
    assert field.maximum_shear_mpa == pytest.approx(20.)
    assert field.maximum_von_mises_mpa == pytest.approx(sqrt(3)*20.)


def test_manual_annex_a_z200_50_3_eccentric_tension_example():
    # Manual p.90: sharp centreline bw=200,bf=50,t=3 mm. Legacy Z
    # dimensions are converted before comparing: d=bw+t, bf_input=bf-t/2.
    # N=100 kN at web centre -> B=N*omega(P), Cw=1875 cm6.
    sheet = open_sheet('Z Formado', {'d': 203., 'bf': 48.5, 't': 3.})
    properties = sectorial_properties(sheet)
    assert properties['Cw_mm6']/1e6 == pytest.approx(1875.)
    omega_load = properties['omega_mm2'][1]
    assert omega_load/100 == pytest.approx(25/3)
    stresses = thin_wall_stresses(sheet, axial=100_000., bimoment=100_000.*omega_load)
    assert max(stresses.normal_mpa) == pytest.approx(148.148148148)
    assert min(stresses.normal_mpa) == pytest.approx(-74.074074074)


@pytest.mark.parametrize(('start', 'end'), [('free', 'free'), ('blocked', 'free'), ('free', 'blocked'), ('blocked', 'blocked')])
def test_condensed_torsion_end_stiffness_recovers_exact_rotation_and_equilibrium(start, end):
    from osa.verification.cold_formed_torsion import TorsionEndModel

    model = TorsionEndModel(3000., E=PARAMS['E'], G=PARAMS['G'], J_mm4=PARAMS['J'], Cw_mm6=PARAMS['Cw'],
                           warping_start=start, warping_end=end)
    state = prescribed_torque((0., 3000.), (1., 1.), warping_start=start, warping_end=end, **PARAMS)
    assert model.compliance_rad_nmm == pytest.approx(state.twist_rad[-1])
    matrix = model.stiffness_nmm
    assert matrix@np.ones(2) == pytest.approx(np.zeros(2), abs=1e-8)
    assert matrix@np.array((0., model.compliance_rad_nmm)) == pytest.approx((-1., 1.))
    positions = np.linspace(0., 3000., 21)
    state = prescribed_torque((0., 3000.), (1., 1.), positions=positions, warping_start=start, warping_end=end, **PARAMS)
    assert model.end_rotation_shape(positions) == pytest.approx(state.twist_rad/state.twist_rad[-1], abs=1e-12)


def test_condensed_member_retains_the_cubic_short_bar_limit_and_consistent_loading():
    from osa.verification.cold_formed_torsion import TorsionEndModel

    model = TorsionEndModel(1., E=200_000., G=77_000., J_mm4=1., Cw_mm6=1e14,
                           warping_start='blocked', warping_end='free')
    assert model.compliance_rad_nmm == pytest.approx(1/(3*model.E*model.Cw_mm6))
    assert model.end_rotation_shape(np.array((0., .5, 1.))) == pytest.approx((0., .3125, 1.))
    # Integral of 1.5s²-0.5s³ = 3/8. Root/end load shares are 5/8,3/8.
    assert model.consistent_torque_load(0., 1., 10., 10.) == pytest.approx((6.25, 3.75))
    both = TorsionEndModel(1., E=200_000., G=77_000., J_mm4=1., Cw_mm6=1e14,
                          warping_start='blocked', warping_end='blocked')
    assert both.compliance_rad_nmm == pytest.approx(1/(12*model.E*model.Cw_mm6))
    assert both.consistent_torque_load(0., 1., 10., 10.) == pytest.approx((5., 5.))


def test_vanishing_sectorial_degree_uses_saint_venant_and_linear_consistent_loads():
    from osa.verification.cold_formed_torsion import TorsionEndModel

    model = TorsionEndModel(1000., E=200_000., G=77_000., J_mm4=10., Cw_mm6=0.,
                           warping_start='blocked', warping_end='blocked')
    assert model.compliance_rad_nmm == pytest.approx(1000/(77_000*10))
    assert model.consistent_torque_load(0., 1000., 0., 3.) == pytest.approx((500., 1000.))


def test_shear_centre_transform_preserves_work_and_induces_the_correct_eccentric_torque():
    from osa.verification.cold_formed_torsion import centroid_to_shear_center_transform

    matrix = centroid_to_shear_center_transform(-40., 10.)
    centroid_load = np.array((1., 2., 3., 4., 5., 6., -1., 4., -3., 1., 2., 3.))
    centroid_displacement = np.linspace(.001, .012, 12)
    sc_load = np.linalg.solve(matrix.T, centroid_load)
    sc_displacement = matrix@centroid_displacement
    assert sc_load@sc_displacement == pytest.approx(centroid_load@centroid_displacement)
    assert sc_load[3] == pytest.approx(4.+10.*2.-(-40.)*3.)
    assert sc_load[9] == pytest.approx(1.+10.*4.-(-40.)*(-3.))
    assert sc_load[[0, 1, 2, 4, 5, 6, 7, 8, 10, 11]] == pytest.approx(centroid_load[[0, 1, 2, 4, 5, 6, 7, 8, 10, 11]])


def test_condensed_torsion_and_shear_center_coupling_match_cantilever_tip_compliance():
    from osa.verification.cold_formed_torsion import TorsionEndModel, centroid_to_shear_center_transform

    L, E, Iy, Iz, ysc, zsc, force = 3000., 200_000., 400_000., 100_000., -40., 5., 1.
    torsion = TorsionEndModel(L, E=E, G=77_000., J_mm4=100., Cw_mm6=1e8,
                             warping_start='blocked', warping_end='free')
    ids = (7, 8, 9)
    transformation = centroid_to_shear_center_transform(ysc, zsc)[np.ix_(ids, ids)]
    stiffness_sc = np.diag((3*E*Iz/L**3, 3*E*Iy/L**3, 1/torsion.compliance_rad_nmm))
    stiffness_c = transformation.T@stiffness_sc@transformation
    displacement = np.linalg.solve(stiffness_c, (0., force, 0.))
    # Tip load at C: T_SC=-ysc*Fz; centroidal deflection includes twist.
    assert displacement[2] == pytest.approx(-ysc*force*torsion.compliance_rad_nmm)
    assert displacement[1] == pytest.approx(force*(L**3/(3*E*Iy)+ysc**2*torsion.compliance_rad_nmm))
    assert displacement[0] == pytest.approx(zsc*displacement[2])
    # The same force at SC is represented at C by the physical torque ysc*Fz.
    at_sc = np.linalg.solve(stiffness_c, (0., force, ysc*force))
    assert at_sc[2] == pytest.approx(0., abs=1e-15)
    assert at_sc[1] == pytest.approx(force*L**3/(3*E*Iy))


@pytest.mark.parametrize('a', [1e-6, 1e-4, .001, .01, .05, .1, 1., 100., 1000.])
@pytest.mark.parametrize(('start', 'end'), [('blocked', 'free'), ('free', 'blocked'), ('blocked', 'blocked')])
def test_end_rotation_shape_matches_high_precision_across_short_and_long_member_limits(a, start, end):
    from decimal import Decimal, localcontext

    from osa.verification.cold_formed_torsion import TorsionEndModel

    model = TorsionEndModel(1., E=1., G=1., J_mm4=1., Cw_mm6=1/a**2,
                           warping_start=start, warping_end=end)
    with localcontext() as context:
        context.prec = 60
        alpha = Decimal(str(a))
        def sh(value):
            return (value.exp()-(-value).exp())/2
        def ch(value):
            return (value.exp()+(-value).exp())/2
        expected = []
        for point in ('0', '.13', '.5', '.87', '1'):
            s = Decimal(point)
            if start == end:
                shape = (s-(sh(alpha*(s-Decimal('.5')))+sh(alpha/2))/(alpha*ch(alpha/2)))/(1-2*sh(alpha/2)/(alpha*ch(alpha/2)))
            else:
                coordinate = s if start == 'blocked' else 1-s
                shape = (coordinate-(sh(alpha)-sh(alpha*(1-coordinate)))/(alpha*ch(alpha)))/(1-sh(alpha)/(alpha*ch(alpha)))
                if start == 'free':
                    shape = 1-shape
            expected.append(float(shape))
    assert model.end_rotation_shape(np.array((0., .13, .5, .87, 1.))) == pytest.approx(expected, rel=1e-10, abs=1e-12)
