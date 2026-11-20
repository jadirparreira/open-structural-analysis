"""Beam kernel with the complete effective normal/sectorial stiffness."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.linalg import expm

from osa.analysis.vlasov import element_matrices, recover, section_from_sheet, shapes
from osa.sections.thin_walled import open_sheet
from osa.verification.cold_formed_warping_effective import effective_warping_section

E, G, LENGTH = 200_000., 77_000., 3000.


def coupled_section():
    geometry = {'d': 300., 'bf': 100., 'c': 25., 't': 1.5}
    effective = effective_warping_section(open_sheet('C Formado', geometry), E, (2000., 2e5, -5e5, 1e8), nominal_lip=26.5)
    section = section_from_sheet('C Formado', geometry)
    cy, cz = effective.field.centroid_mm
    sy, sz = effective.field.shear_center_mm
    return replace(section, ysc=sy-cy, zsc=sz-cz, cw=effective.field.cw_mm6, normal_matrix=effective.normal_matrix)


def test_complete_normal_stiffness_preserves_work_and_constitutive_resultants():
    section = coupled_section()
    rng = np.random.default_rng(7355)
    d = rng.normal(size=14)*.001
    d[[6, 13]] *= .001
    K, _B = element_matrices(LENGTH, section, E, G)
    xi, wi = np.polynomial.legendre.leggauss(8)
    energy = 0.
    local = section.transform@d
    for fraction, weight in zip((xi+1)/2, wi*LENGTH/2, strict=True):
        row = shapes(LENGTH, fraction)
        strain = np.array((-row['u1']@local, row['w2']@local, -row['v2']@local, row['theta2']@local))
        torque_rate = row['theta1']@local
        normal = E*np.asarray(section.normal_matrix)@strain
        result = recover(LENGTH, section, E, G, d, fraction)
        assert [-result['axial_tension_N'], -result['moment_y_Nmm'], -result['moment_z_Nmm'], -result['bimoment_Nmm2']] == pytest.approx(normal)
        energy += weight*(strain@normal+G*section.j*torque_rate**2)
    assert d@K@d == pytest.approx(energy, rel=1e-12)
    for direction in (0, 1, 2, 3):
        rigid = np.zeros(14)
        rigid[[direction, direction+7]] = 1.
        assert np.linalg.norm(K@rigid) < 1e-4


def test_bimoment_induces_axial_and_bending_response_matching_independent_transfer_solution():
    section = coupled_section()
    normal = np.asarray(section.normal_matrix)
    # Eliminate the axial strain at N=0. Retain its coupling when recovering
    # axial displacement; this is distinct from dropping the off-diagonals.
    reduced = normal[1:, 1:]-np.outer(normal[1:, 0], normal[0, 1:])/normal[0, 0]
    curvature = np.array(((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)))
    constitutive = E*curvature.T@reduced@curvature
    matrix = np.zeros((12, 12))
    matrix[:3, 3:6] = np.eye(3)
    matrix[3:6, 6:9] = np.linalg.inv(constitutive)
    matrix[6:9, 3:6] = np.diag((0., 0., G*section.j))
    matrix[6:9, 9:12] = -np.eye(3)
    transfer = expm(matrix*LENGTH)
    bimoment = 1e6
    root = np.linalg.solve(transfer[6:12, 6:12], (0., 0., -bimoment, 0., 0., 0.))
    end = transfer[:, 6:12]@root
    u_end = normal[0, 1:]@curvature@end[3:6]/normal[0, 0]
    expected = np.array((u_end, end[0]+section.zsc*end[2], end[1]-section.ysc*end[2], end[2]))
    errors = []
    for count in (8, 16, 32):
        K = np.zeros((7*(count+1),)*2)
        ke, _ge = element_matrices(LENGTH/count, section, E, G)
        for index in range(count):
            ids = np.arange(7*index, 7*index+14)
            K[np.ix_(ids, ids)] += ke
        force = np.zeros(len(K))
        force[-1] = -bimoment
        free = np.arange(7, len(K))
        d = np.zeros(len(K))
        d[free] = np.linalg.solve(K[np.ix_(free, free)], force[free])
        actual = d[-7:-3]
        errors.append(np.linalg.norm((actual-expected)/np.maximum(abs(expected), 1e-12)))
    assert errors[1] < errors[0]/3
    assert errors[2] < errors[1]/3
    assert errors[-1] < 2e-3
    assert min(abs(expected)) > 1e-12  # all four responses really are excited


@pytest.mark.parametrize('kind', ('nan', 'indefinite', 'asymmetric', 'singular'))
def test_invalid_coupled_normal_matrix_is_rejected(kind):
    section = section_from_sheet('C Formado', {'d': 100., 'bf': 50., 'c': 15., 't': 2.})
    matrix = section.normal_gram
    if kind == 'nan':
        matrix[0, 0] = np.nan
    elif kind == 'indefinite':
        matrix[0, 1] = matrix[1, 0] = np.sqrt(matrix[0, 0]*matrix[1, 1])*2
    elif kind == 'asymmetric':
        matrix[0, 1] = 1.
    else:
        matrix[0, 1] = matrix[1, 0] = np.sqrt(matrix[0, 0]*matrix[1, 1])
    with pytest.raises(ValueError, match='normal/setorial'):
        replace(section, normal_matrix=tuple(map(tuple, matrix)))



def test_normal_matrix_cannot_change_after_its_energy_has_been_validated():
    section = section_from_sheet('C Formado', {'d': 100., 'bf': 50., 'c': 15., 't': 2.})
    supplied = section.normal_gram
    coupled = replace(section, normal_matrix=supplied)
    supplied[0, 0] = np.nan
    assert np.all(np.isfinite(coupled.normal_gram))
