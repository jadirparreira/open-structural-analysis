"""Abertura/importação e salvamento pela janela real, com diálogos controlados."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("mcp")

from PySide6.QtWidgets import QApplication, QDialog

from osa.transcriptions import ImportOptions
from osa.ui import main_window
from osa.ui.import_dialogs import EberickImportDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_options_and_open_filter_expose_prj(qt_app):
    dialog = EberickImportDialog("example.prj")
    assert dialog.options().length_unit == "cm"
    assert dialog.options().force_unit == "kgf"
    assert "*.prj" in main_window.MainWindow._open_file_filter
    assert main_window.MainWindow._project_file_filter == "Modelo OSA (*.osa)"
    dialog.close()


def test_cancel_pending_changes_does_not_load_another_project():
    errors = []
    window = SimpleNamespace(
        show_error=errors.append, _confirm_pending_changes=lambda: False
    )
    main_window.MainWindow._open_model_path(window, "another.prj")
    assert errors == []


@pytest.mark.skipif(
    not os.environ.get("OSA_EBERICK_PRJ"),
    reason="Defina OSA_EBERICK_PRJ para a abertura real pela interface.",
)
def test_real_window_import_save_and_reopen(qt_app, monkeypatch, tmp_path):
    class AcceptedImport:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def options(self):
            return ImportOptions()

    class AcceptedReport:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window, "EberickImportDialog", AcceptedImport)
    monkeypatch.setattr(main_window, "ImportReportDialog", AcceptedReport)
    window = main_window.MainWindow()
    errors = []
    recents = []
    monkeypatch.setattr(window, "show_error", errors.append)
    monkeypatch.setattr(window.home.store, "add", recents.append)
    try:
        source = Path(os.environ["OSA_EBERICK_PRJ"])
        window._open_model_path(source)
        assert errors == []
        assert len(window.model.nodes) == 28
        assert len(window.model.bars) == 16
        assert window.current_path is None
        assert window._has_unsaved_changes()
        assert window._import_save_path.name == "teste_conv.osa"
        assert recents == []
        assert window.view_stack.currentWidget() is window.scene
        target = tmp_path / "converted.osa"
        window._save_model_to(target)
        assert errors == []
        assert target.exists()
        assert window.current_path == target
        assert not window._has_unsaved_changes()
        assert recents == [target]
        window._open_model_path(target)
        assert errors == []
        assert len(window.model.bars) == 16
        assert window.model.import_metadata["requires_review"] is True
        assert window.current_path == target
    finally:
        window._saved_revision = window.model.revision
        window.close()
        qt_app.processEvents()
