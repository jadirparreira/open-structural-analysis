"""Representation switches reuse geometry while keeping displaced details aligned."""

import os
from types import SimpleNamespace

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from osa.domain import AnalysisResult
from osa.model import StructuralModel
from osa.rendering.batched_renderer import BatchedMemberRenderer, prepare_scene_geometry
from osa.rendering.scene_batched import StructureScene
from osa.services.action_service import ActionService


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _model():
    model = StructuralModel()
    for index, point in enumerate(((0, 0, 0), (4, 2, 0), (4, 2, 3))):
        model.add_node(f"N{index}", *point)
    for index, (section, geometry) in enumerate((
        ("Barra Retangular", {"b": 100, "h": 200}), ("Tubular Circular", {"D": 100, "t": 3}),
    )):
        name = f"B{index}"
        model.add_bar(name, f"N{index}", f"N{index + 1}")
        model.update_bar_section(name, section)
        model.update_member_profile(name, name, geometry)
        model.update_member_rotation(name, 45)
        model.update_member_solid_section_offsets(name, (0.3, -0.2))
        model.update_member_releases(name, (True,) * 12)
        model.update_member_rotation_flexibility_percent(name, (15,) * 6)
    model.add_scene_view("Vista")
    model.set_scene_members_hidden({"B1"}, True)
    model.select_scene_view("Completo")
    return model


def _assert_indicators_match_rebuild(scene):
    renderer = BatchedMemberRenderer()
    renderer.position_indicators_with_section = scene._solid_members_visible
    expected = renderer.build(SimpleNamespace(
        bars={name: scene._model.bars[name] for name in scene._member_batch.names}, nodes=scene._model.nodes,
    ), scene._marker_radius_current)
    np.testing.assert_allclose(scene._member_batch.label_positions, expected.label_positions, atol=1e-12)
    np.testing.assert_allclose(scene._member_batch.section_offsets, expected.section_offsets, atol=1e-12)
    for actual, rebuilt in zip(
        (*scene._member_batch.axes, scene._member_batch.releases), (*expected.axes, expected.releases),
    ):
        np.testing.assert_allclose(actual.points, rebuilt.points, atol=1e-12)


@pytest.mark.parametrize("initial_solid", [False, True])
@pytest.mark.parametrize("view", ["Completo", "Vista"])
@pytest.mark.parametrize("prepared", [False, True])
def test_toggles_keep_actors_geometry_labels_and_scene_cache(qt_app, monkeypatch, initial_solid, view, prepared):
    model = _model()
    model.select_scene_view(view)
    scene = StructureScene()
    try:
        scene.set_solid_members_visible(initial_solid)
        geometry = prepare_scene_geometry(
            model, solid_members_visible=initial_solid, position_indicators_with_section=initial_solid,
        ) if prepared else None
        scene.render_model(model, prepared_geometry=geometry)
        scene.set_selection_highlight((("bar", "B0"),))
        batch = scene._member_batch
        source = scene._scene_member_source
        actors = (
            scene._member_face_actor, scene._member_edge_actor, scene._member_line_actor,
            scene._node_actor, scene._support_actor, scene._grid_actor, scene._release_actor,
            *scene._local_axis_actors,
        )
        faces, edges = batch.faces, batch.edges
        face_points, edge_points = faces.points.copy(), edges.points.copy()
        atlas = scene._label_overlay._groups["bar"].atlases
        camera = scene._camera_state()

        def unexpected_rebuild(*args, **kwargs):
            pytest.fail("A representation switch must not rebuild structural geometry or clear actors")

        monkeypatch.setattr(scene._member_renderer, "build", unexpected_rebuild)
        monkeypatch.setattr(scene._node_renderer, "build", unexpected_rebuild)
        with monkeypatch.context() as patch:
            patch.setattr(scene, "render_model", unexpected_rebuild)
            patch.setattr(scene.plotter, "clear", unexpected_rebuild)
            for solid in (not initial_solid, initial_solid, not initial_solid):
                scene.set_solid_members_visible(solid)
                assert scene._member_batch is batch
                assert scene._scene_member_source is source
                assert scene._member_face_actor.GetVisibility() == solid
                assert scene._member_line_actor.GetVisibility() == (not solid)
                assert scene._member_face_actor.GetPickable() == solid
                assert scene._label_overlay._groups["bar"].atlases is atlas
                assert scene._camera_state() == camera
                assert scene._selected_elements == (("bar", "B0"),)
                _assert_indicators_match_rebuild(scene)
                expected_springs = [
                    point for name in batch.names
                    for point in scene._elastic_support_overlay._member_end_positions(
                        model.bars[name], model.nodes, scene._node_marker_radius(), solid,
                    )
                ]
                np.testing.assert_allclose(scene._elastic_support_overlay._positions, expected_springs)
        assert actors == (
            scene._member_face_actor, scene._member_edge_actor, scene._member_line_actor,
            scene._node_actor, scene._support_actor, scene._grid_actor, scene._release_actor,
            *scene._local_axis_actors,
        )
        assert batch.faces is faces and batch.edges is edges
        np.testing.assert_array_equal(faces.points, face_points)
        np.testing.assert_array_equal(edges.points, edge_points)
        # Switching views afterwards must continue to reuse the complete source.
        monkeypatch.undo()
        monkeypatch.setattr(scene._member_renderer, "build", unexpected_rebuild)
        model.select_scene_view("Vista" if view == "Completo" else "Completo")
        scene.render_model(model)
        assert scene._scene_member_source is source
        _assert_indicators_match_rebuild(scene)
    finally:
        scene.close()


def test_toggle_flushes_pending_positioning_edits(qt_app):
    model = _model()
    scene = StructureScene()
    try:
        scene.render_model(model)
        for solid, offset in ((True, (0.6, 0.1)), (False, (-0.2, 0.0)), (True, (0.1, -0.4))):
            model.update_member_solid_section_offsets("B0", offset)
            scene.update_member_geometry("B0")
            scene.set_solid_members_visible(solid)
            assert not scene._member_update_timer.isActive()
            _assert_indicators_match_rebuild(scene)
        # An edit performed analytically must update the cached section offsets
        # even though its labels and axes have not moved yet.
        scene.set_solid_members_visible(False)
        model.update_member_solid_section_offsets("B0", (0.8, -0.3))
        scene.update_member_geometry("B0")
        scene._refresh_pending_member_update()
        scene.set_solid_members_visible(True)
        _assert_indicators_match_rebuild(scene)
    finally:
        scene.close()


def test_deformation_changes_representation_without_rebuilding_the_structure(qt_app, monkeypatch):
    model = _model()
    model.analysis_results = [AnalysisResult(model.revision, "Result", member_results={
        name: {"samples": [
            {"x": 0.0, "deflection_y": 0.0}, {"x": 1.0, "deflection_y": 0.01},
        ]} for name in model.bars
    })]
    scene = StructureScene()
    try:
        scene.render_model(model)
        scene.set_analysis_result("Result", "Deformação XYZ")
        scene.set_analysis_visible(True)
        faces = scene._member_face_actor

        def unexpected_build(*args, **kwargs):
            pytest.fail("Only the deformation overlay should be rebuilt")

        monkeypatch.setattr(scene._member_renderer, "build", unexpected_build)
        for solid in (True, False):
            previous = tuple(scene._result_actors)
            scene.set_solid_members_visible(solid)
            assert scene._member_face_actor is faces
            assert not scene._member_face_actor.GetVisibility()
            assert not scene._member_line_actor.GetVisibility()
            assert scene._result_actors
            assert tuple(scene._result_actors) != previous
            assert all(actor.GetVisibility() for actor in scene._result_actors)
            assert scene._result_layer_key[-1] == solid
    finally:
        scene.close()


def test_toggle_keeps_action_and_force_diagram_actors(qt_app, monkeypatch):
    model = _model()
    ActionService(model).add_member_distributed_force("B0", "Y", 2.0, 2.0, "Case")
    model.analysis_results = [AnalysisResult(model.revision, "Result", member_results={
        "B0": {"samples": [{"x": 0.0, "axial": 2.0}, {"x": 1.0, "axial": 2.0}]},
    })]
    scene = StructureScene()
    try:
        scene.render_model(model)
        scene.set_active_load_case("Case")
        scene.set_actions_visible(True)
        scene.set_analysis_result("Result", "Normal")
        scene.set_analysis_visible(True)
        actions, results = tuple(scene._action_actors), tuple(scene._result_actors)
        assert actions and results

        def unexpected_render(*args, **kwargs):
            pytest.fail("Actions and force diagrams are independent from the solid representation")

        monkeypatch.setattr(scene._action_renderer, "render", unexpected_render)
        monkeypatch.setattr(scene._result_renderer, "render", unexpected_render)
        for solid in (True, False):
            scene.set_solid_members_visible(solid)
            assert tuple(scene._action_actors) == actions
            assert tuple(scene._result_actors) == results
            assert all(actor.GetVisibility() for actor in (*actions, *results))
        scene.set_analysis_visible(False)
        scene.set_analysis_visible(True)
        assert tuple(scene._result_actors) == results
    finally:
        scene.close()


def test_toggle_keeps_reveal_preview_and_its_selection_mode(qt_app, monkeypatch):
    model = _model()
    model.select_scene_view("Vista")
    scene = StructureScene()
    try:
        scene.render_model(model)
        scene.set_scene_selection_mode("reveal")
        preview = scene._reveal_preview_batch
        preview_faces = scene._reveal_preview_face_actor

        def unexpected_build(*args, **kwargs):
            pytest.fail("An existing reveal preview should be reused")

        monkeypatch.setattr(scene._member_renderer, "build", unexpected_build)
        for solid in (True, False):
            scene.set_solid_members_visible(solid)
            assert scene._scene_selection_mode == "reveal"
            assert scene._reveal_preview_batch is preview
            assert scene._reveal_preview_face_actor is preview_faces
            assert preview_faces.GetVisibility() == solid
            assert scene._reveal_preview_line_actor.GetVisibility() == (not solid)
            assert scene._member_batch.names == ("B0",)
    finally:
        scene.close()
