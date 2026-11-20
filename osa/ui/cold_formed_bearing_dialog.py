"""Physical contact inputs for Annex D; design force is declared per web."""
from PySide6.QtWidgets import (
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
    QVBoxLayout,
)

from osa.domain.local_force_inputs import BearingRegion
from osa.domain.stability_inputs import stability_signature


class ColdFormedBearingDialog(QDialog):
    def __init__(self, model, member_names, parent=None):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle('Forças concentradas — NBR 14762, Anexo D')
        self.resize(1050, 440)
        layout = QVBoxLayout(self)
        self.member = QComboBox(self)
        self.member.addItems(member_names)
        layout.addWidget(self.member)
        note = QLabel('Cadastre a envoltória ELU de cada região que comprime a alma, incluindo apoios. '
                      'F é a força por alma, em kN; verifique a partilha entre almas. '
                      'c é o contato longitudinal, em mm; e é a distância livre à extremidade física da barra. '
                      'Mesa conectada exige contenção efetiva pela ligação. Uma ou duas mesas seguem as notas das Tabelas D.2–D.4. '
                      'O cadastro não dimensiona ligações ou dispositivos de transferência direta.', self)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 8, self)
        self.table.setHorizontalHeaderLabels(('Região', 'x (m)', 'c (mm)', 'F/alma (kN)', 'Combinação ELU', 'e (mm)', 'Mesa conectada', 'Mesas carregadas'))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton('Adicionar região', self)
        add.clicked.connect(lambda: self._add())
        remove = QPushButton('Remover região', self)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.reviewed = QCheckBox('Revisei todas as regiões e combinações ELU.', self)
        layout.addWidget(self.reviewed)
        absence = QLabel("Tabela vazia declara: sem compressão localizada de alma ou transmissão direta por dispositivo verificado separadamente.", self)
        absence.setWordWrap(True)
        layout.addWidget(absence)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        accept = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        accept.button(QDialogButtonBox.StandardButton.Save).setText('Salvar')
        accept.button(QDialogButtonBox.StandardButton.Cancel).setText('Cancelar')
        accept.accepted.connect(self._save)
        accept.rejected.connect(self.reject)
        layout.addWidget(accept)
        self.member.currentTextChanged.connect(self._load)
        self._load()

    def _load(self):
        member = self.model.bars[self.member.currentText()]
        self.table.setRowCount(0)
        for region in member.bearing_regions:
            self._add(region)
        self.reviewed.setChecked(member.bearing_basis == stability_signature(self.model))
        self.error.setText('Salvar altera apenas a barra selecionada. A posição x se refere à barra analítica; a distância e se refere à extremidade física do perfil.')

    def _add(self, region=None):
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = (region.name, region.position_m, region.contact_mm, region.force_per_web_kn,
                  region.combination, region.edge_distance_mm) if region else ('Região '+str(row+1), 0., 20., 1., '', 0.)
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))
        connected = QComboBox(self.table)
        connected.addItems(('Não', 'Sim'))
        connected.setCurrentIndex(int(region.connected) if region else 0)
        self.table.setCellWidget(row, 6, connected)
        flanges = QComboBox(self.table)
        flanges.addItems(('1', '2'))
        flanges.setCurrentIndex(region.loaded_flanges-1 if region else 0)
        self.table.setCellWidget(row, 7, flanges)

    def _save(self):
        if not self.reviewed.isChecked():
            self.error.setText('Confirme a revisão de todas as regiões e combinações antes de salvar.')
            return
        try:
            regions = []
            for row in range(self.table.rowCount()):
                values = [self.table.item(row, column).text().strip() if self.table.item(row, column) else '' for column in range(6)]
                regions.append(BearingRegion(values[0], float(values[1].replace(',', '.')),
                    float(values[2].replace(',', '.')), float(values[3].replace(',', '.')), values[4],
                    float(values[5].replace(',', '.')), self.table.cellWidget(row, 6).currentIndex() == 1,
                    self.table.cellWidget(row, 7).currentIndex()+1))
            self.model.update_bar_bearing_regions(self.member.currentText(), regions)
        except (ValueError, TypeError) as exc:
            self.error.setText(str(exc))
            return
        self.accept()
