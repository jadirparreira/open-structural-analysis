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
        self._plane = "XY"
        self._offset = 0.0
        self._nodes: tuple[object, ...] = ()
        self._axes = {}
        self.mesh = self._mesh_for_bounds(self._bounds, self._footprint_bounds, self._plane, self._offset)

    def update(self, nodes: Iterable[object], axes=None, plane: str = "XY", offset: float = 0.0) -> None:
        """Rebuild only when the active plane footprint or level changes."""
        nodes = tuple(nodes)
        self._nodes = nodes
        self._axes = axes or {}
        self._plane = plane.upper()
        self._offset = float(offset)
        axes = self._axes
        x_axis_values = tuple(float(axis.value) for axis in axes.get("X", ()))
        y_axis_values = tuple(float(axis.value) for axis in axes.get("Y", ()))
        z_axis_values = tuple(float(axis.value) for axis in axes.get("Z", ()))
        if self._plane == "XZ":
            positions = tuple((float(node.x), float(node.z)) for node in nodes)
            axis_u_values, axis_v_values = y_axis_values, z_axis_values
        elif self._plane == "YZ":
            positions = tuple((float(node.y), float(node.z)) for node in nodes)
            axis_u_values, axis_v_values = x_axis_values, z_axis_values
        else:
            positions = tuple((float(node.x), float(node.y)) for node in nodes)
            axis_u_values, axis_v_values = y_axis_values, x_axis_values
        if positions:
            us, vs = zip(*positions)
            footprint_bounds = (
                min((*us, *axis_u_values)), max((*us, *axis_u_values)),
                min((*vs, *axis_v_values)), max((*vs, *axis_v_values)),
            )
        elif axis_u_values or axis_v_values:
            us = axis_u_values or (0.0,)
            vs = axis_v_values or (0.0,)
            footprint_bounds = (
                min(us), max(us), min(vs), max(vs),
            )
        else:
            footprint_bounds = (0.0, 0.0, 0.0, 0.0)
        bounds = (
            footprint_bounds[0] - self.margin,
            footprint_bounds[1] + self.margin,
            footprint_bounds[2] - self.margin,
            footprint_bounds[3] + self.margin,
        )

        if (
            bounds == self._bounds
            and footprint_bounds == self._footprint_bounds
            and self._plane == getattr(self, "_built_plane", None)
            and np.isclose(self._offset, getattr(self, "_built_offset", 0.0))
        ):
            return
        self._bounds = bounds
        self._footprint_bounds = footprint_bounds
        self._built_plane = self._plane
        self._built_offset = self._offset
        self.mesh = self._mesh_for_bounds(bounds, footprint_bounds, self._plane, self._offset)

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

    def set_plane(self, plane: str, offset: float) -> None:
        """Change orientation and level using the cached footprint."""
        self.update(self._nodes, self._axes, plane, offset)

    @classmethod
    def _mesh_for_bounds(
        cls,
        bounds: tuple[float, float, float, float],
        footprint_bounds: tuple[float, float, float, float],
        plane: str = "XY",
        offset: float = 0.0,
    ) -> pv.PolyData:
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        width = maximum_x - minimum_x
        height = maximum_y - minimum_y
        center_u = (minimum_x + maximum_x) / 2.0
        center_v = (minimum_y + maximum_y) / 2.0
        # Build in a canonical XY plane first so i_size always represents the
        # first local coordinate (X for XZ, Y for YZ), then map it to world axes.
        mesh = pv.Plane(
            center=(center_u, center_v, 0.0),
            direction=(0, 0, 1),
            i_size=width,
            j_size=height,
            i_resolution=max(1, math.ceil(width)),
            j_resolution=max(1, math.ceil(height)),
        ).extract_all_edges()
        local_points = mesh.points.copy()
        if plane == "XZ":
            mesh.points = np.column_stack((local_points[:, 0], np.full(len(local_points), offset), local_points[:, 1]))
        elif plane == "YZ":
            mesh.points = np.column_stack((np.full(len(local_points), offset), local_points[:, 0], local_points[:, 1]))
        else:
            mesh.points[:, 2] = offset
        cls._add_fade(mesh, footprint_bounds, plane)
        return mesh

    @classmethod
    def _add_fade(
        cls, mesh: pv.PolyData, footprint_bounds: tuple[float, float, float, float], plane: str = "XY",
    ) -> None:
        """Fade each grid vertex from the structural footprint to the outer margin."""
        minimum_x, maximum_x, minimum_y, maximum_y = footprint_bounds
        points = mesh.points
        if plane == "XZ":
            coordinate_u, coordinate_v = points[:, 0], points[:, 2]
        elif plane == "YZ":
            coordinate_u, coordinate_v = points[:, 1], points[:, 2]
        else:
            coordinate_u, coordinate_v = points[:, 0], points[:, 1]
        distance_x = np.maximum(np.maximum(minimum_x - coordinate_u, 0.0), coordinate_u - maximum_x)
        distance_y = np.maximum(np.maximum(minimum_y - coordinate_v, 0.0), coordinate_v - maximum_y)
        opacity = np.clip(1.0 - np.maximum(distance_x, distance_y) / cls.margin, 0.0, 1.0)

        rgba = np.empty((mesh.n_points, 4), dtype=np.uint8)
        rgba[:, :3] = cls._color
        rgba[:, 3] = np.rint(opacity * 255.0).astype(np.uint8)
        mesh.point_data["rgba"] = rgba

    def render(
        self, plotter, nodes: Iterable[object], axes=None,
        plane: str = "XY", offset: float = 0.0,
    ) -> None:
        self.update(nodes, axes, plane, offset)
        return plotter.add_mesh(
            self.mesh, scalars="rgba", rgb=True, line_width=1, pickable=False,
            name="reference-grid", render=False,
        )
