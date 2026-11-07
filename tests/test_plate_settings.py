import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QListWidget

from osa.ui.dialogs import ProgramSettingsDialog
import osa.ui.main_window as main_window


@pytest.fixture
def isolated_window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = str(tmp_path / 'settings.ini')
    monkeypatch.setattr(main_window, 'QSettings', lambda *args: QSettings(path, QSettings.Format.IniFormat))
    window = main_window.MainWindow()
    window.show()
    window.show_editor()
    for name, x, y in [('N1', 0, 0), ('N2', 4, 0), ('N3', 4, 3), ('N4', 0, 3)]:
        window.model.add_node(name, x, y, 0)
    for name, a, b in [('B1', 'N1', 'N2'), ('B2', 'N2', 'N3'), ('B3', 'N3', 'N4')]:
        window.model.add_bar(name, a, b)
    window.scene.render_model(window.model)
    yield window
    window.scene.plotter.close()
    window.hide()
    window.deleteLater()
    app.processEvents()


def test_plate_closure_setting_persists_without_transparency_control(isolated_window, monkeypatch):
    window = isolated_window
    dialog = ProgramSettingsDialog(window)
    categories = dialog.findChild(QListWidget)
    assert [categories.item(i).text() for i in range(categories.count())] == ['Snaps', 'Barras', 'Placas', 'Vídeo', 'MCP']
    assert not hasattr(dialog, '_plate_transparency_slider')
    dialog._plate_closure_switch._buttons['automatico'].click()
    assert window.plate_closure_mode == 'automatico'
    dialog.show()
    dialog.accept()
    monkeypatch.setattr(main_window, 'PlateClosureDialog', lambda *_: pytest.fail('Não deve abrir o diálogo'))
    window.start_plate_placement()
    for name in ('B1', 'B2', 'B3'):
        window._plate_add_selection('bar', name)
    window._finish_plate_selection()
    assert 'P1' in window.model.plates
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == pytest.approx(.7)
    window.scene.set_solid_members_visible(True)
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == 1
    assert window.scene._plate_edge_actors['P1'].GetProperty().GetOpacity() == 1
    window.scene.set_solid_members_visible(False)
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == pytest.approx(.7)
    reopened = main_window.MainWindow()
    try:
        assert reopened.plate_closure_mode == 'automatico'
    finally:
        reopened.scene.plotter.close()
        reopened.hide()
        reopened.deleteLater()
