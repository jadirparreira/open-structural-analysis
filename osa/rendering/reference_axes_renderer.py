"""Batched rendering of named global reference axes."""

import numpy as np
import pyvista as pv


class ReferenceAxesRenderer:
    """Draw all X/Y reference axes in one GPU actor using dash-dot segments."""

    _dash_length = 0.55
    _dot_length = 0.08
    _gap_length = 0.20
    _extension = 5.0

    def __init__(self) -> None:
        self.mesh = pv.PolyData()

    def render(self, plotter, axes, bounds: tuple[float, float, float, float]):
        self.mesh = self.build(axes, bounds)
        if not self.mesh.n_cells:
            return None
        return plotter.add_mesh(
            self.mesh, color="#57606a", line_width=1.5, pickable=False,
            render_lines_as_tubes=True, lighting=False,
            name="reference-axes", reset_camera=False, render=False,
        )

    def set_elevation(self, elevation: float) -> None:
        """Move the complete batch of reference axes without rebuilding it."""
        if not self.mesh.n_points or np.allclose(self.mesh.points[:, 2], elevation):
            return
        self.mesh.points[:, 2] = elevation
        self.mesh.GetPoints().Modified()
        self.mesh.Modified()

    def build(self, axes, bounds: tuple[float, float, float, float]) -> pv.PolyData:
        segments: list[tuple[np.ndarray, np.ndarray]] = []
        x_start, x_end, y_start, y_end = self._line_extents(axes, bounds)
        for axis in axes.get("X", ()):
            self._append_dash_dot(
                segments,
                np.asarray((x_start, axis.value, 0.0)),
                np.asarray((x_end, axis.value, 0.0)),
            )
        for axis in axes.get("Y", ()):
            self._append_dash_dot(
                segments,
                np.asarray((axis.value, y_start, 0.0)),
                np.asarray((axis.value, y_end, 0.0)),
            )
        if not segments:
            return pv.PolyData()

        points = np.empty((len(segments) * 2, 3), dtype=float)
        lines = np.empty((len(segments), 3), dtype=np.int64)
        for index, (start, end) in enumerate(segments):
            points[index * 2] = start
            points[index * 2 + 1] = end
            lines[index] = (2, index * 2, index * 2 + 1)
        return pv.PolyData(points, lines=lines.ravel())

    def labels(
        self, axes, bounds: tuple[float, float, float, float], elevation: float = 0.0,
    ) -> tuple[np.ndarray, tuple[str, ...]]:
        """Return label positions at both ends of every rendered X/Y axis."""
        x_start, x_end, y_start, y_end = self._line_extents(axes, bounds)
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        offset = max(0.25, max(maximum_x - minimum_x, maximum_y - minimum_y) * 0.015)
        positions: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for axis in axes.get("X", ()):
            positions.extend(((x_start, axis.value + offset, elevation), (x_end, axis.value + offset, elevation)))
            labels.extend((axis.label, axis.label))
        for axis in axes.get("Y", ()):
            positions.extend(((axis.value + offset, y_start, elevation), (axis.value + offset, y_end, elevation)))
            labels.extend((axis.label, axis.label))
        return np.asarray(positions, dtype=float).reshape((-1, 3)), tuple(labels)

    def _line_extents(self, axes, bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        x_axis_values = tuple(axis.value for axis in axes.get("X", ()))
        y_axis_values = tuple(axis.value for axis in axes.get("Y", ()))
        x_start = min(y_axis_values) - self._extension if y_axis_values else minimum_x
        x_end = max(y_axis_values) + self._extension if y_axis_values else maximum_x
        y_start = min(x_axis_values) - self._extension if x_axis_values else minimum_y
        y_end = max(x_axis_values) + self._extension if x_axis_values else maximum_y
        return x_start, x_end, y_start, y_end

    def _append_dash_dot(
        self,
        segments: list[tuple[np.ndarray, np.ndarray]],
        start: np.ndarray,
        end: np.ndarray,
    ) -> None:
        direction = end - start
        length = float(np.linalg.norm(direction))
        if length == 0.0:
            return
        unit = direction / length
        position = 0.0
        while position < length:
            position = self._append_segment(segments, start, unit, position, self._dash_length, length)
            position += self._gap_length
            position = self._append_segment(segments, start, unit, position, self._dot_length, length)
            position += self._gap_length

    @staticmethod
    def _append_segment(
        segments: list[tuple[np.ndarray, np.ndarray]],
        origin: np.ndarray,
        direction: np.ndarray,
        position: float,
        segment_length: float,
        total_length: float,
    ) -> float:
        end_position = min(position + segment_length, total_length)
        if end_position > position:
            segments.append((origin + direction * position, origin + direction * end_position))
        return end_position
