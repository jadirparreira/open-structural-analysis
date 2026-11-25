import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QDialog
from osa.ui.dialogs import ActionDialog


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


def test_plate_pressure_launch_ignores_old_member_values(qt_app):
    dialog = ActionDialog()
    dialog._fields['FX'].setText('50')
    dialog.plate_button.click()
    assert dialog.reference == 'local'
    assert dialog._fields['PX'].isEnabled()
    assert not dialog._fields['FX'].isEnabled()
    assert dialog._unit_labels['PX'].text() == 'kN/m²'
    dialog._fields['PX'].setText('-2;-4')
    dialog._fields['PY'].setText('-1,5')
    dialog._launch()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.launch_data() == ('plate', 'local', {'PX': (-2., -4.), 'PY': (-1.5,)})


def test_return_to_node_does_not_launch_plate_pressure(qt_app):
    dialog = ActionDialog()
    dialog.plate_button.click()
    dialog._fields['PX'].setText('-5')
    dialog.node_button.click()
    dialog._fields['FZ'].setText('-2')
    dialog._launch()
    assert dialog.launch_data() == ('node', 'global', {'FZ': (-2.,)})
