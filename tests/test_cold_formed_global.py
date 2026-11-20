"""Independent geometry, sectorial and elastic member stability checks."""
from dataclasses import replace
from math import pi, sqrt

import numpy as np
import pytest

from osa.sections.properties import calculate_section_properties
from osa.sections.thin_walled import open_sheet, sectorial_properties
from osa.verification.cold_formed_global import GlobalSection, bending_critical, compression_critical, global_section

FAMILIES = ["U Formado", "C Formado", "Z Formado", "Z45 Formado", "Z90 Formado", "L Formado", "Cartola Formado"]


@pytest.mark.parametrize("family", FAMILIES)
def test_explicit_sheet_has_same_area_and_centroid_as_rounded_outline(family):
    geometry = {"d": 100., "bf": 50., "c": 15., "t": 2., "r": 2.}
    sheet = open_sheet(family, geometry)
    points, weights = sheet.quadrature()
    props = calculate_section_properties(family, geometry)
    assert weights.sum() == pytest.approx(props.area_mm2, rel=4e-5)
    centroid = np.sum(weights[:, None]*points, axis=0)/sum(weights)
    assert centroid == pytest.approx((props.centroid_y_mm, props.centroid_z_mm), abs=.004)
    mesh, plates, junctions = sheet.mesh()
    assert len(mesh) == len(plates)+1
    assert len(junctions) == len(sheet.vertices)-2
    assert mesh[0] == pytest.approx(sheet.vertices[0])
    assert mesh[-1] == pytest.approx(sheet.vertices[-1])
    assert np.all(np.linalg.norm(np.diff(mesh, axis=0), axis=1) > 0)


def test_cbca_example_04_sectorial_properties_and_global_load():
    # CBCA 2014 pp. 51–52, NBR 6355 Ue 100x50x17x1.2.
    # Legacy C's lip input is D-t (its drawn external lip is c+t).
    section = global_section("C Formado", {"d": 100., "bf": 50., "c": 15.8, "t": 1.2})
    assert section.cw/1e6 == pytest.approx(246.61, rel=2e-5)
    assert abs(section.u0)/10 == pytest.approx(4.28, abs=.002)
    assert section.r0/10 == pytest.approx(6.19, abs=.002)
    critical, _ = compression_critical(section, 200_000., 77_000., 4000., 4000., 4000.)
    assert critical/1000 == pytest.approx(9.57, rel=.002)


@pytest.mark.parametrize("family", FAMILIES)
def test_sectorial_coordinates_are_orthogonal_and_reflect_with_section(family):
    geometry = {"d": 100., "bf": 50., "c": 15., "t": 2., "r": 2.}
    first = global_section(family, geometry)
    second = global_section(family, geometry, mirror=True)
    assert second.cw == pytest.approx(first.cw, abs=1e-15, rel=1e-9)
    assert second.r0 == pytest.approx(first.r0)
    for section in (first, second):
        ne, _ = compression_critical(section, 200_000, 77_000, 2000, 3000, 2500)
        assert ne > 0
    sheet = open_sheet(family, geometry)
    sector = sectorial_properties(sheet)
    # Exact integration of the linear sectorial coordinate along each line.
    q, w = sheet.quadrature(sharp=True)
    xi, _ = np.polynomial.legendre.leggauss(8)
    omega = np.concatenate([a+(xi+1)/2*(b-a) for a, b in zip(sector['omega_mm2'], sector['omega_mm2'][1:])])
    assert w@omega == pytest.approx(0, abs=1e-8)
    assert (w*omega)@q == pytest.approx((0., 0.), abs=1e-6)


def test_equal_leg_angle_sharp_sectorial_warping_is_zero():
    section = global_section("L Formado", {"d": 60., "bf": 60., "t": 2.})
    assert section.cw == pytest.approx(0, abs=1e-15)


def test_compression_eigenproblem_matches_general_normative_cubic():
    section = GlobalSection(1000., 8e6, 2e6, 2000., 3e9, 10., 20., 105., 0., 0., 0.)
    E, G = 200_000., 77_000.
    ne, components = compression_critical(section, E, G, 3000., 4000., 5000.)
    n1, n2, nt = (components[key] for key in ("Ne1_N", "Ne2_N", "Net_N"))
    # 9.7.2.3 polynomial, independently assembled with numpy.poly1d.
    x = np.poly1d((1., 0.))
    polynomial = section.r0**2*(x-n1)*(x-n2)*(x-nt) - x*x*(x-n2)*section.u0**2 - x*x*(x-n1)*section.v0**2
    expected = min(root.real for root in polynomial.r if abs(root.imag) < 1e-5 and root.real > 0)
    assert ne == pytest.approx(expected, rel=1e-10)


def test_symmetric_uniform_bending_matches_9_8_2_2():
    section = GlobalSection(1000., 8e6, 2e6, 2000., 3e9, 0., 0., 100., 0., 0., 0.)
    E, G, length = 200_000., 77_000., 3000.
    expected = sqrt(pi*pi*E*section.i2/length**2*(pi*pi*E*section.cw/length**2+G*section.j))
    assert bending_critical(section, E, G, length, length)[0] == pytest.approx(expected)


def test_monosymmetric_bending_matches_both_signs_of_annex_e():
    section = GlobalSection(1000., 8e6, 2e6, 2000., 3e9, -20., 0., 100., 0., 0., -80.)
    E, G, length = 200_000., 77_000., 3000.
    nex = pi*pi*E*section.i1/length**2
    torsional = pi*pi*E*section.cw/length**2+G*section.j
    # For unit Mz, polar initial-stress coefficient=-2j, so j=40 mm.
    expected = min(nex*(cs*40+sqrt(40**2+torsional/nex)) for cs in (-1, 1))
    assert bending_critical(section, E, G, length, length, moment_y=0., moment_z=1.)[0] == pytest.approx(expected)
    reflected = replace(section, wagner_z=-section.wagner_z)
    assert bending_critical(reflected, E, G, length, length, moment_y=0., moment_z=1.)[0] == pytest.approx(expected)


@pytest.mark.parametrize("value", [0., -1., float('nan'), float('inf')])
def test_global_stability_rejects_invalid_lengths(value):
    section = global_section("U Formado", {"d": 100., "bf": 50., "t": 2.})
    with pytest.raises(ValueError):
        compression_critical(section, 200_000., 77_000., value, 3000., 3000.)
