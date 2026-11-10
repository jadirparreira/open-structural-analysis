"""Color scale shared by plate result contours and deformation overlays."""

from __future__ import annotations

import numpy as np

# A discrete spectrum close to SCIA's slab-result isobands: violet/blue,
# cyan, green, yellow, orange and red. Equal-sized bins keep band widths stable.
RESULT_COLOR_STOPS = (
    "#102BFF", "#006BFF",
    "#009FFF", "#00C8E8", "#00D4B0", "#00C853",
    "#53D000", "#A8DF00", "#E7EB00", "#FFE000",
    "#FFC000", "#FF9700", "#F45A00", "#E00000",
)
RESULT_COLOR_COUNT = len(RESULT_COLOR_STOPS)
RESULT_MESH_COLOR = "#20242A"


def result_colors(values, value_range: tuple[float, float]) -> np.ndarray:
    """Map values into equal-width, discrete spectrum bands."""
    values = np.asarray(values, dtype=float)
    low, high = (float(value) for value in value_range)
    if not np.isfinite(low) or not np.isfinite(high):
        return np.full((*values.shape, 3), (211, 211, 211), dtype=np.uint8)
    if high - low <= 1e-12:
        band_indices = np.full(values.shape, RESULT_COLOR_COUNT // 2, dtype=int)
    else:
        normalized = np.clip((values - low) / (high - low), 0.0, 1.0)
        band_indices = np.minimum((normalized * RESULT_COLOR_COUNT).astype(int), RESULT_COLOR_COUNT - 1)
    palette = np.asarray([
        tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
        for color in RESULT_COLOR_STOPS
    ], dtype=float)
    return palette[band_indices].astype(np.uint8)
