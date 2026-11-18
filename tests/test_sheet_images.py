"""Embedded sheet images share text frame handles and survive PDF export."""
import json
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.project_sheet_pdf import export_sheet_pdf
from osa.ui.sheet_images import image_annotation


@pytest.fixture
def scene(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = QWidget(); window.resize(1500, 1050)
    workspace = ProjectSheetWorkspace(window); workspace.resize(window.size())
    original = tmp_path/'logo.png'
    image = QImage(240, 120, QImage.Format.Format_ARGB32)
    image.fill(QColor('#0969da')); image.save(str(original))
    annotation = image_annotation(original)
    window.show(); app.processEvents()
    yield app, window, workspace, annotation, original
    window.close(); app.processEvents()


def paint(workspace):
    workspace.update()
    QApplication.processEvents()
    return workspace.grab().toImage()


def test_insert_move_resize_preserves_proportion_and_delete(scene):
    _app, _window, sheet, image, _original = scene
    completed = []
    sheet.annotation_finished.connect(lambda *args: completed.append(args))
    sheet.set_sheet_image_mode(image)
    point = sheet._stamp_rect.topLeft()+QPointF(25, 170)
    QTest.mouseClick(sheet, Qt.MouseButton.LeftButton, pos=point.toPoint())
    assert completed == [('image', False)]
    assert sheet._annotation_mode is None
    assert len(sheet._sheet_texts) == 1
    item = sheet._sheet_texts[0]
    assert item['kind'] == 'image' and 'view_index' not in item
    paint(sheet)
    frame = sheet._sheet_text_hit_rects[-1, 0]
    start = frame.center()
    anchor = item['anchor']
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=start.toPoint())
    QTest.mouseMove(sheet, (start+QPointF(-45, -20)).toPoint())
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=(start+QPointF(-45, -20)).toPoint())
    assert item['anchor'][0] < anchor[0] and item['anchor'][1] < anchor[1]
    paint(sheet)
    handle = sheet._sheet_text_handle_hit_rects[-1, 0].center()
    old_width = item['width_mm']
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=handle.toPoint())
    QTest.mouseMove(sheet, (handle+QPointF(30, 10)).toPoint())
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=(handle+QPointF(30, 10)).toPoint())
    assert item['width_mm'] > old_width
    assert item['width_mm']/item['height_mm'] == pytest.approx(2.)
    QTest.keyClick(sheet, Qt.Key.Key_Delete)
    assert not sheet._sheet_texts


def test_escape_cancels_insertion_and_double_click_does_not_open_text_editor(scene):
    _app, _window, sheet, image, _original = scene
    sheet.set_sheet_image_mode(image)
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert sheet._annotation_mode is None and sheet._pending_sheet_image is None
    assert not sheet._sheet_texts
    image['anchor'] = (.05, .1)
    sheet.add_sheet_text(image); paint(sheet)
    opened = []
    sheet.text_editor_requested.connect(opened.append)
    QTest.mouseDClick(sheet, Qt.MouseButton.LeftButton, pos=sheet._sheet_text_hit_rects[-1, 0].center().toPoint())
    assert not opened


def test_images_roundtrip_without_source_file_and_appear_in_pdf(scene, tmp_path):
    _app, _window, sheet, image, original = scene
    image['anchor'] = (.1, .1)
    saved = json.loads(json.dumps([image]))
    original.unlink()
    sheet.set_sheet_annotations(saved, [])
    screen = paint(sheet)
    bounds = sheet._sheet_text_hit_rects[-1, 0]
    assert screen.pixelColor(bounds.center().toPoint()).blue() > 150
    path = tmp_path/'with-image.pdf'
    export_sheet_pdf(sheet, path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    size = QSize(1680, 1188)
    rendered = document.render(0, size)
    scale = 4.
    x = (25 + .1*(420-25-10) + image['width_mm']/2)*scale
    y = (10 + .1*(297-10-10) + image['height_mm']/2)*scale
    color = rendered.pixelColor(round(x), round(y))
    assert color.blue() > 150 and color.red() < 40
    assert b'/Subtype /Image' in path.read_bytes()


def test_image_reader_reports_invalid_files_and_preserves_alpha(scene, tmp_path):
    _app, _window, _sheet, _image, _original = scene
    path = tmp_path/'invalid.png'; path.write_text('not an image')
    with pytest.raises(ValueError):
        image_annotation(path)
    image = QImage(100, 100, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent); image.setPixelColor(40, 40, QColor('red'))
    image.save(str(path))
    import base64
    restored = QImage.fromData(base64.b64decode(image_annotation(path)['image_data']))
    assert restored.pixelColor(0, 0).alpha() == 0
    assert restored.pixelColor(40, 40) == QColor('red')


@pytest.mark.parametrize('position', ['Inferior', 'Superior'])
def test_title_block_has_three_row_logo_spaces_and_matches_bottom_border(scene, position):
    _app, _window, sheet, _image, _original = scene
    sheet._settings['title_block_position'] = position
    paint(sheet)
    stamp, inner, scale = sheet._stamp_rect, sheet._drawing_area, sheet._sheet_pixels_per_mm
    assert stamp.height()/scale == pytest.approx(80.)
    if position == 'Inferior':
        assert stamp.bottom() == pytest.approx(inner.bottom())
    else:
        assert stamp.top() == pytest.approx(inner.top())
    segments = sheet._sheet_reference_segments()
    logo_top = stamp.top()+50*scale
    assert any(a.y() == pytest.approx(logo_top) and b.y() == pytest.approx(logo_top)
               and a.x() == pytest.approx(stamp.left()) for a, b in segments)
    # The responsible/CREA separator stops above the office logo space.
    midpoint = stamp.left()+stamp.width()*.78/2
    assert not any(a.x() == pytest.approx(midpoint) and b.y() == pytest.approx(stamp.bottom())
                   for a, b in segments)


def test_image_command_selects_file_then_starts_placement(scene, monkeypatch):
    import osa.ui.main_window as module
    _app, _window, sheet, _image, original = scene
    canceled, history = [], []
    fake = SimpleNamespace(_detailing_project_mode=True, project_sheet_workspace=sheet,
                           project_sheets_palette=SimpleNamespace(sheet_selector=SimpleNamespace(currentText=lambda:'Folha')),
                           command_session=SimpleNamespace(cancel=lambda:canceled.append(True)), history=history,
                           show_error=lambda message:pytest.fail(message))
    monkeypatch.setattr(module.QFileDialog, 'getOpenFileName', lambda *args:(str(original),''))
    # A real MainWindow installs its event filter; this isolated controller
    # check suppresses it rather than constructing the unrelated 3D renderer.
    monkeypatch.setattr(module, 'QApplication', SimpleNamespace(instance=lambda:None))
    module.MainWindow.start_project_sheet_image(fake)
    assert canceled and fake._command_mode == 'project_sheet_image'
    assert sheet._annotation_mode == 'image' and history
