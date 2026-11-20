"""Declare gravity floor contributions and generate inspectable notional cases."""
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from osa.domain.notional_inputs import NotionalStation
from osa.services.notional_service import (
    base_ultimate_combinations,
    generate_notionals,
    notional_plan_current,
    remove_notionals,
)


class NotionalDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle('Imperfeições e forças nocionais — modelo de barras')
        self.resize(980, 540)
        layout = QVBoxLayout(self)
        note = QLabel('Informe a contribuição gravitacional de cálculo APLICADA em cada nó/nível, em cada ELU base. '
            'Não use o esforço axial acumulado do pilar. Os pares nó do nível/nó da base controlam o deslocamento relativo à base da estrutura, usado na classificação de deslocabilidade. '
            'Inclua todos os níveis e elementos resistentes relevantes; nós intermediários de pilares podem ter contribuição zero. '
            'O programa gera 0,3% em ±X e ±Y separadamente, adicionados também às combinações com vento, e ativa P–Delta com EA/EI=0,8 nos ELU.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(('Nível', 'Nó superior', 'Nó da base', 'ELU base', 'G de cálculo (kN)'))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.table, 'Contribuições gravitacionais')
        self.generated = QTableWidget(0, 5, self)
        self.generated.setHorizontalHeaderLabels(('Combinação', 'Nó', 'Direção', 'Força (kN)', 'Caso de carga'))
        self.generated.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.generated.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.generated, 'Casos gerados')
        layout.addWidget(self.tabs)
        buttons = QHBoxLayout()
        add = QPushButton('Adicionar contribuição', self)
        add.clicked.connect(lambda: self._add())
        remove = QPushButton('Remover linha', self)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        clear = QPushButton('Excluir casos gerados', self)
        clear.clicked.connect(self._clear)
        clear.setEnabled(model.notional_plan is not None)
        buttons.addWidget(clear)
        layout.addLayout(buttons)
        self.reviewed = QCheckBox('Conferi todos os níveis, nós e contribuições gravitacionais em todas as combinações ELU base.', self)
        layout.addWidget(self.reviewed)
        self.large = QCheckBox('Opção do responsável: procedimento alternativo para grande deslocabilidade (4.10.7.2).', self)
        self.large.setToolTip('Sem essa opção, grande deslocabilidade exige análise rigorosa fora deste procedimento. Com ela, usa-se o procedimento de média deslocabilidade, com forças nocionais também nas combinações com ações horizontais. Não substitui a verificação de resistências ou ligações.')
        layout.addWidget(self.large)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        controls.button(QDialogButtonBox.StandardButton.Save).setText('Gerar e substituir casos')
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        controls.accepted.connect(self._save)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        if model.notional_plan:
            for station in model.notional_plan.stations:
                for combo, gravity in station.gravity_kn:
                    self._add((station.level, station.upper_node, station.base_node, combo, gravity))
            for name in model.notional_plan.actions:
                action = model.actions.get(name)
                if action is None:
                    continue
                combinations = [combo for combo in model.notional_plan.combinations
                                if combo in model.load_combinations and action.load_case in dict(model.load_combinations[combo].factors)]
                row = self.generated.rowCount()
                self.generated.insertRow(row)
                for column, value in enumerate((', '.join(combinations), action.target,
                                               action.kind.rsplit('_', 1)[-1], action.components[0], action.load_case)):
                    self.generated.setItem(row, column, QTableWidgetItem(str(value)))
            self.large.setChecked(model.notional_plan.allow_large_displacement)
            self.reviewed.setChecked(notional_plan_current(model))
        self.error.setText('Inspecione as ações efetivamente geradas na aba Casos gerados e as combinações no projeto. Alterações físicas ou de cargas exigem revisar e gerar novamente.')

    def _add(self, values=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = values or ('Nível '+str(row+1), '', '', '', 0.)
        for column in (0, 1, 2, 4):
            self.table.setItem(row, column, QTableWidgetItem(str(values[column])))
        combo = QComboBox(self.table)
        combo.addItems(tuple(base_ultimate_combinations(self.model)))
        if values[3] and combo.findText(values[3]) < 0:
            combo.addItem(values[3])
        if values[3]:
            combo.setCurrentText(values[3])
        self.table.setCellWidget(row, 3, combo)

    def _save(self):
        if not self.reviewed.isChecked():
            self.error.setText('Confirme a revisão dos níveis e de todas as contribuições gravitacionais.')
            return
        try:
            nodes = {}
            for row in range(self.table.rowCount()):
                values = [self.table.item(row, column).text().strip() if self.table.item(row, column) else '' for column in range(5)]
                level, upper, lower = values[:3]
                combo = self.table.cellWidget(row, 3).currentText()
                gravity = float(values[4].replace(',', '.'))
                record = nodes.setdefault(upper, (level, lower, {}))
                if (record[0], record[1]) != (level, lower) or combo in record[2]:
                    raise ValueError('Cada nó superior deve ter o mesmo nível/nó da base e uma única contribuição por combinação.')
                record[2][combo] = gravity
            stations = tuple(NotionalStation(level, upper, lower, tuple(gravity.items()))
                             for upper, (level, lower, gravity) in nodes.items())
            generate_notionals(self.model, stations, allow_large_displacement=self.large.isChecked())
        except (KeyError, TypeError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def _clear(self):
        try:
            remove_notionals(self.model)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()
