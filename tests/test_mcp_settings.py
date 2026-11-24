"""Contrato visual e de ativação do servidor MCP."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from osa.ui.dialogs import ProgramSettingsDialog
from osa.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_mcp_is_disabled_until_user_activates_it(qt_app):
    window = MainWindow()
    dialog = ProgramSettingsDialog(window)

    assert window.mcp_enabled is False
    assert window._mcp_server.is_running is False
    assert window.mcp_status()["state"] == "disabled"
    assert dialog._mcp_checkbox.isChecked() is False
    assert dialog._antialiasing_slider.value() == 2
    assert window.scene.antialiasing_samples() == 4

    dialog._antialiasing_slider.setValue(3)
    assert window.scene.antialiasing_samples() == 8
    assert dialog._antialiasing_value.text() == "8x"

    dialog.close()
    window.close()


def test_mcp_controls_the_live_analysis_switch_and_interpolation(qt_app, monkeypatch):
    from osa.domain import AnalysisResult
    window = MainWindow()
    try:
        # Do not persist test choices in the user's program settings.
        monkeypatch.setattr(window, 'set_plate_result_display_mode', window.scene.set_plate_result_display_mode)
        window._mcp_dispatcher.resume()
        window.model.analysis_results = [AnalysisResult(window.model.revision, 'Combo')]
        window.refresh_analysis_palette()
        window._mcp_application.set_analysis_view('Combo', 'Fletor Y (My)', result_kind='plate',
                                                   deformation_scale=30, plate_result_display_mode='nos_sem_media')
        palette = window.analysis_top_palette
        assert palette.result_kind == 'plate'
        assert palette.diagram_selector.currentData() == 'Fletor Y (My)'
        assert window.scene.analysis_view_state()['result_kind'] == 'plate'
        assert window.scene.analysis_view_state()['plate_result_display_mode'] == 'nos_sem_media'
        assert window.scene.analysis_view_state()['deformation_scale'] == 30
        window._mcp_application.set_analysis_view(diagram='Fletor Y (My)', result_kind='bar')
        assert palette.result_kind == 'bar'
        assert palette.diagram_selector.currentData() == 'Fletor Y'
        assert window.scene.analysis_view_state()['selected_combination'] == 'Combo'
    finally:
        window._mcp_dispatcher.suspend()
        window.scene.plotter.close()
        window.hide()
        window.deleteLater()
        qt_app.processEvents()
