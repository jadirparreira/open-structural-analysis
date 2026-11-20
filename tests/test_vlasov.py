"""Seven-DOF element: energy, work, closed-form response and elastic buckling."""

import numpy as np
import pytest
from scipy.linalg import eigh

from osa.analysis.vlasov import consistent_load, element_matrices, recover, section_from_sheet
from osa.verification.cold_formed_global import bending_critical, compression_critical, global_section
from osa.verification.cold_formed_torsion import TorsionEndModel

E, G, LENGTH = 200_000., 77_000., 3000.
FAMILIES = ['U Formado', 'C Formado', 'Z Formado', 'Z45 Formado', 'Z90 Formado', 'L Formado', 'Cartola Formado']
GEOMETRY = {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.}


def assemble(section, count=16, **prestress):
    K = np.zeros((7*(count+1),)*2)
    B = np.zeros_like(K)
    ke, ge = element_matrices(LENGTH/count, section, E, G, **prestress)
    for i in range(count):
        indices = np.arange(7*i, 7*i+14)
        K[np.ix_(indices, indices)] += ke
        B[np.ix_(indices, indices)] += ge
    return K, B


def solve_cantilever(section, force, warping_start='free', warping_end='free', count=16):
    K, _B = assemble(section, count)
    fixed = [0, 1, 2, 3, 4, 5]
    if warping_start == 'blocked':
        fixed.append(6)
    if warping_end == 'blocked':
        fixed.append(7*count+6)
    free = np.setdiff1d(np.arange(len(K)), fixed)
    F = np.zeros(len(K))
    F[-7:] = force
    d = np.zeros(len(K))
    d[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    return d, K@d-F


def critical(section, **prestress):
    K, B = assemble(section, **prestress)
    # Fork supports, free warping; normal rotations remain free. The axial
    # datum is fixed once while longitudinal motion at the far end is free.
    fixed = [0, 1, 2, 3, len(K)-6, len(K)-5, len(K)-4]
    free = np.setdiff1d(np.arange(len(K)), fixed)
    k, b = K[np.ix_(free, free)], B[np.ix_(free, free)]
    values = eigh(b, k, eigvals_only=True)
    return 1/max(abs(values))


def test_element_elastic_energy_has_exactly_six_rigid_motions():
    section = section_from_sheet('C Formado', GEOMETRY)
    K, B = element_matrices(1000., section, E, G)
    assert K == pytest.approx(K.T, abs=1e-8)
    assert B == pytest.approx(np.zeros((14, 14)))
    # Check actual rigid motions in physical centroidal DOFs, rather than
    # relying on a poorly scaled raw numerical matrix rank.
    for direction in (0, 1, 2, 3):
        d = np.zeros(14)
        d[[direction, direction+7]] = 1.
        assert np.linalg.norm(K@d) < 1e-4
    d = np.zeros(14)
    d[[4, 11]], d[9] = 1., -1000.
    assert np.linalg.norm(K@d) < 1e-4
    d = np.zeros(14)
    d[[5, 12]], d[8] = 1., 1000.
    assert np.linalg.norm(K@d) < 1e-4


@pytest.mark.parametrize(('start', 'end'), [('free', 'free'), ('blocked', 'free'), ('free', 'blocked'), ('blocked', 'blocked')])
def test_finite_elements_match_exact_torsion_with_both_end_warping_conditions(start, end):
    section = section_from_sheet('C Formado', GEOMETRY)
    end_model = TorsionEndModel(LENGTH, E, G, section.j, section.cw, start, end)
    d, reactions = solve_cantilever(section, (0., 0., 0., 1000., 0., 0., 0.), start, end)
    assert d[-4] == pytest.approx(1000*end_model.compliance_rad_nmm, rel=1e-5)
    assert d[-6] == pytest.approx(section.zsc*d[-4], abs=1e-8)
    assert d[-5] == pytest.approx(-section.ysc*d[-4], rel=1e-5)
    assert reactions[3] == pytest.approx(-1000., rel=1e-8)


def test_centroidal_tip_force_automatically_excites_twist_and_matches_closed_solution():
    section = section_from_sheet('C Formado', GEOMETRY)
    end_model = TorsionEndModel(LENGTH, E, G, section.j, section.cw, 'blocked', 'free')
    force = .1
    d, _reaction = solve_cantilever(section, (0., 0., force, 0., 0., 0., 0.), 'blocked')
    expected_twist = -section.ysc*force*end_model.compliance_rad_nmm
    assert d[-4] == pytest.approx(expected_twist, rel=1e-5)
    expected_deflection = force*(LENGTH**3/(3*E*section.iy)+section.ysc**2*end_model.compliance_rad_nmm)
    assert d[-5] == pytest.approx(expected_deflection, rel=1e-5)
    # Applied at SC: a physical centroidal couple ysc*Fz cancels twist.
    d, _reaction = solve_cantilever(section, (0., 0., force, section.ysc*force, 0., 0., 0.), 'blocked')
    assert d[-4] == pytest.approx(0., abs=1e-10)
    assert d[-5] == pytest.approx(force*LENGTH**3/(3*E*section.iy), rel=1e-7)


def test_consistent_loads_preserve_resultants_and_work_at_the_centroid():
    section = section_from_sheet('C Formado', GEOMETRY)
    load = consistent_load(1000., section, force_y=(2., 4.), force_z=(3., 5.), torque=(6., 8.))
    assert load[[1, 8]].sum() == pytest.approx(3000.)
    assert load[[2, 9]].sum() == pytest.approx(4000.)
    assert load[[3, 10]].sum() == pytest.approx(7000.)
    rotation = np.zeros(14)
    rotation[[4, 11]], rotation[9] = 1., -1000.
    assert load@rotation == pytest.approx(-1000**2*(3/2+2/3))


@pytest.mark.parametrize('family', FAMILIES)
def test_compression_eigenvalue_matches_nbr_14762_coupled_global_equation(family):
    section = section_from_sheet(family, GEOMETRY)
    expected, _info = compression_critical(global_section(family, GEOMETRY), E, G, LENGTH, LENGTH, LENGTH)
    assert critical(section, compression=1.) == pytest.approx(expected, rel=2e-4)


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('axis', ['y', 'z'])
def test_uniform_bending_eigenvalue_matches_general_fork_supported_vlasov_equation(family, axis):
    section = section_from_sheet(family, GEOMETRY)
    expected, _sign = bending_critical(global_section(family, GEOMETRY), E, G, LENGTH, LENGTH,
                                      moment_y=float(axis == 'y'), moment_z=float(axis == 'z'))
    actual = critical(section, **{'moment_'+axis: 1.})
    assert actual == pytest.approx(expected, rel=3e-4)


def test_recovery_of_constant_normal_strain_and_curvature():
    section = section_from_sheet('C Formado', GEOMETRY)
    length, axial, curvature = 1000., 1e-5, 1e-7
    # Pure SC w=0.5*k*x², ry=-k*x, no twist, extension u=epsilon*x.
    d = np.zeros(14)
    d[7], d[9], d[11] = axial*length, .5*curvature*length**2, -curvature*length
    data = recover(length, section, E, G, d, .37)
    assert data['axial_tension_N'] == pytest.approx(E*section.area*axial)
    assert data['moment_y_Nmm'] == pytest.approx(-E*section.iy*curvature)
    assert data['moment_z_Nmm'] == pytest.approx(E*section.iyz*curvature, abs=1e-8)
    assert data['bimoment_Nmm2'] == 0.
