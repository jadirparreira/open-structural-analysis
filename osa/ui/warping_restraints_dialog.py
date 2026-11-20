"""Physical warping boundary conditions, distinct from design critical inputs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from osa.verification.cold_formed_member import FAMILIES


class WarpingRestraintsDialog(QDialog):
    def __init__(self, model, member_names=None, parent=None):
        super().__init__(parent)
        self.model = model
        self.names = tuple(name for name in (member_names if member_names is not None else model.bars)
                           if name in model.bars and model.bars[name].section in FAMILIES)
        self.setWindowTitle('Vínculos de empenamento dos perfis formados')
        self.resize(780, 420)
        layout = QVBoxLayout(self)
        note = QLabel('Declare os vínculos físicos de cada extremidade. Livre: bimomento nulo sem ação externa. '
            'Impedido: derivada da rotação torsional nula. Contínuo: transmite empenamento para outra barra colinear '
            'com seção e função setorial compatíveis, também declarada contínua nesse nó. '
            'A análise confere essa compatibilidade. Apoios de translação/rotação permanecem definidos nos nós. '
            'Ative a análise com empenamento no menu de análise. A cantoneira L usa o modelo sem modo setorial independente.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(self.names), 5, self)
        self.table.setHorizontalHeaderLabels(('Barra', 'Nó A', 'Empenamento A', 'Nó B', 'Empenamento B'))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, name in enumerate(self.names):
            member = model.bars[name]
            for column, value in ((0, name), (1, member.start_node), (3, member.end_node)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            for side, column in enumerate((2, 4)):
                combo = QComboBox(self.table)
                for label, value in (('Não declarado', None), ('Livre', 'free'), ('Impedido', 'blocked'), ('Contínuo', 'continuous')):
                    combo.addItem(label, value)
                combo.setCurrentIndex(max(0, combo.findData(member.warping_restraints[side])))
                combo.setAccessibleName('Empenamento '+('A' if side == 0 else 'B')+' da barra '+name)
                combo.setEnabled(member.section != 'L Formado')
                self.table.setCellWidget(row, column, combo)
        layout.addWidget(self.table)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Salvar')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        records = [(name, tuple(self.table.cellWidget(row, column).currentData() for column in (2, 4)))
                   for row, name in enumerate(self.names)]
        # Validate every record before mutating the model.
        try:
            for name, values in records:
                if name not in self.model.bars:
                    raise ValueError('A barra '+name+' foi removida; reabra o cadastro.')
                self.model._member_warping_restraints(values)
            for name, values in records:
                if self.model.bars[name].section != 'L Formado':
                    self.model.update_member_warping_restraints(name, values)
        except (KeyError, TypeError, ValueError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
