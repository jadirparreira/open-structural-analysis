"""PDF export keeps the sheet drawing, physical page and live editing state."""
import copy
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image, ImageFilter
from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication, QWidget

from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.project_sheet_pdf import _export_workspace, export_sheet_pdf
from osa.ui.weld_symbols import DEFAULTS
from pdf_helpers import wait_for_pdf


@pytest.fixture
def sheet():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    workspace = ProjectSheetWorkspace(window)
    workspace.resize(1400, 950)
    corners = ((0., 0.), (2., 0.), (2., .5), (0., .5))
    view = dict(name="DET A - Superior", segments=tuple(zip(corners, (*corners[1:], corners[0]))),
                segment_owners=("bar:B",)*4, scale_denominator=20., position=(.35, .32),
                identifications=[dict(text="CH 6,3", projected_point=(2.3, .3))],
                dimensions=[dict(start=(0., 0.), end=(2., 0.), offset=(0., -.15),
                                 orthogonal_axis="x", unit="mm", decimal_places=0)],
                weld_marks=[dict(DEFAULTS, size=3., all_around=True, point=(1.8, .25), offset_mm=(22., -18.))])
    workspace.set_sheet_views([view])
    workspace._project_settings['client'] = 'Cliente de referência'
    workspace._sheet_texts = [dict(anchor=(.1, .65), width_mm=70., height_mm=15.,
                                  text_height_mm=3., html='<p>Observações da folha</p>')]
    workspace._sheet_lines = [dict(kind='line', points=((.1, .75), (.3, .8)))]
    workspace._settings['tables'] = [dict(kind='accessories', position=(.5, .55))]
    workspace.accessory_rows_provider = lambda: [dict(name='Arruela Lisa Ø 12,5', quantity=4)]
    yield app, window, workspace
    window.close()
    app.processEvents()


def open_pdf(path):
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    wait_for_pdf(document)
    assert document.pageCount() == 1
    return document


def pdf_text(document):
    # Force QtPdf's page backend to initialize before requesting text. Some
    # Windows Qt builds otherwise return an empty selection immediately after load.
    document.render(0, QSize(1200, 900))
    return document.getAllText(0).text()


def test_vector_pdf_contains_drawing_text_tables_and_preserves_live_state(sheet, tmp_path):
    app, _window, workspace = sheet
    views = copy.deepcopy(workspace._sheet_views)
    workspace._zoom_factor = 3.7
    workspace._pan_offset = QPointF(250, -160)
    workspace._selected_view_index = 0
    workspace._selected_identification_indices = {0}
    workspace._annotation_mode = 'line'
    caches = workspace._view_hit_rects
    path = tmp_path/'folha.pdf'
    export_sheet_pdf(workspace, path)
    assert workspace._sheet_views == views
    assert workspace._selected_view_index == 0
    assert workspace._selected_identification_indices == {0}
    assert workspace._zoom_factor == 3.7 and workspace._pan_offset == QPointF(250, -160)
    assert workspace._annotation_mode == 'line' and workspace._view_hit_rects is caches
    document = open_pdf(path)
    text = pdf_text(document)
    for expected in ('DET A', 'CH 6,3', '2000', 'Cliente de referência', 'Observações', 'Arruela Lisa'):
        assert expected in text
    assert 'Exportar projeto' not in text
    assert 'Novo modelo' not in text
    raw = path.read_bytes()
    assert b'/Font' in raw and b'/Subtype /Image' not in raw
    assert document.pagePointSize(0).width() == pytest.approx(420*72/25.4, abs=1)
    assert document.pagePointSize(0).height() == pytest.approx(297*72/25.4, abs=1)


def test_pdf_raster_matches_the_shared_screen_renderer(sheet, tmp_path):
    app, _window, workspace = sheet
    scale = 96/25.4
    width, height = workspace.paper_size_mm()
    size = QSize(round(width*scale), round(height*scale))
    reference = QImage(size, QImage.Format.Format_RGB32)
    reference.fill(Qt.GlobalColor.white)
    clone = _export_workspace(workspace)
    painter = QPainter(reference)
    painter.setFont(workspace.font())
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clone.paint_sheet(painter, QRectF(0, 0, width*scale, height*scale), scale)
    painter.end()
    path = tmp_path/'same-drawing.pdf'
    export_sheet_pdf(workspace, path)
    document = open_pdf(path)
    actual = document.render(0, size)
    def ink(image):
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
        return (pixels[:, :, :3].min(axis=2) < 180).copy()
    expected_mask, actual_mask = ink(reference), ink(actual)
    def near(mask):
        return np.asarray(Image.fromarray(mask.astype('uint8')*255).filter(ImageFilter.MaxFilter(5))) > 0
    # Font antialiasing differs between Qt and PDFium; every visible stroke/text
    # should still coincide within two pixels in both directions.
    threshold = .92 if sys.platform == 'win32' else .98
    assert near(actual_mask)[expected_mask].mean() > threshold
    assert near(expected_mask)[actual_mask].mean() > threshold
    clone.deleteLater()


@pytest.mark.parametrize('orientation,width,height', [('Retrato', 123., 211.), ('Paisagem', 211., 123.)])
def test_custom_paper_orientation_and_margins(sheet, tmp_path, orientation, width, height):
    _app, _window, workspace = sheet
    workspace._settings.update(paper_size='Personalizado', custom_width_mm=123., custom_height_mm=211.,
                               orientation=orientation, margin_left_mm=12., margin_top_mm=17.,
                               margin_right_mm=8., margin_bottom_mm=9., title_block_visible=False)
    path = tmp_path/'custom.pdf'
    export_sheet_pdf(workspace, path)
    document = open_pdf(path)
    assert document.pagePointSize(0).width() == pytest.approx(width*72/25.4, abs=1)
    assert document.pagePointSize(0).height() == pytest.approx(height*72/25.4, abs=1)
    assert 'Cliente' not in pdf_text(document)


def test_failed_export_leaves_existing_file_intact(sheet, tmp_path, monkeypatch):
    _app, _window, workspace = sheet
    path = tmp_path/'keep.pdf'; path.write_bytes(b'previous contents')
    def fail(*args):
        raise RuntimeError('render failed')
    monkeypatch.setattr(ProjectSheetWorkspace, 'paint_sheet', fail)
    with pytest.raises(RuntimeError, match='render failed'):
        export_sheet_pdf(workspace, path)
    assert path.read_bytes() == b'previous contents'
    with pytest.raises(OSError):
        export_sheet_pdf(workspace, tmp_path/'missing'/'file.pdf')


def test_button_stays_bottom_right_and_waits_for_linework(sheet):
    app, window, workspace = sheet
    window.resize(1600, 1100); window.show(); app.processEvents()
    for width, height in ((1200, 850), (1450, 1000)):
        workspace.resize(width, height); app.processEvents()
        button = workspace.export_button
        assert width-button.geometry().right()-1 == 24
        assert height-button.geometry().bottom()-1 == 24
    workspace.set_linework_updating(True)
    assert not button.isEnabled()
    workspace.set_linework_updating(False)
    assert button.isEnabled()


def test_export_dialog_saves_pdf_and_remembers_selected_folder(sheet, tmp_path, monkeypatch):
    from types import SimpleNamespace
    import osa.ui.main_window as module
    _app, _window, workspace = sheet
    settings = QSettings(str(tmp_path/'settings.ini'), QSettings.Format.IniFormat)
    selected = tmp_path/'projeto'
    errors, messages = [], []
    fake = SimpleNamespace(project_sheet_workspace=workspace, current_path=tmp_path/'model.osa',
                           _program_settings=settings, show_error=errors.append)
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: (str(selected), ''))
    monkeypatch.setattr(module, 'DetailingExportSuccessDialog',
                        lambda _parent, message: SimpleNamespace(exec=lambda: messages.append(message)))
    module.MainWindow.export_project_pdf(fake)
    assert not errors and messages == ['Arquivo PDF exportado com sucesso']
    assert selected.with_suffix('.pdf').exists()
    assert settings.value('detailing/pdfDirectory') == str(tmp_path)
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *args: ('', ''))
    module.MainWindow.export_project_pdf(fake)
    assert len(messages) == 1


def test_pdf_is_independent_of_zoom_pan_selection_and_preview(sheet, tmp_path):
    _app, _window, workspace = sheet
    first = tmp_path/'first.pdf'
    export_sheet_pdf(workspace, first)
    workspace._zoom_factor = .45
    workspace._pan_offset = QPointF(-350, 270)
    workspace._selected_view_index = 0
    workspace._selected_sheet_text = (-1, 0)
    workspace._selected_identification_indices = {0}
    workspace._annotation_mode = 'line'
    workspace._line_start_context = (None, (.3, .3))
    workspace._line_preview_endpoint = (.7, .7)
    second = tmp_path/'second.pdf'
    export_sheet_pdf(workspace, second)
    first_doc, second_doc = open_pdf(first), open_pdf(second)
    assert first_doc.render(0, QSize(1200, 850)) == second_doc.render(0, QSize(1200, 850))
