"""Canonical named member groups used by memorial annotations."""

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
    """Return the named member groups used by the calculation memorial."""
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
