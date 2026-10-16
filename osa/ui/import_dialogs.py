"""Opções e resumo da importação de modelos externos."""

from html import escape
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from osa.transcriptions import ImportOptions

_ICON = Path(__file__).resolve().parents[1] / "resources" / "icons" / "eberick.png"
_STYLE = """
QDialog { background: #ffffff; color: #24292f; }
QLabel, QCheckBox { color: #24292f; }
QComboBox, QDoubleSpinBox, QLineEdit {
    min-height: 28px; padding: 2px 6px; background: #ffffff; color: #24292f;
    border: 1px solid #d0d7de; border-radius: 5px;
    selection-background-color: #0969da; selection-color: #ffffff;
}
QComboBox:disabled, QDoubleSpinBox:disabled { background: #f6f8fa; color: #8c959f; }
QComboBox QAbstractItemView {
    background: #ffffff; color: #24292f; border: 1px solid #d0d7de;
    selection-background-color: #0969da; selection-color: #ffffff;
    outline: 0;
}
QComboBox QAbstractItemView::item { min-height: 28px; padding: 3px 8px; }
QComboBox QAbstractItemView::item:selected { background: #0969da; color: #ffffff; }
QPushButton { min-height: 32px; padding: 4px 16px; border: 1px solid #d0d7de;
              border-radius: 6px; background: #f6f8fa; color: #24292f; }
QPushButton#primary { background: #0969da; color: white; border: none; }
QPushButton:disabled { background: #eaeef2; color: #8c959f; }
QTextBrowser {
    border: 1px solid #d0d7de; background: #ffffff; color: #24292f; padding: 8px;
    selection-background-color: #0969da; selection-color: #ffffff;
}
QScrollBar:vertical { background: #f6f8fa; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #afb8c1; min-height: 24px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


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


def _header(layout, title, subtitle):
    row = QHBoxLayout()
    if _ICON.exists():
        image = QLabel()
        image.setPixmap(
            QPixmap(str(_ICON)).scaled(
                42,
                58,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        row.addWidget(image)
    texts = QVBoxLayout()
    heading = QLabel(title)
    heading.setStyleSheet("font-size: 17px; font-weight: 600;")
    texts.addWidget(heading)
    hint = QLabel(subtitle)
    hint.setWordWrap(True)
    hint.setStyleSheet("color: #57606a;")
    texts.addWidget(hint)
    row.addLayout(texts, 1)
    layout.addLayout(row)


class EberickImportDialog(QDialog):
    def __init__(self, source_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importar projeto Eberick")
        self.setWindowIcon(QIcon(str(_ICON)))
        self.setMinimumWidth(540)
        _apply_dialog_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(14)
        _header(
            layout,
            "Importar do Eberick",
            "Importação experimental do lançamento estrutural",
        )
        source = QLabel(Path(source_path).name)
        source.setTextFormat(Qt.TextFormat.PlainText)
        source.setWordWrap(True)
        layout.addWidget(source)
        form = QFormLayout()
        self.length_unit = QComboBox()
        self.length_unit.addItems(["cm", "mm", "m"])
        _style_combo_popup(self.length_unit)
        form.addRow("Comprimento no PRJ", self.length_unit)
        self.force_unit = QComboBox()
        self.force_unit.addItems(["kgf", "tf", "kN", "N"])
        _style_combo_popup(self.force_unit)
        form.addRow("Força no PRJ", self.force_unit)
        self.first_floor_z = QDoubleSpinBox()
        self.first_floor_z.setRange(-100000, 100000)
        self.first_floor_z.setDecimals(4)
        self.first_floor_z.setSuffix(" m")
        form.addRow("Cota do primeiro pavimento no OSA", self.first_floor_z)
        self.poisson_ratio = QDoubleSpinBox()
        self.poisson_ratio.setRange(-0.99, 0.49)
        self.poisson_ratio.setDecimals(3)
        self.poisson_ratio.setSingleStep(0.01)
        self.poisson_ratio.setValue(0.2)
        self.poisson_ratio.setToolTip(
            "Valor informado para o material; não é lido do PRJ."
        )
        form.addRow("Coeficiente de Poisson adotado", self.poisson_ratio)
        layout.addLayout(form)
        self.lower_columns = QCheckBox(
            "Representar trecho inferior pela altura do primeiro pavimento"
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
        for widget in (self.lower_columns, self.offsets, self.material_properties):
            layout.addWidget(widget)
        note = QLabel(
            "O OSA receberá geometria e seções retangulares. As unidades e a "
            "cota inferior são hipóteses a conferir. Apoios, liberações e cargas "
            "ainda não calibrados serão preservados no relatório, sem aplicação "
            "automática ao modelo de cálculo."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #805b10; background: #fff8df; padding: 10px;")
        layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        accept = QPushButton("Importar")
        accept.setObjectName("primary")
        accept.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(accept)
        layout.addLayout(buttons)

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


class ImportReportDialog(QDialog):
    def __init__(self, report, parent=None, *, review=False):
        super().__init__(parent)
        self.setWindowTitle(
            "Revisão da importação" if review else "Resultado da importação"
        )
        self.setWindowIcon(QIcon(str(_ICON)))
        self.resize(660, 590)
        _apply_dialog_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        _header(
            layout,
            "Revisão da importação" if review else "Modelo importado",
            "O relatório acompanha o projeto ao salvar e reabrir o .osa.",
        )
        counts = report.get("counts", {})
        rows = [
            ("Nós", counts.get("nodes", 0)),
            ("Barras", counts.get("members", 0)),
            ("Vigas", counts.get("beams", 0)),
            ("Trechos de pilar", counts.get("columns", 0)),
            ("Ligações rígidas", counts.get("rigid_links", 0)),
            ("Cargas transcritas", counts.get("applied_loads", 0)),
        ]
        options = report.get("options", {})
        html = (
            "<p><b>Origem:</b> "
            + escape(report.get("source", {}).get("filename", ""))
            + "</p>"
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
            "<table cellpadding='5'>"
            + "".join(
                f"<tr><td>{escape(name)}</td><td><b>{escape(str(value))}</b></td></tr>"
                for name, value in rows
            )
            + "</table><h3>Dados que exigem conferência</h3><ul>"
        )
        for warning in report.get("warnings", ()):
            # Compatibilidade com relatórios salvos pela primeira integração.
            warning = str(warning).replace(
                "Cargas, peso próprio, paredes e combinações",
                "Cargas, paredes e combinações",
            )
            html += "<li>" + escape(warning) + "</li>"
        html += "</ul><p>O modelo é editável e pode ser salvo como .osa. A importação "
        html += "não comprova equivalência estrutural com o projeto original.</p>"
        html += "<p>O peso próprio é aplicado pelas ferramentas do OSA.</p>"
        self.report_text = QTextBrowser()
        self.report_text.setPalette(_light_palette())
        self.report_text.viewport().setPalette(_light_palette())
        self.report_text.document().setDefaultStyleSheet(
            "body, p, li, td, h3 { color: #24292f; } h3 { margin-top: 14px; }"
        )
        self.report_text.setHtml(
            '<html><body style="color: #24292f; background-color: #ffffff;">'
            + html
            + "</body></html>"
        )
        layout.addWidget(self.report_text, 1)
        if review:
            self.reviewed = QCheckBox(
                "Revisei unidades, geometria, materiais, apoios, vínculos e cargas no OSA."
            )
            layout.addWidget(self.reviewed)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Cancelar" if review else "Fechar")
        close.clicked.connect(self.reject if review else self.accept)
        buttons.addWidget(close)
        if review:
            proceed = QPushButton("Confirmar revisão e processar")
            proceed.setObjectName("primary")
            proceed.setEnabled(False)
            self.reviewed.toggled.connect(proceed.setEnabled)
            proceed.clicked.connect(self.accept)
            buttons.addWidget(proceed)
        layout.addLayout(buttons)
