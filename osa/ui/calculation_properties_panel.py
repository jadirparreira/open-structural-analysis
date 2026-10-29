"""Manual design-property overrides for the selected verification member."""

from __future__ import annotations

from math import dist
from typing import ClassVar

from osa.memorial_data import calculation_memory

from .common import *


class CalculationPropertiesPanel(QFrame):
    WIDTH = 300
    _TOOLTIPS: ClassVar[dict[str, str]] = {
        "Ly": (
            "Comprimento destravado adotado para flambagem por flexão no eixo local y. "
            "Na NBR 8800:2024, Ly está associado à flexão em torno do eixo central y (5.3.5.1)."
        ),
        "Lz": (
            "No OSA, comprimento destravado adotado para flambagem por flexão no eixo local z. "
            "Atenção à nomenclatura: na NBR 8800:2024, Lz identifica o comprimento para "
            "flambagem por torção (5.3.5.1); no OSA, a torção está no campo Lt."
        ),
        "Lt": (
            "Comprimento destravado adotado pelo OSA para flambagem por torção. "
            "A NBR 8800:2024 identifica esse comprimento pelo símbolo Lz (5.3.5.1). "
            "No cálculo automático atual do OSA, Lt é o menor entre Ly e Lz."
        ),
        "Lb": (
            "Comprimento sem contenção lateral usado na verificação de flambagem lateral com torção "
            "(FLT) e no cálculo de Cb (NBR 8800:2024, 5.4.2.3). "
            "No cálculo automático atual do OSA, Lb acompanha Ly."
        ),
        "Ct": (
            "Coeficiente de redução da área líquida efetiva: Ae = Ct · An. "
            "A NBR 8800:2024 determina Ct conforme a ligação e a transferência dos esforços "
            "(5.2.3 e 5.2.5)."
        ),
        "Cb": (
            "Fator de modificação da resistência à flambagem lateral com torção (FLT) "
            "para diagrama de momento não uniforme ao longo de Lb (NBR 8800:2024, "
            "5.4.2.3 a 5.4.2.5). O cálculo automático do OSA usa o diagrama de momentos. "
            "Faixa aceita pelo campo: 1,0 a 2,5."
        ),
    }
    _FIELDS: ClassVar[tuple[tuple[str, str, str, int, float, float], ...]] = (
        ("Ly", "L<sub>y</sub>", "m", 3, 0.001, 100_000.0),
        ("Lz", "L<sub>z</sub>", "m", 3, 0.001, 100_000.0),
        ("Lt", "L<sub>t</sub>", "m", 3, 0.001, 100_000.0),
        ("Lb", "L<sub>b</sub>", "m", 3, 0.001, 100_000.0),
        ("Ct", "C<sub>t</sub>", "", 3, 0.001, 1.0),
        ("Cb", "C<sub>b</sub>", "", 3, 1.0, 2.5),
    )
    _CB_SECTIONS: ClassVar[frozenset[str]] = frozenset({
        "I Laminado", "W Laminado", "HP Laminado", "U Laminado", "U Inclinado Laminado",
        "Barra Retangular", "Barra Quadrada",
    })
    _LB_SECTIONS: ClassVar[frozenset[str]] = _CB_SECTIONS | {"T Laminado"}
    _LT_SECTIONS: ClassVar[frozenset[str]] = frozenset(
        {"I Laminado", "W Laminado", "HP Laminado", "U Laminado", "U Inclinado Laminado"}
    )

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("propertyPanel")
        self.setFixedWidth(self.WIDTH)
        self.setMinimumHeight(0)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self._member_names: tuple[str, ...] = ()
        self._automatic_lengths_m: dict[str, float] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel("Propriedades de Cálculo")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)

        self._inputs: dict[str, QDoubleSpinBox] = {}
        self._displayed_values: dict[str, float] = {}
        self._labels: dict[str, QLabel] = {}
        self._reset_buttons: dict[str, QToolButton] = {}
        self._unit_labels: dict[str, QLabel] = {}
        fields_grid = QGridLayout()
        fields_grid.setContentsMargins(0, 0, 0, 0)
        fields_grid.setHorizontalSpacing(10)
        fields_grid.setVerticalSpacing(10)
        fields_grid.setColumnStretch(0, 1)
        fields_grid.setColumnStretch(1, 1)
        for index, (name, label_text, unit, decimals, minimum, maximum) in enumerate(self._FIELDS):
            item = QWidget(self)
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            label_row = QWidget(item)
            label_layout = QHBoxLayout(label_row)
            label_layout.setContentsMargins(0, 0, 0, 0)
            label_layout.setSpacing(3)
            label = QLabel(label_text)
            label.setObjectName("propertyName")
            label.setToolTip(self._TOOLTIPS[name])
            self._labels[name] = label
            label_layout.addWidget(label)
            reset = QToolButton(label_row)
            reset.setAutoRaise(True)
            reset.setFixedSize(16, 16)
            reset.setIcon(QIcon(str(
                Path(__file__).parents[1] / "resources" / "icons" / "pen.svg"
            )))
            reset.setIconSize(QSize(13, 13))
            reset.setToolTip("Restaurar valor automático")
            reset.setAccessibleName(f"Restaurar valor automático de {name}")
            reset.setStyleSheet("QToolButton { color: #57606a; border: 0; padding: 0; }")
            reset.clicked.connect(lambda _checked=False, key=name: self._reset_value(key))
            reset.hide()
            self._reset_buttons[name] = reset
            label_layout.addWidget(reset)
            label_layout.addStretch(1)
            spin = QDoubleSpinBox()
            spin.setDecimals(decimals)
            spin.setRange(minimum, maximum)
            spin.setSingleStep(0.1 if unit == "m" else 0.05)
            spin.setKeyboardTracking(False)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setAccessibleName(f"Valor manual de {name}")
            spin.setToolTip(self._TOOLTIPS[name])
            spin.editingFinished.connect(lambda key=name: self._value_changed(key))
            item_layout.addWidget(label_row)
            value_box = QFrame(item)
            value_box.setObjectName("unitValueBox")
            value_box.setToolTip(self._TOOLTIPS[name])
            value_box.setStyleSheet(
                "QFrame#unitValueBox { min-height: 30px; border: 1px solid #d0d7de; "
                "border-radius: 6px; background: #ffffff; }"
                "QFrame#unitValueBox QDoubleSpinBox { border: 0; background: transparent; "
                "color: #57606a; padding: 2px 9px; }"
                "QFrame#unitValueBox QLabel { color: #57606a; padding-right: 9px; }"
            )
            value_layout = QHBoxLayout(value_box)
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(0)
            value_layout.addWidget(spin, 1)
            unit_label = QLabel(unit)
            unit_label.setVisible(bool(unit))
            value_layout.addWidget(unit_label)
            self._unit_labels[name] = unit_label
            item_layout.addWidget(value_box)
            fields_grid.addWidget(item, index // 2, index % 2)
            self._inputs[name] = spin
        layout.addLayout(fields_grid)
        self.hide()

    def configure_for(self, member_names: tuple[str, ...] | list[str]) -> None:
        self._member_names = tuple(dict.fromkeys(
            name for name in member_names if name in self.window.model.bars
        ))
        memory = calculation_memory(self.window.model, self._member_names)
        geometric_parameters = memory.get("geometric_parameters", {})
        self._automatic_lengths_m = {
            name: float(value) / 100.0
            for name in ("Ly", "Lz", "Lt", "Lb")
            if (value := geometric_parameters.get(f"{name}_cm")) is not None
        }
        members = [self.window.model.bars[name] for name in self._member_names]
        sections = {member.section for member in members}
        for name, _label, _unit, _decimals, _minimum, _maximum in self._FIELDS:
            values = [dict(member.calculation_property_overrides).get(name) for member in members]
            present = [value for value in values if value is not None]
            uniform = bool(present) and len(present) == len(values) and all(
                value == present[0] for value in present[1:]
            )
            spin = self._inputs[name]
            reset = self._reset_buttons[name]
            applicable = (
                name != "Cb" or sections <= self._CB_SECTIONS
            ) and (
                name != "Lb" or sections <= self._LB_SECTIONS
            ) and (
                name != "Lt" or sections <= self._LT_SECTIONS
            )
            enabled = bool(members) and applicable
            spin.setEnabled(enabled)
            with QSignalBlocker(spin):
                spin.setValue(present[0] if present else self._initial_value(name))
            self._displayed_values[name] = spin.value()
            reset.setVisible(bool(present))
            reset.setEnabled(enabled)

    def _initial_value(self, name: str) -> float:
        if name in {"Ct", "Cb"}:
            return 1.0
        if name in self._automatic_lengths_m:
            return max(0.001, self._automatic_lengths_m[name])
        lengths = []
        for member_name in self._member_names:
            member = self.window.model.bars[member_name]
            start, end = self.window.model.nodes[member.start_node], self.window.model.nodes[member.end_node]
            lengths.append(dist((start.x, start.y, start.z), (end.x, end.y, end.z)))
        return max(0.001, sum(lengths))

    def _value_changed(self, name: str) -> None:
        spin = self._inputs[name]
        if not spin.isEnabled():
            return
        value = spin.value()
        previous = self._displayed_values.get(name)
        if previous is not None and value == previous:
            return
        try:
            self._save_value(name, value)
        except ValueError as error:
            with QSignalBlocker(spin):
                spin.setValue(previous if previous is not None else spin.minimum())
            self.window.verification_panel.status.setText(str(error))
            return
        self._displayed_values[name] = spin.value()

    def _reset_value(self, name: str) -> None:
        self._save_value(name, None)

    def _save_value(self, name: str, value: float | None) -> None:
        model = self.window.model
        changed = False
        for member_name in self._member_names:
            before = dict(model.bars[member_name].calculation_property_overrides).get(name)
            if before != value:
                model.update_bar_calculation_property(member_name, name, value)
                changed = True
        if not changed:
            return
        self.window.refresh_scene()
        self.window.refresh_selected_property_panel(self.window.palette.active_group)
        affected = ", ".join(self._member_names)
        self.window.verification_panel.status.setText(
            f"Propriedades de cálculo de {affected} alteradas. "
            "Execute novamente a verificação desse elemento."
        )

    def reposition(self) -> None:
        prop = self.window.properties
        # This is an overlay child, not part of a parent layout. Its initial
        # QWidget height is therefore only the default (roughly one row),
        # which clips every control unless we apply the layout's size hint.
        self.adjustSize()
        panel_height = min(self.height(), max(1, self.window.height() - 24))
        self.resize(self.WIDTH, panel_height)
        x = prop.x() - self.width() - 12
        y = prop.y() + (prop.height() - self.height()) // 2
        x = max(12, min(x, self.window.width() - self.width() - 12))
        y = max(12, min(y, self.window.height() - self.height() - 12))
        self.move(
            x,
            y,
        )
        self.raise_()
