import pyvista as pv


class SupportRenderer:
    def render(self, plotter, node, radius: float) -> None:
        if node.supports == (True, True, True, True, True, True):
            side = radius * 2.4
            mesh = pv.Cube(center=(node.x, node.y, node.z - side / 2),
                           x_length=side, y_length=side, z_length=side)
        elif node.supports == (True, True, True, False, False, False):
            height, half = radius * 4.0, radius * 1.5
            mesh = pv.Pyramid(points=[
                (node.x - half, node.y - half, node.z - height),
                (node.x + half, node.y - half, node.z - height),
                (node.x + half, node.y + half, node.z - height),
                (node.x - half, node.y + half, node.z - height),
                (node.x, node.y, node.z),
            ])
        else:
            return
        plotter.add_mesh(mesh, color="#a8b0b9", edge_color="#6e7781", show_edges=True,
                         line_width=1.5, pickable=False, name=f"support-{node.name}")
