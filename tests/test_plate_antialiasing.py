"""Render plate boundaries and depth crossings with antialiasing enabled."""

import numpy as np
import pytest
import pyvista as pv

from osa.model import StructuralModel
from osa.rendering.batched_renderer import BatchedMemberRenderer
from osa.rendering.grid_renderer import GridRenderer
from osa.rendering.plate_antialiasing import PlateAntialiasing
from osa.rendering.scene_batched import StructureScene


class _PlateScene:
    _add_plates = StructureScene._add_plates
    _plate_meshes = StructureScene._plate_meshes
    _update_plate_edge_style = StructureScene._update_plate_edge_style
    _update_plate_antialiasing = StructureScene._update_plate_antialiasing
    _solid_highlight_line_width = 2.0


def test_older_renderer_without_oit_switch_remains_supported():
    antialiasing = PlateAntialiasing(object())
    antialiasing.set_active(True)
    antialiasing.set_active(False)


@pytest.mark.parametrize('previous', [False, True])
def test_original_transparency_mode_is_restored(previous):
    plotter = pv.Plotter(off_screen=True)
    try:
        plotter.renderer.SetUseOIT(previous)
        antialiasing = PlateAntialiasing(plotter.renderer)
        antialiasing.set_active(True)
        assert not plotter.renderer.GetUseOIT()
        antialiasing.set_active(False)
        assert plotter.renderer.GetUseOIT() == previous
    finally:
        plotter.close()


def _project(plotter, point, height):
    plotter.renderer.SetWorldPoint(*point, 1)
    plotter.renderer.WorldToDisplay()
    x, y, _ = plotter.renderer.GetDisplayPoint()
    return np.array((x, height - y))


def test_multisample_levels_change_the_rendered_plate_and_bar_edges():
    plotter = pv.Plotter(off_screen=True, window_size=(500, 500))
    try:
        plotter.set_background('white')
        original_oit = plotter.renderer.GetUseOIT()
        antialiasing = PlateAntialiasing(plotter.renderer)
        antialiasing.set_active(True)
        plotter.add_mesh(pv.Plane(i_size=2, j_size=2), color='#6e7781', opacity=.7)
        plotter.add_mesh(pv.Line((-1, -.8, 0), (1, .8, 0)), color='#24292f', line_width=2)
        plotter.view_xy()
        plotter.camera.parallel_projection = True
        plotter.camera.parallel_scale = 1.5
        images, effective_samples = [], []
        for samples in (2, 4, 8):
            plotter.render_window.SetMultiSamples(samples)
            images.append(plotter.screenshot(return_img=True).copy())
            effective_samples.append(plotter.render_window.GetRenderFramebuffer().GetMultiSamples())
        for index in range(2):
            # Drivers can cap the requested sample count to a lower value.
            if effective_samples[index] != effective_samples[index + 1]:
                assert np.any(images[index] != images[index + 1])
        antialiasing.set_active(False)
        assert plotter.renderer.GetUseOIT() == original_oit
    finally:
        plotter.close()


@pytest.mark.parametrize('direction', [(-1, -1, 1), (1, 1, 1)])
@pytest.mark.parametrize('samples', [2, 4, 8])
def test_antialiased_adjacent_plates_have_no_bright_seam(direction, samples):
    model = StructuralModel()
    for name, xyz in {
        'N6': (-2, -2, 3), 'N10': (0, -6, 3),
        'N8': (2, -2, 3), 'N12': (-4, -2, 3),
    }.items():
        model.add_node(name, *xyz)
    model.add_bar('B10', 'N6', 'N10')
    model.add_plate([(-2, -2, 3), (0, -6, 3), (2, -2, 3)], name='P1')
    model.add_plate([(-4, -2, 3), (-2, -2, 3), (0, -6, 3)], name='P2')

    plotter = pv.Plotter(off_screen=True, window_size=(1600, 1000))
    try:
        plotter.set_background('white')
        plotter.render_window.SetMultiSamples(samples)
        scene = _PlateScene()
        scene.plotter = plotter
        scene._model = model
        scene._antialiasing_samples = samples
        scene._plate_antialiasing = PlateAntialiasing(plotter.renderer)
        scene._solid_members_visible = False
        scene._selected_elements = ()
        scene._hovered = None
        scene._add_plates()
        batch = BatchedMemberRenderer().build(model, 0.03)
        bar = plotter.add_mesh(batch.lines, scalars='rgb', rgb=True, lighting=False, line_width=1.25)
        focus = np.array([-1.5, -3.5, 3.])
        plotter.camera.focal_point = focus
        plotter.camera.position = focus + np.array(direction) * 20
        plotter.camera.up = (0, 0, 1)
        plotter.camera.parallel_projection = True
        plotter.camera.parallel_scale = 4
        image = plotter.screenshot(return_img=True)
        assert plotter.render_window.GetMultiSamples() == samples
        assert not plotter.renderer.GetUseOIT()
        assert not bar.GetForceTranslucent()
        assert bar.GetProperty().GetLineWidth() == pytest.approx(1.25)

        face_brightness = []
        for plate in model.plates.values():
            center = np.asarray(plate.contour).mean(axis=0)
            x, y = np.rint(_project(plotter, center, image.shape[0])).astype(int)
            face_brightness.append(image[y, x, :3].mean())
        start, end = (
            _project(plotter, (model.nodes[name].x, model.nodes[name].y, model.nodes[name].z), image.shape[0])
            for name in ('N6', 'N10')
        )
        line = end - start
        normal = np.array((-line[1], line[0])) / np.linalg.norm(line)
        points = start + np.linspace(.08, .92, 800)[:, None] * line
        for offset in (-1, 0, 1):
            pixels = np.rint(points + normal * offset).astype(int)
            brightness = image[pixels[:, 1], pixels[:, 0], :3].mean(axis=1)
            assert brightness.max() < max(face_brightness) + 20
    finally:
        plotter.close()


@pytest.mark.parametrize('camera_z', [10, -10])
@pytest.mark.parametrize('plate_mode', [True, False])
def test_grid_does_not_draw_over_bar_and_lines_are_smoothed(camera_z, plate_mode):
    plotter = pv.Plotter(off_screen=True, window_size=(500, 500))
    try:
        plotter.set_background('white')
        plotter.render_window.SetMultiSamples(4)
        antialiasing = PlateAntialiasing(plotter.renderer)
        antialiasing.set_active(plate_mode)
        grid = plotter.add_mesh(pv.Line((0, -2, 0), (0, 2, 0)), color='red', opacity=.6, line_width=2)
        GridRenderer.configure_actor(grid)
        bar = plotter.add_mesh(pv.Line((-2, -.6, 1), (2, .6, 1)), color='black', line_width=3, lighting=False)
        plotter.camera.focal_point = (0, 0, 0)
        plotter.camera.position = (0, 0, camera_z)
        plotter.camera.up = (0, 1, 0)
        plotter.camera.parallel_projection = True
        plotter.camera.parallel_scale = 2.8
        image = plotter.screenshot(return_img=True)
        cross = np.rint(_project(plotter, (0, 0, 1), image.shape[0])).astype(int)
        pixel = image[cross[1], cross[0], :3].astype(int)
        assert pixel[0] - pixel[1] < 10  # red grid stays behind the bar
        assert pixel.mean() < 110
        # Antialiased line edges contain pixels between black and white.
        x, y = np.rint(_project(plotter, (.8, .24, 1), image.shape[0])).astype(int)
        patch = image[y - 4:y + 5, x - 4:x + 5, :3]
        assert np.any((patch.mean(axis=2) > 30) & (patch.mean(axis=2) < 225))
        assert bar.GetProperty().GetLineWidth() == pytest.approx(3)
        assert grid.GetProperty().GetLineWidth() == pytest.approx(2)
        antialiasing.set_active(False)
        assert plotter.render_window.GetMultiSamples() == 4
    finally:
        plotter.close()
