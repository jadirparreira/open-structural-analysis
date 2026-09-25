from osa.domain import ActionDefinition, ActionGroup
from osa.model import ReferenceAxis, StructuralModel


def test_round_trip_preserves_supports_material_section_and_profile(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0); model.add_node("N2", 1, 0, 0)
    model.update_node_supports("N1", (True, True, True, False, False, False))
    model.add_bar("B1", "N1", "N2")
    model.update_bar_material("B1", "Aço Estrutural", model.materials["Aço Estrutural"])
    model.update_bar_section("B1", "W Laminado")
    model.update_member_profile("B1", "W 150 x 13.0", {"d": 148, "bf": 100})
    path = tmp_path / "model.osa.json"
    model.save(path)
    restored = StructuralModel(); restored.load(path)
    assert restored.nodes["N1"].supports == model.nodes["N1"].supports
    assert restored.bars["B1"] == model.bars["B1"]


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
