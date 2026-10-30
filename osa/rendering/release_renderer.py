import numpy as np
import pyvista as pv

from .local_axes_renderer import LocalAxesRenderer
from .release_symbols import release_symbol_polylines


class ReleaseRenderer:
    """Draw compact end-release circles over a member."""

    _release_color = "#000000"

    def render(self, plotter, start, end, releases, radius: float, *, rotation: float = 0) -> list[object]:
        if len(releases) != 12 or not any(releases):
            return []
        basis = LocalAxesRenderer.basis(start, end, rotation)
        if basis is None:
            return []
        x_axis, _y_axis, _z_axis = basis
        start_point = np.array((start.x, start.y, start.z), dtype=float)
        end_point = np.array((end.x, end.y, end.z), dtype=float)
        longitudinal_offset = LocalAxesRenderer.end_indicator_offset(
            float(np.linalg.norm(end_point - start_point)), radius,
        )
        actors: list[object] = []
        for endpoint, inward, end_index in (
            (start_point, x_axis, 0),
            (end_point, -x_axis, 1),
        ):
            for points in release_symbol_polylines(
                endpoint, inward, releases, radius, basis, end=end_index,
                longitudinal_offset=longitudinal_offset,
            ):
                actors.append(self._polyline(plotter, points, self._release_color))
        return actors

    @staticmethod
    def _polyline(plotter, points, color: str):
        points = np.asarray(points, dtype=float)
        mesh = pv.PolyData(points)
        mesh.lines = np.hstack(([len(points)], np.arange(len(points), dtype=np.int64)))
        return plotter.add_mesh(
            mesh, color=color, line_width=3, pickable=False, reset_camera=False, render=False,
        )
