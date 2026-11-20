"""Regression checks for automatic elastic local/distortional buckling."""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
from scipy.linalg import eigh

from osa.verification.cold_formed_fsm import FiniteStripSection, _classify, critical_minimum, critical_signature

GEOMETRIES = {
    "U Formado": {"d": 100., "bf": 50., "t": 2., "r": 2.},
    "C Formado": {"d": 100., "bf": 50., "t": 2., "c": 15., "r": 2.},
    "Z Formado": {"d": 100., "bf": 50., "t": 2., "c": 15., "r": 2.},
    "Z45 Formado": {"d": 100., "bf": 50., "t": 2., "c": 15., "r": 2.},
    "Z90 Formado": {"d": 100., "bf": 50., "t": 2., "c": 15., "r": 2.},
    "L Formado": {"d": 100., "bf": 50., "t": 2., "r": 2.},
    "Cartola Formado": {"d": 100., "bf": 50., "t": 2., "c": 15., "r": 2.},
}


@pytest.mark.parametrize(("family", "geometry"), GEOMETRIES.items())
def test_finite_strip_solver_finds_local_modes_and_stiffened_distortional_modes(family, geometry):
    lengths, branches = critical_signature(family, geometry, E=200_000.)
    assert len(lengths) >= 12
    modes = ("local", "distorcional") if family in {"C Formado", "Z45 Formado", "Z90 Formado", "Cartola Formado"} else ("local",)
    for mode in modes:
        values = [item for item in branches[mode] if item is not None]
        assert values
        assert min(item.value for item in values) > 0
        assert min(item.half_wave_mm for item in values) > 0


def test_flexural_eigenproblem_includes_both_moment_signs():
    section = FiniteStripSection("C Formado", GEOMETRIES["C Formado"])
    modes = section.modes(100., "My")
    assert {item.sign for item in modes} == {-1, 1}


def _integrated_resultants(section, stress):
    # Independent four-point quadrature of N, My and Mz on each strip.
    xi, weights = np.polynomial.legendre.leggauss(4)
    result = np.zeros(3)
    for i, (a, b) in enumerate(zip(section.points, section.points[1:])):
        for point, weight in zip((xi+1)/2, weights/2):
            y, z = a + point*(b-a)
            sigma = stress[i] + point*(stress[i+1]-stress[i])
            result += weight*np.linalg.norm(b-a)*section.thickness*sigma*np.array((1., z, -y))
    return result


@pytest.mark.parametrize(("family", "geometry"), GEOMETRIES.items())
@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize(("load", "expected"), [
    ("N", (1., 0., 0.)), ("My", (0., 1., 0.)), ("Mz", (0., 0., 1.)),
    ("My-", (0., -1., 0.)), ("Mz-", (0., 0., -1.)),
])
def test_reference_stresses_recover_requested_resultants(family, geometry, mirror, load, expected):
    section = FiniteStripSection(family, geometry, mirror=mirror)
    stress = section._stresses(load)
    assert _integrated_resultants(section, stress) == pytest.approx(expected, abs=2e-12)
    if load == "N":
        assert np.ptp(stress) < 1e-14


@pytest.mark.parametrize("family", ["C Formado", "Z90 Formado", "L Formado"])
@pytest.mark.parametrize("load", ["N", "My", "Mz"])
def test_reflection_preserves_elastic_critical_spectrum(family, load):
    original = FiniteStripSection(family, GEOMETRIES[family])
    mirrored = FiniteStripSection(family, GEOMETRIES[family], mirror=True)
    a = sorted(item.value for item in original.modes(100., load))
    b = sorted(item.value for item in mirrored.modes(100., load))
    assert b == pytest.approx(a, rel=1e-6)


def test_uniform_load_rejects_unknown_reference_instead_of_treating_it_as_mz():
    section = FiniteStripSection("C Formado", GEOMETRIES["C Formado"])
    with pytest.raises(ValueError, match="Carregamento"):
        section._stresses("Mx")


@pytest.mark.parametrize("half_wave", [50., 100., 200.])
def test_strip_bending_converges_to_simply_supported_plate_buckling(half_wave):
    # Independent classical plate solution: all edges simply supported,
    # uniform compression, one longitudinal sinusoidal half-wave.
    width, thickness, E, nu = 100., 1., 200_000., .3
    exact = np.pi**2*E/(12*(1-nu**2))*(thickness/width)**2 * (
        width/half_wave + half_wave/width)**2 * width*thickness
    errors = []
    for count in (8, 16, 32):
        plate = object.__new__(FiniteStripSection)
        plate.points = np.column_stack((np.linspace(-width/2, width/2, count+1), np.zeros(count+1)))
        plate.thickness, plate.E, plate.nu = thickness, E, nu
        plate.size = 4*(count+1)
        K, G = plate._matrices(half_wave, np.full(count+1, 1/(width*thickness)))
        # Keep plate-normal translations and rotations; zero translations
        # at transverse ends enforce the two other simply supported edges.
        ids = [4*i+j for i in range(count+1) for j in (2, 3) if j == 3 or 0 < i < count]
        critical = eigh(K[np.ix_(ids, ids)], G[np.ix_(ids, ids)]*(np.pi/half_wave)**2,
                        subset_by_index=(0, 0))[0][0]
        errors.append(abs(critical/exact-1))
    assert errors[-1] < errors[0]
    assert errors[-1] < 1e-5


_REFERENCE = json.loads((Path(__file__).parent/'data'/'cold_formed_elastic_reference.json').read_text())


@lru_cache(maxsize=16)
def _reference_section(family, geometry):
    return FiniteStripSection(family, dict(geometry))


@pytest.mark.parametrize("case", _REFERENCE['cases'], ids=lambda c: f"{c['family']}-{c['load']}-{c['half_wave_mm']}")
def test_first_three_positive_eigenvalues_match_independent_finite_strip_solver(case):
    section = _reference_section(case['family'], tuple(sorted(case['geometry'].items())))
    values = sorted(item.value for item in section.modes(case['half_wave_mm'], case['load']) if item.sign > 0)
    assert values[:3] == pytest.approx(case['critical_values'], rel=2e-6)


def test_global_twist_about_an_angle_fold_is_not_misclassified_as_local():
    section = FiniteStripSection('L Formado', GEOMETRIES['L Formado'])
    fold = section.points[section.fold_nodes[len(section.fold_nodes)//2]]
    vector = np.zeros((section.n, 4))
    vector[:, 1] = -(section.points[:, 1]-fold[1])
    vector[:, 2] = section.points[:, 0]-fold[0]
    vector[:, 3] = 1.
    assert _classify(section.points, vector.reshape(-1)) == 'global'


@pytest.mark.parametrize('mode', ['local', 'distorcional'])
def test_signature_minimum_is_refined_below_sampled_minimum(mode):
    geometry = GEOMETRIES['C Formado']
    result = critical_minimum('C Formado', geometry, mode=mode)
    assert result is not None
    _, branches = critical_signature('C Formado', geometry)
    assert result.value <= min(item.value for item in branches[mode] if item is not None)
    section = FiniteStripSection('C Formado', geometry)
    for factor in (.98, 1.02):
        surrounding = [item.value for item in section.modes(result.half_wave_mm*factor, 'N') if item.mode == mode]
        assert min(surrounding) >= result.value*(1-1e-5)



def test_rigid_fold_motion_cannot_hide_local_panel_deformation():
    from osa.verification.cold_formed_fsm import assess_mode

    points = np.array(((50., -50.), (0., -50.), (0., 0.), (0., 50.), (50., 50.)))
    vector = np.zeros((len(points), 4))
    vector[:, 1] = 1.  # Rigid translation including both folds.
    vector[2, 1] += 2.  # Web bends while the folds retain rigid motion.
    assessed = assess_mode(points, vector.ravel(), folds=(1, 3))
    assert assessed.rigid_residual > .12
    assert assessed.fold_nonrigid_residual < 1e-12
    assert assessed.mode == 'misto'
    vector[:, 1] -= 1.
    assert assess_mode(points, vector.ravel(), folds=(1, 3)).mode == 'local'


@pytest.mark.parametrize('scale', [1e-200, -1e-100, 1., -1e100, 1e200])
def test_mode_screening_does_not_depend_on_eigenvector_scale_or_axial_amplitude(scale):
    from osa.verification.cold_formed_fsm import assess_mode

    points = np.array(((50., -50.), (0., -50.), (0., 0.), (0., 50.), (50., 50.)))
    vector = np.zeros((len(points), 4))
    vector[2, 1] = 1.
    assert assess_mode(points, (scale*vector).ravel(), folds=(1, 3)).mode == 'local'
    vector[:, 0] = 1e6  # Longitudinal motion is not cross-section rigidity.
    assert assess_mode(points, (scale*vector).ravel(), folds=(1, 3)).mode == 'local'


def test_continuous_rigid_fit_is_independent_of_straight_panel_subdivision():
    from osa.verification.cold_formed_fsm import assess_mode

    # A web cubic bubble plus rigid translation, exactly represented by
    # cubic Hermite fields on either mesh. Corner displacements stay rigid.
    assessments = []
    for count in (2, 8, 32):
        eta = np.linspace(0., 1., count+1)
        web = np.column_stack((np.zeros(count+1), -50+100*eta))
        points = np.vstack(((50., -50.), web, (50., 50.)))
        vector = np.zeros((len(points), 4))
        vector[:, 1] = 1.
        vector[1:-1, 1] += 8*eta*(1-eta)
        # Plate normal is -Y on the upward web, theta=dw/ds.
        vector[1:-1, 3] = -8*(1-2*eta)/100
        assessed = assess_mode(points, vector.ravel(), folds=(1, count+1))
        assessments.append(assessed)
    assert {a.mode for a in assessments} == {'misto'}
    assert [a.rigid_residual for a in assessments] == pytest.approx([assessments[0].rigid_residual]*3, abs=1e-12)
    assert [a.fold_ratio for a in assessments] == pytest.approx([assessments[0].fold_ratio]*3, abs=1e-12)


def test_transverse_rigid_fit_matches_exact_continuous_quadratic_field():
    from osa.verification.cold_formed_fsm import assess_mode

    points = np.array(((0., -50.), (0., 50.)))
    # Y(eta)=1+8 eta(1-eta), Z=0, normal=-Y.
    vector = np.array(((0., 1., 0., -.08), (0., 1., 0., .08)))
    assessed = assess_mode(points, vector.ravel(), folds=(0, 1))
    # Best rigid translation=7/3. Residual integral=16/45 and total
    # integral=261/45 on eta in [0,1]; the best rigid rotation is zero.
    assert assessed.rigid_residual == pytest.approx(np.sqrt(16/261), abs=1e-13)
    assert assessed.mode == 'misto'


def test_lower_mixed_mode_cannot_be_silently_skipped_for_a_larger_local_critical(monkeypatch):
    import osa.verification.cold_formed_fsm as fsm

    # Use a real profile signature and add the diagnostic witness as if
    # supplied by an independently resolved mixed branch. The pure branch
    # and the refined eigenproblem remain unchanged.
    geometry = GEOMETRIES['C Formado']
    lengths, branches = critical_signature('C Formado', geometry)
    original = fsm._cached_signature
    modified = {name: list(values) for name, values in branches.items()}
    modified['misto'][len(lengths)//2] = fsm.ElasticCritical(1., lengths[len(lengths)//2], 'misto', 1)
    monkeypatch.setattr(fsm, '_cached_signature', lambda *args: (lengths, modified))
    fsm._cached_minimum.cache_clear()
    try:
        with pytest.raises(ValueError, match='Modo misto.*abaixo.*local'):
            critical_minimum('C Formado', geometry, mode='local')
    finally:
        monkeypatch.setattr(fsm, '_cached_signature', original)
        fsm._cached_minimum.cache_clear()
