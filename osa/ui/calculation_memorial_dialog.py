"""Calculation memorial input fields for a structural member or group."""

from html import escape

from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout,
)
from PySide6.QtCore import Qt


class CalculationMemorialDialog(QDialog):
    def __init__(self, memory: dict | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Memorial de cálculo")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(700, 540)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QLabel#windowTitle { color: #24292f; font-size: 13px; font-weight: 600; }"
            "QTextBrowser#calculationMemory { border: 0; background: #ffffff; color: #24292f; "
            "padding: 10px 16px; selection-background-color: #ddf4ff; }"
            "QPushButton#closeProperties { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de; "
            "border-radius: 7px; color: #24292f; background: #f6f8fa; }"
            "QPushButton#closeProperties:hover { background: #eaeef2; }"
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
        self.content.setHtml(self._render(memory or {}))
        outer.addWidget(self.content, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(16, 8, 16, 12)
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setObjectName("closeProperties")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        outer.addLayout(footer)

    @staticmethod
    def _render(memory: dict) -> str:
        def formatted(value, unit: str = "") -> str:
            if value is None or value == "":
                return "—"
            try:
                result = f"{float(value):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
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
        axial_tension = memory.get("axial_tension", {})
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
            return f"{float(value):,.{places}f}".replace(",", "X").replace(".", ",").replace("X", ".")

        axial_tension_content = (
            '<p style="margin:18px 0 12px;color:#57606a;font-weight:700">Tração axial</p>'
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
                    ("Ae = Ct × An = "
                     f"{decimal(ct, 2)} × {decimal(an)} cm² = {decimal(ae)} cm²"),
                ),
                (
                    "Escoamento da seção bruta",
                    ("Nt,Rd1 = Ag × fy / γa1 = "
                     f"{decimal(ag)} cm² × {decimal(fy)} kN/cm² / {decimal(gamma_a1, 2)} "
                     f"= {decimal(nrd1)} kN"),
                ),
                (
                    "Ruptura da seção líquida efetiva",
                    ("Nt,Rd2 = Ae × fu / γa2 = "
                     f"{decimal(ae)} cm² × {decimal(fu)} kN/cm² / {decimal(gamma_a2, 2)} "
                     f"= {decimal(nrd2)} kN"),
                ),
                (
                    "Força axial resistente de cálculo à tração",
                    (f"Nt,Rd = min(Nt,Rd1; Nt,Rd2) = min({decimal(nrd1)}; {decimal(nrd2)}) "
                     f"= {decimal(nrd)} kN"),
                ),
            ]
            applied = verification.get("applied_kn")
            utilization = verification.get("utilization")
            combination_name = escape(str(verification.get("critical_combination", "—")))
            status = "APROVADO" if utilization <= 1.0 else "REPROVADO"
            for index, (check_name, equation) in enumerate(checks):
                top_spacing = "0" if index == 0 else "18px"
                axial_tension_content += (
                    f'<p style="margin:{top_spacing} 0 3px;color:#57606a">{escape(check_name)}</p>'
                    f'<p style="margin:0;color:#57606a">{escape(equation)}</p>'
                )
            axial_tension_content += (
                f'<p style="margin:18px 0 3px;color:#57606a">'
                f'Combinação governante: {combination_name}</p>'
                f'<p style="margin:0;color:#57606a">'
                f'Nt,Sd / Nt,Rd = {decimal(applied)} / {decimal(nrd)} '
                f'= {decimal(utilization * 100.0, 2)} % ({status}).</p>'
            )
        elif memory.get("profile_type") != "W Laminado":
            axial_tension_content += (
                '<p style="margin:5px 0;color:#57606a">'
                "A rotina atual de tração axial atende somente a perfis W Laminados."
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
            '<h3 style="margin:18px 0 8px;font-size:15px">1. Dados do elemento</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in element_rows) + "</table>"
            '<h3 style="margin:22px 0 8px;font-size:15px">2. Parâmetros geométricos</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in section_rows) + "</table>"
            '<h3 style="margin:22px 0 8px;font-size:15px">3. Parâmetros materiais</h3>'
            '<table cellspacing="0" cellpadding="0">' + "".join(row(*item) for item in material_rows) + "</table>"
            '<h3 style="margin:22px 0 8px;font-size:15px">4. Verificações</h3>'
            + axial_tension_content
            + "</div>"
        )
