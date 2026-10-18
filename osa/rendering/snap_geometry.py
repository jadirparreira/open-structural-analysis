"""Geometric intersections of finite 3D segments, independent of the viewport."""

import numpy as np


def segment_intersections(starts: np.ndarray, ends: np.ndarray, tolerance: float) -> np.ndarray:
    """Return unique crossings; reject skew lines and collinear overlaps.

    The caller supplies only segments near the cursor, avoiding a quadratic
    search over the whole scene on every mouse move.
    """
    points = []
    directions = ends - starts
    lengths = np.linalg.norm(directions, axis=1)
    for index in range(len(starts) - 1):
        if lengths[index] <= tolerance:
            continue
        others = np.arange(index + 1, len(starts))
        crosses = np.cross(directions[index], directions[others])
        denominators = np.einsum("ij,ij->i", crosses, crosses)
        valid = denominators > 1e-20 * lengths[index] ** 2 * lengths[others] ** 2
        valid &= lengths[others] > tolerance
        others = others[valid]
        crosses = crosses[valid]
        denominators = denominators[valid]
        if not len(others):
            continue
        offsets = starts[others] - starts[index]
        first = np.einsum("ij,ij->i", np.cross(offsets, directions[others]), crosses) / denominators
        second = np.einsum("ij,ij->i", np.cross(offsets, directions[index]), crosses) / denominators
        valid = (
            (first >= -tolerance / lengths[index])
            & (first <= 1.0 + tolerance / lengths[index])
            & (second >= -tolerance / lengths[others])
            & (second <= 1.0 + tolerance / lengths[others])
        )
        first_points = starts[index] + np.clip(first[valid], 0.0, 1.0)[:, None] * directions[index]
        second_points = (
            starts[others[valid]]
            + np.clip(second[valid], 0.0, 1.0)[:, None] * directions[others[valid]]
        )
        matches = np.linalg.norm(first_points - second_points, axis=1) <= tolerance
        points.extend((first_points[matches] + second_points[matches]) * 0.5)
    if not points:
        return np.empty((0, 3), dtype=float)
    points = np.asarray(points, dtype=float)
    _, indices = np.unique(np.round(points, decimals=9), axis=0, return_index=True)
    return points[np.sort(indices)]
