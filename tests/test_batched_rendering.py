import numpy as np

from osa.commands import CommandSession
from osa.domain import Action
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
    batch = BatchedMemberRenderer().build(model, 0.05)

    assert len(batch.names) == 839
    assert batch.lines.n_cells == 839
    assert batch.faces.n_cells > len(batch.names)
    assert batch.edges.n_cells > len(batch.names)
    assert [mesh.n_cells for mesh in batch.axes] == [839, 839, 839]
    assert set(np.unique(batch.faces.cell_data["element_index"])) == set(range(839))
    assert set(np.unique(batch.lines.cell_data["element_index"])) == set(range(839))
    assert batch.faces.cell_data["rgb"].shape == (batch.faces.n_cells, 3)
    assert len(batch.outlines) == 839


def test_node_batch_keeps_spherical_markers_and_pick_identity():
    model = warehouse_model()
    batch = BatchedNodeRenderer().build(model, 0.05)

    assert len(batch.names) == 408
    assert batch.geometry.n_cells > len(batch.names)
    assert set(np.unique(batch.geometry.cell_data["element_index"])) == set(range(408))
    assert batch.geometry.cell_data["rgb"].shape == (batch.geometry.n_cells, 3)
    assert np.all(batch.geometry.cell_data["rgb"] == 0)
    assert batch.supports.n_cells == 10
    assert batch.label_positions.shape == (408, 3)


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
