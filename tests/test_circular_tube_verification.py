"""Circular tube checks, with independent kN/cm reference calculations."""

from math import pi, sqrt
from zipfile import ZipFile

import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import calculation_memory
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.memorial_docx_export import export_calculation_memorial_docx
from osa.ui.verification_worker import verify_model


def tube(samples=None, diameter=100., thickness=3.):
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 3)
    for node in ("A", "B"):
        model.update_node_supports(node, (True,) * 6)
    model.add_bar("T1", "A", "B")
    model.update_bar_section("T1", "Tubular Circular")
    model.update_bar_material("T1", "ASTM A36", model.materials["ASTM A36"])
    model.update_member_profile("T1", "Tubo de teste", {"D": diameter, "t": thickness})
    for key, value in (("Ly", 3.), ("Lz", 3.)):
        model.update_bar_calculation_property("T1", key, value)
    rows = samples if samples is not None else [{"axial": 10., "moment_y": 1., "shear_z": 1.}]
    complete = [{"x": 1., "axial": 0., "moment_y": 0., "moment_z": 0.,
                 "shear_y": 0., "shear_z": 0., "torque": 0., **row} for row in rows]
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"T1": {"samples": complete}})]
    return model


def checks(model):
    return verify_model(model)["results"]["bar:T1"]["checks"]


def test_compression_uses_gross_area_in_lambda_and_correct_circular_effective_area():
    model = tube(diameter=300., thickness=1.)
    out = checks(model)["axial_compression"]
    # NBR 8800:2024, 5.3.3.2 uses Ag, not Aef, in lambda0.
    ag = pi * (30.**2 - 29.8**2) / 4
    inertia = pi * (30.**4 - 29.8**4) / 64
    ne = pi**2 * 20000 * inertia / 300**2
    lam = sqrt(ag * 25 / ne)
    chi = .658**lam**2 if lam <= 1.5 else .877/lam**2
    aef = ag * (.038 * 20000 / (300 * 25) + 2/3)
    assert out["status"] == "checked"
    assert out["parameters"]["lambda0"] == pytest.approx(lam)
    assert out["capacity"] == pytest.approx(chi*aef*25/1.1)


def test_tension_requires_explicit_net_area_and_ct_and_round_trips_inputs():
    model = tube([{"axial": -10.}])
    assert checks(model)["axial_tension"]["status"] == "not_checked"
    model.update_bar_calculation_property("T1", "An", 8.)
    model.update_bar_calculation_property("T1", "Ct", .8)
    out = checks(model)["axial_tension"]
    assert out["capacity"] == pytest.approx(.8*8*40/1.35)
    restored = StructuralModel()
    serializer = ProjectSerializer()
    serializer.load_into(restored, serializer.dump(model))
    assert dict(restored.bars["T1"].calculation_property_overrides)["An"] == 8.


@pytest.mark.parametrize(("diameter", "thickness", "regime"), [(100., 3., "plastic"), (200., 1., "inelastic"), (300., 1., "elastic")])
def test_flexion_covers_each_branch_of_d26(diameter, thickness, regime):
    model = tube([{"moment_y": 1.}], diameter, thickness)
    out = checks(model)["flexion_y"]
    d, inner = diameter/10, (diameter-2*thickness)/10
    w = pi*(d**4-inner**4)/64/(d/2)
    z = (d**3-inner**3)/6
    ratio = diameter/thickness
    mn = z*25 if regime == "plastic" else (.021*20000/ratio+25)*w if regime == "inelastic" else .33*20000*w/ratio
    assert out["capacity"] == pytest.approx(min(mn, 1.5*w*25)/1.1)


def test_shear_needs_lv_only_when_the_second_branch_does_not_reach_yield():
    model = tube([{"shear_z": 1.}], 300., 1.)
    assert checks(model)["shear_z"]["status"] == "not_checked"
    model.update_bar_calculation_property("T1", "LvZ", 1.5)
    out = checks(model)["shear_z"]
    ag = pi*(30**2-29.8**2)/4
    tau = min(15., max(1.6*20000/(sqrt(1500/300)*300**1.25), .78*20000/300**1.5))
    assert out["capacity"] == pytest.approx(.5*tau*ag/1.1)


def test_interaction_preserves_concurrency_and_critical_position():
    model = tube([{"x": .5, "axial": 100., "moment_y": .01},
                  {"x": 2., "axial": 1., "moment_y": 2.}])
    out = checks(model)
    nc = out["axial_compression"]["capacity"]
    mr = out["flexion_y"]["capacity"]
    ratios = []
    for n, m in ((100., 1.), (1., 200.)):
        ratios.append(n/nc+8/9*m/mr if n/nc >= .2 else n/(2*nc)+m/mr)
    combined = out["flexocompressao"]
    assert combined["utilization"] == pytest.approx(max(ratios))
    assert combined["critical_position_m"] == (.5 if ratios[0] >= ratios[1] else 2.)


def test_pure_torsion_is_checked_and_high_torsion_uniaxial_interaction_is_concurrent():
    model = tube([{"torque": .1}])
    assert verify_model(model)["summary"]["unverified"] == 0
    assert checks(model)["torsion"]["status"] == "checked"
    tr = checks(model)["torsion"]["capacity"]
    model.analysis_results[0].member_results["T1"]["samples"][0].update(torque=.4*tr/100, axial=10., moment_y=1., shear_z=1.)
    out = checks(model)
    expected = 10/out["axial_compression"]["capacity"] + 100/out["flexion_y"]["capacity"]
    expected += (1/out["shear_z"]["capacity"]+.4)**2
    assert out["torsion_interaction"]["utilization"] == pytest.approx(expected)
    assert out["flexocompressao"]["status"] == "not_applicable"
    assert verify_model(model)["summary"]["unverified"] == 0


def test_out_of_range_wall_and_missing_results_cannot_be_approved():
    model = tube([{"axial": 10., "moment_y": 1.}], 400., 1.)
    assert checks(model)["axial_compression"]["status"] == "not_checked"
    assert checks(model)["flexion_y"]["status"] == "not_checked"
    assert verify_model(model)["summary"]["approved"] == 0
    model = tube()
    del model.analysis_results[0].member_results["T1"]["samples"][0]["moment_z"]
    assert verify_model(model)["summary"]["approved"] == 0
    assert all(item["status"] == "not_checked" for item in checks(model).values())


def test_memorial_preserves_traceable_equations_and_editable_docx(tmp_path):
    model = tube([{"x": 1.75, "axial": 10., "moment_y": 1., "shear_z": 1., "torque": .1}])
    model.verification_results = verify_model(model)["results"]
    equations = {}
    html = CalculationMemorialDialog._render(calculation_memory(model, ("T1",)), {}, equation_latex=equations)
    assert "Tubular Circular" in html
    assert "D.2.6" in html and "5.3.3.2" in html
    assert "x = 1,75 m" in html
    assert "estimativas" in html
    assert any("A_g f_y/N_e" in latex for latex in equations.values())
    destination = export_calculation_memorial_docx(html, equations, tmp_path / "tubular.docx")
    with ZipFile(destination) as archive:
        assert "<m:oMath" in archive.read("word/document.xml").decode()
