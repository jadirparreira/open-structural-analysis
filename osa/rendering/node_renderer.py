import pyvista as pv

from .label_renderer import LabelRenderer
from .support_renderer import SupportRenderer


class NodeRenderer:
    supported_patterns = frozenset({
        (False, False, False, False, False, False),
        (True, True, True, False, False, False),
        (True, True, True, True, True, True),
    })

    def __init__(self, support_renderer=None, label_renderer=None) -> None:
        self.supports = support_renderer or SupportRenderer()
        self.labels = label_renderer or LabelRenderer()

    def render(self, plotter, node, radius: float, register_actor, labels_visible: bool):
        color = "#0969da" if node.supports in self.supported_patterns else "#cf222e"
        actor = plotter.add_mesh(
            pv.Sphere(radius=radius, center=(node.x, node.y, node.z), theta_resolution=12, phi_resolution=8),
            color=color,
        )
        register_actor(actor, "node", node.name)
        label = self.labels.render(
            plotter, (node.x, node.y, node.z + radius * 2.2), node.name, visible=labels_visible
        )
        self.supports.render(plotter, node, radius)
        return label
