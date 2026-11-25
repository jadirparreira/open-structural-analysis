"""Angular and world-elevation dimensions: interaction, units and vector PDF."""
import json
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.project_sheet_pdf import export_sheet_pdf
from osa.ui.special_dimensions import angular_geometry, dimension_layout, elevation
from osa.ui.dialogs import ProjectSheetSettingsDialog


@pytest.fixture
def scene():
    app = QApplication.instance() or QApplication([])
    ws = ProjectSheetWorkspace(); ws.resize(1500, 1050)
    view = dict(name='Elevação', segments=(((0., 0.), (2., 0.)), ((0., 0.), (0., 2.)), ((0., 2.), (2., 2.))),
                segment_owners=('bar:B',)*3, scale_denominator=20., position=(.35,.4),
                projection=dict(plane='XZ', coordinate=0.))
    ws.set_sheet_views([view]); ws.show(); app.processEvents(); ws.grab()
    yield ws, view
    ws.close(); app.processEvents()


def click(ws, point):
    QTest.mouseClick(ws, Qt.MouseButton.LeftButton, pos=ws._screen_point(0, point).toPoint())
    QApplication.processEvents()


def test_angular_snap_clicks_preview_degrees_move_delete_and_escape(scene, tmp_path):
    ws, view = scene
    ws.set_dimension_mode(True, 'angular')
    for point in ((0,0), (2,0), (0,2)):
        click(ws, point)
    assert len(ws._dimension_points) == 3
    target = ws._screen_point(0, (.7,.7))
    QTest.mouseMove(ws, target.toPoint())
    ws._special_dimension_input(target, False)
    ws.grab()
    assert ws._dimension_preview['kind'] == 'angular'
    assert dimension_layout(ws, 0, ws._dimension_preview, ws.font())['text'] == '90,0°'
    QTest.keyClick(ws, Qt.Key.Key_Return)
    assert ws._dimension_mode and not view.get('dimensions')
    click(ws, (.7,.7)); QTest.keyClick(ws, Qt.Key.Key_Escape)
    assert not ws._dimension_mode
    mark = view['dimensions'][0]
    assert math.degrees(angular_geometry(mark)[1]) == pytest.approx(90.)
    assert json.loads(json.dumps(mark))['kind'] == 'angular'
    pdf_path = tmp_path/'angle.pdf'; export_sheet_pdf(ws,pdf_path)
    pdf = QPdfDocument(); assert pdf.load(str(pdf_path)) == QPdfDocument.Error.None_
    assert '90,0°' in pdf.getAllText(0).text()
    ws.grab(); layout = dimension_layout(ws,0,mark,ws.font())
    ws.select_view(0); ws.grab()
    center = layout['text_rect'].center()
    QTest.mousePress(ws, Qt.MouseButton.LeftButton, pos=center.toPoint())
    old = mark['offset']
    QTest.mouseMove(ws, (center+QPointF(18, -12)).toPoint())
    QTest.mouseRelease(ws, Qt.MouseButton.LeftButton, pos=(center+QPointF(18,-12)).toPoint())
    assert mark['offset'] != old
    QTest.keyClick(ws, Qt.Key.Key_Delete)
    assert not view['dimensions']


def test_level_in_metres_reference_and_pdf(scene, tmp_path):
    ws, view = scene
    ws.set_dimension_mode(True, 'level')
    click(ws, (0,2)); click(ws, (.7,2.25))
    QTest.keyClick(ws, Qt.Key.Key_Escape); ws.grab()
    mark = view['dimensions'][0]
    assert mark['kind'] == 'level'
    assert dimension_layout(ws,0,mark,ws.font())['text'] == '+2,000 m'
    ws._project_settings['level_dimension_reference_m'] = 2.25
    assert dimension_layout(ws,0,mark,ws.font())['text'] == '-0,250 m'
    path = tmp_path/'levels.pdf'; export_sheet_pdf(ws,path)
    doc = QPdfDocument(); assert doc.load(str(path)) == QPdfDocument.Error.None_
    assert '-0,250 m' in doc.getAllText(0).text()
    doc.render(0,QSize(1500,1050)).save(str(tmp_path/'level.png'))


@pytest.mark.parametrize('plane,point,z', [('XY',(2,3,7),7), ('XZ',(2,0,7),7), ('YZ',(0,3,-2),-2)])
@pytest.mark.parametrize('rotation',[0., 35., 180.])
def test_level_uses_world_height_with_rotated_projections(scene, plane, point, z, rotation):
    ws, view = scene
    view['projection'] = dict(plane=plane, coordinate=7. if plane=='XY' else 0., rotation_degrees=rotation)
    projected = ws._project_world_point(view, point)
    assert elevation(ws,0,projected) == pytest.approx(z)


def test_level_uses_custom_plane_origin_and_rotation(scene):
    ws, view = scene
    view['projection'] = dict(plane='custom', coordinate=((5,10,20),(6,10,20),(5,10,21)), rotation_degrees=30.)
    projected = ws._project_world_point(view,(7,10,23))
    assert elevation(ws,0,projected) == pytest.approx(23.)


def test_angular_reflex_and_degenerate_geometry():
    mark = dict(vertex=(0,0), start=(1,0), end=(0,1), offset=(-1,-1))
    assert math.degrees(angular_geometry(mark)[1]) == pytest.approx(270.)
    assert angular_geometry(dict(mark,end=(2,0))) is None
    assert angular_geometry(dict(mark,start=(0,0))) is None


def test_project_settings_have_independent_parameters_and_roundtrip(scene):
    ws, _view = scene
    dialog = ProjectSheetSettingsDialog('Folha',ws._settings,ws._project_settings,1)
    inputs = dialog._special_dimension_inputs
    inputs['angular_dimension_decimal_places'].setValue(2)
    inputs['level_dimension_reference_m'].setValue(12.345)
    dialog._dimension_color_values['angular_dimension_line_color'] = '#008800'
    dialog._save()
    settings = dialog.result_project_settings
    assert settings['angular_dimension_decimal_places'] == 2
    assert settings['level_dimension_reference_m'] == pytest.approx(12.345)
    reopened = ProjectSheetSettingsDialog('Folha',ws._settings,settings,1)
    assert reopened._special_dimension_inputs['level_dimension_reference_m'].value() == pytest.approx(12.345)
    dialog.close(); reopened.close()


def test_level_anchor_can_be_edited_and_updates_measured_value(scene):
    ws, view = scene
    ws.set_dimension_mode(True, 'level')
    click(ws, (0,2)); click(ws, (.7,2.25)); QTest.keyClick(ws, Qt.Key.Key_Escape)
    ws.select_view(0); ws.grab()
    mark = view['dimensions'][0]
    center = dimension_layout(ws,0,mark,ws.font())['text_rect'].center()
    QTest.mouseClick(ws, Qt.MouseButton.LeftButton, pos=center.toPoint()); ws.grab()
    handle = ws._dimension_endpoint_hit_rects[0,0,'start'].center()
    target = ws._screen_point(0,(0,0)).toPoint()
    QTest.mousePress(ws, Qt.MouseButton.LeftButton, pos=handle.toPoint())
    QTest.mouseMove(ws,target); QTest.mouseRelease(ws,Qt.MouseButton.LeftButton,pos=target)
    assert mark['start'] == pytest.approx((0,0))
    assert dimension_layout(ws,0,mark,ws.font())['text'] == '+0,000 m'
