"""Multiple-selection geometry and inspector behavior."""

from __future__ import annotations

import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QMainWindow, QWidget

from osa.domain import AnalysisResult
from osa.model import StructuralModel
from osa.rendering.label_overlay import project_world_to_screen
from osa.rendering.scene_batched import SelectionRectangle, StructureScene
from osa.services import ActionService, ModelService
from osa.ui.property_panel import PropertyPanel


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class InspectorWindow(QMainWindow):
    def __init__(self, model: StructuralModel) -> None:
        super().__init__()
        self.model = model
        self.model_service = ModelService(model)
        self.action_service = ActionService(model)
        self.selected_action_name = "Caso"
        self.selected_analysis_combination = "Combinação"
        self.section_profiles = {}
        self.section_geometry = {}
        self.section_panel = QWidget(self)
        self.displacement_panel = QWidget(self)
        self.palette = SimpleNamespace(active_group="Geometria")
        self.selected = None
        self.color_refreshes = []

    def refresh_node(self, name: str) -> None:
        pass

    def refresh_node_visual(self, name: str) -> None:
        pass

    def refresh_member_releases(self, name: str) -> None:
        pass

    def refresh_member_geometry(self, name: str) -> None:
        pass

    def refresh_member_colors(self, names) -> None:
        self.color_refreshes.append(tuple(names))

    def refresh_scene(self) -> None:
        pass

    def refresh_selected_property_panel(self, section: str | None) -> None:
        if self.selected is not None and hasattr(self, "properties"):
            self.properties.show_for(
                *self.selected,
                section or "Geometria",
                selection=getattr(self, "selected_elements", None) or [self.selected],
            )

    def close_displacement_panel(self, button=None) -> None:
        self.displacement_panel.hide()

    def close_section_panel(self, button=None) -> None:
        self.section_panel.hide()


def _model() -> StructuralModel:
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 1, 0)
    model.add_node("N3", 2, 2, 0)
    model.add_bar("B1", "N1", "N2")
    model.add_bar("B2", "N2", "N3")
    return model


def test_member_pick_follows_visible_representation_with_section_offset(qt_app):
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_section("B1", "Barra Retangular")
    model.update_member_profile("B1", "R 200 x 200", {"b": 200.0, "h": 200.0})
    model.update_member_solid_section_offsets("B1", (1.0, 0.0))

    scene = StructureScene()
    scene.plotter.resize(800, 600)
    scene.show()
    qt_app.processEvents()
    context = scene.plotter.context()
    if context is None or not context.isValid():
        scene.close()
        pytest.skip("A seleção 3D requer um contexto OpenGL válido.")
    scene.render_model(model)
    camera = scene.plotter.renderer.GetActiveCamera()
    camera.SetPosition(2.5, 0.5, 10.0)
    camera.SetFocalPoint(2.5, 0.5, 0.0)
    camera.SetViewUp(0.0, 1.0, 0.0)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(2.5)
    scene.plotter.reset_camera_clipping_range()
    scene.plotter.render()

    matrix, width, height = scene._measurement_projection_context()
    face_start, face_end = scene._member_batch.face_point_ranges["B1"]
    face_center = scene._member_batch.faces.points[face_start:face_end].mean(axis=0)
    screens, visible = project_world_to_screen(
        np.asarray(((2.5, 0.0, 0.0), face_center)), matrix, width, height,
    )
    assert visible.tolist() == [True, True]
    assert np.linalg.norm(screens[0] - screens[1]) > 20.0

    scene.set_solid_members_visible(True)
    scene._pointer_position = tuple(screens[0])
    assert scene._pick() is None
    scene._pointer_position = tuple(screens[1])
    assert scene._pick() == ("bar", "B1")
    assert scene._hover_candidates_near_cursor()[0] == ("bar", "B1")
    line_x, line_y = (int(value) for value in screens[0])
    face_x, face_y = (int(value) for value in screens[1])
    assert ("bar", "B1") not in scene._elements_in_rectangle(
        (line_x + 5, line_y + 5), (line_x - 5, line_y - 5),
    )
    assert ("bar", "B1") in scene._elements_in_rectangle(
        (face_x + 5, face_y + 5), (face_x - 5, face_y - 5),
    )

    scene.set_solid_members_visible(False)
    scene._pointer_position = tuple(screens[0])
    assert scene._pick() == ("bar", "B1")
    scene._pointer_position = tuple(screens[1])
    assert scene._pick() is None
    assert ("bar", "B1") in scene._elements_in_rectangle(
        (line_x + 5, line_y + 5), (line_x - 5, line_y - 5),
    )
    assert ("bar", "B1") not in scene._elements_in_rectangle(
        (face_x + 5, face_y + 5), (face_x - 5, face_y - 5),
    )
    scene.plotter.close()
    scene.close()


def test_solid_mode_keeps_picking_a_member_drawn_as_fallback_line(qt_app):
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_section("B1", "Seção indisponível")

    scene = StructureScene()
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    assert "B1" not in scene._member_batch.face_cell_ranges
    assert scene._member_batch.fallback_lines.n_cells == 1
    screens = scene._pick_projection_data()[1]
    scene._pointer_position = tuple(screens.mean(axis=0))
    assert scene._pick() == ("bar", "B1")
    scene.plotter.close()
    scene.close()


def test_rectangle_requires_both_member_endpoints_inside(qt_app, monkeypatch):
    scene = StructureScene()
    monkeypatch.setattr(scene, "_pick_projection_data", lambda: (
        ("N1", "N2", "N3"),
        np.asarray(((10, 10), (30, 30), (70, 70)), dtype=float),
        np.asarray((True, True, True)),
        (("bar", "B1"), ("bar", "B2")),
        np.asarray(((10, 10), (30, 30)), dtype=float),
        np.asarray(((20, 20), (40, 40)), dtype=float),
        np.asarray((True, True)),
        *([np.zeros(2)] * 4),
    ))

    assert scene._elements_in_rectangle((5, 5), (40, 40)) == (
        ("node", "N1"), ("node", "N2"), ("bar", "B1"),
    )


def test_leftward_rectangle_selects_members_that_cross_or_touch_it(qt_app, monkeypatch):
    scene = StructureScene()
    monkeypatch.setattr(scene, "_pick_projection_data", lambda: (
        ("N1", "N2", "N3"),
        np.asarray(((10, 10), (30, 30), (70, 70)), dtype=float),
        np.asarray((True, True, True)),
        (("bar", "B1"), ("bar", "B2"), ("bar", "B3"), ("bar", "B4"), ("bar", "B5")),
        np.asarray(((10, 10), (30, 30), (-20, 20), (0, 0), (-20, 5)), dtype=float),
        np.asarray(((20, 20), (40, 40), (120, 0), (0, 100), (120, 0)), dtype=float),
        np.asarray((True, True, True, True, True)),
        *([np.zeros(5)] * 4),
    ))

    assert scene._elements_in_rectangle((40, 40), (5, 5)) == (
        ("node", "N1"), ("node", "N2"),
        ("bar", "B1"), ("bar", "B2"), ("bar", "B3"), ("bar", "B5"),
    )
    scene._ctrl_selection_press = (40, 10)
    scene._update_selection_rectangle(5, 40)
    assert scene._selection_rectangle._crossing
    scene._update_selection_rectangle(80, 40)
    assert not scene._selection_rectangle._crossing


def test_selection_rectangle_changes_from_blue_to_green(qt_app):
    parent = QWidget()
    rectangle = SelectionRectangle(parent)
    rectangle.resize(40, 40)
    assert rectangle.grab().toImage().pixelColor(0, 0).name() == "#0969da"
    rectangle.set_crossing(True)
    assert rectangle.grab().toImage().pixelColor(0, 0).name() == "#2da44e"


def test_ctrl_click_adds_and_then_removes_a_member(qt_app, monkeypatch):
    scene = StructureScene()
    scene._selected_elements = (("node", "N1"),)
    monkeypatch.setattr(scene._orientation_widget, "is_pointer_over", lambda x, y: False)
    monkeypatch.setattr(scene, "_pick", lambda: ("bar", "B1"))
    highlighted = []
    monkeypatch.setattr(scene, "set_selection_highlight", lambda elements: (
        highlighted.append(tuple(elements)),
        setattr(scene, "_selected_elements", tuple(elements)),
    ))
    changes = []
    scene.selection_changed.connect(changes.append)

    def mouse_event(kind):
        return QMouseEvent(
            kind, QPointF(100, 100), QPointF(100, 100), QPointF(100, 100),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
        )

    for _ in range(2):
        assert scene.eventFilter(scene.plotter, mouse_event(QEvent.Type.MouseButtonPress))
        assert scene.eventFilter(scene.plotter, mouse_event(QEvent.Type.MouseButtonRelease))

    assert highlighted == [(("node", "N1"), ("bar", "B1")), (("node", "N1"),)]
    assert changes == highlighted


def test_orbit_preserves_multiple_selection_until_a_click(qt_app, monkeypatch):
    scene = StructureScene()
    scene.plotter.render_window.SetSize(800, 600)
    scene._selected_elements = (("node", "N1"), ("bar", "B1"))
    scene._selected = ("bar", "B1")
    monkeypatch.setattr(scene._orientation_widget, "is_pointer_over", lambda *_args: False)
    monkeypatch.setattr(scene, "_pick", lambda: None)
    empty_clicks = []
    scene.empty_clicked.connect(lambda: empty_clicks.append(True))
    interactor = scene.plotter.iren.interactor

    interactor.SetEventInformation(100, 100, 0, 0, "a", 0, None)
    interactor.InvokeEvent("LeftButtonPressEvent")
    interactor.SetEventInformation(140, 100, 0, 0, "a", 0, None)
    interactor.InvokeEvent("MouseMoveEvent")
    interactor.InvokeEvent("LeftButtonReleaseEvent")

    assert scene._selected_elements == (("node", "N1"), ("bar", "B1"))
    assert empty_clicks == []

    interactor.SetEventInformation(100, 100, 0, 0, "a", 0, None)
    interactor.InvokeEvent("LeftButtonPressEvent")
    interactor.InvokeEvent("LeftButtonReleaseEvent")

    assert scene._selected_elements == ()
    assert empty_clicks == [True]


def test_mixed_member_release_click_disables_all(qt_app):
    model = _model()
    releases = list(model.bars["B1"].releases)
    releases[0] = True
    model.update_member_releases("B1", tuple(releases))
    window = InspectorWindow(model)
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    panel.show_for("bar", "B2", selection=(("bar", "B1"), ("bar", "B2")))

    assert panel.identity_value.text() == "Variado (2)"
    assert panel.fields[0].placeholderText() == "Variado"
    checkbox = panel._release_boxes[0]
    assert checkbox.checkState() == Qt.CheckState.PartiallyChecked
    checkbox.click()
    assert checkbox.checkState() == Qt.CheckState.Unchecked
    assert model.bars["B1"].releases[0]
    assert model.bars["B2"].releases[0]


def test_undefined_member_material_can_be_assigned_from_inspector(qt_app):
    model = _model()
    model.materials.update({"A": (1, 1, 1, 1), "B": (2, 2, 2, 2)})
    window = InspectorWindow(model)
    window.selected = ("bar", "B1")
    panel = PropertyPanel(window)
    panel.show_for("bar", "B1")

    material = panel._material_widget.findChild(QComboBox)
    assert material.isEnabled()
    assert material.currentIndex() == -1
    assert material.placeholderText() == "Indefinido"
    assert [material.itemText(index) for index in range(material.count())] == list(model.materials)
    assert model.bars["B1"].material == "Indefinido"

    material.setCurrentText("B")

    assert model.bars["B1"].material == "B"
    material = panel._material_widget.findChild(QComboBox)
    assert material.currentText() == "B"
    assert material.isEnabled()


def test_member_fields_show_common_or_varied_values(qt_app):
    model = _model()
    model.materials.update({"A": (1, 1, 1, 1), "B": (2, 2, 2, 2)})
    model.material_types.update({"A": "Aço", "B": "Aço"})
    model.sections["Aço"] = ["W", "Tubo"]
    model.update_bar_material("B1", "A", model.materials["A"])
    model.update_bar_material("B2", "B", model.materials["B"])
    model.update_bar_section("B1", "W")
    model.update_bar_section("B2", "Tubo")
    model.update_member_rotation("B1", 15)
    window = InspectorWindow(model)
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    selection = (("bar", "B1"), ("bar", "B2"))
    panel.show_for("bar", "B2", selection=selection)

    material = panel._material_widget.findChild(QComboBox)
    assert material.placeholderText() == "Variado"
    assert panel._section_combo.placeholderText() == "Variado"
    assert panel._positioning_status.text() == "Variado"

    model.update_bar_material("B2", "A", model.materials["A"])
    model.update_bar_section("B2", "W")
    model.update_member_rotation("B1", 0)
    panel.show_for("bar", "B2", selection=selection)
    material = panel._material_widget.findChild(QComboBox)
    assert material.currentText() == "A"
    assert panel._section_combo.currentText() == "W"
    assert panel._positioning_status.text() == "Centro geométrico"


def test_mixed_node_support_click_disables_all_and_coordinate_edit_is_isolated(qt_app):
    model = _model()
    model.update_node_supports("N1", (True, False, False, False, False, False))
    window = InspectorWindow(model)
    window.selected = ("node", "N2")
    panel = PropertyPanel(window)
    panel.show_for("node", "N2", selection=(("node", "N1"), ("node", "N2")))

    assert panel.identity_value.text() == "Variado (2)"
    assert panel.fields[0].text() == "Variado"
    checkbox = panel._supports_widget.findChildren(QCheckBox)[0]
    assert checkbox.checkState() == Qt.CheckState.PartiallyChecked
    checkbox.click()
    assert not model.nodes["N1"].supports[0]
    assert not model.nodes["N2"].supports[0]

    panel.fields[0].setValue(5)
    panel._node_changed("X")
    assert (model.nodes["N1"].x, model.nodes["N1"].y) == (5, 0)
    assert (model.nodes["N2"].x, model.nodes["N2"].y) == (5, 1)


def test_mixed_node_and_member_selection_can_inspect_both(qt_app):
    model = _model()
    window = InspectorWindow(model)
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    selection = (("node", "N1"), ("node", "N2"), ("bar", "B1"), ("bar", "B2"))
    panel.show_for("bar", "B2", selection=selection)

    assert panel.title.text() == "Elementos · 4 selecionados"
    assert panel.identity_value.text() == "Variado (2)"
    assert not panel.selection_kind_switch.isHidden()
    assert panel.selection_kind_switch._buttons["node"].text() == "Nós"
    assert panel.selection_kind_switch._buttons["bar"].text() == "Membros"
    panel.selection_kind_switch._buttons["node"].click()
    assert window.selected == ("node", "N2")
    assert panel._selection == selection
    assert panel.title.text() == "Elementos · 4 selecionados"
    assert panel.identity_value.text() == "Variado (2)"
    assert panel.selection_kind_switch._buttons["node"].isChecked()


def test_identity_counts_selected_members_of_its_kind(qt_app):
    model = _model()
    model.add_node("N4", 3, 3, 0)
    model.add_node("N5", 4, 4, 0)
    model.add_bar("B3", "N3", "N4")
    model.add_bar("B4", "N4", "N5")
    window = InspectorWindow(model)
    window.selected = ("bar", "B4")
    panel = PropertyPanel(window)
    selection = tuple(("bar", name) for name in ("B1", "B2", "B3", "B4"))
    panel.show_for("bar", "B4", selection=selection)

    assert panel.identity_value.text() == "Variado (4)"
    assert panel.title.text() == "Membros · 4 selecionados"


def test_selected_members_share_a_highlight_actor_and_nodes_keep_their_color(qt_app):
    model = _model()
    scene = StructureScene()
    scene.render_model(model)

    scene.set_selection_highlight((("bar", "B1"), ("node", "N2"), ("bar", "B2")))
    assert set(scene._highlight_actors) == {"selected:bar"}
    assert scene._highlight_actors["selected:bar"].GetMapper().GetInput().GetNumberOfLines() == 2
    node_index = scene._node_batch.names.index("N2")
    assert tuple(scene._node_glyph_points.point_data["rgb"][node_index]) == (9, 105, 218)

    scene.set_selection_highlight((("bar", "B1"),))
    assert scene._highlight_actors["selected:bar"].GetMapper().GetInput().GetNumberOfLines() == 1
    assert tuple(scene._node_glyph_points.point_data["rgb"][node_index]) == (0, 0, 0)
    scene.plotter.close()
    scene.close()


def test_solid_selection_preserves_each_member_contour(qt_app):
    model = _model()
    model.update_bar_section("B1", "Barra Circular")
    model.update_member_profile("B1", "D 100", {"d": 100.0})
    scene = StructureScene()
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    scene.set_selection_highlight((("bar", "B1"), ("bar", "B2")))

    assert set(scene._highlight_actors) == {"selected:circular", "selected:bar"}
    for slot, targets in scene._highlight_targets.items():
        actual = scene._highlight_actors[slot].GetMapper().GetInput().GetNumberOfLines()
        expected = sum(scene._member_highlight_mesh(name).n_lines for _, name in targets)
        assert actual == expected
    scene.plotter.close()
    scene.close()


def test_color_edit_refreshes_selected_members_together(qt_app):
    model = _model()
    window = InspectorWindow(model)
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    panel.show_for("bar", "B2", selection=(("bar", "B1"), ("bar", "B2")))

    panel._color_selected("#0969da")

    assert model.bars["B1"].color == model.bars["B2"].color == "#0969da"
    assert window.color_refreshes == [("B1", "B2")]


def test_color_batch_updates_only_the_edited_members(qt_app):
    model = _model()
    model.add_node("N4", 3, 3, 0)
    model.add_bar("B3", "N3", "N4")
    scene = StructureScene()
    scene.render_model(model)
    unchanged_color = tuple(scene._member_batch.lines.cell_data["rgb"][2])

    model.update_member_color("B1", "#0969da")
    model.update_member_color("B2", "#d1242f")
    scene.update_member_colors(("B1", "B2"))

    colors = scene._member_batch.lines.cell_data["rgb"]
    assert tuple(colors[0]) == (9, 105, 218)
    assert tuple(colors[1]) == (209, 36, 47)
    assert tuple(colors[2]) == unchanged_color
    scene.plotter.close()
    scene.close()


def test_positioning_edit_refreshes_all_member_indicators(qt_app):
    model = _model()
    model.update_bar_section("B1", "Barra Retangular")
    model.update_member_profile("B1", "R", {"b": 100.0, "h": 200.0})
    model.update_member_releases("B1", (True,) * 12)
    model.update_member_rotation_flexibility_percent("B1", (15,) * 6)
    scene = StructureScene()
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    try:
        batch = scene._member_batch
        labels_before = batch.label_positions.copy()
        springs_before = scene._elastic_support_overlay._positions.copy()
        axes_before = [mesh.points.copy() for mesh in batch.axes]
        releases_before = batch.releases.points.copy()
        for offsets in ((0.3, -0.2), (0.0, 0.0), (0.3, -0.2)):
            model.update_member_solid_section_offsets("B1", offsets)
            scene.update_member_geometry("B1")
            scene._refresh_pending_member_update()
            delta = np.asarray((-offsets[0] / np.sqrt(2), offsets[0] / np.sqrt(2), offsets[1]))
            assert scene._member_batch is batch
            np.testing.assert_allclose(batch.label_positions[0], labels_before[0] + delta)
            np.testing.assert_allclose(batch.label_positions[1], labels_before[1])
            np.testing.assert_allclose(scene._label_overlay._groups["bar"].positions, batch.label_positions)
            np.testing.assert_allclose(scene._elastic_support_overlay._positions, springs_before + delta)
            np.testing.assert_allclose(batch.releases.points, releases_before + delta, atol=1e-7)
            for mesh, original in zip(batch.axes, axes_before):
                np.testing.assert_allclose(mesh.points[:2], original[:2] + delta, atol=1e-7)
                np.testing.assert_allclose(mesh.points[2:], original[2:])
        for solid in (False, True, False):
            scene.set_solid_members_visible(solid)
            offset = delta if solid else np.zeros(3)
            current = scene._member_batch
            np.testing.assert_allclose(current.label_positions[0], labels_before[0] + offset)
            np.testing.assert_allclose(scene._label_overlay._groups["bar"].positions, current.label_positions)
            np.testing.assert_allclose(scene._elastic_support_overlay._positions, springs_before + offset)
            np.testing.assert_allclose(current.releases.points, releases_before + offset, atol=1e-7)
            for mesh, original in zip(current.axes, axes_before):
                np.testing.assert_allclose(mesh.points[:2], original[:2] + offset, atol=1e-7)
                np.testing.assert_allclose(mesh.points[2:], original[2:])
    finally:
        scene.plotter.close()
        scene.close()


def test_multiple_profile_edits_keep_the_member_batch_when_topology_matches(qt_app):
    model = _model()
    for name in ("B1", "B2"):
        model.update_bar_section(name, "Barra Retangular")
        model.update_member_profile(name, "R 100 x 200", {"b": 100.0, "h": 200.0})
    scene = StructureScene()
    scene.render_model(model)
    scene.set_solid_members_visible(True)
    scene.set_selection_highlight((("bar", "B1"), ("bar", "B2")))
    original_batch = scene._member_batch
    original_points = original_batch.faces.points.copy()

    for name in ("B1", "B2"):
        model.update_member_profile(name, "R 150 x 200", {"b": 150.0, "h": 200.0})
        scene.update_member_geometry(name)
    scene._refresh_pending_member_update()

    assert scene._member_batch is original_batch
    assert not np.array_equal(scene._member_batch.faces.points, original_points)
    assert set(scene._highlight_actors) == {"selected:bar"}
    scene.plotter.close()
    scene.close()


def test_node_actions_show_common_and_varied_values_and_edit_all(qt_app):
    model = _model()
    window = InspectorWindow(model)
    for name in ("N1", "N2"):
        window.action_service.add_node_force(name, "X", 5, "Caso")
    window.action_service.add_node_force("N1", "Y", 3, "Caso")
    window.action_service.add_node_force("N2", "Y", 4, "Caso")
    window.action_service.add_node_moment("N1", "Z", 2, "Caso")
    window.selected = ("node", "N2")
    panel = PropertyPanel(window)
    panel.show_for("node", "N2", "Ações", selection=(("node", "N1"), ("node", "N2")))

    assert panel._node_action_inputs["FX"].text() == "5"
    assert panel._node_action_inputs["FY"].text() == "Variado"
    assert panel._node_action_inputs["MZ"].text() == "Variado"
    assert panel._node_action_inputs["FZ"].text() == ""

    field = panel._node_action_inputs["FY"]
    field.setText("8")
    panel._node_action_changed("FY", field)
    assert panel._node_action_inputs["FY"].text() == "8"
    assert {
        action.target: action.components
        for action in model.actions.values() if action.kind == "node_force_Y"
    } == {"N1": (8.0,), "N2": (8.0,)}


def test_member_actions_show_common_and_varied_values_and_edit_all(qt_app):
    model = _model()
    window = InspectorWindow(model)
    for name in ("B1", "B2"):
        window.action_service.add_member_distributed_force(name, "X", 5, 5, "Caso")
    window.action_service.add_member_distributed_force("B1", "Z", 1, 1, "Caso")
    window.action_service.add_member_distributed_force("B2", "Z", 2, 2, "Caso")
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    panel.show_for("bar", "B2", "Ações", selection=(("bar", "B1"), ("bar", "B2")))

    assert panel._member_action_inputs["FX"].text() == "5"
    assert panel._member_action_inputs["FZ"].text() == "Variado"

    field = panel._member_action_inputs["FZ"]
    field.setText("1; 3")
    panel._member_action_changed("FZ", field)
    assert panel._member_action_inputs["FZ"].text() == "1; 3"
    assert {
        action.target: action.components
        for action in model.actions.values() if action.kind == "member_distributed_force_Z"
    } == {"B1": (1.0, 3.0), "B2": (1.0, 3.0)}


def _analysis_row(panel: PropertyPanel, label: str) -> str:
    for widget in panel._context_widgets:
        labels = widget.findChildren(QLabel)
        if len(labels) == 2 and labels[0].text() == label:
            return labels[1].text()
    raise AssertionError(f"Analysis row {label!r} not found")


def test_node_analysis_shows_common_varied_and_missing_results(qt_app):
    model = _model()
    model.analysis_results = [AnalysisResult(
        model.revision, "Combinação",
        node_results={"N1": {"DX": 0.1, "DY": 0.2, "RXN_FX": 5},
                      "N2": {"DX": 0.1, "DY": 0.3}},
    )]
    window = InspectorWindow(model)
    window.selected = ("node", "N2")
    panel = PropertyPanel(window)
    panel.show_for("node", "N2", "Análise", selection=(("node", "N1"), ("node", "N2")))

    assert _analysis_row(panel, "X") == "0,1 m"
    assert _analysis_row(panel, "Y") == "Variado"
    assert _analysis_row(panel, "Força X") == "Variado"


def test_member_analysis_compares_endpoints_and_extrema(qt_app):
    model = _model()
    model.analysis_results = [AnalysisResult(
        model.revision, "Combinação", member_results={
            "B1": {"start": {"axial": 5, "shear_y": 1},
                   "end": {"axial": 2},
                   "samples": ({"axial": 5, "shear_y": 1}, {"axial": 2, "shear_y": -3})},
            "B2": {"start": {"axial": 5, "shear_y": 2},
                   "end": {"axial": 3},
                   "samples": ({"axial": 5, "shear_y": 2}, {"axial": 3, "shear_y": -3})},
        },
    )]
    window = InspectorWindow(model)
    window.selected = ("bar", "B2")
    panel = PropertyPanel(window)
    panel.show_for("bar", "B2", "Análise", selection=(("bar", "B1"), ("bar", "B2")))

    assert _analysis_row(panel, "Normal") == "5 kN"
    assert _analysis_row(panel, "Cortante Y") == "Variado"

    panel._set_analysis_result_view("B")
    assert _analysis_row(panel, "Normal") == "Variado"

    panel._set_analysis_result_view("MAX")
    extrema = next(widget for widget in panel._context_widgets if widget.layout()
                   and widget.layout().__class__.__name__ == "QGridLayout")
    grid = extrema.layout()
    assert grid.itemAtPosition(1, 1).widget().text() == "5"
    assert grid.itemAtPosition(2, 1).widget().text() == "Variado"
    assert grid.itemAtPosition(2, 2).widget().text() == "-3"


def test_mixed_kind_switch_keeps_action_and_analysis_selection(qt_app):
    model = _model()
    window = InspectorWindow(model)
    window.action_service.add_node_force("N1", "X", 2, "Caso")
    window.action_service.add_node_force("N2", "X", 3, "Caso")
    window.action_service.add_member_distributed_force("B1", "X", 5, 5, "Caso")
    model.analysis_results = [AnalysisResult(
        model.revision, "Combinação",
        node_results={"N1": {"DX": 1}, "N2": {"DX": 2}},
        member_results={"B1": {"start": {"axial": 4}}},
    )]
    selection = (("node", "N1"), ("node", "N2"), ("bar", "B1"))
    window.selected = ("bar", "B1")
    window.selected_elements = list(selection)
    window.palette.active_group = "Ações"
    panel = PropertyPanel(window)
    window.properties = panel
    panel.show_for("bar", "B1", "Ações", selection=selection)

    assert panel.title.text() == "Elementos · 3 selecionados"
    assert panel._member_action_inputs["FX"].text() == "5"
    panel.selection_kind_switch._buttons["node"].click()
    assert panel._selection == selection
    assert panel._node_action_inputs["FX"].text() == "Variado"

    window.palette.active_group = "Análise"
    panel.show_for("node", "N2", "Análise", selection=selection)
    assert _analysis_row(panel, "X") == "Variado"
    panel.selection_kind_switch._buttons["bar"].click()
    assert panel._selection == selection
    assert _analysis_row(panel, "Normal") == "4 kN"


def test_bulk_node_coordinates_are_atomic():
    model = _model()
    before = (model.nodes["N1"], model.nodes["N2"], model.revision)
    with pytest.raises(ValueError):
        model.update_nodes_coordinates({"N1": (2, 2, 0), "N2": (3, 3, 0)})
    assert (model.nodes["N1"], model.nodes["N2"], model.revision) == before

    model.update_nodes_coordinates({"N1": (5, 0, 0), "N2": (5, 1, 0)})
    assert model.nodes["N1"].x == model.nodes["N2"].x == 5
    assert model.revision == before[2] + 1
