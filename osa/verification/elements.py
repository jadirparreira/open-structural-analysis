"""Canonical element list used by model verification."""

from __future__ import annotations

from dataclasses import dataclass

from osa.domain import StructuralModel


@dataclass(frozen=True, slots=True)
class VerificationElement:
    key: str
    name: str
    member_names: tuple[str, ...]

    @property
    def is_group(self) -> bool:
        return len(self.member_names) > 1


def verification_elements(model: StructuralModel) -> tuple[VerificationElement, ...]:
    """Return each standalone bar and verification group exactly once."""
    grouped_names: set[str] = set()
    elements: list[VerificationElement] = []
    for group in model.verification_element_groups:
        members = tuple(name for name in group["members"] if name in model.bars)
        if len(members) < 2:
            continue
        grouped_names.update(members)
        identity = ", ".join(members)
        custom_name = str(group.get("name", "")).strip()
        display_name = f"{custom_name} ({identity})" if custom_name else identity
        elements.append(VerificationElement(f"group:{'|'.join(members)}", display_name, members))

    for member_name in model.bars:
        if member_name in grouped_names:
            continue
        custom_name = model.verification_element_names.get(member_name, "").strip()
        display_name = f"{custom_name} ({member_name})" if custom_name else member_name
        elements.append(VerificationElement(f"bar:{member_name}", display_name, (member_name,)))
    return tuple(elements)


def verification_element_key(model: StructuralModel, member_names) -> str | None:
    """Resolve a complete selected element/group to its stable result key."""
    names = tuple(member_names)
    if len(names) == 1:
        group = model.verification_group_for(names[0])
        return None if group is not None else f"bar:{names[0]}"
    for group in model.verification_element_groups:
        members = tuple(group["members"])
        if len(names) == len(members) and set(names) == set(members):
            return f"group:{'|'.join(members)}"
    return None
