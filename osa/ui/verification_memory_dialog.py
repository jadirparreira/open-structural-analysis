"""Readable calculation summary for the current W rolled verification."""

from html import escape

from PySide6.QtWidgets import QTextBrowser

from .common import *


class VerificationMemoryDialog(QDialog):
    """Show the stored calculation inputs and governing verification result."""

    def __init__(self, memory: dict | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Memória de cálculo")
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
        titlebar.setObjectName("titleBar")
        titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar)
        titlebar_layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel("Memória de cálculo")
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
        if not memory:
            return (
                '<h2 style="font-size:16px">Memória indisponível</h2>'
                '<p style="color:#57606a">Execute a verificação do modelo para gerar a memória de cálculo.</p>'
            )

        def row(label: str, value: object) -> str:
            return (
                "<tr>"
                f'<td style="padding:6px 18px 6px 0;color:#57606a">{escape(label)}</td>'
                f'<td style="padding:6px 0;font-weight:600">{escape(str(value))}</td>'
                "</tr>"
            )

        def number(value: object, digits: int = 3) -> str:
            try:
                return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except (TypeError, ValueError):
                return "—"

        def section(title: str, rows: list[tuple[str, object]]) -> str:
            table_rows = "".join(row(label, value) for label, value in rows)
            return (
                f'<h3 style="margin:20px 0 6px;font-size:13px;color:#24292f">{escape(title)}</h3>'
                f'<table cellspacing="0" cellpadding="0">{table_rows}</table>'
            )

        lengths = memory.get("lengths_cm", {})
        capacities = memory.get("capacities", {})
        critical = memory.get("critical_values", {})
        members = ", ".join(memory.get("members", ())) or "—"
        entries = [
            section("Elemento e material", [
                ("Norma de referência", memory.get("standard", "ABNT NBR 8800")),
                ("Barra governante", memory.get("element", "—")),
                ("Barras do elemento", members),
                ("Perfil", memory.get("profile", "—")),
                ("Material", memory.get("material", "—")),
                ("fy", f"{number(memory.get('fy_kn_m2'))} kN/m²"),
                ("fu", f"{number(memory.get('fu_kn_m2'))} kN/m²"),
                ("E", f"{number(memory.get('E_kn_cm2'))} kN/cm²"),
                ("G", f"{number(memory.get('G_kn_cm2'))} kN/cm²"),
                ("γa1", number(memory.get("gamma_a1"))),
            ]),
            section("Comprimentos e parâmetros", [
                ("Ly", f"{number(lengths.get('Ly'))} cm"),
                ("Lz", f"{number(lengths.get('Lz'))} cm"),
                ("Lt", f"{number(lengths.get('Lt'))} cm"),
                ("Lb", f"{number(lengths.get('Lb'))} cm"),
                ("Cb", number(memory.get("Cb"))),
            ]),
            section("Resistências de cálculo", [
                ("Tração", f"{number(capacities.get('tension_kn'))} kN"),
                ("Compressão", f"{number(capacities.get('compression_kn'))} kN"),
                ("Flexão X-X", f"{number(capacities.get('moment_x_kn_m'))} kN·m"),
                ("Flexão Y-Y", f"{number(capacities.get('moment_y_kn_m'))} kN·m"),
                ("Cisalhamento X-X", f"{number(capacities.get('shear_x_kn'))} kN"),
                ("Cisalhamento Y-Y", f"{number(capacities.get('shear_y_kn'))} kN"),
            ]),
            section("Verificação governante", [
                ("Combinação", memory.get("critical_combination", "—")),
                ("Verificação crítica", memory.get("critical_check", "—")),
                ("Taxa de solicitação", f"{number(float(memory['utilization']) * 100, 1)}%"
                 if memory.get("utilization") is not None else "Não verificado"),
            ]),
        ]
        restraints = memory.get("restraints", {})
        for mode, data in restraints.get("modes", {}).items():
            interval = data.get("governing_interval_m", ())
            mode_rows = []
            if len(interval) == 2:
                mode_rows.append(("Maior trecho", f"{number(interval[0])} a {number(interval[1])} m ao longo do elemento"))
            for point in data.get("points", ()):
                stiffness = point["stiffness"]
                unit = "kN·m/rad" if mode in {"Lt", "Lb"} else "kN/m"
                measured = "restrição ideal" if stiffness == float("inf") else f"{number(stiffness)} {unit}"
                required = point.get("required_stiffness", 0.0)
                required_text = ("contenção elástica insuficiente" if required == float("inf")
                                 else f"mínimo {number(required)} {unit}")
                state = point.get("reason", "considerado" if point["accepted"] else "não considerado")
                mode_rows.append((f"{point['node']} · {number(point['position_m'])} m",
                                  f"{state} · {measured} · {required_text}"))
            entries.append(section(f"Contenções de {mode}", mode_rows))
        if restraints.get("issues"):
            entries.append(section("Verificação não concluída", [("Motivo", issue) for issue in restraints["issues"]]))
        if restraints.get("notes"):
            entries.append(section("Premissas e verificações pendentes", [("", note) for note in restraints["notes"]]))
        if critical:
            entries.append(section("Solicitações e relações", [
                ("N", f"{number(critical.get('axial_kn'))} kN"),
                ("Mx", f"{number(critical.get('moment_x_kn_m'))} kN·m"),
                ("My", f"{number(critical.get('moment_y_kn_m'))} kN·m"),
                ("Vx", f"{number(critical.get('shear_x_kn'))} kN"),
                ("Vy", f"{number(critical.get('shear_y_kn'))} kN"),
                ("Relação axial", number(critical.get("axial_ratio"))),
                ("Relação flexão X-X", number(critical.get("moment_x_ratio"))),
                ("Relação flexão Y-Y", number(critical.get("moment_y_ratio"))),
                ("Relação cisalhamento X-X", number(critical.get("shear_x_ratio"))),
                ("Relação cisalhamento Y-Y", number(critical.get("shear_y_ratio"))),
                ("Interação", number(critical.get("interaction_ratio"))),
            ]))

        return (
            '<div style="font-family: sans-serif;font-size:12px">'
            '<p style="color:#57606a">Resumo dos parâmetros e resultados registrados pela rotina de verificação.</p>'
            '<p style="padding:9px 11px;background:#fff8c5;border-radius:6px;color:#57606a">'
            'Cb está provisoriamente definido como 1,0. Os comprimentos são determinados pelas '
            'contenções analíticas do modelo, com as premissas e pendências registradas abaixo.</p>'
            + "".join(entries)
            + "</div>"
        )
