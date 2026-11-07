from types import SimpleNamespace

import numpy as np
import pyvista as pv

from osa.rendering.plate_member_intersections import (
    _without_member_edges,
    dashed_plate_member_intersections,
)


def batch(*meshes):
    if not meshes:
        return SimpleNamespace(face_point_ranges={}, face_cell_ranges={}, faces=pv.PolyData())
    faces = meshes[0]
    point_ranges = {'B0': (0, faces.n_points)}
    cell_ranges = {'B0': (0, faces.n_cells)}
    for index, mesh in enumerate(meshes[1:], 1):
        old_points, old_cells = faces.n_points, faces.n_cells
        faces = faces.merge(mesh, merge_points=False)
        point_ranges[f'B{index}'] = (old_points, faces.n_points)
        cell_ranges[f'B{index}'] = (old_cells, faces.n_cells)
    return SimpleNamespace(face_point_ranges=point_ranges, face_cell_ranges=cell_ranges, faces=faces)


def test_only_plate_bar_crossings_generate_dashed_lines():
    plate = pv.Cube(bounds=(-2, 2, -2, 2, -.1, .1)).triangulate()
    through = pv.Cube(bounds=(-.2, .2, -3, 3, -.3, .3)).triangulate()
    far = pv.Cube(bounds=(5, 6, 5, 6, 5, 6)).triangulate()
    touching = pv.Cube(bounds=(2, 3, -1, 1, -.1, .1)).triangulate()
    assert dashed_plate_member_intersections([], batch(through, through)).n_cells == 0
    assert dashed_plate_member_intersections([plate], batch(far)).n_cells == 0
    assert dashed_plate_member_intersections([plate], batch(touching)).n_cells == 0
    dashed = dashed_plate_member_intersections([plate], batch(through))
    assert dashed.n_lines > 0
    assert np.all(np.isfinite(dashed.points))
    assert dashed.n_lines > 20


def test_bar_bar_crossings_and_dashes_without_tiny_end_fragments():
    first = pv.Cube(bounds=(-2, 2, -.2, .2, -.2, .2)).triangulate()
    second = pv.Cube(bounds=(-.2, .2, -2, 2, -.3, .3)).triangulate()
    far = pv.Cube(bounds=(5, 6, 5, 6, 5, 6)).triangulate()
    assert dashed_plate_member_intersections([], batch(first, far), include_member_pairs=True).n_cells == 0
    mesh = dashed_plate_member_intersections([], batch(first, second), include_member_pairs=True)
    assert mesh.n_lines > 0
    assert mesh.n_verts == 0
    cells = mesh.lines
    index = 0
    lengths = []
    while index < len(cells):
        count = cells[index]
        path = mesh.points[cells[index + 1:index + count + 1]]
        lengths.append(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
        index += count + 1
    assert min(lengths) >= .025 * .25 - 1e-9


def test_edge_filter_preserves_crossings_and_clips_partial_overlaps():
    path = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., 0.]])
    edges = np.array([[[.25, 0., 0.], [.75, 0., 0.]]])
    remaining = list(_without_member_edges(path, edges))
    assert len(remaining) == 2
    np.testing.assert_allclose(remaining[0], [[0., 0., 0.], [.25, 0., 0.]])
    np.testing.assert_allclose(remaining[1], [[.75, 0., 0.], [1., 0., 0.], [1., 1., 0.]])


def test_crossing_bars_keep_face_intersections_without_tracing_their_edges():
    first = pv.Cube(bounds=(-2, 2, -.2, .2, -.2, .2)).triangulate()
    second = pv.Cube(bounds=(-.2, .2, -2, 2, -.2, .2)).triangulate()
    model = batch(first, second)
    outlines = [mesh.extract_feature_edges(feature_angle=30, boundary_edges=True,
                feature_edges=True, manifold_edges=False, non_manifold_edges=False)
                for mesh in (first, second)]
    model.edges = outlines[0].merge(outlines[1], merge_points=False)
    model.edge_cell_ranges = {'B0': (0, outlines[0].n_cells),
                              'B1': (outlines[0].n_cells, model.edges.n_cells)}
    result = dashed_plate_member_intersections([], model, include_member_pairs=True)
    assert result.n_lines > 0

    edge_ids = model.edges.lines.reshape(-1, 3)[:, 1:]
    edge_points = np.asarray(model.edges.points)[edge_ids]
    vectors = edge_points[:, 1] - edge_points[:, 0]
    squared_lengths = np.einsum('ij,ij->i', vectors, vectors)
    cursor = 0
    while cursor < len(result.lines):
        count = result.lines[cursor]
        points = result.points[result.lines[cursor + 1:cursor + count + 1]]
        midpoints = (points[:-1] + points[1:]) / 2
        lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
        midpoints = midpoints[lengths > 1e-5]
        if not len(midpoints):
            cursor += count + 1
            continue
        relative = midpoints[:, None, :] - edge_points[None, :, 0, :]
        t = np.clip(np.einsum('sij,ij->si', relative, vectors) / squared_lengths, 0, 1)
        distance = np.linalg.norm(relative - t[:, :, None] * vectors, axis=2)
        assert np.all(np.min(distance, axis=1) > 1e-5)
        cursor += count + 1
