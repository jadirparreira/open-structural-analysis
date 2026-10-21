"""Build calculation memorial inputs without running member checks."""

from __future__ import annotations

import logging
from math import sqrt

from osa.sections.contours import polygon_properties, w_contour_points
from osa.verification.elements import VerificationElement, verification_elements
from osa.verification.restraints import restraint_lengths

logger = logging.getLogger(__name__)


def _plastic_modulus(points, axis: int, centroid: float) -> float:
    """Integrate the section plastic modulus about a symmetric axis."""
    def clip(positive: bool):
        output = []
        previous = points[-1]
        previous_value = previous[axis] - centroid
        previous_inside = previous_value >= -1e-10 if positive else previous_value <= 1e-10
        for current in points:
            current_value = current[axis] - centroid
            current_inside = current_value >= -1e-10 if positive else current_value <= 1e-10
            if current_inside != previous_inside:
                fraction = previous_value / (previous_value - current_value)
                output.append(tuple(a + fraction * (b - a) for a, b in zip(previous, current)))
            if current_inside:
                output.append(current)
            previous, previous_value, previous_inside = current, current_value, current_inside
        return output

    modulus = 0.0
    for positive in (False, True):
        polygon = clip(positive)
        if len(polygon) >= 3:
            area, cy, cz, *_ = polygon_properties(polygon)
            modulus += area * abs((cy, cz)[axis] - centroid)
    return modulus


def _w_properties(member) -> dict[str, float]:
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        return float(geometry.get(name, geometry.get(f"{name}_mm")))

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    radius = float(geometry.get("r", geometry.get("r_mm", 10.0)))
    points = w_contour_points(d, bf, tw, tf, radius)
    area_mm2, cy_mm, cz_mm, iy_mm4, iz_mm4, _ = polygon_properties(points)
    area = area_mm2 / 100.0
    iy, iz = iy_mm4 / 1e4, iz_mm4 / 1e4
    d_cm, bf_cm, tw_cm, tf_cm = (value / 10.0 for value in (d, bf, tw, tf))
    torsion = (2 * bf_cm * tf_cm**3 + (d_cm - 2 * tf_cm) * tw_cm**3) / 3.0
    warping = iz * (d_cm - tf_cm) ** 2 / 4.0
    return {
        "d": d, "bf": bf, "tw": tw, "tf": tf,
        "area": area, "Iy": iy, "Iz": iz,
        "Wy": iy / (d_cm / 2.0), "Wz": iz / (bf_cm / 2.0),
        "ry": sqrt(iy / area), "rz": sqrt(iz / area),
        "Zy": _plastic_modulus(points, 1, cz_mm) / 1000.0,
        "Zz": _plastic_modulus(points, 0, cy_mm) / 1000.0,
        "rt": sqrt(sqrt(iy * warping) / (iy / (d_cm / 2.0))),
        "It": torsion, "Cw": warping,
    }


def calculation_memory(model, member_names: tuple[str, ...]) -> dict:
    """Return element, W-section, and material inputs for the memorial."""
    members = [model.bars[name] for name in member_names if name in model.bars]
    if not members:
        return {}
    member = members[0]
    group = model.verification_group_for(member.name)
    element_name = (
        str(group.get("name", "")).strip() if group else
        model.verification_element_names.get(member.name, "")
    )
    geometry = _w_properties(member) if (member.section or "") == "W Laminado" else {}
    group_members = tuple(group.get("members", ())) if group else tuple(member_names)
    selected_result = next((
        model.verification_results.get(element.key)
        for element in verification_elements(model)
        if set(element.member_names) == set(group_members)
    ), None)
    checks = (selected_result or {}).get("checks", {})
    compression_parameters = (
        (checks.get("axial_compression") or {}).get("parameters") or {}
    )
    lengths = {"Ly": None, "Lz": None, "Lt": None, "Lb": None}
    cached_lengths = {
        name: compression_parameters.get(f"{name}_cm")
        for name in lengths
    }
    results = getattr(model, "analysis_results", ())
    if all(value is not None for value in cached_lengths.values()):
        lengths = cached_lengths
    elif geometry and results:
        try:
            element = VerificationElement(
                f"memorial:{'|'.join(member.name for member in members)}",
                element_name or member.name,
                tuple(item.name for item in members),
            )
            restraint = restraint_lengths(
                model,
                element,
                results,
                {"Iy": geometry["Iz"], "tw": geometry["tw"] / 10.0},
            )
            lengths = {name: restraint.lengths_m[name] * 100.0 for name in lengths}
        except Exception:
            logger.exception("Não foi possível determinar os comprimentos de %s no memorial.", element.name)
    material_values = model.materials.get(member.material, ())

    def value(key: str, scale: float = 1.0):
        return geometry[key] * scale if key in geometry else None

    material = {}
    if len(material_values) >= 6:
        material = {
            "type": model.material_types.get(member.material, ""),
            "E_kn_m2": material_values[0], "G_kn_m2": material_values[1],
            "poisson": material_values[2], "unit_weight_kn_m3": material_values[3],
            "fy_kn_m2": material_values[4], "fu_kn_m2": material_values[5],
        }
    gross_area_cm2 = geometry.get("area")
    net_area_cm2 = gross_area_cm2  # O modelo ainda não armazena furos ou recortes.
    net_area_factor = 1.0  # Valor inicial conforme a rotina de referência enviada.
    effective_area_cm2 = (
        net_area_factor * net_area_cm2 if net_area_cm2 is not None else None
    )
    return {
        "element_name": element_name,
        "members": group_members,
        "profile_type": member.section or "",
        "section": member.profile or "",
        "material": member.material or "",
        "geometric_parameters": {
            "d_mm": value("d"), "bf_mm": value("bf"),
            "tw_mm": value("tw"), "tf_mm": value("tf"),
            "Iy_cm4": value("Iy"), "Wy_cm3": value("Wy"),
            "ry_cm": value("ry"), "Zy_cm3": value("Zy"),
            "Iz_cm4": value("Iz"), "Wz_cm3": value("Wz"),
            "Rz_cm": value("rz"), "Zz_cm3": value("Zz"),
            "Ag_cm2": value("area"), "rt_cm": value("rt"),
            "It_cm4": value("It"), "Cw_cm6": value("Cw"),
            "Ly_cm": lengths["Ly"], "Lz_cm": lengths["Lz"],
            "Lt_cm": lengths["Lt"], "Lb_cm": lengths["Lb"],
        },
        "material_parameters": material,
        "axial_tension": {
            "Ag_cm2": gross_area_cm2,
            "An_cm2": net_area_cm2,
            "Ct": net_area_factor,
            "Ae_cm2": effective_area_cm2,
            "verification": checks.get("axial_tension", selected_result),
        },
        "axial_compression": {
            "verification": checks.get("axial_compression"),
        },
        "flexion_y": {
            "verification": checks.get("flexion_y"),
        },
        "flexion_z": {
            "verification": checks.get("flexion_z"),
        },
        "shear_y": {
            "verification": checks.get("shear_y"),
        },
        "shear_z": {
            "verification": checks.get("shear_z"),
        },
        "flexao_obliqua": {
            "verification": checks.get("flexao_obliqua"),
        },
        "flexotracao": {
            "verification": checks.get("flexotracao"),
        },
        "flexocompressao": {
            "verification": checks.get("flexocompressao"),
        },
    }
