"""Rounded RHS/SHS checks and limits from NBR 8800:2024."""

from math import pi, sqrt

import pytest
from scipy.integrate import quad

from osa.domain import AnalysisResult
from osa.model import StructuralModel
from osa.ui.verification_worker import verify_model
from osa.verification.rectangular_tube import effective_width, section


def rhs(geometry=None, sample=None, family="Tubular Retangular"):
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 3)
    for node in ("A", "B"):
        model.update_node_supports(node, (True,) * 6)
    model.add_bar("R1", "A", "B")
    model.update_bar_section("R1", family)
    model.update_bar_material("R1", "ASTM A36", model.materials["ASTM A36"])
    model.update_member_profile("R1", "RHS de teste", geometry or {"b": 100., "h": 200., "t": 5.})
    for key in ("Ly", "Lz", "Lb"):
        model.update_bar_calculation_property("R1", key, 3.)
    sample = {"x": 1., "axial": 10., "moment_y": 1., "moment_z": 0., "shear_y": 0., "shear_z": 1., "torque": 0., **(sample or {})}
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"R1": {"samples": [sample]}})]
    return model


def result(model):
    return verify_model(model)["results"]["bar:R1"]["checks"]


def rounded_plastic_integral(b, h, r):
    # Numerical integration of horizontal strips, independent of the closed
    # expression used by the implementation.
    def width(z):
        if z <= h/2-r:
            return b
        return b-2*r+2*sqrt(max(0., r*r-(z-(h/2-r))**2))
    return 2*quad(lambda z: z*width(z), 0, h/2, points=[h/2-r], epsabs=1e-8)[0]


def test_plastic_moduli_match_independent_integration_of_rounded_walls():
    model = rhs()
    p = section(model.bars["R1"])
    expected_y = rounded_plastic_integral(100, 200, 10)-rounded_plastic_integral(90, 190, 5)
    expected_z = rounded_plastic_integral(200, 100, 10)-rounded_plastic_integral(190, 90, 5)
    assert p["Zy_cm3"] == pytest.approx(expected_y/1000, rel=1e-9)
    assert p["Zz_cm3"] == pytest.approx(expected_z/1000, rel=1e-9)


def test_compact_rhs_compression_and_shear_match_direct_values():
    model = rhs()
    out = result(model)
    p = section(model.bars["R1"])
    ne = pi*pi*20000*p["Iz_cm4"]/300**2
    lam = sqrt(p["Ag_cm2"]*25/ne)
    chi = .658**lam**2 if lam <= 1.5 else .877/lam**2
    assert out["axial_compression"]["capacity"] == pytest.approx(chi*p["Ag_cm2"]*25/1.1)
    # The vertical shear uses two flat webs, each (200-4*5) × 5 mm.
    assert out["shear_z"]["capacity"] == pytest.approx(.6 * (2*18*.5) * 25/1.1)
    assert verify_model(model)["summary"]["approved"] == 1


def test_square_and_rectangular_definitions_give_the_same_resistances():
    square = rhs({"b": 100., "t": 4.}, family="Tubular Quadrado")
    rectangular = rhs({"b": 100., "h": 100., "t": 4.})
    for key in ("axial_compression", "flexion_y", "shear_z"):
        assert result(square)[key]["capacity"] == pytest.approx(result(rectangular)[key]["capacity"])


def test_effective_width_switch_and_reduction_use_the_correct_table_coefficients():
    limit = 1.4*sqrt(20000/25)
    assert effective_width(limit*.2, .2, 20000, 25, 1.) == pytest.approx(limit*.2)
    b, t, chi = 20., .2, .8
    elastic = (1.38*limit/(b/t))**2*25
    q = sqrt(elastic/(chi*25))
    assert effective_width(b, t, 20000, 25, chi) == pytest.approx(b*(1-.2*q)*q)


def test_slender_flange_and_noncompact_web_do_not_reuse_compact_capacity():
    model = rhs({"b": 180., "h": 500., "t": 3.})
    out = result(model)
    assert out["flexion_y"]["status"] == "not_checked"  # web exceeds Annex D
    assert verify_model(model)["summary"]["approved"] == 0
    model = rhs({"b": 180., "h": 200., "t": 3.})
    out = result(model)
    p = section(model.bars["R1"])
    assert out["flexion_y"]["status"] == "checked"
    assert out["flexion_y"]["capacity"] < p["Zy_cm3"]*25/1.1


def test_unsupported_torsion_wall_limit_and_missing_connection_data_are_pending():
    model = rhs({"b": 1000., "h": 1200., "t": 4.}, {"torque": 1.})
    torsion = result(model)["torsion"]
    assert torsion["status"] == "not_checked"
    assert not any(s["symbol"] in ("T_n", "T_{Rd}") for s in torsion["steps"])
    assert verify_model(model)["summary"]["approved"] == 0
    model = rhs(sample={"axial": -10.})
    assert result(model)["axial_tension"]["status"] == "not_checked"
    model.update_bar_calculation_property("R1", "An", 20.)
    model.update_bar_calculation_property("R1", "Ct", .8)
    assert result(model)["axial_tension"]["capacity"] == pytest.approx(.8*20*40/1.35)
