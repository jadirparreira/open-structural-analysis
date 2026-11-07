from types import SimpleNamespace

import numpy as np
import pyvista as pv

from osa.rendering.plate_member_intersections import dashed_plate_member_intersections


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
