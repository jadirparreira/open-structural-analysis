"""Transient properties for placing a plate by coordinates or boundary bars."""

from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout,
    QLabel, QVBoxLayout,
)

from .common import QFrame, QSignalBlocker
from .property_panel import SpringDirectionSwitch, SelectionKindSwitch


class PlatePlacementEditor(QFrame):
    """Small creation panel that keeps plate settings out of the model until commit."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)

        self.title = QLabel("Adicionar placa")
        self.title.setObjectName("propertyTitle")
        layout.addWidget(self.title)

        self.placement_mode_switch = SelectionKindSwitch(
            self,
            choices=(("exact", "Ponto exato"), ("bars", "Selecionar barra")),
        )
        self.placement_mode_switch.set_selection("exact")
        self.placement_mode_switch._buttons["exact"].setToolTip(
            "Desenhar o contorno clicando em cada vértice"
        )
        self.placement_mode_switch._buttons["bars"].setToolTip(
            "Formar o contorno selecionando barras existentes"
        )
        layout.addWidget(self.placement_mode_switch)

        material_title = QLabel("Material")
        material_title.setObjectName("propertySection")
        layout.addWidget(material_title)
        self.material_combo = QComboBox()
        self.material_combo.setAccessibleName("Material da placa")
        self.material_combo.setPlaceholderText("Selecione um concreto")
        layout.addWidget(self.material_combo)

        section_title = QLabel("Seção")
        section_title.setObjectName("propertySection")
        layout.addWidget(section_title)
        self.section_combo = QComboBox()
        self.section_combo.addItem("Retangular")
        self.section_combo.setCurrentIndex(0)
        self.section_combo.setAccessibleName("Seção da placa")
        self.section_combo.setEnabled(False)
        layout.addWidget(self.section_combo)

        thickness_title = QLabel("Espessura")
        thickness_title.setObjectName("propertySection")
        layout.addWidget(thickness_title)
        self.thickness_mm = QDoubleSpinBox()
        self.thickness_mm.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.thickness_mm.setDecimals(2)
        self.thickness_mm.setRange(0.01, 1_000_000.0)
        self.thickness_mm.setValue(100.0)
        self.thickness_mm.setAccessibleName("Espessura da placa (mm)")
        self.thickness_mm.setSuffix(" mm")
        layout.addWidget(self.thickness_mm)

        restraint_title = QLabel("Restrições")
        restraint_title.setObjectName("propertySection")
        layout.addWidget(restraint_title)
        self.restriction_checks = []
        self.restriction_direction_switches = []
        self.restriction_stiffness_fields = []
        for axis in ("Dx", "Dy", "Dz"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            checkbox = QCheckBox(axis)
            checkbox.setAccessibleName(f"Restringir {axis} da placa")
            direction = SpringDirectionSwitch("=", self)
            direction.setAccessibleName(f"Sentido global da mola {axis}")
            spring = QDoubleSpinBox()
            spring.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spring.setDecimals(3)
            spring.setRange(0.0, 1_000_000_000.0)
            spring.setAccessibleName(f"Mola {axis} da placa (kN/m³)")
            spring.setToolTip(
                "Rigidez distribuída da fundação em kN/m³. "
                "Com o eixo marcado, valor zero significa apoio rígido."
            )
            unit = QLabel("kN/m³")
            row.addWidget(checkbox)
            row.addWidget(direction)
            row.addWidget(spring, 1)
            row.addWidget(unit)
            layout.addLayout(row)
            self.restriction_checks.append(checkbox)
            self.restriction_direction_switches.append(direction)
            self.restriction_stiffness_fields.append(spring)
        self.hide()

    @property
    def placement_mode(self) -> str:
        return "exact" if self.placement_mode_switch._buttons["exact"].isChecked() else "bars"

    @property
    def material(self) -> str | None:
        return self.material_combo.currentText() or None

    @property
    def restrictions(self) -> tuple[bool, bool, bool]:
        return tuple(checkbox.isChecked() for checkbox in self.restriction_checks)

    @property
    def restriction_stiffness(self) -> tuple[float, float, float]:
        return tuple(field.value() for field in self.restriction_stiffness_fields)

    @property
    def restriction_directions(self) -> tuple[str, str, str]:
        return tuple(field.value for field in self.restriction_direction_switches)

    def show_for_model(self, model) -> None:
        current = self.material_combo.currentText()
        concrete_materials = [
            name for name in model.materials
            if model.material_types.get(name) == "Concreto"
        ]
        with QSignalBlocker(self.material_combo):
            self.material_combo.clear()
            self.material_combo.addItems(concrete_materials)
            if current in concrete_materials:
                self.material_combo.setCurrentText(current)
            elif concrete_materials:
                self.material_combo.setCurrentIndex(0)
        layout = self.layout()
        layout.activate()
        self.setMinimumHeight(0)
        self.adjustSize()
        self.resize(self.width(), self.sizeHint().height())
        self.reposition()
        super().show()
        self.raise_()

    def reposition(self) -> None:
        margin = 0 if self._window.isMaximized() else 12
        self.move(
            self._window.width() - margin - self.width() - 24,
            (self._window.height() - self.height()) // 2,
        )
        self.raise_()
