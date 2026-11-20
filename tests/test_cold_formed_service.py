"""Actual structural re-solves and explicit ELS displacement measurements."""
from math import isfinite

import numpy as np
import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.vlasov import rounded_section_from_sheet
from osa.domain import Action, LoadCombination
from osa.model import StructuralModel
from osa.sections.properties import calculate_section_properties
from osa.services.action_service import ActionService
from osa.verification.cold_formed_service import service_checks
from osa.verification.elements import verification_elements


def cantilever(force=.7, *, family='Cartola Formado'):
    model = StructuralModel()
    model.add_node('A', 0., 0., 0.)
    model.add_node('B', 3., 0., 0.)
    model.add_bar('B1', 'A', 'B')
    model.update_bar_section('B1', family)
    model.update_bar_material('B1', 'ASTM A36', model.materials['ASTM A36'])
    model.update_member_profile('B1', family+'200', {'d': 200., 'bf': 60., 'c': 30. if family == 'Cartola Formado' else 15., 't': 1.})
    model.update_node_supports('A', (True,)*6)
    actions = ActionService(model)
    actions.add_action(Action('F', 'node_force_Z', 'B', (force,), 'Q'))
    actions.set_combination(LoadCombination('ELU', (('Q', 1.5),), active_actions=('Q',), limit_state='ELU'))
    actions.set_combination(LoadCombination('ELS', (('Q', 1.),), active_actions=('Q',), limit_state='ELS'))
    return model


def matrix_cantilever(force=.7):
    model = cantilever(force)
    model.update_member_warping_restraints('B1', ('free', 'free'))
    model.update_analysis_options(second_order=False, stiffness_factor=1., warping=True)
    return model


@pytest.mark.parametrize('force', [.001, .7])
def test_service_analysis_re_solves_with_effective_rigidity_and_preserves_elu(force):
    model = matrix_cantilever(force)
    physical = rounded_section_from_sheet('Cartola Formado', model.bars['B1'].geometry_dict())
    E = model.materials['ASTM A36'][0]
    gross_inertia = 1/np.linalg.inv(physical.normal_gram)[1, 1]
    gross_tip = force*3**3/(3*E*gross_inertia*1e-12)
    results = PyniteAdapter().run(model, AnalysisRequest())
    by_name = {result.load_reference: result for result in results}
    service = by_name['ELS']
    info = service.member_results['B1']['service_stiffness']
    assert info['status'] == 'converged'
    assert 0 < info['EI_factor'] <= 1
    effective_inertia = 1/np.linalg.inv(info['normal_gram'])[1, 1]
    exact_tip = force*3**3/(3*E*effective_inertia*1e-12)
    assert abs(service.node_results['B']['DZ']) == pytest.approx(exact_tip, rel=2e-3)
    assert abs(by_name['ELU'].node_results['B']['DZ']) == pytest.approx(gross_tip*1.5, rel=1e-5)
    if force < .01:
        assert info['EI_factor'] == pytest.approx(1., abs=1e-12)
    else:
        assert info['EI_factor'] < .99
        assert info['iterations'] >= 2
    assert model.analysis_results == []


def test_absolute_displacement_limit_uses_effective_results_and_can_fail():
    model = matrix_cantilever()
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest())
    model.update_bar_calculation_property('B1', 'ServiceMeasure', 3.)
    model.update_bar_calculation_property('B1', 'DeltaZ', .1)
    item = service_checks(verification_elements(model)[0], model)['serviceability_z']
    assert item['status'] == 'checked' and item['utilization'] > 1
    assert item['critical_combination'] == 'ELS'
    assert item['applied'] == pytest.approx(abs(model.analysis_results[1].node_results['B']['DZ'])*1000)
    model.update_bar_calculation_property('B1', 'DeltaZ', item['applied']*1.01)
    assert service_checks(verification_elements(model)[0], model)['serviceability_z']['utilization'] < 1


def test_effective_iteration_failure_is_recorded_and_never_approved(monkeypatch):
    from osa.analysis.pynite import adapter
    def fail(*_args, **_kwargs):
        raise ValueError('seção efetiva não convergiu')
    monkeypatch.setattr(adapter, 'coupled_service_stiffness', fail)
    model = matrix_cantilever()
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest())
    assert isfinite(model.analysis_results[1].node_results['B']['DZ'])
    model.update_bar_calculation_property('B1', 'ServiceMeasure', 3.)
    model.update_bar_calculation_property('B1', 'DeltaZ', 100.)
    result = service_checks(verification_elements(model)[0], model)['serviceability']
    assert result['status'] == 'not_checked' and 'não convergiu' in result['detail']


def test_old_gross_service_results_need_a_new_solve():
    model = matrix_cantilever(.001)
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest())
    del model.analysis_results[1].member_results['B1']['service_stiffness']
    model.update_bar_calculation_property('B1', 'ServiceMeasure', 3.)
    result = service_checks(verification_elements(model)[0], model)['serviceability']
    assert result['status'] == 'not_checked'
    assert 'rigidez efetiva' in result['detail']


def test_chord_measurement_spans_a_group_instead_of_resetting_at_internal_nodes():
    model = matrix_cantilever(.001)
    ActionService(model).remove_actions()
    model.update_node('B', 2., 0., 0.)
    model.add_node('C', 4., 0., 0.)
    model.add_bar('B2', 'B', 'C', template=model.bars['B1'])
    model.update_node_supports('A', (True, True, True, True, False, False))
    model.update_node_supports('C', (False, True, True, False, False, False))
    actions = ActionService(model)
    for name in ('B1', 'B2'):
        actions.add_member_distributed_force(name, 'Z', -.001, -.001, 'Q')
    model.group_verification_elements(('B1', 'B2'))
    for name in ('B1', 'B2'):
        model.update_bar_calculation_property(name, 'ServiceMeasure', 1.)
        model.update_bar_calculation_property(name, 'DeltaZ', 1.)
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest())
    result = service_checks(verification_elements(model)[0], model)['serviceability_z']
    physical = rounded_section_from_sheet('Cartola Formado', model.bars['B1'].geometry_dict())
    inertia = 1/np.linalg.inv(physical.normal_gram)[1, 1]
    expected = 5*.001*4**4/(384*model.materials['ASTM A36'][0]*inertia*1e-12)*1000
    assert result['status'] == 'checked'
    assert result['applied'] == pytest.approx(expected, rel=1e-5)


def test_service_stress_beyond_yield_is_not_accepted_as_elastic_service():
    model = matrix_cantilever(2.)
    result = PyniteAdapter().run(model, AnalysisRequest())[1]
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'not_checked'
    assert 'supera fy' in info['detail']


def test_service_stress_sign_matches_physical_tension_and_end_couple_in_an_asymmetric_hat():

    from osa.domain import Action
    from osa.sections.thin_walled import open_sheet

    model = matrix_cantilever(.001)
    model.update_bar_section('B1', 'Cartola Formado')
    geometry = {'d': 100., 'bf': 50., 'c': 15., 't': 2.}
    model.update_member_profile('B1', 'Cartola100', geometry)
    actions = ActionService(model)
    actions.remove_actions()
    actions.add_action(Action('tension', 'node_force_X', 'B', (.01,), 'Q'))
    actions.add_action(Action('couple', 'node_moment_Y', 'B', (1e-6,), 'Q'))
    result = next(row for row in PyniteAdapter().run(model, AnalysisRequest()) if row.load_reference == 'ELS')
    sample = result.member_results['B1']['samples'][0]
    assert sample['axial'] == pytest.approx(-.01)
    assert sample['moment_y'] == pytest.approx(1e-6)
    # Tension 10 N plus positive physical My=1 Nmm: the positive-z outer
    # fibre is most tensile. All fibres remain tensile, so A/I are gross.
    sheet = open_sheet('Cartola Formado', geometry)
    points, weights = sheet.quadrature()
    area = float(sum(weights))
    centroid_z = float(weights@points[:, 1]/area)
    iy = float(weights@((points[:, 1]-centroid_z)**2))
    program_centroid_z = calculate_section_properties('Cartola Formado', geometry).centroid_z_mm
    moment_at_mean_line_centroid = 1.-10*(centroid_z-program_centroid_z)
    expected = 10/area+moment_at_mean_line_centroid*(50-centroid_z)/iy
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'converged'
    assert info['EI_factor'] == pytest.approx(1., abs=1e-12)
    assert info['maximum_normal_stress_mpa'] == pytest.approx(expected, rel=1e-6)



def test_centroidal_shear_in_a_channel_requires_actual_warping_analysis_for_service():
    model = cantilever(.001)
    model.update_bar_section('B1', 'C Formado')
    model.update_member_profile('B1', 'C200x60x15x1', {'d': 200., 'bf': 60., 'c': 15., 't': 1.})
    result = next(row for row in PyniteAdapter().run(model, AnalysisRequest()) if row.load_reference == 'ELS')
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'not_checked'
    assert 'vínculos A/B' in info['detail']
    # A stale record claiming convergence in the old 6-DOF calculation must
    # also fail the verifier's independent applicability check.
    info.update(status='converged', EI_factor=1., EA_factor=1., normal_stress_convention='Nc,-My,+Mz')
    model.analysis_results = [result]
    model.update_bar_calculation_property('B1', 'ServiceMeasure', 3.)
    model.update_bar_calculation_property('B1', 'DeltaY', 1000.)
    model.update_bar_calculation_property('B1', 'DeltaZ', 1000.)
    checks = service_checks(verification_elements(model)[0], model)
    assert checks['serviceability']['status'] == 'not_checked'
    assert 'sem solução acoplada' in checks['serviceability']['detail']


def test_effective_widths_can_require_warping_even_under_uniform_moment_without_shear_or_torque():
    model = cantilever(.001, family='C Formado')
    actions = ActionService(model)
    actions.remove_actions()
    actions.add_action(Action('M', 'node_moment_Y', 'B', (2.1,), 'Q'))
    result = next(row for row in PyniteAdapter().run(model, AnalysisRequest()) if row.load_reference == 'ELS')
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'not_checked'
    assert 'matriz normal completa' in info['detail']
    assert max(abs(row['shear_z'])+abs(row['shear_y'])+abs(row['torque']) for row in result.member_results['B1']['samples']) < 1e-8
    info.update(status='converged', EI_factor=.64, EA_factor=.8, normal_stress_convention='Nc,-My,+Mz')
    model.analysis_results = [result]
    for key, value in (('ServiceMeasure', 3.), ('DeltaY', 1000.), ('DeltaZ', 1000.)):
        model.update_bar_calculation_property('B1', key, value)
    check = service_checks(verification_elements(model)[0], model)['serviceability']
    assert check['status'] == 'not_checked'
    assert 'sem solução acoplada' in check['detail']
