"""Node edits must not introduce geometry finer than a millimetre."""

import pytest

from osa.domain.errors import DuplicateNodeCoordinatesError
from osa.model import StructuralModel
from osa.services import ModelService


def test_noisy_vertical_member_is_normalized_upwards():
    model = StructuralModel()
    model.add_node("N1", 9.9, 18.9, 6.12)
    model.add_node("N2", 9.900003814697273, 18.9, 3.06)
    model.add_bar("B1", "N1", "N2")

    assert ModelService(model).normalize_member_directions() == ("B1",)
    member = model.bars["B1"]
    start, end = model.nodes[member.start_node], model.nodes[member.end_node]
    assert (start.x, start.y) == (end.x, end.y) == (9.9, 18.9)
    assert (start.z, end.z) == (3.06, 6.12)


def test_node_creation_and_edits_round_signed_coordinates_and_keep_one_millimetre():
    model = StructuralModel()
    node = model.add_node("N1", 1.2346, -2.3456, -0.0001)
    assert (node.x, node.y, node.z) == (1.235, -2.346, 0.0)
    node = model.add_node("N2", 1.236, -2.346, 0)
    assert node.x - model.nodes["N1"].x == pytest.approx(0.001)
    node = model.update_node("N2", 3.4567, -4.5678, 5.6789)
    assert (node.x, node.y, node.z) == (3.457, -4.568, 5.679)
    model.update_nodes_coordinates({"N2": (6.7891, -7.8912, 8.9123)})
    node = model.nodes["N2"]
    assert (node.x, node.y, node.z) == (6.789, -7.891, 8.912)


def test_collisions_are_checked_after_rounding_and_leave_model_unchanged():
    model = StructuralModel()
    model.add_node("N1", 3.6, 5.1, 3.06)
    model.add_node("N2", 9.9, 5.1, 3.06)
    before = model.as_dict()
    for operation in (
        lambda: model.add_node("N3", 3.600003814697269, 5.1, 3.06),
        lambda: model.update_node("N2", 3.600003814697269, 5.1, 3.06),
        lambda: model.update_nodes_coordinates({"N2": (3.600003814697269, 5.1, 3.06)}),
    ):
        with pytest.raises(DuplicateNodeCoordinatesError):
            operation()
        assert model.as_dict() == before


def test_split_thirds_and_copy_obey_millimetre_precision():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 2, 0)
    model.add_bar("B1", "N1", "N2")
    service = ModelService(model)
    service.split_member("B1", 3)
    assert (model.nodes["N3"].x, model.nodes["N3"].y) == (0.333, 0.667)
    assert (model.nodes["N4"].x, model.nodes["N4"].y) == (0.667, 1.333)
    nodes, _members = service.copy_elements((), ("B1",), (0, 0, 1.2346))
    assert {model.nodes[name].z for name in nodes} == {1.235}
    assert service.copy_elements((), ("B1",), (0, 0, 1.2345999)) == ((), ())


def test_diagonal_split_can_be_repeated_and_joined_after_rounding():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 2, 0)
    model.add_bar("B1", "N1", "N2")
    service = ModelService(model)
    service.split_member_at_point("B1", (1 / 3, 2 / 3, 0))
    service.split_member_at_point("B2", (2 / 3, 4 / 3, 0))
    assert len(model.bars) == 3
    joined = service.join_selected_members(tuple(model.bars))
    assert (joined.start_node, joined.end_node) == ("N1", "N2")
    assert tuple(model.nodes) == ("N1", "N2")


def test_join_still_rejects_a_full_millimetre_bend():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 1, 0.001, 0)
    model.add_node("N3", 2, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.add_bar("B2", "N2", "N3")
    before = model.as_dict()
    with pytest.raises(ValueError, match="colineares"):
        ModelService(model).join_members("B1", "B2")
    assert model.as_dict() == before


@pytest.mark.parametrize("length, parts", [(0.001, 3), (0.002, 8)])
def test_split_rejects_collapsed_segments_before_mutating(length, parts):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", length, 0, 0)
    model.add_bar("B1", "N1", "N2")
    before = model.as_dict()
    with pytest.raises(ValueError):
        ModelService(model).split_member("B1", parts)
    assert model.as_dict() == before


def test_loading_legacy_coordinates_does_not_silently_collapse_members():
    model = StructuralModel()
    model.load_dict({
        "format": "open-structural-analysis/v2",
        "nodes": [
            {"name": "N1", "x": 9.9, "y": 11.900000190734861, "z": 6.12},
            {"name": "N2", "x": 9.9, "y": 11.899999122619676, "z": 6.12},
        ],
        "members": [{"name": "B1", "start_node": "N1", "end_node": "N2"}],
    })
    assert model.nodes["N1"].y == 11.900000190734861
    assert model.nodes["N2"].y == 11.899999122619676
    assert len(model.bars) == 1
    before = model.as_dict()
    with pytest.raises(ValueError, match="comprimento zero"):
        ModelService(model).copy_elements((), ("B1",), (0, 0, 1))
    assert model.as_dict() == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_rounding_still_rejects_nonfinite_coordinates(value):
    model = StructuralModel()
    with pytest.raises(ValueError, match="finitos"):
        model.add_node("N1", value, 0, 0)
    assert not model.nodes
