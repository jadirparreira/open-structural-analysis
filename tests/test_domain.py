import pytest

from osa.domain.errors import DuplicateMemberError, DuplicateNodeCoordinatesError
from osa.model import StructuralModel


def test_duplicate_coordinates_are_rejected_from_model_api():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    with pytest.raises(DuplicateNodeCoordinatesError):
        model.add_node("N2", 0, 0, 0)


def test_reverse_duplicate_member_is_rejected():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0, 0)
    model.add_bar("B1", "N1", "N2")
    with pytest.raises(DuplicateMemberError):
        model.add_bar("B2", "N2", "N1")


def test_profile_geometry_belongs_to_each_member():
    model = StructuralModel()
    for name, x in (("N1", 0), ("N2", 1), ("N3", 2)):
        model.add_node(name, x, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.add_bar("B2", "N2", "N3")
    model.update_member_profile("B1", "W 150 x 13.0", {"d": 148.0})
    model.update_member_profile("B2", "W 200 x 15.0", {"d": 200.0})
    assert model.bars["B1"].geometry_dict()["d"] == 148.0
    assert model.bars["B2"].geometry_dict()["d"] == 200.0
