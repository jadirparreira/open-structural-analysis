"""Effective-width tables, resolved geometry and service iteration."""
from math import sqrt

import numpy as np
import pytest

from osa.sections.thin_walled import open_sheet
from osa.verification.cold_formed_effective import (
    effective_plate,
    effective_section,
    stiffened_flange,
    width_reduction,
)


def test_aa_uniform_compression_reduces_at_both_supported_edges():
    width, thickness, E, sigma = 200., 1., 200_000., 250.
    slenderness = width/thickness/(.95*sqrt(4*E/sigma))
    effective = width*(1-.22/slenderness)/slenderness
    result = effective_plate(width, thickness, E, sigma, sigma)
    assert result.coefficient == 4.
    assert np.asarray(result.intervals) == pytest.approx(np.array(((0., effective/2), (width-effective/2, width))))


def test_al_uniform_compression_retains_connected_edge():
    result = effective_plate(60., 1., 200_000., 250., 250., supported_both=False)
    slenderness = 60/(.95*sqrt(.43*200_000/250))
    assert np.asarray(result.intervals) == pytest.approx(np.array(((0., 60*width_reduction(slenderness)),)))
    mirrored = effective_plate(60., 1., 200_000., 250., 250., supported_both=False, free_start=True)
    assert mirrored.intervals[0][1] == 60.
    assert mirrored.effective_width == pytest.approx(result.effective_width)


@pytest.mark.parametrize('supported_both', [False, True])
def test_tensile_part_is_kept_in_full_when_plate_buckles(supported_both):
    result = effective_plate(200., .5, 200_000., 200., -200., supported_both=supported_both)
    assert result.effective_width >= 100.
    assert any(a <= 100 and b == 200 for a, b in result.intervals)


@pytest.mark.parametrize(('root', 'tip', 'expected'), [(200., 100., .578/.84), (200., -100., 1.7+2.5+17.1*.25),
                                                     (100., 200., .57-.21*.5+.07*.25)])
def test_al_gradient_coefficients_match_table_6(root, tip, expected):
    result = effective_plate(60., 1., 200_000., root, tip, supported_both=False)
    assert result.coefficient == pytest.approx(expected)


def test_al_gradient_outside_table_uses_explicit_conservative_uniform_bound():
    result = effective_plate(200., 1., 200_000., 100., -300., supported_both=False)
    assert result.coefficient == .43
    assert 'conservador' in result.reference
    assert result.effective_width >= 150.


def test_edge_stiffener_reference_inertia_and_reduced_lip():
    (_, _), lip, values = stiffened_flange(100., 10., 12., 1., np.pi/2, 200_000., 250., 8.)
    lp0 = 100/(.623*sqrt(200_000/250))
    expected = min(399*(.487*lp0-.328)**3, 56*lp0+5)
    assert values['Ia_mm4'] == pytest.approx(expected)
    assert values['Is_mm4'] == pytest.approx(10**3/12)
    assert lip <= 8.


def test_cbca_compression_example_04_has_fully_effective_section_at_global_stress():
    sheet = open_sheet('C Formado', {'d': 100., 'bf': 50., 'c': 15.8, 't': 1.2})
    result = effective_section(sheet, 200_000., [0., 0., 0.], uniform_stress=31., nominal_lip=17.)
    assert result.area_mm2/100 == pytest.approx(2.71, abs=.005)
    assert all(interval == ((0., 1.),) for interval in result.intervals.values())


def test_cbca_flexure_example_07_reproduces_first_yield_effective_section():
    sheet = open_sheet('C Formado', {'d': 100., 'bf': 50., 'c': 15.8, 't': 1.2})
    result = effective_section(sheet, 200_000., [0., 1., 0.], yield_stress=250., nominal_lip=17., bending_plane='y')
    # Manual p.71 gives M0,Rd=195.45 kN cm. The exact curved geometry and
    # face stresses used here conservatively differ from the tabulated
    # thin-line/rounded hand iteration by about one percent.
    assert result.load_factor/1.1/10000 == pytest.approx(195.45, rel=.015)
    assert result.centroid_mm[1] < 0


def test_service_effective_stiffness_decreases_with_load_and_preserves_compact_case():
    sheet = open_sheet('C Formado', {'d': 200., 'bf': 80., 'c': 20., 't': 1.})
    gross = effective_section(sheet, 200_000., [0., 0., 0.], nominal_lip=21.)
    low = effective_section(sheet, 200_000., [0., 1000., 0.], nominal_lip=21.)
    high = effective_section(sheet, 200_000., [0., 2e6, 0.], nominal_lip=21.)
    assert low.iy_mm4 == pytest.approx(gross.iy_mm4)
    assert high.iy_mm4 < low.iy_mm4
    assert high.area_mm2 < gross.area_mm2


def test_effective_section_reflection_preserves_physical_load_case():
    geometry = {'d': 100., 'bf': 50., 'c': 15., 't': 1.}
    first = effective_section(open_sheet('C Formado', geometry), 200_000., [500., 1e6, 2e5], nominal_lip=16.)
    second = effective_section(open_sheet('C Formado', geometry, mirror=True), 200_000., [500., 1e6, -2e5], nominal_lip=16.)
    assert second.area_mm2 == pytest.approx(first.area_mm2)
    assert second.iy_mm4 == pytest.approx(first.iy_mm4)
    assert second.iz_mm4 == pytest.approx(first.iz_mm4)
    assert second.iyz_mm4 == pytest.approx(-first.iyz_mm4)


def test_unconverged_section_never_returns_a_resistance():
    sheet = open_sheet('C Formado', {'d': 200., 'bf': 80., 'c': 20., 't': 1.})
    with pytest.raises(ValueError, match='não convergiu'):
        effective_section(sheet, 200_000., [0., 2e6, 0.], nominal_lip=21., maximum_iterations=1)
