import math
from collections.abc import Iterable

import numpy as np
import pyvista as pv


class GridRenderer:
    """Render a 1 m reference grid around the structural model footprint."""

    margin = 5.0
    _color = (208, 215, 222)

    def __init__(self) -> None:
        self._bounds = (-self.margin, self.margin, -self.margin, self.margin)
        self._footprint_bounds = (0.0, 0.0, 0.0, 0.0)
        self.mesh = self._mesh_for_bounds(self._bounds, self._footprint_bounds)

    def update(self, nodes: Iterable[object], axes=None) -> None:
        """Rebuild only when the XY footprint of the model has changed."""
        positions = tuple((float(node.x), float(node.y)) for node in nodes)
        axes = axes or {}
        x_axis_values = tuple(float(axis.value) for axis in axes.get("X", ()))
        y_axis_values = tuple(float(axis.value) for axis in axes.get("Y", ()))
        if positions:
            xs, ys = zip(*positions)
            footprint_bounds = (
                min((*xs, *y_axis_values)), max((*xs, *y_axis_values)),
                min((*ys, *x_axis_values)), max((*ys, *x_axis_values)),
            )
        elif x_axis_values or y_axis_values:
            xs = y_axis_values or (0.0,)
            ys = x_axis_values or (0.0,)
            footprint_bounds = (
                min(xs), max(xs), min(ys), max(ys),
            )
        else:
            footprint_bounds = (0.0, 0.0, 0.0, 0.0)
        bounds = (
            footprint_bounds[0] - self.margin,
            footprint_bounds[1] + self.margin,
            footprint_bounds[2] - self.margin,
            footprint_bounds[3] + self.margin,
        )

        if bounds == self._bounds and footprint_bounds == self._footprint_bounds:
            return
        self._bounds = bounds
        self._footprint_bounds = footprint_bounds
        self.mesh = self._mesh_for_bounds(bounds, footprint_bounds)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._bounds

    def set_elevation(self, elevation: float) -> None:
        """Move the shared reference plane without rebuilding its XY geometry."""
        if not self.mesh.n_points or np.allclose(self.mesh.points[:, 2], elevation):
            return
        self.mesh.points[:, 2] = elevation
        self.mesh.GetPoints().Modified()
        self.mesh.Modified()

    @classmethod
    def _mesh_for_bounds(
        cls,
        bounds: tuple[float, float, float, float],
        footprint_bounds: tuple[float, float, float, float],
    ) -> pv.PolyData:
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        width = maximum_x - minimum_x
        height = maximum_y - minimum_y
        mesh = pv.Plane(
            center=((minimum_x + maximum_x) / 2.0, (minimum_y + maximum_y) / 2.0, 0.0),
            direction=(0, 0, 1),
            i_size=width,
            j_size=height,
            i_resolution=max(1, math.ceil(width)),
            j_resolution=max(1, math.ceil(height)),
        ).extract_all_edges()
        cls._add_fade(mesh, footprint_bounds)
        return mesh

    @classmethod
    def _add_fade(cls, mesh: pv.PolyData, footprint_bounds: tuple[float, float, float, float]) -> None:
        """Fade each grid vertex from the structural footprint to the outer margin."""
        minimum_x, maximum_x, minimum_y, maximum_y = footprint_bounds
        points = mesh.points
        distance_x = np.maximum(np.maximum(minimum_x - points[:, 0], 0.0), points[:, 0] - maximum_x)
        distance_y = np.maximum(np.maximum(minimum_y - points[:, 1], 0.0), points[:, 1] - maximum_y)
        opacity = np.clip(1.0 - np.maximum(distance_x, distance_y) / cls.margin, 0.0, 1.0)

        rgba = np.empty((mesh.n_points, 4), dtype=np.uint8)
        rgba[:, :3] = cls._color
        rgba[:, 3] = np.rint(opacity * 255.0).astype(np.uint8)
        mesh.point_data["rgba"] = rgba

    def render(self, plotter, nodes: Iterable[object], axes=None) -> None:
        self.update(nodes, axes)
        return plotter.add_mesh(
            self.mesh, scalars="rgba", rgb=True, line_width=1, pickable=False,
            name="reference-grid", render=False,
        )
