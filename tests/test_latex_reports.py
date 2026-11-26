import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.commands import CommandSession
from osa.model import StructuralModel
from osa.reports import figures, latex
from osa.reports.memorial_latex import export_element_memorial, memorial_to_latex
from osa.reports.structure_report import (
    ReportOptions,
    StructureReportBuilder,
    combination_expression,
    default_deformed_combinations,
    export_structure_report,
)
from osa.services import ModelService
from osa.services.action_service import ActionService
from osa.verification.runner import verify_model


@pytest.fixture(scope="module")
def analyzed_mezanino():
    model = StructuralModel()
    CommandSession(ModelService(model)).submit("mezanino")
    ActionService(model).ensure_default_combinations()
    model.analysis_results = PyniteAdapter().run(model, AnalysisRequest(tuple(model.load_combinations)))
    model.verification_results = verify_model(model)["results"]
    return model


def test_text_and_numbers_follow_latex_and_brazilian_conventions():
    assert latex.tex_escape("Aço 50% & Cia_1 — cm⁴ λ") == r"Aço 50\% \& Cia\_1 --- cm\textsuperscript{4} $\lambda$"
    assert latex.number(34364.18) == r"34\,364,18"
    assert latex.number(-1.5, 1) == "$-$1,5"
    assert latex.percent(0.9698) == r"97,0\,\%"
    assert latex.unit(None, "mm") == "--"


def test_engine_falls_back_to_bundled_tectonic(monkeypatch, tmp_path):
    monkeypatch.delenv("OSA_LATEX_ENGINE", raising=False)
    monkeypatch.setattr(latex.shutil, "which", lambda _name: None)
    bundled = tmp_path / "tectonic.exe"
    monkeypatch.setattr(latex, "bundled_tectonic", lambda: bundled)

    assert latex.find_latex_engine() == str(bundled)
    assert latex.engine_name(latex.find_latex_engine()) == "tectonic"


def test_combination_expression_multiplies_the_three_factor_columns(analyzed_mezanino):
    service = analyzed_mezanino.load_combinations["Combinação 03"]

    assert combination_expression(analyzed_mezanino, service) == (
        r"$1{,}00\,\text{PP} + 1{,}00\,\text{AP} + 0{,}60\,\text{AV}$"
    )
    assert default_deformed_combinations(analyzed_mezanino) == ("Combinação 03",)


def test_deformed_shape_is_drawn_from_sampled_member_displacements(analyzed_mezanino, tmp_path):
    result = analyzed_mezanino.analysis_results[-1]
    sampled = max(
        sum(sample[f"deflection_{axis}"] ** 2 for axis in "xyz") ** 0.5
        for member in result.member_results.values()
        for sample in member["samples"]
    )

    info = figures.render_deformed_shape(analyzed_mezanino, result, tmp_path / "deformada.pdf")

    assert info["max_mm"] == pytest.approx(sampled * 1000.0)
    assert info["location"].startswith("barra ")
    mantissa = info["scale"] / 10 ** math.floor(math.log10(info["scale"]))
    assert round(mantissa, 6) in {1.0, 2.0, 5.0}
    assert (tmp_path / "deformada.pdf").read_bytes().startswith(b"%PDF")


def test_structure_report_has_reference_sections_tables_and_generated_figures(analyzed_mezanino, tmp_path):
    options = ReportOptions(subject="Mezanino metálico", location="São Paulo/SP", model_file="mezanino.osa")
    tex = StructureReportBuilder(analyzed_mezanino, options).build(tmp_path).read_text(encoding="utf-8")

    for heading in (
        "Objeto", "Descrição da estrutura", "Normas e referências", "Materiais", "Ações", "Combinações",
        "Verificação no estado-limite último (ELU)", "Verificação no estado-limite de serviço (ELS)",
        "Deformadas", "Geometria", "Quantitativo de material", "Conclusões e recomendações",
    ):
        assert f"\\section{{{heading}}}" in tex or f"\\subsection{{{heading}}}" in tex
    assert r"\usepackage{booktabs}" in tex and r"\pageref{LastPage}" in tex and r"\tableofcontents" in tex
    assert r"\NOK" in tex and r"\OK" in tex
    assert "W 310 x 44.5" in tex and "Combinação 03" in tex
    assert r"arquivo \texttt{mezanino.osa}" in tex
    for name in ("modelo_capa.pdf", "deformada_01.pdf", "geometria_3d.pdf", "geometria_planta.pdf"):
        assert (tmp_path / "fig" / name).is_file()
        assert f"fig/{name}" in tex


def test_pdf_export_without_latex_keeps_the_tex_project(analyzed_mezanino, tmp_path, monkeypatch):
    from osa.reports import structure_report

    monkeypatch.setattr(structure_report, "find_latex_engine", lambda: None)

    export = export_structure_report(analyzed_mezanino, tmp_path / "laudo.pdf", ReportOptions())

    assert export.pdf_path is None and "Overleaf" in export.error
    assert export.tex_path == tmp_path / "laudo_latex" / "laudo.tex"
    assert export.tex_path.is_file()


@pytest.mark.skipif(latex.find_latex_engine() is None, reason="nenhum compilador LaTeX disponível")
def test_structure_report_compiles_to_pdf(analyzed_mezanino, tmp_path):
    export = export_structure_report(analyzed_mezanino, tmp_path / "laudo.pdf", ReportOptions(subject="Mezanino"))

    assert export.error is None, export.error
    assert export.pdf_path.read_bytes().startswith(b"%PDF")


def test_element_memorial_html_becomes_latex_sections_tables_and_equations(tmp_path):
    marker = "OSA_EQUATION_OBJECT_0000_END"
    html = (
        "<div><h2>Memória de cálculo de elemento estrutural</h2><h3>1. Dados do elemento</h3>"
        "<table><tr><td>Seção</td><td>W 310 x 44.5</td></tr><tr><td>Área bruta (Ag)</td><td>57,2 cm²</td></tr></table>"
        '<p style="font-weight:700">Tração axial — ABNT NBR 8800:2024, 5.2</p>'
        f'<p align="center" style="text-align:center">{marker}</p></div>'
    )

    tex = memorial_to_latex(html, {marker: r"N_{t,Rd} = \dfrac{A_g f_y}{\gamma_{a1}} = 1,10"}, element="Pilar P1")

    assert r"\section{Dados do elemento}" in tex
    assert r"\subsection{Tração axial --- ABNT NBR 8800:2024, 5.2}" in tex
    assert r"Seção & W 310 x 44.5\\" in tex and r"57,2 cm\textsuperscript{2}" in tex
    assert r"\displaystyle N_{t,Rd} = \dfrac{A_g f_y}{\gamma_{a1}} = 1{,}10" in tex
    assert "Pilar P1" in tex and r"\end{document}" in tex

    export = export_element_memorial(html, {marker: "x = 1"}, tmp_path / "memorial.tex")
    assert export.tex_path.read_text(encoding="utf-8").startswith(r"\documentclass")


def test_memorial_dialog_exports_latex_project(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton

    from osa.ui.calculation_memorial_dialog import CalculationMemorialDialog, MemorialExportSuccessDialog
    from osa.ui.latex_export import TEX_FILTER

    app = QApplication.instance() or QApplication([])
    destination = tmp_path / "memorial"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(destination), TEX_FILTER))
    shown = []
    monkeypatch.setattr(MemorialExportSuccessDialog, "exec", lambda self: shown.append(True))

    dialog = CalculationMemorialDialog({"element_name": "Viga V1", "members": ("B1",)})
    dialog.findChild(QPushButton, "exportMemorial").click()

    exported = tmp_path / "memorial.tex"
    assert exported.is_file() and "Viga V1" in exported.read_text(encoding="utf-8")
    assert shown == [True]
    dialog.close()
    app.processEvents()


def test_structure_report_dialog_collects_cover_data_and_deformed_combinations(analyzed_mezanino, tmp_path):
    from PySide6.QtWidgets import QApplication

    from osa.ui.structure_report_dialog import StructureReportDialog

    app = QApplication.instance() or QApplication([])
    dialog = StructureReportDialog(analyzed_mezanino, tmp_path / "mezanino.osa")
    dialog.location_input.setText("Curitiba/PR")

    options = dialog.options()

    assert options.subject == "mezanino" and options.location == "Curitiba/PR"
    assert options.model_file == "mezanino.osa"
    assert options.deformed_combinations == ("Combinação 03",)
    assert options.deformation_scale is None
    dialog.close()
    app.processEvents()
