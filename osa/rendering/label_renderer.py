class LabelRenderer:
    def render(self, plotter, position, text: str, *, visible: bool):
        actor = plotter.add_point_labels(
            [position], [text], font_size=11, text_color="#24292f", shape_color="white",
            margin=1, shape=None, fill_shape=False, shape_opacity=0.0,
            justification_horizontal="center", always_visible=True, show_points=False,
            name=f"label-{text}",
        )
        actor.SetVisibility(visible)
        return actor
