import pyvista as pv
import vtk

from .label_renderer import LabelRenderer
from .support_renderer import SupportRenderer


class NodeRenderer:
    AURA_RADIUS_FACTOR = 1.25

    supported_patterns = frozenset({
        (False, False, False, False, False, False),
        (True, True, True, False, False, False),
        (True, True, True, True, True, True),
    })

    def __init__(self, support_renderer=None, label_renderer=None) -> None:
        self.supports = support_renderer or SupportRenderer()
        self.labels = label_renderer or LabelRenderer()

    @staticmethod
    def _circle_actor(plotter, node, radius: float, color: str, *, visible: bool):
        source = vtk.vtkRegularPolygonSource()
        source.SetNumberOfSides(32)
        # Keep the source normalized and express the marker radius in model
        # units through the actor scale, so zoom changes its screen size.
        source.SetRadius(1.0)
        source.SetCenter(0.0, 0.0, 0.0)
        source.GeneratePolygonOn()
        source.Update()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())
        actor = vtk.vtkFollower()
        actor.SetMapper(mapper)
        actor.SetPosition(node.x, node.y, node.z)
        actor.SetScale(radius, radius, radius)
        actor.SetCamera(plotter.renderer.GetActiveCamera())
        actor.GetProperty().SetColor(*pv.Color(color).float_rgb)
        actor.SetVisibility(visible)
        plotter.add_actor(actor, pickable=False, render=False)
        return actor

    @staticmethod
    def _sphere_actor(plotter, node, radius: float, color: str, *, visible: bool):
        actor = plotter.add_mesh(
            pv.Sphere(radius=radius, center=(0.0, 0.0, 0.0), theta_resolution=20,
                      phi_resolution=12),
            color=color, pickable=False, reset_camera=False, render=False,
        )
        actor.SetPosition(node.x, node.y, node.z)
        actor.SetVisibility(visible)
        return actor

    def render(
        self, plotter, node, radius: float, register_actor, labels_visible: bool,
        *, support_radius: float | None = None,
    ):
        color = "#000000"
        aura = self._circle_actor(
            plotter, node, radius * self.AURA_RADIUS_FACTOR, "#000000", visible=False,
        )
        actor = self._sphere_actor(plotter, node, radius, color, visible=True)
        register_actor(actor, "node", node.name)
        label = self.labels.render(
            plotter, (node.x, node.y, node.z + radius * 2.2), node.name, visible=labels_visible
        )
        support = self.supports.render(plotter, node, support_radius if support_radius is not None else radius)
        return label, aura, support
