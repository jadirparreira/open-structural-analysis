import pyvista as pv


class GridRenderer:
    def __init__(self) -> None:
        self.mesh = pv.Plane(center=(0.0, 0.0, 0.0), direction=(0, 0, 1),
                             i_size=10.0, j_size=10.0, i_resolution=10, j_resolution=10).extract_all_edges()

    def render(self, plotter) -> None:
        plotter.add_mesh(
            self.mesh, color="#d0d7de", line_width=1, pickable=False,
            name="reference-grid", render=False,
        )
