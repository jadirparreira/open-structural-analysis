"""Automatic component identifiers and all-around welds on base plate details."""
import copy
import json
import os
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from osa.domain.entities import NodeComponentAssignment
from osa.model import StructuralModel
from osa.services.base_plate_details import (
    add_base_plate_annotations, arrange_base_plate_views, component_identifier,
    ensure_base_plate_annotations, minimum_connected_thickness, update_component_identifier,
)
from osa.services.component_accessories import component_accessory_rows
from osa.ui.dialogs import ComponentDetailsDialog
from osa.ui.main_window import MainWindow
from osa.ui.project_sheet import ProjectSheetWorkspace
from osa.ui.weld_symbols import WeldTool


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def model_with_base(identity='Chumbador Químico Ancora AQ12'):
    model = StructuralModel()
    model.add_node('N', 0, 0, 0)
    model.add_node('T', 0, 0, 2)
    model.add_bar('B', 'N', 'T')
    model.bars['B'] = replace(model.bars['B'], section='Tubular Quadrado',
                              section_geometry=(('b',100.), ('t',3.)))
    model.update_node_component('N', NodeComponentAssignment('base_plate', (
        ('espessura_mm', 6.3), ('identificacao_fixador', identity),
    )))
    return model


def generated_views(model):
    data = ComponentDetailsDialog._build_group_views(model, .05,
        {'nodes':['N'], 'parameters':dict(model.nodes['N'].component.parameters)})
    views = []
    for direction, title in [('top', 'Superior'), ('west', 'Oeste')]:
        part = data[direction]
        views.append(dict(name='DET A - '+title, segments=part['segments'],
            segment_owners=part['segment_owners'], dimensions=part['dimensions'],
            scale_denominator=10., component_annotation_geometry=part['component_annotation_geometry'],
            projection={'plane':'custom','coordinate':part['coordinate']},
            component_detail_group={'id':'A','component_id':'base_plate','members':['N'],
                                    'direction':title,'title':'DET A - Base inferior'}))
    return data, views


def test_fastener_labels_share_takeoff_names_and_quantity():
    for identity in ('', 'Chumbador Químico Ancora AQ12'):
        model = model_with_base(identity)
        name, quantity = component_identifier(model, 'component_fastener', 'N')
        rows = component_accessory_rows(model)
        assert {'name':name, 'quantity':quantity} in rows
        item = dict(kind='component_fastener', element='N')
        update_component_identifier(model, item)
        assert ' '.join(item['text_lines']).endswith('(4X)')
        assert '(4X)' not in item['text_lines']
        assert name == ' '.join(' '.join(item['text_lines']).removesuffix(' (4X)').split())
        assert not any('Ø' in line and len(line) > 32 for line in item['text_lines'])


def test_weld_uses_smallest_web_flange_or_wall_of_all_connected_bars():
    model = model_with_base()
    model.add_node('U', 1, 0, 2)
    model.add_bar('C', 'N', 'U')
    model.bars['C'] = replace(model.bars['C'], section='W Laminado',
                              section_geometry=(('d',200),('bf',100),('tw',2.65),('tf',6.3)))
    model.add_node('X', 4, 0, 0); model.add_node('Y', 4, 0, 2)
    model.add_bar('Unrelated', 'X', 'Y')
    model.bars['Unrelated'] = replace(model.bars['Unrelated'], section_geometry=(('t',1.),))
    assert minimum_connected_thickness(model, 'N') == 2.65
    model.bars['C'] = replace(model.bars['C'], section_geometry=(('tw',4.75),('tf',6.3)))
    assert minimum_connected_thickness(model, 'N') == 3.
    model.bars.clear()
    assert minimum_connected_thickness(model, 'N') == 0


def test_generated_top_view_has_live_identifiers_and_all_around_weld_at_connection(app):
    model = model_with_base()
    data, views = generated_views(model)
    assert ensure_base_plate_annotations(model, views)
    top, side = views
    assert len(top['identifications']) == 2
    assert len(side['identifications']) == 2
    assert top['identifications'][0]['kind'] == 'component_fastener'
    assert top['identifications'][1]['text'] == 'CH 6,3'
    weld = top['weld_marks'][0]
    assert weld['all_around'] and weld['kind'] == 'fillet' and weld['size'] == 3
    # The arrow belongs to the 100 mm profile footprint, not the 300 mm plate.
    assert abs(weld['point'][0]) == pytest.approx(.05, abs=1e-5)
    assert abs(weld['point'][1]) < .051
    assert not ensure_base_plate_annotations(model, views)
    assert len(top['identifications']) == 2 and len(top['weld_marks']) == 1
    position = top['identifications'][0]['projected_point']
    original = (position[0] + .03, position[1] - .02)
    top['identifications'][0]['projected_point'] = original
    params = dict(model.nodes['N'].component.parameters)
    params.update(identificacao_fixador='F-02', espessura_mm=8, fixadores_lado_a=3)
    model.update_node_component('N',NodeComponentAssignment('base_plate',tuple(params.items())))
    model.bars['B'] = replace(model.bars['B'],section_geometry=(('b',100.),('t',4.)))
    assert ensure_base_plate_annotations(model, views)
    assert weld['size'] == 4
    window = SimpleNamespace(model=model)
    window._update_project_identification_text = lambda item: MainWindow._update_project_identification_text(window,item)
    assert MainWindow._refresh_project_view_identifications(window, top)
    assert top['identifications'][0]['text'] == 'F-02 (6X)'
    assert top['identifications'][1]['text'] == 'CH 8'
    assert top['identifications'][0]['projected_point'] == original
    # An intentional manual weld size is retained on later refreshes.
    weld['size'] = 5
    ensure_base_plate_annotations(model, views)
    assert weld['size'] == 5
    assert json.loads(json.dumps(top))['weld_marks'][0]['all_around'] is True


def test_side_only_detail_still_receives_identifiers_and_weld(app):
    model = model_with_base('F-01')
    _data, views = generated_views(model)
    assert ensure_base_plate_annotations(model, views[1:])
    assert len(views[1]['identifications']) == 2
    assert views[1]['weld_marks'][0]['size'] == 3


def test_packed_detail_annotations_do_not_overlap_neighbor_view_or_dimension_geometry(app):
    model = model_with_base()
    _data, views = generated_views(model)
    ensure_base_plate_annotations(model, views)
    arrange_base_plate_views(views)
    window = QWidget(); window.model = model
    sheet = ProjectSheetWorkspace(window)
    sheet.resize(1500,1050)
    window.project_sheet_workspace = sheet
    sheet.weld_tool = WeldTool(window, sheet)
    sheet.set_sheet_views(views)
    image = QImage(sheet.size(),QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image); sheet.render(painter,QPoint());painter.end()
    assert len(sheet._identification_hit_rects) == 4
    assert not sheet._view_hit_rects[0].intersects(sheet._view_hit_rects[1])
    ids = list(sheet._identification_hit_rects.values())
    assert not ids[0].intersects(ids[1])
    for label in ids:
        assert not label.intersects(sheet._view_geometry_bounds[0])
        for key, bounds in sheet._view_dimension_bounds.items():
            if key[0] == 0:
                assert not label.intersects(bounds)
    assert (0,0) in sheet.weld_tool.hits
    window.close()


def test_dialog_accept_adds_annotations_and_preserves_existing_choices(app):
    model = model_with_base('F-01')
    data, _views = generated_views(model)
    definitions = ComponentDetailsDialog._VIEW_DEFINITIONS
    fake = SimpleNamespace(_active_group_key='N', _views_ready=True,
        _groups={'N':{'label':'DET A - Base inferior','nodes':['N']}},
        _group_views_cache={'N':data}, _window=SimpleNamespace(model=model),
        _VIEW_DEFINITIONS=definitions, _existing_views_by_direction={}, _editing_group_id=None,
        _cards={key:(SimpleNamespace(isChecked=lambda key=key:key in {'superior','oeste'}),None,direction)
                for key,_title,direction in definitions}, accept=lambda:None)
    ComponentDetailsDialog._accept_selected_views(fake)
    assert len(fake.result_views)==2
    assert fake.result_views[0]['weld_marks'][0]['all_around']
    assert fake.result_views[0]['identifications'][0]['text']=='F-01 (4X)'
    assert all('paper_offset_mm' in view['component_detail_group'] for view in fake.result_views)
    top = fake.result_views[0]
    top['identifications'][0]['projected_point']=(.9,.8)
    fake._editing_group_id='A'
    fake._existing_views_by_direction={'superior':top,'oeste':fake.result_views[1]}
    ComponentDetailsDialog._accept_selected_views(fake)
    assert fake.result_views[0] is top
    assert top['identifications'][0]['projected_point']==(.9,.8)
    assert len(top['identifications'])==2 and len(top['weld_marks'])==1


def test_component_identifier_inspector_resolves_names_from_model():
    model=model_with_base('F-15')
    window=SimpleNamespace(model=model)
    properties=MainWindow._project_sheet_identification_properties(window,
        dict(kind='component_fastener',element='N',show_identity=True))
    assert properties['identity']=='F-15'
    assert properties['show_identity'] and not properties['disabled_identity']
    properties=MainWindow._project_sheet_identification_properties(window,
        dict(kind='component_plate',element='N',show_identity=True))
    assert properties['identity']=='CH 6,3'


def test_manual_component_identification_uses_same_model_names():
    model=model_with_base('AQ12')
    view={'component_detail_group':{'members':['N']},'identifications':[]}
    window=SimpleNamespace(model=model, project_sheets_palette=SimpleNamespace(
        sheet_selector=SimpleNamespace(currentText=lambda:'S'),_sheet_views={'S':[view]}),
        project_sheet_workspace=SimpleNamespace(update=lambda:None),_store_detailing_state=lambda:None)
    window._update_project_identification_text=lambda item:MainWindow._update_project_identification_text(window,item)
    MainWindow._add_project_view_identification(window,0,'componente:chapa_base:0',(.2,0))
    MainWindow._add_project_view_identification(window,0,'componente:chapa_base:1',(.2,.1))
    assert [item['text'] for item in view['identifications']]==['CH 6,3','AQ12 (4X)']
    MainWindow._add_project_view_identification(window,0,'componente:chapa_base:4',(.2,.1))
    assert len(view['identifications'])==2


def test_six_views_pack_without_covering_each_other_or_title_block(app):
    model=model_with_base('F-01')
    data, sample=generated_views(model)
    views=[]
    for _key,title,direction in ComponentDetailsDialog._VIEW_DEFINITIONS:
        view=copy.deepcopy(sample[0]);part=data[direction]
        view.update(name='DET A - '+title,segments=part['segments'],segment_owners=part['segment_owners'],
                    dimensions=part['dimensions'],component_annotation_geometry=part['component_annotation_geometry'])
        view['component_detail_group']['direction']=title
        views.append(view)
    ensure_base_plate_annotations(model,views)
    arrange_base_plate_views(views)
    window=QWidget();window.model=model
    sheet=ProjectSheetWorkspace(window);sheet.resize(1500,1050);sheet.set_sheet_views(views)
    image=QImage(sheet.size(),QImage.Format.Format_ARGB32_Premultiplied)
    painter=QPainter(image);sheet.render(painter,QPoint());painter.end()
    bounds=list(sheet._view_hit_rects.values())
    for i,first in enumerate(bounds):
        assert not first.intersects(sheet._stamp_rect)
        for second in bounds[i+1:]:
            assert not first.intersects(second)
    window.close()


def test_all_directions_have_annotations_and_left_embedment_dimension(app):
    model = model_with_base()
    data, sample = generated_views(model)
    views = []
    for _key, title, direction in ComponentDetailsDialog._VIEW_DEFINITIONS:
        view = copy.deepcopy(sample[0]); part = data[direction]
        view.update(segments=part['segments'], segment_owners=part['segment_owners'],
                    dimensions=part['dimensions'], component_annotation_geometry=part['component_annotation_geometry'])
        view['component_detail_group']['direction'] = title
        views.append(view)
    ensure_base_plate_annotations(model, views)
    for view in views:
        assert len(view['identifications']) == 2
        assert len(view['weld_marks']) == 1
        if view['component_detail_group']['direction'] not in {'Superior', 'Inferior'}:
            dim = view['dimensions'][0]
            assert dim['start'][0] + dim['offset'][0] < view['component_annotation_geometry']['plate_bounds'][0]
    # An existing version-one group gains the other views without resetting edits.
    views[0]['base_plate_auto_annotations_version'] = 1
    views[0]['identifications'][0]['projected_point'] = (.9, .8)
    assert ensure_base_plate_annotations(model, views)
    assert views[0]['identifications'][0]['projected_point'] == (.9, .8)
    assert not ensure_base_plate_annotations(model, views)
    elevation = views[-1]
    elevation['dimensions'][0]['offset'] = (.3, 0.)
    assert not ensure_base_plate_annotations(model, views)
    assert elevation['dimensions'][0]['offset'] == (.3, 0.)


@pytest.mark.parametrize('rotation', [0., 35.])
def test_identifier_resize_wraps_and_persists_without_changing_identity(app, rotation):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QTransform
    from PySide6.QtTest import QTest
    model = model_with_base()
    _data, views = generated_views(model)
    ensure_base_plate_annotations(model, views)
    arrange_base_plate_views(views)
    window = QWidget(); window.model = model
    sheet = ProjectSheetWorkspace(window); sheet.resize(1500, 1050)
    sheet.set_sheet_views(views); sheet.select_view(0)
    sheet._selected_identification_indices = {0}
    item = views[0]['identifications'][0]
    item['text_rotation_degrees'] = rotation
    window.show(); app.processEvents(); sheet.grab()
    original_text = item['text']
    handle, width, height = sheet._identification_resize_handles[0, 0]
    start = handle.center()
    movement = QTransform().rotate(rotation).map(QPointF(-width*.5*sheet._sheet_pixels_per_mm, 0))
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=start.toPoint())
    assert sheet._drag_identification_resize is not None
    QTest.mouseMove(sheet, (start+movement).toPoint())
    QTest.mouseRelease(sheet, Qt.MouseButton.LeftButton, pos=(start+movement).toPoint())
    sheet.grab()
    assert item['width_mm'] == pytest.approx(width/2, abs=1.)
    assert item['text'] == original_text
    new_handle, new_width, new_height = sheet._identification_resize_handles[0, 0]
    assert new_height > height
    sheet._zoom_factor *= 1.5
    sheet.grab()
    new_handle, zoom_width, zoom_height = sheet._identification_resize_handles[0, 0]
    assert zoom_width == pytest.approx(new_width)
    assert zoom_height == pytest.approx(new_height)
    saved = dict(item)
    QTest.mousePress(sheet, Qt.MouseButton.LeftButton, pos=new_handle.center().toPoint())
    QTest.mouseMove(sheet, (new_handle.center()+QPointF(35, 20)).toPoint())
    QTest.keyClick(sheet, Qt.Key.Key_Escape)
    assert item == saved
    update_component_identifier(model, item)
    assert item['width_mm'] == saved['width_mm']
    assert item['projected_point'] == saved['projected_point']
    window.close()
