"""Geometry helpers for member end release symbols."""

from __future__ import annotations

from math import cos, pi, sin

import numpy as np


def release_symbol_polylines(
    endpoint: np.ndarray,
    inward: np.ndarray,
    releases: tuple[bool, ...],
    radius: float,
    basis: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    end: int,
    longitudinal_offset: float,
) -> list[np.ndarray]:
    """Return independent visual marks for the released local DOFs at one end.

    Release storage alternates A/B values for each local DOF: Dxa, Dxb,
    Dya, Dyb, Dza, Dzb, Rxa, Rxb, Rya, Ryb, Rza, Rzb.
    """
    if len(releases) != 12:
        return []

    local_x, local_y, local_z = basis
    axes = (local_x, local_y, local_z)
    selected = tuple(bool(releases[2 * dof + end]) for dof in range(6))
    if not any(selected):
        return []

    center = endpoint + inward * max(float(longitudinal_offset), 0.0)
    scale = max(float(radius), 0.0)
    marks: list[np.ndarray] = []

    # Translation releases use two short parallel strokes along the released
    # direction, offset symmetrically in the plane normal to that direction.
    for dof, (axis, offset_axis) in enumerate(zip(axes, (local_z, local_x, local_y))):
        if not selected[dof]:
            continue
        for sign in (-1.0, 1.0):
            midpoint = center + offset_axis * sign * scale * 1.15
            marks.append(np.asarray((midpoint - axis * scale, midpoint + axis * scale)))

    # Each rotational release is a loop in the plane normal to its local axis.
    # Slightly different radii keep simultaneous releases legible.
    for dof, axis_index in enumerate((0, 1, 2), start=3):
        if not selected[dof]:
            continue
        axis = axes[axis_index]
        first = axes[(axis_index + 1) % 3]
        second = axes[(axis_index + 2) % 3]
        loop_radius = scale * (1.05 + 0.25 * (axis_index))
        angles = np.linspace(0.0, 2.0 * pi, 40)
        marks.append(np.asarray([
            center + loop_radius * (first * cos(angle) + second * sin(angle))
            for angle in angles
        ]))
    return marks
