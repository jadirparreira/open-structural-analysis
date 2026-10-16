"""Abertura/importação e salvamento pela janela real, com diálogos controlados."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("mcp")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog

from osa.transcriptions import ImportOptions
from osa.ui import main_window
from osa.ui.import_dialogs import EberickImportDialog, ImportReportDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_options_and_open_filter_expose_prj(qt_app):
    dialog = EberickImportDialog("example.prj")
    assert dialog.options().length_unit == "cm"
    assert dialog.options().force_unit == "kgf"
    assert "*.prj" in main_window.MainWindow._import_file_filter
    assert "*.prj" not in main_window.MainWindow._open_file_filter
    assert main_window.MainWindow._project_file_filter == "Modelo OSA (*.osa)"
    dialog.close()


def test_cancel_pending_changes_does_not_load_another_project():
    errors = []
    window = SimpleNamespace(
        show_error=errors.append, _confirm_pending_changes=lambda: False
    )
    main_window.MainWindow._load_model_path(window, Path("another.prj"), importing=True)
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
        monkeypatch.setattr(
            main_window.QFileDialog, "getOpenFileName", lambda *args: (str(source), "")
        )
        window.home.import_model_button.click()
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
        window.title_bar.import_model_action.trigger()
        assert errors == []
        assert window.current_path is None
        assert len(window.model.bars) == 16
    finally:
        window._saved_revision = window.model.revision
        window.close()
        qt_app.processEvents()


@pytest.mark.parametrize(
    "method,path,message",
    [
        ("_open_model_path", "foreign.prj", "Importar modelo"),
        ("_import_model_path", "native.osa", "Abrir modelo"),
    ],
)
def test_open_and_import_reject_the_wrong_format(method, path, message):
    errors = []
    window = SimpleNamespace(show_error=errors.append)
    getattr(main_window.MainWindow, method)(window, path)
    assert len(errors) == 1
    assert message in errors[0]


def test_file_choosers_use_separate_format_filters(monkeypatch):
    requests = []
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getOpenFileName",
        lambda *args: requests.append(args) or ("", ""),
    )
    window = SimpleNamespace(
        _open_file_filter=main_window.MainWindow._open_file_filter,
        _import_file_filter=main_window.MainWindow._import_file_filter,
    )
    main_window.MainWindow.open_model(window)
    main_window.MainWindow.import_model(window)
    assert requests[0][1] == "Abrir modelo"
    assert requests[0][3] == "Modelo OSA (*.osa)"
    assert requests[1][1] == "Importar modelo"
    assert "*.prj" in requests[1][3] and "*.osa" not in requests[1][3]


def _luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast(first, second):
    a, b = sorted((_luminance(first), _luminance(second)))
    return (b + 0.05) / (a + 0.05)


@pytest.mark.parametrize("dark", [False, True])
def test_report_and_combo_popups_remain_readable_with_system_palette(qt_app, dark):
    original = qt_app.palette()
    inherited = QPalette(original)
    inherited.setColor(
        QPalette.ColorRole.Base, QColor("#161b22" if dark else "#ffffff")
    )
    inherited.setColor(
        QPalette.ColorRole.Text, QColor("#ffffff" if dark else "#24292f")
    )
    inherited.setColor(
        QPalette.ColorRole.WindowText, QColor("#ffffff" if dark else "#24292f")
    )
    qt_app.setPalette(inherited)
    options = EberickImportDialog("teste.prj")
    report = ImportReportDialog(
        {
            "source": {"filename": "teste.prj"},
            "options": {"length_unit": "cm", "force_unit": "kgf"},
            "counts": {"nodes": 28, "members": 16},
            "warnings": [
                "Cargas, peso próprio, paredes e combinações não foram aplicados ao modelo."
            ],
        }
    )
    try:
        options.show()
        report.show()
        qt_app.processEvents()
        text = report.report_text
        palette = text.palette()
        assert (
            _contrast(
                palette.color(QPalette.ColorRole.Text),
                palette.color(QPalette.ColorRole.Base),
            )
            >= 7
        )
        plain = text.toPlainText()
        assert "O peso próprio é aplicado pelas ferramentas do OSA." in plain
        assert "Cargas, peso próprio" not in plain
        image = text.viewport().grab().toImage()
        dark_pixels = sum(
            max(
                image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue(),
            )
            < 120
            for x in range(8, image.width() - 8, 2)
            for y in range(8, min(image.height() - 8, 220), 2)
        )
        assert dark_pixels > 100
        for combo in (options.length_unit, options.force_unit):
            combo.showPopup()
            qt_app.processEvents()
            popup = combo.view().palette()
            assert (
                _contrast(
                    popup.color(QPalette.ColorRole.Text),
                    popup.color(QPalette.ColorRole.Base),
                )
                >= 7
            )
            assert (
                _contrast(
                    popup.color(QPalette.ColorRole.HighlightedText),
                    popup.color(QPalette.ColorRole.Highlight),
                )
                >= 4.5
            )
            combo.hidePopup()
    finally:
        options.close()
        report.close()
        qt_app.setPalette(original)
