from math import cos, hypot, radians, sin

import numpy as np
import pyvista as pv


class LocalAxesRenderer:
    @staticmethod
    def section_offset(member, start, end) -> np.ndarray:
        """Translate visual member details in the positioning Y/Z frame."""
        offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
        if len(offsets) != 2 or not any(offsets):
            return np.zeros(3, dtype=float)
        basis = LocalAxesRenderer.basis(start, end, rotation=0)
        if basis is None:
            return np.zeros(3, dtype=float)
        return basis[1] * float(offsets[0]) + basis[2] * float(offsets[1])

    @staticmethod
    def end_indicator_offset(length: float, radius: float) -> float:
        """Keep end markers inside their member, even for short members."""
        return min(max(float(radius), 0.0) * 4.0, max(float(length), 0.0) * 0.2)

    @staticmethod
    def basis(start, end, rotation: int = 0):
        x, y, z = end.x - start.x, end.y - start.y, end.z - start.z
        length = hypot(x, y, z)
        if length <= 1e-12:
            return None
        x, y, z = x / length, y / length, z / length
        # Expand the two fixed-reference cross products directly. NumPy's
        # general cross/axis dispatch dominated this per-member hot path.
        yx, yy, yz = (z, 0.0, -x) if abs(z) > 0.99 else (-y, x, 0.0)
        y_length = hypot(yx, yy, yz)
        yx, yy, yz = yx / y_length, yy / y_length, yz / y_length
        x_axis = np.array((x, y, z))
        y_axis = np.array((yx, yy, yz))
        z_axis = np.array((y * yz - z * yy, z * yx - x * yz, x * yy - y * yx))
        if rotation == 0:
            return x_axis, y_axis, z_axis
        angle = radians(rotation)
        cosine, sine = cos(angle), sin(angle)
        rotated_y = y_axis * cosine + z_axis * sine
        rotated_z = z_axis * cosine - y_axis * sine
        return x_axis, rotated_y, rotated_z

    def render(self, plotter, start, end, *, rotation: int = 0, visible: bool) -> list[object]:
        origin = np.array(((start.x + end.x) / 2, (start.y + end.y) / 2, (start.z + end.z) / 2))
        basis = self.basis(start, end, rotation)
        if basis is None:
            return []
        x_axis, rotated_y, rotated_z = basis
        length = np.linalg.norm(np.array((end.x - start.x, end.y - start.y, end.z - start.z)))
        scale = min(max(length * 0.2, 0.15), 1.0)
        actors = []
        for axis, color in ((x_axis, "#d1242f"), (rotated_y, "#f2b705"), (rotated_z, "#2da44e")):
            actor = plotter.add_mesh(pv.Line(origin, origin + axis * scale), color=color,
                                     line_width=4, pickable=False, reset_camera=False,
                                     render=False)
            actor.SetVisibility(visible)
            actors.append(actor)
        return actors
