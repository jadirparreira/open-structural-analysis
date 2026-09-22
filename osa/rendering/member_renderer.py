import pyvista as pv

from .label_renderer import LabelRenderer
from .local_axes_renderer import LocalAxesRenderer
from .release_renderer import ReleaseRenderer


class MemberRenderer:
    AURA_LINE_WIDTH = 6.0

    def __init__(self, axes_renderer=None, label_renderer=None, release_renderer=None) -> None:
        self.axes = axes_renderer or LocalAxesRenderer()
        self.labels = label_renderer or LabelRenderer()
        self.releases = release_renderer or ReleaseRenderer()

    @staticmethod
    def _rounded_caps(plotter, start, end, color: str, *, visible: bool, radius: float) -> list[object]:
        actors = []
        for point in (start, end):
            actor = plotter.add_mesh(
                pv.Sphere(radius=1.0, center=(0.0, 0.0, 0.0), theta_resolution=20, phi_resolution=12),
                color=color, pickable=False, reset_camera=False, render=False,
            )
            actor.SetPosition(point.x, point.y, point.z)
            actor.SetScale(radius, radius, radius)
            actor.SetVisibility(visible)
            actors.append(actor)
        return actors

    def render(self, plotter, member, start, end, radius: float, register_actor,
               labels_visible: bool, axes_visible: bool):
        aura = plotter.add_mesh(
            pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z)),
            color="#000000", line_width=self.AURA_LINE_WIDTH, pickable=False,
            reset_camera=False, render=False,
        )
        aura.SetVisibility(False)
        aura_caps = self._rounded_caps(
            plotter, start, end, "#000000", visible=False, radius=radius * 0.01,
        )
        actor = plotter.add_mesh(
            pv.Line((start.x, start.y, start.z), (end.x, end.y, end.z)),
            color=member.color, line_width=4, reset_camera=False, render=False,
        )
        member_caps = self._rounded_caps(
            plotter, start, end, member.color, visible=True, radius=radius * 0.01,
        )
        register_actor(actor, "bar", member.name)
        axes = self.axes.render(plotter, start, end, rotation=member.rotation, visible=axes_visible)
        release_actors = self.releases.render(
            plotter, start, end, member.releases, radius, rotation=member.rotation,
        )
        midpoint = ((start.x + end.x) / 2, (start.y + end.y) / 2,
                    (start.z + end.z) / 2 + radius * 2.2)
        label = self.labels.render(plotter, midpoint, member.name, visible=labels_visible)
        return label, axes, aura, release_actors, member_caps, aura_caps
