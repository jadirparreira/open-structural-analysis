"""Continuous rounded-wall sectorial geometry against independent integrals."""
import numpy as np
import pytest
from scipy.integrate import quad

from osa.sections.thin_walled import OpenSheet, WallPiece, open_sheet, rounded_sectorial_field, sectorial_properties

FAMILIES = ('U Formado', 'C Formado', 'Z Formado', 'Z45 Formado', 'Z90 Formado', 'L Formado', 'Cartola Formado')
GEOMETRY = {'d': 100., 'bf': 50., 'c': 15., 't': 2., 'r': 2.}


@pytest.mark.parametrize('family', FAMILIES)
@pytest.mark.parametrize('mirror', (False, True))
def test_rounded_field_preserves_continuity_orthogonality_and_sectorial_inertia(family, mirror):
    sheet = open_sheet(family, GEOMETRY, mirror=mirror)
    field = rounded_sectorial_field(sheet)
    basis, weights = field.quadrature()
    gram = basis.T@(weights[:, None]*basis)
    assert gram[3, 3] == pytest.approx(field.cw_mm6, rel=1e-12)
    scaling = np.sqrt(np.diag(gram))
    assert abs(gram[0, 1:3]/scaling[0]/scaling[1:3]).max() < 1e-12
    assert abs(gram[:3, 3]/scaling[:3]/scaling[3]).max() < 1e-11
    for index in range(len(sheet.pieces)-1):
        assert field.omega(index, 1.) == pytest.approx(field.omega(index+1, 0.), abs=1e-10)
    # Independently integrate the sectorial derivative along every piece.
    for index, piece in enumerate(sheet.pieces):
        def density(fraction, piece=piece):
            point, tangent = piece.point(fraction), piece.tangent(fraction)
            cy, cz = field.shear_center_mm
            return ((point[0]-cy)*tangent[1]-(point[1]-cz)*tangent[0])*piece.length
        integral = quad(density, 0., 1., epsabs=1e-9)[0]
        assert field.omega(index, 1.)-field.omega(index, 0.) == pytest.approx(integral, abs=1e-9)


@pytest.mark.parametrize('family', FAMILIES)
def test_rounded_field_is_invariant_under_translation_and_consistent_under_reflection(family):
    sheet = open_sheet(family, GEOMETRY)
    reference = rounded_sectorial_field(sheet)
    shift = np.array((2345., -6789.))
    pieces = tuple(WallPiece(tuple(np.asarray(p.start)+shift), tuple(np.asarray(p.end)+shift), p.role, p.plate,
        None if p.center is None else tuple(np.asarray(p.center)+shift), p.turn) for p in sheet.pieces)
    translated = rounded_sectorial_field(OpenSheet(tuple(tuple(np.asarray(p)+shift) for p in sheet.vertices), pieces,
                                                 sheet.thickness, sheet.radius, sheet.roles))
    mirrored = rounded_sectorial_field(open_sheet(family, GEOMETRY, mirror=True))
    assert translated.cw_mm6 == pytest.approx(reference.cw_mm6, rel=2e-9)
    assert np.asarray(translated.shear_center_mm)-shift == pytest.approx(reference.shear_center_mm, abs=2e-8)
    assert mirrored.cw_mm6 == pytest.approx(reference.cw_mm6, rel=1e-12)
    assert mirrored.shear_center_mm == pytest.approx((-reference.shear_center_mm[0], reference.shear_center_mm[1]), abs=1e-10)
    for index in range(len(sheet.pieces)):
        for fraction in (0., .3, 1.):
            assert translated.omega(index, fraction) == pytest.approx(reference.omega(index, fraction), abs=2e-7)
            assert mirrored.omega(index, fraction) == pytest.approx(-reference.omega(index, fraction), abs=1e-10)


@pytest.mark.parametrize('family', FAMILIES)
def test_straight_piece_field_recovers_the_existing_sharp_fold_properties(family):
    actual = open_sheet(family, GEOMETRY)
    pieces = tuple(WallPiece(a, b, role, i) for i, (a, b, role) in enumerate(zip(actual.vertices, actual.vertices[1:], actual.roles, strict=False)))
    sheet = OpenSheet(actual.vertices, pieces, actual.thickness, 0., actual.roles)
    field, reference = rounded_sectorial_field(sheet), sectorial_properties(actual)
    assert field.cw_mm6 == pytest.approx(reference['Cw_mm6'], rel=1e-11, abs=1e-16)
    assert field.shear_center_mm == pytest.approx((reference['shear_center_y_mm'], reference['shear_center_z_mm']), abs=1e-10)
