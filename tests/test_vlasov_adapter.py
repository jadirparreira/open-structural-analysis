"""Actual adapter solves with centroidal loads, warping and continuity."""
import itertools
import json

import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.vlasov import rounded_section_from_sheet
from osa.domain import Action, LoadCombination
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.services.action_service import ActionService
from osa.verification.cold_formed_torsion import TorsionEndModel, prescribed_torque


def model_for(family='C Formado'):
    model = StructuralModel()
    model.add_node('A', 0., 0., 0.)
    model.add_node('B', 3., 0., 0.)
    model.add_bar('B1', 'A', 'B')
    model.update_bar_section('B1', family)
    model.update_bar_material('B1', 'ASTM A36', model.materials['ASTM A36'])
    geometry = {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.}
    model.update_member_profile('B1', 'section', geometry)
    model.update_node_supports('A', (True,)*6)
    model.update_member_warping_restraints('B1', ('blocked', 'free'))
    ActionService(model).set_combination(LoadCombination('Case', (('Q', 1.),), active_actions=('Q',), limit_state='CAR'))
    return model


def solve(model):
    return PyniteAdapter().run(model, AnalysisRequest(warping=True))[0]


def test_centroidal_tip_force_generates_shear_center_torque_and_matches_exact_solution():
    model = model_for()
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    material = model.materials['ASTM A36']
    E, G = material[0]/1000, material[1]/1000
    reference = TorsionEndModel(3000., E, G, section.j, section.cw, 'blocked', 'free')
    result = solve(model)
    expected_torque = section.ysc  # -ysc*Fz with Fz=-1 N
    expected_theta = expected_torque*reference.compliance_rad_nmm
    expected_w = -(3000**3/(3*E*section.iy)+section.ysc**2*reference.compliance_rad_nmm)/1000
    assert result.node_results['B']['RX'] == pytest.approx(expected_theta, rel=1e-5)
    assert result.node_results['B']['DZ'] == pytest.approx(expected_w, rel=1e-5)
    assert result.node_results['A']['RXN_FZ'] == pytest.approx(.001, rel=1e-8)
    assert result.node_results['A']['RXN_MX'] == pytest.approx(0., abs=1e-10)
    samples = result.member_results['B1']['samples']
    assert [row['torque_sc'] for row in samples] == pytest.approx([expected_torque/1e6]*len(samples), abs=1e-12)
    assert samples[0]['moment_y'] == pytest.approx(.003, rel=1e-8)
    exact = prescribed_torque((0., 3000.), (expected_torque, expected_torque), E=E, G=G, J=section.j, Cw=section.cw, warping_start='blocked')
    assert samples[0]['bimoment'] == pytest.approx(exact.bimoment_nmm2[0]/1e9, rel=1e-4)
    assert samples[-1]['bimoment'] == pytest.approx(0., abs=1e-10)
    assert result.member_results['B1']['warping_analysis']['status'] == 'solved'
    json.dumps(result.member_results)


def test_force_applied_at_shear_center_does_not_excite_twist():
    model = model_for()
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    actions = ActionService(model)
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    actions.add_action(Action('eccentric', 'node_moment_X', 'B', (-section.ysc/1e6,), 'Q'))
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(0., abs=1e-10)
    assert max(abs(row['torque_sc']) for row in result.member_results['B1']['samples']) < 1e-10


def test_continuous_warping_across_two_bars_matches_unsplit_member():
    model = model_for()
    actions = ActionService(model)
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    reference = solve(model)
    model.add_node('M', 1.5, 0., 0.)
    model.update_bar('B1', 'A', 'M')
    model.add_bar('B2', 'M', 'B', template=model.bars['B1'])
    model.update_member_warping_restraints('B1', ('blocked', 'continuous'))
    model.update_member_warping_restraints('B2', ('continuous', 'free'))
    result = solve(model)
    assert result.node_results['B']['DZ'] == pytest.approx(reference.node_results['B']['DZ'], rel=1e-5)
    assert result.node_results['B']['RX'] == pytest.approx(reference.node_results['B']['RX'], rel=1e-5)
    assert result.member_results['B1']['end']['bimoment'] == pytest.approx(result.member_results['B2']['start']['bimoment'], rel=1e-5)


def test_unknown_or_incompatible_warping_restraints_never_silently_default():
    model = model_for()
    model.update_member_warping_restraints('B1', (None, None))
    with pytest.raises(ValueError, match='Declare'):
        solve(model)
    model.update_member_warping_restraints('B1', ('continuous', 'free'))
    with pytest.raises(ValueError, match='outra extremidade'):
        solve(model)


def test_warping_data_persist_and_invalidate_analysis_on_physical_changes():
    model = model_for()
    model.update_analysis_options(second_order=False, stiffness_factor=1., warping=True)
    restored = StructuralModel()
    ProjectSerializer().load_into(restored, ProjectSerializer().dump(model))
    assert restored.warping_analysis
    assert restored.bars['B1'].warping_restraints == ('blocked', 'free')
    restored.analysis_results = [solve(restored)]
    revision = restored.revision
    restored.update_member_warping_restraints('B1', ('free', 'free'))
    assert restored.revision == revision+1 and not restored.analysis_results


def test_distributed_centroidal_force_has_consistent_torsion_and_exact_equilibrium():
    model = model_for()
    ActionService(model).add_member_distributed_force('B1', 'Z', -.001, -.001, 'Q')
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    rod = TorsionEndModel(3000., E, G, section.j, section.cw, 'blocked', 'free')
    torque_density = section.ysc*.001
    expected_theta = rod.compliance_rad_nmm*rod.consistent_torque_load(0., 3000., torque_density, torque_density)[1]
    expected_w = (-.001*3000**4/(8*E*section.iy)-section.ysc*expected_theta)/1000
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(expected_theta, rel=1e-5)
    assert result.node_results['B']['DZ'] == pytest.approx(expected_w, rel=1e-5)
    assert result.node_results['A']['RXN_FZ'] == pytest.approx(.003, rel=1e-8)
    assert result.node_results['A']['RXN_MX'] == pytest.approx(0., abs=1e-10)
    for sample in result.member_results['B1']['samples']:
        expected = torque_density*(3000-sample['x']*1000)/1e6
        assert sample['torque_sc'] == pytest.approx(expected, abs=1e-11)
    assert result.member_results['B1']['end']['bimoment'] == pytest.approx(0., abs=1e-10)


def test_geometric_result_components_match_the_legacy_solver_when_shear_center_is_centroidal():
    model = model_for('Z90 Formado')
    actions = ActionService(model)
    actions.add_action(Action('Fz', 'node_force_Z', 'B', (-.001,), 'Q'))
    actions.add_action(Action('Fy', 'node_force_Y', 'B', (.0003,), 'Q'))
    baseline = PyniteAdapter().run(model, AnalysisRequest(warping=False))[0]
    result = solve(model)
    import numpy as np

    physical = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E = model.materials['ASTM A36'][0]/1000
    curvature = np.linalg.solve(E*np.array(((physical.iz, physical.iyz), (physical.iyz, physical.iy))), (.3, -1.))
    translation = curvature*3000**3/3/1000
    slope = curvature*3000**2/2
    for field, expected in zip(('DY', 'DZ', 'RY', 'RZ'), (*translation, -slope[1], slope[0]), strict=True):
        assert result.node_results['B'][field] == pytest.approx(expected, rel=1e-7)
    first = result.member_results['B1']['start']
    for field in ('shear_y', 'shear_z', 'moment_y', 'moment_z'):
        assert first[field] == pytest.approx(baseline.member_results['B1']['start'][field], abs=1e-11)


def test_cold_member_can_share_a_frame_with_an_ordinary_six_dof_member():
    model = model_for()
    model.add_node('M', 1.5, 0., 0.)
    model.update_bar('B1', 'A', 'M')
    model.add_bar('B2', 'M', 'B')
    model.update_bar_section('B2', 'Barra Retangular')
    model.update_bar_material('B2', 'ASTM A36', model.materials['ASTM A36'])
    model.update_member_profile('B2', 'solid', {'b': 100., 'h': 200.})
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    from osa.sections.properties import calculate_section_properties
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    other = calculate_section_properties('Barra Retangular', model.bars['B2'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    rod = TorsionEndModel(1500., E, G, section.j, section.cw, 'blocked', 'free')
    expected = -((3000**3-1500**3)/(3*E*section.iy)+1500**3/(3*E*other.iy_mm4)+section.ysc**2*rod.compliance_rad_nmm)/1000
    result = solve(model)
    assert result.node_results['B']['DZ'] == pytest.approx(expected, rel=1e-5)
    assert 'warping_analysis' not in result.member_results['B2']
    assert result.node_results['A']['RXN_FZ'] == pytest.approx(.001, rel=1e-8)


def test_torsional_joint_spring_keeps_its_physical_value_under_internal_meshing():
    model = model_for()
    model.update_member_rotation_flexibility_percent('B1', (50, 0, 0, 0, 0, 0))
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (1e-6,), 'Q'))
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    rod = TorsionEndModel(3000., E, G, section.j, section.cw, 'blocked', 'free')
    # Existing 50% input defines kspring=GJ/L using gross physical length.
    spring_compliance = 3000/(G*section.j)
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(rod.compliance_rad_nmm+spring_compliance, rel=1e-5)
    assert result.member_results['B1']['start']['twist'] == pytest.approx(spring_compliance, rel=1e-7)
    assert result.node_results['A']['RX'] == 0.


def test_reversed_axis_with_mirrored_profile_preserves_physical_warping_continuity():
    model = model_for()
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    reference = solve(model)
    model.add_node('M', 1.5, 0., 0.)
    model.update_bar('B1', 'A', 'M')
    model.add_bar('B2', 'B', 'M', template=model.bars['B1'])
    model.update_member_section_mirrored('B2', True)
    model.update_member_warping_restraints('B1', ('blocked', 'continuous'))
    model.update_member_warping_restraints('B2', ('free', 'continuous'))
    result = solve(model)
    assert result.node_results['B']['DZ'] == pytest.approx(reference.node_results['B']['DZ'], rel=1e-5)
    assert result.node_results['B']['RX'] == pytest.approx(reference.node_results['B']['RX'], rel=1e-5)
    assert result.member_results['B1']['end']['bimoment'] == pytest.approx(-result.member_results['B2']['end']['bimoment'], rel=1e-5)


def test_explicit_bimoment_represents_localized_axial_transfer_and_is_not_hidden_by_zero_total_torque():
    from osa.sections.thin_walled import open_sheet
    from osa.ui.verification_worker import verify_model
    from osa.verification.cold_formed_torsion import thin_wall_stresses

    model = model_for('Z Formado')
    # Manual, Annex A: mean-line bw=200,bf=50,t=3 mm. A localized tensile
    # force at the web centre has omega(P)=8.333... cm², B=N*omega(P).
    model.update_member_profile('B1', 'Z200x50x3', {'d': 203., 'bf': 48.5, 't': 3.})
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (100.,), 'Q'))
    # End-B work-conjugate load is -B, in kN m².
    actions.add_member_bimoment('B1', 'B', -1/12, 'Q')
    with pytest.raises(ValueError, match='bimomento'):
        PyniteAdapter().run(model, AnalysisRequest(warping=False))
    result = solve(model)
    end = result.member_results['B1']['end']
    assert end['axial'] == pytest.approx(-100., rel=1e-8)
    assert end['bimoment'] == pytest.approx(1/12, rel=1e-7)
    assert max(abs(row['torque_sc']) for row in result.member_results['B1']['samples']) < 1e-10
    sheet = open_sheet('Z Formado', model.bars['B1'].geometry_dict())
    stresses = thin_wall_stresses(sheet, axial=100_000., bimoment=end['bimoment']*1e9)
    assert max(stresses.normal_mpa) == pytest.approx(148.148148148, rel=1e-7)
    assert min(stresses.normal_mpa) == pytest.approx(-74.074074074, rel=1e-7)
    model.analysis_results = [result]
    check = verify_model(model)['results']['bar:B1']['checks']['torsion']
    assert check['status'] == 'not_checked'
    assert 'bimomento' in check['detail']


def test_large_sparse_system_preserves_the_same_continuous_member_solution():
    model = model_for()
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    reference = solve(model)
    template = model.bars['B1']
    names = ['A']
    for i in range(1, 10):
        name = 'M'+str(i)
        model.add_node(name, .3*i, 0., 0.)
        names.append(name)
    names.append('B')
    model.update_bar('B1', 'A', 'M1')
    for i, (start, end) in enumerate(itertools.pairwise(names)):
        name = 'B'+str(i+1)
        if i:
            model.add_bar(name, start, end, template=template)
        model.update_member_warping_restraints(name, ('blocked' if i == 0 else 'continuous', 'free' if i == 9 else 'continuous'))
    result = solve(model)
    assert result.node_results['B']['DZ'] == pytest.approx(reference.node_results['B']['DZ'], rel=1e-5)
    assert result.node_results['B']['RX'] == pytest.approx(reference.node_results['B']['RX'], rel=1e-5)


def test_uniform_distributed_torque_is_integrated_continuously_with_warping():
    model = model_for()
    ActionService(model).add_member_moment('B1', 'X', 1e-6, 'Q')
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    rod = TorsionEndModel(3000., E, G, section.j, section.cw, 'blocked', 'free')
    density = .001  # N mm/mm
    expected = rod.compliance_rad_nmm*rod.consistent_torque_load(0., 3000., density, density)[1]
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(expected, rel=1e-5)
    assert result.node_results['A']['RXN_MX'] == pytest.approx(-3e-6, rel=1e-8)
    for row in result.member_results['B1']['samples']:
        assert row['torque_sc'] == pytest.approx(density*(3000-row['x']*1000)/1e6, abs=1e-12)


def test_continuous_force_at_shear_center_has_no_artificial_point_torque_residuals():
    model = model_for()
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    actions = ActionService(model)
    actions.add_member_distributed_force('B1', 'Z', -.001, -.001, 'Q')
    actions.add_member_moment('B1', 'X', -section.ysc*1e-6, 'Q')
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(0., abs=1e-10)
    assert max(abs(row['bimoment']) for row in result.member_results['B1']['samples']) < 1e-10
    assert max(abs(row['torque_sc']) for row in result.member_results['B1']['samples']) < 1e-10


def test_zero_sectorial_mode_does_not_require_invented_angle_warping_restraints():
    model = model_for('L Formado')
    model.update_member_warping_restraints('B1', (None, None))
    ActionService(model).add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = solve(model)
    assert not result.member_results['B1']['warping_analysis']['end_warping_dofs']['A']['sectorial_degree']
    assert max(abs(row['bimoment']) for row in result.member_results['B1']['samples']) < 1e-10


@pytest.mark.parametrize('compression', (True, False))
def test_second_order_bending_matches_exact_coupled_principal_beam_columns(compression):
    from math import pi, sqrt, tan, tanh

    import numpy as np

    model = model_for('Z90 Formado')
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    L = 3000.
    values, vectors = np.linalg.eigh(np.array(((section.iz, section.iyz), (section.iyz, section.iy))))
    normal = .35*min(pi*pi*E*min(values)/(4*L*L), (G*section.j+E*section.cw*(pi/(2*L))**2)/section.r0_squared)
    if not compression:
        normal = -normal
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-normal/1000,), 'Q'))
    actions.add_action(Action('H', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    compliance = []
    for inertia in values:
        k = sqrt(abs(normal)/(E*inertia))
        compliance.append((tan(k*L)-k*L)/(normal*k) if compression else (tanh(k*L)-k*L)/(normal*k))
    expected = vectors@np.diag(compliance)@vectors.T@np.array((0., -1.))
    assert result.node_results['B']['DY'] == pytest.approx(expected[0]/1000, rel=2e-5)
    assert result.node_results['B']['DZ'] == pytest.approx(expected[1]/1000, rel=2e-5)
    end = result.member_results['B1']['end']
    assert end['moment_y'] == pytest.approx(0., abs=1e-9)
    assert end['moment_z'] == pytest.approx(0., abs=1e-9)
    root = result.member_results['B1']['start']
    assert root['moment_y'] == pytest.approx(.003-normal*expected[1]/1e6, rel=2e-5)
    assert root['moment_z'] == pytest.approx(-normal*expected[0]/1e6, rel=2e-5)
    assert root['axial'] == pytest.approx(normal/1000, rel=1e-9)
    assert result.member_results['B1']['structural_analysis']['tangent_stability']['status'] == 'positive'


@pytest.mark.parametrize('tensile_force', (0., 100_000.))
def test_second_order_torsion_matches_exact_reduced_saint_venant_rigidity(tensile_force):
    model = model_for('Z90 Formado')
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    normal = -tensile_force if tensile_force else .2*G*section.j/section.r0_squared
    torque = 10.
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-normal/1000,), 'Q'))
    actions.add_action(Action('T', 'node_moment_X', 'B', (torque/1e6,), 'Q'))
    reference = TorsionEndModel(3000., E, G-normal*section.r0_squared/section.j, section.j, section.cw, 'blocked', 'free')
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    theta = torque*reference.compliance_rad_nmm
    assert result.node_results['B']['RX'] == pytest.approx(theta, rel=2e-5)
    end = result.member_results['B1']['end']
    assert end['bimoment'] == pytest.approx(0., abs=1e-9)
    # Material torque differs from the applied generalized torque under N.
    rate = result.member_results['B1']['warping_analysis']['end_warping_dofs']['B']['rate_rad_per_m']/1000
    assert end['torque_sc'] == pytest.approx((torque+normal*section.r0_squared*rate)/1e6, rel=1e-8)


def test_second_order_rejects_postcritical_flexural_equilibrium():
    from math import pi
    model = model_for('Z90 Formado')
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E = model.materials['ASTM A36'][0]/1000
    weak = min(__import__('numpy').linalg.eigvalsh(((section.iz, section.iyz), (section.iyz, section.iy))))
    critical = pi*pi*E*weak/(4*3000**2)
    ActionService(model).add_action(Action('N', 'node_force_X', 'B', (-1.1*critical/1000,), 'Q'))
    with pytest.raises(ValueError, match='estável|instáveis'):
        PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))


def test_second_order_mixed_frame_matches_independent_piecewise_beam_column_transfer():
    import numpy as np
    from scipy.linalg import expm

    from osa.sections.properties import calculate_section_properties

    model = model_for('Z90 Formado')
    model.add_node('M', 1.5, 0., 0.)
    model.update_bar('B1', 'A', 'M')
    model.add_bar('B2', 'M', 'B')
    model.update_bar_section('B2', 'Barra Retangular')
    model.update_bar_material('B2', 'ASTM A36', model.materials['ASTM A36'])
    model.update_member_profile('B2', 'solid', {'b': 50., 'h': 100.})
    normal = 100.
    E = model.materials['ASTM A36'][0]/1000
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-normal/1000,), 'Q'))
    actions.add_action(Action('H', 'node_force_Z', 'B', (-.001,), 'Q'))
    transfer = np.eye(8)
    for name in ('B1', 'B2'):
        member = model.bars[name]
        if name == 'B1':
            physical = rounded_section_from_sheet(member.section, member.geometry_dict())
            inertia = np.array(((physical.iz, physical.iyz), (physical.iyz, physical.iy)))
        else:
            props = calculate_section_properties(member.section, member.geometry_dict())
            inertia = np.array(((props.iz_mm4, props.iyz_mm4), (props.iyz_mm4, props.iy_mm4)))
        matrix = np.zeros((8, 8))
        matrix[0, 2] = matrix[1, 3] = 1.
        matrix[2:4, 4:6] = np.linalg.inv(E*inertia)
        matrix[4, 2] = matrix[5, 3] = -normal
        matrix[4, 6] = matrix[5, 7] = 1.
        transfer = expm(matrix*1500)@transfer
    root = np.linalg.solve(transfer[4:8, 4:8], (0., 0., 0., 1.))
    expected = transfer[:, 4:8]@root
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    assert result.node_results['B']['DY'] == pytest.approx(expected[0]/1000, rel=5e-5)
    assert result.node_results['B']['DZ'] == pytest.approx(expected[1]/1000, rel=5e-5)
    assert result.member_results['B1']['end']['moment_y'] == pytest.approx(result.member_results['B2']['start']['moment_y'], rel=5e-5)
    assert result.member_results['B1']['end']['moment_z'] == pytest.approx(result.member_results['B2']['start']['moment_z'], rel=5e-5)


def test_second_order_centroidal_force_matches_independent_coupled_vlasov_transfer():
    import numpy as np
    from scipy.linalg import expm

    model = model_for()
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    normal = 100.
    constitutive = E*np.array(((section.iz, section.iyz, 0.), (section.iyz, section.iy, 0.), (0., 0., section.cw)))
    initial = normal*np.array(((1., 0., section.zsc), (0., 1., -section.ysc), (section.zsc, -section.ysc, section.r0_squared)))
    gradient = np.diag((0., 0., G*section.j))-initial
    matrix = np.zeros((12, 12))
    matrix[:3, 3:6] = np.eye(3)
    matrix[3:6, 6:9] = np.linalg.inv(constitutive)
    matrix[6:9, 3:6] = gradient
    matrix[6:9, 9:12] = -np.eye(3)
    transfer = expm(matrix*3000)
    root = np.linalg.solve(transfer[6:12, 6:12], (0., 0., 0., 0., -1., section.ysc))
    end = transfer[:, 6:12]@root
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-normal/1000,), 'Q'))
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    assert result.node_results['B']['DZ'] == pytest.approx((end[1]-section.ysc*end[2])/1000, rel=3e-5)
    assert result.node_results['B']['RX'] == pytest.approx(end[2], rel=3e-5)
    assert result.member_results['B1']['end']['bimoment'] == pytest.approx(0., abs=1e-9)


def test_second_order_distributed_axial_load_uses_variable_normal_force():
    import numpy as np
    from scipy.integrate import solve_ivp

    model = model_for('Z90 Formado')
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E = model.materials['ASTM A36'][0]/1000
    inverse = np.linalg.inv(E*np.array(((section.iz, section.iyz), (section.iyz, section.iy))))
    def derivative(x, values):
        transfer = values.reshape((8, 8))
        matrix = np.zeros((8, 8))
        matrix[0, 2] = matrix[1, 3] = 1.
        matrix[2:4, 4:6] = inverse
        matrix[4, 2] = matrix[5, 3] = -.05*(3000-x)
        matrix[4, 6] = matrix[5, 7] = 1.
        return (matrix@transfer).reshape(-1)
    integration = solve_ivp(derivative, (0., 3000.), np.eye(8).reshape(-1), rtol=1e-11, atol=1e-12)
    assert integration.success
    transfer = integration.y[:, -1].reshape((8, 8))
    root = np.linalg.solve(transfer[4:8, 4:8], (0., 0., 0., 1.))
    expected = transfer[:, 4:8]@root
    actions = ActionService(model)
    actions.add_member_distributed_force('B1', 'X', -.05, -.05, 'Q')
    actions.add_action(Action('H', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    assert result.node_results['B']['DY'] == pytest.approx(expected[0]/1000, rel=3e-5)
    assert result.node_results['B']['DZ'] == pytest.approx(expected[1]/1000, rel=3e-5)
    for sample in result.member_results['B1']['samples']:
        assert sample['axial'] == pytest.approx(.05*(3-sample['x']), abs=1e-10)
    assert result.member_results['B1']['end']['moment_y'] == pytest.approx(0., abs=1e-9)


def test_second_order_warping_integrates_reduced_rigidity_notionals_and_global_proof():
    from test_cold_formed_notionals import frame, stations

    from osa.services.notional_service import generate_notionals, notional_plan_current
    from osa.verification.cold_formed_stability import stability_procedure

    model = frame(.1)
    model.update_bar_section('B1', 'C Formado')
    model.update_member_profile('B1', 'section', {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.})
    model.update_member_warping_restraints('B1', ('blocked', 'free'))
    model.update_analysis_options(second_order=False, stiffness_factor=1., warping=True)
    plan = generate_notionals(model, stations(.15))
    assert notional_plan_current(model)
    results = PyniteAdapter().run(model, AnalysisRequest())
    assert {row.load_reference for row in results} == {'ELU', *plan.combinations}
    for result in results:
        data = result.member_results['B1']
        assert data['warping_analysis']['status'] == 'solved'
        assert data['structural_analysis']['EA_EI_factor'] == .8
        assert data['structural_analysis']['tangent_stability']['status'] == 'positive'
        assert data['structural_analysis']['storey_amplification']['classification'] in ('pequena', 'média')
        assert result.node_results['A']['RXN_FZ'] == pytest.approx(.15, rel=1e-8)
    assert stability_procedure(model, results)['status'] == 'checked'
    assert notional_plan_current(model)


@pytest.mark.parametrize('length', (.1, 100.))
def test_warping_boundary_layer_is_resolved_for_short_and_long_members(length):
    model = model_for('Z90 Formado')
    model.update_node('B', length, 0., 0.)
    section = rounded_section_from_sheet('Z90 Formado', model.bars['B1'].geometry_dict())
    E, G = (model.materials['ASTM A36'][i]/1000 for i in (0, 1))
    torque = 1.
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (torque/1e6,), 'Q'))
    reference = TorsionEndModel(length*1000, E, G, section.j, section.cw, 'blocked', 'free')
    exact = prescribed_torque((0., length*1000), (torque, torque), E=E, G=G, J=section.j, Cw=section.cw, warping_start='blocked')
    result = solve(model)
    assert result.node_results['B']['RX'] == pytest.approx(torque*reference.compliance_rad_nmm, rel=1e-5)
    assert result.member_results['B1']['start']['bimoment'] == pytest.approx(exact.bimoment_nmm2[0]/1e9, rel=1e-4)



def test_released_torsional_end_does_not_hide_a_rigid_twist_mechanism():
    model = model_for()
    model.update_member_releases('B1', (False,)*6+(True,)+(False,)*5)
    ActionService(model).add_action(Action('T', 'node_moment_X', 'B', (1e-6,), 'Q'))
    with pytest.raises(ValueError, match='estável|instáveis'):
        solve(model)


def test_second_order_section_recovery_preserves_equilibrium_inside_every_element():
    model = model_for()
    actions = ActionService(model)
    actions.add_action(Action('N', 'node_force_X', 'B', (-1.,), 'Q'))
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    result = PyniteAdapter().run(model, AnalysisRequest(warping=True, second_order=True))[0]
    section = rounded_section_from_sheet('C Formado', model.bars['B1'].geometry_dict())
    GJ = model.materials['ASTM A36'][1]*section.j*1e-12
    polar = (section.r0_squared-section.ysc**2-section.zsc**2)/1e6
    ysc, zsc = section.ysc/1000, section.zsc/1000
    samples = result.member_results['B1']['samples']
    for left, right in itertools.pairwise(samples):
        dx = right['x']-left['x']
        dv = right['deflection_y']-left['deflection_y']
        dw = right['deflection_z']-left['deflection_z']
        dt = right['twist']-left['twist']
        normal = left['axial']
        assert right['moment_y']-left['moment_y'] == pytest.approx(-left['shear_z']*dx+normal*dw, abs=1e-10)
        assert right['moment_z']-left['moment_z'] == pytest.approx(-left['shear_y']*dx+normal*dv, abs=1e-10)
        expected = left['generalized_torque_sc']*dx-GJ*dt+normal*(zsc*dv-ysc*dw+polar*dt)
        assert right['bimoment']-left['bimoment'] == pytest.approx(expected, abs=1e-10)
