import numpy as np
import pyvista as pv


class LocalAxesRenderer:
    @staticmethod
    def section_offset(member, start, end) -> np.ndarray:
        """Translate visual member details in the positioning Y/Z frame."""
        offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
        basis = LocalAxesRenderer.basis(start, end, rotation=0)
        if basis is None or len(offsets) != 2:
            return np.zeros(3, dtype=float)
        return basis[1] * float(offsets[0]) + basis[2] * float(offsets[1])

    @staticmethod
    def end_indicator_offset(length: float, radius: float) -> float:
        """Keep end markers inside their member, even for short members."""
        return min(max(float(radius), 0.0) * 4.0, max(float(length), 0.0) * 0.2)

    @staticmethod
    def basis(start, end, rotation: int = 0):
        x_axis = np.array((end.x - start.x, end.y - start.y, end.z - start.z), dtype=float)
        length = np.linalg.norm(x_axis)
        if length <= 1e-12:
            return None
        x_axis /= length
        reference = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(x_axis, reference))) > 0.99:
            reference = np.array((0.0, 1.0, 0.0))
        y_axis = np.cross(reference, x_axis)
        y_axis /= np.linalg.norm(y_axis)
        z_axis = np.cross(x_axis, y_axis)
        angle = np.deg2rad(rotation)
        cosine, sine = np.cos(angle), np.sin(angle)
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
