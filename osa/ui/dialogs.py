from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem
from PySide6.QtGui import QPalette

from osa.domain import ActionDefinition, ActionGroup
from osa.services.action_service import ACTION_GROUP_TEMPLATES

from .common import *
from .profile_selector import ProfileComboBox

PROTECTED_ACTION_GROUP_NAMES = frozenset(("PP+AP+AV", "PP+AV+AP"))


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
                           "QPushButton#closeProperties { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de; border-radius: 7px; color: #24292f; background: #f6f8fa; }"
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
                included = self.window.model.sections.get("Aço") or all_sections
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


class ActionGroupDialog(QDialog):
    """Cadastro dos grupos e das siglas usadas nas combinações."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self.action_service = parent.action_service
        self._editing_name: str | None = None
        self._current_group_name: str | None = None
        self._loading_actions = False
        self.setWindowTitle("Grupo de ações")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(780, 540)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QFrame#titleBar { background: #e1e4e8; border-bottom: 1px solid #d0d7de; }"
            "QLabel#windowTitle { color: #24292f; font-weight: 600; }"
            "QLabel#sectionLabel { color: #57606a; font-size: 12px; font-weight: 600; }"
            "QListWidget { background: #f6f8fa; border: 0; padding: 8px; }"
            "QListWidget::item { padding: 9px 10px; border-radius: 6px; color: #57606a; }"
            "QListWidget::item:selected { background: #d0d7de; color: #24292f; }"
            "QLineEdit, QComboBox { min-height: 34px; border: 1px solid #d0d7de;"
            " border-radius: 6px; padding: 2px 9px; background: #ffffff; color: #24292f; }"
            "QComboBox::drop-down { width: 0px; border: 0; }"
            "QComboBox::down-arrow { image: none; }"
            "QFrame#actionTableFrame { background: #ffffff; border: 0; }"
            "QTableWidget#actionTable { padding: 0; border-left: 1px solid #d0d7de; border-right: 1px solid #d0d7de;"
            " border-bottom: 1px solid #d0d7de; border-top: 0; border-top-left-radius: 0; border-top-right-radius: 0;"
            " border-bottom-left-radius: 6px;"
            " border-bottom-right-radius: 6px; gridline-color: #eaeef2; }"
            "QFrame#actionTableHeader { background: #f6f8fa; border-left: 1px solid #d0d7de;"
            " border-right: 1px solid #d0d7de; border-top: 1px solid #d0d7de; border-bottom: 0;"
            " border-top-left-radius: 6px; border-top-right-radius: 6px; }"
            "QLabel#actionTableHeaderLabel { background: transparent; padding: 7px 9px; color: #57606a; font-weight: 600; }"
            "QLabel#actionTableHeaderSigla { background: transparent; border-left: 1px solid #d0d7de;"
            " padding: 7px 9px; color: #57606a; font-weight: 600; }"
            "QTableWidget#actionTable::item { background: #ffffff; padding: 4px 8px; }"
            "QTableWidget#actionTable::item:selected { background: #ffffff; color: #24292f; }"
            "QTableWidget#actionTable::item:selected:active { background: #ffffff; color: #24292f; }"
            "QTableWidget#actionTable::item:selected:!active { background: #ffffff; color: #24292f; }"
            "QTableWidget#actionTable QLineEdit { min-height: 0px; border: 0; border-radius: 0;"
            " padding: 0 8px; background: #ffffff; color: #24292f; }"
            "QHeaderView { background: #f6f8fa; }"
            "QHeaderView::section { background: #f6f8fa; border-left: 1px solid #d0d7de;"
            " border-right: 1px solid #d0d7de; border-top: 1px solid #d0d7de; border-bottom: 0;"
            " padding: 7px 9px; color: #57606a; font-weight: 600; }"
            "QTableWidget QHeaderView::section:first { border-top-left-radius: 6px; }"
            "QTableWidget QHeaderView::section:last { border-top-right-radius: 6px; }"
            "QPushButton#primaryButton { min-height: 34px; padding: 4px 16px; border: 0;"
            " border-radius: 7px; background: #0969da; color: #ffffff; font-weight: 700; }"
            "QPushButton#primaryButton:hover { background: #0550ae; }"
            "QPushButton#secondaryButton, QPushButton#closeProperties { min-height: 34px; padding: 4px 14px;"
            " border: 1px solid #d0d7de; border-radius: 7px; background: #f6f8fa; color: #24292f; }"
            "QPushButton#secondaryButton:hover, QPushButton#closeProperties:hover { background: #eaeef2; }"
            "QPushButton#secondaryButton:disabled { background: #f6f8fa; color: #afb8c1; }"
            "QToolButton#groupActionButton { border: 1px solid #d0d7de; border-radius: 6px;"
            " background: #ffffff; padding: 4px; color: #24292f; }"
            "QToolButton#groupActionButton:hover { background: #eaeef2; }"
            "QToolButton#groupActionButton:disabled { background: #f6f8fa; color: #afb8c1; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        titlebar = QFrame()
        titlebar.setObjectName("titleBar")
        titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar)
        titlebar_layout.setContentsMargins(12, 4, 8, 4)
        title = QLabel("Grupo de ações")
        title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title)
        titlebar_layout.addStretch()
        outer.addWidget(titlebar)

        content = QVBoxLayout()
        content.setContentsMargins(16, 14, 16, 16)
        content.setSpacing(8)
        right = QVBoxLayout()
        right.setSpacing(8)
        template_row = QHBoxLayout()
        template_row.addWidget(QLabel("Grupo"))
        self.template_combo = ProfileComboBox()
        template_row.addWidget(self.template_combo, 1)
        new_button = QToolButton()
        new_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "plus.svg")))
        new_button.setIconSize(QSize(24, 24))
        new_button.setFixedSize(36, 36)
        new_button.setToolTip("Novo grupo")
        new_button.setAccessibleName("Novo grupo")
        new_button.setObjectName("groupActionButton")
        new_button.clicked.connect(self._new_group)
        template_row.addWidget(new_button)
        icons_path = Path(__file__).parents[1] / "resources" / "icons"

        def group_icon(name: str) -> QIcon:
            icon = QIcon()
            icon.addFile(str(icons_path / f"{name}.svg"), QSize(24, 24), QIcon.Mode.Normal)
            icon.addFile(str(icons_path / f"{name}-disabled.svg"), QSize(24, 24), QIcon.Mode.Disabled)
            return icon

        self.edit_group_button = QToolButton()
        self.edit_group_button.setIcon(group_icon("pencil"))
        self.edit_group_button.setIconSize(QSize(24, 24))
        self.edit_group_button.setFixedSize(36, 36)
        self.edit_group_button.setToolTip("Renomear grupo")
        self.edit_group_button.setAccessibleName("Renomear grupo")
        self.edit_group_button.setObjectName("groupActionButton")
        self.edit_group_button.clicked.connect(self._rename_group)
        template_row.addWidget(self.edit_group_button)
        self.remove_group_button = QToolButton()
        self.remove_group_button.setIcon(group_icon("x"))
        self.remove_group_button.setIconSize(QSize(24, 24))
        self.remove_group_button.setFixedSize(36, 36)
        self.remove_group_button.setToolTip("Remover grupo")
        self.remove_group_button.setAccessibleName("Remover grupo")
        self.remove_group_button.setObjectName("groupActionButton")
        self.remove_group_button.clicked.connect(self._remove_group)
        template_row.addWidget(self.remove_group_button)
        self.template_combo.currentIndexChanged.connect(self._select_group)
        right.addLayout(template_row)

        actions_label = QLabel("Ações do grupo")
        actions_label.setObjectName("sectionLabel")
        right.addWidget(actions_label)
        self.actions_table = QTableWidget(0, 2)
        self.actions_table.setObjectName("actionTable")
        self.actions_table.setHorizontalHeaderLabels(("Nome da ação", "Sigla"))
        self.actions_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.actions_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.actions_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.actions_table.setAlternatingRowColors(False)
        self.actions_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.actions_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.actions_table.horizontalHeader().setVisible(False)
        self.actions_table.verticalHeader().setVisible(False)
        self.actions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.actions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.actions_table.setColumnWidth(1, 110)
        table_palette = self.actions_table.palette()
        table_palette.setColor(QPalette.ColorRole.Highlight, QColor("#ffffff"))
        table_palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#24292f"))
        self.actions_table.setPalette(table_palette)
        self.actions_table.itemChanged.connect(lambda _item: self._persist_current_group())
        action_table_frame = QFrame()
        action_table_frame.setObjectName("actionTableFrame")
        action_table_layout = QVBoxLayout(action_table_frame)
        action_table_layout.setContentsMargins(1, 1, 1, 1)
        action_table_layout.setSpacing(0)
        action_header = QFrame()
        action_header.setObjectName("actionTableHeader")
        action_header_layout = QHBoxLayout(action_header)
        action_header_layout.setContentsMargins(0, 0, 0, 0)
        action_header_layout.setSpacing(0)
        action_name_header = QLabel("Nome da ação")
        action_name_header.setObjectName("actionTableHeaderLabel")
        action_sigla_header = QLabel("Sigla")
        action_sigla_header.setObjectName("actionTableHeaderSigla")
        action_sigla_header.setFixedWidth(110)
        action_header_layout.addWidget(action_name_header, 1)
        action_header_layout.addWidget(action_sigla_header)
        action_header_layout.addSpacing(self.actions_table.verticalScrollBar().sizeHint().width())
        action_table_layout.addWidget(action_header)
        action_table_layout.addWidget(self.actions_table)
        right.addWidget(action_table_frame, 1)

        table_buttons = QHBoxLayout()
        table_buttons.setContentsMargins(0, 0, 0, 0)
        table_buttons.setSpacing(8)
        self.add_action_button = QPushButton("Adicionar ação")
        self.add_action_button.setObjectName("secondaryButton")
        self.add_action_button.clicked.connect(self._add_action_row)
        self.remove_action_button = QPushButton("Remover ação")
        self.remove_action_button.setObjectName("secondaryButton")
        self.remove_action_button.clicked.connect(self._remove_action_rows)
        table_buttons.addWidget(self.add_action_button)
        table_buttons.addWidget(self.remove_action_button)
        table_buttons.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self._close_and_save)
        table_buttons.addWidget(close_button)
        right.addLayout(table_buttons)
        content.addLayout(right, 1)
        outer.addLayout(content, 1)

        self._refresh_group_selector(self.window.model.selected_action_group)
        if self.template_combo.currentIndex() < 0:
            self.template_combo.setCurrentIndex(0)
        self._select_group()

    def _refresh_group_selector(self, select_name: str | None = None) -> None:
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        added_names = set()
        for name in ACTION_GROUP_TEMPLATES:
            alias = self.window.model.action_group_aliases.get(name)
            if alias and alias in self.window.model.action_groups:
                self.template_combo.addItem(alias, ("saved", alias))
                added_names.add(alias)
            else:
                self.template_combo.addItem(name, ("template", name))
                added_names.add(name)
        for name in self.window.model.action_groups:
            if name not in added_names:
                self.template_combo.addItem(name, ("saved", name))
        self.template_combo.blockSignals(False)
        if select_name:
            index = self.template_combo.findText(select_name, Qt.MatchFlag.MatchExactly)
            if index >= 0:
                self.template_combo.setCurrentIndex(index)
        self._update_remove_button()

    def _rename_group(self) -> None:
        index = self.template_combo.currentIndex()
        if index < 0:
            return
        kind, name = self.template_combo.currentData() or ("", "")
        if not name or name in PROTECTED_ACTION_GROUP_NAMES:
            return
        template_source = next(
            (template for template, group in self.window.model.action_group_aliases.items() if group == name),
            None,
        )
        if template_source is None and name in ACTION_GROUP_TEMPLATES:
            template_source = name
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Renomear grupo")
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dialog.setLabelText("Novo nome do grupo:")
        dialog.setOkButtonText("Renomear")
        dialog.setCancelButtonText("Cancelar")
        dialog.setStyleSheet("QInputDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
                             "QLabel { color: #57606a; }"
                             "QLineEdit { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px; padding: 2px 9px; background: #ffffff; }"
                             "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px; background: #f6f8fa; color: #57606a; }"
                             "QPushButton:hover { background: #eaeef2; }")
        for dialog_button in dialog.findChildren(QPushButton):
            dialog_button.setIcon(QIcon())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dialog.textValue().strip()
        if not new_name or new_name == name:
            return
        if new_name in self.window.model.action_groups or new_name in ACTION_GROUP_TEMPLATES:
            QMessageBox.warning(self, "Renomear grupo", f"Já existe um grupo chamado '{new_name}'.")
            return
        template_actions = None
        if name in ACTION_GROUP_TEMPLATES and name not in self.window.model.action_groups:
            template_actions = ACTION_GROUP_TEMPLATES[name].actions
        if name in self.window.model.action_groups:
            group = self.window.model.action_groups[name]
            self.action_service.update_action_group(name, ActionGroup(new_name, group.actions))
            kind = "saved"
        elif template_actions is not None:
            self.action_service.add_action_group(ActionGroup(new_name, template_actions))
            kind = "saved"
        if template_source is not None:
            self.action_service.set_action_group_alias(template_source, new_name)
        self.template_combo.setItemText(index, new_name)
        self.template_combo.setItemData(index, (kind, new_name))
        self._current_group_name = new_name
        self._editing_name = new_name if kind == "saved" else None
        self.action_service.select_action_group(new_name)
        self._update_remove_button()

    def _prepare_blank_group(self, name: str | None = None) -> None:
        self._editing_name = None
        self._current_group_name = name
        self._replace_action_rows(())
        self._add_action_row()
        self._update_remove_button()

    def _new_group(self) -> None:
        dialog = QInputDialog(self)
        dialog.setWindowTitle("Adicionar grupo")
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dialog.setLabelText("Nome do novo grupo:")
        dialog.setOkButtonText("Adicionar")
        dialog.setCancelButtonText("Cancelar")
        dialog.setStyleSheet("QInputDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
                             "QLabel { color: #57606a; }"
                             "QLineEdit { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px; padding: 2px 9px; background: #ffffff; }"
                             "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px; background: #f6f8fa; color: #57606a; }"
                             "QPushButton:hover { background: #eaeef2; }")
        for dialog_button in dialog.findChildren(QPushButton):
            dialog_button.setIcon(QIcon())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.textValue().strip()
        if not name:
            return
        if name in self.window.model.action_groups or name in ACTION_GROUP_TEMPLATES:
            QMessageBox.warning(self, "Novo grupo", f"Já existe um grupo chamado '{name}'.")
            return
        self.template_combo.addItem(name, ("new", name))
        self.template_combo.setCurrentIndex(self.template_combo.count() - 1)
        self._prepare_blank_group(name)

    def _confirm_group_removal(self, name: str) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Remover grupo")
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dialog.setMinimumWidth(max(420, min(760, 260 + len(name) * 8)))
        dialog.setStyleSheet("QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
                             "QLabel { color: #57606a; }"
                             "QLabel#groupName { color: #24292f; font-weight: 600; }"
                             "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px; background: #f6f8fa; color: #57606a; }"
                             "QPushButton:hover { background: #eaeef2; }")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)
        message = QLabel("Deseja remover o grupo")
        group_name = QLabel(name)
        group_name.setObjectName("groupName")
        layout.addWidget(message)
        layout.addWidget(group_name)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Cancelar")
        remove_button = QPushButton("Remover")
        cancel_button.clicked.connect(dialog.reject)
        remove_button.clicked.connect(dialog.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(remove_button)
        layout.addLayout(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _remove_group(self) -> None:
        index = self.template_combo.currentIndex()
        if index < 0:
            return
        kind, name = self.template_combo.currentData() or ("", "")
        if name in PROTECTED_ACTION_GROUP_NAMES:
            return
        template_source = next(
            (template for template, group in self.window.model.action_group_aliases.items() if group == name),
            None,
        )
        if not self._confirm_group_removal(name):
            return
        if kind != "new" and name in self.window.model.action_groups:
            self.action_service.remove_action_group(name)
        if template_source is not None:
            self._refresh_group_selector()
            self.template_combo.setCurrentIndex(0)
        else:
            self.template_combo.removeItem(index)
            self.template_combo.setCurrentIndex(min(index, self.template_combo.count() - 1))

    def _load_saved_group(self, name: str) -> None:
        group = self.window.model.action_groups[name]
        self._editing_name = group.name
        self._current_group_name = group.name
        self._replace_action_rows(group.actions)
        self._update_remove_button()

    def _replace_action_rows(self, actions) -> None:
        self._loading_actions = True
        self.actions_table.setRowCount(0)
        for action in actions:
            self._add_action_row(action.name, action.abbreviation)
        self._loading_actions = False

    def _apply_template(self) -> None:
        template = ACTION_GROUP_TEMPLATES.get(self.template_combo.currentText())
        if template is None:
            return
        self._editing_name = None
        self._current_group_name = template.name
        self._replace_action_rows(template.actions)
        self._update_remove_button()

    def _select_group(self, _index: int | None = None) -> None:
        kind, name = self.template_combo.currentData() or ("custom", "")
        if name:
            self.action_service.select_action_group(name)
        if kind == "saved" or name in self.window.model.action_groups:
            self._load_saved_group(name)
        elif kind == "template":
            self._apply_template()
        elif kind == "new":
            self._prepare_blank_group(name)
        else:
            self._prepare_blank_group()

    def _update_remove_button(self) -> None:
        kind, name = self.template_combo.currentData() or ("", "")
        editable = bool(name) and name not in PROTECTED_ACTION_GROUP_NAMES
        self.edit_group_button.setEnabled(editable)
        self.remove_group_button.setEnabled(
            editable
            and (kind in ("saved", "new", "template") or name in self.window.model.action_groups)
        )
        self.add_action_button.setEnabled(editable)
        self.remove_action_button.setEnabled(editable)

    def _add_action_row(self, name: str = "", abbreviation: str = "") -> None:
        if not self._loading_actions:
            _, group_name = self.template_combo.currentData() or ("", "")
            if group_name in PROTECTED_ACTION_GROUP_NAMES:
                return
        row = self.actions_table.rowCount()
        self.actions_table.insertRow(row)
        self.actions_table.setItem(row, 0, QTableWidgetItem(name))
        self.actions_table.setItem(row, 1, QTableWidgetItem(abbreviation))
        self.actions_table.setCurrentCell(row, 0)

    def _remove_action_rows(self) -> None:
        _, group_name = self.template_combo.currentData() or ("", "")
        if group_name in PROTECTED_ACTION_GROUP_NAMES:
            return
        rows = sorted({index.row() for index in self.actions_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.actions_table.removeRow(row)
        self._persist_current_group()

    def _persist_current_group(self) -> None:
        if self._loading_actions or not self._current_group_name:
            return
        try:
            group = self._group_from_form()
        except ValueError:
            return
        if any(not action.name or not action.abbreviation for action in group.actions):
            return
        try:
            if self._editing_name is None:
                if group.name in self.window.model.action_groups:
                    self.action_service.update_action_group(group.name, group)
                else:
                    self.action_service.add_action_group(group)
                self._editing_name = group.name
            else:
                self.action_service.update_action_group(self._editing_name, group)
        except ValueError:
            return
        self.action_service.select_action_group(group.name)

    def _group_from_form(self) -> ActionGroup:
        actions = []
        for row in range(self.actions_table.rowCount()):
            name_item = self.actions_table.item(row, 0)
            abbreviation_item = self.actions_table.item(row, 1)
            actions.append(ActionDefinition(
                name_item.text().strip() if name_item else "",
                abbreviation_item.text().strip() if abbreviation_item else "",
            ))
        return ActionGroup(self._current_group_name or "", tuple(actions))

    def _normalized_group_from_form(self) -> ActionGroup:
        actions = []
        abbreviations: set[str] = set()
        pending_abbreviations: list[tuple[int, str]] = []
        for row in range(self.actions_table.rowCount()):
            name_item = self.actions_table.item(row, 0)
            abbreviation_item = self.actions_table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            abbreviation = abbreviation_item.text().strip() if abbreviation_item else ""
            if not name:
                continue
            actions.append(ActionDefinition(name, abbreviation))
            if abbreviation:
                abbreviations.add(abbreviation.casefold())
            else:
                pending_abbreviations.append((len(actions) - 1, name))

        for action_index, name in pending_abbreviations:
            words = [word for word in name.replace("-", " ").split() if word]
            base = "".join(word[0] for word in words).upper() or "A"
            candidate = base
            suffix = 2
            while candidate.casefold() in abbreviations:
                candidate = f"{base}{suffix}"
                suffix += 1
            abbreviations.add(candidate.casefold())
            actions[action_index] = ActionDefinition(name, candidate)
        return ActionGroup(self._current_group_name or "", tuple(actions))

    def _close_and_save(self) -> None:
        try:
            group = self._normalized_group_from_form()
            if self._editing_name is None:
                self.action_service.add_action_group(group)
            else:
                self.action_service.update_action_group(self._editing_name, group)
        except ValueError as error:
            QMessageBox.warning(self, "Grupo de ações", str(error))
            return
        self.accept()
