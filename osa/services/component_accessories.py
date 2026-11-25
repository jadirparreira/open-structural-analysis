"""Accessory quantities supplied by component-specific providers."""
from __future__ import annotations

from collections import Counter

from osa.domain.node_components import base_plate_anchor_offsets


def _dimension(value, *, diameter=False, comma=False) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if diameter and "." not in text:
        text += ".0"
    return text.replace(".", ",") if comma else text


def base_plate_fastener_name(parameters):
    """The shared identity/fallback name used by takeoffs and detail labels."""
    diameter = parameters.get("diametro_mm", 16.0)
    identity = str(parameters.get("identificacao_fixador", "")).strip()
    if not identity:
        material = str(parameters.get("material_fixador", "SAE 1020")).strip() or "SAE 1020"
        if material.startswith("SAE "):
            material = "SAE" + material[4:]
        dimensions = [_dimension(diameter, diameter=True),
                      _dimension(parameters.get("comprimento_fixador_mm", 300.0))]
        if parameters.get("fixador") == "Gancho":
            dimensions.append(_dimension(parameters.get("perna_mm", 200.0)))
        identity = f"Barra Redonda Ø {' x '.join(dimensions)} {material}"
    return identity


def _base_plate_accessories(parameters):
    count = len(base_plate_anchor_offsets(parameters))
    diameter = parameters.get("diametro_mm", 16.0)
    identity = base_plate_fastener_name(parameters)
    nominal_diameter = _dimension(diameter, diameter=True, comma=True)
    return (
        (identity, count),
        (f"Porca Sextavada Ø {nominal_diameter}", count),
        (f"Arruela Lisa Ø {nominal_diameter}", count),
    )


# Additional component types can supply their own accessory descriptions/counts.
_COMPONENT_PROVIDERS = {"base_plate": _base_plate_accessories}


def component_accessory_rows(model) -> list[dict]:
    """Group matching final names across every applied component instance."""
    quantities = Counter()
    for node in model.nodes.values():
        component = node.component
        if component is None:
            continue
        provider = _COMPONENT_PROVIDERS.get(component.component_id)
        if provider is not None:
            for name, quantity in provider(dict(component.parameters)):
                quantities[name] += quantity
    return [{"name": name, "quantity": quantities[name]} for name in sorted(quantities, key=str.casefold)]
