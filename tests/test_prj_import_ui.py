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
from osa.ui.import_dialogs import PrjImportDialog, ImportReportDialog


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
    dialog = PrjImportDialog("example.prj")
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


def test_report_shows_supported_element_counts_and_empty_categories(qt_app):
    report = ImportReportDialog(
        {
            "counts": {
                "columns": 2,
                "foundation_columns": 1,
                "pending_plates": 1,
                "beams": 101,
                "beam_segments": 101,
            },
        }
    )
    plain = "\n".join(
        browser.toPlainText() for browser in report.report_sections.values()
    )
    assert list(report.report_sections) == [
        "Resumo", "Fundações", "Pilares", "Vigas", "Lajes", "Paredes",
    ]
    assert "101 barras" in report.report_sections["Resumo"].toPlainText()
    assert "1 barras" in report.report_sections["Resumo"].toPlainText()
    assert "0 placas" in report.report_sections["Resumo"].toPlainText()
    for category in ("Fundações", "Pilares", "Vigas", "Lajes", "Paredes"):
        assert report.report_sections[category].toPlainText() == "Nenhum elemento importado"
    assert "Assentamento das sapatas" not in plain
    assert "Geometria de placa pendente" not in plain
    options = PrjImportDialog("example.prj")
    selected_options = options.options()
    assert selected_options.include_lower_columns is True
    assert selected_options.preserve_end_offsets is True
    assert selected_options.import_material_properties is True
    assert not hasattr(options, "lower_columns")
    assert not hasattr(options, "offsets")
    assert not hasattr(options, "material_properties")
    report.close()
    options.close()


def test_report_uses_only_imported_element_categories(qt_app):
    dialog = ImportReportDialog(
        {
            "floor_elevations_m": [{"id": 1, "name": "Inferior", "z": 0}],
            "geometry_mapping": {
                "column_axes": [
                    {"name": "P17", "floor_id": 1,
                     "coordinate_sources": ["beam_faces", "insertion_fallback"]}
                ],
                "unmatched_beam_endpoints": [
                    {"beam_name": "VI-12_T1", "column_name": "P17",
                     "floor_id": 1, "axis": "y"}
                ],
                "section_review": [
                    {"beam_name": "V6_T1", "member_name": "B125", "floor_id": 1,
                     "rectangular_candidate_mm": [300, 800]}
                ],
                "omitted_columns": [
                    {"name": "P25", "floor_id": 1,
                     "reason": "continuidade no pavimento anterior não identificada"}
                ],
            },
        }
    )
    assert list(dialog.report_sections) == [
        "Resumo", "Fundações", "Pilares", "Vigas", "Lajes", "Paredes",
    ]
    for category in ("Fundações", "Pilares", "Vigas", "Lajes", "Paredes"):
        assert dialog.report_sections[category].toPlainText() == "Nenhum elemento importado"
    plain = "\n".join(
        browser.toPlainText() for browser in dialog.report_sections.values()
    )
    assert "P17" not in plain
    assert "VI-12_T1" not in plain
    assert "300 × 800 mm" not in plain
    dialog.close()


def test_foundation_report_lists_original_element_and_created_bar_ids(qt_app):
    dialog = ImportReportDialog({
        "counts": {"foundation_columns": 1},
        "member_sources": {
            "B428": {
                "kind": "column", "foundation_bar": True,
                "original_name": "P23",
            },
        },
    })
    text = dialog.report_sections["Fundações"].toPlainText()
    assert "P23" in text
    assert "B428" in text
    assert "0.520" not in text
    assert "-0.520" not in text
    dialog.close()


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
    options = PrjImportDialog("teste.prj")
    report = ImportReportDialog(
        {
            "source": {"filename": "teste.prj"},
            "counts": {"beam_segments": 3, "columns": 2},
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
        assert "3 barras" in plain
        assert "2 barras" in plain
        assert "0 placas" in plain
        assert "Código interno do PRJ" not in plain
        assert "Compatibilidade experimental" not in plain
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
        assert dark_pixels > 30
        for combo in (options.length_unit, options.force_unit):
            combo.showPopup()
            qt_app.processEvents()
            assert combo._popup is not None
            assert combo._list is not None
            selected_text, selected_background = QColor("#24292f"), QColor("#eaeef2")
            assert _contrast(selected_text, selected_background) >= 4.5
            combo.hidePopup()
    finally:
        options.close()
        report.close()
        qt_app.setPalette(original)
