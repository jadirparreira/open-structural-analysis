"""Reusable structural model builders for benchmark cases."""

from __future__ import annotations

from osa.model import StructuralModel


def _configure_member(model: StructuralModel, name: str, width_mm: float, height_mm: float) -> None:
    model.update_bar_material(name, "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section(name, "Retangular")
    model.update_member_profile(
        name,
        f"RET {width_mm:g} x {height_mm:g}",
        {"b": width_mm, "h": height_mm},
    )


def cantilever_model(
    *,
    length_m: float = 2.0,
    width_mm: float = 100.0,
    height_mm: float = 200.0,
) -> StructuralModel:
    """Create a two-node, fully fixed-base cantilever for a benchmark."""
    model = StructuralModel()
    model.add_node("A", 0.0, 0.0, 0.0)
    model.add_node("B", 0.0, 0.0, length_m)
    model.add_bar("B1", "A", "B")
    model.update_node_supports("A", (True,) * 6)
    _configure_member(model, "B1", width_mm, height_mm)
    return model


def segmented_cantilever_model(
    member_count: int,
    *,
    length_m: float = 2.0,
    width_mm: float = 100.0,
    height_mm: float = 200.0,
) -> StructuralModel:
    """Create a cantilever split into equal frame members."""
    if member_count < 1:
        raise ValueError("member_count must be positive")

    model = StructuralModel()
    for index in range(member_count + 1):
        model.add_node(f"N{index}", 0.0, 0.0, length_m * index / member_count)
    for index in range(member_count):
        name = f"B{index + 1}"
        model.add_bar(name, f"N{index}", f"N{index + 1}")
        _configure_member(model, name, width_mm, height_mm)
    model.update_node_supports("N0", (True,) * 6)
    return model
