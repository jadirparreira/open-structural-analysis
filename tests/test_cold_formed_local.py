"""Normative branch and scope checks of NBR 14762 web/bearing resistance."""
from math import sqrt

import pytest

from osa.verification.cold_formed_local import bearing_resistance, web_shear_resistance


@pytest.mark.parametrize(('h', 'branch'), [(50., 'yield'), (80., 'inelastic'), (120., 'elastic')])
def test_three_web_shear_branches(h, branch):
    capacity, data = web_shear_resistance(h, 1., 200_000., 250.)
    assert data['branch'] == branch
    expected = (.6*250*h/1.1 if branch == 'yield' else
                .65*sqrt(5*250*200_000)/1.1 if branch == 'inelastic' else .905*200_000*5/h/1.1)
    assert capacity == pytest.approx(expected)


def test_qualified_transverse_stiffeners_increase_kv_only_within_three_web_depths():
    base, _ = web_shear_resistance(200., 1., 200_000., 250.)
    close, data = web_shear_resistance(200., 1., 200_000., 250., stiffener_spacing=200.)
    assert data['kv'] == 10.
    assert close > base
    assert web_shear_resistance(200., 1., 200_000., 250., stiffener_spacing=601.)[0] == pytest.approx(base)


def test_table_d2_connected_stiffened_channel_end_one_flange():
    # D.2: alpha=4.6, ar=.14, ac=.35, ah=.02, gamma=1.35.
    result = bearing_resistance('C Formado', h=92., t=2., ri=2., c=40., fy=250.,
                                edge_distance=0., connected=True)
    expected = 4.6*4*250*(1-.14)*(1+.35*sqrt(20))*(1-.02*sqrt(46))/1.35
    assert result.per_web_n == pytest.approx(expected)
    assert result.table == 'D.2' and result.end_loading


def test_table_d3_z_disconnected_one_flange_has_its_own_coefficients():
    result = bearing_resistance('Z90 Formado', h=92., t=2., ri=2., c=40., fy=250.,
                                edge_distance=0., connected=False)
    expected = 5.7*4*250*(1-.09)*(1+.02*sqrt(20))*(1-.001*sqrt(46))/1.35
    assert result.per_web_n == pytest.approx(expected)
    assert result.table == 'D.3'


def test_table_d4_returns_one_web_capacity_without_assuming_force_distribution():
    result = bearing_resistance('Cartola Formado', h=92., t=2., ri=2., c=40., fy=250.,
                                edge_distance=500., connected=True)
    expected = 19.5*4*250*(1-.13)*(1+.13*sqrt(20))*(1-.04*sqrt(46))/1.35
    assert result.per_web_n == pytest.approx(expected)
    assert result.table == 'D.4' and not result.end_loading


def test_end_internal_transition_uses_clear_distance_and_not_bearing_center():
    parameters = {'h': 92., 't': 2., 'ri': 2., 'c': 40., 'fy': 250., 'connected': False}
    assert bearing_resistance('C Formado', edge_distance=1.5*92, **parameters).end_loading
    assert not bearing_resistance('C Formado', edge_distance=1.5*92+.01, **parameters).end_loading


def test_connected_two_flange_internal_force_requires_more_than_2_5h():
    with pytest.raises(ValueError, match='2,5h'):
        bearing_resistance('C Formado', h=92., t=2., ri=2., c=40., fy=250.,
                           edge_distance=200., connected=True, loaded_flanges=2)
    assert bearing_resistance('C Formado', h=92., t=2., ri=2., c=40., fy=250.,
                              edge_distance=231., connected=True, loaded_flanges=2).per_web_n > 0


@pytest.mark.parametrize('overrides', [{'c': 19.9}, {'h': 401.}, {'c': 185.}, {'ri': 19.}, {'angle': 60.}])
def test_bearing_scope_is_not_extrapolated(overrides):
    parameters = {'h': 92., 't': 2., 'ri': 2., 'c': 40., 'fy': 250., 'edge_distance': 0., 'connected': True}
    with pytest.raises(ValueError):
        bearing_resistance('C Formado', **{**parameters, **overrides})


def test_cartola_unsupported_two_flange_disconnected_case_is_explicit():
    with pytest.raises(ValueError, match='não prevista'):
        bearing_resistance('Cartola Formado', h=92., t=2., ri=2., c=40., fy=250.,
                           edge_distance=0., connected=False, loaded_flanges=2)


def test_bearing_regions_are_checked_per_web_and_become_stale_on_load_changes():
    from test_cold_formed_service import cantilever

    from osa.domain import Action
    from osa.domain.local_force_inputs import BearingRegion
    from osa.services.action_service import ActionService
    from osa.verification.cold_formed_local import bearing_checks
    from osa.verification.elements import verification_elements

    model = cantilever(.001, family='C Formado')
    element = verification_elements(model)[0]
    assert bearing_checks(element, model, 250.)['bearing_B1']['status'] == 'not_checked'
    region = BearingRegion('Apoio A', 0., 30., 10., 'ELU', 0., True, 1)
    model.update_bar_bearing_regions('B1', (region,))
    item = bearing_checks(element, model, 250.)['bearing_B1_Apoio A']
    assert item['status'] == 'checked'
    expected = bearing_resistance('C Formado', h=196., t=1., ri=1., c=30., fy=250., edge_distance=0., connected=True)
    assert item['capacity'] == pytest.approx(expected.per_web_n/1000)
    assert item['applied'] == 10. and item['utilization'] > 1
    ActionService(model).add_action(Action('nova', 'node_force_Z', 'B', (-.1,), 'Q'))
    assert bearing_checks(element, model, 250.)['bearing_B1']['status'] == 'not_checked'
    assert model.bars['B1'].bearing_regions == (region,)


def test_bearing_regions_round_trip_and_invalid_input_are_rejected():
    from dataclasses import replace

    from test_cold_formed_service import cantilever

    from osa.domain.local_force_inputs import BearingRegion
    from osa.model import StructuralModel
    from osa.persistence.project_serializer import ProjectSerializer
    from osa.verification.cold_formed_local import bearing_checks
    from osa.verification.elements import verification_elements

    model = cantilever(.001, family='C Formado')
    region = BearingRegion('A', 0., 30., 2., 'ELU', 0.)
    with pytest.raises(ValueError):
        model.update_bar_bearing_regions('B1', (replace(region, position_m=4.),))
    with pytest.raises(ValueError):
        replace(region, force_per_web_kn=float('nan'))
    model.update_bar_bearing_regions('B1', (region,))
    serializer = ProjectSerializer()
    restored = StructuralModel()
    serializer.load_into(restored, serializer.dump(model))
    assert restored.bars['B1'].bearing_regions == (region,)
    assert bearing_checks(verification_elements(restored)[0], restored, 250.)['bearing_B1_A']['status'] == 'checked'


@pytest.mark.parametrize('mirror', [False, True])
def test_hat_section_web_shares_are_integrated_and_match_independent_sharp_wall_solution(mirror):
    from osa.verification.cold_formed_local import web_shear_shares

    geometry = {'d': 100., 'bf': 50., 'c': 15., 't': 2.}
    shares = web_shear_shares('Cartola Formado', tuple(sorted(geometry.items())), mirror)
    assert len(shares) == 2
    assert [item.flat_height_mm for item in shares] == pytest.approx((92., 92.))
    assert [item.vertical_per_shear_z for item in shares] == pytest.approx((.5, .5), abs=1e-12)
    # Exact contour integrals of first moment, separately derived for a
    # sharp hat: b=bf-t, h=d-t, c_outstand=c+t/2. Thickness cancels in Vy.
    b, h, c = 48., 98., 16.
    iz_over_t = 2/3*((b/2+c)**3-(b/2)**3)+h*b*b/2+b**3/12
    coefficient = (h*(b*c+c*c)/2+b*h*h/4)/iz_over_t
    expected = (coefficient, -coefficient) if mirror else (-coefficient, coefficient)
    assert [item.vertical_per_shear_y for item in shares] == pytest.approx(expected, abs=1e-12)
