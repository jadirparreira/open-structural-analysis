from osa.model import StructuralModel


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
