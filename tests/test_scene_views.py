"""Scene views preserve independent visibility without changing structural data."""

import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from osa.model import StructuralModel
from osa.rendering.batched_renderer import prepare_scene_geometry
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


@pytest.mark.parametrize("prepared", [False, True])
@pytest.mark.parametrize("initial_view", ["Completo", "Vista"])
def test_switches_reuse_geometry_including_when_opened_in_a_filtered_view(qt_app, monkeypatch, prepared, initial_view):
    model = _model()
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B1"}, True)
    model.select_scene_view(initial_view)
    scene = StructureScene()
    try:
        geometry = prepare_scene_geometry(model) if prepared else None
        scene.render_model(model, prepared_geometry=geometry)
        source = scene._scene_member_source
        camera = scene._camera_state()

        def unexpected_build(*args, **kwargs):
            pytest.fail("Changing a view must reuse the prepared member geometry")

        monkeypatch.setattr(scene._member_renderer, "build", unexpected_build)
        for name in ("Vista", "Completo", "Vista", "Completo"):
            model.select_scene_view(name)
            scene.render_model(model)
            assert scene._member_batch.names == (("B2",) if name == "Vista" else ("B1", "B2"))
            assert scene._scene_member_source is source
            assert scene._camera_state() == camera
        model.select_scene_view("Vista")
        model.set_scene_members_hidden({"B2"}, True)
        scene.render_model(model)
        assert scene._member_batch.names == ()
        assert scene._node_batch.names == ()
        model.show_all_scene_members()
        scene.render_model(model)
        assert scene._member_batch.names == ("B1", "B2")
    finally:
        scene.close()


def test_view_geometry_is_invalidated_after_edits_to_hidden_members(qt_app):
    model = _model()
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B1"}, True)
    scene = StructureScene()
    try:
        scene.render_model(model)
        source = scene._scene_member_source
        model.update_node("N1", -2.0, 1.0, 0.0)
        model.update_member_color("B1", "#ff0000")
        # The displayed member is unchanged, but the complete source is stale.
        scene.render_model(model)
        model.select_scene_view("Completo")
        scene.render_model(model)
        assert scene._scene_member_source is not source
        np.testing.assert_allclose(scene._member_batch.lines.points[0], (-2.0, 1.0, 0.0))
        np.testing.assert_array_equal(scene._member_batch.lines.cell_data["rgb"][0], (255, 0, 0))
        scene.set_solid_members_visible(True)
        model.select_scene_view("Vista")
        scene.render_model(model)
        assert scene._member_batch.names == ("B2",)
    finally:
        scene.close()


def test_scene_switch_keeps_incremental_edits_to_the_complete_batch(qt_app, monkeypatch):
    model = _model()
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B2"}, True)
    model.select_scene_view("Completo")
    scene = StructureScene()
    try:
        scene.render_model(model)
        model.update_node("N1", -1.0, 0.0, 0.0)
        model.update_member_color("B1", "#ff0000")
        scene.refresh_model_changes(model)

        def unexpected_build(*args, **kwargs):
            pytest.fail("The complete batch already contains the incremental edits")

        monkeypatch.setattr(scene._member_renderer, "build", unexpected_build)
        for name in ("Vista", "Completo"):
            model.select_scene_view(name)
            scene.render_model(model)
            np.testing.assert_allclose(scene._member_batch.lines.points[0], (-1.0, 0.0, 0.0))
            np.testing.assert_array_equal(scene._member_batch.lines.cell_data["rgb"][0], (255, 0, 0))
    finally:
        scene.close()


def test_solid_silhouettes_are_only_prepared_when_they_are_visible(qt_app, monkeypatch):
    model = _model()
    model.update_bar_section("B1", "Tubular Circular")
    model.update_member_profile("B1", "T", {"D": 100, "t": 3})
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B2"}, True)
    scene = StructureScene()
    try:
        with monkeypatch.context() as patch:
            def unexpected_silhouette(*args, **kwargs):
                pytest.fail("A line view does not need a solid silhouette")

            patch.setattr(scene._member_renderer, "silhouette_mesh", unexpected_silhouette)
            scene.render_model(model)
            model.select_scene_view("Completo")
            scene.render_model(model)
            assert scene._member_silhouette_actor is None
        scene.set_solid_members_visible(True)
        assert scene._member_silhouette_actor is not None
        assert scene._member_silhouette_actor.GetVisibility()
        model.select_scene_view("Vista")
        scene.render_model(model)
        assert scene._member_silhouette_actor is not None
        assert scene._member_silhouette_actor.GetVisibility()
    finally:
        scene.close()
