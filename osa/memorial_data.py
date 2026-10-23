"""Build calculation memorial inputs without running member checks."""

from __future__ import annotations

import logging
from math import sqrt

from osa.sections.contours import (
    i_contour_points, l_contour_points, polygon_properties, u_contour_points, w_contour_points,
)
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


def _i_properties(member) -> dict[str, float]:
    """Return rolled I geometry using its own parametric section contour."""
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        value = geometry.get(name, geometry.get(f"{name}_mm"))
        if value is None:
            raise ValueError(f"dimensão '{name}' ausente na seção")
        return float(value)

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    r1 = float(geometry.get("r1", geometry.get("r1_mm", 0.0))) or None
    r2 = float(geometry.get("r2", geometry.get("r2_mm", 0.0))) or None
    flange_angle_deg = float(geometry.get("flange_angle_deg", 2.0))
    points = i_contour_points(d, bf, tw, tf, r1, r2, flange_angle_deg)
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


def _l_properties(member) -> dict[str, float]:
    """Return equal-leg rolled L section properties used by checks and memorial."""
    from osa.verification.l_rolled import _section

    props = _section(member)
    return {
        "b": props["b_mm"], "b_mm": props["b_mm"],
        "t": props["t_mm"], "t_mm": props["t_mm"], "area": props["Ag_cm2"],
        "Iy": props["Iy_cm4"], "Iz": props["Iz_cm4"],
        "Imajor_cm4": props["Imajor_cm4"], "Iminor_cm4": props["Iminor_cm4"],
        "Wy": props["Wy_cm3"], "Wz": props["Wz_cm3"],
        "Zy": props["Zy_cm3"], "Zz": props["Zz_cm3"],
        "ry": props["ry_cm"], "rz": props["rz_cm"],
        "rt": props["r0_cm"], "It": props["It_cm4"], "Cw": props["Cw_cm6"],
    }


def _safe_l_properties(member) -> dict[str, float]:
    try:
        return _l_properties(member)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        logger.warning("Geometria L inválida ao preparar o memorial da barra %s.", member.name)
        return {}


def _t_properties(member) -> dict[str, float]:
    """Return the rolled T section properties used by its resistance routine."""
    from osa.verification.t_rolled import _section

    props = _section(member)
    return {
        "d": props["d_mm"], "bf": props["bf_mm"],
        "tw": props["tw_mm"], "tf": props["tf_mm"],
        "area": props["Ag_cm2"], "Iy": props["Iy_cm4"],
        "Iz": props["Iz_cm4"], "Wy": props["Wy_cm3"],
        "Wz": props["Wz_cm3"], "Zy": props["Zy_cm3"],
        "Zz": props["Zz_cm3"], "ry": props["ry_cm"],
        "rz": props["rz_cm"], "rt": props["r0_cm"],
        "It": props["It_cm4"], "Cw": props["Cw_cm6"],
    }


def _rectangular_bar_properties(member) -> dict[str, float]:
    from osa.verification.rectangular_bar import _section

    props = _section(member)
    return {
        "b": props["b_mm"], "b_mm": props["b_mm"],
        "h": props["h_mm"], "h_mm": props["h_mm"],
        "area": props["Ag_cm2"], "Iy": props["Iy_cm4"],
        "Iz": props["Iz_cm4"], "Wy": props["Wy_cm3"],
        "Wz": props["Wz_cm3"], "Zy": props["Zy_cm3"],
        "Zz": props["Zz_cm3"], "ry": props["ry_cm"],
        "rz": props["rz_cm"], "rt": props["r0_cm"], "It": props["It_cm4"],
    }


def _safe_rectangular_bar_properties(member) -> dict[str, float]:
    try:
        return _rectangular_bar_properties(member)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        logger.warning("Geometria retangular inválida ao preparar o memorial da barra %s.", member.name)
        return {}


def _safe_square_bar_properties(member) -> dict[str, float]:
    try:
        from osa.verification.rectangular_bar import _section

        props = _section(member)
        return {
            "b": props["b_mm"], "b_mm": props["b_mm"],
            "h": props["b_mm"], "h_mm": props["b_mm"],
            "area": props["Ag_cm2"], "Iy": props["Iy_cm4"],
            "Iz": props["Iz_cm4"], "Wy": props["Wy_cm3"],
            "Wz": props["Wz_cm3"], "Zy": props["Zy_cm3"],
            "Zz": props["Zz_cm3"], "ry": props["ry_cm"],
            "rz": props["rz_cm"], "rt": props["r0_cm"], "It": props["It_cm4"],
        }
    except (KeyError, TypeError, ValueError, ArithmeticError):
        logger.warning("Geometria quadrada inválida ao preparar o memorial da barra %s.", member.name)
        return {}


def _safe_round_bar_properties(member) -> dict[str, float]:
    try:
        from osa.verification.round_bar import _section

        props = _section(member)
        return {
            "d": props["d_mm"], "d_mm": props["d_mm"],
            "area": props["Ag_cm2"], "Iy": props["Iy_cm4"],
            "Iz": props["Iz_cm4"], "Wy": props["Wy_cm3"],
            "Wz": props["Wz_cm3"], "Zy": props["Zy_cm3"],
            "Zz": props["Zz_cm3"], "ry": props["ry_cm"],
            "rz": props["rz_cm"], "rt": props["r0_cm"], "It": props["It_cm4"],
        }
    except (KeyError, TypeError, ValueError, ArithmeticError):
        logger.warning("Geometria circular inválida ao preparar o memorial da barra %s.", member.name)
        return {}


def _plastic_modulus_asymmetric(points, axis: int) -> float:
    """Find the plastic neutral axis and modulus by integrating section strips.

    A U contour is concave, so clipping it into one polygon can connect
    disconnected pieces with artificial edges. Strip integration preserves
    the separate flange intervals on the open side of the section.
    """
    coordinates = sorted({point[axis] for point in points})
    low, high = coordinates[0], coordinates[-1]

    def width_at(position: float) -> float:
        intersections = []
        for first, second in zip(points, points[1:] + points[:1]):
            start, end = first[axis], second[axis]
            if min(start, end) < position < max(start, end):
                fraction = (position - start) / (end - start)
                other_axis = 1 - axis
                intersections.append(
                    first[other_axis] + fraction * (second[other_axis] - first[other_axis])
                )
        intersections.sort()
        return sum(
            intersections[index + 1] - intersections[index]
            for index in range(0, len(intersections) - 1, 2)
        )

    def area_to(position: float) -> float:
        breaks = [low, *(value for value in coordinates if low < value < position), position]
        return sum(
            width_at((start + end) / 2.0) * (end - start)
            for start, end in zip(breaks, breaks[1:])
        )

    area_total = polygon_properties(points)[0]
    left, right = low, high
    for _ in range(60):
        neutral_axis = (left + right) / 2.0
        if area_to(neutral_axis) < area_total / 2.0:
            left = neutral_axis
        else:
            right = neutral_axis
    neutral_axis = (left + right) / 2.0

    breaks = sorted({low, high, neutral_axis, *coordinates})
    modulus = 0.0
    for start, end in zip(breaks, breaks[1:]):
        if end <= start:
            continue
        width_1 = width_at(start + (end - start) / 4.0)
        width_3 = width_at(start + 3.0 * (end - start) / 4.0)
        span = end - start
        slope = 2.0 * (width_3 - width_1) / span
        width_at_start = width_1 - slope * span / 4.0
        first_moment = (
            width_at_start * ((start - neutral_axis) * span + span**2 / 2.0)
            + slope * ((start - neutral_axis) * span**2 / 2.0 + span**3 / 3.0)
        )
        modulus += abs(first_moment)
    return modulus


def _u_properties(member) -> dict[str, float]:
    """Return rolled U geometry, including its single-axis symmetry properties."""
    geometry = member.geometry_dict()

    def dimension(name: str) -> float:
        value = geometry.get(name, geometry.get(f"{name}_mm"))
        if value is None:
            raise ValueError(f"dimensão '{name}' ausente na seção")
        return float(value)

    d, bf, tw, tf = (dimension(key) for key in ("d", "bf", "tw", "tf"))
    radius = float(geometry.get("r", geometry.get("r_mm", 0.0))) or max(2.0, 1.5 * tf)
    tip_radius = float(geometry.get("r1", geometry.get("r1_mm", 0.0))) or None
    flange_angle = float(geometry.get("flange_angle_deg", geometry.get("angle", 2.0)))
    # The section-properties model represents U flanges as parallel to the
    # web; the rolled root radius is included in the contour used here.
    points = u_contour_points(d, bf, tw, tf, radius, tip_radius, flange_angle)
    area_mm2, cy_mm, cz_mm, iy_mm4, iz_mm4, _ = polygon_properties(points)
    area = area_mm2 / 100.0
    iy, iz = iy_mm4 / 1e4, iz_mm4 / 1e4
    d_cm, bf_cm, tw_cm, tf_cm = (value / 10.0 for value in (d, bf, tw, tf))
    flat_flange_width_cm = (bf - tw / 2.0) / 10.0
    clear_web_cm = (d - 2.0 * tf - 2.0 * radius) / 10.0
    web_to_flange = bf_cm - 0.5 * tw_cm
    torsion = (2.0 * bf_cm * tf_cm**3 + (d_cm - 2.0 * tf_cm) * tw_cm**3) / 3.0
    warping = (
        tf_cm * web_to_flange**3 * (d_cm - tf_cm)**2
        * (3.0 * web_to_flange * tf_cm + 2.0 * (d_cm - tf_cm) * tw_cm)
        / (12.0 * (6.0 * web_to_flange * tf_cm + (d_cm - tf_cm) * tw_cm))
    )
    # Thin-wall shear-flow estimate for the offset between the centroid and shear center.
    shear_center_offset_cm = abs(
        tf_cm * web_to_flange**2 * clear_web_cm**2 / (4.0 * iy)
    )
    max_weak_axis_distance_cm = max(
        (cy_mm + bf / 2.0) / 10.0,
        (bf / 2.0 - cy_mm) / 10.0,
    )
    return {
        "d": d, "bf": bf, "tw": tw, "tf": tf,
        "r": radius, "r1": tip_radius or max(0.75, 0.8 * tf),
        "flange_angle_deg": flange_angle,
        "area": area, "Iy": iy, "Iz": iz,
        "Wy": iy / (d_cm / 2.0), "Wz": iz / max_weak_axis_distance_cm,
        "ry": sqrt(iy / area), "rz": sqrt(iz / area),
        "Zy": _plastic_modulus(points, 1, cz_mm) / 1000.0,
        "Zz": _plastic_modulus_asymmetric(points, 0) / 1000.0,
        "rt": sqrt(sqrt(iy * warping) / (iy / (d_cm / 2.0))),
        "It": torsion, "Cw": warping,
        "x0": shear_center_offset_cm,
        "cx_mm": cy_mm,
        "h": max(0.0, d - 2.0 * tf - 2.0 * radius),
        "flange_width": flat_flange_width_cm * 10.0,
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
    profile_type = member.section or ""
    geometry = (
        _w_properties(member) if profile_type == "W Laminado" else
        _i_properties(member) if profile_type == "I Laminado" else
        _safe_l_properties(member) if profile_type == "L Laminado" else
        _t_properties(member) if profile_type == "T Laminado" else
        _safe_rectangular_bar_properties(member) if profile_type == "Barra Retangular" else
        _safe_square_bar_properties(member) if profile_type == "Barra Quadrada" else
        _safe_round_bar_properties(member) if profile_type == "Barra Circular" else
        _u_properties(member) if profile_type in {"U Laminado", "U Inclinado Laminado"} else {}
    )
    group_members = tuple(group.get("members", ())) if group else tuple(member_names)
    selected_result = next((
        model.verification_results.get(element.key)
        for element in verification_elements(model)
        if set(element.member_names) == set(group_members)
    ), None)
    checks = (selected_result or {}).get("checks", {})
    results = getattr(model, "analysis_results", ())
    compression_parameters = (
        (checks.get("axial_compression") or {}).get("parameters") or {}
    )
    lengths = {"Ly": None, "Lz": None, "Lt": None, "Lb": None}
    cached_lengths = {
        name: compression_parameters.get(f"{name}_cm")
        for name in lengths
    }
    if all(value is not None for value in cached_lengths.values()):
        lengths = cached_lengths
    elif geometry and results:
        try:
            thickness = geometry.get("tw", geometry.get("t", min(
                geometry.get("b", 0.0), geometry.get("h", 0.0),
            )))
            element = VerificationElement(
                f"memorial:{'|'.join(member.name for member in members)}",
                element_name or member.name,
                tuple(item.name for item in members),
            )
            restraint = restraint_lengths(
                model,
                element,
                results,
                {"Iy": geometry["Iz"], "tw": thickness / 10.0},
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
            "b_mm": value("b_mm"), "t_mm": value("t_mm"),
            "h_mm": value("h_mm"),
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
