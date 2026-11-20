"""P-Delta integration against the exact elastic beam-column solution."""
from math import sqrt, tan

import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import Action, LoadCombination
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.sections.properties import calculate_section_properties
from osa.services.action_service import ActionService


def column():
    model = StructuralModel()
    model.add_node('A', 0., 0., 0.)
    model.add_node('B', 3., 0., 0.)
    model.add_bar('B1', 'A', 'B')
    model.update_bar_section('B1', 'Barra Retangular')
    model.update_bar_material('B1', 'ASTM A36', model.materials['ASTM A36'])
    model.update_member_profile('B1', '100x200', {'b': 100., 'h': 200.})
    model.update_node_supports('A', (True,)*6)
    props = calculate_section_properties('Barra Retangular', model.bars['B1'].geometry_dict())
    ei = model.materials['ASTM A36'][0]*props.iy_mm4*1e-12
    P, H = .49*ei/3**2, .1
    actions = ActionService(model)
    actions.add_action(Action('P', 'node_force_X', 'B', (-P,), 'Q'))
    actions.add_action(Action('H', 'node_force_Z', 'B', (-H,), 'Q'))
    actions.set_combination(LoadCombination('ELU', (('Q', 1.),), active_actions=('Q',), limit_state='ELU'))
    return model, P, H, ei


def test_pdelta_amplification_matches_exact_beam_column_and_records_method():
    model, P, H, ei = column()
    first = PyniteAdapter().run(model, AnalysisRequest(second_order=False))[0]
    second = PyniteAdapter().run(model, AnalysisRequest(second_order=True))[0]
    k = sqrt(P/ei)
    exact = H/(ei*k**3)*(tan(k*3)-k*3)
    assert abs(first.node_results['B']['DZ']) == pytest.approx(H*3**3/(3*ei))
    assert abs(second.node_results['B']['DZ']) == pytest.approx(exact, rel=.002)
    assert abs(second.node_results['B']['DZ']) > abs(first.node_results['B']['DZ'])
    info = second.member_results['B1']['structural_analysis']
    assert info['method'] == 'P-Delta' and info['EA_EI_factor'] == 1.


def test_reduced_rigidity_is_applied_to_ultimate_combinations_and_persists():
    model, P, H, ei = column()
    model.update_analysis_options(second_order=True, stiffness_factor=.8)
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    k = sqrt(P/(ei*.8))
    exact = H/(ei*.8*k**3)*(tan(k*3)-k*3)
    assert abs(result.node_results['B']['DZ']) == pytest.approx(exact, rel=.002)
    assert result.member_results['B1']['structural_analysis']['EA_EI_factor'] == .8
    restored = StructuralModel()
    serializer = ProjectSerializer()
    serializer.load_into(restored, serializer.dump(model))
    assert restored.second_order_analysis
    assert restored.ultimate_stiffness_factor == .8


def test_invalid_rigidity_is_rejected():
    with pytest.raises(ValueError):
        AnalysisRequest(stiffness_factor=float('nan'))
    with pytest.raises(ValueError):
        AnalysisRequest(second_order=1)
