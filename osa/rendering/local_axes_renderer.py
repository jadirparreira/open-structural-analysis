import numpy as np
import pyvista as pv


class LocalAxesRenderer:
    def render(self, plotter, start, end, *, visible: bool) -> list[object]:
        origin = np.array(((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2))
        x_axis = np.array((end.x - start.x, end.y - start.y, end.z - start.z), dtype=float)
        length = np.linalg.norm(x_axis)
        if length <= 1e-12:
            return []
        x_axis /= length
        reference = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(x_axis, reference))) > 0.99:
            reference = np.array((0.0, 1.0, 0.0))
        y_axis = np.cross(reference, x_axis); y_axis /= np.linalg.norm(y_axis)
        z_axis = np.cross(x_axis, y_axis)
        scale = max(length * 0.2, 0.15)
        actors = []
        for axis, color in ((x_axis, "#d1242f"), (y_axis, "#f2b705"), (z_axis, "#2da44e")):
            actor = plotter.add_mesh(pv.Line(origin, origin + axis * scale), color=color,
                                     line_width=3, pickable=False)
            actor.SetVisibility(visible)
            actors.append(actor)
        return actors
