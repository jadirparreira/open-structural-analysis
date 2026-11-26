"""Diálogo do laudo técnico da estrutura em LaTeX/PDF."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from osa.reports.structure_report import (
    LIMIT_STATE_LABELS,
    MAX_DEFORMED_FIGURES,
    ReportOptions,
    default_deformed_combinations,
    export_structure_report,
)

from .latex_export import PDF_FILTER, TEX_FILTER, destination_with_suffix, run_with_progress, warn_export_problem


class StructureReportDialog(QDialog):
    """Coleta os dados da capa e as deformadas, e exporta o laudo."""

    def __init__(self, model, model_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.model_path = model_path
        self.exported_path: Path | None = None
        self.setWindowTitle("Laudo estrutural")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setMinimumWidth(520)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; }"
            "QLabel { color: #24292f; }"
            "QLabel#windowTitle { font-size: 13px; font-weight: 600; }"
            "QLabel#hint { color: #57606a; }"
            "QLineEdit, QDoubleSpinBox, QListWidget { border: 1px solid #d0d7de; border-radius: 6px; "
            "padding: 4px 6px; color: #24292f; background: #ffffff; }"
            "QPushButton { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de; "
            "border-radius: 7px; color: #24292f; background: #f6f8fa; }"
            "QPushButton:hover { background: #eaeef2; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 14)
        layout.setSpacing(10)
        title = QLabel("Laudo técnico da estrutura")
        title.setObjectName("windowTitle")
        layout.addWidget(title)
        hint = QLabel(
            "Gera um laudo em LaTeX com capa, sumário, ações, combinações, ELU, ELS, "
            "deformadas e quantitativo, a partir da análise e da verificação atuais."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        defaults = ReportOptions()
        self.title_input = QLineEdit(defaults.title)
        self.subject_input = QLineEdit(model_path.stem if model_path else "")
        self.subject_input.setPlaceholderText("Ex.: Cobertura metálica – Galpão")
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("Ex.: São Paulo/SP")
        self.author_input = QLineEdit()
        self.author_input.setPlaceholderText("Nome e registro profissional")
        self.revision_input = QLineEdit(defaults.revision)
        self.scale_input = QDoubleSpinBox()
        self.scale_input.setRange(0.0, 1_000_000.0)
        self.scale_input.setDecimals(0)
        self.scale_input.setSpecialValueText("Automática")
        self.scale_input.setValue(0.0)
        form.addRow("Título", self.title_input)
        form.addRow("Obra", self.subject_input)
        form.addRow("Local", self.location_input)
        form.addRow("Responsável", self.author_input)
        form.addRow("Revisão", self.revision_input)
        form.addRow("Escala da deformada", self.scale_input)
        layout.addLayout(form)

        layout.addWidget(QLabel(f"Deformadas no laudo (até {MAX_DEFORMED_FIGURES})"))
        self.combination_list = QListWidget()
        self.combination_list.setMaximumHeight(150)
        available = {result.load_reference for result in getattr(model, "analysis_results", ())}
        selected = set(default_deformed_combinations(model))
        for combination in model.load_combinations.values():
            if combination.name not in available:
                continue
            label = f"{combination.name} ({LIMIT_STATE_LABELS.get(combination.limit_state, combination.limit_state)})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, combination.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if combination.name in selected else Qt.CheckState.Unchecked)
            self.combination_list.addItem(item)
        if self.combination_list.count() == 0:
            self.combination_list.addItem(QListWidgetItem("Processe a análise para incluir deformadas."))
            self.combination_list.setEnabled(False)
        layout.addWidget(self.combination_list)
        if not getattr(model, "verification_results", None):
            warning = QLabel("A verificação (VERIFY) ainda não foi executada: o ELU sairá sem resultados.")
            warning.setObjectName("hint")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #d0d7de;")
        layout.addWidget(separator)
        footer = QHBoxLayout()
        self.export_button = QPushButton("Exportar")
        self.export_button.setObjectName("exportReport")
        self.export_button.clicked.connect(self._export)
        footer.addWidget(self.export_button)
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.clicked.connect(self.reject)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def options(self) -> ReportOptions:
        combinations = tuple(
            self.combination_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.combination_list.count())
            if self.combination_list.item(index).checkState() == Qt.CheckState.Checked
            and self.combination_list.item(index).data(Qt.ItemDataRole.UserRole)
        )
        return ReportOptions(
            title=self.title_input.text().strip() or ReportOptions().title,
            subject=self.subject_input.text().strip(),
            location=self.location_input.text().strip(),
            author=self.author_input.text().strip(),
            revision=self.revision_input.text().strip() or "0",
            model_file=self.model_path.name if self.model_path else "",
            deformed_combinations=combinations[:MAX_DEFORMED_FIGURES],
            deformation_scale=self.scale_input.value() or None,
        )

    def _export(self) -> None:
        suggested = f"Laudo - {self.subject_input.text().strip() or 'estrutura'}.pdf"
        if self.model_path:
            suggested = str(self.model_path.with_name(suggested))
        filename, selected_filter = QFileDialog.getSaveFileName(
            self, "Exportar laudo estrutural", suggested, f"{PDF_FILTER};;{TEX_FILTER}",
        )
        if not filename:
            return
        destination = destination_with_suffix(filename, selected_filter, (".pdf", ".tex"))
        options = self.options()
        try:
            export = run_with_progress(
                self,
                "Gerando laudo estrutural",
                lambda progress: export_structure_report(
                    self.model, destination, options, compile_pdf=False, progress=progress,
                ),
            )
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Falha ao gerar laudo", f"Não foi possível gerar o laudo.\n\n{exc}")
            return
        if export.error and destination.suffix.lower() == ".pdf":
            warn_export_problem(self, "Laudo sem PDF", export)
            self.exported_path = export.tex_path
            return
        self.exported_path = export.pdf_path or export.tex_path
        QMessageBox.information(self, "Laudo estrutural", f"Laudo exportado com sucesso:\n{self.exported_path}")
        self.accept()
