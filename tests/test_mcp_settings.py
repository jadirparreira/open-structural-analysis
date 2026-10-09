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

    dialog.close()
    window.close()
