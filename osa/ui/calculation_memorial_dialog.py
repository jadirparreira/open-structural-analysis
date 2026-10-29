"""Calculation memorial input fields for a structural member or group."""

import re
from html import escape
from math import isinf

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QTextBlockFormat, QTextCharFormat
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .math_equations import (
    EQUATION_OBJECT_TYPE,
    EQUATION_SVG_PROPERTY,
    SvgEquationObject,
    equation_svg,
)
from .memorial_docx_export import export_calculation_memorial_docx


class MemorialExportSuccessDialog(QDialog):
    """Compact success confirmation matching the detailing DXF export dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(360)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QLabel { color: #24292f; }"
            "QPushButton#closeProperties { min-height: 34px; padding: 4px 14px; "
            "border: 1px solid #d0d7de; border-radius: 7px; color: #24292f; background: #f6f8fa; }"
            "QPushButton#closeProperties:hover { background: #eaeef2; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(16)
        message = QLabel("Memorial exportado com sucesso")
        message.setWordWrap(False)
        layout.addWidget(message)
        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setObjectName("closeProperties")
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)
        self.adjustSize()


class CalculationMemorialDialog(QDialog):
    def __init__(self, memory: dict | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Memorial de cálculo")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(700, 540)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QLabel#windowTitle { color: #24292f; font-size: 13px; font-weight: 600; }"
            "QTextBrowser#calculationMemory { border: 0; border-left: 1px solid #d0d7de; "
            "border-right: 1px solid #d0d7de; background: #ffffff; color: #24292f; "
            "padding: 10px 16px; selection-background-color: #ddf4ff; }"
            "QPushButton#closeProperties, QPushButton#exportMemorial { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de; "
            "border-radius: 7px; color: #24292f; background: #f6f8fa; }"
            "QPushButton#closeProperties:hover, QPushButton#exportMemorial:hover { background: #eaeef2; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        titlebar = QFrame()
        titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar)
        titlebar_layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel("Memorial de cálculo")
        title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title)
        titlebar_layout.addStretch()
        outer.addWidget(titlebar)
        self.content = QTextBrowser()
        self.content.setObjectName("calculationMemory")
        self.content.setOpenExternalLinks(False)
        equation_objects: dict[str, bytes] = {}
        self._equation_latex: dict[str, str] = {}
        html = self._render(
            memory or {}, equation_objects,
            max_equation_width=max(250.0, float(self.width() - 56)),
            equation_latex=self._equation_latex,
        )
        self._memorial_html = html
        self.content.setHtml(html)
        document = self.content.document()
        text_option = document.defaultTextOption()
        text_option.setAlignment(Qt.AlignmentFlag.AlignLeft)
        document.setDefaultTextOption(text_option)
        self._equation_handler = SvgEquationObject(self.content)
        document.documentLayout().registerHandler(EQUATION_OBJECT_TYPE, self._equation_handler)
        for marker, svg_data in equation_objects.items():
            cursor = document.find(marker)
            if cursor.isNull():
                continue
            text_format = QTextCharFormat()
            text_format.setObjectType(EQUATION_OBJECT_TYPE)
            text_format.setProperty(EQUATION_SVG_PROPERTY, QByteArray(svg_data))
            cursor.insertText("\uFFFC", text_format)
            block_format = QTextBlockFormat(cursor.blockFormat())
            block_format.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            block_format.setLeftMargin(0.0)
            block_format.setRightMargin(0.0)
            block_format.setTextIndent(0.0)
            cursor.setBlockFormat(block_format)
        outer.addWidget(self.content, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 8, 16, 12)
        export_button = QPushButton("Exportar")
        export_button.setObjectName("exportMemorial")
        export_button.clicked.connect(self._export_docx)
        footer.addWidget(export_button)
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setObjectName("closeProperties")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        outer.addLayout(footer)

    @staticmethod
    def _render(
        memory: dict,
        equation_objects: dict[str, bytes] | None = None,
        max_equation_width: float = 644.0,
        equation_latex: dict[str, str] | None = None,
    ) -> str:
        equation_objects = equation_objects if equation_objects is not None else {}
        equation_latex = equation_latex if equation_latex is not None else {}

        def formatted(value, unit: str = "") -> str:
            if value is None or value == "":
                return "—"
            try:
                result = (
                    "∞" if isinf(float(value)) else
                    f"{float(value):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
                )
                if "," in result:
                    result = result.rstrip("0").rstrip(",")
            except (TypeError, ValueError):
                result = str(value)
            return f"{result} {unit}" if unit else result

        def row(label: str, value: object) -> str:
            text = value if isinstance(value, str) else str(value) if value is not None else "—"
            return (
                "<tr>"
                f'<td style="padding:8px 18px 8px 0;color:#57606a;font-weight:700">{escape(label)}</td>'
                f'<td style="padding:8px 0;color:#57606a">{escape(text or "—")}</td>'
                "</tr>"
            )

        geometry = memory.get("geometric_parameters", {})
        material = memory.get("material_parameters", {})
        verification_summary = memory.get("verification_summary") or {}
        scope_warnings = verification_summary.get("scope_warnings", ())
        torsion_summary = verification_summary.get("torsion_summary") or {}
        biaxial_shear_summary = verification_summary.get("biaxial_shear_summary") or {}
        slenderness_summary = verification_summary.get("slenderness_summary") or {}
        axial_tension = memory.get("axial_tension", {})
        axial_compression = memory.get("axial_compression", {})
        flexion_y = memory.get("flexion_y", {})
        flexion_z = memory.get("flexion_z", {})
        shear_y = memory.get("shear_y", {})
        section_rows = [
            ("Altura total (d)", formatted(geometry.get("d_mm"), "mm")),
            ("Largura da mesa (bf)", formatted(geometry.get("bf_mm"), "mm")),
            ("Espessura da alma (tw)", formatted(geometry.get("tw_mm"), "mm")),
            ("Espessura da mesa (tf)", formatted(geometry.get("tf_mm"), "mm")),
            ("Momento de inércia em Y (Iy)", formatted(geometry.get("Iy_cm4"), "cm⁴")),
            ("Módulo resistente elástico em Y (Wy)", formatted(geometry.get("Wy_cm3"), "cm³")),
            ("Raio de giração em Y (ry)", formatted(geometry.get("ry_cm"), "cm")),
            ("Módulo resistente plástico em Y (Zy)", formatted(geometry.get("Zy_cm3"), "cm³")),
            ("Momento de inércia em Z (Iz)", formatted(geometry.get("Iz_cm4"), "cm⁴")),
            ("Módulo resistente elástico em Z (Wz)", formatted(geometry.get("Wz_cm3"), "cm³")),
            ("Raio de giração em Z (Rz)", formatted(geometry.get("Rz_cm"), "cm")),
            ("Módulo resistente plástico em Z (Zz)", formatted(geometry.get("Zz_cm3"), "cm³")),
            ("Área bruta (Ag)", formatted(geometry.get("Ag_cm2"), "cm²")),
            ("Raio de giração para torção (rt)", formatted(geometry.get("rt_cm"), "cm")),
            ("Constante de torção (It)", formatted(geometry.get("It_cm4"), "cm⁴")),
            ("Constante de empenamento (Cw)", formatted(geometry.get("Cw_cm6"), "cm⁶")),
            ("Comprimento destravado em Y (Ly)", formatted(geometry.get("Ly_cm"), "cm")),
            ("Comprimento destravado em Z (Lz)", formatted(geometry.get("Lz_cm"), "cm")),
            ("Comprimento destravado à torção (Lt)", formatted(geometry.get("Lt_cm"), "cm")),
            ("Comprimento destravado à flexão (Lb)", formatted(geometry.get("Lb_cm"), "cm")),
        ]
        if memory.get("profile_type") in {"W Laminado", "HP Laminado"}:
            section_rows.insert(4, ("Raio de concordância adotado (r)", formatted(geometry.get("r_mm"), "mm")))
        if memory.get("profile_type") == "L Laminado":
            section_rows[:4] = [
                ("Aba (b)", formatted(geometry.get("b_mm"), "mm")),
                ("Espessura (t)", formatted(geometry.get("t_mm"), "mm")),
            ]
            section_rows[13] = (
                "Raio polar ao centro de cisalhamento (r₀)",
                formatted(geometry.get("rt_cm"), "cm"),
            )
        elif memory.get("profile_type") == "Barra Retangular":
            section_rows[:4] = [
                ("Largura (b)", formatted(geometry.get("b_mm"), "mm")),
                ("Altura (h)", formatted(geometry.get("h_mm"), "mm")),
            ]
        elif memory.get("profile_type") == "Barra Quadrada":
            section_rows[:4] = [
                ("Lado (b)", formatted(geometry.get("b_mm"), "mm")),
            ]
        elif memory.get("profile_type") == "Barra Circular":
            section_rows[:4] = [
                ("Diâmetro (d)", formatted(geometry.get("d_mm"), "mm")),
            ]
        material_rows = [
            ("Tipo de material", material.get("type", "—")),
            ("Módulo de elasticidade (E)", formatted(material.get("E_kn_m2"), "kN/m²")),
            ("Módulo de cisalhamento (G)", formatted(material.get("G_kn_m2"), "kN/m²")),
            ("Coeficiente de Poisson (ν)", formatted(material.get("poisson"))),
            ("Peso específico", formatted(material.get("unit_weight_kn_m3"), "kN/m³")),
            ("Tensão de escoamento (fy)", formatted(material.get("fy_kn_m2"), "kN/m²")),
            ("Tensão de ruptura (fu)", formatted(material.get("fu_kn_m2"), "kN/m²")),
        ]
        verification = axial_tension.get("verification") or {}
        parameters = verification.get("parameters", {})

        def decimal(value, places: int = 3) -> str:
            if value is None:
                return "—"
            result = f"{float(value):,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return result.rstrip("0").rstrip(",") if "," in result else result

        def equation_width(latex: str) -> float | None:
            svg_data = equation_svg(latex)
            if svg_data is None:
                return None
            match = re.search(rb'<svg[^>]*viewBox="0 0 ([\d.]+) ([\d.]+)"', svg_data)
            if match is None:
                return None
            # Qt lays out the SVG object at the viewBox width; converting it
            # from points here would count the SVG scaling a second time.
            return float(match.group(1))

        def wrap_equation(latex: str) -> tuple[str, ...]:
            """Split an overlong equation after an equality, keeping each part on its own row."""
            pending = [latex]
            wrapped: list[str] = []
            while pending:
                part = pending.pop(0)
                width = equation_width(part)
                if width is None or width <= max_equation_width:
                    wrapped.append(part)
                    continue

                # Only split equals signs outside LaTeX groups, so fractions and
                # subscripts remain intact. Prefer the last equality that fits.
                candidates: list[tuple[int, int]] = []
                depth = 0
                index = 0
                while index < len(part):
                    char = part[index]
                    if char == "{":
                        depth += 1
                    elif char == "}":
                        depth = max(0, depth - 1)
                    elif depth == 0 and part.startswith(" = ", index):
                        candidates.append((index, index + 3))
                        index += 2
                    index += 1
                fitting = []
                for candidate in candidates:
                    prefix_width = equation_width(part[:candidate[1] - 1])
                    if prefix_width is not None and prefix_width <= max_equation_width:
                        fitting.append(candidate)
                if not fitting:
                    wrapped.append(part)
                    continue
                _, split_end = fitting[-1]
                left = part[:split_end - 1].rstrip()
                right = part[split_end:].lstrip()
                wrapped.append(left)
                pending.insert(0, "= " + right)
            return tuple(wrapped)

        def equation(
            latex_lines: tuple[str, ...],
            fallback: str,
            indent_continuations: bool = True,
        ) -> str:
            rendered_lines = []
            expanded_lines = tuple(
                part for latex in latex_lines for part in wrap_equation(latex)
            )
            for index, latex in enumerate(expanded_lines):
                svg_data = equation_svg(latex)
                if svg_data is None:
                    status_match = re.search(r"\b(APROVADO|REPROVADO)\b", fallback)
                    if status_match:
                        start, end = status_match.span()
                        return (
                            escape(fallback[:start])
                            + f"<b>{status_match.group(1)}</b>"
                            + escape(fallback[end:])
                        )
                    return escape(fallback)
                marker = f"OSA_EQUATION_OBJECT_{len(equation_objects):04d}_END"
                equation_objects[marker] = svg_data
                equation_latex[marker] = latex
                indent = "&nbsp;&nbsp;&nbsp;&nbsp;" if index and indent_continuations else ""
                rendered_lines.append(f"{indent}{marker}")
            return "<br/>".join(rendered_lines)

        def equation_triplet(variable: str, formula: str, substituted: str,
                             result: str, unit: str = "") -> tuple[str, ...]:
            result_with_unit = rf"{result}\,\mathrm{{{unit}}}" if unit else result
            return (rf"{variable} = {formula} = {substituted} = {result_with_unit}",)

        equation_names = {
            r"A_e": "Área líquida efetiva",
            r"A_w": "Área efetiva de cisalhamento",
            r"A_{ef}": "Área efetiva da seção transversal",
            r"M_p": "Momento fletor de plastificação",
            r"M_r": "Momento fletor de início de escoamento",
            r"M_{cr}": "Momento crítico elástico",
            r"M_{Rd,FLA}": "Momento resistente de cálculo por flambagem local da alma",
            r"M_{Rd,FLM}": "Momento resistente de cálculo por flambagem local da mesa",
            r"M_{Rd,FLM,Z}": "Momento resistente de cálculo por flambagem local da mesa em Z",
            r"M_{Rd,FLT}": "Momento resistente de cálculo por flambagem lateral com torção",
            r"M_{Rd,max}": "Limite máximo do momento resistente de cálculo",
            r"M_{Rd,max,Z}": "Limite máximo do momento resistente de cálculo em Z",
            r"M_{cr,FLM}": "Momento crítico elástico por flambagem local da mesa",
            r"M_{cr,FLM,Z}": "Momento crítico elástico por flambagem local da mesa em Z",
            r"M_{cr,FLT}": "Momento crítico elástico por flambagem lateral com torção",
            r"M_{n,FLA}": "Momento nominal por flambagem local da alma",
            r"M_{n,FLM}": "Momento nominal por flambagem local da mesa",
            r"M_{n,FLM,Z}": "Momento nominal por flambagem local da mesa em Z",
            r"M_{n,FLT}": "Momento nominal por flambagem lateral com torção",
            r"M_{p,Z}": "Momento de plastificação em Z",
            r"M_{r,Z}": "Momento de início de escoamento em Z",
            r"M_{y,Rd}": "Momento resistente de cálculo em Y",
            r"M_{z,Rd}": "Momento resistente de cálculo em Z",
            r"N_e": "Força axial de flambagem global",
            r"N_{c,Rd}": "Força axial resistente de cálculo à compressão",
            r"N_{et}": "Força axial de flambagem por torção",
            r"N_{ey}": "Força axial de flambagem por flexão em Y",
            r"N_{ez}": "Força axial de flambagem por flexão em Z",
            r"N_{t,Rd1}": "Força axial resistente de cálculo por escoamento da seção bruta",
            r"N_{t,Rd2}": "Força axial resistente de cálculo por ruptura da seção líquida efetiva",
            r"N_{t,Rd}": "Força axial resistente de cálculo à tração",
            r"V_{p\ell}": "Força cortante correspondente à plastificação",
            r"V_{y,Rd}": "Força cortante resistente de cálculo em Y",
            r"V_{z,Rd}": "Força cortante resistente de cálculo em Z",
            r"\beta_1": "Parâmetro de esbeltez para flambagem lateral com torção",
            r"\chi": "Fator de redução por flambagem global",
            r"\eta_c": "Taxa de utilização à compressão axial",
            r"\eta_t": "Taxa de utilização à tração axial",
            r"\eta_y": "Taxa de utilização à flexão em Y",
            r"\eta_z": "Taxa de utilização à flexão em Z",
            r"\eta_{v,Y}": "Taxa de utilização à força cortante em Y",
            r"\eta_{v,Z}": "Taxa de utilização à força cortante em Z",
            r"\eta_{V_y,V_z}": "Taxa de utilização dos cortantes simultâneos em Y e Z",
            r"\tau_{y,Sd}": "Tensão solicitante de cisalhamento na mesa",
            r"\tau_{z,Sd}": "Tensão solicitante de cisalhamento na alma",
            r"\tau_{e,y}": "Tensão crítica elástica de cisalhamento na mesa",
            r"\tau_{e,z}": "Tensão crítica elástica de cisalhamento na alma sem enrijecedores",
            r"\lambda_y": "Índice de esbeltez da barra no eixo Y",
            r"\lambda_z": "Índice de esbeltez da barra no eixo Z",
            r"\tau_{Rd}": "Tensão resistente de cálculo ao cisalhamento",
            r"\tau_{Sd}": "Tensão resultante (envelope conservador dos máximos na mesa e na alma)",
            r"\lambda_{0,y}": "Índice de esbeltez reduzido da mesa ao cisalhamento",
            r"\lambda_{0,z}": "Índice de esbeltez reduzido da alma ao cisalhamento",
            r"\chi_y": "Fator de redução por instabilidade da mesa ao cisalhamento",
            r"\chi_z": "Fator de redução por instabilidade da alma ao cisalhamento",
            r"\chi_V": "Fator de redução governante ao cisalhamento",
            r"\eta_{ob}": "Taxa de utilização à flexão oblíqua",
            r"\eta_{int}": "Taxa de utilização da interação entre força axial e flexão",
            r"\lambda_0": "Índice de esbeltez reduzido",
            r"\lambda_Y": "Índice de esbeltez da mesa para cortante em Y",
            r"\lambda_Z": "Índice de esbeltez da alma para cortante em Z",
            r"\lambda_{AA}": "Índice de esbeltez do elemento AA (alma)",
            r"\lambda_{AL}": "Índice de esbeltez do elemento AL (mesa)",
            r"\lambda_{FLA}": "Índice de esbeltez para flambagem local da alma",
            r"\lambda_{FLM,Z}": "Índice de esbeltez para flambagem local da mesa em Z",
            r"\lambda_{FLM}": "Índice de esbeltez para flambagem local da mesa",
            r"\lambda_{FLT}": "Índice de esbeltez para flambagem lateral com torção",
            r"\lambda_{lim,AA}": "Limite de esbeltez do elemento AA (alma)",
            r"\lambda_{lim,AL}": "Limite de esbeltez do elemento AL (mesa)",
            r"\lambda_{p,FLA}": "Limite de esbeltez para plastificação da alma",
            r"\lambda_{p,FLM,Z}": "Limite de esbeltez para plastificação da mesa em Z",
            r"\lambda_{p,FLM}": "Limite de esbeltez para plastificação da mesa",
            r"\lambda_{p,FLT}": "Limite de esbeltez para plastificação por FLT",
            r"\lambda_{p,Y}": "Limite de esbeltez para cortante em Y",
            r"\lambda_{p,Z}": "Limite de esbeltez para cortante em Z",
            r"\lambda_{r,FLA}": "Limite de esbeltez para flambagem elástica da alma",
            r"\lambda_{r,FLM,Z}": "Limite de esbeltez para flambagem elástica da mesa em Z",
            r"\lambda_{r,FLM}": "Limite de esbeltez para flambagem elástica da mesa",
            r"\lambda_{r,FLT}": "Limite de esbeltez para flambagem elástica por FLT",
            r"\lambda_{r,Y}": "Limite superior de esbeltez para cortante em Y",
            r"\lambda_{r,Z}": "Limite superior de esbeltez para cortante em Z",
            r"\lambda_{red,AA}": "Limite reduzido de esbeltez do elemento AA (alma)",
            r"\lambda_{red,AL}": "Limite reduzido de esbeltez do elemento AL (mesa)",
            r"\sigma_r": "Tensão residual",
            r"\sigma_{el,AA}": "Tensão crítica elástica do elemento AA (alma)",
            r"\sigma_{el,AL}": "Tensão crítica elástica do elemento AL (mesa)",
            r"b_{ef,f}": "Largura efetiva da mesa comprimida",
            r"b_{f,aba}": "Largura da aba da mesa",
            r"d_{ef}": "Altura efetiva da alma",
        }

        def equation_reference(variable: str) -> str:
            if variable in {r"\tau_{y,Sd}", r"\tau_{z,Sd}", r"\tau_{Sd}",
                            r"\tau_{Rd}", r"\eta_{V_y,V_z}"}:
                return "5.5.1.3; 5.5.2.3(b), (d)"
            if variable in {r"\tau_{e,y}", r"\tau_{e,z}"}:
                return "5.4.3.1.1 e 5.4.3.5"
            if variable in {r"\lambda_y", r"\lambda_z"}:
                return "5.2.8.1 e 5.3.7.1"
            if variable in {r"\lambda_{0,y}", r"\lambda_{0,z}",
                            r"\chi_y", r"\chi_z", r"\chi_V"}:
                return "5.3.3.1–.2; 5.5.2.3(d)"
            if variable == r"A_e":
                return "5.2.3"
            if variable in {r"N_{t,Rd1}", r"N_{t,Rd2}", r"N_{t,Rd}"}:
                return "5.2.2"
            if variable == r"\eta_t":
                return "5.2.1.2"
            if variable in {r"N_{ey}", r"N_{ez}", r"N_{et}", r"N_e"}:
                return "5.3.5.1"
            if variable == r"\lambda_0":
                return "5.3.3.2"
            if variable == r"\chi":
                return "5.3.3.1"
            if variable == r"N_{c,Rd}" or variable == r"\eta_c":
                return "5.3.2"
            if variable in {
                r"A_{ef}", r"\lambda_{AA}", r"\lambda_{AL}",
                r"\lambda_{lim,AA}", r"\lambda_{lim,AL}",
                r"\lambda_{red,AA}", r"\lambda_{red,AL}",
                r"\sigma_{el,AA}", r"\sigma_{el,AL}", r"b_{ef,f}",
                r"b_{f,aba}", r"d_{ef}",
            }:
                return "5.3.4; Tabelas 4 e 5"
            if variable == r"A_w":
                return "5.4.3.1.2 e 5.4.3.5"
            if variable == r"V_{p\ell}":
                return "5.4.3.1.2 e 5.4.3.5"
            if variable in {r"V_{z,Rd}",
                            r"\lambda_Z", r"\lambda_{p,Z}", r"\lambda_{r,Z}"}:
                return "5.4.3.1.1–1.2"
            if variable in {r"V_{y,Rd}", r"\lambda_Y", r"\lambda_{p,Y}", r"\lambda_{r,Y}"}:
                return "5.4.3.5"
            if variable in {r"\eta_{v,Y}"}:
                return "5.4.3.5"
            if variable in {r"\eta_{v,Z}"}:
                return "5.4.3.1.1–1.2"
            if variable in {r"\eta_{ob}", r"\eta_{int}"}:
                return "5.5.1.2"
            if variable in {r"M_{Rd,max}", r"M_{Rd,max,Z}"}:
                return "5.4.2.2"
            if "FLT" in variable:
                return "5.4.2.1; Anexo D, D.2.1 e D.2.8-a"
            if "FLA" in variable:
                return "5.4.2.1; Anexo D, D.2.3 e D.2.8-h"
            if "FLM,Z" in variable:
                return "5.4.2.1; Anexo D, D.2.2, D.2.8-f e h"
            if "FLM" in variable:
                return "5.4.2.1; Anexo D, D.2.2 e D.2.8-f"
            if variable.startswith("M_"):
                return "5.4.2.1; Anexo D, Tabela D.1"
            if variable in {r"\beta_1", r"\lambda_{FLT}", r"\lambda_{p,FLT}",
                            r"\lambda_{r,FLT}"}:
                return "5.4.2.1; Anexo D, D.2.1 e D.2.8-a"
            if variable in {r"\lambda_{FLM}", r"\lambda_{p,FLM}",
                            r"\lambda_{r,FLM}"}:
                return "5.4.2.1; Anexo D, D.2.2 e D.2.8-f"
            if variable in {r"\lambda_{FLA}", r"\lambda_{p,FLA}",
                            r"\lambda_{r,FLA}"}:
                return "5.4.2.1; Anexo D, D.2.3 e D.2.8-h"
            if variable in {r"\lambda_{FLM,Z}", r"\lambda_{p,FLM,Z}",
                            r"\lambda_{r,FLM,Z}", r"\sigma_r"}:
                return "5.4.2.1; Anexo D, D.2.2, D.2.8-f e h"
            if variable in {r"\eta_y", r"\eta_z"}:
                return "5.4.2.1"
            return "5.4.2.1; Anexo D"

        def spaced_equations(latex_lines: tuple[str, ...], fallback: str = "",
                             spacing_px: int = 10,
                             named: bool = True) -> str:
            rendered = []
            for latex_line in latex_lines:
                variable = latex_line.split(" = ", 1)[0].strip()
                name = equation_names.get(variable, "Equação de verificação")
                if named:
                    rendered.append(
                        f'<p style="margin:0 0 2px;color:#57606a">'
                        f'{escape(name)} ({escape(equation_reference(variable))})</p>'
                    )
                rendered.append(
                    f'<p align="center" style="margin:0 0 {spacing_px}px;padding-left:0;text-indent:0;'
                    f'color:#57606a;text-align:center">'
                    f'{equation((latex_line,), fallback, indent_continuations=False)}</p>'
                )
            return "".join(rendered)

        slenderness_content = ""
        if memory.get("profile_type") in {"W Laminado", "HP Laminado"}:
            slenderness_status = slenderness_summary.get("status")
            slenderness_content = (
                '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">'
                'Limite de esbeltez — ABNT NBR 8800:2024, 5.2.8.1 e 5.3.7.1–5.3.7.2</p>'
            )
            if slenderness_status == "checked":
                p = slenderness_summary.get("parameters") or {}
                lambda_y = p.get("lambda_y")
                lambda_z = p.get("lambda_z")
                slenderness_lines = (
                    *equation_triplet(
                        r"\lambda_y", r"\dfrac{L_y}{r_y}",
                        rf"\dfrac{{{decimal(p.get('Ly_cm'))}}}{{{decimal(p.get('ry_cm'))}}}",
                        decimal(lambda_y),
                    ),
                    *equation_triplet(
                        r"\lambda_z", r"\dfrac{L_z}{r_z}",
                        rf"\dfrac{{{decimal(p.get('Lz_cm'))}}}{{{decimal(p.get('rz_cm'))}}}",
                        decimal(lambda_z),
                    ),
                )
                slenderness_content += spaced_equations(slenderness_lines, spacing_px=7)

                def recommendation(label: str, value: float, limit: float) -> str:
                    if value <= limit:
                        status = "dentro do limite recomendado"
                    else:
                        status = "acima do limite recomendado"
                    return (
                        '<p align="center" style="margin:0 0 3px;color:#57606a;text-align:center">'
                        f'{escape(label)} = {decimal(value)}; limite recomendado = '
                        f'{decimal(limit)} — {escape(status)}.</p>'
                    )

                slenderness_content += (
                    '<p style="margin:7px 0 3px;color:#57606a">'
                    'Esbeltez na tração</p>'
                    + recommendation("λy", lambda_y, p.get("tension_limit"))
                    + recommendation("λz", lambda_z, p.get("tension_limit"))
                    + '<p style="margin:7px 0 3px;color:#57606a">'
                    'Esbeltez na compressão</p>'
                    + recommendation("λy", lambda_y, p.get("compression_limit"))
                    + recommendation("λz", lambda_z, p.get("compression_limit"))
                )
            else:
                slenderness_content += (
                    '<p style="margin:5px 0;color:#57606a">Não foi possível determinar os índices: '
                    f'{escape(str(slenderness_summary.get("detail", "dados indisponíveis")))}.</p>'
                )

        axial_tension_content = (
            '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">Tração axial — ABNT NBR 8800:2024, 5.2</p>'
        )
        if verification.get("status") == "checked":
            ag = parameters.get("Ag_cm2")
            an = parameters.get("An_cm2")
            ae = parameters.get("Ae_cm2")
            ct = parameters.get("Ct")
            fy = parameters.get("fy_kn_cm2")
            fu = parameters.get("fu_kn_cm2")
            gamma_a1 = parameters.get("gamma_a1")
            gamma_a2 = parameters.get("gamma_a2")
            nrd1 = parameters.get("Nt_Rd1_kn")
            nrd2 = parameters.get("Nt_Rd2_kn")
            nrd = parameters.get("Nt_Rd_kn")
            checks = [
                (
                    "Área efetiva da seção transversal",
                    equation_triplet(
                        r"A_e", r"C_t \cdot A_n",
                        rf"{decimal(ct, 2)} \cdot {decimal(an)}",
                        decimal(ae), r"cm^2",
                    ),
                ),
                (
                    "Escoamento da seção bruta",
                    equation_triplet(
                        r"N_{t,Rd1}", r"\dfrac{A_g \cdot f_y}{\gamma_{a1}}",
                        rf"\dfrac{{{decimal(ag)} \cdot {decimal(fy)}}}{{{decimal(gamma_a1, 2)}}}",
                        decimal(nrd1), r"kN",
                    ),
                ),
                (
                    "Ruptura da seção líquida efetiva",
                    equation_triplet(
                        r"N_{t,Rd2}", r"\dfrac{A_e \cdot f_u}{\gamma_{a2}}",
                        rf"\dfrac{{{decimal(ae)} \cdot {decimal(fu)}}}{{{decimal(gamma_a2, 2)}}}",
                        decimal(nrd2), r"kN",
                    ),
                ),
                (
                    "Força axial resistente de cálculo à tração",
                    equation_triplet(
                        r"N_{t,Rd}", r"\min(N_{t,Rd1};\,N_{t,Rd2})",
                        rf"\min({decimal(nrd1)};\,{decimal(nrd2)})",
                        decimal(nrd), r"kN",
                    ),
                ),
            ]
            applied = verification.get("applied_kn")
            utilization = verification.get("utilization")
            combination_name = escape(str(verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            for index, (check_name, latex_lines) in enumerate(checks):
                top_spacing = "0" if index == 0 else "18px"
                variable = latex_lines[0].split(" = ", 1)[0].strip()
                axial_tension_content += (
                    f'<p style="margin:{top_spacing} 0 3px;color:#57606a">'
                    f'{escape(check_name)} ({escape(equation_reference(variable))})</p>'
                    f'{spaced_equations(latex_lines, named=False)}'
                )
            utilization_latex_lines = (
                *equation_triplet(
                    r"\eta_t", r"\dfrac{N_{t,Sd}}{N_{t,Rd}}",
                    rf"\dfrac{{{decimal(applied)}}}{{{decimal(nrd)}}}",
                    rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
                ),
            )
            utilization_fallback = (
                f"Nt,Sd / Nt,Rd = {decimal(applied)} / {decimal(nrd)} "
                f"= {decimal(utilization * 100.0, 2)} % {status}"
            )
            axial_tension_content += (
                f'{spaced_equations(utilization_latex_lines, utilization_fallback)}'
                f'<p style="margin:0 0 3px;color:#57606a">'
                f'Combinação governante: {combination_name}</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            axial_tension_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de tração axial atende somente a perfis W, I e U Laminados."
                "</p>"
            )
        elif verification.get("status") == "not_checked":
            axial_tension_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif verification.get("status") == "not_applicable":
            axial_tension_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(verification.get("detail", "Sem tração axial.")))}.</p>'
            )
        else:
            axial_tension_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados."
                "</p>"
            )
        compression_verification = axial_compression.get("verification") or {}
        compression_parameters = compression_verification.get("parameters", {})
        axial_compression_content = (
            '<p style="margin:22px 0 12px;color:#57606a;font-weight:700">Compressão axial — ABNT NBR 8800:2024, 5.3</p>'
        )
        if compression_verification.get("status") == "checked" and memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            p = compression_parameters
            axial_compression_content += spaced_equations((
                *equation_triplet(r"N_{ey}", r"\dfrac{\pi^2 E I_y}{L_y^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iy_cm4'))}}}{{{decimal(p.get('Ly_cm'))}^2}}",
                                  decimal(p.get("Ney_kn")), r"kN"),
                *equation_triplet(r"N_{ez}", r"\dfrac{\pi^2 E I_z}{L_z^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iz_cm4'))}}}{{{decimal(p.get('Lz_cm'))}^2}}",
                                  decimal(p.get("Nez_kn")), r"kN"),
                *equation_triplet(r"N_{et}", r"\dfrac{G I_t}{r_0^2}",
                                  rf"\dfrac{{{decimal(p.get('G_kn_cm2'))}\cdot {decimal(p.get('It_cm4'))}}}{{{decimal(p.get('r0_cm'))}^2}}",
                                  decimal(p.get("Net_kn")), r"kN"),
                *equation_triplet(r"N_e", r"\min(N_{ey};N_{ez};N_{et})",
                                  rf"\min({decimal(p.get('Ney_kn'))};{decimal(p.get('Nez_kn'))};{decimal(p.get('Net_kn'))})",
                                  decimal(p.get("Ne_kn")), r"kN"),
                *equation_triplet(r"\lambda_0", r"\sqrt{\dfrac{A_g f_y}{N_e}}",
                                  rf"\sqrt{{\dfrac{{{decimal(p.get('Ag_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('Ne_kn'))}}}}}",
                                  decimal(p.get("lambda0"))),
                *equation_triplet(r"\chi", r"0,658^{\lambda_0^2}\;\mathrm{ou}\;\dfrac{0,877}{\lambda_0^2}",
                                  decimal(p.get("chi")), decimal(p.get("chi"))),
                *equation_triplet(r"N_{c,Rd}", r"\dfrac{\chi A_g f_y}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('chi'))}\cdot {decimal(p.get('Ag_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Nc_Rd_kn")), r"kN"),
            ))
            utilization = compression_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            axial_compression_content += spaced_equations(equation_triplet(
                r"\eta_c", r"\dfrac{N_{c,Sd}}{N_{c,Rd}}",
                rf"\dfrac{{{decimal(compression_verification.get('applied_kn'))}}}{{{decimal(p.get('Nc_Rd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif compression_verification.get("status") == "checked" and memory.get("profile_type") == "T Laminado":
            p = compression_parameters
            axial_compression_content += spaced_equations((
                *equation_triplet(r"N_{ey}", r"\dfrac{\pi^2 E I_y}{L_y^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iy_cm4'))}}}{{{decimal(p.get('Ly_cm'))}^2}}",
                                  decimal(p.get("Ney_kn")), r"kN"),
                *equation_triplet(r"N_{ez}", r"\dfrac{\pi^2 E I_z}{L_z^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iz_cm4'))}}}{{{decimal(p.get('Lz_cm'))}^2}}",
                                  decimal(p.get("Nez_kn")), r"kN"),
                *equation_triplet(r"N_{et}", r"\dfrac{G I_t}{r_0^2}",
                                  rf"\dfrac{{{decimal(p.get('G_kn_cm2'))}\cdot {decimal(p.get('It_cm4'))}}}{{{decimal(p.get('r0_cm'))}^2}}",
                                  decimal(p.get("Net_kn")), r"kN"),
                *equation_triplet(r"H", r"1-\dfrac{x_0^2}{r_0^2}",
                                  rf"1-\dfrac{{{decimal(p.get('x0_cm'))}^2}}{{{decimal(p.get('r0_cm'))}^2}}",
                                  decimal(p.get("H_flexotorsion"))),
                *equation_triplet(r"N_{eyz}", r"\dfrac{N_{ez}+N_{et}}{2H}\left(1-\sqrt{1-\dfrac{4N_{ez}N_{et}H}{(N_{ez}+N_{et})^2}}\right)",
                                  decimal(p.get("Ne_flexotorsao_kn")), decimal(p.get("Ne_flexotorsao_kn")), r"kN"),
                *equation_triplet(r"N_e", r"\min(N_{ey};N_{eyz})",
                                  rf"\min({decimal(p.get('Ney_kn'))};{decimal(p.get('Ne_flexotorsao_kn'))})",
                                  decimal(p.get("Ne_kn")), r"kN"),
                *equation_triplet(r"\lambda_0", r"\sqrt{\dfrac{A_g f_y}{N_e}}",
                                  rf"\sqrt{{\dfrac{{{decimal(p.get('Ag_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('Ne_kn'))}}}}}",
                                  decimal(p.get("lambda0"))),
                *equation_triplet(r"\chi", r"0,658^{\lambda_0^2}\;\mathrm{ou}\;\dfrac{0,877}{\lambda_0^2}",
                                  decimal(p.get("chi")), decimal(p.get("chi"))),
                *equation_triplet(r"\lambda_{AL,f}", r"\dfrac{(b_f-t_w)/2}{t_f}",
                                  rf"\dfrac{{({decimal(p.get('bf_mm'))}-{decimal(p.get('tw_mm'))})/2}}{{{decimal(p.get('tf_mm'))}}}",
                                  decimal(p.get("flange_slenderness"))),
                *equation_triplet(r"\lambda_{lim,AL,f}", r"0,56\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,56\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("flange_limit"))),
                *equation_triplet(r"\lambda_{AL,w}", r"\dfrac{d-t_f}{t_w}",
                                  rf"\dfrac{{{decimal(p.get('web_width_mm'))}}}{{{decimal(p.get('tw_mm'))}}}",
                                  decimal(p.get("web_slenderness"))),
                *equation_triplet(r"\lambda_{lim,AL,w}", r"0,75\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,75\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("web_limit"))),
                *equation_triplet(r"A_{ef}", r"A_g-2(b_f/2-b_{ef,f})t_f-(d-t_f-b_{ef,w})t_w",
                                  decimal(p.get("Aef_cm2")), decimal(p.get("Aef_cm2")), r"cm^2"),
                *equation_triplet(r"N_{c,Rd}", r"\dfrac{\chi A_{ef}f_y}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('chi'))}\cdot {decimal(p.get('Aef_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Nc_Rd_kn")), r"kN"),
            ))
            applied = compression_verification.get("applied_kn")
            utilization = compression_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            axial_compression_content += spaced_equations(equation_triplet(
                r"\eta_c", r"\dfrac{N_{c,Sd}}{N_{c,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Nc_Rd_kn'))}}}",
                rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif compression_verification.get("status") == "checked" and memory.get("profile_type") == "L Laminado":
            p = compression_parameters
            axial_compression_content += spaced_equations((
                *equation_triplet(r"N_{ey}", r"\dfrac{\pi^2 E I_y}{L_y^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iy_cm4'))}}}{{{decimal(p.get('Ly_cm'))}^2}}",
                                  decimal(p.get("Ney_kn")), r"kN"),
                *equation_triplet(r"N_{ez}", r"\dfrac{\pi^2 E I_z}{L_z^2}",
                                  rf"\dfrac{{\pi^2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Iz_cm4'))}}}{{{decimal(p.get('Lz_cm'))}^2}}",
                                  decimal(p.get("Nez_kn")), r"kN"),
                *equation_triplet(r"N_{et}", r"\dfrac{G I_t}{r_0^2}",
                                  rf"\dfrac{{{decimal(p.get('G_kn_cm2'))}\cdot {decimal(p.get('It_cm4'))}}}{{{decimal(p.get('r0_cm'))}^2}}",
                                  decimal(p.get("Net_kn")), r"kN"),
                *equation_triplet(r"N_{eyt}", r"\dfrac{N_{ey}+N_{et}}{2}\left(1-\sqrt{1-\dfrac{4N_{ey}N_{et}}{(N_{ey}+N_{et})^2}}\right)",
                                  rf"{decimal(p.get('Ne_flexotorsao_kn'))}", decimal(p.get("Ne_flexotorsao_kn")), r"kN"),
                *equation_triplet(r"N_e", r"\min(N_{ez};N_{eyt})",
                                  rf"\min({decimal(p.get('Nez_kn'))};{decimal(p.get('Ne_flexotorsao_kn'))})",
                                  decimal(p.get("Ne_kn")), r"kN"),
                *equation_triplet(r"\lambda_0", r"\sqrt{\dfrac{A_g f_y}{N_e}}",
                                  rf"\sqrt{{\dfrac{{{decimal(p.get('Ag_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('Ne_kn'))}}}}}",
                                  decimal(p.get("lambda0"))),
                *equation_triplet(r"\chi", r"0,658^{\lambda_0^2}\;\mathrm{ou}\;\dfrac{0,877}{\lambda_0^2}",
                                  decimal(p.get("chi")), decimal(p.get("chi"))),
                *equation_triplet(r"\lambda_{AL}", r"\dfrac{b}{t}",
                                  rf"\dfrac{{{decimal(p.get('b_mm'))}}}{{{decimal(p.get('t_mm'))}}}",
                                  decimal(p.get("leg_slenderness"))),
                *equation_triplet(r"\lambda_{lim,AL}", r"0,45\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,45\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("leg_limit"))),
                *equation_triplet(r"\lambda_{red,AL}", r"\dfrac{\lambda_{lim,AL}}{\sqrt{\chi}}",
                                  rf"\dfrac{{{decimal(p.get('leg_limit'))}}}{{\sqrt{{{decimal(p.get('chi'))}}}}}",
                                  decimal(p.get("leg_reduced_limit"))),
                *equation_triplet(r"\sigma_{el,AL}", r"\left(1,49\dfrac{\lambda_{lim,AL}}{\lambda_{AL}}\right)^2 f_y",
                                  decimal(p.get("leg_sigma_el_kn_cm2")), decimal(p.get("leg_sigma_el_kn_cm2")), r"kN/cm^2"),
                *equation_triplet(r"b_{ef}", r"b\;\mathrm{ou}\;b\left(1-0,22\sqrt{\dfrac{\sigma_{el}}{\chi f_y}}\right)\sqrt{\dfrac{\sigma_{el}}{\chi f_y}}",
                                  decimal(p.get("leg_effective_width_mm")),
                                  decimal(p.get("leg_effective_width_mm")), r"mm"),
                *equation_triplet(r"A_{ef}", r"A_g-2(b-b_{ef})t/100",
                                  rf"{decimal(p.get('Ag_cm2'))}-2({decimal(p.get('b_mm'))}-{decimal(p.get('leg_effective_width_mm'))})\cdot {decimal(p.get('t_mm'))}/100",
                                  decimal(p.get("Aef_cm2")), r"cm^2"),
                *equation_triplet(r"N_{c,Rd}", r"\dfrac{\chi A_{ef} f_y}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('chi'))}\cdot {decimal(p.get('Aef_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Nc_Rd_kn")), r"kN"),
            ))
            applied = compression_verification.get("applied_kn")
            utilization = compression_verification.get("utilization")
            status = "APROVADO" if utilization <= 1 else "REPROVADO"
            axial_compression_content += spaced_equations(equation_triplet(
                r"\eta_c", r"\dfrac{N_{c,Sd}}{N_{c,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Nc_Rd_kn'))}}}",
                rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif compression_verification.get("status") == "checked":
            p = compression_parameters
            lt_latex = r"\infty" if isinf(p.get("Lt_cm", 0.0)) else decimal(p.get("Lt_cm"))
            lambda0 = p.get("lambda0", 0.0)
            web_effective_ratio = (
                rf"\dfrac{{{decimal(p.get('web_sigma_el_kn_cm2'))}}}"
                rf"{{{decimal(p.get('chi'))} \cdot {decimal(p.get('fy_kn_cm2'))}}}"
            )
            flange_effective_ratio = (
                rf"\dfrac{{{decimal(p.get('flange_sigma_el_kn_cm2'))}}}"
                rf"{{{decimal(p.get('chi'))} \cdot {decimal(p.get('fy_kn_cm2'))}}}"
            )
            chi_equation = (
                r"0,658^{\lambda_0^2}"
                if lambda0 <= 1.5 else
                r"\dfrac{0,877}{\lambda_0^2}"
            )
            u_section = memory.get("profile_type") in {"U Laminado", "U Inclinado Laminado"}
            flange_width_expression = r"b_f" if u_section else r"\dfrac{b_f}{2}"
            flange_width_input = (
                decimal(p.get("flange_width_mm")) if u_section else
                decimal(2.0 * p.get("flange_width_mm"))
            )
            flange_piece_count = 2 if u_section else 4
            if u_section:
                axial_buckling_lines = (
                    *equation_triplet(
                        r"N_{ey}", r"\dfrac{\pi^2 E I_y}{L_y^2}",
                        rf"\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Iy_cm4'))}}}"
                        rf"{{{decimal(p.get('Ly_cm'))}^2}}",
                        decimal(p.get("Ney_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_{ez}", r"\dfrac{\pi^2 E I_z}{L_z^2}",
                        rf"\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Iz_cm4'))}}}"
                        rf"{{{decimal(p.get('Lz_cm'))}^2}}",
                        decimal(p.get("Nez_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_{et}", r"\dfrac{\dfrac{\pi^2 E C_w}{L_t^2}+G I_t}{r_0^2}",
                        rf"\dfrac{{\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Cw_cm6'))}}}"
                        rf"{{{lt_latex}^2}}+{decimal(p.get('G_kn_cm2'))} \cdot {decimal(p.get('It_cm4'))}}}"
                        rf"{{{decimal(p.get('r0_cm'))}^2}}",
                        decimal(p.get("Net_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"H", r"1-\dfrac{x_0^2}{r_0^2}",
                        rf"1-\dfrac{{{decimal(p.get('x0_cm'))}^2}}{{{decimal(p.get('r0_cm'))}^2}}",
                        decimal(p.get("H_flexotorsion")),
                    ),
                    *equation_triplet(
                        r"N_{eyt}",
                        r"\dfrac{N_{ey}+N_{et}}{2H}\left(1-\sqrt{1-\dfrac{4N_{ey}N_{et}H}{(N_{ey}+N_{et})^2}}\right)",
                        rf"\dfrac{{{decimal(p.get('Ney_kn'))}+{decimal(p.get('Net_kn'))}}}"
                        rf"{{2\cdot {decimal(p.get('H_flexotorsion'))}}}"
                        rf"\left(1-\sqrt{{1-\dfrac{{4\cdot {decimal(p.get('Ney_kn'))}"
                        rf"\cdot {decimal(p.get('Net_kn'))}\cdot {decimal(p.get('H_flexotorsion'))}}}"
                        rf"{{({decimal(p.get('Ney_kn'))}+{decimal(p.get('Net_kn'))})^2}}}}\right)",
                        decimal(p.get("Neyt_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_e", r"\min(N_{ez};N_{eyt})",
                        rf"\min({decimal(p.get('Nez_kn'))};{decimal(p.get('Neyt_kn'))})",
                        decimal(p.get("Ne_kn")), r"kN",
                    ),
                )
            else:
                axial_buckling_lines = (
                    *equation_triplet(
                        r"N_{ey}", r"\dfrac{\pi^2 E I_y}{L_y^2}",
                        rf"\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Iy_cm4'))}}}"
                        rf"{{{decimal(p.get('Ly_cm'))}^2}}",
                        decimal(p.get("Ney_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_{ez}", r"\dfrac{\pi^2 E I_z}{L_z^2}",
                        rf"\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Iz_cm4'))}}}"
                        rf"{{{decimal(p.get('Lz_cm'))}^2}}",
                        decimal(p.get("Nez_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_{et}", r"\dfrac{\dfrac{\pi^2 E C_w}{L_t^2}+G I_t}{r_0^2}",
                        rf"\dfrac{{\dfrac{{\pi^2 \cdot {decimal(p.get('E_kn_cm2'))} \cdot {decimal(p.get('Cw_cm6'))}}}"
                        rf"{{{lt_latex}^2}}+{decimal(p.get('G_kn_cm2'))} \cdot {decimal(p.get('It_cm4'))}}}"
                        rf"{{{decimal(p.get('r0_cm'))}^2}}",
                        decimal(p.get("Net_kn")), r"kN",
                    ),
                    *equation_triplet(
                        r"N_e", r"\min(N_{ey};N_{ez};N_{et})",
                        rf"\min({decimal(p.get('Ney_kn'))};{decimal(p.get('Nez_kn'))};{decimal(p.get('Net_kn'))})",
                        decimal(p.get("Ne_kn")), r"kN",
                    ),
                )
            compression_steps = [
                (
                    axial_buckling_lines,
                    "",
                ),
                (
                    equation_triplet(
                        r"\lambda_0", r"\sqrt{\dfrac{A_g \cdot f_y}{N_e}}",
                        rf"\sqrt{{\dfrac{{{decimal(p.get('Ag_cm2'))} \cdot {decimal(p.get('fy_kn_cm2'))}}}"
                        rf"{{{decimal(p.get('Ne_kn'))}}}}}",
                        decimal(p.get("lambda0")),
                    ),
                    "",
                ),
                (
                    equation_triplet(
                        r"\chi", chi_equation,
                        (rf"0,658^{{{decimal(lambda0)}^2}}" if lambda0 <= 1.5 else
                         rf"\dfrac{{0,877}}{{{decimal(lambda0)}^2}}"),
                        decimal(p.get("chi")),
                    ),
                    "",
                ),
                (
                    (
                        *equation_triplet(
                            r"\lambda_{AA}", r"\dfrac{d_i}{t_w}",
                            rf"\dfrac{{{decimal(p.get('web_width_mm'))}}}{{{decimal(p.get('tw_mm'))}}}",
                            decimal(p.get("web_slenderness")),
                        ),
                        *equation_triplet(
                            r"\lambda_{lim,AA}", r"1,49\sqrt{\dfrac{E}{f_y}}",
                            rf"1,49\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                            decimal(p.get("web_limit")),
                        ),
                        *equation_triplet(
                            r"\lambda_{red,AA}", r"\dfrac{\lambda_{lim,AA}}{\sqrt{\chi}}",
                            rf"\dfrac{{{decimal(p.get('web_limit'))}}}{{\sqrt{{{decimal(p.get('chi'))}}}}}",
                            decimal(p.get("web_reduced_limit")),
                        ),
                        (rf"\lambda_{{AA}} = {decimal(p.get('web_slenderness'))} "
                         + (r">" if p.get("web_is_slender") else r"\leq")
                         + rf" \lambda_{{red,AA}} = {decimal(p.get('web_reduced_limit'))}"),
                        *equation_triplet(
                            r"\sigma_{el,AA}",
                            r"\left(1,31\dfrac{\lambda_{lim,AA}}{\lambda_{AA}}\right)^2 \cdot f_y",
                            rf"\left(1,31 \cdot \dfrac{{{decimal(p.get('web_limit'))}}}"
                            rf"{{{decimal(p.get('web_slenderness'))}}}\right)^2 \cdot {decimal(p.get('fy_kn_cm2'))}",
                            decimal(p.get("web_sigma_el_kn_cm2")), r"kN/cm^2",
                        ),
                        *equation_triplet(
                            r"d_{ef}",
                            (r"d_i\left(1-0,18\sqrt{\dfrac{\sigma_{el,AA}}{\chi f_y}}\right)"
                             r"\sqrt{\dfrac{\sigma_{el,AA}}{\chi f_y}}"
                             if p.get("web_is_slender") else r"d_i"),
                            (rf"{decimal(p.get('web_width_mm'))}"
                             if not p.get("web_is_slender") else
                             rf"{decimal(p.get('web_width_mm'))}\left(1-0,18\sqrt{{{web_effective_ratio}}}\right)"
                             rf"\sqrt{{{web_effective_ratio}}}"),
                            decimal(p.get("web_effective_mm")), r"mm",
                        ),
                    ),
                    "",
                ),
                (
                    (
                        *equation_triplet(
                            r"b_{f,aba}", flange_width_expression,
                            flange_width_input,
                            decimal(p.get("flange_width_mm")), r"mm",
                        ),
                        *equation_triplet(
                            r"\lambda_{AL}", r"\dfrac{b_{f,aba}}{t_f}",
                            rf"\dfrac{{{decimal(p.get('flange_width_mm'))}}}{{{decimal(p.get('tf_mm'))}}}",
                            decimal(p.get("flange_slenderness")),
                        ),
                        *equation_triplet(
                            r"\lambda_{lim,AL}", r"0,56\sqrt{\dfrac{E}{f_y}}",
                            rf"0,56\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                            decimal(p.get("flange_limit")),
                        ),
                        *equation_triplet(
                            r"\lambda_{red,AL}", r"\dfrac{\lambda_{lim,AL}}{\sqrt{\chi}}",
                            rf"\dfrac{{{decimal(p.get('flange_limit'))}}}{{\sqrt{{{decimal(p.get('chi'))}}}}}",
                            decimal(p.get("flange_reduced_limit")),
                        ),
                        (rf"\lambda_{{AL}} = {decimal(p.get('flange_slenderness'))} "
                         + (r">" if p.get("flange_is_slender") else r"\leq")
                         + rf" \lambda_{{red,AL}} = {decimal(p.get('flange_reduced_limit'))}"),
                        *equation_triplet(
                            r"\sigma_{el,AL}",
                            r"\left(1,49\dfrac{\lambda_{lim,AL}}{\lambda_{AL}}\right)^2 \cdot f_y",
                            rf"\left(1,49 \cdot \dfrac{{{decimal(p.get('flange_limit'))}}}"
                            rf"{{{decimal(p.get('flange_slenderness'))}}}\right)^2 \cdot {decimal(p.get('fy_kn_cm2'))}",
                            decimal(p.get("flange_sigma_el_kn_cm2")), r"kN/cm^2",
                        ),
                        *equation_triplet(
                            r"b_{ef,f}",
                            (r"b_{f,aba}\left(1-0,22\sqrt{\dfrac{\sigma_{el,AL}}{\chi f_y}}\right)"
                             r"\sqrt{\dfrac{\sigma_{el,AL}}{\chi f_y}}"
                             if p.get("flange_is_slender") else r"b_{f,aba}"),
                            (rf"{decimal(p.get('flange_width_mm'))}"
                             if not p.get("flange_is_slender") else
                             rf"{decimal(p.get('flange_width_mm'))}\left(1-0,22\sqrt{{{flange_effective_ratio}}}\right)"
                             rf"\sqrt{{{flange_effective_ratio}}}"),
                            decimal(p.get("flange_effective_mm")), r"mm",
                        ),
                    ),
                    "",
                ),
                (
                    equation_triplet(
                        r"A_{ef}",
                        rf"A_g-\dfrac{{(d_i-d_{{ef}})\cdot t_w+{flange_piece_count}\cdot(b_{{f,aba}}-b_{{ef,f}})\cdot t_f}}{{100}}",
                        rf"{decimal(p.get('Ag_cm2'))}-\dfrac{{"
                        rf"({decimal(p.get('web_width_mm'))}-{decimal(p.get('web_effective_mm'))})"
                        rf"\cdot {decimal(p.get('tw_mm'))}+{flange_piece_count}\cdot"
                        rf"({decimal(p.get('flange_width_mm'))}-{decimal(p.get('flange_effective_mm'))})"
                        rf"\cdot {decimal(p.get('tf_mm'))}}}{{100}}",
                        decimal(p.get("Aef_cm2")), r"cm^2",
                    ),
                    "",
                ),
                (
                    equation_triplet(
                        r"N_{c,Rd}", r"\dfrac{\chi \cdot A_{ef} \cdot f_y}{\gamma_{a1}}",
                        rf"\dfrac{{{decimal(p.get('chi'))} \cdot {decimal(p.get('Aef_cm2'))}"
                        rf" \cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'), 2)}}}",
                        decimal(p.get("Nc_Rd_kn")), r"kN",
                    ),
                    "",
                ),
            ]
            for latex_lines, fallback in compression_steps:
                axial_compression_content += spaced_equations(latex_lines, fallback)
            applied = compression_verification.get("applied_kn")
            utilization = compression_verification.get("utilization")
            combination_name = escape(str(compression_verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            ratio_lines = equation_triplet(
                r"\eta_c", r"\dfrac{N_{c,Sd}}{N_{c,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Nc_Rd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
            )
            axial_compression_content += (
                f'{spaced_equations(ratio_lines)}'
                f'<p style="margin:0 0 3px;color:#57606a">'
                f'Combinação governante: {combination_name}</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            axial_compression_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de compressão axial atende somente a perfis W, I e U Laminados.</p>"
            )
        elif compression_verification.get("status") == "not_checked":
            axial_compression_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(compression_verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif compression_verification.get("status") == "not_applicable":
            axial_compression_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(compression_verification.get("detail", "Sem compressão axial.")))}.</p>'
            )
        else:
            axial_compression_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
            )
        flexion_verification = flexion_y.get("verification") or {}
        flexion_parameters = flexion_verification.get("parameters", {})
        flexion_y_content = (
            '<p style="margin:22px 0 12px;color:#57606a;font-weight:700">'
            + ("Flexão em Y — ABNT NBR 8800:2024, 5.4.2.2 e Anexo D, D.2.5</p>"
               if memory.get("profile_type") == "Barra Circular" else
               "Flexão em Y — ABNT NBR 8800:2024, 5.4 e Anexo D, D.2.5 e Tabela D.1</p>"
               if memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"} else
               "Flexão em Y — ABNT NBR 8800:2024, 5.4.1.1-c e Anexo D, D.2.3</p>"
               if memory.get("profile_type") == "T Laminado" else
               "Flexão em Y</p>" if memory.get("profile_type") == "L Laminado"
               else "Flexão em Y — ABNT NBR 8800:2024, 5.4 e Anexo D</p>")
        )
        if flexion_verification.get("status") == "checked" and memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            p = flexion_parameters
            if memory.get("profile_type") == "Barra Circular":
                flexion_y_content += spaced_equations((
                    *equation_triplet(r"M_{pl}", r"Z_{pl} f_y",
                                      rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{cap}", r"1,50W f_y",
                                      rf"1,50\cdot {decimal(p.get('Wy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mcap_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{y,Rd}", r"\dfrac{\min(M_{pl},M_{cap})}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            elif p.get("strong_axis"):
                flexion_y_content += spaced_equations((
                    *equation_triplet(r"M_p", r"Z_y f_y",
                                      rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"\lambda", r"\dfrac{L_b}{r_{min}}",
                                      rf"\dfrac{{{decimal(p.get('Lb_cm'))}}}{{{decimal(min(p.get('ry_cm', 0.0), p.get('rz_cm', 0.0)))}}}",
                                      decimal(p.get("lambda_flt"))),
                    *equation_triplet(r"\lambda_p", r"0,13\dfrac{E\sqrt{J A_g}}{M_p}",
                                      rf"0,13\cdot\dfrac{{{decimal(p.get('E_kn_cm2'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('Mpl_kn_cm'))}}}",
                                      decimal(p.get("lambda_p_flt"))),
                    *equation_triplet(r"\lambda_r", r"2C_b\dfrac{E\sqrt{J A_g}}{M_r}",
                                      rf"2\cdot {decimal(p.get('Cb'))}\cdot\dfrac{{{decimal(p.get('E_kn_cm2'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('Mr_kn_cm'))}}}",
                                      decimal(p.get("lambda_r_flt"))),
                    *equation_triplet(r"M_{cr}", r"\dfrac{2E C_b\sqrt{J A_g}}{\lambda}",
                                      rf"\dfrac{{2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Cb'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('lambda_flt'))}}}",
                                      decimal(p.get("Mcr_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{y,Rd}", r"\dfrac{M_n}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            else:
                flexion_y_content += spaced_equations((
                    *equation_triplet(r"M_p", r"Z_y f_y",
                                      rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{y,Rd}", r"\dfrac{M_p}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mpl_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            utilization = flexion_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            flexion_y_content += spaced_equations(equation_triplet(
                r"\eta_y", r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}",
                rf"\dfrac{{{decimal(flexion_verification.get('applied_kn_cm'))}}}{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif flexion_verification.get("status") == "checked" and memory.get("profile_type") == "T Laminado":
            p = flexion_parameters
            flexion_y_content += spaced_equations((
                *equation_triplet(r"M_p", r"Z_y f_y",
                                  rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"\lambda_{FLA}", r"\dfrac{d}{t_w}",
                                  rf"\dfrac{{{decimal(p.get('d_mm'))}}}{{{decimal(p.get('tw_mm'))}}}",
                                  decimal(p.get("lambda_fla"))),
                *equation_triplet(r"\lambda_{y,FLA}", r"0,84\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,84\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_p_fla"))),
                *equation_triplet(r"\lambda_{r,FLA}", r"1,52\sqrt{\dfrac{E}{f_y}}",
                                  rf"1,52\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_r_fla"))),
                *equation_triplet(r"M_{Rd,FLA}", r"\dfrac{M_{n,FLA}}{\gamma_{a1}}",
                                  decimal(p.get("Mrd_fla_kn_cm")), decimal(p.get("Mrd_fla_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"\lambda_{FLM}", r"\dfrac{b_f}{2t_f}",
                                  rf"\dfrac{{{decimal(p.get('bf_mm'))}}}{{2\cdot {decimal(p.get('tf_mm'))}}}",
                                  decimal(p.get("lambda_flm"))),
                *equation_triplet(r"\lambda_{p,FLM}", r"0,38\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,38\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_p_flm"))),
                *equation_triplet(r"\lambda_{r,FLM}", r"0,83\sqrt{\dfrac{E}{f_y-\sigma_r}}",
                                  rf"0,83\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_r_flm"))),
                *equation_triplet(r"M_r", r"(f_y-\sigma_r)W_{xc}\leq f_yW_{xt}",
                                  decimal(p.get("Mr_flm_kn_cm")), decimal(p.get("Mr_flm_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{cr,FLM}", r"\dfrac{0,69EW_{xc}}{\lambda_{FLM}^2}",
                                  decimal(p.get("Mcr_flm_kn_cm")), decimal(p.get("Mcr_flm_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{Rd,FLM}", r"\dfrac{M_{n,FLM}}{\gamma_{a1}}",
                                  decimal(p.get("Mrd_flm_kn_cm")), decimal(p.get("Mrd_flm_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"\lambda_{FLT}", r"\dfrac{L_b}{r_z}",
                                  rf"\dfrac{{{decimal(p.get('Lb_cm'))}}}{{{decimal(p.get('rz_cm'))}}}",
                                  decimal(p.get("lambda_flt"))),
                *equation_triplet(r"B", r"2,3\dfrac{d}{L_b}\sqrt{\dfrac{I_z}{I_t}}",
                                  decimal(p.get("B_flt")), decimal(p.get("B_flt"))),
                *equation_triplet(r"M_{cr,FLT,+}", r"\dfrac{1,95E}{L_b}\sqrt{I_zI_t}(B+\sqrt{1+B^2})",
                                  decimal(p.get("Mcr_flt_tension_kn_cm")),
                                  decimal(p.get("Mcr_flt_tension_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{cr,FLT,-}", r"\dfrac{1,95E}{L_b}\sqrt{I_zI_t}(-B+\sqrt{1+B^2})",
                                  decimal(p.get("Mcr_flt_compression_kn_cm")),
                                  decimal(p.get("Mcr_flt_compression_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(
                    r"M_{y,Rd}",
                    (r"\min(M_{Rd,FLM};M_{Rd,FLT,+})"
                     if p.get("bending_sign") == "web_end_tension" else
                     r"\min(M_{Rd,FLA};M_{Rd,FLT,-})"),
                    (rf"\min({decimal(p.get('Mrd_flm_kn_cm'))};"
                     rf"{decimal(p.get('Mrd_flt_tension_kn_cm'))})"
                     if p.get("bending_sign") == "web_end_tension" else
                     rf"\min({decimal(p.get('Mrd_fla_kn_cm'))};"
                     rf"{decimal(p.get('Mrd_flt_compression_kn_cm'))})"),
                    decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
            ))
            utilization = flexion_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            flexion_y_content += spaced_equations(equation_triplet(
                r"\eta_y", r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}",
                rf"\dfrac{{{decimal(flexion_verification.get('applied_kn_cm'))}}}{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif flexion_verification.get("status") == "checked" and memory.get("profile_type") == "L Laminado":
            p = flexion_parameters
            flexion_y_content += spaced_equations((
                *equation_triplet(r"M_p", r"Z_y f_y", rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}", decimal(p.get("Mn_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{y,Rd}", r"\dfrac{M_n}{\gamma_{a1}}", rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}", decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
            ))
            utilization = flexion_verification.get("utilization")
            status = "APROVADO" if utilization <= 1 else "REPROVADO"
            flexion_y_content += spaced_equations(equation_triplet(
                r"\eta_y", r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}",
                rf"\dfrac{{{decimal(flexion_verification.get('applied_kn_cm'))}}}{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif (
            flexion_verification.get("status") == "checked"
            and not (flexion_verification.get("parameters") or {}).get("slender_web_rejected")
        ):
            p = flexion_parameters
            def interpolate_mn(lambda_value: float, lambda_p: float, lambda_r: float,
                               mcr: float, label: str) -> tuple[str, str]:
                if lambda_value <= lambda_p:
                    return r"M_p", decimal(p.get("Mp_kn_cm"))
                if lambda_value <= lambda_r:
                    formula = (
                        rf"M_p-(M_p-M_r)\cdot"
                        rf"\dfrac{{\lambda_{{{label}}}-\lambda_{{p,{label}}}}}"
                        rf"{{\lambda_{{r,{label}}}-\lambda_{{p,{label}}}}}"
                    )
                    substituted = (
                        rf"{decimal(p.get('Mp_kn_cm'))}-({decimal(p.get('Mp_kn_cm'))}"
                        rf"-{decimal(p.get('Mr_kn_cm'))})\cdot"
                        rf"\dfrac{{{decimal(lambda_value)}-{decimal(lambda_p)}}}"
                        rf"{{{decimal(lambda_r)}-{decimal(lambda_p)}}}"
                    )
                    return formula, substituted
                return r"M_{cr}", decimal(mcr)

            flt_mn_formula, flt_mn_sub = interpolate_mn(
                p["lambda_flt"], p["lambda_p_flt"], p["lambda_r_flt"],
                p["Mcr_flt_kn_cm"], "FLT",
            )
            flm_mn_formula, flm_mn_sub = interpolate_mn(
                p["lambda_flm"], p["lambda_p_flm"], p["lambda_r_flm"],
                p["Mcr_flm_kn_cm"], "FLM",
            )
            if p["lambda_fla"] <= p["lambda_p_fla"]:
                fla_mn_formula, fla_mn_sub = r"M_p", decimal(p.get("Mp_kn_cm"))
            else:
                fla_mn_formula = (
                    r"M_p-(M_p-M_{r,FLA})\cdot"
                    r"\dfrac{\lambda_{FLA}-\lambda_{p,FLA}}{\lambda_{r,FLA}-\lambda_{p,FLA}}"
                )
                fla_mn_sub = (
                    rf"{decimal(p.get('Mp_kn_cm'))}-({decimal(p.get('Mp_kn_cm'))}"
                    rf"-{decimal(p.get('Mr_fla_kn_cm'))})\cdot"
                    rf"\dfrac{{{decimal(p.get('lambda_fla'))}-{decimal(p.get('lambda_p_fla'))}}}"
                    rf"{{{decimal(p.get('lambda_r_fla'))}-{decimal(p.get('lambda_p_fla'))}}}"
                )

            lambda_r_flt_substituted = (
                r"\dfrac{1,38\cdot "
                + decimal(p.get("Cb"))
                + r"\sqrt{" + decimal(p.get("Iy_cm4"))
                + r"\cdot " + decimal(p.get("It_cm4")) + r"}}"
                + r"{" + decimal(p.get("rz_cm"))
                + r"\cdot " + decimal(p.get("It_cm4"))
                + r"\cdot " + decimal(p.get("beta1")) + r"}"
                + r"\sqrt{1+\sqrt{1+\dfrac{27\cdot "
                + decimal(p.get("Cw_cm6"))
                + r"\cdot " + decimal(p.get("beta1"))
                + r"^2}{" + decimal(p.get("Cb"))
                + r"^2\cdot " + decimal(p.get("Iy_cm4")) + r"}}}"
            )

            flt_lines = (
                *equation_triplet(r"\lambda_{FLT}", r"\dfrac{L_b}{r_z}",
                                  rf"\dfrac{{{decimal(p.get('Lb_cm'))}}}{{{decimal(p.get('rz_cm'))}}}",
                                  decimal(p.get("lambda_flt"))),
                *equation_triplet(r"\lambda_{p,FLT}", r"1,76\sqrt{\dfrac{E}{f_y}}",
                                  rf"1,76\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_p_flt"))),
                *equation_triplet(r"\beta_1", r"\dfrac{(f_y-\sigma_r)\cdot W_y}{E\cdot I_t}",
                                  rf"\dfrac{{({decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_kn_cm2'))})"
                                  rf"\cdot {decimal(p.get('Wy_cm3'))}}}"
                                  rf"{{{decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('It_cm4'))}}}",
                                  decimal(p.get("beta1")), r"cm^{-1}"),
                *equation_triplet(
                    r"\lambda_{r,FLT}",
                    r"\dfrac{1,38C_b\sqrt{I_y I_t}}{r_z I_t\beta_1}"
                    r"\sqrt{1+\sqrt{1+\dfrac{27C_w\beta_1^2}{C_b^2I_y}}}",
                    lambda_r_flt_substituted,
                    decimal(p.get("lambda_r_flt")),
                ),
                *equation_triplet(
                    r"M_{cr,FLT}",
                    r"\dfrac{C_b\pi^2E I_y}{L_b^2}"
                    r"\sqrt{\dfrac{C_w}{I_y}\left(1+0,039\dfrac{I_tL_b^2}{C_w}\right)}",
                    rf"\dfrac{{{decimal(p.get('Cb'))}\cdot \pi^2\cdot {decimal(p.get('E_kn_cm2'))}"
                    rf"\cdot {decimal(p.get('Iy_cm4'))}}}{{{decimal(p.get('Lb_cm'))}^2}}"
                    rf"\sqrt{{\dfrac{{{decimal(p.get('Cw_cm6'))}}}{{{decimal(p.get('Iy_cm4'))}}}"
                    rf"\left(1+0,039\dfrac{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Lb_cm'))}^2}}"
                    rf"{{{decimal(p.get('Cw_cm6'))}}}\right)}}",
                    decimal(p.get("Mcr_flt_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(r"M_p", r"Z_y\cdot f_y",
                                  rf"{decimal(p.get('Zy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Mp_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_r", r"0,70W_y\cdot f_y",
                                  rf"0,70\cdot {decimal(p.get('Wy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Mr_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{n,FLT}", flt_mn_formula, flt_mn_sub,
                                  decimal(p.get("Mn_flt_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{Rd,FLT}", r"\dfrac{M_{n,FLT}}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('Mn_flt_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Mrd_flt_nominal_kn_cm")), r"kN\cdot cm"),
            )
            u_flex_y = memory.get("profile_type") in {"U Laminado", "U Inclinado Laminado"}
            lambda_flm_formula_y = r"\dfrac{b_f}{t_f}" if u_flex_y else r"\dfrac{b_f}{2t_f}"
            lambda_flm_substitution_y = (
                rf"\dfrac{{{decimal(p.get('bf_cm'))}}}{{{decimal(p.get('tf_cm'))}}}"
                if u_flex_y else
                rf"\dfrac{{{decimal(p.get('bf_cm'))}}}{{2\cdot {decimal(p.get('tf_cm'))}}}"
            )
            flm_lines = (
                *equation_triplet(r"\lambda_{FLM}", lambda_flm_formula_y,
                                  lambda_flm_substitution_y,
                                  decimal(p.get("lambda_flm"))),
                *equation_triplet(r"\lambda_{p,FLM}", r"0,38\sqrt{\dfrac{E}{f_y}}",
                                  rf"0,38\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_p_flm"))),
                *equation_triplet(r"\lambda_{r,FLM}", r"0,83\sqrt{\dfrac{E}{f_y-\sigma_r}}",
                                  rf"0,83\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}"
                                  rf"{{{decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_r_flm"))),
                *equation_triplet(r"M_{cr,FLM}", r"\dfrac{0,69E W_y}{\lambda_{FLM}^2}",
                                  rf"\dfrac{{0,69\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Wy_cm3'))}}}"
                                  rf"{{{decimal(p.get('lambda_flm'))}^2}}",
                                  decimal(p.get("Mcr_flm_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{n,FLM}", flm_mn_formula, flm_mn_sub,
                                  decimal(p.get("Mn_flm_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{Rd,FLM}", r"\dfrac{M_{n,FLM}}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('Mn_flm_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Mrd_flm_nominal_kn_cm")), r"kN\cdot cm"),
            )
            fla_lines = (
                *equation_triplet(r"\lambda_{FLA}", r"\dfrac{d_i}{t_w}",
                                  rf"\dfrac{{{decimal(p.get('di_cm'))}}}{{{decimal(p.get('tw_cm'))}}}",
                                  decimal(p.get("lambda_fla"))),
                *equation_triplet(r"\lambda_{p,FLA}", r"3,76\sqrt{\dfrac{E}{f_y}}",
                                  rf"3,76\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_p_fla"))),
                *equation_triplet(r"\lambda_{r,FLA}", r"5,70\sqrt{\dfrac{E}{f_y}}",
                                  rf"5,70\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                                  decimal(p.get("lambda_r_fla"))),
                *equation_triplet(r"M_{r,FLA}", r"W_y\cdot f_y",
                                  rf"{decimal(p.get('Wy_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Mr_fla_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{n,FLA}", fla_mn_formula, fla_mn_sub,
                                  decimal(p.get("Mn_fla_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{Rd,FLA}", r"\dfrac{M_{n,FLA}}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('Mn_fla_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("Mrd_fla_nominal_kn_cm")), r"kN\cdot cm"),
            )
            flexion_steps = (
                flt_lines,
                flm_lines,
                fla_lines,
                (
                    *equation_triplet(
                        r"M_{Rd,max}", r"\dfrac{1,50W_y\cdot f_y}{\gamma_{a1}}",
                        rf"\dfrac{{1,50\cdot {decimal(p.get('Wy_cm3'))}"
                        rf"\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                        decimal(p.get("Mrd_limit_kn_cm")), r"kN\cdot cm",
                    ),
                    *equation_triplet(
                        r"M_{y,Rd}",
                        r"\min(M_{Rd,FLT};M_{Rd,FLM};M_{Rd,FLA};M_{Rd,max})",
                        rf"\min({decimal(p.get('Mrd_flt_nominal_kn_cm'))};"
                        rf"{decimal(p.get('Mrd_flm_nominal_kn_cm'))};"
                        rf"{decimal(p.get('Mrd_fla_nominal_kn_cm'))};"
                        rf"{decimal(p.get('Mrd_limit_kn_cm'))})",
                        decimal(p.get("Mrd_kn_cm")), r"kN\cdot cm",
                    ),
                ),
            )
            for latex_lines in flexion_steps:
                flexion_y_content += spaced_equations(latex_lines)
            applied = flexion_verification.get("applied_kn_cm")
            utilization = flexion_verification.get("utilization")
            combination_name = escape(str(flexion_verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            utilization_lines = equation_triplet(
                r"\eta_y", r"\dfrac{M_{y,Sd}}{M_{y,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Mrd_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
            )
            flexion_y_content += (
                f'{spaced_equations(utilization_lines)}'
                f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
            )
        elif (
            memory.get("profile_type") in {"W Laminado", "HP Laminado"}
            and flexion_verification.get("status") == "not_checked"
            and (flexion_verification.get("parameters") or {}).get("slender_web_rejected")
        ):
            p = flexion_verification.get("parameters", {})
            slenderness_lines = (
                *equation_triplet(
                    r"\lambda_{FLA}", r"\dfrac{h}{t_w}",
                    rf"\dfrac{{{decimal(p.get('di_cm'))}}}{{{decimal(p.get('tw_cm'))}}}",
                    decimal(p.get("lambda_fla")),
                ),
                *equation_triplet(
                    r"\lambda_{r,FLA}", r"5,70\sqrt{\dfrac{E}{f_y}}",
                    rf"5,70\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                    decimal(p.get("lambda_r_fla")),
                ),
                *equation_triplet(
                    r"\eta_{FLA}", r"\dfrac{\lambda_{FLA}}{\lambda_{r,FLA}}\leq 1,0",
                    rf"\dfrac{{{decimal(p.get('lambda_fla'))}}}{{{decimal(p.get('lambda_r_fla'))}}}",
                    decimal(p.get("lambda_fla") / p.get("lambda_r_fla"), 2),
                ),
            )
            flexion_y_content += (
                f'{spaced_equations(slenderness_lines)}'
                f'<p style="margin:0 0 3px;color:#57606a">Não verificado: '
                f'{escape(str(flexion_verification.get("detail", "limite de aplicação excedido")))}.</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            flexion_y_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de flexão em Y atende somente a perfis W, I e U Laminados.</p>"
            )
        elif flexion_verification.get("status") == "not_checked":
            flexion_y_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(flexion_verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif flexion_verification.get("status") == "not_applicable":
            flexion_y_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(flexion_verification.get("detail", "Sem momento fletor em Y.")))}.</p>'
            )
        else:
            flexion_y_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
            )
        flexion_z_verification = flexion_z.get("verification") or {}
        u_weak_axis = memory.get("profile_type") in {"U Laminado", "U Inclinado Laminado"}
        flexion_z_basis = (
            "Anexo D, Tabela D.1 e D.2.8-c e d" if u_weak_axis else
            "Anexo D, Tabela D.1 e D.2.8-f e h"
        )
        flexion_z_content = (
            '<p style="margin:22px 0 12px;color:#57606a;font-weight:700">'
            + ("Flexão em Z — ABNT NBR 8800:2024, 5.4.2.2 e Anexo D, D.2.5</p>"
               if memory.get("profile_type") == "Barra Circular" else
               "Flexão em Z — ABNT NBR 8800:2024, 5.4 e Anexo D, D.2.5 e Tabela D.1</p>" if memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada"}
               else "Flexão em Z</p>" if memory.get("profile_type") == "L Laminado"
               else "Flexão em Z</p>" if memory.get("profile_type") == "T Laminado"
               else f"Flexão em Z — ABNT NBR 8800:2024, 5.4.2.1 e 5.4.2.2; {flexion_z_basis}</p>")
        )
        if flexion_z_verification.get("status") == "checked" and memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            p = flexion_z_verification.get("parameters", {})
            if memory.get("profile_type") == "Barra Circular":
                flexion_z_content += spaced_equations((
                    *equation_triplet(r"M_{pl}", r"Z_{pl} f_y",
                                      rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{cap}", r"1,50W f_y",
                                      rf"1,50\cdot {decimal(p.get('Wz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mcap_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{z,Rd}", r"\dfrac{\min(M_{pl},M_{cap})}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            elif p.get("strong_axis"):
                flexion_z_content += spaced_equations((
                    *equation_triplet(r"M_p", r"Z_z f_y",
                                      rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"\lambda", r"\dfrac{L_b}{r_{min}}",
                                      rf"\dfrac{{{decimal(p.get('Lb_cm'))}}}{{{decimal(min(p.get('ry_cm', 0.0), p.get('rz_cm', 0.0)))}}}",
                                      decimal(p.get("lambda_flt"))),
                    *equation_triplet(r"\lambda_p", r"0,13\dfrac{E\sqrt{J A_g}}{M_p}",
                                      rf"0,13\cdot\dfrac{{{decimal(p.get('E_kn_cm2'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('Mpl_kn_cm'))}}}",
                                      decimal(p.get("lambda_p_flt"))),
                    *equation_triplet(r"\lambda_r", r"2C_b\dfrac{E\sqrt{J A_g}}{M_r}",
                                      rf"2\cdot {decimal(p.get('Cb'))}\cdot\dfrac{{{decimal(p.get('E_kn_cm2'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('Mr_kn_cm'))}}}",
                                      decimal(p.get("lambda_r_flt"))),
                    *equation_triplet(r"M_{cr}", r"\dfrac{2E C_b\sqrt{J A_g}}{\lambda}",
                                      rf"\dfrac{{2\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Cb'))}\sqrt{{{decimal(p.get('It_cm4'))}\cdot {decimal(p.get('Ag_cm2'))}}}}}{{{decimal(p.get('lambda_flt'))}}}",
                                      decimal(p.get("Mcr_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{z,Rd}", r"\dfrac{M_n}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            else:
                flexion_z_content += spaced_equations((
                    *equation_triplet(r"M_p", r"Z_z f_y",
                                      rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                      decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                    *equation_triplet(r"M_{z,Rd}", r"\dfrac{M_p}{\gamma_{a1}}",
                                      rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
                ))
            utilization = flexion_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            flexion_z_content += spaced_equations(equation_triplet(
                r"\eta_z", r"\dfrac{|M_{z,Sd}|}{M_{z,Rd}}",
                rf"\dfrac{{{decimal(flexion_z_verification.get('applied_kn_cm'))}}}{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif flexion_z_verification.get("status") == "checked" and memory.get("profile_type") == "T Laminado":
            p = flexion_z_verification.get("parameters", {})
            flexion_z_content += spaced_equations((
                *equation_triplet(r"\lambda_{FLM,Z}", r"\dfrac{b_f}{t_f}",
                                  rf"\dfrac{{{decimal(p.get('bf_mm'))}}}{{{decimal(p.get('tf_mm'))}}}",
                                  decimal(p.get("lambda_flm"))),
                *equation_triplet(r"\lambda_{p,FLM}", r"0,38\sqrt{\dfrac{E}{f_y}}",
                                  decimal(p.get("lambda_p_flm")), decimal(p.get("lambda_p_flm"))),
                *equation_triplet(r"\lambda_{r,FLM}", r"0,83\sqrt{\dfrac{E}{f_y-\sigma_r}}",
                                  decimal(p.get("lambda_r_flm")), decimal(p.get("lambda_r_flm"))),
                *equation_triplet(r"M_p", r"Z_z f_y",
                                  rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Mpl_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_r", r"(f_y-\sigma_r)W_{zc}",
                                  decimal(p.get("Mr_kn_cm")), decimal(p.get("Mr_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{cr,FLM}", r"\dfrac{0,69EW_{zc}}{\lambda_{FLM,Z}^2}",
                                  decimal(p.get("Mcr_kn_cm")), decimal(p.get("Mcr_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{z,Rd}", r"\dfrac{M_{n,FLM}}{\gamma_{a1}}",
                                  decimal(p.get("MRd_kn_cm")), decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
            ))
            utilization = flexion_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            flexion_z_content += spaced_equations(equation_triplet(
                r"\eta_z", r"\dfrac{|M_{z,Sd}|}{M_{z,Rd}}",
                rf"\dfrac{{{decimal(flexion_z_verification.get('applied_kn_cm'))}}}"
                rf"{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif flexion_z_verification.get("status") == "checked" and memory.get("profile_type") == "L Laminado":
            p = flexion_z_verification.get("parameters", {})
            flexion_z_content += spaced_equations((
                *equation_triplet(r"M_p", r"Z_z f_y", rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}", decimal(p.get("Mn_kn_cm")), r"kN\cdot cm"),
                *equation_triplet(r"M_{z,Rd}", r"\dfrac{M_n}{\gamma_{a1}}", rf"\dfrac{{{decimal(p.get('Mn_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}", decimal(p.get("MRd_kn_cm")), r"kN\cdot cm"),
            ))
            utilization = flexion_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1 else "REPROVADO"
            flexion_z_content += spaced_equations(equation_triplet(
                r"\eta_z", r"\dfrac{|M_{z,Sd}|}{M_{z,Rd}}",
                rf"\dfrac{{{decimal(flexion_z_verification.get('applied_kn_cm'))}}}{{{decimal(p.get('MRd_kn_cm'))}}}",
                rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif flexion_z_verification.get("status") == "checked":
            p = flexion_z_verification.get("parameters", {})
            instability_label = "FLA" if u_weak_axis else "FLM"
            lambda_symbol_z = rf"\lambda_{{{instability_label},Z}}"
            lambda_p_symbol_z = rf"\lambda_{{p,{instability_label},Z}}"
            lambda_r_symbol_z = rf"\lambda_{{r,{instability_label},Z}}"
            lambda_coefficient_z = "1,12" if u_weak_axis else "0,38"
            lambda_r_coefficient_z = "1,40" if u_weak_axis else "0,83"
            lambda_formula_z = (
                r"\dfrac{h}{t_w}" if u_weak_axis else r"\dfrac{b_f}{2\cdot t_f}"
            )
            lambda_substitution_z = (
                rf"\dfrac{{{decimal(p.get('h_cm'))}}}{{{decimal(p.get('tw_cm'))}}}"
                if u_weak_axis else
                rf"\dfrac{{{decimal(p.get('bf_cm'))}}}{{2\cdot {decimal(p.get('tf_cm'))}}}"
            )
            lambda_p_formula_z = rf"{lambda_coefficient_z}\cdot\sqrt{{\dfrac{{E}}{{f_y}}}}"
            lambda_r_formula_z = (
                rf"{lambda_r_coefficient_z}\cdot\sqrt{{\dfrac{{E}}{{f_y}}}}"
                if u_weak_axis else
                rf"{lambda_r_coefficient_z}\cdot\sqrt{{\dfrac{{E}}{{f_y-\sigma_r}}}}"
            )
            lambda_p_substitution_z = (
                rf"{lambda_coefficient_z}\cdot\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}"
                rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}"
            )
            lambda_r_substitution_z = (
                rf"{lambda_r_coefficient_z}\cdot\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}"
                rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}"
                if u_weak_axis else
                rf"{lambda_r_coefficient_z}\cdot\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}"
                rf"{{{decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_kn_cm2'))}}}}}"
            )
            lambda_demand_z = p["lambda_fla_z"] if u_weak_axis else p["lambda_flm_z"]
            lambda_p_demand_z = p["lambda_p_fla_z"] if u_weak_axis else p["lambda_p_flm_z"]
            lambda_r_demand_z = p["lambda_r_fla_z"] if u_weak_axis else p["lambda_r_flm_z"]
            if lambda_demand_z <= lambda_p_demand_z:
                mn_formula_z, mn_substituted_z = r"M_{p,Z}", decimal(p.get("Mp_z_kn_cm"))
            elif lambda_demand_z <= lambda_r_demand_z:
                mn_formula_z = (
                    r"M_{p,Z}-(M_{p,Z}-M_{r,Z})\cdot"
                    rf"\dfrac{{{lambda_symbol_z}-{lambda_p_symbol_z}}}"
                    rf"{{{lambda_r_symbol_z}-{lambda_p_symbol_z}}}"
                )
                mn_substituted_z = (
                    rf"{decimal(p.get('Mp_z_kn_cm'))}"
                    rf"-({decimal(p.get('Mp_z_kn_cm'))}-{decimal(p.get('Mr_z_kn_cm'))})\cdot"
                    rf"\dfrac{{{decimal(lambda_demand_z)}-{decimal(lambda_p_demand_z)}}}"
                    rf"{{{decimal(lambda_r_demand_z)}-{decimal(lambda_p_demand_z)}}}"
                )
            else:
                mn_formula_z, mn_substituted_z = (
                    rf"M_{{cr,{instability_label},Z}}",
                    decimal(p.get("Mcr_fla_z_kn_cm" if u_weak_axis else "Mcr_flm_z_kn_cm")),
                )

            flm_z_lines = (
                *(() if u_weak_axis else equation_triplet(
                    r"\sigma_r", r"0,30f_y",
                    rf"0,30\cdot {decimal(p.get('fy_kn_cm2'))}",
                    decimal(p.get("sigma_r_kn_cm2")), r"kN/cm^2",
                )),
                *equation_triplet(
                    lambda_symbol_z, lambda_formula_z, lambda_substitution_z,
                    decimal(lambda_demand_z),
                ),
                *equation_triplet(
                    lambda_p_symbol_z, lambda_p_formula_z, lambda_p_substitution_z,
                    decimal(lambda_p_demand_z),
                ),
                *equation_triplet(
                    lambda_r_symbol_z, lambda_r_formula_z, lambda_r_substitution_z,
                    decimal(lambda_r_demand_z),
                ),
                *(() if not u_weak_axis else (
                    *equation_triplet(
                        r"\lambda_{lim,AA}", r"1,49\sqrt{\dfrac{E}{f_y}}",
                        rf"1,49\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                        decimal(p.get("web_limit_AA")),
                    ),
                    *equation_triplet(
                        r"\sigma_{el,AA}",
                        r"\left(1,31\dfrac{\lambda_{lim,AA}}{\lambda_{FLA,Z}}\right)^2 f_y",
                        rf"\left(1,31\dfrac{{{decimal(p.get('web_limit_AA'))}}}"
                        rf"{{{decimal(p.get('lambda_fla_z'))}}}\right)^2\cdot {decimal(p.get('fy_kn_cm2'))}",
                        decimal(p.get("web_sigma_el_AA_kn_cm2")), r"kN/cm^2",
                    ),
                    *equation_triplet(
                        r"h_{ef}",
                        (r"h\left(1-0,18\sqrt{\dfrac{\sigma_{el,AA}}{f_y}}\right)"
                         r"\sqrt{\dfrac{\sigma_{el,AA}}{f_y}}"
                         if p.get("lambda_fla_z", 0.0) > p.get("web_limit_AA", 0.0)
                         else r"h"),
                        decimal(p.get("web_effective_width_mm")), r"mm",
                    ),
                    *equation_triplet(
                        r"W_{ef,Z}", r"\dfrac{I_{z,ef}}{c_{max,ef}}",
                        rf"\dfrac{{{decimal(p.get('Iz_ef_cm4'))}}}{{{decimal(p.get('cmax_ef_cm'))}}}",
                        decimal(p.get("Wef_z_cm3")), r"cm^3",
                    ),
                )),
                *equation_triplet(
                    r"M_{p,Z}", r"Z_z\cdot f_y",
                    rf"{decimal(p.get('Zz_cm3'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                    decimal(p.get("Mp_z_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(
                    r"M_{r,Z}",
                    r"f_y\cdot W_{ef,Z}" if u_weak_axis else r"(f_y-\sigma_r)\cdot W_z",
                    (rf"{decimal(p.get('fy_kn_cm2'))}\cdot {decimal(p.get('Wef_z_cm3'))}"
                     if u_weak_axis else
                     rf"({decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_kn_cm2'))})"
                     rf"\cdot {decimal(p.get('Wz_cm3'))}"),
                    decimal(p.get("Mr_z_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(
                    rf"M_{{cr,{instability_label},Z}}",
                    (r"\dfrac{W_{ef,Z}^2}{W_z}\cdot f_y" if u_weak_axis else
                     r"\dfrac{0,69\cdot E\cdot W_z}{\lambda_{FLM,Z}^2}"),
                    (rf"\dfrac{{{decimal(p.get('Wef_z_cm3'))}^2}}"
                     rf"{{{decimal(p.get('Wz_cm3'))}}}\cdot {decimal(p.get('fy_kn_cm2'))}"
                     if u_weak_axis else
                     rf"\dfrac{{0,69\cdot {decimal(p.get('E_kn_cm2'))}"
                     rf"\cdot {decimal(p.get('Wz_cm3'))}}}{{{decimal(p.get('lambda_flm_z'))}^2}}"),
                    decimal(p.get("Mcr_fla_z_kn_cm" if u_weak_axis else "Mcr_flm_z_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(
                    rf"M_{{n,{instability_label},Z}}", mn_formula_z, mn_substituted_z,
                    decimal(p.get("Mn_fla_z_kn_cm" if u_weak_axis else "Mn_flm_z_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(
                    rf"M_{{Rd,{instability_label},Z}}",
                    rf"\dfrac{{M_{{n,{instability_label},Z}}}}{{\gamma_{{a1}}}}",
                    rf"\dfrac{{{decimal(p.get('Mn_fla_z_kn_cm' if u_weak_axis else 'Mn_flm_z_kn_cm'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}",
                    decimal(p.get("Mrd_fla_z_kn_cm" if u_weak_axis else "Mrd_flm_z_kn_cm")), r"kN\cdot cm",
                ),
            )
            resistance_lines_z = (
                *equation_triplet(
                    r"M_{Rd,max,Z}", r"\dfrac{1,50\cdot W_z\cdot f_y}{\gamma_{a1}}",
                    rf"\dfrac{{1,50\cdot {decimal(p.get('Wz_cm3'))}"
                    rf"\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                    decimal(p.get("Mrd_limit_kn_cm")), r"kN\cdot cm",
                ),
                *equation_triplet(
                    r"M_{z,Rd}",
                    (r"\min(M_{Rd,FLM,Z};M_{Rd,FLA,Z};M_{Rd,max,Z})"
                     if u_weak_axis else rf"\min(M_{{Rd,{instability_label},Z}};M_{{Rd,max,Z}})"),
                    (rf"\min({decimal(p.get('Mrd_flm_z_kn_cm'))};"
                     rf"{decimal(p.get('Mrd_fla_z_kn_cm'))};{decimal(p.get('Mrd_limit_kn_cm'))})"
                     if u_weak_axis else
                     rf"\min({decimal(p.get('Mrd_flm_z_kn_cm'))};"
                     rf"{decimal(p.get('Mrd_limit_kn_cm'))})"),
                    decimal(p.get("Mrd_z_kn_cm")), r"kN\cdot cm",
                ),
            )
            flexion_z_content += (
                f'{spaced_equations(flm_z_lines)}'
                f'{spaced_equations(resistance_lines_z)}'
            )
            if u_weak_axis:
                flexion_z_content += (
                    '<p style="margin:8px 0 4px;color:#57606a">'
                    "FLM da mesa (aplicável quando a borda livre está comprimida; verificação combinada conservadora):</p>"
                )
                weak_axis_flm_lines = (
                    *equation_triplet(
                        r"\lambda_{FLM,Z}", r"\dfrac{b_f}{t_f}",
                        rf"\dfrac{{{decimal(p.get('bf_cm'))}}}{{{decimal(p.get('tf_cm'))}}}",
                        decimal(p.get("lambda_flm_z")),
                    ),
                    *equation_triplet(
                        r"\lambda_{p,FLM,Z}", r"0,38\sqrt{\dfrac{E}{f_y}}",
                        rf"0,38\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                        decimal(p.get("lambda_p_flm_z")),
                    ),
                    *equation_triplet(
                        r"\lambda_{r,FLM,Z}", r"0,83\sqrt{\dfrac{E}{f_y-\sigma_r}}",
                        rf"0,83\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}"
                        rf"{{{decimal(p.get('fy_kn_cm2'))}-{decimal(p.get('sigma_r_flm_z_kn_cm'))}}}}}",
                        decimal(p.get("lambda_r_flm_z")),
                    ),
                    *equation_triplet(
                        r"M_{cr,FLM,Z}", r"\dfrac{0,69EW_z}{\lambda_{FLM,Z}^2}",
                        rf"\dfrac{{0,69\cdot {decimal(p.get('E_kn_cm2'))}\cdot {decimal(p.get('Wz_cm3'))}}}"
                        rf"{{{decimal(p.get('lambda_flm_z'))}^2}}",
                        decimal(p.get("Mcr_flm_z_kn_cm")), r"kN\cdot cm",
                    ),
                    *equation_triplet(
                        r"M_{n,FLM,Z}",
                        (r"M_p" if p.get("lambda_flm_z", 0) <= p.get("lambda_p_flm_z", 0) else
                         (r"M_p-(M_p-M_r)\dfrac{\lambda_{FLM,Z}-\lambda_{p,FLM,Z}}{\lambda_{r,FLM,Z}-\lambda_{p,FLM,Z}}"
                          if p.get("lambda_flm_z", 0) <= p.get("lambda_r_flm_z", 0) else
                          r"M_{cr,FLM,Z}")),
                        (decimal(p.get("Mp_z_kn_cm"))
                         if p.get("lambda_flm_z", 0) <= p.get("lambda_p_flm_z", 0) else
                         (rf"{decimal(p.get('Mp_z_kn_cm'))}-({decimal(p.get('Mp_z_kn_cm'))}-"
                          rf"{decimal(p.get('Mr_flm_z_kn_cm'))})"
                          rf"\dfrac{{{decimal(p.get('lambda_flm_z'))}-{decimal(p.get('lambda_p_flm_z'))}}}"
                          rf"{{{decimal(p.get('lambda_r_flm_z'))}-{decimal(p.get('lambda_p_flm_z'))}}}"
                          if p.get("lambda_flm_z", 0) <= p.get("lambda_r_flm_z", 0) else
                          decimal(p.get("Mcr_flm_z_kn_cm")))),
                        decimal(p.get("Mn_flm_z_kn_cm")), r"kN\cdot cm",
                    ),
                    *equation_triplet(
                        r"M_{Rd,FLM,Z}", r"\dfrac{M_{n,FLM,Z}}{\gamma_{a1}}",
                        rf"\dfrac{{{decimal(p.get('Mn_flm_z_kn_cm'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                        decimal(p.get("Mrd_flm_z_kn_cm")), r"kN\cdot cm",
                    ),
                )
                flexion_z_content += spaced_equations(weak_axis_flm_lines)
            applied = flexion_z_verification.get("applied_kn_cm")
            utilization = flexion_z_verification.get("utilization")
            combination_name = escape(str(flexion_z_verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            utilization_line_z = equation_triplet(
                r"\eta_z", r"\dfrac{|M_{z,Sd}|}{M_{z,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Mrd_z_kn_cm'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
            )
            flexion_z_content += (
                f'{spaced_equations(utilization_line_z)}'
                f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            flexion_z_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de flexão em Z atende somente a perfis W, I e U Laminados.</p>"
            )
        elif flexion_z_verification.get("status") == "not_checked":
            flexion_z_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(flexion_z_verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif flexion_z_verification.get("status") == "not_applicable":
            flexion_z_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(flexion_z_verification.get("detail", "Sem momento fletor em Z.")))}.</p>'
            )
        else:
            flexion_z_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
            )
        shear_y_verification = shear_y.get("verification") or {}
        shear_y_content = (
            '<p style="margin:22px 0 12px;color:#57606a;font-weight:700">'
            + ("Cortante em Y — ABNT NBR 8800:2024, 5.5.2.3-b</p>"
               if memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"} else
               "Cortante em Y — ABNT NBR 8800:2024, 5.4.3.3</p>"
               if memory.get("profile_type") == "T Laminado" else
               "Cortante em Y</p>" if memory.get("profile_type") == "L Laminado"
               else "Cortante em Y — ABNT NBR 8800:2024, 5.4.3.5 e 5.4.3.1.1–1.2</p>")
        )
        if shear_y_verification.get("status") == "checked" and memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            p = shear_y_verification.get("parameters", {})
            if memory.get("profile_type") == "Barra Circular":
                shear_y_content += spaced_equations((
                    *equation_triplet(r"V_{Sd,res}", r"\sqrt{V_{y,Sd}^2+V_{z,Sd}^2}",
                                      decimal(shear_y_verification.get("applied_kn")),
                                      decimal(shear_y_verification.get("applied_kn")), r"kN"),
                    *equation_triplet(r"\tau_{max}", r"\dfrac{4V_{Sd,res}}{3A_g}",
                                      rf"\dfrac{{4\cdot {decimal(shear_y_verification.get('applied_kn'))}}}{{3\cdot {decimal(p.get('Ag_cm2'))}}}",
                                      decimal(p.get("tau_max_kn_cm2")), r"kN/cm^2"),
                    *equation_triplet(r"\tau_{Rd}", r"\dfrac{0,60f_y}{\gamma_{a1}}",
                                      rf"\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("tau_Rd_kn_cm2")), r"kN/cm^2"),
                    *equation_triplet(r"V_{Rd}", r"\dfrac{\tau_{Rd}A_g}{4/3}",
                                      decimal(p.get("VRd_kn")), decimal(p.get("VRd_kn")), r"kN"),
                ))
            else:
                shear_y_content += spaced_equations((
                *equation_triplet(r"\tau_{max}", r"1,5\dfrac{V_{y,Sd}}{A_g}",
                                  rf"1,5\cdot\dfrac{{{decimal(shear_y_verification.get('applied_kn'))}}}{{{decimal(p.get('Ag_cm2'))}}}",
                                  decimal(p.get("tau_max_kn_cm2")), r"kN/cm^2"),
                *equation_triplet(r"\tau_{Rd}", r"\dfrac{0,60f_y}{\gamma_{a1}}",
                                  rf"\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("tau_Rd_kn_cm2")), r"kN/cm^2"),
                *equation_triplet(r"V_{y,Rd}", r"\dfrac{\tau_{Rd}A_g}{1,5}",
                                  decimal(p.get("VRd_kn")), decimal(p.get("VRd_kn")), r"kN"),
                ))
            utilization = shear_y_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            shear_y_content += spaced_equations(equation_triplet(
                r"\eta_{v,Y}", r"\dfrac{V_{Sd,res}}{V_{Rd}}" if memory.get("profile_type") == "Barra Circular" else r"\dfrac{|V_{y,Sd}|}{V_{y,Rd}}",
                rf"\dfrac{{{decimal(shear_y_verification.get('applied_kn'))}}}{{{decimal(p.get('VRd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_y_verification.get("status") == "checked" and memory.get("profile_type") == "T Laminado":
            p = shear_y_verification.get("parameters", {})
            shear_y_content += spaced_equations((
                *equation_triplet(r"\lambda", r"\dfrac{d-t_f}{t_w}",
                                  rf"\dfrac{{{decimal(p.get('d_mm'))}-{decimal(p.get('tf_mm'))}}}"
                                  rf"{{{decimal(p.get('tw_mm'))}}}",
                                  decimal(p.get("lambda"))),
                *equation_triplet(r"k_v", r"1,2", decimal(p.get("kv")), decimal(p.get("kv"))),
                *equation_triplet(r"\lambda_p", r"1,10\sqrt{\dfrac{k_v E}{f_y}}",
                                  decimal(p.get("lambda_p")), decimal(p.get("lambda_p"))),
                *equation_triplet(r"\lambda_r", r"1,37\sqrt{\dfrac{k_v E}{f_y}}",
                                  decimal(p.get("lambda_r")), decimal(p.get("lambda_r"))),
                *equation_triplet(r"A_w", r"2d t_w", decimal(p.get("Aw_cm2")),
                                  decimal(p.get("Aw_cm2")), r"cm^2"),
                *equation_triplet(r"V_{p\ell}", r"0,60 A_w f_y",
                                  rf"0,60\cdot {decimal(p.get('Aw_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Vp_kn")), r"kN"),
                *equation_triplet(r"V_{y,Rd}", r"\dfrac{V_n}{\gamma_{a1}}",
                                  rf"\dfrac{{{decimal(p.get('Vn_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("VRd_kn")), r"kN"),
            ))
            utilization = shear_y_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            shear_y_content += spaced_equations(equation_triplet(
                r"\eta_{v,Y}", r"\dfrac{|V_{y,Sd}|}{V_{y,Rd}}",
                rf"\dfrac{{{decimal(shear_y_verification.get('applied_kn'))}}}{{{decimal(p.get('VRd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_y_verification.get("status") == "checked" and memory.get("profile_type") == "L Laminado":
            p = shear_y_verification.get("parameters", {})
            shear_y_content += spaced_equations((
                *equation_triplet(r"A_w", r"b t", rf"{decimal(p.get('Aw_cm2'))}", decimal(p.get("Aw_cm2")), r"cm^2"),
                *equation_triplet(r"V_p", r"0,60 A_w f_y", rf"0,60\cdot {decimal(p.get('Aw_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}", decimal(p.get("Vp_kn")), r"kN"),
                *equation_triplet(r"V_{y,Rd}", r"\dfrac{V_n}{\gamma_{a1}}", rf"\dfrac{{{decimal(p.get('Vn_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}", decimal(p.get("VRd_kn")), r"kN"),
            ))
            utilization = shear_y_verification.get("utilization")
            status = "APROVADO" if utilization <= 1 else "REPROVADO"
            shear_y_content += spaced_equations(equation_triplet(r"\eta_{v,Y}", r"\dfrac{|V_{y,Sd}|}{V_{y,Rd}}", rf"\dfrac{{{decimal(shear_y_verification.get('applied_kn'))}}}{{{decimal(p.get('VRd_kn'))}}}", rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_y_verification.get("status") == "checked":
            p = shear_y_verification.get("parameters", {})
            u_shear_y = memory.get("profile_type") in {"U Laminado", "U Inclinado Laminado"}
            lambda_y = p["lambda_y"]
            lambda_p_y = p["lambda_p_y"]
            lambda_r_y = p["lambda_r_y"]
            if lambda_y <= lambda_p_y:
                vrd_formula_y = r"\dfrac{V_{p\ell}}{\gamma_{a1}}"
                vrd_substituted_y = (
                    rf"\dfrac{{{decimal(p.get('Vp_y_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )
            elif lambda_y <= lambda_r_y:
                vrd_formula_y = (
                    r"\dfrac{\lambda_{p,Y}}{\lambda_Y}"
                    r"\cdot\dfrac{V_{p\ell}}{\gamma_{a1}}"
                )
                vrd_substituted_y = (
                    rf"\dfrac{{{decimal(lambda_p_y)}}}{{{decimal(lambda_y)}}}"
                    rf"\cdot\dfrac{{{decimal(p.get('Vp_y_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )
            else:
                vrd_formula_y = (
                    r"1,24\cdot\left(\dfrac{\lambda_{p,Y}}{\lambda_Y}\right)^2"
                    r"\cdot\dfrac{V_{p\ell}}{\gamma_{a1}}"
                )
                vrd_substituted_y = (
                    rf"1,24\cdot\left(\dfrac{{{decimal(lambda_p_y)}}}"
                    rf"{{{decimal(lambda_y)}}}\right)^2"
                    rf"\cdot\dfrac{{{decimal(p.get('Vp_y_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )

            lambda_y_substituted = (
                rf"\dfrac{{{decimal(p.get('bf_cm'))}}}{{{decimal(p.get('tf_cm'))}}}"
                if u_shear_y else
                rf"\dfrac{{{decimal(p.get('bf_cm'))}/2}}{{{decimal(p.get('tf_cm'))}}}"
            )
            shear_parameters_y = (
                *equation_triplet(
                    r"A_w", r"2\cdot b_f\cdot t_f",
                    rf"2\cdot {decimal(p.get('bf_cm'))}\cdot {decimal(p.get('tf_cm'))}",
                    decimal(p.get("Aw_cm2")), r"cm^2",
                ),
                *equation_triplet(
                    r"V_{p\ell}", r"0,60\cdot A_w\cdot f_y",
                    rf"0,60\cdot {decimal(p.get('Aw_cm2'))}"
                    rf"\cdot {decimal(p.get('fy_kn_cm2'))}",
                    decimal(p.get("Vp_y_kn")), r"kN",
                ),
                *equation_triplet(
                    r"\lambda_Y",
                    r"\dfrac{b_f}{t_f}" if u_shear_y else r"\dfrac{b_f/2}{t_f}",
                    lambda_y_substituted,
                    decimal(lambda_y),
                ),
                *equation_triplet(
                    r"\lambda_{p,Y}", r"1,10\sqrt{\dfrac{k_v\cdot E}{f_y}}",
                    rf"1,10\sqrt{{\dfrac{{{decimal(p.get('kv_y'))}"
                    rf"\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                    decimal(lambda_p_y),
                ),
                *equation_triplet(
                    r"\lambda_{r,Y}", r"1,37\sqrt{\dfrac{k_v\cdot E}{f_y}}",
                    rf"1,37\sqrt{{\dfrac{{{decimal(p.get('kv_y'))}"
                    rf"\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                    decimal(lambda_r_y),
                ),
            )
            shear_resistance_y = equation_triplet(
                r"V_{y,Rd}", vrd_formula_y, vrd_substituted_y,
                decimal(p.get("Vrd_y_kn")), r"kN",
            )
            shear_y_content += (
                f'{spaced_equations(shear_parameters_y)}'
                f'{spaced_equations(shear_resistance_y)}'
            )
            applied = shear_y_verification.get("applied_kn")
            utilization = shear_y_verification.get("utilization")
            combination_name = escape(str(shear_y_verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            utilization_line_y = equation_triplet(
                r"\eta_{v,Y}", r"\dfrac{|V_{y,Sd}|}{V_{y,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Vrd_y_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
            )
            shear_y_content += (
                f'{spaced_equations(utilization_line_y)}'
                f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            shear_y_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de cortante em Y atende somente a perfis W, I e U Laminados.</p>"
            )
        elif shear_y_verification.get("status") == "not_checked":
            shear_y_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(shear_y_verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif shear_y_verification.get("status") == "not_applicable":
            shear_y_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(shear_y_verification.get("detail", "Sem força cortante em Y.")))}.</p>'
            )
        else:
            shear_y_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
            )
        shear_z = memory.get("shear_z", {})
        shear_z_verification = shear_z.get("verification") or {}
        shear_z_content = (
            '<p style="margin:22px 0 12px;color:#57606a;font-weight:700">'
            + ("Cortante em Z — ABNT NBR 8800:2024, 5.5.2.3-b</p>" if memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"} else
               "Cortante em Z</p>" if memory.get("profile_type") in {"L Laminado", "T Laminado"}
               else "Cortante em Z — ABNT NBR 8800:2024, 5.4.3.1.1–1.2</p>")
        )
        if shear_z_verification.get("status") == "checked" and memory.get("profile_type") in {"Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            p = shear_z_verification.get("parameters", {})
            if memory.get("profile_type") == "Barra Circular":
                shear_z_content += spaced_equations((
                    *equation_triplet(r"V_{Sd,res}", r"\sqrt{V_{y,Sd}^2+V_{z,Sd}^2}",
                                      decimal(shear_z_verification.get("applied_kn")),
                                      decimal(shear_z_verification.get("applied_kn")), r"kN"),
                    *equation_triplet(r"\tau_{max}", r"\dfrac{4V_{Sd,res}}{3A_g}",
                                      rf"\dfrac{{4\cdot {decimal(shear_z_verification.get('applied_kn'))}}}{{3\cdot {decimal(p.get('Ag_cm2'))}}}",
                                      decimal(p.get("tau_max_kn_cm2")), r"kN/cm^2"),
                    *equation_triplet(r"\tau_{Rd}", r"\dfrac{0,60f_y}{\gamma_{a1}}",
                                      rf"\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                      decimal(p.get("tau_Rd_kn_cm2")), r"kN/cm^2"),
                    *equation_triplet(r"V_{Rd}", r"\dfrac{\tau_{Rd}A_g}{4/3}",
                                      decimal(p.get("VRd_kn")), decimal(p.get("VRd_kn")), r"kN"),
                ))
            else:
                shear_z_content += spaced_equations((
                *equation_triplet(r"\tau_{max}", r"1,5\dfrac{V_{z,Sd}}{A_g}",
                                  rf"1,5\cdot\dfrac{{{decimal(shear_z_verification.get('applied_kn'))}}}{{{decimal(p.get('Ag_cm2'))}}}",
                                  decimal(p.get("tau_max_kn_cm2")), r"kN/cm^2"),
                *equation_triplet(r"\tau_{Rd}", r"\dfrac{0,60f_y}{\gamma_{a1}}",
                                  rf"\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}{{{decimal(p.get('gamma_a1'))}}}",
                                  decimal(p.get("tau_Rd_kn_cm2")), r"kN/cm^2"),
                *equation_triplet(r"V_{z,Rd}", r"\dfrac{\tau_{Rd}A_g}{1,5}",
                                  decimal(p.get("VRd_kn")), decimal(p.get("VRd_kn")), r"kN"),
                ))
            utilization = shear_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            shear_z_content += spaced_equations(equation_triplet(
                r"\eta_{v,Z}", r"\dfrac{V_{Sd,res}}{V_{Rd}}" if memory.get("profile_type") == "Barra Circular" else r"\dfrac{|V_{z,Sd}|}{V_{z,Rd}}",
                rf"\dfrac{{{decimal(shear_z_verification.get('applied_kn'))}}}{{{decimal(p.get('VRd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_z_verification.get("status") == "checked" and memory.get("profile_type") == "T Laminado":
            p = shear_z_verification.get("parameters", {})
            lambda_z = p["lambda"]
            lambda_p_z, lambda_r_z = p["lambda_p"], p["lambda_r"]
            if lambda_z <= lambda_p_z:
                vrd_formula_z = r"\dfrac{V_{p\ell}}{\gamma_{a1}}"
                vrd_substituted_z = rf"\dfrac{{{decimal(p.get('Vp_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}"
            elif lambda_z <= lambda_r_z:
                vrd_formula_z = r"\dfrac{\lambda_p}{\lambda}\cdot\dfrac{V_{p\ell}}{\gamma_{a1}}"
                vrd_substituted_z = (
                    rf"\dfrac{{{decimal(lambda_p_z)}}}{{{decimal(lambda_z)}}}"
                    rf"\cdot\dfrac{{{decimal(p.get('Vp_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}"
                )
            else:
                vrd_formula_z = r"1,24\left(\dfrac{\lambda_p}{\lambda}\right)^2\dfrac{V_{p\ell}}{\gamma_{a1}}"
                vrd_substituted_z = (
                    rf"1,24\left(\dfrac{{{decimal(lambda_p_z)}}}{{{decimal(lambda_z)}}}\right)^2"
                    rf"\dfrac{{{decimal(p.get('Vp_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}"
                )
            shear_z_content += spaced_equations((
                *equation_triplet(r"\lambda_Z", r"\dfrac{b_f}{t_f}",
                                  rf"\dfrac{{{decimal(p.get('bf_mm'))}}}{{{decimal(p.get('tf_mm'))}}}",
                                  decimal(lambda_z)),
                *equation_triplet(r"k_v", r"5,0", decimal(p.get("kv")), decimal(p.get("kv"))),
                *equation_triplet(r"\lambda_p", r"1,10\sqrt{\dfrac{k_vE}{f_y}}",
                                  decimal(lambda_p_z), decimal(lambda_p_z)),
                *equation_triplet(r"\lambda_r", r"1,37\sqrt{\dfrac{k_vE}{f_y}}",
                                  decimal(lambda_r_z), decimal(lambda_r_z)),
                *equation_triplet(r"A_w", r"(b_f-t_w)t_f",
                                  decimal(p.get("Aw_cm2")), decimal(p.get("Aw_cm2")), r"cm^2"),
                *equation_triplet(r"V_{p\ell}", r"0,60A_wf_y",
                                  rf"0,60\cdot {decimal(p.get('Aw_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}",
                                  decimal(p.get("Vp_kn")), r"kN"),
                *equation_triplet(r"V_{z,Rd}", vrd_formula_z, vrd_substituted_z,
                                  decimal(p.get("VRd_kn")), r"kN"),
            ))
            utilization = shear_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            shear_z_content += spaced_equations(equation_triplet(
                r"\eta_{v,Z}", r"\dfrac{|V_{z,Sd}|}{V_{z,Rd}}",
                rf"\dfrac{{{decimal(shear_z_verification.get('applied_kn'))}}}"
                rf"{{{decimal(p.get('VRd_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_z_verification.get("status") == "checked" and memory.get("profile_type") == "L Laminado":
            p = shear_z_verification.get("parameters", {})
            shear_z_content += spaced_equations((
                *equation_triplet(r"A_w", r"b t", rf"{decimal(p.get('Aw_cm2'))}", decimal(p.get("Aw_cm2")), r"cm^2"),
                *equation_triplet(r"V_p", r"0,60 A_w f_y", rf"0,60\cdot {decimal(p.get('Aw_cm2'))}\cdot {decimal(p.get('fy_kn_cm2'))}", decimal(p.get("Vp_kn")), r"kN"),
                *equation_triplet(r"V_{z,Rd}", r"\dfrac{V_n}{\gamma_{a1}}", rf"\dfrac{{{decimal(p.get('Vn_kn'))}}}{{{decimal(p.get('gamma_a1'))}}}", decimal(p.get("VRd_kn")), r"kN"),
            ))
            utilization = shear_z_verification.get("utilization")
            status = "APROVADO" if utilization <= 1 else "REPROVADO"
            shear_z_content += spaced_equations(equation_triplet(r"\eta_{v,Z}", r"\dfrac{|V_{z,Sd}|}{V_{z,Rd}}", rf"\dfrac{{{decimal(shear_z_verification.get('applied_kn'))}}}{{{decimal(p.get('VRd_kn'))}}}", rf"{decimal(utilization * 100, 2)}\,\%\quad\mathbf{{{status}}}"))
        elif shear_z_verification.get("status") == "checked":
            p = shear_z_verification.get("parameters", {})
            lambda_z = p["lambda_z"]
            lambda_p_z = p["lambda_p_z"]
            lambda_r_z = p["lambda_r_z"]
            if lambda_z <= lambda_p_z:
                vrd_formula_z = r"\dfrac{V_{p\ell}}{\gamma_{a1}}"
                vrd_substituted_z = (
                    rf"\dfrac{{{decimal(p.get('Vp_z_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )
            elif lambda_z <= lambda_r_z:
                vrd_formula_z = (
                    r"\dfrac{\lambda_{p,Z}}{\lambda_Z}"
                    r"\cdot\dfrac{V_{p\ell}}{\gamma_{a1}}"
                )
                vrd_substituted_z = (
                    rf"\dfrac{{{decimal(lambda_p_z)}}}{{{decimal(lambda_z)}}}"
                    rf"\cdot\dfrac{{{decimal(p.get('Vp_z_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )
            else:
                vrd_formula_z = (
                    r"1,24\cdot\left(\dfrac{\lambda_{p,Z}}{\lambda_Z}\right)^2"
                    r"\cdot\dfrac{V_{p\ell}}{\gamma_{a1}}"
                )
                vrd_substituted_z = (
                    rf"1,24\cdot\left(\dfrac{{{decimal(lambda_p_z)}}}"
                    rf"{{{decimal(lambda_z)}}}\right)^2"
                    rf"\cdot\dfrac{{{decimal(p.get('Vp_z_kn'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}}"
                )

            shear_parameters_z = (
                *equation_triplet(
                    r"A_w", r"d\cdot t_w",
                    rf"{decimal(p.get('d_cm'))}\cdot {decimal(p.get('tw_cm'))}",
                    decimal(p.get("Aw_cm2")), r"cm^2",
                ),
                *equation_triplet(
                    r"V_{p\ell}", r"0,60\cdot A_w\cdot f_y",
                    rf"0,60\cdot {decimal(p.get('Aw_cm2'))}"
                    rf"\cdot {decimal(p.get('fy_kn_cm2'))}",
                    decimal(p.get("Vp_z_kn")), r"kN",
                ),
                *equation_triplet(
                    r"\lambda_Z", r"\dfrac{h}{t_w}",
                    rf"\dfrac{{{decimal(p.get('h_cm'))}}}"
                    rf"{{{decimal(p.get('tw_cm'))}}}",
                    decimal(lambda_z),
                ),
                *equation_triplet(
                    r"\lambda_{p,Z}", r"1,10\sqrt{\dfrac{k_v\cdot E}{f_y}}",
                    rf"1,10\sqrt{{\dfrac{{{decimal(p.get('kv_z'))}"
                    rf"\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                    decimal(lambda_p_z),
                ),
                *equation_triplet(
                    r"\lambda_{r,Z}", r"1,37\sqrt{\dfrac{k_v\cdot E}{f_y}}",
                    rf"1,37\sqrt{{\dfrac{{{decimal(p.get('kv_z'))}"
                    rf"\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                    decimal(lambda_r_z),
                ),
            )
            shear_resistance_z = equation_triplet(
                r"V_{z,Rd}", vrd_formula_z, vrd_substituted_z,
                decimal(p.get("Vrd_z_kn")), r"kN",
            )
            shear_z_content += (
                f'{spaced_equations(shear_parameters_z)}'
                f'{spaced_equations(shear_resistance_z)}'
            )
            applied = shear_z_verification.get("applied_kn")
            utilization = shear_z_verification.get("utilization")
            combination_name = escape(str(shear_z_verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            utilization_line_z = equation_triplet(
                r"\eta_{v,Z}", r"\dfrac{|V_{z,Sd}|}{V_{z,Rd}}",
                rf"\dfrac{{{decimal(applied)}}}{{{decimal(p.get('Vrd_z_kn'))}}}",
                rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
            )
            shear_z_content += (
                f'{spaced_equations(utilization_line_z)}'
                f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
            )
        elif memory.get("profile_type") not in {"W Laminado", "HP Laminado", "I Laminado", "U Laminado", "U Inclinado Laminado", "L Laminado", "Barra Retangular", "Barra Quadrada", "Barra Circular"}:
            shear_z_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de cortante em Z atende somente a perfis W, I e U Laminados.</p>"
            )
        elif shear_z_verification.get("status") == "not_checked":
            shear_z_content += (
                f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                f'{escape(str(shear_z_verification.get("detail", "dados indisponíveis")))}.</p>'
            )
        elif shear_z_verification.get("status") == "not_applicable":
            shear_z_content += (
                f'<p style="margin:5px 0;color:#57606a">'
                f'{escape(str(shear_z_verification.get("detail", "Sem força cortante em Z.")))}.</p>'
            )
        else:
            shear_z_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
            )

        def combined_interaction_content(key: str, title: str, mode: str) -> str:
            verification = (memory.get(key, {}).get("verification") or {})
            interaction_basis = "" if memory.get("profile_type") == "L Laminado" else " — ABNT NBR 8800:2024, 5.5.1.2"
            content = (
                f'<p style="margin:22px 0 12px;color:#57606a;font-weight:700">'
                f'{escape(title)}{escape(interaction_basis)}</p>'
            )
            if verification.get("status") == "checked":
                utilization = verification.get("utilization")
                combination_name = escape(str(verification.get("critical_combination", "—")))
                status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
                p = verification.get("parameters", {})
                if memory.get("profile_type") == "T Laminado":
                    my_sd = verification.get("applied_my_kn_cm") or 0.0
                    mz_sd = verification.get("applied_mz_kn_cm") or 0.0
                    if mz_sd >= 0.1:
                        content += spaced_equations(equation_triplet(
                            r"\eta_{int}", r"\infty", decimal(mz_sd),
                            r"\infty\quad\mathbf{REPROVADO}"))
                    elif mode == "oblique":
                        my_rd = p.get("My_Rd_kn_cm", 0.0)
                        content += spaced_equations(equation_triplet(
                            r"\eta_{ob}", r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}",
                            rf"\dfrac{{{decimal(my_sd)}}}{{{decimal(my_rd)}}}",
                            rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
                    else:
                        n_sd = verification.get("applied_kn") or 0.0
                        n_rd = p.get("Nt_Rd_kn" if mode == "tension" else "Nc_Rd_kn", 0.0)
                        ratio_n = n_sd / n_rd if n_rd else float("inf")
                        if ratio_n >= 0.2:
                            formula = r"\dfrac{N_{Sd}}{N_{Rd}}+\dfrac{8}{9}\dfrac{|M_{y,Sd}|}{M_{y,Rd}}"
                            substituted = rf"\dfrac{{{decimal(n_sd)}}}{{{decimal(n_rd)}}}+\dfrac{{8}}{{9}}\dfrac{{{decimal(my_sd)}}}{{{decimal(p.get('My_Rd_kn_cm'))}}}"
                        else:
                            formula = r"\dfrac{N_{Sd}}{2N_{Rd}}+\dfrac{|M_{y,Sd}|}{M_{y,Rd}}"
                            substituted = rf"\dfrac{{{decimal(n_sd)}}}{{2\cdot {decimal(n_rd)}}}+\dfrac{{{decimal(my_sd)}}}{{{decimal(p.get('My_Rd_kn_cm'))}}}"
                        content += spaced_equations(equation_triplet(
                            r"\eta_{int}", formula, substituted,
                            rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
                    return content
                if memory.get("profile_type") == "Barra Circular":
                    my_sd = verification.get("applied_my_kn_cm") or 0.0
                    mz_sd = verification.get("applied_mz_kn_cm") or 0.0
                    my_rd = p.get("My_Rd_kn_cm") or 0.0
                    mz_rd = p.get("Mz_Rd_kn_cm") or 0.0
                    if mode == "oblique":
                        formula = r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}+\dfrac{|M_{z,Sd}|}{M_{z,Rd}}"
                        substituted = rf"\dfrac{{{decimal(my_sd)}}}{{{decimal(my_rd)}}}+\dfrac{{{decimal(mz_sd)}}}{{{decimal(mz_rd)}}}"
                    else:
                        n_sd = verification.get("applied_kn") or 0.0
                        n_rd = p.get("Nt_Rd_kn" if mode == "tension" else "Nc_Rd_kn") or 0.0
                        ratio_n = n_sd / n_rd if n_rd else float("inf")
                        moment_sum = (
                            rf"\dfrac{{{decimal(my_sd)}}}{{{decimal(my_rd)}}}"
                            rf"+\dfrac{{{decimal(mz_sd)}}}{{{decimal(mz_rd)}}}"
                        )
                        if ratio_n >= 0.2:
                            formula = r"\dfrac{N_{Sd}}{N_{Rd}}+\dfrac{8}{9}\left(\dfrac{|M_{y,Sd}|}{M_{y,Rd}}+\dfrac{|M_{z,Sd}|}{M_{z,Rd}}\right)"
                            substituted = rf"\dfrac{{{decimal(n_sd)}}}{{{decimal(n_rd)}}}+\dfrac{{8}}{{9}}\left({moment_sum}\right)"
                        else:
                            formula = r"\dfrac{N_{Sd}}{2N_{Rd}}+\dfrac{|M_{y,Sd}|}{M_{y,Rd}}+\dfrac{|M_{z,Sd}|}{M_{z,Rd}}"
                            substituted = rf"\dfrac{{{decimal(n_sd)}}}{{2\cdot {decimal(n_rd)}}}+{moment_sum}"
                    content += spaced_equations(equation_triplet(
                        r"\eta_{int}", formula, substituted,
                        rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}"))
                    return content
                if p.get("slender_web_rejected"):
                    slenderness_lines = (
                        *equation_triplet(
                            r"\lambda_{FLA}", r"\dfrac{h}{t_w}",
                            rf"\dfrac{{{decimal(p.get('di_cm'))}}}{{{decimal(p.get('tw_cm'))}}}",
                            decimal(p.get("lambda_fla")),
                        ),
                        *equation_triplet(
                            r"\lambda_{r,FLA}", r"5,70\sqrt{\dfrac{E}{f_y}}",
                            rf"5,70\sqrt{{\dfrac{{{decimal(p.get('E_kn_cm2'))}}}{{{decimal(p.get('fy_kn_cm2'))}}}}}",
                            decimal(p.get("lambda_r_fla")),
                        ),
                        *equation_triplet(
                            r"\eta_{FLA}", r"\dfrac{\lambda_{FLA}}{\lambda_{r,FLA}}\leq 1,0",
                            rf"\dfrac{{{decimal(p.get('lambda_fla'))}}}{{{decimal(p.get('lambda_r_fla'))}}}",
                            rf"{decimal(p.get('slenderness_ratio'), 2)}\quad\mathbf{{REPROVADO}}",
                        ),
                    )
                    content += (
                        f'{spaced_equations(slenderness_lines)}'
                        f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
                    )
                    return content
                my_rd = p.get("My_Rd_kn_cm")
                mz_rd = p.get("Mz_Rd_kn_cm")
                my_sd = verification.get("applied_my_kn_cm")
                mz_sd = verification.get("applied_mz_kn_cm")
                if mode == "oblique":
                    formula = (
                        r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}"
                        r"+\dfrac{|M_{z,Sd}|}{M_{z,Rd}}"
                    )
                    substituted = (
                        rf"\dfrac{{{decimal(my_sd)}}}{{{decimal(my_rd)}}}"
                        rf"+\dfrac{{{decimal(mz_sd)}}}{{{decimal(mz_rd)}}}"
                    )
                    variable = r"\eta_{ob}"
                else:
                    n_sd = verification.get("applied_kn")
                    n_rd = p.get("N_Rd_kn")
                    moment_sum = (
                        r"\dfrac{|M_{y,Sd}|}{M_{y,Rd}}"
                        r"+\dfrac{|M_{z,Sd}|}{M_{z,Rd}}"
                    )
                    substituted_moments = (
                        rf"\dfrac{{{decimal(my_sd)}}}{{{decimal(my_rd)}}}"
                        rf"+\dfrac{{{decimal(mz_sd)}}}{{{decimal(mz_rd)}}}"
                    )
                    if verification.get("interaction_case") == "Nsd/Nrd >= 0,2":
                        formula = (
                            r"\dfrac{N_{Sd}}{N_{Rd}}"
                            r"+\dfrac{8}{9}\left(" + moment_sum + r"\right)"
                        )
                        substituted = (
                            rf"\dfrac{{{decimal(n_sd)}}}{{{decimal(n_rd)}}}"
                            rf"+\dfrac{{8}}{{9}}\left({substituted_moments}\right)"
                        )
                    else:
                        formula = (
                            r"\dfrac{N_{Sd}}{2\cdot N_{Rd}}"
                            r"+\left(" + moment_sum + r"\right)"
                        )
                        substituted = (
                            rf"\dfrac{{{decimal(n_sd)}}}"
                            rf"{{2\cdot {decimal(n_rd)}}}"
                            rf"+\left({substituted_moments}\right)"
                        )
                    variable = r"\eta_{int}"
                interaction_equation = equation_triplet(
                    variable, formula, substituted,
                    rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{status}}}",
                )
                content += (
                    f'{spaced_equations(interaction_equation)}'
                    f'<p style="margin:0 0 3px;color:#57606a">Combinação governante: {combination_name}</p>'
                )
            elif verification.get("status") == "not_checked":
                content += (
                    f'<p style="margin:5px 0;color:#57606a">Não verificado: '
                    f'{escape(str(verification.get("detail", "dados indisponíveis")))}.</p>'
                )
            elif verification.get("status") == "not_applicable":
                content += (
                    f'<p style="margin:5px 0;color:#57606a">'
                    f'{escape(str(verification.get("detail", "sem esforços combinados aplicáveis")))}.</p>'
                )
            else:
                content += (
                    '<p style="margin:5px 0;color:#57606a">'
                    "Execute Verificar modelo após a análise para exibir as equações e os resultados.</p>"
                )
            return content

        flexao_obliqua_content = combined_interaction_content(
            "flexao_obliqua", "Flexão oblíqua", "oblique",
        )
        flexotracao_content = combined_interaction_content(
            "flexotracao", "Flexotração", "axial",
        )
        flexocompressao_content = combined_interaction_content(
            "flexocompressao", "Flexocompressão", "axial",
        )
        scope_notice = ""
        torsion_content = ""
        biaxial_shear_content = ""
        if memory.get("profile_type") in {"W Laminado", "HP Laminado"}:
            if not torsion_summary.get("available"):
                torsion_message = (
                    "Execute a análise e a verificação do modelo para identificar "
                    "as solicitações de torção."
                )
            elif torsion_summary.get("has_torsion"):
                torsion_message = (
                    "Foi detectado uma torção de "
                    f"{formatted(torsion_summary.get('torque_kn_m'), 'kN·m')} "
                    f"na barra {torsion_summary.get('member', '—')}, combinação "
                    f"{torsion_summary.get('combination', '—')}, "
                    f"x = {formatted(torsion_summary.get('position_m'), 'm')}. "
                    "Solicitação não verificada."
                )
            else:
                torsion_message = (
                    "Nenhuma combinação analisada apresentou solicitação de torção "
                    "acima da tolerância numérica adotada."
                )
            torsion_content = (
                '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">'
                'Torção — ABNT NBR 8800:2024, 5.5.2.3</p>'
                f'<p style="margin:5px 0;color:#57606a">{escape(torsion_message)}</p>'
            )
            biaxial_check_status = biaxial_shear_summary.get("status")
            if not biaxial_shear_summary.get("available"):
                biaxial_shear_message = (
                    "Execute a análise e a verificação do modelo para identificar "
                    "os cortantes simultâneos."
                )
            elif biaxial_check_status == "checked":
                p = biaxial_shear_summary.get("parameters") or {}
                utilization = biaxial_shear_summary.get("utilization")
                result_status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
                lambda0_y = float(p.get("lambda0_y"))
                lambda0_z = float(p.get("lambda0_z"))
                chi_formula_y = (
                    r"0,658^{\lambda_{0,y}^2}" if lambda0_y <= 1.5
                    else r"\dfrac{0,877}{\lambda_{0,y}^2}"
                )
                chi_formula_z = (
                    r"0,658^{\lambda_{0,z}^2}" if lambda0_z <= 1.5
                    else r"\dfrac{0,877}{\lambda_{0,z}^2}"
                )
                chi_substituted_y = (
                    rf"0,658^{{{decimal(lambda0_y)}^2}}" if lambda0_y <= 1.5
                    else rf"\dfrac{{0,877}}{{{decimal(lambda0_y)}^2}}"
                )
                chi_substituted_z = (
                    rf"0,658^{{{decimal(lambda0_z)}^2}}" if lambda0_z <= 1.5
                    else rf"\dfrac{{0,877}}{{{decimal(lambda0_z)}^2}}"
                )
                biaxial_shear_message = (
                    "Combinação governante: "
                    f"{escape(str(biaxial_shear_summary.get('critical_combination', '—')))}"
                )
                biaxial_shear_equations = spaced_equations((
                    rf"\tau_{{y,Sd}} = \dfrac{{V_{{y,Sd}}Q_{{z,mesa}}}}{{I_z t_f}} = "
                    rf"\dfrac{{{decimal(biaxial_shear_summary.get('applied_shear_y_kn'))}"
                    rf"\cdot {decimal(p.get('Q_flange_cm3'))}}}"
                    rf"{{{decimal(p.get('Iz_cm4'))}\cdot {decimal(p.get('tf_cm'))}}} = "
                    rf"{decimal(biaxial_shear_summary.get('tau_y_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\tau_{{z,Sd}} = \dfrac{{V_{{z,Sd}}Q_{{y,alma}}}}{{I_y t_w}} = "
                    rf"\dfrac{{{decimal(biaxial_shear_summary.get('applied_shear_z_kn'))}"
                    rf"\cdot {decimal(p.get('Q_web_cm3'))}}}"
                    rf"{{{decimal(p.get('Iy_cm4'))}\cdot {decimal(p.get('tw_cm'))}}} = "
                    rf"{decimal(biaxial_shear_summary.get('tau_z_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\tau_{{Sd}} = \sqrt{{\tau_{{y,Sd}}^2 + \tau_{{z,Sd}}^2}} = "
                    rf"\sqrt{{{decimal(biaxial_shear_summary.get('tau_y_kn_cm2'))}^2"
                    rf"+{decimal(biaxial_shear_summary.get('tau_z_kn_cm2'))}^2}} = "
                    rf"{decimal(biaxial_shear_summary.get('tau_sd_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\tau_{{e,y}} = \dfrac{{1,2\pi^2E}}{{12(1-\nu^2)}}"
                    rf"\left(\dfrac{{t_f}}{{b_f/2}}\right)^2 = "
                    rf"\dfrac{{1,2\pi^2\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{12(1-{decimal(p.get('poisson'))}^2)}}"
                    rf"\left(\dfrac{{{decimal(p.get('tf_cm'))}}}"
                    rf"{{{decimal(p.get('bf_cm') / 2.0)}}}\right)^2 = "
                    rf"{decimal(p.get('tau_e_y_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\tau_{{e,z}} = \dfrac{{5,34\pi^2E}}{{12(1-\nu^2)}}"
                    rf"\left(\dfrac{{t_w}}{{h}}\right)^2 = "
                    rf"\dfrac{{5,34\pi^2\cdot {decimal(p.get('E_kn_cm2'))}}}"
                    rf"{{12(1-{decimal(p.get('poisson'))}^2)}}"
                    rf"\left(\dfrac{{{decimal(p.get('tw_cm'))}}}"
                    rf"{{{decimal(p.get('h_cm'))}}}\right)^2 = "
                    rf"{decimal(p.get('tau_e_z_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\lambda_{{0,y}} = \sqrt{{\dfrac{{0,60f_y}}{{\tau_{{e,y}}}}}} = "
                    rf"\sqrt{{\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('tau_e_y_kn_cm2'))}}}}} = "
                    rf"{decimal(lambda0_y)}",
                    rf"\lambda_{{0,z}} = \sqrt{{\dfrac{{0,60f_y}}{{\tau_{{e,z}}}}}} = "
                    rf"\sqrt{{\dfrac{{0,60\cdot {decimal(p.get('fy_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('tau_e_z_kn_cm2'))}}}}} = "
                    rf"{decimal(lambda0_z)}",
                    rf"\chi_y = {chi_formula_y} = {chi_substituted_y} = "
                    rf"{decimal(p.get('chi_y'))}",
                    rf"\chi_z = {chi_formula_z} = {chi_substituted_z} = "
                    rf"{decimal(p.get('chi_z'))}",
                    rf"\chi_V = \min(\chi_y,\chi_z) = "
                    rf"\min({decimal(p.get('chi_y'))},{decimal(p.get('chi_z'))}) = "
                    rf"{decimal(p.get('chi'))}",
                    rf"\tau_{{Rd}} = \dfrac{{0,60\chi f_y}}{{\gamma_{{a1}}}} = "
                    rf"\dfrac{{0,60\cdot {decimal(p.get('chi'))}"
                    rf"\cdot {decimal(p.get('fy_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('gamma_a1'))}}} = "
                    rf"{decimal(p.get('tau_rd_kn_cm2'))}\,\mathrm{{kN/cm^2}}",
                    rf"\eta_{{V_y,V_z}} = \dfrac{{\tau_{{Sd}}}}{{\tau_{{Rd}}}} = "
                    rf"\dfrac{{{decimal(biaxial_shear_summary.get('tau_sd_kn_cm2'))}}}"
                    rf"{{{decimal(p.get('tau_rd_kn_cm2'))}}} = "
                    rf"{decimal(utilization * 100.0, 2)}\,\%\quad\mathbf{{{result_status}}}",
                ), spacing_px=7)
            elif biaxial_check_status == "not_checked":
                biaxial_shear_message = (
                    "Não foi possível concluir a verificação: "
                    f"{biaxial_shear_summary.get('detail', 'dados indisponíveis')}."
                )
                biaxial_shear_equations = ""
            else:
                biaxial_shear_message = (
                    "Nenhuma combinação analisada apresentou solicitação simultânea "
                    "significativa de cortantes em Y e Z."
                )
                biaxial_shear_equations = ""
            biaxial_shear_content = (
                '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">'
                'Cortantes simultâneos em Y e Z — ABNT NBR 8800:2024, '
                '5.5.1.3 e 5.5.2.3(b), (d)</p>'
                + (
                    biaxial_shear_equations
                    + f'<p style="margin:0 0 3px;color:#57606a">'
                    f'{escape(biaxial_shear_message)}</p>'
                    if biaxial_check_status == "checked"
                    else
                    f'<p style="margin:5px 0;color:#57606a">'
                    f'{escape(biaxial_shear_message)}</p>'
                )
            )
            notes: list[str] = []
            notes.extend(
                str(item) for item in scope_warnings
                if not str(item).startswith("cortantes Y e Z simultâneos fora do escopo")
            )
            if notes:
                scope_notice = (
                    '<div style="margin:10px 0 16px;padding:9px 12px;border-left:3px solid #bf8700;'
                    'background:#fff8c5;color:#6e5100">'
                    '<b>Premissas e limites de verificação do perfil W</b>'
                    '<ul style="margin:5px 0 0;padding-left:20px">'
                    + "".join(f"<li>{escape(note)}</li>" for note in dict.fromkeys(notes))
                    + "</ul></div>"
                )
        members = ", ".join(memory.get("members", ())) or "—"
        element_rows = [
            ("Nome", memory.get("element_name", "—")),
            ("Barra(s) do elemento", members),
            ("Tipo de Perfil", memory.get("profile_type", "—")),
            ("Seção", memory.get("section", "—")),
            ("Material", memory.get("material", "—")),
        ]
        return (
            '<div style="font-family:sans-serif;font-size:13px;color:#24292f">'
            '<h2 style="margin:14px 0 12px;font-size:18px">Memória de cálculo de elemento estrutural</h2>'
            + scope_notice
            + '<h3 style="margin:18px 0 8px;font-size:15px">1. Dados do elemento</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in element_rows) + "</table>"
            '<h3 style="margin:22px 0 8px;font-size:15px">2. Parâmetros geométricos</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in section_rows) + "</table>"
            + '<h3 style="margin:22px 0 8px;font-size:15px">3. Parâmetros materiais</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in material_rows) + "</table>"
            '<h3 style="margin:22px 0 8px;font-size:15px">4. Verificações</h3>'
            + slenderness_content
            + axial_tension_content
            + axial_compression_content
            + torsion_content
            + flexion_y_content
            + flexion_z_content
            + shear_y_content
            + shear_z_content
            + flexao_obliqua_content
            + flexotracao_content
            + flexocompressao_content
            + biaxial_shear_content
            + "</div>"
        )

    def _export_docx(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar memorial de cálculo",
            "Memorial de cálculo.docx",
            "Documento Word (*.docx)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        try:
            export_calculation_memorial_docx(
                self._memorial_html,
                self._equation_latex,
                filename,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(
                self,
                "Falha ao exportar memorial",
                f"Não foi possível gerar o arquivo DOCX.\n\n{exc}",
            )
            return
        MemorialExportSuccessDialog(self).exec()
