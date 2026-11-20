"""Manual design-property overrides for the selected verification member."""

from __future__ import annotations

from math import dist
from typing import ClassVar

from PySide6.QtWidgets import QScrollArea

from osa.memorial_data import calculation_memory
from osa.verification.cold_formed_member import FAMILIES as COLD_FAMILIES

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
            "para diagrama de momento não uniforme (NBR 8800:2024, 5.4.2.3). "
            "O OSA calcula Cb com o diagrama amostrado na combinação mais desfavorável e no "
            "intervalo Lb identificado. Um valor informado substitui o cálculo automático. "
            "Se Lb for definido manualmente sem informar a posição do trecho, o OSA adota Cb = 1,0 "
            "porque o escalar não localiza o intervalo no diagrama. "
            "A expressão automática pressupõe as condições gerais de 5.4.2.3(a); cargas fora da "
            "semialtura ou contenções especiais podem exigir análise própria."
        ),
        "An": "Área líquida na região da ligação (cm²), calculada conforme os furos, recortes e a norma aplicável.",
        "An0": "Área líquida fora da região da ligação (cm²), conforme a NBR 14762:2010, 9.6.2(b).",
        "LvY": "Distância entre as seções de cortante Y máximo e nulo, conforme a NBR 8800:2024, 5.4.3.6.",
        "LvZ": "Distância entre as seções de cortante Z máximo e nulo, conforme a NBR 8800:2024, 5.4.3.6.",
        "KL1": "Comprimento efetivo de flambagem K₁L₁, em metros, no eixo principal de maior inércia do perfil formado. Necessário para KL/r ≤ 200 (NBR 14762:2010, 9.7.4). Não é o esforço crítico nem apenas o comprimento geométrico. Alterações físicas do modelo invalidam este valor.",
        "KL2": "Comprimento efetivo de flambagem K₂L₂, em metros, no eixo principal de menor inércia do perfil formado. Necessário para KL/r ≤ 200 (NBR 14762:2010, 9.7.4). O OSA não deduz K dos apoios. Alterações físicas do modelo invalidam este valor.",
        "KLt": "Comprimento efetivo de flambagem por torção KtLt (m). Com KL1 e KL2 permite calcular o crítico global dos formados. Sem garantia de impedimento ao empenamento, a NBR 14762:2010, 9.7.2.1, determina Kt=1. Alterações físicas invalidam o valor.",
        "DeltaY": "Deslocamento máximo admissível no eixo local Y (mm), definido pelo uso, vão e combinações de serviço da NBR 14762:2010, Anexo A. A medição é selecionada abaixo. O programa não presume o uso estrutural da barra.",
        "DeltaZ": "Deslocamento máximo admissível no eixo local Z (mm), definido pelo uso, vão e combinações de serviço da NBR 14762:2010, Anexo A. Informe o limite aplicável às combinações ELS verificadas, incluindo limites absolutos quando exigidos.",
    }
    _MRD_KEYS: ClassVar[tuple[str, ...]] = ("NcrG", "NcrL", "NcrD", "McrGy", "McrLy", "McrDy", "McrGz", "McrLz", "McrDz")
    _TOOLTIPS.update({key: (
        "Esforço crítico de flambagem elástica " + {"G": "global", "L": "local", "D": "distorcional"}[key[3]] +
        (" (kN)." if key.startswith("N") else " (kN·m), em torno do eixo " + key[-1].upper() + ".") +
        " Deve vir de análise geral de estabilidade da seção e contenções efetivas (NBR 14762:2010, C.2). " +
        ("O OSA determina automaticamente os modos local e distorcional por análise elástica de faixas finitas; "
         "um valor manual substitui a estimativa automática. " if key[3] in {"L", "D"} else
         "O modo global pode ser calculado com KL1/KL2/KLt; para flexão exige ainda confirmação dos vínculos de garfo e carregamento no centro de torção. ") +
        ("Para flexão, o cálculo automático considera os dois sinais em momento uniforme; informe uma envoltória "
         "manual quando o diagrama ou as condições reais exigirem análise própria. " if key.startswith("M") else "") +
        "Alterações na geometria, materiais, apoios, cargas ou agrupamento invalidam e removem os esforços críticos afetados; informe os resultados da nova análise elástica."
    ) for key in _MRD_KEYS})
    _FIELDS: ClassVar[tuple[tuple[str, str, str, int, float, float], ...]] = (
        ("Ly", "L<sub>y</sub>", "m", 3, 0.001, 100_000.0),
        ("Lz", "L<sub>z</sub>", "m", 3, 0.001, 100_000.0),
        ("Lt", "L<sub>t</sub>", "m", 3, 0.001, 100_000.0),
        ("Lb", "L<sub>b</sub>", "m", 3, 0.001, 100_000.0),
        ("Ct", "C<sub>t</sub>", "", 3, 0.001, 1.0),
        ("Cb", "C<sub>b</sub>", "", 3, 1.0, 1.0e12),
        ("An", "A<sub>n</sub>", "cm²", 4, 0.0, 1.0e8),
        ("An0", "A<sub>n0</sub>", "cm²", 4, 0.0, 1.0e8),
        ("LvY", "L<sub>v,Y</sub>", "m", 3, 0.0, 100_000.0),
        ("LvZ", "L<sub>v,Z</sub>", "m", 3, 0.0, 100_000.0),
    ) + (("KL1", "K₁L₁", "m", 3, 0.0, 100_000.0),
         ("KL2", "K₂L₂", "m", 3, 0.0, 100_000.0),
         ("KLt", "KₜLₜ", "m", 3, 0.0, 100_000.0)) + tuple(
             (key, key, "kN" if key.startswith("N") else "kN·m", 4, 0.0, 1.0e12) for key in _MRD_KEYS) + (
                 ("DeltaY", "δ<sub>lim,Y</sub>", "mm", 3, 0.0, 100_000.),
                 ("DeltaZ", "δ<sub>lim,Z</sub>", "mm", 3, 0.0, 100_000.))
    _CB_SECTIONS: ClassVar[frozenset[str]] = frozenset({
        "I Laminado", "W Laminado", "HP Laminado", "U Laminado",
        "Barra Retangular", "Barra Quadrada",
        "Tubular Quadrado", "Tubular Retangular",
    })
    _LB_SECTIONS: ClassVar[frozenset[str]] = _CB_SECTIONS | {"T Laminado"}
    _LT_SECTIONS: ClassVar[frozenset[str]] = frozenset(
        {"I Laminado", "W Laminado", "HP Laminado", "U Laminado"}
    )
    _NET_SECTIONS: ClassVar[frozenset[str]] = frozenset({
        "W Laminado", "HP Laminado", "I Laminado", "U Laminado", "L Laminado", "T Laminado",
        "Tubular Circular", "Tubular Quadrado", "Tubular Retangular",
        "U Formado", "C Formado", "Z Formado", "Z45 Formado", "Z90 Formado", "L Formado", "Cartola Formado",
    })

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
        self._absent_buttons: dict[str, QToolButton] = {}
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
            reset_action = "Limpar valor informado" if name in {"An", "An0", "Ct", "LvY", "LvZ", "KL1", "KL2", "KLt", "DeltaY", "DeltaZ"} or name in self._MRD_KEYS else "Restaurar valor automático"
            reset.setToolTip(reset_action)
            reset.setAccessibleName(f"{reset_action} de {name}")
            reset.setStyleSheet("QToolButton { color: #57606a; border: 0; padding: 0; }")
            reset.clicked.connect(lambda _checked=False, key=name: self._reset_value(key))
            reset.hide()
            self._reset_buttons[name] = reset
            label_layout.addWidget(reset)
            label_layout.addStretch(1)
            if name in self._MRD_KEYS:
                absent = QToolButton(label_row)
                absent.setText("∅")
                absent.setCheckable(True)
                absent.setAutoRaise(True)
                absent.setFixedSize(18, 18)
                absent.setAccessibleName(f"Modo de flambagem ausente: {name}")
                absent.setToolTip("Marque somente se a análise geral de estabilidade elástica comprovar que este modo não ocorre (NBR 14762:2010, C.2). Desmarcar restaura a entrada do esforço crítico.")
                absent.toggled.connect(lambda checked, key=name: self._save_value(key, -1. if checked else None))
                label_layout.addWidget(absent)
                self._absent_buttons[name] = absent
            spin = QDoubleSpinBox()
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        self._fork_supports = QCheckBox("Vínculos de garfo para FLT", self)
        self._fork_supports.setToolTip("Confirme somente para trechos com contenções laterais e torsionais nas extremidades, empenamento livre e cargas no centro de torção (ou em posição comprovadamente estabilizante). O cálculo envolve ambos os sinais de momento uniforme, sem ganho por gradiente de momento. Outras condições exigem crítico externo de análise própria.")
        self._fork_supports.toggled.connect(lambda checked: self._save_value("ForkSupports", 1. if checked else None))
        fields_grid.addWidget(self._fork_supports, (len(self._FIELDS)+1)//2, 0, 1, 2)
        self._service_measure = QComboBox(self)
        self._service_measure.addItem("Escolher medição de serviço", None)
        self._service_measure.addItem("Flecha relativa à corda", 1.)
        self._service_measure.addItem("Deslocamento entre extremidades", 2.)
        self._service_measure.addItem("Deslocamento absoluto", 3.)
        self._service_measure.setToolTip("Flecha: desconta a reta entre os deslocamentos das extremidades do elemento, inclusive grupos. Deslocamento entre extremidades: diferença transversal entre os dois extremos, para controles de deslocamento relativo. Deslocamento absoluto: componente transversal sem descontar a corda. Os limites em mm devem corresponder à medição e às combinações escolhidas.")
        self._service_measure.currentIndexChanged.connect(lambda index: self._save_value(
            "ServiceMeasure", self._service_measure.itemData(index)))
        fields_grid.addWidget(self._service_measure, (len(self._FIELDS)+1)//2+1, 0, 1, 2)
        self._bearing_button = QPushButton("Forças concentradas e apoios…", self)
        self._bearing_button.clicked.connect(self._edit_bearing_regions)
        fields_grid.addWidget(self._bearing_button, (len(self._FIELDS)+1)//2+2, 0, 1, 2)
        fields = QWidget(self)
        fields.setLayout(fields_grid)
        scroll = QScrollArea(self)
        scroll.setObjectName("calculationPropertiesScroll")
        scroll.setStyleSheet("QScrollArea#calculationPropertiesScroll, QScrollArea#calculationPropertiesScroll QWidget#qt_scrollarea_viewport { background: transparent; border: 0; }")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(fields)
        fields.setAutoFillBackground(False)
        layout.addWidget(scroll, 1)
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
        cold = bool(sections) and sections <= COLD_FAMILIES
        self._fork_supports.setVisible(cold)
        self._service_measure.setVisible(cold)
        self._bearing_button.setVisible(cold)
        with QSignalBlocker(self._fork_supports):
            self._fork_supports.setChecked(bool(members) and all(
                dict(member.calculation_property_overrides).get("ForkSupports") == 1. for member in members))
        values = [dict(member.calculation_property_overrides).get("ServiceMeasure") for member in members]
        value = values[0] if values and all(item == values[0] for item in values) else None
        with QSignalBlocker(self._service_measure):
            self._service_measure.setCurrentIndex(max(0, self._service_measure.findData(value)))
        for name, _label, _unit, _decimals, _minimum, _maximum in self._FIELDS:
            values = [dict(member.calculation_property_overrides).get(name) for member in members]
            present = [value for value in values if value is not None]
            spin = self._inputs[name]
            reset = self._reset_buttons[name]
            tooltip = self._TOOLTIPS[name]
            if sections == {"L Laminado"} and name in {"Ly", "Lz"}:
                tooltip = "Comprimento de flambagem no eixo principal " + ("maior" if name == "Ly" else "menor") + " da cantoneira. Informe ambos Ly e Lz; contenções nos eixos geométricos não são automaticamente contenções dos eixos principais."
            if name == "Ct" and sections and sections <= COLD_FAMILIES:
                tooltip = "Coeficiente de redução da área líquida na ligação, conforme NBR 14762:2010, 9.6.2(c). Não é inferido pela geometria bruta."
            self._labels[name].setToolTip(tooltip)
            spin.setToolTip(tooltip)
            spin.parentWidget().setToolTip(tooltip)
            applicable = (
                name != "Cb" or sections <= self._CB_SECTIONS
            ) and (
                name != "Lb" or sections <= self._LB_SECTIONS
            ) and (
                name != "Lt" or sections <= self._LT_SECTIONS
            ) and (
                name not in {"An", "An0"} or sections <= self._NET_SECTIONS
            ) and (
                name not in {"LvY", "LvZ"} or sections == {"Tubular Circular"}
            ) and (
                name != "An0" or sections <= COLD_FAMILIES
            )
            cold = bool(sections) and sections <= COLD_FAMILIES
            if name in {"Ly", "Lz", "Lt", "Lb", "Cb"}:
                # MRD consumes external global criticals. Geometric Ly/Lz
                # remain available for the separate tension recommendation.
                spin.parentWidget().parentWidget().setVisible(bool(members) and (not cold or name in {"Ly", "Lz"}))
                if cold and name not in {"Ly", "Lz"}:
                    applicable = False
            if cold and name in {"Ly", "Lz"}:
                tooltip = "Comprimento destravado geométrico " + name + " para a recomendação de tração L/r ≤ 300 (NBR 14762:2010, 9.6.3). Não substitui K₁L₁/K₂L₂ da compressão; em eixos inclinados é usada uma estimativa conservadora com o maior comprimento."
                self._labels[name].setToolTip(tooltip)
                spin.setToolTip(tooltip)
                spin.parentWidget().setToolTip(tooltip)
            if name in self._MRD_KEYS or name in {"KL1", "KL2", "KLt", "DeltaY", "DeltaZ"}:
                applicable = cold
            if name in {"An", "An0", "LvY", "LvZ", "KL1", "KL2", "KLt", "DeltaY", "DeltaZ"} or name in self._MRD_KEYS:
                spin.parentWidget().parentWidget().setVisible(bool(members) and applicable)
                automatic_mrd = name in self._MRD_KEYS
                spin.setSpecialValueText("Automático" if automatic_mrd else "Informar")
            if name == "Ct":
                explicit = bool(sections) and sections <= self._NET_SECTIONS
                spin.setMinimum(0.0 if explicit else 0.001)
                spin.setSpecialValueText("Informar" if explicit else "")
            enabled = bool(members) and applicable
            is_absent = bool(present) and len(present) == len(members) and all(value == -1 for value in present)
            if name in self._absent_buttons:
                with QSignalBlocker(self._absent_buttons[name]):
                    self._absent_buttons[name].setChecked(is_absent)
                spin.setSpecialValueText("Ausente" if is_absent else "Automático" if automatic_mrd else "Informar")
                self._unit_labels[name].setVisible(not is_absent)
            spin.setEnabled(enabled and not is_absent)
            with QSignalBlocker(spin):
                spin.setValue(0. if is_absent else present[0] if present else self._initial_value(name))
            self._displayed_values[name] = spin.value()
            reset.setVisible(bool(present))
            reset.setEnabled(enabled)

    def _initial_value(self, name: str) -> float:
        if name in {"An", "An0", "LvY", "LvZ", "KL1", "KL2", "KLt", "DeltaY", "DeltaZ"} or name in self._MRD_KEYS:
            return 0.0
        if name == "Ct" and self._member_names and all(
            self.window.model.bars[key].section in self._NET_SECTIONS for key in self._member_names
        ):
            return 0.0
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

    def _edit_bearing_regions(self):
        from .cold_formed_bearing_dialog import ColdFormedBearingDialog

        dialog = ColdFormedBearingDialog(self.window.model, self._member_names, self)
        if dialog.exec():
            self.window.refresh_scene()
            self.window.verification_panel.status.setText("Regiões de contato atualizadas. Execute novamente a verificação.")

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
