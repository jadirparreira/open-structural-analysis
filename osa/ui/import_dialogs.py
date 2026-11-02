"""Opções e resumo da importação de modelos externos."""

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
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
from osa.transcriptions.plates import pending_plate_count

from .theme import APP_STYLESHEET

_ICON = Path(__file__).resolve().parents[1] / "resources" / "icons" / "documentation-scroll.svg"
_STYLE = APP_STYLESHEET + """
QDialog#prjImportDialog {
    background: #ffffff; color: #24292f;
    border: 1px solid #d0d7de; border-radius: 0;
}
QComboBox:disabled, QDoubleSpinBox:disabled {
    background: #f6f8fa; color: #8c959f;
}
QFrame#importSource {
    background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
}
QLabel#importSourceCaption { color: #57606a; font-size: 11px; }
QLabel#importSourceName { color: #24292f; font-weight: 600; }
QLabel#importNote {
    color: #57606a; background: #f6f8fa;
    border: 1px solid #d0d7de; border-radius: 6px; padding: 10px 12px;
}
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
QComboBox QAbstractItemView {
    background: #ffffff; color: #24292f; border: 1px solid #d0d7de;
    selection-background-color: #0969da; selection-color: #ffffff; outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 8px; }
QComboBox QAbstractItemView::item:selected { background: #0969da; color: #ffffff; }
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


def _style_combo_popup(combo):
    # O popup é uma janela própria em alguns temas e não herda a paleta do pai.
    combo.setPalette(_light_palette())
    combo.view().setPalette(_light_palette())
    combo.view().viewport().setPalette(_light_palette())
    combo.view().setStyleSheet(
        "QAbstractItemView { background: #ffffff; color: #24292f; "
        "selection-background-color: #0969da; selection-color: #ffffff; }"
        "QAbstractItemView::item:selected { background: #0969da; color: #ffffff; }"
    )


class EberickImportDialog(QDialog):
    def __init__(self, source_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar modelo - PRJ (Beta)")
        self.setWindowIcon(QIcon(str(_ICON)))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(680, 660)
        self.setMinimumSize(640, 610)
        self.setObjectName("prjImportDialog")
        _apply_dialog_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_ReportTitleBar(self))

        content = QVBoxLayout()
        content.setContentsMargins(24, 20, 24, 18)
        content.setSpacing(10)
        heading = QLabel("Configurar importação")
        heading.setObjectName("dialogTitle")
        content.addWidget(heading)
        subtitle = QLabel("Confira o arquivo e ajuste as opções para importar o modelo.")
        subtitle.setObjectName("hint")
        subtitle.setWordWrap(True)
        content.addWidget(subtitle)

        source_panel = QFrame()
        source_panel.setObjectName("importSource")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(12, 8, 12, 8)
        source_layout.setSpacing(2)
        source_caption = QLabel("Arquivo de origem")
        source_caption.setObjectName("importSourceCaption")
        source_layout.addWidget(source_caption)
        source = QLabel(Path(source_path).name)
        source.setObjectName("importSourceName")
        source.setTextFormat(Qt.TextFormat.PlainText)
        source.setWordWrap(True)
        source_layout.addWidget(source)
        content.addWidget(source_panel)

        form = QFormLayout()
        form.setContentsMargins(0, 4, 0, 0)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.length_unit = QComboBox()
        self.length_unit.addItems(["cm", "mm", "m"])
        self.length_unit.setFixedWidth(150)
        _style_combo_popup(self.length_unit)
        length_label = QLabel("Comprimento no PRJ")
        length_label.setObjectName("importFormLabel")
        form.addRow(length_label, self.length_unit)
        self.force_unit = QComboBox()
        self.force_unit.addItems(["kgf", "tf", "kN", "N"])
        self.force_unit.setFixedWidth(150)
        _style_combo_popup(self.force_unit)
        force_label = QLabel("Força no PRJ")
        force_label.setObjectName("importFormLabel")
        form.addRow(force_label, self.force_unit)
        self.first_floor_z = QDoubleSpinBox()
        self.first_floor_z.setRange(-100000, 100000)
        self.first_floor_z.setDecimals(4)
        self.first_floor_z.setSuffix(" m")
        self.first_floor_z.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.first_floor_z.setFixedWidth(150)
        elevation_label = QLabel("Cota do topo do baldrame no OSA")
        elevation_label.setObjectName("importFormLabel")
        form.addRow(elevation_label, self.first_floor_z)
        self.poisson_ratio = QDoubleSpinBox()
        self.poisson_ratio.setRange(-0.99, 0.49)
        self.poisson_ratio.setDecimals(3)
        self.poisson_ratio.setSingleStep(0.01)
        self.poisson_ratio.setValue(0.2)
        self.poisson_ratio.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.poisson_ratio.setToolTip(
            "Valor informado para o material; não é lido do PRJ."
        )
        self.poisson_ratio.setFixedWidth(150)
        poisson_label = QLabel("Coeficiente de Poisson adotado")
        poisson_label.setObjectName("importFormLabel")
        form.addRow(poisson_label, self.poisson_ratio)
        content.addLayout(form)

        options_heading = QLabel("Opções do modelo")
        options_heading.setObjectName("propertySection")
        content.addWidget(options_heading)
        self.lower_columns = QCheckBox(
            "Prolongar pilares até o assentamento das sapatas"
        )
        self.lower_columns.setToolTip(
            "Usa a profundidade individual lida do PRJ. Blocos e outros tipos ainda não foram mapeados."
        )
        self.lower_columns.setChecked(True)
        self.offsets = QCheckBox(
            "Representar deslocamentos de extremidade com ligações rígidas"
        )
        self.offsets.setChecked(True)
        self.material_properties = QCheckBox(
            "Usar propriedades de concreto lidas do PRJ"
        )
        self.material_properties.setChecked(True)
        self.material_properties.toggled.connect(self.poisson_ratio.setEnabled)
        checks = QVBoxLayout()
        checks.setContentsMargins(0, 0, 0, 0)
        checks.setSpacing(2)
        for widget in (self.lower_columns, self.offsets, self.material_properties):
            checks.addWidget(widget)
        content.addLayout(checks)
        note = QLabel(
            "O OSA receberá geometria e seções retangulares. Confira as unidades "
            "e a referência do topo do baldrame. Lajes serão preservadas para a "
            "futura integração com placas. Tipos de apoio, liberações e cargas "
            "permanecem pendentes de calibração."
        )
        note.setObjectName("importNote")
        note.setWordWrap(True)
        content.addWidget(note)
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
            first_floor_elevation_m=self.first_floor_z.value(),
            include_lower_columns=self.lower_columns.isChecked(),
            preserve_end_offsets=self.offsets.isChecked(),
            import_material_properties=self.material_properties.isChecked(),
            poisson_ratio=self.poisson_ratio.value(),
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
        self.resize(820, 560)
        self.setMinimumSize(720, 480)
        self.setSizeGripEnabled(True)
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
        for category, title, html in self._sections(report):
            browser = QTextBrowser()
            browser.setAccessibleName(title)
            browser.setPalette(_light_palette())
            browser.viewport().setPalette(_light_palette())
            browser.document().setDefaultStyleSheet(
                "body, p, li, td, th { color: #24292f; }"
                "h2 { color: #24292f; font-size: 20px; font-weight: 700; "
                "margin-top: 0; margin-bottom: 14px; }"
            )
            browser.setHtml(
                '<html><body style="color: #24292f; background-color: #ffffff;">'
                + "<h2>"
                + escape(title)
                + "</h2>"
                + html
                + "</body></html>"
            )
            self.categories.addItem(category)
            self.pages.addWidget(browser)
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
        rows = [
            ("Nós", counts.get("nodes", 0)),
            ("Barras", counts.get("members", 0)),
            ("Vigas", counts.get("beam_groups", counts.get("beams", 0))),
            ("Trechos de viga", counts.get("beam_segments", counts.get("beams", 0))),
            ("Trechos de pilar", counts.get("columns", 0)),
            ("Ligações rígidas", counts.get("rigid_links", 0)),
            ("Cargas transcritas", counts.get("applied_loads", 0)),
            ("Bases de sapatas posicionadas", counts.get("support_candidates", 0)),
            ("Lajes aguardando placas", counts.get("pending_plates", 0)),
        ]
        options = report.get("options", {})
        html = (
            "<p>"
            + (
                "Geometria de barras importada; lajes aguardam elementos de placa."
                if pending_plate_count(report)
                else "O relatório acompanha o projeto ao salvar e reabrir o .osa."
            )
            + "</p>"
        )
        html += (
            "<p><b>Origem:</b> "
            + escape(report.get("source", {}).get("filename", ""))
            + "</p>"
        )
        if report.get("internal_version_code") is not None:
            html += (
                "<p><b>Código interno do PRJ:</b> "
                + escape(str(report["internal_version_code"]))
                + ". Esse código é apenas uma identificação interna do arquivo.</p>"
            )
        if report.get("compatibility", {}).get("mode") == "structural_probe":
            html += (
                "<p><b>Compatibilidade experimental:</b> o lançamento foi reconhecido "
                "pela estrutura dos registros. Confira a geometria e os dados "
                "deste projeto no OSA.</p>"
            )
        html += "<p><b>Unidades adotadas na origem:</b> " + escape(
            str(options.get("length_unit", ""))
        )
        html += (
            " e "
            + escape(str(options.get("force_unit", "")))
            + ". Destino: m, mm e kN.</p>"
        )
        html += (
            "<table cellpadding='5' width='100%'>"
            + "".join(
                f"<tr><td>{escape(name)}</td><td align='right'><b>{escape(str(value))}</b></td></tr>"
                for name, value in rows
            )
            + "</table>"
        )
        html += "<p>O modelo é editável e pode ser salvo como .osa.</p>"
        sections = [("Resumo", "Resumo da importação", html)]
        supports = report.get("support_candidates", ())
        html = "<p>Não há bases de sapata posicionadas nesta importação.</p>"
        if supports:
            html = "<p>Referência: topo do baldrame. Tipos de vínculo ainda não aplicados.</p>"
            html += "<table cellpadding='4'><tr><th>Pilar</th><th>Profundidade (m)</th><th>Cota da base (m)</th></tr>"
            for support in supports:
                html += (
                    "<tr><td>"
                    + escape(str(support["column_name"]))
                    + "</td><td>"
                    + escape(f"{support['settlement_depth_m']:.3f}")
                    + "</td><td>"
                    + escape(f"{support['elevation_m']:.3f}")
                    + "</td></tr>"
                )
            html += "</table>"
        sections.append(("Sapatas", "Assentamento das sapatas", html))
        html = "<p>Não há lajes aguardando integração por elementos de placa neste relatório.</p>"
        if pending_plate_count(report):
            html = "<p>O processamento aguarda a implementação dos elementos de placa e o mapeamento completo dessas lajes.</p><ul>"
            for plate in report["plate_transfer"]["records"]:
                if plate.get("status") != "imported":
                    html += (
                        "<li>"
                        + escape(str(plate["name"]))
                        + " — "
                        + escape(str(plate.get("floor_name") or "pavimento a conferir"))
                        + ". Geometria de placa pendente.</li>"
                    )
            html += "</ul>"
        sections.append(("Lajes", "Lajes preservadas para placas", html))
        html = "<ul>"
        for warning in report.get("warnings", ()):
            # Compatibilidade com relatórios salvos pela primeira integração.
            warning = str(warning).replace(
                "Cargas, peso próprio, paredes e combinações",
                "Cargas, paredes e combinações",
            )
            html += "<li>" + escape(warning) + "</li>"
        html += "</ul><p>A importação "
        html += "não comprova equivalência estrutural com o projeto original.</p>"
        html += "<p>O peso próprio é aplicado pelas ferramentas do OSA.</p>"
        sections.append(("Conferência", "Dados que exigem conferência", html))
        return sections
