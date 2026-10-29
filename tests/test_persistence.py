import json

import pytest

from osa.domain import ActionDefinition, ActionGroup, AnalysisResult
from osa.domain.errors import DuplicateMemberError, DuplicateNodeCoordinatesError
from osa.model import ReferenceAxis, StructuralModel
from osa.persistence import ProjectRepository
from osa.services import ThumbnailService


@pytest.mark.parametrize("first, second", [
    ((1.9e-9, 0, 0), (2.1e-9, 0, 0)),
    ((-1.9e-9, 0, 0), (-2.1e-9, 0, 0)),
    ((0, 0, 0), (1e-9, 1e-9, 1e-9)),
])
def test_loading_rejects_near_duplicate_nodes_without_replacing_current_model(first, second):
    model = StructuralModel()
    model.add_node("Existing", 10, 10, 10)
    data = {
        "format": "open-structural-analysis/v2",
        "nodes": [{"name": name, "x": point[0], "y": point[1], "z": point[2]}
                  for name, point in (("N1", first), ("N2", second))],
    }

    with pytest.raises(DuplicateNodeCoordinatesError):
        model.load_dict(data)

    assert tuple(model.nodes) == ("Existing",)


def test_loading_accepts_distinct_nodes_in_the_same_spatial_cell_and_large_coordinates():
    model = StructuralModel()
    data = {
        "format": "open-structural-analysis/v2",
        "nodes": [
            {"name": "N1", "x": 0, "y": 0, "z": 0},
            {"name": "N2", "x": 1.5e-9, "y": 0, "z": 0},
            {"name": "N3", "x": 1e308, "y": 0, "z": 0},
        ],
    }
    model.load_dict(data)

    assert len(model.nodes) == 3


def test_loading_rejects_reverse_duplicate_members_with_batch_validation():
    model = StructuralModel()
    data = {
        "format": "open-structural-analysis/v2",
        "nodes": [{"name": "N1", "x": 0, "y": 0, "z": 0},
                  {"name": "N2", "x": 1, "y": 0, "z": 0}],
        "members": [{"name": "B1", "start_node": "N1", "end_node": "N2"},
                    {"name": "B2", "start_node": "N2", "end_node": "N1"}],
    }
    with pytest.raises(DuplicateMemberError):
        model.load_dict(data)


@pytest.mark.parametrize("preview_first", [True, False])
def test_preview_loading_preserves_unicode_and_supports_arbitrary_field_order(tmp_path, preview_first):
    preview = {"format": "png", "data": "prévia"}
    data = {"thumbnail": preview, "members": [{"name": "B1"}]} if preview_first else {
        "members": [{"name": "B1"}], "thumbnail": preview,
    }
    path = tmp_path / "preview.osa"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert ProjectRepository().load_thumbnail(path) == "prévia"


def test_saved_results_remain_available_after_source_replacement_and_resave(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")
    node_values = {"DX": 0.25, "nested": {"value": 2.5}}
    member_values = {"samples": [{"x": 0.0, "axial": 25.5}], "end_a": {"force": 25.5}}
    model.analysis_results = [AnalysisResult(model.revision, "Combinação 01", {"N1": node_values}, {"B1": member_values})]
    path = tmp_path / "results.osa"
    model.save(path)
    restored = StructuralModel()
    restored.load(path)
    path.unlink()

    result = restored.analysis_results[0]
    assert isinstance(result.member_results["B1"], dict)
    assert result.member_results["B1"] == member_values
    assert result.node_results["N1"] == node_values
    result.node_results["N1"]["DX"] = 0.5
    restored.save(path)
    reloaded = StructuralModel()
    reloaded.load(path)

    assert reloaded.analysis_results[0].node_results["N1"]["DX"] == 0.5
    assert reloaded.analysis_results[0].member_results["B1"] == member_values


def test_member_calculation_property_overrides_round_trip_and_legacy_models_default_to_auto(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 0, 0, 2)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_calculation_property("B1", "Lb", 1.25)
    model.update_bar_calculation_property("B1", "Cb", 1.7)

    path = tmp_path / "calculation-properties.osa"
    model.save(path)
    restored = StructuralModel()
    restored.load(path)

    assert dict(restored.bars["B1"].calculation_property_overrides) == {
        "Lb": 1.25, "Cb": 1.7,
    }
    legacy = {
        "format": "open-structural-analysis/v2",
        "nodes": [{"name": "A", "x": 0, "y": 0, "z": 0},
                  {"name": "B", "x": 0, "y": 0, "z": 1}],
        "members": [{"name": "M1", "start_node": "A", "end_node": "B"}],
    }
    restored.load_dict(legacy)
    assert restored.bars["M1"].calculation_property_overrides == ()


def test_copying_and_serializing_deferred_results_does_not_expand_live_records():
    import copy

    from osa.persistence.deferred_result import DeferredResultMap

    values = DeferredResultMap({"B1": '{"samples": [{"x": 0, "axial": 5}]}', "B2": "null"})
    result = AnalysisResult(1, "Combinação 01", {}, values)
    model = StructuralModel()
    model.analysis_results = [result]
    copied = copy.deepcopy(result)
    payload = json.loads(json.dumps(model.as_dict()))

    assert values._encoded == {"B1", "B2"}
    assert copied.member_results["B1"] == {"samples": [{"x": 0, "axial": 5}]}
    assert payload["results"][0]["member_results"]["B2"] is None


def test_round_trip_preserves_supports_material_section_and_profile(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0); model.add_node("N2", 1, 0, 0)
    model.update_node_supports("N1", (True, True, True, False, False, False))
    model.add_bar("B1", "N1", "N2")
    model.update_member_rotation_flexibility_percent("B1", (10, 20, 30, 40, 50, 60))
    model.update_bar_material("B1", "Aço Estrutural", model.materials["Aço Estrutural"])
    model.update_bar_section("B1", "W Laminado")
    model.update_member_profile("B1", "W 150 x 13.0", {"d": 148, "bf": 100})
    model.update_member_section_mirrored("B1", True)
    path = tmp_path / "model.osa.json"
    model.save(path)
    restored = StructuralModel(); restored.load(path)
    assert restored.nodes["N1"].supports == model.nodes["N1"].supports
    assert restored.bars["B1"].rotation_flexibility_percent == (10, 20, 30, 40, 50, 60)
    assert restored.bars["B1"].section_mirrored is True
    assert restored.bars["B1"] == model.bars["B1"]


def test_project_thumbnail_is_persisted_without_affecting_model_round_trip(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 4, 0, 0)
    model.add_bar("B1", "N1", "N2")
    thumbnail = ThumbnailService.generate(model)
    path = tmp_path / "preview.osa"

    repository = ProjectRepository()
    repository.save(model, path, thumbnail=thumbnail)

    restored = StructuralModel()
    repository.load(restored, path)
    assert restored.as_dict() == model.as_dict()
    assert repository.load_thumbnail(path) == thumbnail


def test_v1_files_are_still_readable():
    data = {
        "format": "open-structural-analysis/v1",
        "nodes": [
            {"name": "N1", "x": 0, "y": 0, "z": 0, "supports": [True, True, True, False, False, False]},
            {"name": "N2", "x": 1, "y": 0, "z": 0},
        ],
        "bars": [{"name": "B1", "start_node": "N1", "end_node": "N2", "section": "W Laminado"}],
    }
    model = StructuralModel(); model.load_dict(data)
    assert model.nodes["N1"].supports[0]
    assert model.bars["B1"].section == "W Laminado"


def test_legacy_v2_materials_are_converted_to_kn_units_when_opened():
    data = {
        "format": "open-structural-analysis/v2",
        "nodes": [
            {"name": "N1", "x": 0, "y": 0, "z": 0},
            {"name": "N2", "x": 1, "y": 0, "z": 0},
        ],
        "members": [{
            "name": "B1", "start_node": "N1", "end_node": "N2",
            "material_values": [200.0, 76.9, 0.3, 7850.0],
        }],
        "materials": {
            "Aço legado": {"type": "Aço", "values": [200.0, 76.9, 0.3, 7850.0]},
        },
    }

    model = StructuralModel()
    model.load_dict(data)

    expected = (200000000.0, 76900000.0, 0.3, 76.9822025)
    assert model.materials["Aço legado"] == expected
    assert model.bars["B1"].material_values == expected


def test_round_trip_preserves_reference_axes(tmp_path):
    model = StructuralModel()
    model.set_reference_axes({
        "X": (ReferenceAxis("A", 5.0),),
        "Y": (ReferenceAxis("1", -2.5),),
    })
    path = tmp_path / "axes.osa.json"
    model.save(path)

    restored = StructuralModel()
    restored.load(path)

    assert restored.axes == model.axes


def test_round_trip_preserves_action_groups(tmp_path):
    model = StructuralModel()
    model.add_action_group(ActionGroup(
        "PP + AP + AV",
        (
            ActionDefinition("Peso próprio", "PP"),
            ActionDefinition("Ação permanente", "AP"),
            ActionDefinition("Ação variável", "AV"),
        ),
    ))
    model.add_action_group(ActionGroup(
        "PP+TESTE",
        (ActionDefinition("Vento", "V"),),
    ))
    model.set_action_group_alias("PP+AP+AV+4V", "PP+TESTE")
    model.set_selected_action_group("PP+TESTE")
    path = tmp_path / "actions.osa.json"
    model.save(path)
    restored = StructuralModel()
    restored.load(path)
    assert restored.action_groups == model.action_groups
    assert restored.selected_action_group == "PP+TESTE"
    assert restored.action_group_aliases == {"PP+AP+AV+4V": "PP+TESTE"}
