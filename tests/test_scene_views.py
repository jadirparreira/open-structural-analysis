"""Scene views preserve independent visibility without changing structural data."""

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.rendering.scene_batched import StructureScene


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _model() -> StructuralModel:
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_node("N3", 2, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.add_bar("B2", "N2", "N3")
    return model


def test_scene_views_round_trip_with_independent_hidden_members(tmp_path):
    model = _model()
    structural_revision = model.revision
    model.add_scene_view("Esquerda")
    model.set_scene_members_hidden({"B1"}, True)
    model.add_scene_view("Direita")
    model.set_scene_members_hidden({"B2"}, True)

    path = tmp_path / "scene-views.osa"
    model.save(path)
    restored = StructuralModel()
    restored.load(path)

    assert restored.active_scene_view == "Direita"
    assert restored.scene_views == {
        "Completo": set(), "Esquerda": {"B1"}, "Direita": {"B2"},
    }
    assert set(restored.bars) == {"B1", "B2"}
    assert model.revision == structural_revision

    restored.set_scene_members_hidden({"B2"}, False)
    assert restored.scene_views["Esquerda"] == {"B1"}
    restored.select_scene_view("Esquerda")
    restored.show_all_scene_members()
    assert restored.scene_views["Esquerda"] == set()


def test_hidden_nodes_follow_all_connected_members():
    model = _model()
    model.add_scene_view("Vista")
    scene = SimpleNamespace(_model=model)
    model.set_scene_members_hidden({"B1"}, True)
    hidden = StructureScene._scene_hidden_members(scene)
    assert StructureScene._scene_visible_node_names(scene, hidden) == {"N2", "N3"}
    model.set_scene_members_hidden({"B2"}, True)
    hidden = StructureScene._scene_hidden_members(scene)
    assert StructureScene._scene_visible_node_names(scene, hidden) == set()


def test_split_member_keeps_its_view_visibility():
    model = _model()
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B1"}, True)
    model.split_bar("B1", ("N4",), ("B1a", "B1b"))
    assert model.scene_views["Vista"] == {"B1a", "B1b"}


def test_scene_renders_only_visible_members_and_previews_hidden_ones(qt_app):
    model = _model()
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B1"}, True)
    scene = StructureScene()
    scene.render_model(model)
    assert scene._member_batch.names == ("B2",)
    assert scene._node_batch.names == ("N2", "N3")

    targets = scene._pick_projection_data()[3]
    selectable = scene._pick_projection_data()[6]
    assert not bool(dict(zip(targets, selectable))[("bar", "B1")])

    scene.set_scene_selection_mode("reveal")
    assert scene._reveal_preview_line_actor is not None
    assert scene._reveal_preview_line_actor.GetProperty().GetOpacity() == pytest.approx(0.7)
    targets = scene._pick_projection_data()[3]
    selectable = scene._pick_projection_data()[6]
    assert not bool(dict(zip(targets, selectable))[("bar", "B2")])
    assert bool(dict(zip(targets, selectable))[("bar", "B1")])

    scene.set_scene_selection_mode(None)
    model.set_scene_members_hidden({"B2"}, True)
    scene.render_model(model)
    assert scene._member_batch.names == ()
    assert scene._node_batch.names == ()

    model.select_scene_view("Completo")
    scene.render_model(model)
    assert scene._member_batch.names == ("B1", "B2")
    assert scene._node_batch.names == ("N1", "N2", "N3")
    scene.close()
