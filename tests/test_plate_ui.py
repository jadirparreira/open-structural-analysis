import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLabel

from osa.model import StructuralModel
from osa.persistence.project_repository import ProjectRepository
from osa.ui.main_window import MainWindow


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window._plate_closure_mode = 'perguntar'
    window.show()
    window.show_editor()
    for name, x, y in [('N1', 0, 0), ('N2', 4, 0), ('N3', 4, 3), ('N4', 0, 3)]:
        window.model.add_node(name, x, y, 0)
    window.model.add_bar('B1', 'N1', 'N2')
    window.model.add_bar('B2', 'N2', 'N3')
    window.model.add_bar('B3', 'N3', 'N4')
    window.model.add_rigid_bar('N4', 'N1')
    window.scene.render_model(window.model)
    yield window
    window.scene.plotter.close()
    window.hide()
    window.deleteLater()
    app.processEvents()


def click(window, kind, name):
    window.scene.element_clicked.emit(kind, name, window.scene.element_center(kind, name))


def test_closed_contour_create_inspect_save_delete(window, tmp_path):
    window.handle_command('PLATE')
    for name in ('B1', 'B2', 'B3'):
        click(window, 'bar', name)
    assert window.scene._selected_elements == (('bar', 'B1'), ('bar', 'B2'), ('bar', 'B3'))
    click(window, 'rigid_bar', 'N4-N1')
    assert list(window.model.plates) == ['P1']
    assert 'P1' in window.scene._plate_actors
    click(window, 'plate', 'P1')
    assert window.properties.title.text() == 'Placa'
    assert window.properties.identity_value.text() == 'P1'
    path = tmp_path / 'plate.osa'
    ProjectRepository().save(window.model, path)
    restored = StructuralModel()
    ProjectRepository().load(restored, path)
    assert restored.plates == window.model.plates
    window.delete_selected()
    assert not window.model.plates


def test_automatic_and_manual_closure(window, monkeypatch):
    import osa.ui.main_window as module
    class Auto:
        choice = 'automatic'
        def __init__(self, *args): pass
        def move(self, *args): pass
        def rect(self): return window.rect()
        def exec(self): return 1
    monkeypatch.setattr(module, 'PlateClosureDialog', Auto)
    window.start_plate_placement()
    click(window, 'bar', 'B1')
    click(window, 'bar', 'B2')
    click(window, 'bar', 'B3')
    window._confirm_command_selection()
    assert list(window.model.plates) == ['P1']
    Auto.choice = 'manual'
    window.start_plate_placement()
    click(window, 'bar', 'B1')
    click(window, 'bar', 'B2')
    click(window, 'bar', 'B3')
    window._confirm_command_selection()
    assert window._command_mode == 'plate_manual'
    window._handle_member_placement_point((0, 0, 0))
    window._handle_member_placement_point((0, 3, 0))
    assert list(window.model.plates) == ['P1', 'P2']
    window.start_plate_placement()
    click(window, 'bar', 'B1')
    window.cancel_member_placement()
    assert window._command_mode is None
    assert len(window.model.plates) == 2


def test_plate_picking_and_bar_highlight_with_solid_toggle(window):
    import numpy as np
    window.start_plate_placement()
    for name in ('B1', 'B2', 'B3'):
        click(window, 'bar', name)
    click(window, 'rigid_bar', 'N4-N1')
    scene = window.scene
    scene.plotter.view_xy()
    scene.reset_camera()
    scene.plotter.render()
    scene.plotter.render_window.SetSize(scene.plotter.width(), scene.plotter.height())
    screen, visible = scene._world_to_screen(np.array([2.0, 1.5, 0.0]))
    assert visible
    scene._pointer_position = tuple(screen)
    interactor = scene.plotter.iren.interactor
    height = scene.plotter.render_window.GetSize()[1]
    interactor.SetEventInformation(int(screen[0]), int(height - screen[1]), 0, 0, 'a', 0, None)
    assert scene._pick() == ('plate', 'P1')
    for solid in (False, True):
        scene.set_solid_members_visible(solid)
        window.start_plate_placement()
        click(window, 'bar', 'B1')
        click(window, 'rigid_bar', 'N4-N1')
        assert scene._selected_elements == (('bar', 'B1'), ('rigid_bar', 'N4-N1'))
        window.cancel_member_placement()


@pytest.mark.parametrize('solid', [False, True])
def test_pick_real_bar_for_plate_in_both_representations(window, solid):
    import numpy as np
    model, scene = window.model, window.scene
    model.update_bar_section('B1', 'Barra Retangular')
    model.update_member_profile('B1', 'R1', {'b': 200, 'h': 200})
    scene.render_model(model)
    scene.set_solid_members_visible(solid)
    scene.plotter.view_xy()
    scene.reset_camera()
    scene.plotter.render()
    scene.plotter.render_window.SetSize(scene.plotter.width(), scene.plotter.height())
    window.start_plate_placement()
    world = np.array([2., 0., 0.1 if solid else 0.])
    screen, visible = scene._world_to_screen(world)
    assert visible
    scene._pointer_position = tuple(screen)
    height = scene.plotter.render_window.GetSize()[1]
    scene.plotter.iren.interactor.SetEventInformation(
        int(screen[0]), int(height - screen[1]), 0, 0, 'a', 0, None,
    )
    picked = scene._pick()
    assert picked == ('bar', 'B1')
    scene.element_clicked.emit(*picked, scene.element_center(*picked))
    assert scene._selected_elements == (('bar', 'B1'),)
    assert 'selected:bar' in scene._highlight_actors


def test_manual_closing_restores_snap_and_rejects_invalid_segment(window, monkeypatch):
    import osa.ui.main_window as module
    class Manual:
        choice = 'manual'
        def __init__(self, *args): pass
        def move(self, *args): pass
        def rect(self): return window.rect()
        def exec(self): return 1
    monkeypatch.setattr(module, 'PlateClosureDialog', Manual)
    window.scene._snap_types['endpoint'] = False
    window.start_plate_placement()
    click(window, 'bar', 'B1')
    window._confirm_command_selection()
    assert window.scene._snap_types['endpoint']
    window._plate_manual_point((0, 0, 0))
    window._plate_manual_point((4, 0, 0))
    assert not window.model.plates
    assert window._plate_manual_segments == []
    window.cancel_member_placement()
    assert not window.scene._snap_types['endpoint']
    assert not window.scene._placement_active()


def test_plate_panel_properties_and_solid_thickness_roundtrip(window, tmp_path):
    from PySide6.QtWidgets import QDoubleSpinBox, QLineEdit
    window.start_plate_placement()
    for name in ('B1', 'B2', 'B3'):
        click(window, 'bar', name)
    click(window, 'rigid_bar', 'N4-N1')
    plate = window.model.plates['P1']
    assert plate.color == window.model.bars['B1'].color == '#6e7781'
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == pytest.approx(.7)
    assert window.scene._plate_antialiasing._active
    assert plate.supports == (('bar', 'B1'), ('bar', 'B2'), ('bar', 'B3'), ('rigid_bar', 'N4-N1'))
    click(window, 'plate', 'P1')
    panel = window.properties
    assert panel.member_color_button.isVisible()
    fields = {field.accessibleName(): field for field in panel.findChildren(QLineEdit)}
    assert fields['Barras'].text() == 'B1, B2, B3, N4-N1'
    assert fields['Material'].text() == 'Concreto Estrutural'
    thickness = next(field for field in panel.findChildren(QDoubleSpinBox)
                     if field.accessibleName() == 'Espessura da placa (mm)')
    assert thickness.value() == 100
    thickness.setValue(240)
    thickness.editingFinished.emit()
    panel._toggle_color_palette()
    assert panel._color_palette.isVisible()
    panel._color_selected('#ff0000')
    assert window.model.plates['P1'].thickness_mm == 240
    assert window.model.plates['P1'].color == '#ff0000'
    window.scene.set_solid_members_visible(True)
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == pytest.approx(1.0)
    assert not window.scene._plate_antialiasing._active
    surface = window.scene._plate_actors['P1'].GetMapper().GetInput()
    assert surface.GetBounds()[5] - surface.GetBounds()[4] == pytest.approx(.24)
    window.scene.plotter.view_xy()
    window.scene.reset_camera()
    window.scene.plotter.render_window.SetSize(window.scene.plotter.width(), window.scene.plotter.height())
    screen, visible = window.scene._world_to_screen(np.array([2., 1.5, .12]))
    assert visible
    window.scene._pointer_position = tuple(screen)
    height = window.scene.plotter.render_window.GetSize()[1]
    window.scene.plotter.iren.interactor.SetEventInformation(
        int(screen[0]), int(height - screen[1]), 0, 0, 'a', 0, None,
    )
    assert window.scene._pick() == ('plate', 'P1')
    outline = window.scene._plate_edge_actors['P1'].GetMapper().GetInput()
    assert outline.GetNumberOfLines() == 6  # two perimeter loops, four vertical edges
    assert outline.GetNumberOfVerts() == 0
    window.scene.set_solid_members_visible(False)
    assert window.scene._plate_actors['P1'].GetProperty().GetOpacity() == pytest.approx(.7)
    assert window.scene._plate_antialiasing._active
    window.scene.set_antialiasing_samples(0)
    assert window.scene._plate_antialiasing._active
    window.scene.set_antialiasing_samples(4)
    assert window.scene._plate_antialiasing._active
    assert window.scene._plate_edge_actors['P1'].GetProperty().GetOpacity() == pytest.approx(1.0)
    outline = window.scene._plate_edge_actors['P1'].GetMapper().GetInput()
    assert outline.GetNumberOfLines() == 1
    assert outline.GetNumberOfPoints() == 4
    path = tmp_path / 'with-properties.osa'
    ProjectRepository().save(window.model, path)
    restored = StructuralModel()
    ProjectRepository().load(restored, path)
    assert restored.plates['P1'] == window.model.plates['P1']
    restored.remove_bar('B1')
    assert ('bar', 'B1') not in restored.plates['P1'].supports


def test_plate_action_and_analysis_panels_show_only_the_requested_fields(window):
    from PySide6.QtWidgets import QLabel, QLineEdit

    window.model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))
    window.scene.render_model(window.model)
    window.selected_action_name = 'Caso'
    window.action_service.add_plate_surface_pressure('P1', -3.0, 'Caso')

    panel = window.properties
    panel.show_for('plate', 'P1', 'Ações')
    assert panel.name.text() == 'Identidade'
    assert panel.identity_value.text() == 'P1'
    assert not panel.member_color_button.isVisible()
    assert panel.findChild(QLabel, 'propertySection').text() == 'Identidade'
    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert 'Ação distribuída' in labels
    assert 'Barras' not in labels and 'Material' not in labels and 'Espessura' not in labels
    pressure_field = next(
        field for field in panel.findChildren(QLineEdit)
        if field.accessibleName() == 'Ação distribuída na laje (kN/m²)'
    )
    assert pressure_field.text() == '-3'
    assert all(field.accessibleName() != 'Espessura da placa (mm)'
               for field in panel.findChildren(QLineEdit))
    assert panel._format_plate_pressure(1.23456) == '1.235'
    assert panel._format_plate_pressure(1.2) == '1.2'
    assert panel._format_plate_pressure(1.0) == '1'

    window.model.add_bar('B4', 'N4', 'N2')
    window.action_service.add_member_selfweight('B4', -1.0, 'Peso próprio')
    window.selected_action_name = 'Peso próprio'
    panel.show_for('plate', 'P1', 'Ações')
    selfweight_field = next(
        field for field in panel.findChildren(QLineEdit)
        if field.accessibleName() == 'Peso próprio distribuído da placa (kN/m²)'
    )
    expected_pressure = -window.model.materials['Concreto Estrutural'][3] * 0.1
    assert float(selfweight_field.text()) == pytest.approx(round(expected_pressure, 3))
    assert selfweight_field.isReadOnly()

    panel.show_for('plate', 'P1', 'Análise')
    QApplication.processEvents()
    labels = [label.text() for label in panel.findChildren(QLabel) if label.isVisible()]
    assert panel.identity_value.text() == 'P1'
    assert not panel.member_color_button.isVisible()
    assert labels == ['Placa', 'Identidade']


def test_old_plate_recovers_matching_supports(window):
    from osa.persistence.project_serializer import ProjectSerializer
    window.start_plate_placement()
    for name in ('B1', 'B2', 'B3'):
        click(window, 'bar', name)
    click(window, 'rigid_bar', 'N4-N1')
    serializer = ProjectSerializer()
    data = serializer.dump(window.model)
    for field in ('supports', 'color', 'thickness_mm'):
        del data['plates'][0][field]
    restored = StructuralModel()
    serializer.load_into(restored, data)
    assert set(restored.plates['P1'].supports) == {('bar', 'B1'), ('bar', 'B2'), ('bar', 'B3'), ('rigid_bar', 'N4-N1')}


def test_dashed_intersections_follow_solid_mode_and_geometry(window):
    model, scene = window.model, window.scene
    model.add_plate(((-2, -2, 0), (6, -2, 0), (6, 5, 0), (-2, 5, 0)))
    model.update_bar_section('B1', 'Barra Retangular')
    model.update_member_profile('B1', 'R1', {'b': 300, 'h': 300})
    scene.render_model(model)
    assert scene._plate_intersection_actor is None
    scene.set_solid_members_visible(True)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    assert scene._plate_intersection_actor is not None
    assert scene._plate_intersection_actor.GetMapper().GetInput().GetNumberOfLines() > 0
    assert scene._plate_intersection_actor.GetProperty().GetOpacity() == 1
    scene.set_solid_members_visible(False)
    assert not scene._plate_intersection_actor.GetVisibility()
    scene.set_solid_members_visible(True)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    model.update_node('N1', 0, 0, 5)
    model.update_node('N2', 4, 0, 5)
    scene.refresh_model_changes(model)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    assert scene._plate_intersection_actor is None


def test_bar_intersections_without_plate_are_solid_only(window):
    model, scene = window.model, window.scene
    for name in ('B1', 'B2'):
        model.update_bar_section(name, 'Barra Retangular')
        model.update_member_profile(name, name, {'b': 300, 'h': 300})
    scene.render_model(model)
    assert not model.plates
    scene.set_solid_members_visible(True)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    assert scene._plate_intersection_actor is not None
    assert scene._plate_intersection_actor.GetMapper().GetInput().GetNumberOfLines() > 0
    scene.set_solid_members_visible(False)
    assert not scene._plate_intersection_actor.GetVisibility()


def test_bar_hover_and_selection_color_only_associated_intersections(window):
    import pyvista as pv
    model, scene = window.model, window.scene
    model.add_plate(((-2, -2, 0), (6, -2, 0), (6, 5, 0), (-2, 5, 0)))
    for name in ('B1', 'B2'):
        model.update_bar_section(name, 'Barra Retangular')
        model.update_member_profile(name, name, {'b': 300, 'h': 300})
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    mesh = pv.wrap(scene._plate_intersection_actor.GetMapper().GetInput())
    assert not scene._plate_intersection_actor.GetMapper().GetScalarVisibility()
    a, b = mesh.cell_data['member_a'], mesh.cell_data['member_b']
    names = scene._plate_intersection_names
    i, j = names.index('B1'), names.index('B2')
    b1 = (a == i) | (b == i)
    b2 = (a == j) | (b == j)
    assert np.any(b1 & b2)  # both members own their shared intersection
    assert np.any(b1 & ~b2) and np.any(b2 & ~b1)  # plate intersections remain separate
    plate_ids = np.asarray(mesh.cell_data['plate'])
    plate = plate_ids == 0
    original_face = scene._plate_actors['P1'].GetProperty().GetColor()
    scene._hovered = ('bar', 'B1')
    scene._sync_highlights()
    hover = scene._plate_intersection_overlays['hover']
    assert hover.GetVisibility()
    assert not hover.GetMapper().GetScalarVisibility()
    assert hover.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(b1))
    assert hover.GetProperty().GetColor() == pytest.approx((36/255, 41/255, 47/255))
    scene.set_selection_highlight((('bar', 'B2'),))
    selected = scene._plate_intersection_overlays['selected']
    assert selected.GetVisibility()
    assert selected.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(b2))
    assert selected.GetProperty().GetColor() == pytest.approx((9/255, 105/255, 218/255))
    assert hover.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(b1 & ~b2))
    scene._hovered = ('plate', 'P1')
    scene.set_selection_highlight(())
    assert hover.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(plate))
    assert scene._plate_actors['P1'].GetProperty().GetColor() == pytest.approx(original_face)
    assert scene._plate_edge_actors['P1'].GetProperty().GetColor() == pytest.approx((36/255, 41/255, 47/255))
    scene.set_selection_highlight((('plate', 'P1'),))
    assert selected.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(plate))
    assert scene._plate_actors['P1'].GetProperty().GetColor() == pytest.approx(original_face)
    assert scene._plate_edge_actors['P1'].GetProperty().GetColor() == pytest.approx((9/255, 105/255, 218/255))
    scene._hovered = None
    scene.set_selection_highlight(())
    assert not selected.GetVisibility()
    assert not hover.GetVisibility()
    assert scene._plate_intersection_actor.GetVisibility()
    assert scene._plate_intersection_actor.GetMapper().GetInput().GetNumberOfLines() == mesh.n_lines
    assert scene._plate_intersection_actor.GetProperty().GetColor() == pytest.approx((69/255, 75/255, 82/255))
    assert scene._plate_actors['P1'].GetProperty().GetColor() == pytest.approx(original_face)


def test_deformation_hides_original_plate_mesh_during_hover(window):
    from osa.domain import AnalysisResult

    model, scene = window.model, window.scene
    model.add_plate(((-2, -2, 0), (6, -2, 0), (6, 5, 0), (-2, 5, 0)))
    for name in ('B1', 'B2'):
        model.update_bar_section(name, 'Barra Retangular')
        model.update_member_profile(name, name, {'b': 300, 'h': 300})
    scene.render_model(model)
    scene.set_solid_members_visible(False)
    assert scene._plate_fe_mesh_actors['P1'].GetVisibility()

    nodes = {
        'FE::N1': {'coordinates': (-2, -2, 0), 'DZ': 0.0},
        'FE::N2': {'coordinates': (6, -2, 0), 'DZ': -0.01},
        'FE::N3': {'coordinates': (6, 5, 0), 'DZ': -0.01},
        'FE::N4': {'coordinates': (-2, 5, 0), 'DZ': 0.0},
    }
    model.analysis_results = [AnalysisResult(
        model.revision, 'Result', plate_results={
            'P1': {'nodes': nodes, 'elements': {'Q1': {'nodes': tuple(nodes)}}},
        },
    )]
    scene._hovered = ('plate', 'P1')
    scene._sync_highlights()
    scene.set_analysis_result('Result', 'Deformação XYZ')
    scene.set_analysis_visible(True)

    assert not scene._plate_actors['P1'].GetVisibility()
    assert not scene._plate_fe_mesh_actors['P1'].GetVisibility()
    scene._sync_highlights()
    assert not scene._plate_fe_mesh_actors['P1'].GetVisibility()

    scene.set_analysis_visible(False)
    assert scene._plate_fe_mesh_actors['P1'].GetVisibility()


def test_node_markers_follow_deformation_scale_and_return_to_original_position(window):
    from osa.domain import AnalysisResult

    model, scene = window.model, window.scene
    node_index = scene._node_batch.names.index('N2')
    original = np.asarray(scene._node_glyph_points.points[node_index]).copy()
    model.analysis_results = [AnalysisResult(
        model.revision, 'Result', node_results={
            'N2': {'DX': 0.01, 'DY': -0.02, 'DZ': 0.03},
        },
    )]
    scene._hovered = ('node', 'N2')
    scene._sync_highlights()

    scene.set_analysis_deformation_scale(10)
    scene.set_analysis_result('Result', 'Deformação XYZ')
    scene.set_analysis_visible(True)
    assert scene._node_glyph_points.points[node_index] == pytest.approx(
        original + np.asarray((0.01, -0.02, 0.03)) * 10,
    )

    scene.set_analysis_deformation_scale(20)
    assert scene._node_glyph_points.points[node_index] == pytest.approx(
        original + np.asarray((0.01, -0.02, 0.03)) * 20,
    )

    scene.set_analysis_visible(False)
    assert scene._node_glyph_points.points[node_index] == pytest.approx(original)


def test_analysis_palette_has_independent_bar_and_plate_diagram_toggles(window):
    palette = window.analysis_top_palette
    assert palette.result_diagrams_button.toolTip() == 'Diagrama nas barras'
    assert palette.plate_diagrams_button.toolTip() == 'Diagrama nas placas'
    assert palette.result_diagrams_button.isChecked()
    assert palette.plate_diagrams_button.isChecked()

    palette.plate_diagrams_button.setChecked(False)
    assert not window.scene.analysis_view_state()['plate_diagrams_visible']
    assert palette.result_diagrams_button.isChecked()

    palette.diagram_selector.setCurrentText('Deformação XYZ')
    assert palette.result_diagrams_button.isEnabled()
    assert palette.plate_diagrams_button.isEnabled()

    palette.result_diagrams_button.setChecked(False)
    assert not window.scene.analysis_view_state()['result_diagrams_visible']
    palette.result_diagrams_button.setChecked(True)
    assert window.scene.analysis_view_state()['result_diagrams_visible']


def test_plate_diagram_toggle_shows_and_hides_colored_plate_results(window):
    from osa.domain import AnalysisResult

    model, scene = window.model, window.scene
    model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))
    scene.render_model(model)
    nodes = {
        'FE::1': {'coordinates': (0, 0, 0)},
        'FE::2': {'coordinates': (4, 0, 0)},
        'FE::3': {'coordinates': (4, 3, 0)},
        'FE::4': {'coordinates': (0, 3, 0)},
    }
    model.analysis_results = [AnalysisResult(model.revision, 'Result', plate_results={
        'P1': {'nodes': nodes, 'elements': {
            'Q1': {'nodes': tuple(nodes), 'moment': [1.0, -2.0, 0.5]},
        }},
    })]

    scene.set_analysis_result('Result', 'Fletor Y')
    scene.set_analysis_visible(True)
    assert len(scene._plate_result_actors) == 2
    scale = scene._result_color_scale_widget
    assert not scale.isHidden()
    assert scale.size().width() == 120
    assert scale.size().height() == 365
    assert scale._unit == 'kN·m/m'
    assert scale._format_value(-2.0) == '-2,000'
    assert not scale.findChildren(QLabel)
    assert not scene._plate_actors['P1'].GetVisibility()
    assert not scene._result_actors

    scene.set_analysis_plate_diagrams_visible(False)
    assert not scene._plate_result_actors
    assert scale.isHidden()
    assert scene._plate_actors['P1'].GetVisibility()


def test_plate_selection_highlights_only_its_own_intersections(window):
    import pyvista as pv
    model, scene = window.model, window.scene
    model.add_plate(((0, -1, 0), (1.5, -1, 0), (1.5, 1, 0), (0, 1, 0)))
    model.add_plate(((2.5, -1, 0), (4, -1, 0), (4, 1, 0), (2.5, 1, 0)))
    model.update_bar_section('B1', 'Barra Retangular')
    model.update_member_profile('B1', 'R1', {'b': 300, 'h': 300})
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    scene._plate_intersection_timer.stop()
    scene._refresh_plate_intersections()
    mesh = pv.wrap(scene._plate_intersection_actor.GetMapper().GetInput())
    plate_ids = np.asarray(mesh.cell_data['plate'])
    assert set(plate_ids) == {0, 1}
    scene.set_selection_highlight((('plate', 'P1'),))
    overlay = scene._plate_intersection_overlays['selected']
    assert overlay.GetMapper().GetInput().GetNumberOfLines() == int(np.count_nonzero(plate_ids == 0))
    assert scene._plate_edge_actors['P1'].GetProperty().GetColor() == pytest.approx((9/255, 105/255, 218/255))
    assert scene._plate_edge_actors['P2'].GetProperty().GetColor() != pytest.approx((9/255, 105/255, 218/255))
