"""Component preview geometry and applied scene stay efficient and selectable."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from osa.domain.entities import NodeComponentAssignment
from osa.domain.node_components import base_plate_anchor_offsets
from osa.model import StructuralModel
from osa.rendering.node_component_renderer import base_plate_component_meshes
from osa.rendering.scene_batched import StructureScene
from osa.ui.node_components_dialog import ComponentPreview, NodeComponentsDialog
from osa.ui.theme import APP_STYLESHEET


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _model_with_connected_bars() -> StructuralModel:
    model = StructuralModel()
    model.add_node("N0", 0.0, 0.0, 0.0)
    for index, (x, y, z) in enumerate(
        ((1, 0, 0), (0.7, 0.7, 0), (0, 1, 0), (-0.7, 0.7, 0),
         (-1, 0, 0), (-0.7, -0.7, 0), (0, -1, 0), (0.7, -0.7, 0)),
        start=1,
    ):
        node_name = f"N{index}"
        model.add_node(node_name, x, y, z)
        model.add_bar(f"B{index}", "N0", node_name)
    return model


def _hook_parameters(count_a=4, count_b=6):
    return {
        "largura_mm": 300.0,
        "comprimento_mm": 300.0,
        "espessura_mm": 20.0,
        "rotacao_deg": 0.0,
        "fixador": "Gancho",
        "diametro_mm": 16.0,
        "comprimento_fixador_mm": 300.0,
        "embutimento_mm": 150.0,
        "perna_mm": 200.0,
        "fixadores_lado_a": count_a,
        "fixadores_lado_b": count_b,
        "distancia_a_mm": 50.0,
    }


@pytest.mark.parametrize(
    ("count_a", "count_b", "expected"),
    ((2, 2, 4), (2, 3, 6), (4, 6, 16)),
)
def test_fasteners_are_only_on_the_plate_perimeter(count_a, count_b, expected):
    params = _hook_parameters(count_a, count_b)
    anchors = base_plate_anchor_offsets(params)

    assert len(anchors) == expected
    x_edges = {-params["largura_mm"] / 2 + params["distancia_a_mm"],
               params["largura_mm"] / 2 - params["distancia_a_mm"]}
    y_edges = {-params["comprimento_mm"] / 2 + params["distancia_a_mm"],
               params["comprimento_mm"] / 2 - params["distancia_a_mm"]}
    assert all(x in x_edges or y in y_edges for x, y in anchors)


def test_plate_displacements_translate_the_full_assembly_in_rotated_axes():
    params = _hook_parameters()
    params["fixador"] = "Reto"
    params["rotacao_deg"] = 90.0
    centered = base_plate_component_meshes(params, (0.0, 0.0, 0.0))
    params["deslocamento_a_mm"] = 100.0
    params["deslocamento_b_mm"] = -50.0
    shifted = base_plate_component_meshes(params, (0.0, 0.0, 0.0))

    def bounds_center(mesh):
        bounds = mesh.bounds
        return ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2,
                (bounds[4] + bounds[5]) / 2)

    moved_parts = (shifted[0], shifted[1][0], shifted[2][0], shifted[3][0])
    base_parts = (centered[0], centered[1][0], centered[2][0], centered[3][0])
    for moved, base in zip(moved_parts, base_parts):
        assert tuple(a - b for a, b in zip(bounds_center(moved), bounds_center(base))) == pytest.approx(
            (0.05, 0.1, 0.0), abs=1e-8,
        )


@pytest.mark.parametrize(
    ("plane", "normal_axis", "sign"),
    (
        ("XY+", 2, 1), ("XY-", 2, -1),
        ("XZ+", 1, 1), ("XZ-", 1, -1),
        ("YZ+", 0, 1), ("YZ-", 0, -1),
    ),
)
def test_base_plate_plane_orients_the_full_assembly(plane, normal_axis, sign):
    params = _hook_parameters()
    params.update(fixador="Reto", plano=plane)
    origin = (0.3, -0.2, 0.8)
    plate, rods, washers, nuts = base_plate_component_meshes(params, origin)

    bounds = plate.bounds
    minimum, maximum = bounds[normal_axis * 2:normal_axis * 2 + 2]
    expected_origin = origin[normal_axis]
    if sign > 0:
        assert minimum == pytest.approx(expected_origin, abs=1e-7)
        assert maximum == pytest.approx(expected_origin + 0.02, abs=1e-7)
    else:
        assert minimum == pytest.approx(expected_origin - 0.02, abs=1e-7)
        assert maximum == pytest.approx(expected_origin, abs=1e-7)

    assembly = (*rods, *washers, *nuts)
    assert all(
        (mesh.bounds[normal_axis * 2] < expected_origin if sign < 0
         else mesh.bounds[normal_axis * 2 + 1] > expected_origin)
        for mesh in assembly
    )


def test_base_plate_plane_is_normalized_and_validated_on_the_node():
    model = StructuralModel()
    model.add_node("N0", 0.0, 0.0, 0.0)
    params = _hook_parameters()
    params["fixador"] = "Reto"
    params.pop("plano", None)
    node = model.update_node_component(
        "N0", NodeComponentAssignment("base_plate", tuple(params.items())),
    )
    assert dict(node.component.parameters)["plano"] == "XY+"

    params["plano"] = "XY?"
    with pytest.raises(ValueError, match="plano válido"):
        model.update_node_component(
            "N0", NodeComponentAssignment("base_plate", tuple(params.items())),
        )


def test_preview_reuses_actors_bars_and_camera_while_editing(qt_app):
    model = _model_with_connected_bars()
    preview = ComponentPreview(model, "N0")
    try:
        preview.set_component("base_plate", _hook_parameters())
        bar_actors = tuple(preview._preview_bar_actors)
        camera = preview.plotter.renderer.GetActiveCamera()
        camera_position = camera.GetPosition()
        preview._set_selected_hook(3)
        component_actors = tuple(preview._preview_component_actors)

        changed = _hook_parameters()
        changed["espessura_mm"] = 25.0
        preview.set_component("base_plate", changed)

        assert tuple(preview._preview_component_actors) == component_actors
        assert tuple(preview._preview_bar_actors) == bar_actors
        assert all(
            not actor.GetProperty().GetLighting()
            for actor in (*component_actors, *bar_actors)
        )
        assert camera.GetPosition() == camera_position
        assert len(preview._hook_cell_ranges) == 16
        assert preview._selected_hook_index == 3
        assert preview._selected_hook_silhouette_actor.GetVisibility()
        assert preview._selected_hook_silhouette_actor.GetProperty().GetColor() == pytest.approx(
            (9 / 255, 105 / 255, 218 / 255), abs=0.01,
        )

        preview._set_selected_hook(-1)
        assert not preview._selected_hook_silhouette_actor.GetVisibility()
    finally:
        preview.shutdown()


def test_component_preview_uses_adjusted_local_bar_segment(qt_app):
    import numpy as np
    import pyvista as pv

    model = StructuralModel()
    model.add_node("N0", 0.0, 0.0, 0.0)
    model.add_node("N1", 2.0, 0.0, 0.0)
    model.add_bar("B1", "N0", "N1")

    # Represents the detailing solid after its section displacement has been
    # applied. The preview should preserve that displacement and crop it to
    # the short segment connected to the component.
    # Closed hollow square tube with annular end faces.
    points = []
    for x in (0.0, 2.0):
        points.extend((
            (x, 0.07, -0.05), (x, 0.17, -0.05),
            (x, 0.17, 0.05), (x, 0.07, 0.05),
            (x, 0.08, -0.04), (x, 0.16, -0.04),
            (x, 0.16, 0.04), (x, 0.08, 0.04),
        ))
    faces = []
    for offset in (0, 4):
        for corner in range(4):
            next_corner = (corner + 1) % 4
            faces.append((4, offset + corner, offset + next_corner,
                          offset + next_corner + 8, offset + corner + 8))
    for x_offset in (0, 8):
        for corner in range(4):
            next_corner = (corner + 1) % 4
            faces.append((4, x_offset + corner, x_offset + next_corner,
                          x_offset + next_corner + 4, x_offset + corner + 4))
    packed_faces = np.hstack([np.asarray(face, dtype=np.int64) for face in faces])
    adjusted_bar = pv.PolyData(np.asarray(points), packed_faces).triangulate()

    class _DetailingGeometry:
        def detailing_view_solid_meshes(self, _model):
            return (("B1", adjusted_bar),)

    preview = ComponentPreview(
        model, "N0", detailing_scene=_DetailingGeometry(),
    )
    try:
        preview.set_component("base_plate", _hook_parameters())
        actor = next(
            actor for actor in preview._preview_bar_actors
            if actor.GetObjectName() == "component-preview-bar:B1"
        )
        bounds = actor.GetMapper().GetInput().GetBounds()
        edge_actor = next(
            actor for actor in preview._preview_bar_actors
            if actor.GetObjectName() == "component-preview-bar-edge:B1"
        )

        assert bounds[0] == pytest.approx(0.0, abs=1e-6)
        assert bounds[1] == pytest.approx(0.42, abs=1e-5)
        assert bounds[2] == pytest.approx(0.07, abs=1e-6)
        assert bounds[3] == pytest.approx(0.17, abs=1e-6)
        assert pv.wrap(actor.GetMapper().GetInput()).n_open_edges == 0
        assert edge_actor.GetMapper().GetInput().GetNumberOfCells() > 0
        assert preview._rod_silhouette_actors[0].GetMapper().GetInput().GetNumberOfCells() > 0
    finally:
        preview.shutdown()


def test_component_preview_keeps_curved_section_transition_edges(qt_app):
    import pyvista as pv

    model = StructuralModel()
    model.add_node("N0", 0.0, 0.0, 0.0)
    model.add_node("N1", 2.0, 0.0, 0.0)
    model.add_bar("B1", "N0", "N1")
    model.update_bar_section("B1", "Tubular Quadrado")
    model.update_member_profile("B1", "TQ100x3", {"b": 100.0, "t": 3.0})
    adjusted_bar = pv.Cube(
        center=(1.0, 0.0, 0.0), x_length=2.0, y_length=0.10, z_length=0.10,
    ).triangulate()

    class _DetailingGeometry:
        def detailing_view_solid_meshes(self, _model):
            return (("B1", adjusted_bar),)

    preview = ComponentPreview(model, "N0", detailing_scene=_DetailingGeometry())
    try:
        preview.set_component("base_plate", _hook_parameters())
        edge_actor = next(
            actor for actor in preview._preview_bar_actors
            if actor.GetObjectName() == "component-preview-bar-edge:B1"
        )
        edge_mesh = pv.wrap(edge_actor.GetMapper().GetInput())

        # The rounded tube has sixteen curve-transition lines in addition to
        # the ordinary edges extracted from its adjusted solid.
        assert edge_mesh.n_lines >= 16
        assert edge_mesh.bounds[0] == pytest.approx(0.0, abs=1e-6)
        assert edge_mesh.bounds[1] == pytest.approx(0.42, abs=1e-5)
    finally:
        preview.shutdown()


def test_dialog_labels_and_accepts_signed_plate_displacements(qt_app):
    model = _model_with_connected_bars()
    window = QWidget()
    window.model = model
    previous_stylesheet = qt_app.styleSheet()
    qt_app.setStyleSheet(APP_STYLESHEET)
    dialog = NodeComponentsDialog(window, "N0")
    try:
        dialog.component_list.setCurrentRow(1)
        dialog.resize(1120, 680)
        dialog.show()
        qt_app.processEvents()

        assert list(dialog._inputs)[:4] == [
            "largura_mm", "comprimento_mm", "deslocamento_a_mm", "deslocamento_b_mm",
        ]
        assert dialog.parameters_scroll.verticalScrollBar().maximum() == 0
        assert dialog._inputs["largura_mm"].accessibleName() == "Dimensão A"
        assert dialog._inputs["comprimento_mm"].accessibleName() == "Dimensão B"
        plane = dialog._inputs["plano"]
        assert plane.currentText() == "XY+"
        assert [plane.itemText(index) for index in range(plane.count())] == [
            "XY+", "XY-", "XZ+", "XZ-", "YZ+", "YZ-",
        ]
        assert dialog.details_title.text() == "Chapa de base/topo"
        plane.setCurrentText("XZ+")
        qt_app.processEvents()
        assert dialog._draft_parameters["plano"] == "XZ+"
        preview_plate_bounds = dialog.preview._plate_actor.GetMapper().GetInput().GetBounds()
        assert preview_plate_bounds[2:4] == pytest.approx((0.0, 0.02), abs=1e-7)
        plane.setCurrentText("XY+")
        displacement = dialog._inputs["deslocamento_a_mm"]
        assert displacement.minimum() < 0.0
        displacement.setValue(-25.0)
        assert dialog._draft_parameters["deslocamento_a_mm"] == -25.0

        dialog._inputs["fixador"].setCurrentText("Gancho")
        qt_app.processEvents()
        assert dialog.parameters_scroll.verticalScrollBar().maximum() > 0
        assert dialog.parameters_widget.minimumHeight() == dialog.parameters_layout.sizeHint().height()
    finally:
        dialog.reject()
        window.close()
        qt_app.setStyleSheet(previous_stylesheet)


def test_applied_component_uses_constant_actor_count(qt_app):
    model = _model_with_connected_bars()
    params = _hook_parameters()
    params["plano"] = "XZ+"
    preview = ComponentPreview(model, "N0")
    preview.set_component("base_plate", params)
    model.update_node_component(
        "N0", NodeComponentAssignment("base_plate", tuple(params.items())),
    )
    scene = StructureScene()
    try:
        scene.render_model(model)

        assert len(scene._node_component_actors) == 6
        assert len(scene._node_component_rod_meshes) == 1
        assert len(scene._node_component_pick_actors) == 3
        bounds = scene._node_component_plate_actors["N0"].GetMapper().GetInput().GetBounds()
        assert bounds[2:4] == pytest.approx((0.0, 0.02), abs=1e-7)
        assert scene._node_component_actors[0].GetMapper().GetInput().GetBounds() == pytest.approx(
            preview._plate_actor.GetMapper().GetInput().GetBounds(),
        )
    finally:
        scene.close()
        preview.shutdown()
