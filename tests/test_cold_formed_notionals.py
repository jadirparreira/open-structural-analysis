"""Visible notional cases, provenance and actual second-order analysis."""
from dataclasses import replace
from math import sqrt, tan

import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.domain import Action, LoadCombination
from osa.domain.notional_inputs import NotionalStation
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.services.action_service import ActionService
from osa.services.notional_service import generate_notionals, notional_plan_current
from osa.verification.cold_formed_stability import stability_procedure


def frame(force=100.):
    model = StructuralModel()
    model.add_node('A', 0., 0., 0.)
    model.add_node('B', 0., 0., 3.)
    model.add_bar('B1', 'A', 'B')
    model.update_bar_section('B1', 'Barra Retangular')
    model.update_bar_material('B1', 'ASTM A36', model.materials['ASTM A36'])
    model.update_member_profile('B1', '100x200', {'b': 100., 'h': 200.})
    model.update_node_supports('A', (True,)*6)
    actions = ActionService(model)
    actions.add_action(Action('P', 'node_force_Z', 'B', (-force,), 'Q'))
    actions.set_combination(LoadCombination('ELU', (('Q', 1.5),), active_actions=('Q',), limit_state='ELU'))
    return model


def stations(gravity=150.):
    return (NotionalStation('Cobertura', 'B', 'A', (('ELU', gravity),)),)


def test_generation_adds_four_visible_signed_cases_without_changing_base_load_factors():
    from osa.analysis.pynite.combination_builder import CombinationBuilder

    model = frame()
    plan = generate_notionals(model, stations())
    assert len(plan.actions) == len(plan.combinations) == 4
    assert notional_plan_current(model)
    assert model.second_order_analysis and model.ultimate_stiffness_factor == .8
    forces = [(model.actions[name].kind, model.actions[name].components[0]) for name in plan.actions]
    assert forces == [('node_force_X', .45), ('node_force_X', -.45), ('node_force_Y', .45), ('node_force_Y', -.45)]
    for name in plan.combinations:
        factors = CombinationBuilder._factors_for(model.load_combinations[name], model)
        assert factors['Q'] == 1.5
        assert list(factors.values()).count(1.) == 1
    assert model.load_combinations['ELU'].factors == (('Q', 1.5),)


def test_notionals_are_solved_separately_and_classification_has_same_rigidity_reference():
    model = frame()
    plan = generate_notionals(model, stations())
    results = PyniteAdapter().run(model, AnalysisRequest())
    assert {row.load_reference for row in results} == {'ELU', *plan.combinations}
    for result in results:
        info = result.member_results['B1']['structural_analysis']
        assert info['method'] == 'P-Delta' and info['EA_EI_factor'] == .8
        assert info['notional_basis'] == plan.basis
        assert info['storey_amplification']['classification'] in ('pequena', 'média')
        assert result.node_results['A']['RXN_FZ'] == pytest.approx(150.)
    plus = next(row for row in results if row.load_reference == 'ELU [N+X]')
    minus = next(row for row in results if row.load_reference == 'ELU [N−X]')
    assert plus.node_results['A']['RXN_FX'] == pytest.approx(-.45, abs=1e-5)
    # Weak-axis EI=200 GPa * (200*100³/12) mm4 * 0.8.
    ei = 200e6*(200*100**3/12)*1e-12*.8
    kL = 3*sqrt(150/ei)
    expected_amplification = 3*(tan(kL)-kL)/kL**3
    actual = plus.member_results['B1']['structural_analysis']['storey_amplification']['maximum_ratio']
    assert actual == pytest.approx(expected_amplification, rel=.002)
    assert plus.node_results['B']['DX'] == pytest.approx(-minus.node_results['B']['DX'])
    assert stability_procedure(model, results)['status'] == 'checked'
    assert stability_procedure(model, results[:-1])['status'] == 'not_checked'


def test_changes_invalidate_derived_notionals_and_regeneration_replaces_instead_of_accumulating():
    model = frame()
    first = generate_notionals(model, stations())
    ActionService(model).add_action(Action('wind', 'node_force_X', 'B', (.1,), 'W'))
    assert not notional_plan_current(model)
    with pytest.raises(ValueError, match='nocionais'):
        PyniteAdapter().run(model, AnalysisRequest())
    second = generate_notionals(model, stations())
    assert notional_plan_current(model)
    assert len(model.actions) == 6 and len(model.load_combinations) == 5
    assert second.actions == first.actions and second.combinations == first.combinations
    assert second.basis != first.basis


def test_notional_plan_round_trip_and_unchanged_generation_is_still_current():
    model = frame()
    plan = generate_notionals(model, stations(), allow_large_displacement=True)
    saved = ProjectSerializer().dump(model)
    restored = StructuralModel()
    ProjectSerializer().load_into(restored, saved)
    assert restored.notional_plan == plan
    assert notional_plan_current(restored)
    assert restored.notional_plan.allow_large_displacement


def test_generation_rejects_missing_combinations_and_unknown_levels_atomically():
    model = frame()
    before = ProjectSerializer().dump(model)
    with pytest.raises(ValueError):
        generate_notionals(model, (replace(stations()[0], gravity_kn=(('outra', 150.),)),))
    assert ProjectSerializer().dump(model) == before
    with pytest.raises(ValueError):
        generate_notionals(model, (replace(stations()[0], upper_node='inexistente'),))
    assert ProjectSerializer().dump(model) == before


def test_large_displacement_requires_explicit_alternative_and_preserves_ratio_trace():
    model = frame(250.)
    generate_notionals(model, stations(375.))
    results = PyniteAdapter().run(model, AnalysisRequest())
    assert any(result.member_results['B1']['structural_analysis']['storey_amplification']['classification'] == 'grande' for result in results)
    item = stability_procedure(model, results)
    assert item['status'] == 'not_checked' and 'Grande deslocabilidade' in item['detail']
    model.notional_plan = replace(model.notional_plan, allow_large_displacement=True)
    assert stability_procedure(model, results)['status'] == 'checked'


def test_classification_uses_displacement_relative_to_base_at_every_level():
    from types import SimpleNamespace

    stations = (NotionalStation('2', 'N2', 'BASE', (('ELU', 1.),)),)
    target = SimpleNamespace(nodes={
        'BASE': SimpleNamespace(DX={'ELU': .001}, DY={'ELU': 0.}),
        'N1': SimpleNamespace(DX={'ELU': .004}, DY={'ELU': 0.}),
        'N2': SimpleNamespace(DX={'ELU': .009}, DY={'ELU': 0.}),
    })
    drifts = PyniteAdapter._story_drifts(target, stations, 'ELU')
    assert drifts[0]['drift_m'] == pytest.approx(.008)
    assert drifts[0]['base_node'] == 'BASE'


def test_corrupt_classification_does_not_approve_global_procedure():
    model = frame()
    generate_notionals(model, stations())
    results = PyniteAdapter().run(model, AnalysisRequest())
    results[1].member_results['B1']['structural_analysis']['storey_amplification']['rows'][0]['second_order_m'] *= .5
    assert stability_procedure(model, results)['status'] == 'not_checked'


def test_cold_formed_worker_and_memorial_include_global_proof_without_hiding_remaining_checks():
    from osa.memorial_data import calculation_memory
    from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
    from osa.ui.verification_worker import verify_model

    model = frame(.001)
    model.update_bar_section('B1', 'C Formado')
    model.update_member_profile('B1', 'C100x50x15x2', {'d': 100., 'bf': 50., 'c': 15., 't': 2.})
    generate_notionals(model, stations(.0015))
    for key in ('KL1', 'KL2', 'KLt'):
        model.update_bar_calculation_property('B1', key, 3.)
    model.update_bar_calculation_property('B1', 'ForkSupports', 1.)
    model.update_bar_bearing_regions('B1', ())
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest())
    output = verify_model(model)
    item = output['results']['bar:B1']
    assert item['checks']['stability_procedure']['status'] == 'checked'
    assert item['checks']['serviceability']['status'] == 'not_checked'
    assert item['status'] == 'not_checked'
    model.verification_results = output['results']
    html = CalculationMemorialDialog._render(calculation_memory(model, ['B1']), {}, equation_latex={})
    assert 'deslocamentos relativos à base' in html
    assert 'osa-story-base-v1' not in html
    assert 'N+X' in html
    assert '4.10.7.1.2' in html
    assert 'NÃO VERIFICADO' in html


def test_converged_postcritical_solution_is_not_accepted_as_elastic_stability():
    # Weak-axis cantilever Euler load with EI reduced to 0.8 is about 731 kN.
    # Design compression=1.5*500=750 kN, beyond that critical load.
    model = frame(500.)
    generate_notionals(model, stations(750.), allow_large_displacement=True)
    with pytest.raises(ValueError, match='tangente'):
        PyniteAdapter().run(model, AnalysisRequest())


def test_generated_cases_cannot_be_removed_under_a_dependent_custom_combination():
    from osa.services.notional_service import remove_notionals

    model = frame()
    plan = generate_notionals(model, stations())
    case = model.actions[plan.actions[0]].load_case
    ActionService(model).set_combination(LoadCombination('dependente', ((case, 1.),), active_actions=(case,), limit_state='ELS'))
    before = ProjectSerializer().dump(model)
    with pytest.raises(ValueError, match='depende'):
        remove_notionals(model)
    assert ProjectSerializer().dump(model) == before
    with pytest.raises(ValueError, match='depende'):
        generate_notionals(model, stations())
