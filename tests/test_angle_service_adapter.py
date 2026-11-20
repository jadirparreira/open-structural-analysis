"""Effective normal/Saint-Venant angle model with no sectorial restraint."""
import numpy as np
import pytest
from test_warping_service_adapter import service_model, solve_service

from osa.analysis.vlasov import rounded_section_from_sheet
from osa.domain import Action
from osa.services.action_service import ActionService
from osa.ui.verification_worker import verify_model


def angle_model():
    model = service_model('L Formado')
    model.update_member_warping_restraints('B1', (None, None))
    return model


def test_angle_service_uses_three_normal_fields_and_exact_saint_venant_twist():
    model = angle_model()
    section = rounded_section_from_sheet('L Formado', model.bars['B1'].geometry_dict(), sectorial_mode=False)
    torque = 10.
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (torque/1e6,), 'Q'))
    result = solve_service(model)
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'converged', info
    assert info['normal_mode_count'] == 3
    assert info['geometry_basis'] == 'rounded-angle-saint-venant-v1'
    assert np.asarray(info['normal_gram']).shape == (3, 3)
    G = model.materials['ASTM A36'][1]/1000
    assert result.node_results['B']['RX'] == pytest.approx(torque*3000/(G*section.j), rel=1e-8)
    for row in result.member_results['B1']['samples']:
        assert row['bimoment'] == 0.
        assert row['warping_torque'] == 0.
        assert row['saint_venant_torque'] == pytest.approx(torque/1e6, rel=1e-8)
    checks = verify_model(model)['results']['bar:B1']['checks']
    assert checks['serviceability_y']['status'] == 'checked'
    assert checks['serviceability_z']['status'] == 'checked'
    assert checks['torsion']['status'] == 'not_checked'  # not an ELU torsion capacity


@pytest.mark.parametrize('fraction', (.5, 1.1))
def test_angle_service_checks_shear_yield_even_with_zero_normal_stress(fraction):
    model = angle_model()
    section = rounded_section_from_sheet('L Formado', model.bars['B1'].geometry_dict(), sectorial_mode=False)
    fy = model.materials['ASTM A36'][4]/1000
    torque = fraction*fy/np.sqrt(3)*section.j/model.bars['B1'].geometry_dict()['t']
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (torque/1e6,), 'Q'))
    info = solve_service(model).member_results['B1']['service_stiffness']
    if fraction < 1:
        assert info['status'] == 'converged', info
        assert info['maximum_equivalent_stress_bound_mpa'] == pytest.approx(fraction*fy, rel=1e-7)
    else:
        assert info['status'] == 'not_checked'
        assert 'elasticidade ELS' in info['detail']


def test_angle_effective_matrix_and_pole_are_transported_to_the_actual_structural_solve():
    model = angle_model()
    model.update_node('B', .3, 0., 0.)
    model.update_member_profile('B1', 'L80x50x1.5', {'d': 80., 'bf': 50., 't': 1.5})
    model.update_node_supports('B', (False, True, True, True, True, True))
    ActionService(model).add_action(Action('N', 'node_force_X', 'B', (-8.,), 'Q'))
    section = rounded_section_from_sheet('L Formado', model.bars['B1'].geometry_dict(), sectorial_mode=False)
    result = solve_service(model)
    data = result.member_results['B1']
    info = data['service_stiffness']
    assert info['status'] == 'converged', info
    assert info['iterations'] > 1
    normal = np.asarray(info['normal_gram'])
    assert normal[0, 0] < .99*section.area
    assert np.asarray(data['warping_analysis']['normal_gram_geometric']) == pytest.approx(normal, rel=1e-12, abs=1e-7)
    applied_pole = np.asarray(data['warping_analysis']['normal_origin_section_mm'])+np.asarray(data['warping_analysis']['shear_center_offset_geometric_mm'])
    assert info['shear_center_section_mm'] == pytest.approx(applied_pole, abs=1e-10)
    gross_pole = np.array((section.ysc, section.zsc))+np.asarray(info['normal_origin_section_mm'])
    assert np.linalg.norm(applied_pole-gross_pole) > 1e-6
    assert info['elasticity'] == 'proven_by_upper_bound'
    stress = 8000/normal[0, 0]
    assert info['maximum_normal_stress_mpa'] == pytest.approx(stress, rel=1e-7)
    assert result.node_results['B']['DX'] == pytest.approx(-stress*300/(model.materials['ASTM A36'][0]/1000)/1000, rel=1e-7)
    for row in data['samples']:
        assert row['moment_y'] == pytest.approx(-stress*normal[0, 1]/1e6, abs=1e-8)
        assert row['moment_z'] == pytest.approx(stress*normal[0, 2]/1e6, abs=1e-8)



def test_angle_point_torque_does_not_artificially_enforce_twist_rate_continuity():
    from osa.analysis import AnalysisRequest
    from osa.analysis.pynite import PyniteAdapter

    model = angle_model()
    model.add_node('M', 1.5, 0., 0.)
    torque = 10.
    ActionService(model).add_action(Action('T', 'node_moment_X', 'M', (torque/1e6,), 'Q'))
    section = rounded_section_from_sheet('L Formado', model.bars['B1'].geometry_dict(), sectorial_mode=False)
    result = PyniteAdapter().run(model, AnalysisRequest(load_combinations=('Case',), warping=True))[0]
    exact = torque*1500/(model.materials['ASTM A36'][1]/1000*section.j)
    assert result.node_results['M']['RX'] == pytest.approx(exact, rel=1e-8)
    assert result.node_results['B']['RX'] == pytest.approx(exact, rel=1e-8)
    for row in result.member_results['B1']['samples']:
        expected = torque*min(row['x']*1000, 1500)/(model.materials['ASTM A36'][1]/1000*section.j)
        assert row['twist'] == pytest.approx(expected, rel=1e-8, abs=1e-12)
        assert row['bimoment'] == 0.
        assert row['warping_torque'] == 0.


def test_angle_second_order_service_keeps_the_three_field_elasticity_proof():
    from osa.analysis import AnalysisRequest
    from osa.analysis.pynite import PyniteAdapter

    model = angle_model()
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-.1,), 'Q'))
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(load_combinations=('ELS',), warping=True, second_order=True))[0]
    info = result.member_results['B1']['service_stiffness']
    assert info['status'] == 'converged', info
    assert info['normal_mode_count'] == 3
    assert info['elasticity'] == 'proven_by_upper_bound'
