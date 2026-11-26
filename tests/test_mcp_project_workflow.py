"""MCP project output uses real projected solids and the shared PDF renderer."""
import copy
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtPdf import QPdfDocument
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from osa.mcp import McpApplication
from osa.model import StructuralModel
from osa.services import ModelService
from pdf_helpers import wait_for_pdf


@pytest.fixture
def api():
    app = QApplication.instance() or QApplication([])
    model = StructuralModel()
    model.add_node('N1', 0, 0, 0)
    model.add_node('N2', 2, 0, 0)
    model.add_bar('B1', 'N1', 'N2')
    result = McpApplication(model, ModelService(model))
    result.set_member_rectangular_section(['B1'], 200, 300, 'Concreto C25')
    yield result
    app.processEvents()


def test_sheets_geometry_dimensions_save_reload_and_pdf(api, tmp_path):
    revision = api.model.revision
    api.create_project_sheet('01 - Teste', project={'work': 'Demonstração MCP'})
    view = api.create_sheet_view('01 - Teste', 'Planta', 'XY', 0, position=[.5, .3])
    assert view['segments'] > 0
    api.add_view_dimension('01 - Teste', 0, [0, 0], [2, 0], [0, -.3], 'mm')
    api.add_sheet_text('01 - Teste', 'Nota <literal>', [.1, .7])
    assert api.model.revision == revision
    assert api.get_project_sheets()['sheet_views']['01 - Teste'][0]['dimensions']
    path = tmp_path/'project.osa'
    api.save_project(str(path))
    loaded = StructuralModel()
    loaded.load(path)
    assert loaded.detailing_data == json.loads(json.dumps(api.model.detailing_data))
    pdf = tmp_path/'sheet.pdf'
    before = copy.deepcopy(api.model.detailing_data)
    api.export_project_sheet_pdf('01 - Teste', str(pdf))
    assert api.model.detailing_data == before
    doc = QPdfDocument()
    assert doc.load(str(pdf)) == QPdfDocument.Error.None_
    wait_for_pdf(doc)
    assert doc.pageCount() == 1
    doc.render(0, QSize(1200, 900))
    assert 'Nota <literal>' in doc.getAllText(0).text()
    assert '2000' in doc.getAllText(0).text()
    with pytest.raises(ValueError, match='já existe'):
        api.save_project(str(path))
    api.save_project(str(path), overwrite=True)


def test_invalid_sheet_operations_are_atomic(api):
    api.create_project_sheet('Teste')
    before = copy.deepcopy(api.model.detailing_data)
    for operation in (
        lambda: api.create_sheet_view('Teste', 'V', 'XY', 0, scale_denominator=float('nan')),
        lambda: api.create_sheet_view('Teste', 'V', 'XY', 0, position=[1.5, .5]),
        lambda: api.add_sheet_text('Teste', 'T', [.5, .5], width_mm=-1),
        lambda: api.add_view_dimension('Teste', 0, [0, 0], [1, 0], [0, 1]),
    ):
        with pytest.raises(ValueError):
            operation()
        assert api.model.detailing_data == before


def test_reverse_rejects_canonical_orientation_before_mutating(api):
    api._can_reverse_member = lambda: False
    before = api.model.revision
    with pytest.raises(ValueError, match='orientação canônica'):
        api.reverse_member('B1')
    assert api.model.bars['B1'].start_node == 'N1'
    assert api.model.revision == before


def test_dxf_export_import_and_reference_lifecycle(api, tmp_path):
    path = tmp_path/'model.dxf'
    assert api.export_model_dxf(str(path))['members'] == 1
    result = api.import_drawing_reference(str(path))
    reference_id = result['reference_id']
    api.update_drawing_reference(reference_id, origin=[1, 2, 0], plane='XZ', visible=False)
    assert api.model.references[reference_id].plane == 'XZ'
    api.delete_drawing_reference(reference_id)
    assert not api.model.references


def test_component_detail_contains_real_geometry_and_automatic_dimensions(api):
    api.set_node_component('N1', 'base_plate', {'largura_mm': 350, 'comprimento_mm': 350})
    api.create_project_sheet('Bases')
    result = api.create_component_detail('Bases', 'N1')
    assert result['view_indices'] == [0, 1]
    views = api.get_project_sheets()['sheet_views']['Bases']
    assert all(v['segments'] and v['dimensions'] and v['identifications'] for v in views)
    api.update_sheet_view('Bases', 0, name='Superior', axes_visible=False)
    assert api.get_project_sheets()['sheet_views']['Bases'][0]['name'] == 'Superior'
    group = views[0]['component_detail_group']
    label_gap = group['label_position'][1] - group['group_position'][1]
    api.update_sheet_view('Bases', 0, position=[.5, .35])
    moved = api.get_project_sheets()['sheet_views']['Bases']
    assert all(v['component_detail_group']['group_position'] == (.5, .35) for v in moved)
    assert moved[0]['component_detail_group']['label_position'] == pytest.approx((.5, .35 + label_gap))


def test_live_sheet_creation_selects_project_mode_and_survives_ui_snapshot(api, monkeypatch):
    from osa.ui.main_window import MainWindow
    window = MainWindow()
    try:
        window.show_editor()
        window.palette.show_group('Detalhamento')
        window._mcp_dispatcher.resume()
        window._mcp_application.create_project_sheet('MCP na interface')
        assert window._detailing_project_mode
        assert window.detailing_mode_palette._buttons[1].isChecked()
        assert window.view_stack.currentWidget() is window.project_sheet_workspace
        assert 'MCP na interface' in window._mcp_application.get_project_sheets()['sheet_names']
    finally:
        monkeypatch.setattr(window, '_confirm_pending_changes', lambda: True)
        window.scene.plotter.close()
        window.close()


def test_mcp_model_edits_and_session_changes_leave_the_home_screen(api, monkeypatch):
    from osa.ui.main_window import MainWindow
    window = MainWindow()
    try:
        window._mcp_dispatcher.resume()
        assert window.view_stack.currentWidget() is window.home
        window._mcp_application.create_node(1, 2, 3)
        assert window.view_stack.currentWidget() is window.scene
        window.show_home()
        window._mcp_application.set_session('Ações')
        assert window.view_stack.currentWidget() is window.scene
        assert window.palette.active_group == 'Ações'
        window.show_home()
        window._mcp_application.set_session('Detalhamento')
        window._mcp_application.create_project_sheet('Folha via MCP')
        assert window.view_stack.currentWidget() is window.project_sheet_workspace
        assert window.detailing_mode_palette._buttons[1].isChecked()
    finally:
        monkeypatch.setattr(window, '_confirm_pending_changes', lambda: True)
        window.scene.plotter.close()
        window.close()


def test_mcp_leaves_project_sheet_for_each_model_session(api, monkeypatch):
    from osa.ui.main_window import MainWindow
    window = MainWindow()
    try:
        window._mcp_dispatcher.resume()
        client = window._mcp_application
        client.create_node(0, 0, 0)
        client.set_session('Detalhamento')
        client.create_project_sheet('Navegação MCP')
        for session, palette in [('Geometria', 'Geometria'), ('Ações', 'Ações'),
                                 ('Análise', 'Análise'), ('Verificação', 'Memorial')]:
            window.detailing_mode_palette.set_project_mode(True)
            window.set_detailing_project_mode(True)
            assert window.view_stack.currentWidget() is window.project_sheet_workspace
            client.set_session(session)
            assert client.get_session_state()['active_session'] == session
            assert window.palette.active_group == palette
            assert window.view_stack.currentWidget() is window.scene
            assert not window._detailing_project_mode
            client.set_session('Detalhamento')
    finally:
        monkeypatch.setattr(window, '_confirm_pending_changes', lambda: True)
        window.scene.plotter.close()
        window.close()
