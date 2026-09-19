import numpy as np
import pyvista as pv

from .local_axes_renderer import LocalAxesRenderer


class ReleaseRenderer:
    """Draw compact end-release circles over a member."""

    _release_color = "#000000"

    def render(self, plotter, start, end, releases, radius: float, *, rotation: int = 0) -> list[object]:
        if len(releases) != 12 or not any(releases):
            return []
        basis = LocalAxesRenderer.basis(start, end, rotation)
        if basis is None:
            return []
        x_axis, y_axis, z_axis = basis
        start_point = np.array((start.x, start.y, start.z), dtype=float)
        end_point = np.array((end.x, end.y, end.z), dtype=float)
        actors: list[object] = []
        for endpoint, inward, has_release in (
            (start_point, x_axis, any(releases[index] for index in (0, 2, 4, 6, 8, 10))),
            (end_point, -x_axis, any(releases[index] for index in (1, 3, 5, 7, 9, 11))),
        ):
            if not has_release:
                continue
            center = endpoint + inward * radius * 4.0
            points = []
            circle_radius = radius * 1.05
            for angle in np.linspace(0.0, 2.0 * np.pi, 32):
                points.append(center + y_axis * np.cos(angle) * circle_radius
                             + z_axis * np.sin(angle) * circle_radius)
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
