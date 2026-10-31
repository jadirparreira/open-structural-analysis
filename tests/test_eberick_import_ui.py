"""Abertura/importação e salvamento pela janela real, com diálogos controlados."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


pytest.importorskip("PySide6")
pytest.importorskip("pyvistaqt")
pytest.importorskip("mcp")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog

from osa.transcriptions import ImportOptions
from osa.ui import main_window
from osa.ui.import_dialogs import EberickImportDialog, ImportReportDialog


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_for_loading(app, window):
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    poll.timeout.connect(
        lambda: loop.quit()
        if window._project_loading_path is None and window._project_load_thread is None
        else None
    )
    poll.start()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(20000)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert window._project_loading_path is None
    assert window._project_load_thread is None


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


@pytest.mark.parametrize(
    "source_env,node_count,bar_count,save_name",
    [
        ("OSA_EBERICK_PRJ", 28, 16, "teste_conv.osa"),
        (
            "OSA_EBERICK_FOUNDATIONS_PRJ",
            225,
            145,
            "Arara Azul - Ampliação.osa",
        ),
    ],
)
def test_real_window_import_save_and_reopen(
    qt_app, monkeypatch, tmp_path, source_env, node_count, bar_count, save_name
):
    if not os.environ.get(source_env):
        pytest.skip(f"Defina {source_env} para a abertura real pela interface.")

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
        source = Path(os.environ[source_env])
        monkeypatch.setattr(
            main_window.QFileDialog, "getOpenFileName", lambda *args: (str(source), "")
        )
        window.home.import_model_button.click()
        _wait_for_loading(qt_app, window)
        assert errors == []
        assert len(window.model.nodes) == node_count
        assert len(window.model.bars) == bar_count
        assert window.current_path is None
        assert window._has_unsaved_changes()
        assert window._import_save_path.name == save_name
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
        _wait_for_loading(qt_app, window)
        assert errors == []
        assert len(window.model.bars) == bar_count
        assert window.model.import_metadata["requires_review"] is True
        assert window.current_path == target
        window.title_bar.import_model_action.trigger()
        _wait_for_loading(qt_app, window)
        assert errors == []
        assert window.current_path is None
        assert len(window.model.bars) == bar_count
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


def test_analysis_stops_before_starting_for_pending_plates():
    errors = []
    window = SimpleNamespace(
        _analysis_thread=None,
        model=SimpleNamespace(
            import_metadata={
                "plate_transfer": {"records": [{"status": "pending_plate_support"}]}
            }
        ),
        show_error=errors.append,
    )
    main_window.MainWindow.process_analysis(window)
    assert len(errors) == 1 and "placas" in errors[0]


def test_report_shows_footing_position_and_plate_pending_state(qt_app):
    report = ImportReportDialog(
        {
            "counts": {
                "support_candidates": 1,
                "pending_plates": 1,
                "beams": 101,
                "beam_groups": 30,
                "beam_segments": 101,
            },
            "support_candidates": [
                {"column_name": "P1", "settlement_depth_m": 1.5, "elevation_m": -1.5}
            ],
            "plate_transfer": {
                "records": [
                    {
                        "name": "L1",
                        "floor_name": "Térreo",
                        "status": "pending_plate_support",
                    }
                ]
            },
        }
    )
    plain = "\n".join(
        browser.toPlainText() for browser in report.report_sections.values()
    )
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    assert lines[lines.index("Vigas") + 1] == "30"
    assert lines[lines.index("Trechos de viga") + 1] == "101"
    assert "Assentamento das sapatas" in plain
    assert "-1.500" in plain
    assert "L1 — Térreo" in plain
    assert "Geometria de placa pendente" in plain
    options = EberickImportDialog("example.prj")
    assert "assentamento das sapatas" in options.lower_columns.text()
    assert "altura do primeiro pavimento" not in options.lower_columns.text()
    report.close()
    options.close()


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
            "internal_version_code": 2281,
            "compatibility": {"mode": "structural_probe"},
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
        plain = "\n".join(
            browser.toPlainText() for browser in report.report_sections.values()
        )
        assert "Código interno do PRJ: 2281" in plain
        assert "Compatibilidade experimental" in plain
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
