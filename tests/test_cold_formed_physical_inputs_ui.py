"""Physical input UI binds to validated, persistent model fields."""
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QDialog, QWidget
from test_cold_formed_service import cantilever

from osa.ui.cold_formed_bearing_dialog import ColdFormedBearingDialog
from osa.ui.palettes import AnalysisTopPalette


def test_bearing_dialog_requires_review_and_saves_only_valid_regions():
    app = QApplication.instance() or QApplication([])
    model = cantilever(.001)
    dialog = ColdFormedBearingDialog(model, ('B1',))
    dialog._save()
    assert model.bars['B1'].bearing_basis is None
    dialog._add()
    dialog.table.item(0, 4).setText('ELU')
    dialog.reviewed.setChecked(True)
    dialog.table.item(0, 3).setText('nan')
    dialog._save()
    assert model.bars['B1'].bearing_basis is None
    dialog.table.item(0, 3).setText('2,5')
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert model.bars['B1'].bearing_regions[0].force_per_web_kn == 2.5
    assert model.bars['B1'].bearing_basis
    dialog.close()
    del app


class AnalysisWindow(QWidget):
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.scene = SimpleNamespace(set_analysis_diagrams_visible=lambda *_: None,
                                     set_analysis_plate_diagrams_visible=lambda *_: None)

    def _select_analysis_combination(self, *_):
        pass

    def _select_analysis_diagram(self, *_):
        pass

    def open_combinations(self):
        pass

    def process_analysis(self):
        pass

    def refresh_analysis_palette(self):
        pass

    def refresh_scene(self):
        pass


def test_analysis_menu_reads_project_options_and_invalidates_old_results():
    app = QApplication.instance() or QApplication([])
    model = cantilever(.001)
    window = AnalysisWindow(model)
    palette = AnalysisTopPalette(window)
    menu = palette.analysis_options_button.menu()
    menu.aboutToShow.emit()
    order, reduced = menu.actions()[:2]
    assert not order.isChecked() and not reduced.isChecked()
    revision = model.revision
    order.setChecked(True)
    reduced.setChecked(True)
    assert model.second_order_analysis and model.ultimate_stiffness_factor == .8
    assert model.revision == revision+2
    palette.close()
    window.close()
    del app


def test_notional_dialog_generates_cases_only_after_review_and_can_remove_them():
    from test_cold_formed_notionals import frame

    from osa.ui.notional_dialog import NotionalDialog

    app = QApplication.instance() or QApplication([])
    model = frame()
    dialog = NotionalDialog(model)
    dialog._add(('Cobertura', 'B', 'A', 'ELU', 150.))
    dialog._save()
    assert model.notional_plan is None
    dialog.reviewed.setChecked(True)
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert model.notional_plan and len(model.notional_plan.combinations) == 4
    dialog.close()
    reopened = NotionalDialog(model)
    assert reopened.reviewed.isChecked()
    assert reopened.table.rowCount() == 1
    assert reopened.generated.rowCount() == 4
    assert float(reopened.generated.item(0, 3).text()) == .45
    reopened._clear()
    assert model.notional_plan is None
    assert set(model.actions) == {'P'} and set(model.load_combinations) == {'ELU'}
    reopened.close()
    del app


def test_warping_dialog_saves_physical_end_conditions_and_invalidates_analysis():
    from osa.ui.warping_restraints_dialog import WarpingRestraintsDialog

    app = QApplication.instance() or QApplication([])
    model = cantilever(.001)
    dialog = WarpingRestraintsDialog(model)
    assert dialog.table.rowCount() == 1
    assert dialog.table.cellWidget(0, 2).currentData() is None
    a, b = dialog.table.cellWidget(0, 2), dialog.table.cellWidget(0, 4)
    a.setCurrentIndex(a.findData('blocked'))
    b.setCurrentIndex(b.findData('free'))
    revision = model.revision
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert model.bars['B1'].warping_restraints == ('blocked', 'free')
    assert model.revision == revision+1
    reopened = WarpingRestraintsDialog(model)
    assert reopened.table.cellWidget(0, 2).currentData() == 'blocked'
    reopened._save()
    assert model.revision == revision+1
    dialog.close()
    reopened.close()
    del app


def test_analysis_menu_exposes_warping_without_changing_existing_end_conditions():
    app = QApplication.instance() or QApplication([])
    model = cantilever(.001)
    model.update_member_warping_restraints('B1', ('free', 'blocked'))
    window = AnalysisWindow(model)
    palette = AnalysisTopPalette(window)
    menu = palette.analysis_options_button.menu()
    menu.aboutToShow.emit()
    warping = next(action for action in menu.actions() if action.text() == 'Análise dos formados (torção/empenamento)')
    assert not warping.isChecked()
    revision = model.revision
    warping.setChecked(True)
    assert model.warping_analysis and model.revision == revision+1
    assert model.bars['B1'].warping_restraints == ('free', 'blocked')
    menu.aboutToShow.emit()
    assert warping.isChecked()
    assert model.revision == revision+1
    palette.close()
    window.close()
    del app


def test_bimoment_editor_saves_actions_preserves_other_loads_and_invalidates_results():
    from test_vlasov_adapter import model_for

    from osa.domain import Action
    from osa.services.action_service import ActionService
    from osa.ui.bimoment_dialog import BimomentDialog

    app = QApplication.instance() or QApplication([])
    model = model_for()
    actions = ActionService(model)
    actions.add_action(Action('F', 'node_force_Z', 'B', (-.001,), 'Q'))
    model.analysis_results = [object()]
    revision = model.revision
    dialog = BimomentDialog(model)
    dialog._add()
    dialog.table.cellWidget(0, 1).setCurrentIndex(1)
    dialog.table.item(0, 3).setText('-0,002')
    dialog._save()
    assert dialog.result() == QDialog.DialogCode.Accepted
    loads = [a for a in model.actions.values() if a.kind == 'member_bimoment_B']
    assert len(loads) == 1 and loads[0].components == (-.002,) and loads[0].target == 'B1' and loads[0].load_case == 'Q'
    assert model.actions['F'].components == (-.001,)
    assert model.revision == revision+1 and not model.analysis_results
    dialog.close()
    # Edit and remove the same action; a save without changes is a no-op.
    dialog = BimomentDialog(model)
    dialog._save()
    assert model.revision == revision+1
    dialog.close()
    dialog = BimomentDialog(model)
    dialog.table.removeRow(0)
    dialog._save()
    assert list(model.actions) == ['F']
    dialog.close()
    del app


def test_bimoment_editor_rejects_duplicates_nonfinite_and_stale_model_atomically():
    from test_vlasov_adapter import model_for

    from osa.ui.bimoment_dialog import BimomentDialog

    app = QApplication.instance() or QApplication([])
    model = model_for()
    dialog = BimomentDialog(model)
    dialog._add()
    dialog.table.item(0, 3).setText('nan')
    revision = model.revision
    dialog._save()
    assert not model.actions and model.revision == revision
    dialog.table.item(0, 3).setText('1')
    dialog._add()
    dialog._save()
    assert not model.actions and 'duplicados' in dialog.error.text()
    dialog.table.removeRow(1)
    model.update_analysis_options(second_order=True, stiffness_factor=1.)
    dialog._save()
    assert not model.actions and 'modelo mudou' in dialog.error.text()
    dialog.close()
    del app
