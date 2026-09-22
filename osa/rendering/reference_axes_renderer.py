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

    def render(
        self, plotter, axes, bounds: tuple[float, float, float, float],
        plane: str = "XY", offset: float = 0.0,
    ):
        self.mesh = self.build(axes, bounds, plane, offset)
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

    def build(
        self, axes, bounds: tuple[float, float, float, float],
        plane: str = "XY", offset: float = 0.0,
    ) -> pv.PolyData:
        segments: list[tuple[np.ndarray, np.ndarray]] = []
        for start, end, _label, _offset in self._line_specs(axes, bounds, plane, offset):
            self._append_dash_dot(
                segments,
                self._world_point(start, plane, offset),
                self._world_point(end, plane, offset),
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
        plane: str = "XY", offset: float | None = None,
    ) -> tuple[np.ndarray, tuple[str, ...]]:
        """Return label positions at both ends of every axis on the active plane."""
        plane_offset = elevation if offset is None else offset
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        positions: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for start, end, label, label_offset in self._line_specs(axes, bounds, plane, plane_offset):
            if not label:
                continue
            start_label = self._world_point((start[0] + label_offset[0], start[1] + label_offset[1]), plane, plane_offset)
            end_label = self._world_point((end[0] + label_offset[0], end[1] + label_offset[1]), plane, plane_offset)
            positions.extend((start_label, end_label))
            labels.extend((label, label))
        return np.asarray(positions, dtype=float).reshape((-1, 3)), tuple(labels)

    def _line_specs(self, axes, bounds, plane: str, offset: float):
        plane = plane.upper()
        minimum_u, maximum_u, minimum_v, maximum_v = bounds
        x_values = tuple(float(axis.value) for axis in axes.get("X", ()))
        y_values = tuple(float(axis.value) for axis in axes.get("Y", ()))
        z_values = tuple(float(axis.value) for axis in axes.get("Z", ()))
        u_start, u_end = self._extended_range(y_values if plane != "YZ" else x_values, minimum_u, maximum_u)
        v_start, v_end = self._extended_range(z_values, minimum_v, maximum_v)
        specs = []
        if plane == "XZ":
            for axis in axes.get("X", ()):
                if np.isclose(float(axis.value), offset):
                    specs.append(((u_start, 0.0), (u_end, 0.0), "", (0.0, self._label_offset(bounds))))
            for axis in axes.get("Y", ()):
                specs.append(((axis.value, v_start), (axis.value, v_end), axis.label, (self._label_offset(bounds), 0.0)))
            for axis in axes.get("Z", ()):
                specs.append(((u_start, axis.value), (u_end, axis.value), axis.label, (0.0, self._label_offset(bounds))))
        elif plane == "YZ":
            for axis in axes.get("Y", ()):
                if np.isclose(float(axis.value), offset):
                    specs.append(((u_start, 0.0), (u_end, 0.0), "", (0.0, self._label_offset(bounds))))
            for axis in axes.get("X", ()):
                specs.append(((axis.value, v_start), (axis.value, v_end), axis.label, (self._label_offset(bounds), 0.0)))
            for axis in axes.get("Z", ()):
                specs.append(((u_start, axis.value), (u_end, axis.value), axis.label, (0.0, self._label_offset(bounds))))
        else:
            x_start, x_end, y_start, y_end = self._line_extents(axes, bounds)
            label_offset = self._label_offset(bounds)
            for axis in axes.get("X", ()):
                specs.append(((x_start, axis.value), (x_end, axis.value), axis.label, (0.0, label_offset)))
            for axis in axes.get("Y", ()):
                specs.append(((axis.value, y_start), (axis.value, y_end), axis.label, (label_offset, 0.0)))
        return specs

    @classmethod
    def _extended_range(cls, values, minimum, maximum):
        return (
            min(values) - cls._extension if values else minimum,
            max(values) + cls._extension if values else maximum,
        )

    @staticmethod
    def _label_offset(bounds) -> float:
        return max(0.25, max(bounds[1] - bounds[0], bounds[3] - bounds[2]) * 0.015)

    @staticmethod
    def _world_point(point, plane: str, offset: float) -> np.ndarray:
        u, v = point
        if plane.upper() == "XZ":
            return np.asarray((u, offset, v), dtype=float)
        if plane.upper() == "YZ":
            return np.asarray((offset, u, v), dtype=float)
        return np.asarray((u, v, offset), dtype=float)

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
