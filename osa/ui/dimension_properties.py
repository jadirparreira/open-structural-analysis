"""Individual dimension values in model units and their display units."""
import math

from .special_dimensions import angular_geometry, elevation

UNIT_SCALES = {"m": 1., "dm": 10., "cm": 100., "mm": 1000., "°": 1.}


def dimension_unit(dimension, settings):
    kind = dimension.get("kind")
    default = "°" if kind == "angular" else "m" if kind == "level" else settings.get("dimension_unit", "cm")
    return dimension.get("unit", default)


def dimension_value(ws, view_index, dimension):
    if "value_override" in dimension:
        return float(dimension["value_override"])
    if dimension.get("kind") == "angular":
        geometry = angular_geometry(dimension)
        return math.degrees(geometry[1]) if geometry else 0.
    if dimension.get("kind") == "level":
        return (elevation(ws, view_index, dimension["start"]) or 0.) - float(
            ws._project_settings.get("level_dimension_reference_m", 0.))
    first, second = dimension["start"], dimension["end"]
    axis = dimension.get("orthogonal_axis")
    if axis in {"x", "y"}:
        index = 0 if axis == "x" else 1
        return abs(second[index] - first[index])
    return math.hypot(second[0] - first[0], second[1] - first[1])
