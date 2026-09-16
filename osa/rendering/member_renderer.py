import pyvista as pv

from .label_renderer import LabelRenderer
from .local_axes_renderer import LocalAxesRenderer


class MemberRenderer:
    def __init__(self, axes_renderer=None, label_renderer=None) -> None:
        self.axes = axes_renderer or LocalAxesRenderer()
        self.labels = label_renderer or LabelRenderer()

    def render(self, plotter, member, start, end, radius: float, register_actor,
               labels_visible: bool, axes_visible: bool):
        actor = plotter.add_mesh(
            pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z)),
            color="#24292f", line_width=4,
        )
        register_actor(actor, "bar", member.name)
        axes = self.axes.render(plotter, start, end, visible=axes_visible)
        midpoint = ((start.x + end.x) / 2, (start.y + end.y) / 2,
                    (start.z + end.z) / 2 + radius * 2.2)
        label = self.labels.render(plotter, midpoint, member.name, visible=labels_visible)
        return label, axes
