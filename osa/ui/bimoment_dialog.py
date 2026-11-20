"""Edit physical end bimoments, work-conjugate to the local twist rate."""
from math import isfinite

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from osa.domain import Action
from osa.verification.cold_formed_member import FAMILIES


class BimomentDialog(QDialog):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.revision = model.revision
        self.names = tuple(name for name, member in model.bars.items()
                           if member.section in FAMILIES and member.section != 'L Formado')
        self.cases = tuple(dict.fromkeys((*model.load_cases,
            *(case for combo in model.load_combinations.values() for case in combo.active_actions),
            *(action.load_case for action in model.actions.values()))))
        self.setWindowTitle('Bimomentos nas extremidades dos formados')
        self.resize(820, 430)
        layout = QVBoxLayout(self)
        note = QLabel('Informe a ação conjugada à derivada local da rotação torsional, em kN·m². '
            'No extremo A, a ação tem o sinal do bimomento interno B; no extremo B, o sinal oposto. '
            'A/B seguem os nós inicial/final da barra. Para transferência axial localizada, a ação é −F·ω(P), '
            'com a função setorial da seção. A cantoneira Cw=0 não admite essa ação. '
            'Ative a análise dos formados e declare os vínculos de empenamento.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(('Barra', 'Extremidade / nó', 'Caso de carga', 'Ação (kN·m²)'))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        add, remove = QPushButton('Adicionar', self), QPushButton('Remover linha', self)
        add.clicked.connect(lambda: self._add())
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        layout.addLayout(controls)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Salvar')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for action in model.actions.values():
            if action.kind in ('member_bimoment_A', 'member_bimoment_B'):
                self._add(action)

    def _add(self, action=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        bar, end, case = (QComboBox(self.table) for _ in range(3))
        bar.addItems(self.names)
        case.addItems(self.cases)
        for widget, value in ((bar, action.target if action else None), (case, action.load_case if action else None)):
            if value is not None:
                if widget.findText(value) < 0:
                    widget.addItem(value)
                widget.setCurrentText(value)
        def update_ends():
            selected = end.currentData()
            end.clear()
            member = self.model.bars.get(bar.currentText())
            for side, node in (('A', member.start_node if member else '?'), ('B', member.end_node if member else '?')):
                end.addItem(side+' / '+node, side)
            end.setCurrentIndex(max(0, end.findData(selected)))
        bar.currentTextChanged.connect(update_ends)
        update_ends()
        if action:
            end.setCurrentIndex(end.findData(action.kind[-1]))
        for col, widget in enumerate((bar, end, case)):
            widget.setAccessibleName(('Barra', 'Extremidade', 'Caso de carga')[col]+' do bimomento '+str(row+1))
            self.table.setCellWidget(row, col, widget)
        value = QTableWidgetItem(str(action.components[0]) if action else '0')
        value.setData(Qt.ItemDataRole.UserRole, action.name if action else None)
        self.table.setItem(row, 3, value)

    def _save(self):
        try:
            if self.model.revision != self.revision:
                raise ValueError('O modelo mudou; reabra o cadastro de bimomentos para preservar as alterações.')
            records, keys = [], set()
            for row in range(self.table.rowCount()):
                bar, end, case = (self.table.cellWidget(row, col) for col in range(3))
                target, side, load_case = bar.currentText(), end.currentData(), case.currentText()
                value = float(self.table.item(row, 3).text().replace(',', '.'))
                key = (target, side, load_case)
                if target not in self.names or side not in ('A', 'B') or load_case not in self.cases or not isfinite(value):
                    raise ValueError('Informe barra formada com modo setorial, extremidade, caso de carga e valor finito.')
                if key in keys:
                    raise ValueError('Há bimomentos duplicados para a mesma barra, extremidade e caso; informe a resultante.')
                keys.add(key)
                records.append((self.table.item(row, 3).data(Qt.ItemDataRole.UserRole), target, side, load_case, value))
            actions = {name: action for name, action in self.model.actions.items()
                       if action.kind not in ('member_bimoment_A', 'member_bimoment_B')}
            for name, target, side, case, value in records:
                if not name:
                    index = 1
                    while 'Bimomento '+str(index) in actions or 'Bimomento '+str(index) in self.model.actions:
                        index += 1
                    name = 'Bimomento '+str(index)
                actions[name] = Action(name, 'member_bimoment_'+side, target, (value,), case)
            if actions != self.model.actions:
                self.model.actions.clear()
                self.model.actions.update(actions)
                self.model._touch()
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
