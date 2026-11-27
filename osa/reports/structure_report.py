"""Laudo técnico da estrutura em LaTeX, com figuras geradas a partir do modelo.

O documento segue a estrutura de um laudo de verificação estrutural: capa,
sumário, objeto, descrição, normas, materiais, ações e combinações, critérios
de cálculo, ELU, ELS, deformadas, geometria, quantitativo e conclusões. As
seções são preenchidas com os dados do modelo, da análise e das verificações.
O ``.tex`` fica editável para o engenheiro complementar o texto.
"""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

from . import figures
from .latex import (
    DocumentStyle,
    LatexCompilationError,
    clean_auxiliary_files,
    compile_latex,
    find_latex_engine,
    number,
    percent,
    preamble,
    tex_escape,
    unit,
)

logger = logging.getLogger(__name__)

DEFAULT_STANDARDS = (
    "ABNT NBR 8800:2024 -- Projeto de estruturas de aço e de estruturas mistas de aço e concreto de edifícios.",
    "ABNT NBR 8681:2003 -- Ações e segurança nas estruturas.",
    "ABNT NBR 6120:2019 -- Ações para o cálculo de estruturas de edificações.",
    "ABNT NBR 6123:2023 -- Forças devidas ao vento em edificações.",
)
LIMIT_STATE_LABELS = {"ELU": "ELU", "ELS": "ELS", "CAR": "Característica"}
MAX_DEFORMED_FIGURES = 8
_GRAVITY = 9.80665


@dataclass
class ReportOptions:
    """Dados editáveis do laudo (capa, cabeçalho e rodapé)."""

    title: str = "Laudo técnico de verificação estrutural"
    subject: str = ""
    location: str = ""
    author: str = ""
    crea: str = ""
    cover_work: str = ""
    cover_client: str = ""
    cover_address: str = ""
    cover_model_mode: str = "analytic"
    cover_direction: str = "ISO-SE"
    cover_identity_path: str = ""
    revision: str = "0"
    issue_date: date = field(default_factory=date.today)
    model_file: str = ""
    deformed_combinations: tuple[str, ...] | None = None
    deformation_scale: float | None = None
    standards: tuple[str, ...] = DEFAULT_STANDARDS


@dataclass
class ReportExport:
    tex_path: Path
    pdf_path: Path | None = None
    engine: str | None = None
    error: str | None = None


def software_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("open-structural-analysis")
    except PackageNotFoundError:
        return ""


def _math_number(value: float, decimals: int = 2) -> str:
    return number(value, decimals, thousands=False).replace(",", "{,}")


def profile_label(bar) -> str:
    """Nome curto do perfil (ex.: ``W 250 x 44.8``); a família só aparece quando não há perfil."""
    return (bar.profile or bar.section or "Sem seção").strip()


def _bar_material(model, bar) -> tuple[float, ...]:
    return tuple(model.materials.get(bar.material, ()) or getattr(bar, "material_values", ()))


def _member_status(model) -> dict[str, str]:
    """Situação de cada barra no ELU: ``ok``, ``fail`` ou ``none`` (sem verificação)."""
    from osa.verification.elements import verification_elements

    status: dict[str, str] = {}
    results = getattr(model, "verification_results", {}) or {}
    if not results:
        return status
    for element in verification_elements(model):
        result = results.get(element.key) or {}
        utilization = result.get("utilization")
        if result.get("status") == "checked" and utilization is not None:
            state = "fail" if result.get("has_rejected_check") or float(utilization) > 1.0 else "ok"
        elif result.get("has_rejected_check"):
            state = "fail"
        else:
            state = "none"
        for name in element.member_names:
            status[name] = state
    return status


def combination_terms(model, combination) -> list[tuple[str, float]]:
    """Fator total (γ·ψ0·ψ) de cada ação ativa, na ordem do grupo de ações."""
    from osa.services.action_service import ActionService

    group = model.action_groups.get(combination.action_group or "") or ActionService(model).selected_group()
    order = [action.abbreviation for action in (group.actions if group is not None else ())]
    active = list(combination.active_actions or order)
    active.sort(key=lambda name: order.index(name) if name in order else len(order))
    gamma, psi_0, psi = (dict(values) for values in (
        combination.factors, combination.factors_2, combination.factors_3,
    ))
    return [
        (name, gamma.get(name, 1.0) * psi_0.get(name, 1.0) * psi.get(name, 1.0))
        for name in active
    ]


def combination_expression(model, combination) -> str:
    terms = [
        f"{_math_number(factor)}\\,\\text{{{tex_escape(name)}}}"
        for name, factor in combination_terms(model, combination) if abs(factor) > 1e-12
    ]
    return f"${' + '.join(terms)}$" if terms else "--"


class StructureReportBuilder:
    """Monta o ``.tex`` do laudo e as figuras em ``fig/``."""

    def __init__(
        self, model, options: ReportOptions | None = None, *, cover_support_mesh=None,
        cover_model_image=None,
    ) -> None:
        self.model = model
        self.options = options or ReportOptions()
        self.cover_support_mesh = cover_support_mesh
        self.cover_model_image = cover_model_image
        self.results = {result.load_reference: result for result in getattr(model, "analysis_results", ())}
        self.status = _member_status(model)
        self.version = software_version()

    # ------------------------------------------------------------------ dados
    def _coordinates(self) -> np.ndarray:
        return figures._model_points(self.model)

    def deformed_combinations(self) -> tuple[str, ...]:
        if self.options.deformed_combinations is not None:
            return tuple(name for name in self.options.deformed_combinations if name in self.results)
        return default_deformed_combinations(self.model)

    def _profiles(self) -> dict[tuple[str, str], list]:
        profiles: dict[tuple[str, str], list] = defaultdict(list)
        for bar in self.model.bars.values():
            profiles[(bar.section or "Sem seção", bar.profile or "--")].append(bar)
        return dict(sorted(profiles.items()))

    def _bar_length(self, bar) -> float:
        start, end = self.model.nodes.get(bar.start_node), self.model.nodes.get(bar.end_node)
        if start is None or end is None:
            return 0.0
        return float(np.linalg.norm(np.subtract((end.x, end.y, end.z), (start.x, start.y, start.z))))

    def _mass_per_meter(self, bar) -> float | None:
        from osa.sections.properties import calculate_section_properties

        values = _bar_material(self.model, bar)
        density = values[3] * 1000.0 / _GRAVITY if len(values) > 3 and values[3] else 7850.0
        try:
            return calculate_section_properties(bar.section, bar.geometry_dict(), density).mass_kg_m
        except (KeyError, TypeError, ValueError, ArithmeticError):
            logger.debug("Sem massa linear para a barra %s (%s).", bar.name, bar.profile)
            return None

    # ------------------------------------------------------------- documento
    def build(self, folder: str | Path, progress: Callable[[str], None] | None = None) -> Path:
        folder = Path(folder)
        figure_folder = folder / "fig"
        figure_folder.mkdir(parents=True, exist_ok=True)
        notify = progress or (lambda _message: None)
        parts = [self._preamble(), r"\begin{document}"]
        notify("Gerando vista do modelo")
        parts.append(self._title_page(figure_folder))
        parts.append("\\tableofcontents\n\\newpage\n")
        parts.append(self._object_section())
        parts.append(self._description_section())
        parts.append(self._standards_section())
        parts.append(self._materials_section())
        parts.append(self._actions_section())
        parts.append(self._criteria_section())
        parts.append(self._ultimate_section())
        parts.append(self._service_section())
        notify("Gerando deformadas")
        parts.append(self._deformed_section(figure_folder))
        notify("Gerando geometria")
        parts.append(self._geometry_section(figure_folder))
        parts.append(self._quantities_section())
        parts.append(self._conclusions_section())
        parts.append(r"\end{document}")
        tex_path = folder / "laudo.tex"
        tex_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
        return tex_path

    def _subject(self) -> str:
        return self.options.subject or (Path(self.options.model_file).stem if self.options.model_file else "Estrutura")

    def _preamble(self) -> str:
        options = self.options
        software = f"Open Structural Analysis {self.version}".strip()
        model_file = (
            f" -- arquivo \\texttt{{{tex_escape(Path(options.model_file).name)}}}" if options.model_file else ""
        )
        return preamble(DocumentStyle(
            header_left=f"Laudo estrutural – {self._subject()}",
            footer_left=f"Modelo: {tex_escape(software)}{model_file}",
            footer_right=f"Emissão: {options.issue_date:%d/%m/%Y} – Rev. {options.revision}",
            pdf_title=options.title,
            pdf_author=options.author,
        ))

    def _title_page(self, figure_folder: Path) -> str:
        options = self.options
        # Reserve the logo's height even when no visual identity is supplied,
        # so the title and model keep the same vertical positions.
        identity = "\\rule{0pt}{3cm}\\par\n"
        if options.cover_identity_path:
            from PIL import Image, ImageOps

            source = Path(options.cover_identity_path)
            if source.is_file():
                with Image.open(source) as image:
                    ImageOps.exif_transpose(image).convert("RGBA").save(
                        figure_folder / "identidade_visual.png"
                    )
                identity = (
                    "\\includegraphics[height=3cm]"
                    "{fig/identidade_visual.png}\\par\n"
                )
        cover = ""
        if self.model.bars or getattr(self.model, "plates", {}):
            cover_model_image = self.cover_model_image
            if options.cover_model_mode == "executive" and cover_model_image is None:
                cover_model_image = figure_folder / "modelo_capa_executivo.png"
                figures.render_executive_model_image(
                    self.model,
                    options.cover_direction,
                    cover_model_image,
                    support_mesh=self.cover_support_mesh,
                )
            figures.render_model_view(
                self.model,
                figure_folder / "modelo_capa.pdf",
                view=(
                    figures.cover_view(self.options.cover_direction)
                    if self.options.cover_model_mode == "executive" else None
                ),
                member_status=None,
                max_height_cm=10.0,
                model_mode=self.options.cover_model_mode,
                show_global_axes=False,
                cover_rendering=True,
                support_mesh=self.cover_support_mesh,
                cover_model_image=cover_model_image,
            )
            cover = (
                "\\includegraphics[width=0.9\\textwidth,height=0.42\\textheight,keepaspectratio]"
                "{fig/modelo_capa.pdf}\\par\n"
            )
        rows = [
            ("Endereço:", options.cover_address),
            ("Cliente:", options.cover_client),
            ("Responsável:", options.author),
            ("CREA:", options.crea),
        ]
        table = "\n".join(f"{tex_escape(label)} & {tex_escape(value)}\\\\" for label, value in rows)
        cover_work = options.cover_work or options.subject or self._subject()
        location = f"{{\\Large {tex_escape(cover_work)}\\par}}\n"
        return (
            "\\begin{titlepage}\n\\centering\n"
            f"{identity}"
            "\\vspace{2.5cm}\n"
            f"{{\\LARGE\\bfseries {tex_escape(options.title.upper())}\\par}}\n"
            "\\vspace{0.8cm}\n"
            f"{location}\\vspace{{0.8cm}}\n{cover}\\vfill\n"
            "\\begin{tabular}{p{0.16\\textwidth}p{0.74\\textwidth}}\n"
            f"{table}\n\\end{{tabular}}\n\\end{{titlepage}}\n"
        )

    def _object_section(self) -> str:
        extent = np.ptp(self._coordinates(), axis=0) if len(self._coordinates()) else np.zeros(3)
        plan = f", com planta aproximada de ${_math_number(extent[0])} \\times {_math_number(extent[1])}$\\,m" if (
            extent[0] > 0 and extent[1] > 0
        ) else ""
        location = f", em {tex_escape(self.options.location)}" if self.options.location else ""
        return (
            "\\section{Objeto}\n"
            f"Este laudo apresenta a verificação estrutural de \\textbf{{{tex_escape(self._subject())}}}{plan}{location}. "
            "A estrutura foi modelada e calculada no Open Structural Analysis "
            f"{tex_escape(self.version)} (análise com PyNite). O laudo reúne as premissas de cálculo, "
            "as ações consideradas, o resumo das verificações de estado-limite último (ELU) e de serviço (ELS), "
            "as deformadas obtidas no modelo e o quantitativo de material por perfil.\n"
        )

    def _description_section(self) -> str:
        model = self.model
        coordinates = self._coordinates()
        items = []
        if len(coordinates):
            low, high = coordinates.min(axis=0), coordinates.max(axis=0)
            items.append(
                "Dimensões envolventes do modelo: "
                f"$X$ de {unit(low[0], 'm')} a {unit(high[0], 'm')}, "
                f"$Y$ de {unit(low[1], 'm')} a {unit(high[1], 'm')} e "
                f"$Z$ de {unit(low[2], 'm')} a {unit(high[2], 'm')}."
            )
        supports = sum(1 for node in model.nodes.values() if any(node.supports))
        plates = len(getattr(model, "plates", {}))
        counts = f"{len(model.nodes)} nós, {len(model.bars)} barras"
        counts += f", {plates} placas" if plates else ""
        items.append(f"Modelo de barras com {counts} e {supports} nós com restrições de apoio.")
        for (family, profile), bars in self._profiles().items():
            items.append(
                f"{tex_escape(family)} {tex_escape(profile)}: {len(bars)} barra{'s' if len(bars) != 1 else ''} "
                f"({unit(sum(self._bar_length(bar) for bar in bars), 'm')})."
            )
        body = "\n".join(f"  \\item {item}" for item in items)
        return f"\\section{{Descrição da estrutura}}\n\\begin{{itemize}}\n{body}\n\\end{{itemize}}\n"

    def _standards_section(self) -> str:
        body = "\n".join(f"  \\item {tex_escape(item)}" for item in self.options.standards)
        return f"\\section{{Normas e referências}}\n\\begin{{itemize}}\n{body}\n\\end{{itemize}}\n"

    def _materials_section(self) -> str:
        used = sorted({bar.material for bar in self.model.bars.values()} | {
            plate.material for plate in getattr(self.model, "plates", {}).values()
        })
        rows = []
        for name in used:
            values = self.model.materials.get(name, ())
            if len(values) < 6:
                continue
            rows.append(
                f"{tex_escape(name)} & {tex_escape(self.model.material_types.get(name, ''))} & "
                f"{number(values[0] / 1e6, 1)} & {number(values[4] / 1e3, 0)} & {number(values[5] / 1e3, 0)} & "
                f"{number(values[3], 2)}\\\\"
            )
        if not rows:
            return "\\section{Materiais}\nNenhum material atribuído às barras do modelo.\n"
        return (
            "\\section{Materiais}\n"
            "\\begin{table}[H]\\centering\\small\n\\caption{Propriedades dos materiais adotadas no modelo}\n"
            "\\begin{tabular}{llrrrr}\n\\toprule\n"
            "Material & Tipo & $E$ (GPa) & $f_y$ (MPa) & $f_u$ (MPa) & $\\gamma$ (kN/m$^3$)\\\\\n\\midrule\n"
            + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n"
        )

    def _actions_section(self) -> str:
        from osa.services.action_service import ActionService

        model = self.model
        group = ActionService(model).selected_group()
        definitions = list(group.actions) if group is not None else []
        counts: dict[str, int] = defaultdict(int)
        for action in model.actions.values():
            counts[action.load_case] += 1
        rows = [
            f"{tex_escape(item.abbreviation)} & {tex_escape(item.name)} & "
            f"{counts.get(item.name, 0) + counts.get(item.abbreviation, 0)}\\\\"
            for item in definitions
        ]
        parts = ["\\section{Ações}", "\\subsection{Ações consideradas}"]
        if rows:
            parts.append(
                "\\begin{table}[H]\\centering\\small\n"
                f"\\caption{{Ações do grupo {tex_escape(group.name)}}}\n"
                "\\begin{tabular}{llr}\n\\toprule\nSigla & Descrição & Cargas aplicadas\\\\\n\\midrule\n"
                + "\n".join(rows) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}"
            )
        else:
            parts.append("Nenhuma ação cadastrada no modelo.")
        parts.append("\\subsection{Combinações}")
        combinations = list(model.load_combinations.values())
        if not combinations:
            parts.append("Nenhuma combinação de ações cadastrada.")
            return "\n".join(parts) + "\n"
        parts.append(
            "Combinações últimas normais e de serviço (NBR 8681 / NBR 8800), com os fatores "
            "$\\gamma$, $\\psi_0$ e $\\psi_1$/$\\psi_2$ já multiplicados:\n"
            "\\[F_d = \\sum \\gamma_{g} F_{G,k} + \\gamma_{q1} F_{Q1,k} + \\sum \\gamma_{qj}\\, \\psi_{0j} F_{Qj,k}\\]"
        )
        rows = [
            f"{tex_escape(item.name)} & {LIMIT_STATE_LABELS.get(item.limit_state, tex_escape(item.limit_state))} & "
            f"{combination_expression(model, item)}\\\\"
            for item in combinations
        ]
        parts.append(
            "{\\small\n\\begin{longtable}{llp{0.62\\textwidth}}\n"
            "\\caption{Combinações de ações}\\\\\n\\toprule\nCombinação & Tipo & Expressão\\\\\n\\midrule\n\\endfirsthead\n"
            "\\toprule\nCombinação & Tipo & Expressão\\\\\n\\midrule\n\\endhead\n"
            "\\bottomrule\n\\endfoot\n" + "\n".join(rows) + "\n\\end{longtable}\n}"
        )
        return "\n".join(parts) + "\n"

    def _criteria_section(self) -> str:
        items = [
            (
                "Análise elástica linear de primeira ordem pelo método dos deslocamentos (PyNite), "
                "com barras de pórtico espacial (6 graus de liberdade por nó)."
            ),
            (
                "Verificação das barras de aço segundo a ABNT NBR 8800:2024 (tração, compressão, flexão, "
                "cortante e esforços combinados), com os comprimentos de flambagem definidos no modelo."
            ),
            "Deslocamentos obtidos diretamente das combinações de serviço do modelo.",
        ]
        released = sum(1 for bar in self.model.bars.values() if any(bar.releases))
        if released:
            items.append(f"{released} barras com liberações de extremidade (articulações) definidas no modelo.")
        if getattr(self.model, "plates", {}):
            items.append("Placas discretizadas em elementos de casca quadrilaterais.")
        body = "\n".join(f"  \\item {item}" for item in items)
        return f"\\section{{Modelo e critérios de cálculo}}\n\\begin{{itemize}}\n{body}\n\\end{{itemize}}\n"

    def _ultimate_rows(self):
        from osa.verification.elements import verification_elements

        results = getattr(self.model, "verification_results", {}) or {}
        by_profile: dict[str, dict] = {}
        elements = []
        for element in verification_elements(self.model):
            result = results.get(element.key)
            if not result:
                continue
            bar = self.model.bars.get(element.member_names[0])
            if bar is None:
                continue
            utilization = result.get("utilization")
            checked = result.get("status") == "checked" and utilization is not None
            elements.append((element, result, float(utilization) if checked else None))
            key = profile_label(bar)
            entry = by_profile.setdefault(key, {"count": 0, "best": None, "element": None, "result": None})
            entry["count"] += 1
            if checked and (entry["best"] is None or float(utilization) > entry["best"]):
                entry.update(best=float(utilization), element=element, result=result)
        return by_profile, elements

    def _ultimate_section(self) -> str:
        parts = ["\\section{Verificação no estado-limite último (ELU)}"]
        by_profile, elements = self._ultimate_rows()
        if not elements:
            parts.append(
                "A verificação das barras ainda não foi executada para este modelo. "
                "Execute o comando \\texttt{VERIFY} antes de emitir o laudo."
            )
            return "\n".join(parts) + "\n"
        checked = [item for item in elements if item[2] is not None]
        failed = [item for item in elements if self._fails(item)]
        unchecked = len(elements) - len(checked)
        worst = max(checked, key=lambda item: item[2], default=None)
        if failed:
            summary = f"Das {len(elements)} barras/elementos verificados, {len(failed)} não atendem às verificações."
        else:
            summary = f"Todas as {len(checked)} barras/elementos verificados atendem às verificações de resistência e estabilidade."
        if worst is not None:
            summary += (
                f" O maior aproveitamento é $\\eta = {_math_number(worst[2] * 100.0, 1)}\\,\\%$, "
                f"no elemento {tex_escape(worst[0].name)} ({tex_escape(worst[1].get('critical_check', ''))})."
            )
        if unchecked:
            summary += f" {unchecked} elementos não têm rotina de verificação aplicável."
        parts.append(summary + " A Tabela~\\ref{tab:elu} mostra o aproveitamento máximo de cada perfil.")
        rows = []
        for profile, entry in by_profile.items():
            result = entry["result"] or {}
            situation = "\\NV" if entry["best"] is None else "\\NOK" if entry["best"] > 1.0 else "\\OK"
            rows.append(
                f"{tex_escape(profile)} & {entry['count']} & "
                f"{percent(entry['best']) if entry['best'] is not None else '--'} & "
                f"{tex_escape(entry['element'].name) if entry['element'] else '--'} & "
                f"{tex_escape(result.get('critical_check', '--'))} & "
                f"{tex_escape(result.get('critical_combination', '--'))} & {situation}\\\\"
            )
        parts.append(
            "{\\small\\setlength{\\tabcolsep}{4pt}\n"
            "\\begin{longtable}{@{}>{\\raggedright\\arraybackslash}p{0.2\\textwidth}rrl"
            ">{\\raggedright\\arraybackslash}p{0.2\\textwidth}lc@{}}\n"
            "\\caption{Aproveitamento máximo ($\\eta$) por perfil -- combinações últimas}\\label{tab:elu}\\\\\n"
            "\\toprule\nPerfil & Elem. & $\\eta_{\\max}$ & Crítico & Verificação & Combinação & Situação\\\\\n"
            "\\midrule\n\\endfirsthead\n\\toprule\nPerfil & Elem. & $\\eta_{\\max}$ & Crítico & Verificação & "
            "Combinação & Situação\\\\\n\\midrule\n\\endhead\n\\bottomrule\n\\endfoot\n"
            + "\n".join(rows) + "\n\\end{longtable}\n}"
        )
        if failed:
            failed_rows = [
                f"{tex_escape(element.name)} & {tex_escape(', '.join(element.member_names))} & "
                f"{percent(utilization) if utilization is not None else '--'} & "
                f"{tex_escape(result.get('critical_check', '--'))} & {tex_escape(result.get('critical_combination', '--'))}\\\\"
                for element, result, utilization in sorted(failed, key=lambda item: -(item[2] or 0.0))
            ]
            parts.append(
                "{\\small\n\\begin{longtable}{lp{0.25\\textwidth}rp{0.22\\textwidth}l}\n"
                "\\caption{Elementos que não atendem ao ELU}\\\\\n\\toprule\n"
                "Elemento & Barras & $\\eta$ & Verificação & Combinação\\\\\n\\midrule\n\\endfirsthead\n"
                "\\toprule\nElemento & Barras & $\\eta$ & Verificação & Combinação\\\\\n\\midrule\n\\endhead\n"
                "\\bottomrule\n\\endfoot\n" + "\n".join(failed_rows) + "\n\\end{longtable}\n}"
            )
        return "\n".join(parts) + "\n"

    @staticmethod
    def _fails(item) -> bool:
        _element, result, utilization = item
        return bool(result.get("has_rejected_check")) or (utilization is not None and utilization > 1.0)

    def _service_combinations(self) -> list:
        combinations = [item for item in self.model.load_combinations.values() if item.name in self.results]
        service = [item for item in combinations if item.limit_state == "ELS"]
        return service or [item for item in combinations if item.limit_state == "CAR"] or combinations

    def _service_section(self) -> str:
        parts = [
            "\\section{Verificação no estado-limite de serviço (ELS)}",
            "\\subsection{Critérios}\\label{sec:els-criterios}",
            (
                "Limites usuais da ABNT NBR 8800 (Anexo C, Tabela C.1), a comparar com os deslocamentos abaixo:\n"
                "\\begin{itemize}\n"
                "  \\item vigas de piso: $L/350$; treliças e vigas de cobertura: $L/250$;\n"
                "  \\item terças e travessas de fechamento: $L/180$;\n"
                "  \\item galpões em geral: deslocamento horizontal do topo dos pilares em relação à base $H/300$.\n"
                "\\end{itemize}"
            ),
            "\\subsection{Resultados}",
        ]
        combinations = self._service_combinations()
        if not combinations:
            parts.append("A análise ainda não foi processada; não há deslocamentos para apresentar.")
            return "\n".join(parts) + "\n"
        rows = []
        for combination in combinations:
            result = self.results[combination.name]
            vertical = max(
                ((abs(values.get("DZ", 0.0)), name) for name, values in result.node_results.items()), default=(0.0, "--"),
            )
            horizontal = max((
                (float(np.hypot(values.get("DX", 0.0), values.get("DY", 0.0))), name)
                for name, values in result.node_results.items()
            ), default=(0.0, "--"))
            total, location = figures.max_displacement(self.model, result)
            rows.append(
                f"{tex_escape(combination.name)} & {LIMIT_STATE_LABELS.get(combination.limit_state, '')} & "
                f"{unit(vertical[0] * 1000, 'mm', 1)} ({tex_escape(vertical[1])}) & "
                f"{unit(horizontal[0] * 1000, 'mm', 1)} ({tex_escape(horizontal[1])}) & "
                f"{unit(total * 1000, 'mm', 1)} ({tex_escape(location or '--')})\\\\"
            )
        parts.append(
            "{\\small\n\\begin{longtable}{llrrr}\n"
            "\\caption{Deslocamentos máximos por combinação}\\label{tab:els}\\\\\n\\toprule\n"
            "Combinação & Tipo & Vertical nodal & Horizontal nodal & Total (nós e barras)\\\\\n\\midrule\n\\endfirsthead\n"
            "\\toprule\nCombinação & Tipo & Vertical nodal & Horizontal nodal & Total (nós e barras)\\\\\n\\midrule\n"
            "\\endhead\n\\bottomrule\n\\endfoot\n" + "\n".join(rows) + "\n\\end{longtable}\n}"
        )
        parts.append(
            "O deslocamento total inclui a flecha local das barras entre nós; os valores nodais permitem a "
            "comparação direta com os limites de deslocamento horizontal e vertical da estrutura."
        )
        return "\n".join(parts) + "\n"

    def _deformed_section(self, figure_folder: Path) -> str:
        parts = ["\\section{Deformadas}"]
        names = self.deformed_combinations()
        if not names:
            parts.append("A análise ainda não foi processada; não há deformadas para apresentar.")
            return "\n".join(parts) + "\n"
        rendered = []
        for index, name in enumerate(names, start=1):
            path = figure_folder / f"deformada_{index:02d}.pdf"
            info = figures.render_deformed_shape(
                self.model, self.results[name], path, scale=self.options.deformation_scale,
            )
            rendered.append((name, path, info))
        scales = {info["scale"] for _, _, info in rendered}
        scale_text = (
            f"com fator de escala {number(next(iter(scales)), 0)} nos deslocamentos" if len(scales) == 1
            else "com o fator de escala indicado em cada legenda"
        )
        parts.append(
            "As figuras a seguir mostram a deformada da estrutura, geradas diretamente dos resultados da "
            f"análise, {scale_text}. A indeformada aparece em cinza claro e a escala de cores dá o "
            "deslocamento total de cada ponto das barras, em mm."
        )
        for name, path, info in rendered:
            combination = self.model.load_combinations.get(name)
            expression = f" ({combination_expression(self.model, combination)})" if combination else ""
            scale = f", escala {number(info['scale'], 0)}" if len(scales) > 1 else ""
            parts.append(
                "\\begin{figure}[H]\\centering\n"
                f"\\includegraphics[width=\\textwidth]{{fig/{path.name}}}\n"
                f"\\caption{{Deformada para {tex_escape(name)}{expression} -- máx. "
                f"{unit(info['max_mm'], 'mm', 1)}{scale}}}\n\\end{{figure}}"
            )
        return "\n".join(parts) + "\n"

    def _geometry_section(self, figure_folder: Path) -> str:
        if not self.model.bars and not getattr(self.model, "plates", {}):
            return ""
        iso = figure_folder / "geometria_3d.pdf"
        top = figure_folder / "geometria_planta.pdf"
        figures.render_model_view(self.model, iso, view=figures.VIEWS["iso_se"])
        figures.render_model_view(self.model, top, view=figures.VIEWS["top"], max_height_cm=9.5)
        return (
            "\\section{Geometria}\n"
            "\\begin{figure}[H]\\centering\n\\includegraphics[width=\\textwidth]{fig/geometria_3d.pdf}\n"
            "\\caption{Vista tridimensional do modelo de cálculo}\n\\end{figure}\n"
            "\\begin{figure}[H]\\centering\n\\includegraphics[width=\\textwidth]{fig/geometria_planta.pdf}\n"
            "\\caption{Planta (vista superior) do modelo de cálculo}\n\\end{figure}\n"
        )

    def _quantities_section(self) -> str:
        by_material: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))
        missing = 0
        for bar in self.model.bars.values():
            length = self._bar_length(bar)
            mass = self._mass_per_meter(bar)
            entry = by_material[bar.material or "--"][profile_label(bar)]
            entry[0] += length
            if mass is None:
                missing += 1
            else:
                entry[1] += mass * length
        parts = ["\\section{Quantitativo de material}"]
        if not by_material:
            parts.append("O modelo não possui barras.")
            return "\n".join(parts) + "\n"
        rows = []
        total_length = total_mass = 0.0
        for material, profiles in sorted(by_material.items()):
            first = True
            subtotal_length = subtotal_mass = 0.0
            for profile, (length, mass, _count) in sorted(profiles.items()):
                rows.append(
                    f"{tex_escape(material) if first else ''} & {tex_escape(profile)} & "
                    f"{number(length, 2)} & {number(mass, 2)}\\\\"
                )
                first = False
                subtotal_length += length
                subtotal_mass += mass
            rows.append(
                f"\\cmidrule(l){{2-4}}\n & \\textit{{Subtotal}} & \\textit{{{number(subtotal_length, 2)}}} & "
                f"\\textit{{{number(subtotal_mass, 2)}}}\\\\\n\\midrule"
            )
            total_length += subtotal_length
            total_mass += subtotal_mass
        rows[-1] = rows[-1].removesuffix("\n\\midrule")
        rows.append(
            f"\\midrule\n\\textbf{{Total geral}} & & \\textbf{{{number(total_length, 2)}}} & "
            f"\\textbf{{{number(total_mass, 2)}}}\\\\"
        )
        parts.append(
            "Comprimentos medidos entre nós do modelo e pesos calculados com a massa linear de cada seção.\n"
            "{\\small\n\\begin{longtable}{llrr}\n\\caption{Comprimento e peso por perfil}\\\\\n\\toprule\n"
            "Material & Perfil & Comprimento (m) & Peso (kg)\\\\\n\\midrule\n\\endfirsthead\n"
            "\\toprule\nMaterial & Perfil & Comprimento (m) & Peso (kg)\\\\\n\\midrule\n\\endhead\n"
            "\\bottomrule\n\\endfoot\n" + "\n".join(rows) + "\n\\end{longtable}\n}"
        )
        coordinates = self._coordinates()
        area = float(np.ptp(coordinates[:, 0]) * np.ptp(coordinates[:, 1])) if len(coordinates) else 0.0
        note = (
            f"A estrutura pesa cerca de {unit(total_mass / 1000.0, 't', 1)} para uma área em planta de "
            f"aproximadamente {unit(area, 'm$^2$', 0)}, ou seja, $\\approx$ {unit(total_mass / area, 'kg/m$^2$', 1)}. "
            if area > 1e-6 and total_mass > 0 else ""
        )
        parts.append(
            note + "Os pesos não incluem chapas de ligação, parafusos, soldas nem acréscimo para perdas."
            + (f" {missing} barras não têm massa linear calculável e ficaram com peso nulo." if missing else "")
        )
        return "\n".join(parts) + "\n"

    def _conclusions_section(self) -> str:
        items = []
        _by_profile, elements = self._ultimate_rows()
        if elements:
            failed = [item for item in elements if self._fails(item)]
            worst = max((item[2] for item in elements if item[2] is not None), default=None)
            if failed:
                items.append(
                    f"{len(failed)} elementos não atendem ao ELU e precisam ser revistos "
                    "(ver Tabela~\\ref{tab:elu} e a lista de elementos reprovados)."
                )
            else:
                items.append(
                    "Todas as barras verificadas atendem ao ELU da ABNT NBR 8800:2024"
                    + (f". O maior aproveitamento é {percent(worst)}." if worst is not None else ".")
                )
        else:
            items.append("A verificação das barras no ELU deve ser executada antes da emissão final deste laudo.")
        if self.results:
            items.append(
                "Os deslocamentos da Tabela~\\ref{tab:els} devem ser comparados aos limites da Seção~\\ref{sec:els-criterios} "
                "conforme o uso de cada elemento."
            )
        items.append(
            "Ligações, placas de base, chumbadores e fundações não fazem parte deste laudo e devem ser "
            "dimensionados com as reações do modelo."
        )
        items.append("Qualquer acréscimo de carga em relação ao considerado exige nova verificação.")
        body = "\n".join(f"  \\item {item}" for item in items)
        return f"\\section{{Conclusões e recomendações}}\n\\begin{{enumerate}}\n{body}\n\\end{{enumerate}}\n"


def default_deformed_combinations(model) -> tuple[str, ...]:
    """Combinações de serviço com resultado (ou características, ou todas), até o limite de figuras."""
    available = {result.load_reference for result in getattr(model, "analysis_results", ())}
    combinations = [item for item in model.load_combinations.values() if item.name in available]
    chosen = (
        [item.name for item in combinations if item.limit_state == "ELS"]
        or [item.name for item in combinations if item.limit_state == "CAR"]
        or [item.name for item in combinations]
        or sorted(available)
    )
    return tuple(chosen[:MAX_DEFORMED_FIGURES])


def export_structure_report(
    model,
    destination: str | Path,
    options: ReportOptions | None = None,
    *,
    compile_pdf: bool = True,
    progress: Callable[[str], None] | None = None,
    cover_support_mesh=None,
    cover_model_image=None,
) -> ReportExport:
    """Gera o laudo.

    ``destination`` terminado em ``.pdf``: o projeto LaTeX vai para a pasta
    ``<nome>_latex`` ao lado e o PDF compilado é copiado para o destino.
    ``destination`` terminado em ``.tex``: grava o projeto naquela pasta e
    compila apenas se ``compile_pdf`` for verdadeiro.
    """
    destination = Path(destination)
    as_pdf = destination.suffix.lower() == ".pdf"
    folder = destination.with_name(f"{destination.stem}_latex") if as_pdf else destination.parent
    tex_path = StructureReportBuilder(
        model, options, cover_support_mesh=cover_support_mesh,
        cover_model_image=cover_model_image,
    ).build(folder, progress)
    if not as_pdf:
        tex_path = tex_path.replace(destination) if tex_path != destination else tex_path
    export = ReportExport(tex_path=tex_path)
    if not (as_pdf or compile_pdf):
        return export
    engine = find_latex_engine()
    export.engine = engine
    if engine is None:
        export.error = (
            "Nenhum compilador LaTeX foi encontrado (pdflatex, lualatex, xelatex ou tectonic). "
            f"O projeto LaTeX foi salvo em {folder} para compilar depois (por exemplo, no Overleaf)."
        )
        return export
    if progress:
        progress("Compilando o PDF")
    try:
        pdf = compile_latex(tex_path, engine)
    except LatexCompilationError as exc:
        export.error = str(exc)
        return export
    clean_auxiliary_files(tex_path)
    if as_pdf:
        shutil.copyfile(pdf, destination)
        export.pdf_path = destination
    else:
        export.pdf_path = pdf
    return export
