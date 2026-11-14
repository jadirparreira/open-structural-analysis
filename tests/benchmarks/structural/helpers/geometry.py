"""Independent geometric reference formulas."""

from __future__ import annotations


def rectangular_area(width_mm: float, height_mm: float) -> float:
    """Return the area of a solid rectangle in m²."""
    return width_mm * height_mm * 1e-6


def rectangular_major_inertia(width_mm: float, height_mm: float) -> float:
    """Return the major inertia used for local-y bending, in m⁴."""
    return width_mm * height_mm**3 / 12.0 * 1e-12


def rectangular_section_modulus(width_mm: float, height_mm: float) -> float:
    """Return the elastic section modulus for local-y bending, in m³."""
    return rectangular_major_inertia(width_mm, height_mm) / (height_mm * 1e-3 / 2.0)


def rectangular_torsion_constant(width_mm: float, height_mm: float) -> float:
    """Return the Saint-Venant approximation used for a solid rectangle, in m⁴."""
    long_side = max(width_mm, height_mm)
    short_side = min(width_mm, height_mm)
    ratio = short_side / long_side
    j_mm4 = long_side * short_side**3 * (
        1.0 / 3.0 - 0.21 * ratio * (1.0 - ratio**4 / 12.0)
    )
    return j_mm4 * 1e-12
