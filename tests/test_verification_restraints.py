"""The verification length routine uses connected member geometry."""

from dataclasses import replace

import pytest

from osa.domain.member_axes import member_basis
from osa.model import StructuralModel
from osa.verification.elements import VerificationElement
from osa.verification.restraints import MemberChainRestraints, restraint_lengths


def chain(*, rotation=0):
    model = StructuralModel()
    for name, x in (("A", 0), ("C", 2), ("B", 6)):
        model.add_node(name, x, 0, 0)
    model.add_bar("B1", "A", "C")
    model.add_bar("B2", "C", "B")
    model.update_member_rotation("B1", rotation)
    model.update_member_rotation("B2", rotation)
    element = VerificationElement("group:B1|B2", "Grupo", ("B1", "B2"))
    return model, element


def test_collinear_segments_use_the_full_connected_element_length():
    model, element = chain()

    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m == pytest.approx(
        {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6},
    )
    assert values.issues == ()
    assert any("geométrica e simplificada" in note for note in values.notes)


def test_collinear_extension_outside_group_is_included_in_member_length():
    model, _element = chain()
    element = VerificationElement("bar:B2", "B2", ("B2",))

    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m == pytest.approx(
        {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6},
    )


def test_rigid_support_splits_only_its_local_direction():
    model, element = chain()
    model.update_node_supports("C", (False, True, False, False, False, False))

    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m["Ly"] == 4
    assert values.lengths_m["Lz"] == 6


def test_transverse_connected_bar_splits_only_its_local_direction():
    model, element = chain()
    model.add_node("D", 2, 3, 0)
    model.add_bar("BR", "C", "D")

    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m["Ly"] == 4
    assert values.lengths_m["Lz"] == 6
    assert values.modes["Ly"]["governing_interval_m"] == (2, 6)


def test_element_rotation_changes_the_local_direction_of_a_transverse_bar():
    model, element = chain(rotation=90)
    model.add_node("D", 2, 3, 0)
    model.add_bar("BR", "C", "D")

    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m["Ly"] == 6
    assert values.lengths_m["Lz"] == 4


def test_inclined_member_chain_still_uses_its_true_geometric_length():
    model, element = chain()
    axis = (1 / 3**0.5, 1 / 3**0.5, 1 / 3**0.5)
    for name, node in tuple(model.nodes.items()):
        model.nodes[name] = replace(
            node, x=node.x * axis[0], y=node.x * axis[1], z=node.x * axis[2],
        )
    # The original six metre chain is projected along a unit axis, so its
    # length remains six metres regardless of its global direction.
    values = MemberChainRestraints(model).lengths(element)

    assert values.lengths_m == pytest.approx(
        {"Ly": 6, "Lz": 6, "Lt": 6, "Lb": 6},
    )
    assert member_basis(model.nodes["A"], model.nodes["B"]) is not None


def test_shared_length_routine_reuses_its_cached_geometric_result():
    model, element = chain()
    first = restraint_lengths(model, element, [], {})
    repeated = restraint_lengths(model, element, [], {})

    assert repeated is first
    model.add_node("D", 2, 3, 0)
    model.add_bar("BR", "C", "D")
    updated = restraint_lengths(model, element, [], {})

    assert updated is not first
    assert updated.lengths_m["Ly"] == 4
    assert updated.lengths_m["Lz"] == 6
