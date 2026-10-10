from itertools import product

import numpy as np
import vtk

from osa.commands import CommandSession
from osa.domain import Action, Node
from osa.model import StructuralModel
from osa.rendering.action_renderer import ActionRenderer
from osa.rendering.batched_renderer import (
    BatchedMemberRenderer,
    BatchedNodeRenderer,
    has_semirigid_member_end,
)
from osa.services import ModelService
from osa.services.action_service import ActionService


def warehouse_model():
    model = StructuralModel()
    response = CommandSession(ModelService(model)).submit("galpao")
    assert response.model_changed
    return model


def test_member_batch_keeps_full_solid_geometry_and_pick_identity():
    model = warehouse_model()
    renderer = BatchedMemberRenderer()
    batch = renderer.build(model, 0.05)

    assert len(batch.names) == 839
    assert batch.lines.n_cells == 839
    assert batch.faces.n_cells > len(batch.names)
    assert batch.edges.n_cells > len(batch.names)
    assert [mesh.n_cells for mesh in batch.axes] == [839, 839, 839]
    assert set(np.unique(batch.faces.cell_data["element_index"])) == set(range(839))
    assert set(np.unique(batch.lines.cell_data["element_index"])) == set(range(839))
    assert batch.faces.cell_data["rgb"].shape == (batch.faces.n_cells, 3)
    assert len(batch.outlines) == 839
    expected_silhouette_members = {
        name for name, member in model.bars.items()
        if member.section in renderer._silhouette_sections
    }
    assert set(batch.silhouette_sources) == expected_silhouette_members
    assert sum(mesh.n_cells for mesh in batch.silhouette_faces_by_color.values()) > 0


def test_member_silhouette_batch_keeps_a_line_for_each_visible_contour():
    model = warehouse_model()
    renderer = BatchedMemberRenderer()
    batch = renderer.build(model, 0.05)
    camera = vtk.vtkCamera()
    camera.SetPosition(20.0, 20.0, 15.0)
    camera.SetFocalPoint(0.0, 0.0, 0.0)

    silhouettes = renderer.silhouette_mesh(batch, camera)

    assert silhouettes.n_lines > 0
    assert silhouettes.cell_data["rgb"].shape == (silhouettes.n_cells, 3)
    assert np.all(silhouettes.cell_data["rgb"] == np.asarray((71, 77, 83), dtype=np.uint8))


def test_member_silhouette_color_update_only_rebuilds_its_color_groups():
    model = warehouse_model()
    renderer = BatchedMemberRenderer()
    batch = renderer.build(model, 0.05)
    member_name = next(iter(batch.silhouette_sources))
    camera = vtk.vtkCamera()
    camera.SetPosition(20.0, 20.0, 15.0)
    camera.SetFocalPoint(0.0, 0.0, 0.0)

    renderer.update_silhouette_color(batch, member_name, np.asarray((9, 18, 27), dtype=np.uint8))
    silhouettes = renderer.silhouette_mesh(batch, camera)

    assert batch.silhouette_member_colors[member_name] == (9, 18, 27)
    assert np.any(np.all(silhouettes.cell_data["rgb"] == (5, 11, 17), axis=1))


def test_node_batch_keeps_spherical_markers_and_pick_identity():
    model = warehouse_model()
    batch = BatchedNodeRenderer().build(model, 0.05)

    assert len(batch.names) == 408
    assert batch.geometry.n_cells > len(batch.names)
    assert set(np.unique(batch.geometry.cell_data["element_index"])) == set(range(408))
    assert batch.geometry.cell_data["rgb"].shape == (batch.geometry.n_cells, 3)
    assert np.all(batch.geometry.cell_data["rgb"] == 0)
    assert batch.supports.n_cells > 0
    assert batch.label_positions.shape == (408, 3)


def test_fixed_support_is_a_thirty_centimeter_3x3x3_modular_cube():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N1", 0.0, 0.0, 0.0, (True, True, True, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.n_cells == 27 * 6
    assert np.allclose(mesh.bounds, expected_bounds)


def test_number_62_support_chamfers_the_top_layer_along_x():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N62", 0.0, 0.0, 0.0, (True, True, True, True, False, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.n_cells == 18 * 6 + 6 * 5 + 3 * 6
    assert np.allclose(mesh.bounds, expected_bounds)
    top_points = mesh.points[np.isclose(mesh.points[:, 2], 0.0)]
    bottom_top_layer_points = mesh.points[np.isclose(mesh.points[:, 2], -0.10)]
    assert np.isclose(top_points[:, 0].max(), 0.05)
    assert np.isclose(bottom_top_layer_points[:, 0].max(), 0.15)


def test_number_60_support_chamfers_the_top_layer_along_y():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N60", 0.0, 0.0, 0.0, (True, True, True, False, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.n_cells == 18 * 6 + 6 * 5 + 3 * 6
    assert np.allclose(mesh.bounds, expected_bounds)
    top_points = mesh.points[np.isclose(mesh.points[:, 2], 0.0)]
    bottom_top_layer_points = mesh.points[np.isclose(mesh.points[:, 2], -0.10)]
    assert np.isclose(top_points[:, 1].max(), 0.05)
    assert np.isclose(bottom_top_layer_points[:, 1].max(), 0.15)


def test_number_58_intersects_x_and_y_top_chamfers_at_the_corners():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N58", 0.0, 0.0, 0.0, (True, True, True, False, False, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.n_cells > 18 * 6
    assert np.allclose(mesh.bounds, expected_bounds)
    top_points = mesh.points[np.isclose(mesh.points[:, 2], 0.0)]
    bottom_top_layer_points = mesh.points[np.isclose(mesh.points[:, 2], -0.10)]
    assert np.isclose(top_points[:, 0].max(), 0.05)
    assert np.isclose(top_points[:, 1].max(), 0.05)
    assert np.isclose(bottom_top_layer_points[:, 0].max(), 0.15)
    assert np.isclose(bottom_top_layer_points[:, 1].max(), 0.15)


def test_number_57_combines_double_chamfer_with_middle_cylinder():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N57", 0.0, 0.0, 0.0, (True, True, True, False, False, False))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells > 18 * 6


def test_number_61_combines_top_chamfer_with_middle_cylinder():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N61", 0.0, 0.0, 0.0, (True, True, True, True, False, False))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells > 9 * 5 + 9 * 6


def test_number_59_combines_y_chamfer_with_middle_cylinder():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N59", 0.0, 0.0, 0.0, (True, True, True, False, True, False))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells > 9 * 5 + 9 * 6


def test_number_63_support_removes_middle_layer_and_adds_vertical_cylinder():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N63", 0.0, 0.0, 0.0, (True, True, True, True, True, False))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells > 18 * 6


def test_number_56_removes_minus_x_face_and_adds_six_y_cylinders():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N56", 0.0, 0.0, 0.0, (True, True, False, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells == 18 * 6 + 6 * 26


def test_number_55_adds_a_vertical_middle_cylinder_to_number_56():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N55", 0.0, 0.0, 0.0, (True, True, False, True, True, False))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells == 12 * 6 + 7 * 26


def test_number_48_uses_two_rows_of_three_x_oriented_rollers_after_x_rotation():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N48", 0.0, 0.0, 0.0, (True, False, True, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells == 18 * 6 + 6 * 26


def test_dy_only_family_keeps_the_minus_z_roller_pattern_for_all_rotations():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    for rx, ry, rz in product((False, True), repeat=3):
        node = Node("NDY", 0.0, 0.0, 0.0, (True, False, True, rx, ry, rz))
        mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
        assert mesh is not None
        assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
        assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
        assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
        assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
        assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
        assert mesh.bounds[5] <= expected_bounds[5] + 1e-6


def test_number_40_places_the_four_spheres_exclusively_on_minus_x():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N40", 0.0, 0.0, 0.0, (True, False, False, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
    assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
    assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
    assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
    assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
    assert mesh.bounds[5] <= expected_bounds[5] + 1e-6


def test_dx_restrained_dy_dz_free_family_keeps_spheres_on_minus_x():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    for rx, ry, rz in product((False, True), repeat=3):
        node = Node("NDYDZ", 0.0, 0.0, 0.0, (True, False, False, rx, ry, rz))
        mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
        assert mesh is not None
        assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
        assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
        assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
        assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
        assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
        assert mesh.bounds[5] <= expected_bounds[5] + 1e-6


def test_number_32_is_number_48_rotated_90_degrees_around_z():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N32", 0.0, 0.0, 0.0, (False, True, True, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert np.allclose(mesh.bounds, expected_bounds)
    assert mesh.n_cells == 18 * 6 + 6 * 26


def test_dx_only_family_keeps_the_rotated_roller_pattern_for_all_rotations():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    for rx, ry, rz in product((False, True), repeat=3):
        node = Node("NDX", 0.0, 0.0, 0.0, (False, True, True, rx, ry, rz))
        mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
        assert mesh is not None
        assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
        assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
        assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
        assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
        assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
        assert mesh.bounds[5] <= expected_bounds[5] + 1e-6


def test_number_16_rotates_number_40_spheres_to_minus_z():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    node = Node("N16", 0.0, 0.0, 0.0, (False, False, True, True, True, True))
    mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
    assert mesh is not None
    assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
    assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
    assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
    assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
    assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
    assert mesh.bounds[5] <= expected_bounds[5] + 1e-6


def test_every_support_pattern_has_a_model_except_the_free_node():
    expected_bounds = (-0.15, 0.15, -0.15, 0.15, -0.30, 0.0)
    for supports in product((False, True), repeat=6):
        node = Node("N1", 0.0, 0.0, 0.0, supports)
        mesh = BatchedNodeRenderer._support_mesh(node, 0.05)
        if any(supports):
            assert mesh is not None
            assert mesh.bounds[0] >= expected_bounds[0] - 1e-6
            assert mesh.bounds[1] <= expected_bounds[1] + 1e-6
            assert mesh.bounds[2] >= expected_bounds[2] - 1e-6
            assert mesh.bounds[3] <= expected_bounds[3] + 1e-6
            assert mesh.bounds[4] >= expected_bounds[4] - 1e-6
            assert mesh.bounds[5] <= expected_bounds[5] + 1e-6
        else:
            assert mesh is None


def test_semirigid_indicator_requires_active_rotation_at_the_member_end():
    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")

    assert not has_semirigid_member_end(model.bars["B1"], "start")
    assert not has_semirigid_member_end(model.bars["B1"], "end")

    model.update_member_rotation_flexibility_percent("B1", (15, 0, 0, 0, 0, 0))
    assert has_semirigid_member_end(model.bars["B1"], "start")
    assert not has_semirigid_member_end(model.bars["B1"], "end")

    model.update_member_rotation_flexibility_percent("B1", (0, 0, 0, 0, 0, 25))
    assert not has_semirigid_member_end(model.bars["B1"], "start")
    assert has_semirigid_member_end(model.bars["B1"], "end")


def test_action_renderer_groups_repeated_action_geometry_into_few_actors():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    actions = ActionService(model)
    actions.add_member_distributed_force("B1", "Z", 5.0, 5.0, "Caso")
    actions.add_member_moment("B1", "Y", 2.0, "Caso")

    plotter = Plotter()
    actors, _positions, labels = ActionRenderer().render(plotter, model, "Caso")

    assert len(actors) == len(plotter.meshes) == 3
    assert len(labels) == 2
    assert max(mesh.n_cells for mesh, _options in plotter.meshes) > 1


def test_action_renderer_omits_zero_actions_and_their_identifiers():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    model.actions.update({
        "Carga zero distribuída": Action(
            "Carga zero distribuída", "member_distributed_force_Z", "B1", (0.0, 0.0), "Caso",
        ),
        "Momento zero": Action(
            "Momento zero", "member_moment_Y", "B1", (0.0,), "Caso",
        ),
        "Força nodal zero": Action(
            "Força nodal zero", "node_force_Z", "N1", (0.0,), "Caso",
        ),
        "Momento nodal zero": Action(
            "Momento nodal zero", "node_moment_X", "N1", (0.0,), "Caso",
        ),
    })

    plotter = Plotter()
    actors, positions, labels = ActionRenderer().render(plotter, model, "Caso")

    assert actors == []
    assert plotter.meshes == []
    assert positions.shape == (0, 3)
    assert labels == ()


def test_action_renderer_keeps_distributed_actions_with_one_zero_endpoint():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    model.add_node("N1", 0.0, 0.0, 0.0)
    model.add_node("N2", 5.0, 0.0, 0.0)
    model.add_bar("B1", "N1", "N2")
    model.actions["Carga variável"] = Action(
        "Carga variável", "member_distributed_force_Z", "B1", (0.0, 5.0), "Caso",
    )

    _actors, _positions, labels = ActionRenderer().render(Plotter(), model, "Caso")

    assert labels == ("0 kN/m", "5 kN/m")
