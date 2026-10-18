"""Graphical members inherit the transient editor's complete properties."""

import os
from dataclasses import fields

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QComboBox

from osa.domain.entities import Member
from osa.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def application_window():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show_editor()
    window.show()
    yield window
    window.scene.plotter.close()
    window.hide()
    window.deleteLater()
    app.processEvents()


@pytest.fixture
def window(application_window, monkeypatch):
    window = application_window
    window._reset_model_state()
    window.model.materials = {
        "Aço": (200000000.0, 76900000.0, 0.3, 77.0),
        "Concreto": (25000000.0, 10416666.0, 0.2, 25.0),
    }
    window.model.material_types = {"Aço": "Aço", "Concreto": "Concreto"}
    window.model.sections = {"Aço": ["W Laminado", "U Formado"], "Concreto": ["Retangular"]}
    window.palette.show_group("Geometria")
    window.set_member_direction_normalization_enabled(False)
    monkeypatch.setattr(window, "refresh_scene", lambda *args, **kwargs: None)
    return window


def set_material(editor, material):
    editor.properties._material_widget.findChild(QComboBox).setCurrentText(material)


def edit(field, text):
    field.setText(text)
    field.editingFinished.emit()


def launch(window, start, end):
    window._handle_member_placement_point(start)
    window._handle_member_placement_point(end)


def test_opening_and_editing_do_not_create_entities_or_invalidate_results(window):
    window.model.add_node("N1", 0, 0, 0)
    window.model.add_node("N2", 1, 0, 0)
    original = window.model.add_bar("B1", "N1", "N2")
    window.selected = ("bar", "B1")
    window.selected_elements = [window.selected]
    window.model.analysis_results.append("existing result")
    revision = window.model.revision

    window.start_member_placement()
    editor = window.member_placement_editor
    panel = editor.properties
    assert panel.isVisible()
    assert panel.width() == window.properties.width()
    assert panel.title.text() == "Adicionar membro"
    assert panel.name.isHidden()
    assert panel._identity_row.isHidden()
    assert panel.nodes_title.isHidden()
    assert panel.form.count() == 0
    assert panel.kind_control.isHidden()
    assert window.selected is None
    assert window.properties.isHidden()

    set_material(editor, "Aço")
    panel._section_combo.setCurrentText("W Laminado")
    panel._release_boxes[0].setChecked(False)
    panel._displacement_settings_button.click()
    edit(editor.displacement_panel.rotation_input, "45")
    assert editor.template.rotation == 45
    assert editor.template.releases[0]
    assert window.model.bars == {"B1": original}
    assert tuple(window.model.nodes) == ("N1", "N2")
    assert window.model.revision == revision
    assert window.model.analysis_results == ["existing result"]
    window.cancel_member_placement()
    assert window.model.revision == revision


def test_catalog_positioning_and_releases_are_inherited_by_each_new_member(window):
    window.start_member_placement()
    editor = window.member_placement_editor
    panel = editor.properties
    set_material(editor, "Aço")
    panel._section_combo.setCurrentText("W Laminado")
    panel._section_settings_button.click()
    section = editor.section_panel
    assert section.isVisible()
    section.profile.setCurrentIndex(0)
    section.mirror_toggle.click()
    section.mechanical_toggle.click()
    assert section.mechanical_container.isVisible()
    assert editor.template.profile
    assert editor.template.section_geometry
    assert editor.template.section_mirrored

    panel._displacement_settings_button.click()
    displacement = editor.displacement_panel
    assert displacement.isVisible()
    assert section.isHidden()
    assert not panel._section_settings_button.isChecked()
    edit(displacement.rotation_input, "45")
    edit(displacement._solid_offset_inputs["A"], "125")
    edit(displacement._solid_offset_inputs["B"], "250")
    edit(displacement._position_parameter_inputs["Y"], "12,5")
    edit(displacement._position_parameter_inputs["Z"], "-30")
    panel._release_boxes[0].setChecked(False)
    panel._release_boxes[9].setChecked(False)
    edit(panel._release_rotation_percent_inputs[7], "35")
    draft = editor.template
    assert draft.rotation == 45
    assert draft.solid_face_offsets == (0.125, 0.25)
    assert draft.solid_section_offsets == (0.0125, -0.03)
    assert draft.releases[0] and draft.releases[9]
    assert draft.rotation_flexibility_percent[1] == 35

    launch(window, (0, 0, 0), (2, 0, 0))
    launch(window, (2, 0, 0), (2, 3, 0))
    assert len(window.model.nodes) == 3  # shared endpoint is still reused
    for member in window.model.bars.values():
        for field in fields(Member):
            if field.name not in {"name", "start_node", "end_node"}:
                assert getattr(member, field.name) == getattr(draft, field.name), field.name
        assert member.name != draft.name
        assert member.start_node and member.end_node
    assert tuple(window.model.bars) == ("B1", "B2")
    assert editor.template == draft
    assert panel.isVisible()
    assert window._command_mode == "member_placement"
    assert window._member_placement_start is None

    old_members = dict(window.model.bars)
    edit(displacement.rotation_input, "90")
    launch(window, (2, 3, 0), (5, 3, 0))
    assert window.model.bars["B3"].rotation == 90
    assert all(window.model.bars[name] == member for name, member in old_members.items())


def test_parametric_section_uses_the_same_subpanel_and_material_filter(window):
    window.start_member_placement()
    editor = window.member_placement_editor
    set_material(editor, "Aço")
    editor.properties._section_combo.setCurrentText("U Formado")
    editor.properties._section_settings_button.click()
    assert editor.section_panel._section_family == "U Formado"
    for key, value in {"d": "100", "bf": "50", "t": "2"}.items():
        edit(editor.section_panel.fields[key], value)
    assert editor.template.section_geometry

    set_material(editor, "Concreto")
    assert editor.section_panel.isHidden()
    assert not editor.template.section
    assert not editor.template.profile
    assert not editor.template.section_geometry
    combo = editor.properties._section_combo
    assert [combo.itemText(index) for index in range(combo.count())] == ["Retangular"]
    combo.setCurrentText("Retangular")
    editor.properties._section_settings_button.click()
    assert editor.section_panel.isVisible()
    assert editor.section_panel._section_family == "Retangular"
    for key, value in {"b": "200", "h": "400"}.items():
        edit(editor.section_panel.fields[key], value)
    launch(window, (0, 0, 0), (0, 1, 0))
    assert window.model.bars["B1"].material == "Concreto"
    assert window.model.bars["B1"].section == "Retangular"
    assert window.model.bars["B1"].section_geometry == editor.template.section_geometry


def test_cancel_repeat_switch_tools_and_new_project_manage_the_draft(window):
    window.start_member_placement()
    editor = window.member_placement_editor
    set_material(editor, "Aço")
    editor.properties._section_combo.setCurrentText("W Laminado")
    editor.properties._section_settings_button.click()
    window.cancel_member_placement()
    assert editor.properties.isHidden() and editor.section_panel.isHidden()
    assert not editor.properties._section_settings_button.isChecked()
    assert not window.model.nodes and not window.model.bars

    window._last_command_callback()
    assert editor.properties.isVisible()
    assert editor.template.material == "Aço"
    assert editor.template.section == "W Laminado"
    editor.properties._displacement_settings_button.click()
    window.start_measurement()
    assert editor.properties.isHidden() and editor.displacement_panel.isHidden()
    window.start_member_placement()
    window.palette.show_group("Ações")
    assert editor.properties.isHidden()
    assert window._command_mode is None

    window._reset_model_state()
    assert editor.template == Member("draft", "", "")


def test_invalid_endpoints_keep_draft_and_do_not_leave_partial_members(window):
    window.start_member_placement()
    editor = window.member_placement_editor
    set_material(editor, "Aço")
    draft = editor.template
    launch(window, (0, 0, 0), (0, 0, 0))
    assert not window.model.nodes and not window.model.bars
    assert window._member_placement_start == (0.0, 0.0, 0.0)
    window._handle_member_placement_point((1, 0, 0))
    original = dict(window.model.bars)
    launch(window, (1, 0, 0), (0, 0, 0))
    assert window.model.bars == original
    assert len(window.model.nodes) == 2
    assert editor.template == draft
    assert editor.properties.isVisible()


def test_direction_normalization_keeps_chosen_member_properties(window):
    window.set_member_direction_normalization_enabled(True)
    window.start_member_placement()
    editor = window.member_placement_editor
    set_material(editor, "Aço")
    editor.properties._release_boxes[6].setChecked(False)
    launch(window, (2, 0, 0), (0, 0, 0))
    member = window.model.bars["B1"]
    assert window.model.nodes[member.start_node].x == 0
    assert window.model.nodes[member.end_node].x == 2
    assert member.material == "Aço"
    assert member.releases == editor.template.releases


@pytest.mark.parametrize("toggle", ["toggle_axes_panel", "toggle_reference_panel"])
def test_configuration_panels_do_not_overlap_the_placement_editor(window, toggle):
    window.start_member_placement()
    editor = window.member_placement_editor
    editor.properties._displacement_settings_button.click()
    getattr(window, toggle)()
    assert editor.properties.isHidden()
    assert editor.displacement_panel.isHidden()
    assert window._command_mode is None


def pick(window, point):
    """Confirm a viewport point through the same path as clicks and typed coordinates."""
    window.scene._manual_edit_target = np.asarray(point, dtype=float)
    window.scene._emit_member_placement_point()


def choose_point_mode(window, mode):
    window.member_placement_editor.properties.point_mode_switch._buttons[mode].click()


def test_exact_point_is_default_and_midpoint_switch_precedes_material(window):
    window.start_member_placement()
    panel = window.member_placement_editor.properties
    switch = panel.point_mode_switch
    assert switch.isVisible()
    assert switch._buttons["exact"].text() == "Ponto exato"
    assert switch._buttons["midpoint"].text() == "Ponto Médio"
    assert switch._buttons["exact"].isChecked()
    assert panel.layout.indexOf(switch) < panel.layout.indexOf(panel._material_widget)
    pick(window, (1, 2, 3))
    pick(window, (4, 5, 6))
    assert len(window.model.bars) == 1
    assert [(node.x, node.y, node.z) for node in window.model.nodes.values()] == [(1, 2, 3), (4, 5, 6)]


def test_midpoint_pairs_define_both_endpoints_without_creating_support_nodes(window):
    window.start_member_placement()
    editor = window.member_placement_editor
    choose_point_mode(window, "midpoint")
    set_material(editor, "Aço")
    assert editor.point_mode == "midpoint"
    revision = window.model.revision
    pick(window, (0, 2, 4))
    assert window._member_placement_start is None
    assert window.model.revision == revision
    pick(window, (4, 6, 8))
    assert window._member_placement_start == (2, 4, 6)
    assert not window.model.nodes and not window.model.bars
    pick(window, (10, 0, 2))
    assert not window.model.nodes and not window.model.bars
    pick(window, (14, 8, 10))
    assert [(node.x, node.y, node.z) for node in window.model.nodes.values()] == [(2, 4, 6), (12, 4, 6)]
    assert window.model.bars["B1"].material == "Aço"
    assert window.scene._member_midpoint_anchor is None
    assert window._member_placement_start is None
    assert editor.point_mode == "midpoint"
    assert window._command_mode == "member_placement"

    # Another pair at the existing endpoint reuses the node on the next member.
    for point in ((10, 0, 2), (14, 8, 10), (20, 0, 0), (24, 8, 12)):
        pick(window, point)
    assert len(window.model.bars) == 2
    assert len(window.model.nodes) == 3
    assert window.model.bars["B1"].end_node == window.model.bars["B2"].start_node


def test_point_mode_can_change_between_endpoints_and_discards_only_pending_pair(window):
    window.start_member_placement()
    pick(window, (1, 2, 3))
    choose_point_mode(window, "midpoint")
    pick(window, (100, 100, 100))
    choose_point_mode(window, "midpoint")  # clicking the active option keeps the pair
    np.testing.assert_allclose(window.scene._member_midpoint_anchor, (100, 100, 100))
    choose_point_mode(window, "exact")
    assert window.scene._member_midpoint_anchor is None
    assert window._member_placement_start == (1, 2, 3)
    pick(window, (5, 6, 7))
    assert [(node.x, node.y, node.z) for node in window.model.nodes.values()] == [(1, 2, 3), (5, 6, 7)]


@pytest.mark.parametrize("switch_tool", ["cancel_member_placement", "start_measurement", "start_node_placement",
                                       "start_rigid_bar_placement"])
def test_partial_midpoint_is_discarded_when_leaving_the_member_tool(window, switch_tool):
    window.start_member_placement()
    choose_point_mode(window, "midpoint")
    pick(window, (100, 0, 0))
    getattr(window, switch_tool)()
    assert window.scene._member_midpoint_anchor is None
    window.start_member_placement()
    assert window.member_placement_editor.point_mode == "midpoint"
    pick(window, (0, 0, 0))
    pick(window, (2, 2, 2))
    assert window._member_placement_start == (1, 1, 1)
    window._reset_model_state()
    assert window.member_placement_editor.point_mode == "exact"
    assert window.scene._member_midpoint_anchor is None


def test_midpoint_preview_ends_at_the_average_and_errors_allow_a_new_pair(window):
    window.start_member_placement()
    choose_point_mode(window, "midpoint")
    pick(window, (0, 0, 0))
    pick(window, (2, 0, 0))
    pick(window, (4, 2, 0))
    window.scene._update_member_preview(np.asarray((8, 6, 0)))
    mesh = window.scene._member_preview_actor.GetMapper().GetInput()
    np.testing.assert_allclose(mesh.GetPoint(0), (1, 0, 0))
    np.testing.assert_allclose(mesh.GetPoint(1), (6, 4, 0))

    # The same midpoint as the initial endpoint is rejected without extra nodes.
    pick(window, (-2, -2, 0))
    assert not window.model.nodes and not window.model.bars
    assert window._member_placement_start == (1, 0, 0)
    assert window.scene._member_midpoint_anchor is None
    pick(window, (5, 0, 0))
    pick(window, (7, 0, 0))
    assert len(window.model.bars) == 1


def test_midpoint_uses_snapped_endpoints_and_centers(window, monkeypatch):
    window.start_member_placement()
    choose_point_mode(window, "midpoint")
    scene = window.scene
    monkeypatch.setattr(scene, "_cursor_world_position", lambda: np.asarray((99, 99, 99)))
    monkeypatch.setattr(scene, "_placement_guide_target", lambda: None)
    for point, kind in (((2, 4, 6), "endpoint"), ((4, 8, 10), "center")):
        monkeypatch.setattr(scene, "_snap_position", lambda _position, p=point, k=kind: (np.asarray(p), k))
        scene._emit_member_placement_point()
    assert window._member_placement_start == (3, 6, 8)


@pytest.mark.parametrize("operation", ["member", "rigid", "measurement"])
def test_perpendicular_capture_is_applied_by_member_rigid_bar_and_measure_commands(window, monkeypatch, operation):
    window.model.add_node("A", -5, 0, 0)
    window.model.add_node("B", 5, 0, 0)
    window.model.add_bar("existing", "A", "B")
    scene = window.scene
    scene._pointer_position = None
    scene.render_model(window.model)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetParallelProjection(True)
    camera.SetPosition(0, 0, 30)
    camera.SetFocalPoint(0, 0, 0)
    camera.SetViewUp(0, 1, 0)
    camera.SetParallelScale(10)
    camera.SetClippingRange(0.1, 100)
    scene._snap_types["intersection"] = False
    monkeypatch.setattr(scene, "_measurement_visible_points", lambda screens, *_args, **_kwargs: np.ones(len(screens), bool))
    messages = []
    monkeypatch.setattr(window.history, "append", messages.append)
    {"member": window.start_member_placement, "rigid": window.start_rigid_bar_placement,
     "measurement": window.start_measurement}[operation]()
    pick(window, (1, 4, 0))
    screen, visible = scene._world_to_screen(np.asarray((1, 0, 0)))
    assert visible
    scene._pointer_position = tuple(screen)
    monkeypatch.setattr(scene, "_cursor_world_position", lambda: np.asarray((1.01, 0.01, 0)))
    scene._emit_member_placement_point()
    if operation == "measurement":
        assert any("Δ: 4.000 m" in message for message in messages)
        assert window._command_mode is None
        assert len(window.model.nodes) == 2
    else:
        member = window.model.bars["B1"] if operation == "member" else next(iter(window.model.rigid_bars.values()))
        node = window.model.nodes[member.end_node]
        np.testing.assert_allclose((node.x, node.y, node.z), (1, 0, 0))
