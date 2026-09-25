from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QListWidgetItem, QTableWidget, QTableWidgetItem

from osa.domain import ActionDefinition, ActionGroup, LoadCombination
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
                labels = ("Módulo de elasticidade", "Módulo de cisalhamento", "Coeficiente de Poisson", "Peso específico")
                type_combo = QComboBox(); type_combo.addItems(["Aço", "Concreto", "Madeira"])
                type_combo.setCurrentText(self.material_types.get(material_combo.currentText(), "Aço"))
                type_combo.currentTextChanged.connect(
                    lambda material_type: self.window.material_service.upsert(
                        material_combo.currentText(), material_type, tuple(field.value() for field in fields)
                    )
                )
                form.addRow("Tipo de material", type_combo)
                units = ("kN/m²", "kN/m²", "", "kN/m³")
                for label, unit, value in zip(labels, units, values["Aço Estrutural"]):
                    box = QFrame(); box.setObjectName("unitInputBox")
                    box.setStyleSheet("QFrame#unitInputBox { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; } QFrame#unitInputBox QDoubleSpinBox { border: 0; background: transparent; color: #24292f; padding: 2px 9px; } QFrame#unitInputBox QLabel { color: #57606a; padding-right: 9px; }")
                    row = QHBoxLayout(box); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(0)
                    field = QDoubleSpinBox(); field.setDecimals(3); field.setRange(0, 1e12); field.setValue(value)
                    field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons); field.setMinimumWidth(0)
                    row.addWidget(field, 1)
                    if unit:
                        row.addWidget(QLabel(unit))
                    form.addRow(label, box); fields.append(field)
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


class ProgramSettingsDialog(QDialog):
    """Application settings window using the same navigation as properties."""

    _snap_options = (
        ("grid", "Malha", "hash.svg"),
        ("endpoint", "Extremidade", "square.svg"),
        ("center", "Centro", "triangle.svg"),
        ("perpendicular", "Perpendicular", "axis-configuration.svg"),
        ("orthogonal", "Ortogonal", "axis-3d.svg"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Configurações")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(640, 400)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QListWidget { background: #f6f8fa; border: 0; padding: 8px; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; color: #57606a; }"
            "QListWidget::item:selected { background: #d0d7de; color: #24292f; }"
            "QListWidget:focus { outline: none; border: 0; }"
            "QCheckBox { color: #57606a; spacing: 8px; min-height: 30px; }"
            "QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de; "
            "border-radius: 5px; background: #ffffff; }"
            "QCheckBox::indicator:hover { border-color: #0969da; }"
            "QCheckBox::indicator:checked { background: #0969da; border-color: #0969da; }"
            "QPushButton#closeProperties { min-height: 34px; padding: 4px 14px; "
            "border: 1px solid #d0d7de; border-radius: 7px; color: #24292f; background: #f6f8fa; }"
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
        title = QLabel("Configurações")
        title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title)
        titlebar_layout.addStretch()
        outer.addWidget(titlebar)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        categories = QListWidget()
        categories.setFixedWidth(170)
        categories.setSpacing(8)
        categories.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        categories.addItem("Snaps")
        pages = QStackedWidget()
        snaps_page = QWidget()
        page_layout = QVBoxLayout(snaps_page)
        page_layout.addSpacing(10)
        hint = QLabel("Selecione os pontos que podem atrair o cursor durante o lançamento.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        page_layout.addWidget(hint)
        page_layout.addSpacing(8)
        self._snap_checkboxes: dict[str, QCheckBox] = {}
        icon_path = Path(__file__).parents[1] / "resources" / "icons"
        for snap_kind, label, icon_name in self._snap_options:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            checkbox = QCheckBox()
            checkbox.setAccessibleName(f"Snap {label.casefold()}")
            checkbox.setChecked(self.window.scene.snap_type_enabled(snap_kind))
            checkbox.toggled.connect(
                lambda enabled, kind=snap_kind: self.window.scene.set_snap_type_enabled(kind, enabled)
            )
            icon = QLabel()
            icon.setFixedSize(22, 22)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setPixmap(QIcon(str(icon_path / icon_name)).pixmap(QSize(20, 20)))
            name = QLabel(label)
            self._snap_checkboxes[snap_kind] = checkbox
            row_layout.addWidget(checkbox)
            row_layout.addWidget(icon)
            row_layout.addWidget(name)
            row_layout.addStretch(1)
            page_layout.addWidget(row)
        page_layout.addStretch(1)
        close_button = QPushButton("Fechar")
        close_button.setObjectName("closeProperties")
        close_button.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close_row.addWidget(close_button)
        page_layout.addLayout(close_row)
        pages.addWidget(snaps_page)
        categories.currentRowChanged.connect(pages.setCurrentIndex)
        categories.setCurrentRow(0)
        layout.addWidget(categories)
        layout.addWidget(pages, 1)
        outer.addLayout(layout, 1)


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


class CombinationsDialog(QDialog):
    """Edição inicial das combinações vinculadas ao grupo de ações ativo."""

    _STYLE = (
        "QDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
        "QFrame#titleBar { background: #e1e4e8; border-bottom: 1px solid #d0d7de; }"
        "QLabel#windowTitle { color: #24292f; font-weight: 600; }"
        "QLabel#sectionLabel { color: #57606a; font-size: 12px; font-weight: 600; }"
        "QLabel#emptyHint { color: #57606a; padding: 16px; }"
        "QListWidget#combinationList { background: #ffffff; border: 1px solid #d0d7de;"
        " border-radius: 6px; padding: 6px; }"
        "QListWidget#combinationList::item { padding: 6px 10px; border-radius: 6px; color: #57606a; }"
        "QListWidget#combinationList::item:selected { background: #f6f8fa; color: #24292f; }"
        "QLabel#combinationName { color: #24292f; }"
        "QLabel#combinationExpression { color: #57606a; font-size: 8pt; }"
        "QLabel#combinationLimitState { min-width: 27px; padding: 3px 4px; border-radius: 5px;"
        " background: #eaeef2; color: #57606a; font-size: 8pt; font-weight: 600; }"
        "QLineEdit#activeGroup { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px;"
        " padding: 2px 9px; background: #ffffff; color: #24292f; }"
        "QTableWidget#combinationTable { border: 1px solid #d0d7de; border-radius: 6px;"
        " gridline-color: #eaeef2; background: #ffffff; }"
        "QHeaderView::section { background: #f6f8fa; border: 0; border-bottom: 1px solid #d0d7de;"
        " padding: 7px 9px; color: #57606a; font-weight: 600; }"
        "QTableWidget#combinationTable::item { padding: 4px 8px; color: #24292f; }"
        "QTableWidget#combinationTable QLineEdit { min-height: 0; border: 0; border-radius: 0;"
        " padding: 0 8px; background: #ffffff; color: #24292f; }"
        "QTableWidget#combinationTable QLineEdit:disabled { background: #ffffff; color: #afb8c1; }"
        "QTableWidget#combinationTable QCheckBox::indicator { width: 18px; height: 18px;"
        " border: 1px solid #d0d7de; border-radius: 5px; background: #ffffff; }"
        "QTableWidget#combinationTable QCheckBox::indicator:hover { border-color: #0969da; }"
        "QTableWidget#combinationTable QCheckBox::indicator:checked {"
        " background: #0969da; border-color: #0969da; }"
        "QLabel#combinationAction { color: #24292f; padding-left: 4px; }"
        "QToolButton#groupActionButton { border: 1px solid #d0d7de; border-radius: 6px;"
        " background: #ffffff; padding: 4px; color: #24292f; }"
        "QToolButton#groupActionButton:hover { background: #eaeef2; }"
        "QToolButton#groupActionButton:disabled { background: #f6f8fa; color: #afb8c1; }"
        "QToolButton#limitStateButton { min-width: 38px; min-height: 30px; padding: 0 7px;"
        " border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; color: #57606a; }"
        "QToolButton#limitStateButton:checked { background: #eaeef2; color: #24292f; font-weight: 600; }"
        "QToolButton#limitStateButton:disabled { background: #ffffff; color: #afb8c1; }"
        "QPushButton#secondaryButton { min-height: 34px; padding: 4px 14px; border: 1px solid #d0d7de;"
        " border-radius: 7px; background: #f6f8fa; color: #24292f; }"
        "QPushButton#secondaryButton:hover { background: #eaeef2; }"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self.action_service = parent.action_service
        self._loading = False
        self.setWindowTitle("Combinações")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(920, 540)
        self.setStyleSheet(self._STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        titlebar = QFrame()
        titlebar.setObjectName("titleBar")
        titlebar.setFixedHeight(40)
        titlebar_layout = QHBoxLayout(titlebar)
        titlebar_layout.setContentsMargins(12, 4, 8, 4)
        title = QLabel("Combinações")
        title.setObjectName("windowTitle")
        titlebar_layout.addWidget(title)
        titlebar_layout.addStretch()
        outer.addWidget(titlebar)

        content = QVBoxLayout()
        content.setContentsMargins(16, 14, 16, 16)
        content.setSpacing(12)
        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Grupo de ações"))
        self.active_group = QLineEdit()
        self.active_group.setObjectName("activeGroup")
        self.active_group.setReadOnly(True)
        group_row.addWidget(self.active_group, 1)
        content.addLayout(group_row)

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(8)
        combinations_header_widget = QWidget()
        combinations_header_widget.setFixedHeight(36)
        combinations_header = QHBoxLayout(combinations_header_widget)
        combinations_header.setContentsMargins(0, 0, 0, 0)
        combinations_label = QLabel("Combinações")
        combinations_label.setObjectName("sectionLabel")
        combinations_header.addWidget(combinations_label)
        combinations_header.addStretch()
        self._add_icon_button(combinations_header, "plus", "Adicionar combinação", self._add_combination)
        self.edit_button = self._add_icon_button(combinations_header, "pencil", "Renomear combinação", self._rename_combination)
        self.remove_button = self._add_icon_button(combinations_header, "x", "Excluir combinação", self._remove_combination)
        left.addWidget(combinations_header_widget)
        self.combination_list = QListWidget()
        self.combination_list.setObjectName("combinationList")
        self.combination_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.combination_list.currentItemChanged.connect(
            lambda current, _previous: self._load_combination(self._combination_name(current))
        )
        left.addWidget(self.combination_list, 1)
        body.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(8)
        actions_header = QWidget()
        actions_header.setFixedHeight(36)
        actions_header_layout = QHBoxLayout(actions_header)
        actions_header_layout.setContentsMargins(0, 0, 0, 0)
        actions_label = QLabel("Ações do grupo")
        actions_label.setObjectName("sectionLabel")
        actions_header_layout.addWidget(actions_label)
        actions_header_layout.addStretch()
        self.limit_state_group = QButtonGroup(self)
        self.limit_state_buttons: dict[str, QToolButton] = {}
        actions_header_layout.setSpacing(4)
        state_descriptions = {
            "CAR": "Combinação Característica",
            "ELU": "Estado Limite Último",
            "ELS": "Estado Limite de Serviço",
        }
        for state in ("CAR", "ELU", "ELS"):
            button = QToolButton()
            button.setObjectName("limitStateButton")
            button.setText(state)
            button.setCheckable(True)
            button.setFixedSize(38, 30)
            button.setEnabled(False)
            button.setToolTip(state_descriptions[state])
            button.setAccessibleName(state_descriptions[state])
            self.limit_state_group.addButton(button)
            button.toggled.connect(lambda checked, value=state: checked and self._set_limit_state(value))
            self.limit_state_buttons[state] = button
            actions_header_layout.addWidget(button)
        right.addWidget(actions_header)
        self.factors_table = QTableWidget(0, 4)
        self.factors_table.setObjectName("combinationTable")
        self.factors_table.setHorizontalHeaderLabels(("Ação", "γf", "ψ₀", "ψ₁; ψ₂"))
        self.factors_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.factors_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.factors_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.factors_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.factors_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.factors_table.verticalHeader().setVisible(False)
        self.factors_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.factors_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.factors_table.setColumnWidth(column, 100)
        right.addWidget(self.factors_table, 1)
        body.addLayout(right, 7)
        content.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Fechar")
        close_button.setObjectName("secondaryButton")
        close_button.setAutoDefault(False)
        close_button.setDefault(False)
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        content.addLayout(footer)
        outer.addLayout(content, 1)

        self._refresh_group()
        self._ensure_default_combinations()
        self._refresh_combinations()

    def _add_icon_button(self, layout, icon_name: str, tooltip: str, callback):
        icons_path = Path(__file__).parents[1] / "resources" / "icons"
        button = QToolButton()
        icon = QIcon()
        icon.addFile(str(icons_path / f"{icon_name}.svg"), QSize(24, 24), QIcon.Mode.Normal)
        disabled_icon = icons_path / f"{icon_name}-disabled.svg"
        if disabled_icon.exists():
            icon.addFile(str(disabled_icon), QSize(24, 24), QIcon.Mode.Disabled)
        button.setIcon(icon)
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(30, 30)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setObjectName("groupActionButton")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _refresh_group(self) -> None:
        group = self.action_service.selected_group()
        self._group_actions = group.actions if group is not None else ()
        self._active_group_name = group.name if group is not None else ""
        self.active_group.setText(group.name if group is not None else "Nenhum grupo selecionado")

    def _visible_combinations(self):
        return tuple(
            combination
            for combination in self.window.model.load_combinations.values()
            if combination.action_group in (None, self._active_group_name)
        )

    def _ensure_default_combinations(self) -> None:
        """Cria uma única vez as três combinações usuais do grupo padrão."""
        self.action_service.ensure_default_combinations()

    def _refresh_combinations(self, selected_name: str | None = None) -> None:
        selected_name = selected_name or self._combination_name(self.combination_list.currentItem())
        self.combination_list.blockSignals(True)
        self.combination_list.clear()
        for combination in self._visible_combinations():
            name = combination.name
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.combination_list.addItem(item)
            self._update_combination_item(item, name)
        self.combination_list.blockSignals(False)
        if selected_name:
            for row in range(self.combination_list.count()):
                item = self.combination_list.item(row)
                if self._combination_name(item) == selected_name:
                    self.combination_list.setCurrentItem(item)
                    break
        if self.combination_list.currentRow() < 0 and self.combination_list.count():
            self.combination_list.setCurrentRow(0)
        self._load_combination(self._combination_name(self.combination_list.currentItem()))

    @staticmethod
    def _combination_name(item: QListWidgetItem | None) -> str:
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else ""

    def _combination_expression(self, name: str) -> str:
        combination = self.window.model.load_combinations.get(name)
        if combination is None:
            return ""
        active_actions = set(combination.active_actions) if combination.active_actions is not None else {
            action.abbreviation for action in self._group_actions
        }
        gamma_f = dict(combination.factors)
        psi_0 = dict(combination.factors_2)
        psi_service = dict(combination.factors_3)
        terms = [
            f"{self._format_factor(\
                gamma_f.get(action.abbreviation, 1.0)\
                * psi_0.get(action.abbreviation, 1.0)\
                * psi_service.get(action.abbreviation, 1.0)\
            )}{action.abbreviation}"
            for action in self._group_actions
            if action.abbreviation in active_actions
        ]
        return " + ".join(terms) or "Sem ações selecionadas"

    def _update_combination_item(self, item: QListWidgetItem, name: str) -> None:
        expression = self._combination_expression(name)
        # O conteúdo visual é renderizado pelo widget com duas linhas abaixo.
        # Manter texto no item faria o QListWidget desenhá-lo novamente por
        # baixo desse widget, duplicando nome e expressão.
        item.setText("")
        item.setSizeHint(QSize(0, 52))
        widget = self.combination_list.itemWidget(item)
        if widget is None:
            widget = QWidget()
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 5, 0, 5)
            layout.setSpacing(7)
            state_label = QLabel()
            state_label.setObjectName("combinationLimitState")
            state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(state_label, 0, Qt.AlignmentFlag.AlignVCenter)
            text_widget = QWidget()
            text_layout = QVBoxLayout(text_widget)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(1)
            name_label = QLabel()
            name_label.setObjectName("combinationName")
            expression_label = QLabel()
            expression_label.setObjectName("combinationExpression")
            text_layout.addWidget(name_label)
            text_layout.addWidget(expression_label)
            layout.addWidget(text_widget, 1)
            self.combination_list.setItemWidget(item, widget)
        combination = self.window.model.load_combinations[name]
        widget.findChild(QLabel, "combinationLimitState").setText(combination.limit_state)
        widget.findChild(QLabel, "combinationName").setText(name)
        widget.findChild(QLabel, "combinationExpression").setText(expression)

    def _refresh_current_expression(self) -> None:
        item = self.combination_list.currentItem()
        name = self._combination_name(item)
        if item is not None and name:
            self._update_combination_item(item, name)

    def _add_combination(self) -> None:
        name = self._request_combination_name(
            "Adicionar combinação", "Nome da nova combinação:", "Adicionar",
        )
        if not name:
            return
        if name in self.window.model.load_combinations:
            QMessageBox.warning(self, "Combinações", f"Já existe uma combinação chamada '{name}'.")
            return
        factors = tuple((action.abbreviation, 1.0) for action in self._group_actions)
        active_actions = tuple(action.abbreviation for action in self._group_actions)
        from osa.domain import LoadCombination
        self.action_service.set_combination(LoadCombination(
            name, factors, factors, factors, active_actions, self._active_group_name,
        ))
        self._refresh_combinations(name)

    def _rename_combination(self) -> None:
        current = self.combination_list.currentItem()
        if current is None:
            return
        old_name = self._combination_name(current)
        name = self._request_combination_name(
            "Renomear combinação", "Novo nome da combinação:", "Renomear", old_name,
        )
        if not name or name == old_name:
            return
        if name in self.window.model.load_combinations:
            QMessageBox.warning(self, "Combinações", f"Já existe uma combinação chamada '{name}'.")
            return
        combination = self.window.model.load_combinations.pop(old_name)
        from osa.domain import LoadCombination
        self.action_service.set_combination(LoadCombination(
            name, combination.factors, combination.factors_2, combination.factors_3,
            combination.active_actions, combination.action_group or self._active_group_name, combination.limit_state,
        ))
        self._refresh_combinations(name)

    def _request_combination_name(
        self, title: str, label: str, accept_text: str, initial_value: str = "",
    ) -> str | None:
        """Aplica ao pedido de nome o mesmo padrão dos grupos de ações."""
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        dialog.setLabelText(label)
        dialog.setTextValue(initial_value)
        dialog.setOkButtonText(accept_text)
        dialog.setCancelButtonText("Cancelar")
        dialog.setStyleSheet(
            "QInputDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
            "QLabel { color: #57606a; }"
            "QLineEdit { min-height: 34px; border: 1px solid #d0d7de; border-radius: 6px;"
            " padding: 2px 9px; background: #ffffff; }"
            "QPushButton { min-height: 34px; padding: 4px 16px; border: 0; border-radius: 6px;"
            " background: #f6f8fa; color: #57606a; }"
            "QPushButton:hover { background: #eaeef2; }"
        )
        for button in dialog.findChildren(QPushButton):
            button.setIcon(QIcon())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.textValue().strip()

    def _remove_combination(self) -> None:
        current = self.combination_list.currentItem()
        if current is None:
            return
        self.action_service.remove_combination(self._combination_name(current))
        self._refresh_combinations()

    def _load_combination(self, name: str) -> None:
        self._loading = True
        combination = self.window.model.load_combinations.get(name)
        factors = (dict(combination.factors), dict(combination.factors_2), dict(combination.factors_3)) if combination else ({}, {}, {})
        active_actions = set(combination.active_actions) if combination and combination.active_actions is not None else {
            action.abbreviation for action in self._group_actions
        }
        # A grade pode ser recarregada ao reabrir a janela ou alternar a
        # combinação. Remover os widgets anteriores evita que um editor de
        # fator permaneça associado a uma coluna antiga.
        self.factors_table.clearContents()
        self.factors_table.setRowCount(len(self._group_actions))
        for row, action in enumerate(self._group_actions):
            checkbox = QCheckBox()
            checkbox.setAccessibleName(f"Incluir {action.name}")
            is_active = combination is not None and action.abbreviation in active_actions
            checkbox.setChecked(is_active)
            checkbox.setEnabled(combination is not None)
            action_container = QWidget()
            action_layout = QHBoxLayout(action_container)
            action_layout.setContentsMargins(10, 0, 8, 0)
            action_layout.setSpacing(8)
            action_layout.addWidget(checkbox)
            action_label = QLabel(f"{action.name} ({action.abbreviation})")
            action_label.setObjectName("combinationAction")
            action_layout.addWidget(action_label, 1)
            self.factors_table.setCellWidget(row, 0, action_container)
            for factor_index, values in enumerate(factors):
                field = QLineEdit(self._format_factor(values.get(action.abbreviation, 1.0)) if is_active else "")
                field.setAlignment(Qt.AlignmentFlag.AlignCenter)
                field.setEnabled(is_active)
                field.editingFinished.connect(
                    lambda r=row, index=factor_index, input_field=field: self._save_factor(r, index, input_field)
                )
                self.factors_table.setCellWidget(row, factor_index + 1, field)
            checkbox.toggled.connect(lambda checked, r=row: self._set_action_enabled(r, checked))
        self._loading = False
        has_selection = combination is not None
        self.edit_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)
        for state, button in self.limit_state_buttons.items():
            button.blockSignals(True)
            button.setChecked(combination is not None and combination.limit_state == state)
            button.setEnabled(has_selection)
            button.blockSignals(False)

    def _set_action_enabled(self, row: int, enabled: bool) -> None:
        if self._loading or self.combination_list.currentItem() is None or row >= len(self._group_actions):
            return
        name = self._combination_name(self.combination_list.currentItem())
        combination = self.window.model.load_combinations[name]
        action = self._group_actions[row]
        selected = set(combination.active_actions) if combination.active_actions is not None else {
            item.abbreviation for item in self._group_actions
        }
        if enabled:
            selected.add(action.abbreviation)
        else:
            selected.discard(action.abbreviation)
        active_actions = tuple(
            item.abbreviation for item in self._group_actions if item.abbreviation in selected
        )
        from osa.domain import LoadCombination
        self.action_service.set_combination(LoadCombination(
            name, combination.factors, combination.factors_2, combination.factors_3,
            active_actions, combination.action_group or self._active_group_name, combination.limit_state,
        ))
        values = (dict(combination.factors), dict(combination.factors_2), dict(combination.factors_3))
        for factor_index, factors_for_column in enumerate(values):
            field = self.factors_table.cellWidget(row, factor_index + 1)
            field.setEnabled(enabled)
            field.setText(self._format_factor(factors_for_column.get(action.abbreviation, 1.0)) if enabled else "")
        self._refresh_current_expression()

    def _set_limit_state(self, state: str) -> None:
        if self._loading or self.combination_list.currentItem() is None:
            return
        name = self._combination_name(self.combination_list.currentItem())
        combination = self.window.model.load_combinations[name]
        if combination.limit_state == state:
            return
        self.action_service.set_combination(LoadCombination(
            name, combination.factors, combination.factors_2, combination.factors_3,
            combination.active_actions, combination.action_group or self._active_group_name, state,
        ))
        self._refresh_current_expression()

    @staticmethod
    def _format_factor(value: float) -> str:
        return f"{value:.2f}".replace(".", ",")

    def _save_factor(self, row: int, factor_index: int, field: QLineEdit) -> None:
        if self._loading or self.combination_list.currentItem() is None or row >= len(self._group_actions):
            return
        try:
            value = float(field.text().strip().replace(",", "."))
        except ValueError:
            self._load_combination(self._combination_name(self.combination_list.currentItem()))
            return
        name = self._combination_name(self.combination_list.currentItem())
        combination = self.window.model.load_combinations[name]
        all_factors = [dict(combination.factors), dict(combination.factors_2), dict(combination.factors_3)]
        all_factors[factor_index][self._group_actions[row].abbreviation] = value
        from osa.domain import LoadCombination
        self.action_service.set_combination(LoadCombination(
            name, *(tuple(values.items()) for values in all_factors),
            combination.active_actions, combination.action_group or self._active_group_name, combination.limit_state,
        ))
        field.setText(self._format_factor(value))
        self._refresh_current_expression()
