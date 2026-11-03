"""Opções e resumo da importação de modelos externos."""

import re
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
)

from osa.transcriptions import ImportOptions

from .profile_selector import ProfileComboBox
from .theme import APP_STYLESHEET

_ICON = Path(__file__).resolve().parents[1] / "resources" / "icons" / "documentation-scroll.svg"
_STYLE = APP_STYLESHEET + """
QDialog#prjImportDialog {
    background: #ffffff; color: #24292f;
    border: 1px solid #d0d7de; border-radius: 0;
}
QComboBox#prjUnitSelector {
    min-height: 30px; height: 30px; padding: 2px 9px;
    border: 1px solid #d0d7de; border-radius: 6px;
    background: #ffffff; color: #57606a;
}
QComboBox#prjUnitSelector:focus { border: 2px solid #0969da; }
QComboBox#prjUnitSelector:disabled {
    background: #f6f8fa; color: #8c959f;
}
QComboBox#prjUnitSelector::drop-down { width: 0; border: 0; }
QComboBox#prjUnitSelector::down-arrow { image: none; }
QFrame#importSource {
    background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
}
QLabel#importInfoTitle { color: #57606a; font-weight: 600; }
QLabel#importInfoBody { color: #57606a; }
QLabel#importFormLabel { color: #57606a; }
QCheckBox { color: #57606a; spacing: 8px; min-height: 30px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border: 1px solid #d0d7de;
    border-radius: 5px; background: #ffffff;
}
QCheckBox::indicator:hover { border-color: #0969da; }
QCheckBox::indicator:checked { background: #0969da; border-color: #0969da; }
QPushButton#secondaryButton {
    min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de;
    border-radius: 7px; background: #f6f8fa; color: #24292f;
}
QPushButton#secondaryButton:hover { background: #eaeef2; }
QPushButton#primaryButton {
    min-height: 34px; padding: 4px 16px; border: 0;
    border-radius: 7px; background: #0969da; color: #ffffff; font-weight: 700;
}
QPushButton#primaryButton:hover { background: #0550ae; }
QFrame#titleBar { background: #e1e4e8; border-bottom: 1px solid #d0d7de; }
QLabel#windowTitle { color: #24292f; font-weight: 600; }
"""
_REPORT_STYLE = (
    APP_STYLESHEET
    + """
QDialog { border: 1px solid #d0d7de; border-radius: 0; }
QListWidget { background: #f6f8fa; border: 0; padding: 8px; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #57606a; }
QListWidget::item:selected { background: #d0d7de; color: #24292f; }
QListWidget:focus { outline: none; border: 0; }
QTextBrowser {
    border: 0; background: #ffffff; color: #24292f; padding: 0;
    selection-background-color: #0969da; selection-color: #ffffff;
}
QPushButton#closeProperties {
    min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de;
    border-radius: 7px; color: #24292f; background: #f6f8fa;
}
QPushButton#closeProperties:hover { background: #eaeef2; }
QPushButton#primaryButton:disabled { background: #d0d7de; color: #8c959f; }
"""
)


def _light_palette():
    """Paleta local dos diálogos claros, independente da aparência do sistema."""
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#ffffff",
        QPalette.ColorRole.WindowText: "#24292f",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f6f8fa",
        QPalette.ColorRole.Text: "#24292f",
        QPalette.ColorRole.Button: "#f6f8fa",
        QPalette.ColorRole.ButtonText: "#24292f",
        QPalette.ColorRole.Highlight: "#0969da",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#6e7781",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#24292f",
    }
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        for role, color in colors.items():
            palette.setColor(group, role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#8c959f"))
    return palette


def _apply_dialog_theme(dialog):
    dialog.setPalette(_light_palette())
    dialog.setStyleSheet(_STYLE)


def _alphanumeric_sort_key(value):
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", str(value))
    )


class PrjImportDialog(QDialog):
    def __init__(self, source_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar modelo - PRJ (Beta)")
        self.setWindowIcon(QIcon(str(_ICON)))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(600, 350)
        self.setMinimumSize(560, 340)
        self.setObjectName("prjImportDialog")
        _apply_dialog_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_ReportTitleBar(self))

        content = QVBoxLayout()
        content.setContentsMargins(12, 12, 12, 12)
        content.setSpacing(8)

        source_panel = QFrame()
        source_panel.setObjectName("importSource")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(12, 8, 12, 8)
        source_layout.setSpacing(8)
        source_caption = QLabel("Modelo de origem")
        source_caption.setObjectName("propertySection")
        source_layout.addWidget(source_caption)
        source = QLabel(Path(source_path).name)
        source.setObjectName("identityDisplay")
        source.setTextFormat(Qt.TextFormat.PlainText)
        source.setWordWrap(True)
        source_layout.addWidget(source)

        unit_fields = QHBoxLayout()
        unit_fields.setContentsMargins(0, 0, 0, 0)
        unit_fields.setSpacing(14)
        self.length_unit = ProfileComboBox()
        self.length_unit.setObjectName("prjUnitSelector")
        self.length_unit.addItems(["cm", "mm", "m"])
        self.length_unit.setAccessibleName("Comprimento no PRJ")
        length_label = QLabel("Comprimento no PRJ")
        length_label.setObjectName("propertySection")
        length_label.setBuddy(self.length_unit)
        length_field = QVBoxLayout()
        length_field.setContentsMargins(0, 0, 0, 0)
        length_field.setSpacing(3)
        length_field.addWidget(length_label)
        length_field.addWidget(self.length_unit)
        unit_fields.addLayout(length_field, 1)

        self.force_unit = ProfileComboBox()
        self.force_unit.setObjectName("prjUnitSelector")
        self.force_unit.addItems(["kgf", "tf", "kN", "N"])
        self.force_unit.setAccessibleName("Força no PRJ")
        force_label = QLabel("Força no PRJ")
        force_label.setObjectName("propertySection")
        force_label.setBuddy(self.force_unit)
        force_field = QVBoxLayout()
        force_field.setContentsMargins(0, 0, 0, 0)
        force_field.setSpacing(3)
        force_field.addWidget(force_label)
        force_field.addWidget(self.force_unit)
        unit_fields.addLayout(force_field, 1)
        source_layout.addLayout(unit_fields)
        content.addWidget(source_panel)

        usage_intro = QLabel(
            "Importação em desenvolvimento, caso haja incompatibilidade ou "
            "inconsistência com o modelo original entre em contato com o desenvolvedor."
        )
        usage_intro.setObjectName("importInfoBody")
        usage_intro.setWordWrap(True)
        content.addWidget(usage_intro)
        usage_scope = QLabel(
            "Serão importados somente vigas e pilares, os demais elementos ainda "
            "não tem suporte no OpenSA."
        )
        usage_scope.setObjectName("importInfoBody")
        usage_scope.setWordWrap(True)
        content.addWidget(usage_scope)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        accept = QPushButton("Importar")
        accept.setObjectName("primaryButton")
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        content.addLayout(buttons)
        outer.addLayout(content)

    def options(self):
        return ImportOptions(
            length_unit=self.length_unit.currentText(),
            force_unit=self.force_unit.currentText(),
            first_floor_elevation_m=0.0,
            include_lower_columns=True,
            preserve_end_offsets=True,
            import_material_properties=True,
            poisson_ratio=0.2,
        )


class _ReportTitleBar(QFrame):
    """Barra do diálogo no padrão do OSA, com arraste da janela sem moldura."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self._drag_offset = None
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel(dialog.windowTitle())
        title.setObjectName("windowTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)
        layout.addStretch()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if not (handle and handle.startSystemMove()):
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.window().pos()
                )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)


class ImportReportDialog(QDialog):
    def __init__(self, report, parent=None, *, review=False):
        super().__init__(parent)
        self.setWindowTitle(
            "Revisão da importação" if review else "Resultado da importação"
        )
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowIcon(QIcon(str(_ICON)))
        self.resize(600, 350)
        self.setMinimumSize(560, 340)
        self.setPalette(_light_palette())
        self.setStyleSheet(_REPORT_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_ReportTitleBar(self))
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.categories = QListWidget()
        self.categories.setAccessibleName("Seções do relatório de importação")
        self.categories.setFixedWidth(170)
        self.categories.setSpacing(8)
        body.addWidget(self.categories)

        content = QVBoxLayout()
        content.setContentsMargins(16, 14, 16, 16)
        content.setSpacing(10)
        self.pages = QStackedWidget()
        self.report_sections = {}
        report_font = self.font()
        report_font_family = report_font.family().replace('"', "'")
        report_font_size = report_font.pointSizeF() or 10
        report_typography = (
            f'font-family: "{report_font_family}"; '
            f"font-size: {report_font_size:g}pt;"
        )
        for category, title, html in self._sections(report):
            browser = QTextBrowser()
            browser.setAccessibleName(title)
            browser.setPalette(_light_palette())
            browser.viewport().setPalette(_light_palette())
            browser.document().setDefaultStyleSheet(
                f"body, p, li, td, th {{ {report_typography} }}"
                "body, p, li, td, th { font-weight: 400; }"
                "body, p, li, td, th { color: #57606a; }"
            )
            title_label = QLabel(title)
            title_label.setObjectName("windowTitle")
            title_label.setTextFormat(Qt.TextFormat.PlainText)
            body_html = html or "<p>Nenhum elemento importado</p>"
            browser.setHtml(
                '<html><body style="color: #24292f; background-color: #ffffff; '
                + report_typography
                + '">'
                + body_html
                + "</body></html>"
            )
            self.categories.addItem(category)
            page = QFrame()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(14)
            page_layout.addWidget(title_label)
            page_layout.addWidget(browser, 1)
            self.pages.addWidget(page)
            self.report_sections[category] = browser
        self.report_text = self.report_sections["Resumo"]
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)
        content.addWidget(self.pages, 1)
        if review:
            self.reviewed = QCheckBox(
                "Revisei unidades, geometria, materiais, apoios, vínculos e cargas no OSA."
            )
            content.addWidget(self.reviewed)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Cancelar" if review else "Fechar")
        close.setObjectName("closeProperties")
        close.setAutoDefault(False)
        close.setDefault(not review)
        close.clicked.connect(self.reject if review else self.accept)
        buttons.addWidget(close)
        if review:
            proceed = QPushButton("Confirmar revisão e processar")
            proceed.setObjectName("primaryButton")
            proceed.setEnabled(False)
            proceed.setDefault(True)
            self.reviewed.toggled.connect(proceed.setEnabled)
            proceed.clicked.connect(self.accept)
            buttons.addWidget(proceed)
        content.addLayout(buttons)
        body.addLayout(content, 1)
        outer.addLayout(body, 1)

    @staticmethod
    def _sections(report):
        counts = report.get("counts", {})
        member_sources = report.get("member_sources", {})
        grouped_members = {
            "Fundações": {},
            "Pilares": {},
            "Vigas": {},
        }
        for member_id, source in member_sources.items():
            if source.get("kind") == "beam":
                category = "Vigas"
            elif source.get("foundation_bar"):
                category = "Fundações"
            elif source.get("kind") == "column":
                category = "Pilares"
            else:
                continue
            source_name = str(
                source.get("source_group_name")
                or source.get("original_name")
                or source.get("source_label")
                or source.get("object_id", "")
            )
            if category == "Vigas":
                group_key = (
                    "beam",
                    source.get("beam_object_id") or source_name,
                )
            else:
                group_key = (category, source_name)
            element = grouped_members[category].setdefault(
                group_key,
                {"name": source_name, "member_ids": []},
            )
            element["member_ids"].append(member_id)

        if member_sources:
            beam_bars = sum(
                len(element["member_ids"])
                for element in grouped_members["Vigas"].values()
            )
            column_bars = sum(
                len(element["member_ids"])
                for element in grouped_members["Pilares"].values()
            )
            foundation_bars = sum(
                len(element["member_ids"])
                for element in grouped_members["Fundações"].values()
            )
        else:
            beam_bars = counts.get("beam_segments", counts.get("beams", 0))
            foundation_bars = counts.get("foundation_columns", 0)
            column_bars = max(0, counts.get("columns", 0) - foundation_bars)
        rows = (
            ("Vigas", f"{beam_bars} barras"),
            ("Pilares", f"{column_bars} barras"),
            ("Fundações", f"{foundation_bars} barras"),
            ("Lajes", "0 placas"),
            ("Paredes", "0 placas"),
        )
        summary_html = (
            "<table cellpadding='6' width='100%'>"
            + "".join(
                f"<tr><td>{escape(category)}</td>"
                f"<td align='right'>{escape(value)}</td></tr>"
                for category, value in rows
            )
            + "</table>"
        )

        def element_table(category):
            elements = grouped_members.get(category, {})
            if not elements:
                return ""
            html = (
                "<table cellpadding='5' width='100%'>"
                "<tr><th align='left'>Elemento no PRJ</th>"
                "<th align='left'>ID(s) das barras</th></tr>"
            )
            for element in sorted(
                elements.values(),
                key=lambda item: _alphanumeric_sort_key(item["name"]),
            ):
                html += (
                    "<tr><td>" + escape(element["name"]) + "</td><td>"
                    + escape(", ".join(element["member_ids"])) + "</td></tr>"
                )
            return html + "</table>"

        return [
            ("Resumo", "Modelo importado com sucesso", summary_html),
            ("Fundações", "Fundações", element_table("Fundações")),
            ("Pilares", "Pilares", element_table("Pilares")),
            ("Vigas", "Vigas", element_table("Vigas")),
            ("Lajes", "Lajes", ""),
            ("Paredes", "Paredes", ""),
        ]
