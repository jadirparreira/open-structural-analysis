import pytest

from osa.model import StructuralModel


def test_model_round_trip(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 5, 0, 0)
    model.add_bar("B1", "N1", "N2")
    path = tmp_path / "frame.osa.json"
    model.save(path)
    loaded = StructuralModel()
    loaded.load(path)
    assert loaded.as_dict() == model.as_dict()


def test_node_with_bar_cannot_be_removed():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")
    with pytest.raises(ValueError, match="Remova-as primeiro"):
        model.remove_node("N1")


def test_bar_requires_distinct_existing_nodes():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    with pytest.raises(ValueError):
        model.add_bar("B1", "N1", "N1")


def test_rigid_bar_uses_node_pair_as_identity_and_round_trips(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    rigid = model.add_rigid_bar("N1", "N2")
    assert rigid.name == "N1-N2"
    path = tmp_path / "rigid.osa.json"
    model.save(path)
    loaded = StructuralModel()
    loaded.load(path)
    assert loaded.rigid_bars == model.rigid_bars


def test_member_solid_face_offsets_are_visual_and_round_trip(tmp_path):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 5, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.update_member_solid_face_offsets("B1", (0.25, 0.4))

    assert model.bars["B1"].solid_face_offsets == (0.25, 0.4)
    path = tmp_path / "solid-offsets.osa.json"
    model.save(path)
    loaded = StructuralModel()
    loaded.load(path)
    assert loaded.bars["B1"].solid_face_offsets == (0.25, 0.4)


def test_member_solid_face_offsets_accept_signed_values():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")

    member = model.update_member_solid_face_offsets("B1", (0.1, -0.1))

    assert member.solid_face_offsets == (0.1, -0.1)


def test_node_with_rigid_bar_cannot_be_removed():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_rigid_bar("N1", "N2")
    with pytest.raises(ValueError, match="Remova-as primeiro"):
        model.remove_node("N1")


@pytest.mark.parametrize(
    ("entered", "expected"),
    ((0, 0), (179, 179), (180, 180), (359, 359), (360, 0), (721, 1), (-1, 359), (-361, 359)),
)
def test_member_rotation_is_normalized_to_one_full_turn(entered, expected):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")

    member = model.update_member_rotation("B1", entered)

    assert member.rotation == expected
