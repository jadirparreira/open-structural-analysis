class LabelRenderer:
    def render(self, plotter, position, text: str, *, visible: bool):
        actor = plotter.add_point_labels(
            [position], [text], font_size=11, text_color="#24292f", shape_color="white",
            margin=1, shape=None, fill_shape=False, shape_opacity=0.0,
            justification_horizontal="center", always_visible=True, show_points=False,
            reset_camera=False, render=False,
            name=f"label-{text}",
        )
        actor.SetVisibility(visible)
        return actor

    def render_many(self, plotter, positions, labels, *, visible: bool, name: str):
        if not labels:
            return None
        actor = plotter.add_point_labels(
            positions,
            labels,
            font_size=11,
            text_color="#24292f",
            shape_color="white",
            margin=1,
            shape=None,
            fill_shape=False,
            shape_opacity=0.0,
            justification_horizontal="center",
            always_visible=True,
            show_points=False,
            reset_camera=False,
            render=False,
            name=name,
        )
        actor.SetVisibility(visible)
        return actor
