"""Actual service solves using a common coupled effective normal matrix."""
from math import cosh, sqrt

import numpy as np
import pytest
from test_vlasov_adapter import model_for

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.vlasov import rounded_section_from_sheet
from osa.domain import Action, LoadCombination
from osa.services.action_service import ActionService
from osa.ui.verification_worker import verify_model


def service_model(family='Z90 Formado'):
    model = model_for(family)
    ActionService(model).set_combination(LoadCombination('ELS', (('Q', 1.),), active_actions=('Q',), limit_state='ELS'))
    for key, value in (('ServiceMeasure', 3.), ('DeltaY', 1000.), ('DeltaZ', 1000.)):
        model.update_bar_calculation_property('B1', key, value)
    return model


def solve_service(model):
    result = PyniteAdapter().run(model, AnalysisRequest(load_combinations=('ELS',), warping=True))[0]
    model.analysis_results = [result]
    return result


def test_service_bimoment_is_solved_on_the_same_rounded_geometry_and_matches_exact_torsion():
    model = service_model()
    bimoment = 10_000.
    ActionService(model).add_member_bimoment('B1', 'B', -bimoment/1e9, 'Q')
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    exact = -bimoment/(G*section.j)*(1-1/cosh(3000*sqrt(G*section.j/(E*section.cw))))
    result = solve_service(model)
    data = result.member_results['B1']
    info = data['service_stiffness']
    assert info['status'] == 'converged'
    assert info['geometry_basis'] == data['warping_analysis']['geometry_basis'] == 'rounded-mean-line-v1'
    assert info['normal_stress_convention'] == 'Nc,-My,+Mz,-B'
    assert result.node_results['B']['RX'] == pytest.approx(exact, rel=2e-5)
    assert data['end']['bimoment'] == pytest.approx(bimoment/1e9, rel=1e-7)
    assert np.asarray(info['normal_gram']) == pytest.approx(np.asarray(data['warping_analysis']['normal_gram_geometric']), rel=1e-12, abs=1e-6)
    assert info['maximum_normal_stress_mpa'] < model.materials['ASTM A36'][4]/1000
    checks = verify_model(model)['results']['bar:B1']['checks']
    assert checks['serviceability_y']['status'] in ('checked', 'not_applicable')
    assert checks['serviceability_z']['status'] in ('checked', 'not_applicable')
    assert checks['torsion']['status'] == 'not_checked'  # ELS is not an ELU torsion resistance


def test_service_reduces_material_and_applies_the_complete_coupled_matrix():
    from scipy.linalg import expm

    model = service_model('C Formado')
    model.update_member_profile('B1', 'slender', {'d': 300., 'bf': 100., 'c': 25., 't': 1.5})
    actions = ActionService(model)
    actions.add_action(Action('My', 'node_moment_Y', 'B', (.2,), 'Q'))
    actions.add_action(Action('Mz', 'node_moment_Z', 'B', (-.5,), 'Q'))
    actions.add_member_bimoment('B1', 'B', -.1, 'Q')
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    result = solve_service(model)
    data = result.member_results['B1']
    info = data['service_stiffness']
    assert info['status'] == 'converged', info
    assert info['iterations'] > 1
    normal = np.asarray(info['normal_gram'])
    assert normal[0, 0] < .99*section.area
    assert max(abs(normal[:3, 3])) > 1.
    diagonal = np.sqrt(np.diag(section.normal_gram))
    assert min(np.linalg.eigvalsh((section.normal_gram-normal)/np.outer(diagonal, diagonal))) > -1e-9
    # Independent continuous member with the final effective constitutive
    # matrix. N=0 is eliminated analytically, retaining its axial coupling.
    reduced = normal[1:, 1:]-np.outer(normal[1:, 0], normal[0, 1:])/normal[0, 0]
    mapping = np.array(((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)))
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    matrix = np.zeros((12, 12))
    matrix[:3, 3:6] = np.eye(3)
    matrix[3:6, 6:9] = np.linalg.inv(E*mapping.T@reduced@mapping)
    matrix[6:9, 3:6] = np.diag((0., 0., G*section.j))
    matrix[6:9, 9:12] = -np.eye(3)
    transfer = expm(matrix*3000)
    end_forces = (-.5e6, -.2e6, -.1e9, 0., 0., 0.)
    root = np.linalg.solve(transfer[6:12, 6:12], end_forces)
    end = transfer[:, 6:12]@root
    axial = normal[0, 1:]@mapping@end[3:6]/normal[0, 0]
    expected = np.array((axial/1000, (end[0]+section.zsc*end[2])/1000,
                         (end[1]-section.ysc*end[2])/1000, end[2]))
    actual = np.array([result.node_results['B'][key] for key in ('DX', 'DY', 'DZ', 'RX')])
    assert actual == pytest.approx(expected, rel=2e-3, abs=1e-10)


def test_service_rejects_fy_exceeded_by_bimoment_and_rejects_a_mismatched_matrix():
    model = service_model()
    ActionService(model).add_member_bimoment('B1', 'B', -100., 'Q')
    result = solve_service(model)
    assert result.member_results['B1']['service_stiffness']['status'] == 'not_checked'
    assert 'fy' in result.member_results['B1']['service_stiffness']['detail']
    model = service_model('C Formado')
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = solve_service(model)
    data = result.member_results['B1']
    assert data['service_stiffness']['status'] == 'converged'
    data['service_stiffness']['normal_gram'][0][0] *= .9
    checks = verify_model(model)['results']['bar:B1']['checks']
    assert checks['serviceability']['status'] == 'not_checked'
    assert 'matriz' in checks['serviceability']['detail'].lower()


def test_service_roundtrip_preserves_coupled_results_and_rejects_an_old_geometry_stamp():
    from osa.model import StructuralModel
    from osa.persistence.project_serializer import ProjectSerializer

    model = service_model('C Formado')
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = solve_service(model)
    restored = StructuralModel()
    import json

    ProjectSerializer().load_into(restored, json.loads(json.dumps(ProjectSerializer().dump(model))))
    assert restored.analysis_results[0].member_results['B1']['service_stiffness']['normal_gram'] == result.member_results['B1']['service_stiffness']['normal_gram']
    # Project loading keeps stored results inspectable but changes the model
    # revision. Reprocessing, as required by the existing import lifecycle,
    # must reproduce a verifiable coupled ELS from the persistent inputs.
    solve_service(restored)
    checks = verify_model(restored)['results']['bar:B1']['checks']
    assert checks['serviceability_y']['status'] in ('checked', 'not_applicable')
    assert checks['serviceability_z']['status'] in ('checked', 'not_applicable')
    result.member_results['B1']['warping_analysis']['geometry_basis'] = 'sharp-sectorial-previous'
    verification = verify_model(model)['results']['bar:B1']
    assert verification['status'] == 'not_checked'
    assert 'base geométrica atual' in verification['checks']['torsion']['detail']
    result.member_results['B1']['warping_analysis']['geometry_basis'] = 'rounded-mean-line-v1'
    result.member_results['B1']['warping_analysis'].pop('algorithm')
    assert verify_model(model)['results']['bar:B1']['status'] == 'not_checked'



def test_memorial_identifies_the_complete_effective_matrix_and_actual_normal_stress():
    from osa.memorial_data import calculation_memory
    from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog

    model = service_model('C Formado')
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    solve_service(model)
    model.verification_results = verify_model(model)['results']
    memory = calculation_memory(model, ['B1'])
    html = CalculationMemorialDialog._render(memory, {}, equation_latex={})
    assert 'Matriz normal efetiva' in html
    assert 'menor razão de energia normal' in html
    assert 'Tensão normal máxima, incluindo empenamento' in html
    assert 'termos fora da diagonal foram usados na análise' in html


def _exact_coupled_member_stiffness(section, normal, E, G, length):
    """14-state continuous equilibrium; axial reaction is not suppressed."""
    from scipy.linalg import expm

    mapping = np.array(((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)))
    reduced = normal[1:, 1:]-np.outer(normal[1:, 0], normal[0, 1:])/normal[0, 0]
    constitutive = E*mapping.T@reduced@mapping
    inverse = np.linalg.inv(constitutive)
    coupling = mapping.T@normal[1:, 0]/normal[0, 0]
    axial = normal[0, 1:]@mapping/normal[0, 0]
    # State: [u,q(3),q'(3),M(3),h(3),Nc]. q is at the shear centre.
    differential = np.zeros((14, 14))
    differential[0, 7:10] = axial@inverse
    differential[0, 13] = -1/(E*normal[0, 0])-axial@inverse@coupling
    differential[1:4, 4:7] = np.eye(3)
    differential[4:7, 7:10] = inverse
    differential[4:7, 13] = -inverse@coupling
    differential[7:10, 4:7] = np.diag((0., 0., G*section.j))
    differential[7:10, 10:13] = -np.eye(3)
    transfer = expm(differential*length)
    transform = np.zeros((7, 7))
    transform[0, 0] = 1.
    transform[1, [1, 3]] = (1., -section.zsc)
    transform[2, [2, 3]] = (1., section.ysc)
    transform[3, 3] = 1.
    transform[4, 5], transform[5, 4], transform[6, 6] = 1., -1., 1.
    stiffness = np.zeros((14, 14))
    for column in range(14):
        prescribed = np.eye(14)[:, column]
        initial_q, final_q = transform@prescribed[:7], transform@prescribed[7:]
        forces = np.linalg.solve(transfer[:7, 7:], final_q-transfer[:7, :7]@initial_q)
        end = transfer@np.r_[initial_q, forces]
        moment, shear, compression = forces[:3], forces[3:6], forces[6]
        stiffness[:7, column] = transform.T@np.r_[compression, -shear, -moment]
        stiffness[7:, column] = transform.T@np.r_[-end[13], end[10:13], end[7:10]]
    return stiffness


def test_two_span_service_with_reactions_and_normal_coupling_matches_exact_continuous_members():
    model = service_model('C Formado')
    model.add_node('M', 1.5, 0., 0.)
    model.update_bar('B1', 'A', 'M')
    model.update_member_profile('B1', 'slender1', {'d': 300., 'bf': 100., 'c': 25., 't': 1.5})
    model.add_bar('B2', 'M', 'B', template=model.bars['B1'])
    model.update_member_profile('B2', 'slender2', {'d': 200., 'bf': 60., 'c': 15., 't': 1.})
    model.update_node_supports('B', (True,)*6)
    model.update_member_warping_restraints('B1', ('blocked', 'free'))
    model.update_member_warping_restraints('B2', ('free', 'blocked'))
    actions = ActionService(model)
    actions.add_action(Action('Fy', 'node_force_Y', 'M', (.5,), 'Q'))
    actions.add_action(Action('Fz', 'node_force_Z', 'M', (-.25,), 'Q'))
    result = solve_service(model)
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    exact = np.zeros((22, 22))
    reduced = False
    for name, a, b, phi_a, phi_b in (('B1', 0, 6, 18, 19), ('B2', 6, 12, 20, 21)):
        member = model.bars[name]
        info = result.member_results[name]['service_stiffness']
        assert info['status'] == 'converged', info
        section = rounded_section_from_sheet(member.section, member.geometry_dict())
        normal = np.asarray(info['normal_gram'])
        reduced |= normal[0, 0] < .99*section.area
        stiffness = _exact_coupled_member_stiffness(section, normal, E, G, 1500.)
        ids = np.r_[np.arange(a, a+6), phi_a, np.arange(b, b+6), phi_b]
        exact[np.ix_(ids, ids)] += stiffness
    assert reduced
    force = np.zeros(22)
    force[7], force[8] = 500., -250.
    free = np.r_[np.arange(6, 12), 19, 20]
    displacement = np.zeros(22)
    displacement[free] = np.linalg.solve(exact[np.ix_(free, free)], force[free])
    for index, key in enumerate(('DX', 'DY', 'DZ', 'RX', 'RY', 'RZ')):
        expected = displacement[6+index]/(1000 if index < 3 else 1)
        assert result.node_results['M'][key] == pytest.approx(expected, rel=2e-3, abs=1e-10)
    reaction = exact@displacement-force
    for index, key in enumerate(('RXN_FX', 'RXN_FY', 'RXN_FZ', 'RXN_MX', 'RXN_MY', 'RXN_MZ')):
        expected = reaction[index]/(1000 if index < 3 else 1e6)
        assert result.node_results['A'][key] == pytest.approx(expected, rel=2e-3, abs=1e-9)


@pytest.mark.parametrize('yield_fraction', (.5, 1.1))
def test_service_saint_venant_shear_cannot_hide_behind_zero_normal_stress(yield_fraction):
    model = service_model()
    model.update_member_warping_restraints('B1', ('free', 'free'))
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    fy = model.materials['ASTM A36'][4]/1000
    torque = yield_fraction*fy/np.sqrt(3)*section.j/model.bars['B1'].geometry_dict()['t']
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (torque/1e6,), 'Q'))
    result = solve_service(model)
    info = result.member_results['B1']['service_stiffness']
    if yield_fraction < 1:
        assert info['status'] == 'converged', info
        assert info['maximum_equivalent_stress_bound_mpa'] == pytest.approx(yield_fraction*fy, rel=1e-6)
        assert info['maximum_normal_stress_mpa'] < 1e-5
    else:
        assert info['status'] == 'not_checked'
        assert 'elasticidade ELS' in info['detail']


def test_service_with_warping_and_second_order_retains_the_elasticity_proof():
    model = service_model('C Formado')
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-.1,), 'Q'))
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(load_combinations=('ELS',), warping=True, second_order=True))[0]
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'converged', info
    assert info['elasticity'] == 'proven_by_upper_bound'
    assert result.member_results['B1']['warping_analysis']['second_order']


@pytest.mark.parametrize('damage', ['missing_bimoment', 'missing_slope', 'torque_balance'])
def test_service_rejects_incomplete_coupled_samples_even_with_preserved_stiffness_proof(damage):
    from copy import deepcopy
    from dataclasses import replace

    model = service_model()
    ActionService(model).set_combination(LoadCombination('ELU', (('Q', 1.),), active_actions=('Q',), limit_state='ELU'))
    ActionService(model).add_member_bimoment('B1', 'B', -.00001, 'Q')
    result = solve_service(model)
    model.analysis_results.append(replace(deepcopy(result), load_reference='ELU'))
    assert result.member_results['B1']['service_stiffness']['status'] == 'converged'
    sample = result.member_results['B1']['samples'][0]
    if damage == 'missing_bimoment':
        del sample['bimoment']
    elif damage == 'missing_slope':
        del sample['centroid_slope_y']
    else:
        sample['saint_venant_torque'] += 1.
    checks = verify_model(model)['results']['bar:B1']['checks']
    assert checks['serviceability']['status'] == 'not_checked'
    assert 'Amostra ELS' in checks['serviceability']['detail']


def test_strength_rejects_a_coupled_result_with_a_missing_bimoment():
    model = service_model()
    ActionService(model).add_member_bimoment('B1', 'B', -.00001, 'Q')
    result = solve_service(model)
    del result.member_results['B1']['samples'][0]['bimoment']
    checks = verify_model(model)['results']['bar:B1']['checks']
    assert checks['input_data']['status'] == 'not_checked'
    assert checks['torsion']['status'] == 'not_checked'
