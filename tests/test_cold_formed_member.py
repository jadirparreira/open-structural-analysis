"""Independent branch, integration and axis checks of NBR 14762 MRD."""
from math import sqrt
from zipfile import ZipFile

import pytest

from osa.domain import AnalysisResult
from osa.memorial_data import calculation_memory
from osa.model import StructuralModel
from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog
from osa.ui.memorial_docx_export import export_calculation_memorial_docx
from osa.ui.verification_worker import verify_model
from osa.verification.cold_formed import direct_resistance
from osa.verification.cold_formed_member import FAMILIES, section


def formed(family="C Formado", rows=None, overrides=None, combinations=None):
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 3)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", family)
    model.update_bar_material("B1", "ASTM A36", model.materials["ASTM A36"])
    geometry = {"d": 100., "bf": 50., "t": 2.}
    if family in {"C Formado", "Cartola Formado", "Z45 Formado", "Z90 Formado"}:
        geometry["c"] = 15.
    if family in {"Z45 Formado", "Z90 Formado"}:
        geometry["r"] = 2.
    model.update_member_profile("B1", family+" teste", geometry)
    if combinations is not None:
        model.load_combinations = combinations
    # Synthetic resistance cases supply effective lengths independently of
    # the geometric span; K is never silently inferred from the model.
    for key, value in {"KL1": 1., "KL2": 1., **(overrides or {})}.items():
        model.update_bar_calculation_property("B1", key, value)
    complete = [{"x": 1., "axial": 0., "moment_y": 0., "moment_z": 0.,
                 "shear_y": 0., "shear_z": 0., "torque": 0., **row}
                for row in (rows if rows is not None else [{"axial": 10.}])]
    # These isolated section-force fixtures contain no concentrated transverse contact.
    model.update_bar_bearing_regions("B1", ())
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"B1": {"samples": complete}})]
    return model


def output(model):
    return verify_model(model)["results"]["bar:B1"]


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_each_formed_family_integrates_tension_and_does_not_assume_net_area(family):
    model = formed(family, [{"axial": -10.}])
    assert output(model)["status"] == "not_checked"
    assert output(model)["checks"]["axial_tension"]["status"] == "not_checked"
    ag = section(model.bars["B1"])["Ag_cm2"]
    for key, value in {"An": .9*ag, "An0": .8*ag, "Ct": .75}.items():
        model.update_bar_calculation_property("B1", key, value)
    result = output(model)
    tension = result["checks"]["axial_tension"]
    assert tension["capacity"] == pytest.approx(min(ag*25/1.1, .8*ag*40/1.35, .75*.9*ag*40/1.65))
    assert result["status"] == "checked"
    assert result["checks"]["axial_compression"]["status"] == "not_applicable"


def test_mrd_compression_reference_all_modes_and_gamma():
    # Arbitrary independent kN benchmark: Ny=100, Ne=25, Nl=10, Nd=40.
    re = .877/4*100
    ll = sqrt(re/10)
    local = (1-.15/ll**.8)*re/ll**.8
    ld = sqrt(100/40)
    distortional = (1-.25/ld**1.2)*100/ld**1.2
    result = direct_resistance(100, 25, 10, 40)
    assert result.global_characteristic == pytest.approx(re)
    assert result.local_characteristic == pytest.approx(local)
    assert result.distortional_characteristic == pytest.approx(distortional)
    assert result.resistance == pytest.approx(min(re, local, distortional)/1.2)


@pytest.mark.parametrize("l0", [.4, .6, .8, 1.336, 2.])
def test_mrd_flexion_global_branches(l0):
    result = direct_resistance(100, 100/l0**2, 10000, 10000, bending=True)
    expected = 100 if l0 <= .6 else 111*(1-.278*l0*l0) if l0 < 1.336 else 100/l0**2
    assert result.resistance == pytest.approx(expected/1.1)


@pytest.mark.parametrize("bending", [False, True])
def test_mrd_local_and_distortional_branches(bending):
    low = direct_resistance(100, 10000, 10000, 10000, bending=bending)
    assert low.local_characteristic == pytest.approx(low.global_characteristic)
    assert low.distortional_characteristic == 100
    local = direct_resistance(100, 10000, 5, 10000, bending=bending)
    assert local.governing == "local"
    dist = direct_resistance(100, 10000, 10000, 5, bending=bending)
    assert dist.governing == "distorcional"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_mrd_invalid_critical_values_cannot_approve(value):
    with pytest.raises(ValueError):
        direct_resistance(100, value, 10, 10)


def test_mrd_local_and_distortional_critical_loads_are_automatic_and_persisted():
    model = formed(overrides={"NcrG": 100.})
    expected = output(model)
    assert expected["status"] == "checked"
    check = expected["checks"]["axial_compression"]
    assert check["parameters"]["automatic_elastic_criticals"]["NcrL"]["value"] > 0
    assert check["parameters"]["automatic_elastic_criticals"]["NcrD"]["value"] > 0
    assert check["parameters"]["automatic_elastic_criticals"]["NcrL"]["half_wave_mm"] > 0
    assert check["parameters"]["automatic_elastic_criticals"]["NcrD"]["half_wave_mm"] > 0
    restored = StructuralModel()
    restored.load_dict(model.as_dict())
    restored.revision = model.revision
    assert output(restored)["checks"]["axial_compression"]["capacity"] == expected["checks"]["axial_compression"]["capacity"]


def test_formed_flexure_automates_local_modes_and_reports_wavelength_in_memorial():
    model = formed(rows=[{"moment_y": .1}], overrides={"McrGy": 100., "McrGz": 100.})
    result = output(model)
    flexion = result["checks"]["flexion_y"]
    assert flexion["status"] == "checked"
    automatic = flexion["parameters"]["automatic_elastic_criticals"]
    assert automatic["McrLy"]["value"] > 0
    assert automatic["McrDy"]["value"] > 0
    assert automatic["McrLy"]["half_wave_mm"] > 0
    model.verification_results = verify_model(model)["results"]
    memory = calculation_memory(model, ["B1"])
    equations = {}
    html = CalculationMemorialDialog._render(memory, {}, equation_latex=equations)
    assert "calculado automaticamente por faixas finitas" in html
    assert "meia-onda crítica" in html


def test_unclassified_distortional_mode_does_not_get_a_fictitious_critical_value(monkeypatch):
    from osa.verification import cold_formed_member as module
    original = module._automatic_mode_critical
    def unidentified(*args, **kwargs):
        return None if args[-1] == "distorcional" else original(*args, **kwargs)
    monkeypatch.setattr(module, "_automatic_mode_critical", unidentified)
    result = output(formed("C Formado", overrides={"NcrG": 100.}))
    check = result["checks"]["axial_compression"]
    assert check["status"] == "not_checked"
    assert "NcrD" in check["detail"]
    assert "NcrD" not in check["parameters"].get("automatic_elastic_criticals", {})


@pytest.mark.parametrize("family", ["U Formado", "Z Formado", "L Formado"])
def test_isolated_unstiffened_sections_have_no_distortional_space(family):
    result = output(formed(family, overrides={"NcrG": 100.}))
    item = result["checks"]["axial_compression"]
    assert item["status"] == "checked"
    assert item["parameters"]["NcrD"] == -1.
    assert "isolad" in item["parameters"]["advisories"][0]


def test_z_elastic_modulus_retains_unsymmetrical_bending_coupling():
    model = formed("Z90 Formado")
    p = section(model.bars["B1"])
    # Ignoring Iyz overstates the elastic modulus in a Z section.
    assert p["Wy_cm3"] < p["Iy_cm4"]/5
    assert abs(p["Iyz_cm4"]) > 1


def test_cold_shear_uses_14762_instead_of_8800_coefficients():
    model = formed(rows=[{"shear_z": 2.}])
    result = output(model)["checks"]["shear_z"]
    # h=100-4t=92 mm, t=2 mm: compact web branch with kv=5.
    assert result["capacity"] == pytest.approx(.6*25*9.2*.2/1.1)
    assert result["reference"] == "ABNT NBR 14762:2010, 9.8.3"


def test_unknown_horizontal_shear_and_torsion_block_global_approval():
    for row in ({"shear_y": 1.}, {"torque": 1.}):
        assert output(formed(rows=[row]))["status"] == "not_checked"


def test_interaction_uses_same_sample_and_requires_constant_axial_force():
    values = {"NcrG": 100, "NcrL": 100, "NcrD": 100,
              "McrGy": 100, "McrLy": 100, "McrDy": 100,
              "McrGz": 100, "McrLz": 100, "McrDz": 100}
    model = formed(rows=[{"x": 0., "axial": 10., "moment_y": 1.},
                         {"x": 3., "axial": 10., "moment_z": .5}], overrides=values)
    result = output(model)["checks"]
    nr, my, mz = (result[k]["capacity"] for k in ("axial_compression", "flexion_y", "flexion_z"))
    assert result["flexocompressao"]["utilization"] == pytest.approx(max(10/nr+100/my, 10/nr+50/mz))
    model.analysis_results[0].member_results["B1"]["samples"][1]["axial"] = 11.
    assert output(model)["checks"]["flexocompressao"]["status"] == "not_checked"


def test_z90_memorial_uses_actual_mrd_steps_and_editable_word_equations(tmp_path):
    model = formed("Z90 Formado", overrides={"NcrG": 100, "NcrL": 50, "NcrD": 80})
    model.verification_results = verify_model(model)["results"]
    memory = calculation_memory(model, ["B1"])
    equations = {}
    html = CalculationMemorialDialog._render(memory, {}, equation_latex=equations)
    assert "14762:2010" in html and "C.3" in html
    assert "enrijecedor" in html and "Produto de inércia" in html
    assert "curva geral de compressão da NBR 8800" not in html
    assert "NÃO VERIFICADO" not in html
    target = tmp_path/"z90.docx"
    export_calculation_memorial_docx(html, equations, target)
    with ZipFile(target) as document:
        xml = document.read("word/document.xml").decode()
    assert "m:oMath" in xml


def test_mode_absence_is_explicit_persisted_and_has_no_fictitious_critical_steps():
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": -1.})
    item = output(model)["checks"]["axial_compression"]
    assert item["status"] == "checked"
    ag = section(model.bars["B1"])["Ag_cm2"]
    expected = direct_resistance(ag*25, 100, 50, None)
    assert item["capacity"] == pytest.approx(expected.resistance)
    assert not any("dist" in step["symbol"] for step in item["steps"])
    assert "distorcional" in item["parameters"]["advisories"][0]
    restored = StructuralModel()
    restored.load_dict(model.as_dict())
    assert dict(restored.bars["B1"].calculation_property_overrides)["NcrD"] == -1.
    assert direct_resistance(100, None, None, None).resistance == pytest.approx(100/1.2)


@pytest.mark.parametrize("family", ["U Formado", "C Formado", "Z90 Formado"])
def test_grouped_formed_members_use_consistent_data_and_governing_member(family):
    model = formed(family, overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    model.add_node("C", 0, 0, 6)
    model.add_bar("B2", "B", "C")
    model.update_bar_section("B2", family)
    model.update_bar_material("B2", "ASTM A36", model.materials["ASTM A36"])
    model.update_member_profile("B2", model.bars["B1"].profile, model.bars["B1"].geometry_dict())
    for name in ("B1", "B2"):
        for key, value in {"NcrG": 100., "NcrL": 50., "NcrD": 80.}.items():
            model.update_bar_calculation_property(name, key, value)
    model.group_verification_elements(("B1", "B2"))
    assert all(not model.bars[name].calculation_property_overrides for name in ("B1", "B2"))
    # The group is a new stability member: supply its results after grouping.
    for name in ("B1", "B2"):
        for key, value in {"NcrG": 100., "NcrL": 50., "NcrD": 80.}.items():
            model.update_bar_calculation_property(name, key, value)
    def sample(force):
        return {"x": 1., "axial": force, "moment_y": 0., "moment_z": 0., "shear_y": 0., "shear_z": 0., "torque": 0.}
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={
        "B1": {"samples": [sample(10.)]}, "B2": {"samples": [sample(20.)]}})]
    summary = verify_model(model)["results"]["group:B1|B2"]
    assert summary["checks"]["axial_compression"]["critical_member"] == "B2"
    model.update_bar_calculation_property("B2", "NcrL", None)
    item = verify_model(model)["results"]["group:B1|B2"]
    assert item["status"] == "not_checked"
    assert "diferentes no grupo" in item["detail"]


def test_mrd_does_not_bypass_general_plate_slenderness_limits():
    model = formed("U Formado", overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    model.update_member_profile("B1", "U com alma excessivamente esbelta", {"d": 200., "bf": 40., "t": 1.})
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={"B1": {"samples": [{
        "x": 1., "axial": 10., "moment_y": 0., "moment_z": 0., "shear_y": 0., "shear_z": 0., "torque": 0.}]}})]
    item = output(model)["checks"]["axial_compression"]
    assert item["status"] == "not_checked"
    assert "Tabela 4" in item["detail"]
    assert "capacity" not in item


def test_external_buckling_inputs_are_invalidated_by_physical_changes_but_not_other_overrides():
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": -1.})
    model.update_bar_calculation_property("B1", "Ct", .8)
    assert dict(model.bars["B1"].calculation_property_overrides)["NcrG"] == 100.
    model.update_member_profile("B1", "Seção alterada", {"d": 120., "bf": 50., "t": 2., "c": 15.})
    values = dict(model.bars["B1"].calculation_property_overrides)
    assert "NcrG" not in values and "NcrD" not in values
    assert values["Ct"] == .8


def test_saved_buckling_inputs_cannot_be_reused_after_external_geometry_edit():
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    data = model.as_dict()
    data["members"][0]["section_geometry"] = (("d", 150.), ("bf", 50.), ("t", 2.), ("c", 15.))
    restored = StructuralModel()
    restored.load_dict(data)
    assert not any(key.startswith("Ncr") for key, _ in restored.bars["B1"].calculation_property_overrides)


def test_mrd_source_survives_numeric_normalization_in_project_round_trip():
    from osa.domain import LoadCombination

    model = formed(combinations={"ELU": LoadCombination("ELU", (("Q", 1),), limit_state="ELU")})
    for key, value in {"NcrG": 100., "NcrL": 50., "NcrD": 80.}.items():
        model.update_bar_calculation_property("B1", key, value)
    restored = StructuralModel()
    restored.load_dict(model.as_dict())
    restored.revision = model.revision
    assert dict(restored.bars["B1"].calculation_property_overrides)["NcrG"] == 100.
    assert output(restored)["checks"]["axial_compression"]["status"] == "checked"
    assert output(restored)["checks"]["serviceability"]["status"] == "not_checked"


def test_actual_mrd_worker_runs_in_background_and_delivers_to_gui_thread(monkeypatch):
    import copy
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Slot
    from PySide6.QtWidgets import QApplication

    from osa.ui import verification_worker as module

    app = QApplication.instance() or QApplication([])
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    original = module.verify_model
    events = {}
    def record_calculation(snapshot, names=None):
        events["calculation_thread"] = QThread.currentThread()
        assert snapshot is not model
        return original(snapshot, names)
    monkeypatch.setattr(module, "verify_model", record_calculation)
    class Receiver(QObject):
        @Slot(object)
        def accept(self, payload):
            events["delivery_thread"] = QThread.currentThread()
            events["payload"] = payload
    receiver = Receiver()
    thread = QThread()
    worker = module.VerificationWorker(copy.deepcopy(model))
    worker.moveToThread(thread)
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    thread.started.connect(worker.run)
    worker.finished.connect(receiver.accept)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(loop.quit)
    thread.start()
    timer.start(5000)
    loop.exec()
    timer.stop()
    thread.quit()
    assert thread.wait(5000)
    assert events["calculation_thread"] != app.thread()
    assert events["delivery_thread"] == app.thread()
    assert events["payload"]["results"]["bar:B1"]["status"] == "checked"
    assert model.verification_results == {}
    app.processEvents()


def test_profile_label_and_parameter_order_do_not_discard_compatible_stability_inputs():
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    model.update_member_profile("B1", "Mesmo perfil renomeado", {"t": 2., "c": 15., "bf": 50., "d": 100.})
    assert dict(model.bars["B1"].calculation_property_overrides)["NcrG"] == 100.


def test_compression_without_effective_lengths_remains_pending_even_with_all_criticals():
    model = formed(overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80., "KL1": None, "KL2": None})
    result = output(model)
    assert result["status"] == "not_checked"
    assert result["checks"]["axial_compression"]["status"] == "checked"
    item = result["checks"]["compression_slenderness"]
    assert item["status"] == "not_checked"
    assert "K₁L₁" in item["detail"]


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_compression_slenderness_uses_principal_inertias_and_enforces_200(family):
    model = formed(family, rows=[{"axial": .01}],
                   overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    p = section(model.bars["B1"])
    r1, r2 = (sqrt(p[key]/p["Ag_cm2"]) for key in ("I1_cm4", "I2_cm4"))
    # Major-axis ratio=100, minor-axis ratio=201, with independent KL inputs.
    model.update_bar_calculation_property("B1", "KL1", r1)
    model.update_bar_calculation_property("B1", "KL2", 2.01*r2)
    result = output(model)
    item = result["checks"]["compression_slenderness"]
    assert item["parameters"]["lambda_1"] == pytest.approx(100.)
    assert item["applied"] == pytest.approx(201.)
    assert item["capacity"] == 200.
    assert item["utilization"] == pytest.approx(1.005)
    assert result["utilization"] > 1
    model.update_bar_calculation_property("B1", "KL2", r2*1.99)
    assert output(model)["utilization"] <= 1


def test_long_bar_reproduction_cannot_pass_compression_slenderness():
    model = formed(rows=[{"axial": .01}], overrides={"NcrG": 100., "NcrL": 50., "NcrD": 80.})
    result = model.analysis_results[0]
    model.update_node("B", 0, 0, 6)
    for key, value in {"KL1": 6., "KL2": 6., "NcrG": 100., "NcrL": 50., "NcrD": 80.}.items():
        model.update_bar_calculation_property("B1", key, value)
    from dataclasses import replace
    model.analysis_results = [replace(result, model_revision=model.revision)]
    result = output(model)
    assert result["checks"]["compression_slenderness"]["applied"] == pytest.approx(317.3043, rel=1e-6)
    assert result["utilization"] > 1
    assert result["critical_check"] == "Esbeltez de compressão"


def test_tension_slenderness_over_300_is_an_advisory_and_is_in_memorial():
    model = formed(rows=[{"axial": -.01}])
    area = section(model.bars["B1"])["Ag_cm2"]
    for key, value in {"An": area, "An0": area, "Ct": 1., "Ly": 20., "Lz": 20.}.items():
        model.update_bar_calculation_property("B1", key, value)
    result = output(model)
    item = result["checks"]["axial_tension"]
    assert item["parameters"]["tension_slenderness"] > 300
    assert "Acima do recomendado" in item["parameters"]["advisories"][0]
    assert result["status"] == "checked" and result["utilization"] < 1
    assert result["checks"]["compression_slenderness"]["status"] == "not_applicable"
    model.verification_results = verify_model(model)["results"]
    html = CalculationMemorialDialog._render(calculation_memory(model, ["B1"]), {}, equation_latex={})
    assert "Acima do recomendado" in html
    assert "Esbeltez de tração (recomendação)" in html


def test_effective_lengths_persist_and_physical_changes_invalidate_them():
    model = formed(overrides={"KL1": 2., "KL2": 1.})
    restored = StructuralModel()
    restored.load_dict(model.as_dict())
    assert dict(restored.bars["B1"].calculation_property_overrides)["KL1"] == 2.
    restored.update_node("B", 0, 0, 4)
    assert "KL1" not in dict(restored.bars["B1"].calculation_property_overrides)
    assert "KL2" not in dict(restored.bars["B1"].calculation_property_overrides)


@pytest.mark.parametrize("value", [0., -1., float("inf"), float("nan")])
def test_effective_lengths_reject_invalid_values_and_mode_absence(value):
    model = formed()
    with pytest.raises(ValueError):
        model.update_bar_calculation_property("B1", "KL1", value)


def test_group_with_different_effective_lengths_cannot_pass_slenderness():
    model = formed()
    model.add_node("C", 0, 0, 6)
    model.add_bar("B2", "B", "C", template=model.bars["B1"])
    model.group_verification_elements(("B1", "B2"))
    for name in ("B1", "B2"):
        for key, value in {"KL1": 1., "KL2": 1., "NcrG": 100., "NcrL": 50., "NcrD": 80.}.items():
            model.update_bar_calculation_property(name, key, value)
    model.update_bar_calculation_property("B2", "KL2", 2.)
    row = {"x": 1., "axial": .01, "moment_y": 0., "moment_z": 0., "shear_y": 0., "shear_z": 0., "torque": 0.}
    model.analysis_results = [AnalysisResult(model.revision, "ELU", member_results={
        name: {"samples": [row.copy()]} for name in ("B1", "B2")})]
    result = verify_model(model)["results"]["group:B1|B2"]
    assert result["status"] == "not_checked"
    assert "diferentes no grupo" in result["checks"]["compression_slenderness"]["detail"]


def test_global_compression_is_automatic_when_all_effective_lengths_are_supplied():
    model = formed(overrides={"KL1": 3., "KL2": 3., "KLt": 3.})
    result = output(model)['checks']['axial_compression']
    assert result['status'] == 'checked'
    automatic = result['parameters']['automatic_elastic_criticals']['NcrG']
    assert automatic['value'] > 0
    assert 'flexo-torção' in automatic['source']
    assert min(automatic['eigenvalues_N'])/1000 == pytest.approx(automatic['value'])


def test_global_bending_requires_explicit_fork_support_confirmation():
    model = formed(rows=[{'moment_y': .01}], overrides={'KL1': 3., 'KL2': 3., 'KLt': 3.})
    result = output(model)['checks']['flexion_y']
    assert result['status'] == 'not_checked'
    assert 'garfo' in result['detail']
    model.update_bar_calculation_property('B1', 'ForkSupports', 1.)
    result = output(model)['checks']['flexion_y']
    assert result['status'] == 'checked'
    assert 'McrGy' in result['parameters']['automatic_elastic_criticals']
    model.verification_results = verify_model(model)['results']
    html = CalculationMemorialDialog._render(calculation_memory(model, ['B1']), {}, equation_latex={})
    assert 'Vlasov' in html and 'empenamento livre' in html


def test_manual_global_critical_remains_available_for_other_boundary_conditions():
    model = formed(rows=[{'moment_z': .01}], overrides={'McrGz': 10., 'McrLz': 5., 'McrDz': 8.})
    result = output(model)['checks']['flexion_z']
    assert result['status'] == 'checked'
    assert 'McrGz' not in result['parameters']['automatic_elastic_criticals']


def test_cartola_vertical_shear_checks_each_web_and_reports_the_actual_participation():
    model = formed('Cartola Formado', rows=[{'shear_z': 10.}])
    item = output(model)['checks']['shear_z']
    per_web = .6*25*9.2*.2/1.1
    assert item['status'] == 'checked'
    assert item['capacity'] == pytest.approx(2*per_web)
    assert item['utilization'] == pytest.approx(10/(2*per_web))
    assert [row['vertical_fraction'] for row in item['parameters']['shear_web_distribution']] == pytest.approx((.5, .5))
    model.verification_results = verify_model(model)['results']
    html = CalculationMemorialDialog._render(calculation_memory(model, ['B1']), {}, equation_latex={})
    assert 'Integração do fluxo elástico em cada alma' in html
    assert 'VRd,w=' in html


@pytest.mark.parametrize('additional', [{'shear_y': 1.}, {'torque': .1}, {'bimoment': .01},
    {'saint_venant_torque': .1, 'warping_torque': -.1}])
def test_cartola_does_not_assume_pure_vertical_partition_with_other_flows(additional):
    model = formed('Cartola Formado', rows=[{'shear_z': 10., **additional}])
    item = output(model)['checks']['shear_z']
    assert item['status'] == 'not_checked'
    assert 'empenamento' in item['detail']



def test_cancelled_total_torque_does_not_hide_opposing_shear_stress_fields():
    model = formed(rows=[{'torque': 0., 'bimoment': 0., 'saint_venant_torque': .1, 'warping_torque': -.1}])
    check = output(model)['checks']['torsion']
    assert check['status'] == 'not_checked'



def test_zero_centroidal_torque_does_not_hide_channel_shear_center_eccentricity():
    model = formed('C Formado', rows=[{'shear_z': 1., 'torque': 0.}])
    result = output(model)
    assert result['checks']['torsion']['status'] == 'not_checked'
    assert 'cortante excêntrico' in result['checks']['torsion']['detail']
    assert result['checks']['torsion']['parameters']['unresolved_eccentric_torsion']
