from .common import *


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Propriedades")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(640, 400)
        self.materials = parent.model.materials if parent is not None and hasattr(parent, "model") else {}
        self.material_types = parent.model.material_types if parent is not None and hasattr(parent, "model") else {}
        self.setStyleSheet("QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
                           "QListWidget { background: #f6f8fa; border: 0; padding: 8px; }"
                           "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #57606a; }"
                           "QListWidget::item:selected { background: #d0d7de; color: #24292f; }"
                           "QListWidget:focus { outline: none; border: 0; }"
                           "QComboBox::drop-down { width: 0px; border: 0; }"
                           "QComboBox::down-arrow { image: none; }"
                           "QPushButton#closeProperties { border: 0; border-radius: 6px; padding: 9px 10px; color: #57606a; background: #f6f8fa; }"
                           "QPushButton#closeProperties:hover { background: #eaeef2; }")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        titlebar = QFrame(); titlebar.setObjectName("titleBar"); titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar); titlebar_layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel("Propriedades"); title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title); titlebar_layout.addStretch()
        outer.addWidget(titlebar)
        layout = QHBoxLayout(); layout.setContentsMargins(0, 0, 0, 0)
        categories = QListWidget()
        categories.setFixedWidth(170)
        categories.setSpacing(8)
        categories.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        categories.addItems(["Materiais", "Seções"])
        pages = QStackedWidget()
        for title in ("Materiais", "Seções"):
            page = QWidget(); page_layout = QVBoxLayout(page)
            heading = QLabel(title); heading.setObjectName("dialogTitle")
            if title == "Materiais":
                page_layout.addSpacing(10)
                values = self.materials
                material_combo = QComboBox(); material_combo.addItems(values)
                material_row = QHBoxLayout(); material_row.addWidget(material_combo, 1)
                add_button = QToolButton(); add_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "plus.svg"))); add_button.setToolTip("Adicionar material")
                remove_button = QToolButton(); remove_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "trash-2.svg"))); remove_button.setToolTip("Remover material")
                for tool_button in (add_button, remove_button):
                    tool_button.setFixedSize(36, 36); tool_button.setIconSize(QSize(30, 30))
                    tool_button.setStyleSheet("QToolButton { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; }"
                                             "QToolButton:hover { background: #eaeef2; }")
                material_row.addWidget(add_button); material_row.addWidget(remove_button); page_layout.addLayout(material_row)
                form = QFormLayout(); fields = []
                labels = ("Módulo de elasticidade", "Módulo de cisalhamento", "Coeficiente de Poisson", "Densidade")
                type_combo = QComboBox(); type_combo.addItems(["Aço", "Concreto", "Madeira"])
                type_combo.setCurrentText(self.material_types.get(material_combo.currentText(), "Aço"))
                type_combo.currentTextChanged.connect(
                    lambda material_type: self.window.material_service.upsert(
                        material_combo.currentText(), material_type, tuple(field.value() for field in fields)
                    )
                )
                form.addRow("Tipo de material", type_combo)
                for label, value in zip(labels, values["Aço Estrutural"]):
                    field = QDoubleSpinBox(); field.setDecimals(3); field.setRange(0, 1e9); field.setValue(value)
                    field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); form.addRow(label, field); fields.append(field)
                for index, field in enumerate(fields):
                    field.valueChanged.connect(
                        lambda _v, idx=index: self.window.material_service.upsert(
                            material_combo.currentText(), type_combo.currentText(), tuple(f.value() for f in fields)
                        )
                    )
                def load_material(material):
                    for field in fields:
                        field.blockSignals(True)
                    for field, value in zip(fields, values[material]):
                        field.setValue(value)
                    for field in fields:
                        field.blockSignals(False)
                    type_combo.blockSignals(True)
                    type_combo.setCurrentText(self.material_types.get(material, "Aço"))
                    type_combo.blockSignals(False)
                material_combo.currentTextChanged.connect(load_material)
                def add_material():
                    dialog = QInputDialog(self)
                    dialog.setWindowTitle("Adicionar material")
                    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
                    dialog.setLabelText("Nome do material:")
                    dialog.setOkButtonText("Adicionar")
                    dialog.setCancelButtonText("Cancelar")
                    dialog.setStyleSheet("QInputDialog { background: #ffffff; border: 0; }"
                                         "QLabel { color: #57606a; }"
                                         "QLineEdit { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px; padding: 2px 9px; background: #ffffff; }"
                                         "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px; background: #f6f8fa; color: #57606a; }"
                                         "QPushButton:hover { background: #eaeef2; }")
                    for dialog_button in dialog.findChildren(QPushButton):
                        dialog_button.setIcon(QIcon())
                    ok = dialog.exec() == QDialog.DialogCode.Accepted
                    name = dialog.textValue()
                    if ok and name.strip() and name.strip() not in values:
                        self.window.material_service.upsert(
                            name.strip(), type_combo.currentText(), tuple(field.value() for field in fields)
                        )
                        material_combo.addItem(name.strip()); material_combo.setCurrentText(name.strip())
                def remove_material():
                    name = material_combo.currentText()
                    if name not in ("Aço Estrutural", "Concreto Estrutural", "Madeira Estrutural"):
                        self.window.material_service.remove(name); material_combo.removeItem(material_combo.currentIndex())
                add_button.clicked.connect(add_material); remove_button.clicked.connect(remove_material)
                page_layout.addLayout(form)
            else:
                section_row = QHBoxLayout()
                section_row.addWidget(QLabel("Tipo de material"))
                section_material = QComboBox()
                section_material.addItems(["Aço", "Concreto", "Madeira"])
                section_row.addWidget(section_material, 1)
                page_layout.addLayout(section_row)
                section_catalog = {
                    "Aço": ["W Laminado", "I Laminado", "U Laminado", "L Laminado", "T Laminado", "U Formado", "C Formado", "Z Formado", "L Formado", "Cartola Formado", "Tubular Circular", "Tubular Quadrado", "Tubular Retangular", "Barra Circular", "Barra Quadrada", "Barra Retangular"],
                    "Concreto": ["Retangular", "Circular", "Tipo L", "Tipo T", "Tipo I", "Tipo U", "Tipo +", "Retangular Vazado", "Circular Vazado"],
                    "Madeira": ["Circular", "Quadrada", "Retangular"],
                }
                all_sections = section_catalog["Aço"]
                included = self.window.model.sections.get("Aço") or ["U Formado", "C Formado", "Z Formado", "L Formado", "Cartola Formado"]
                available = [section for section in all_sections if section not in included]
                lists = QHBoxLayout(); available_list = QListWidget(); included_list = QListWidget()
                lists.setContentsMargins(0, 0, 0, 0)
                available_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                included_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                for section_list in (available_list, included_list):
                    section_list.setSpacing(0)
                    section_list.setUniformItemSizes(True)
                available_list.addItems(available); included_list.addItems(included)
                for section_list in (available_list, included_list):
                    for row in range(section_list.count()):
                        item = section_list.item(row)
                        item.setData(Qt.ItemDataRole.UserRole, all_sections.index(item.text()))
                        item.setSizeHint(QSize(0, 34))
                transfer = QVBoxLayout(); transfer.addStretch()
                add_section = QToolButton(); add_section.setText("←")
                remove_section = QToolButton(); remove_section.setText("→")
                transfer.addWidget(add_section); transfer.addWidget(remove_section); transfer.addStretch()
                included_label = QLabel("Inclusos")
                available_label = QLabel("Disponíveis")
                list_columns = QVBoxLayout(); list_columns.setContentsMargins(0, 0, 0, 0); list_columns.addWidget(included_label); list_columns.addWidget(included_list, 1)
                available_columns = QVBoxLayout(); available_columns.setContentsMargins(0, 0, 0, 0); available_columns.addWidget(available_label); available_columns.addWidget(available_list, 1)
                lists.addLayout(list_columns, 1); lists.addLayout(transfer); lists.addLayout(available_columns, 1)
                lists_widget = QWidget()
                lists_widget.setLayout(lists)
                page_layout.addWidget(lists_widget, 1)
                add_section.clicked.connect(lambda: (self._transfer_section(available_list, included_list), self._save_sections(section_material.currentText(), included_list)))
                remove_section.clicked.connect(lambda: (self._transfer_section(included_list, available_list), self._save_sections(section_material.currentText(), included_list)))
                section_material.currentTextChanged.connect(
                    lambda material: load_sections(material)
                )

                def load_sections(material):
                    catalog = section_catalog[material]
                    saved = self.window.model.sections.get(material, [])
                    included_list.clear(); available_list.clear()
                    included_list.addItems([item for item in catalog if item in saved])
                    available_list.addItems([item for item in catalog if item not in saved])
                    for section_list in (available_list, included_list):
                        for row in range(section_list.count()):
                            item = section_list.item(row)
                            item.setData(Qt.ItemDataRole.UserRole, catalog.index(item.text()))
                            item.setSizeHint(QSize(0, 34))
            page_layout.addStretch()
            close_button = QPushButton("Fechar"); close_button.setObjectName("closeProperties")
            close_button.clicked.connect(self.accept)
            close_row = QHBoxLayout(); close_row.addStretch(); close_row.addWidget(close_button)
            page_layout.addLayout(close_row)
            pages.addWidget(page)
        categories.currentRowChanged.connect(pages.setCurrentIndex)
        categories.setCurrentRow(0)
        layout.addWidget(categories); layout.addWidget(pages, 1)
        outer.addLayout(layout, 1)

    @staticmethod
    def _transfer_section(source: QListWidget, target: QListWidget) -> None:
        for item in source.selectedItems():
            target.addItem(source.takeItem(source.row(item)))
        items = [target.takeItem(0) for _ in range(target.count())]
        for item in sorted(items, key=lambda item: item.data(Qt.ItemDataRole.UserRole)):
            item.setSizeHint(QSize(0, 34))
            target.addItem(item)

    def _save_sections(self, material: str, included_list: QListWidget) -> None:
        self.window.section_service.set_included_families(
            material, [included_list.item(i).text() for i in range(included_list.count())]
        )
