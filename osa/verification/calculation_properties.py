"""Resolve user supplied calculation properties for member checks."""

from __future__ import annotations


def calculation_property(model, element, name: str, default: float | None) -> float | None:
    """Return one consistent override for a bar or verification group.

    A grouped verification element must use the same manual override on every
    member. This prevents a group from silently applying one member's value to
    the rest of the chain.
    """
    values = [
        dict(model.bars[member_name].calculation_property_overrides).get(name)
        for member_name in element.member_names
    ]
    specified = [value for value in values if value is not None]
    if not specified:
        return None if default is None else float(default)
    if len(specified) != len(values) or any(value != specified[0] for value in specified[1:]):
        raise ValueError(
            f"A propriedade {name} tem valores manuais diferentes no grupo; "
            "aplique o mesmo valor a todas as barras do elemento."
        )
    return float(specified[0])
