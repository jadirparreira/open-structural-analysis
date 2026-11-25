"""Traços nos cruzamentos visuais entre superfícies sólidas de placas e barras."""

from __future__ import annotations

import numpy as np
import pyvista as pv
import vtk


def _surface_for_members(batch, names, member_indices):
    cells = np.concatenate([
        np.arange(*batch.face_cell_ranges[name], dtype=np.int64) for name in names
    ])
    subset = batch.faces.extract_cells(cells)
    subset.cell_data['_intersection_owner'] = np.concatenate([
        np.full(batch.face_cell_ranges[name][1] - batch.face_cell_ranges[name][0],
                member_indices[name], dtype=np.int32)
        for name in names
    ])
    surface = vtk.vtkDataSetSurfaceFilter()
    surface.SetInputData(subset)
    surface.Update()
    return pv.wrap(surface.GetOutput()).triangulate()


def _normals(mesh):
    triangles = np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]
    vertices = np.asarray(mesh.points)[triangles]
    vectors = np.cross(vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0])
    lengths = np.linalg.norm(vectors, axis=1)
    return np.divide(vectors, lengths[:, None], out=np.zeros_like(vectors), where=lengths[:, None] > 1e-12)


def _crossing_paths(first, second):
    """Retorna polilinhas transversais, descartando faces coplanares."""
    first = first.triangulate()
    crossing = vtk.vtkIntersectionPolyDataFilter()
    crossing.SetInputData(0, first)
    crossing.SetInputData(1, second)
    crossing.SplitFirstOutputOff()
    crossing.SplitSecondOutputOff()
    crossing.Update()
    if not crossing.GetOutput().GetNumberOfCells():
        return
    intersection = pv.wrap(crossing.GetOutput())
    first_ids = np.asarray(intersection.cell_data['Input0CellID'], dtype=int)
    second_ids = np.asarray(intersection.cell_data['Input1CellID'], dtype=int)
    valid = (first_ids >= 0) & (second_ids >= 0)
    indices = np.flatnonzero(valid)
    first_normals, second_normals = _normals(first), _normals(second)
    valid[indices] &= np.linalg.norm(
        np.cross(first_normals[first_ids[indices]], second_normals[second_ids[indices]]), axis=1
    ) > 1e-8
    if not np.any(valid):
        return
    owners = np.asarray(second.cell_data['_intersection_owner'], dtype=int)
    valid_indices = np.flatnonzero(valid)
    for owner in np.unique(owners[second_ids[valid_indices]]):
        filtered = vtk.vtkPolyData()
        filtered.SetPoints(crossing.GetOutput().GetPoints())
        selected_lines = vtk.vtkCellArray()
        for index in valid_indices[owners[second_ids[valid_indices]] == owner]:
            selected_lines.InsertNextCell(crossing.GetOutput().GetCell(int(index)).GetPointIds())
        filtered.SetLines(selected_lines)
        stripper = vtk.vtkStripper()
        stripper.SetInputData(filtered)
        stripper.JoinContiguousSegmentsOn()
        stripper.Update()
        polyline = stripper.GetOutput()
        ids = vtk.vtkIdList()
        cells = polyline.GetLines()
        cells.InitTraversal()
        while cells.GetNextCell(ids):
            yield int(owner), np.asarray([polyline.GetPoint(ids.GetId(i)) for i in range(ids.GetNumberOfIds())])


def _dash_path(path, dash_points, lines, ownership, pair):
    if len(path) < 2:
        return
    vectors = np.diff(path, axis=0)
    lengths = np.linalg.norm(vectors, axis=1)
    total = float(lengths.sum())
    if total <= 1e-6:
        return
    dash = 0.025  # Comprimento fixo de 25 mm nas unidades do modelo (m).
    period = 2 * dash
    position = 0.0
    current = []
    current_length = 0.0

    def finish():
        nonlocal current, current_length
        # A sliver left at a triangulation edge or endpoint reads as a square.
        if len(current) >= 2 and current_length >= dash * 0.25:
            first = len(dash_points)
            dash_points.extend(current)
            lines.extend((len(current), *range(first, first + len(current))))
            ownership.append(pair)
        current = []
        current_length = 0.0

    for start, delta, length in zip(path[:-1], vectors, lengths):
        if length <= 1e-12:
            continue
        offset = 0.0
        while offset < length - 1e-12:
            phase = (position + offset) % period
            remaining = dash - phase if phase < dash else period - phase
            step = min(remaining, length - offset)
            if step <= 1e-12:
                step = min(period * 1e-8, length - offset)
            if phase < dash:
                start_point = start + delta * (offset / length)
                end_point = start + delta * ((offset + step) / length)
                if not current:
                    current.append(start_point)
                current.append(end_point)
                current_length += step
            elif current:
                finish()
            offset += step
        position += length
    finish()


def _member_edge_segments(batch, names):
    """Mapeia as arestas sólidas de cada barra em segmentos 3D."""
    mesh = getattr(batch, "edges", None)
    if mesh is None or not hasattr(batch, "edge_cell_ranges"):
        return {name: np.empty((0, 2, 3), dtype=float) for name in names}
    connectivity = np.asarray(mesh.lines, dtype=np.int64)
    points = np.asarray(mesh.points, dtype=float)
    ranges = {name: batch.edge_cell_ranges.get(name, (0, 0)) for name in names}
    segments = {name: [] for name in names}
    if not len(connectivity):
        return {name: np.empty((0, 2, 3), dtype=float) for name in names}

    cell_ranges = sorted(
        (start, end, name)
        for name, (start, end) in ranges.items()
        if end > start
    )
    cursor = 0
    cell_index = 0
    range_index = 0
    while cursor < len(connectivity):
        count = int(connectivity[cursor])
        ids = connectivity[cursor + 1:cursor + count + 1]
        while range_index < len(cell_ranges) and cell_ranges[range_index][1] <= cell_index:
            range_index += 1
        if range_index < len(cell_ranges):
            start, end, name = cell_ranges[range_index]
            if start <= cell_index < end:
                segments[name].extend(np.stack((points[ids[:-1]], points[ids[1:]]), axis=1))
        cursor += count + 1
        cell_index += 1
    return {
        name: np.asarray(value, dtype=float).reshape(-1, 2, 3)
        for name, value in segments.items()
    }


def _without_member_edges(path, edge_segments):
    """Recorta apenas as partes da interseção coincidentes com arestas sólidas."""
    if not len(edge_segments):
        yield path
        return

    current = []
    for start, end in zip(path[:-1], path[1:]):
        vector = end - start
        length_squared = float(np.dot(vector, vector))
        if length_squared <= 1e-18:
            continue
        length = np.sqrt(length_squared)
        relative = edge_segments - start
        parameters = np.einsum("ijk,k->ij", relative, vector) / length_squared
        residual = relative - parameters[:, :, None] * vector
        # 0,01 mm de tolerância para arredondamento das malhas.
        on_line = np.all(np.linalg.norm(residual, axis=2) <= 1e-5, axis=1)
        low = np.maximum(np.min(parameters, axis=1), 0.0)
        high = np.minimum(np.max(parameters, axis=1), 1.0)
        overlaps = sorted(zip(low[on_line & ((high - low) * length > 1e-8)],
                              high[on_line & ((high - low) * length > 1e-8)]))
        position = 0.0
        for low_bound, high_bound in overlaps:
            if low_bound > position + 1e-10:
                if not current:
                    current.append(start + position * vector)
                current.append(start + low_bound * vector)
            if high_bound > position:
                if len(current) >= 2:
                    yield np.asarray(current)
                current = []
                position = high_bound
        if position < 1.0 - 1e-10:
            if not current:
                current.append(start + position * vector)
            current.append(end)
    if len(current) >= 2:
        yield np.asarray(current)


def dashed_plate_member_intersections(plate_meshes, batch, *, include_member_pairs=False) -> pv.PolyData:
    """Agrupa cruzamentos entre superfícies, sem alterar o modelo estrutural.

    Com ``include_member_pairs``, também representa encontros barra–barra. As
    caixas delimitadoras descartam pares distantes e contatos apenas tangenciais.
    """
    if batch is None or not batch.face_point_ranges or not batch.faces.n_cells:
        return pv.PolyData()
    points = np.asarray(batch.faces.points)
    names, lows, highs = [], [], []
    for name, (start, end) in batch.face_point_ranges.items():
        if end <= start or name not in batch.face_cell_ranges:
            continue
        member_points = points[start:end]
        names.append(name)
        lows.append(member_points.min(axis=0))
        highs.append(member_points.max(axis=0))
    if not names:
        return pv.PolyData()
    lows, highs = np.asarray(lows), np.asarray(highs)
    member_indices = {name: index for index, name in enumerate(names)}
    edge_segments = _member_edge_segments(batch, names)
    dash_points, lines, ownership = [], [], []

    def append_crossings(source, candidates, source_owner=-1, plate_owner=-1):
        if not len(candidates):
            return
        members = _surface_for_members(batch, [names[index] for index in candidates], member_indices)
        for owner, path in _crossing_paths(source, members):
            source_name = names[source_owner] if source_owner >= 0 else None
            edges = edge_segments[names[owner]]
            if source_name is not None:
                edges = np.concatenate((edge_segments[source_name], edges))
            for visible_path in _without_member_edges(path, edges):
                _dash_path(visible_path, dash_points, lines, ownership, (source_owner, owner, plate_owner))

    for plate_index, plate in enumerate(plate_meshes):
        if not plate.n_cells:
            continue
        bounds = np.asarray(plate.bounds).reshape(3, 2)
        overlap = np.minimum(highs, bounds[:, 1]) - np.maximum(lows, bounds[:, 0])
        append_crossings(plate, np.flatnonzero(np.all(overlap > 1e-9, axis=1)), plate_owner=plate_index)

    if include_member_pairs:
        # Each pair occurs once. The first axis is sorted to avoid testing every
        # possible pair of widely separated bars in large scenes.
        order = np.argsort(lows[:, 0], kind='stable')
        sorted_starts = lows[order, 0]
        for position, index in enumerate(order):
            stop = np.searchsorted(sorted_starts, highs[index, 0] - 1e-9, side='left')
            candidates = order[position + 1:stop]
            if not len(candidates):
                continue
            overlap = np.minimum(highs[candidates], highs[index]) - np.maximum(lows[candidates], lows[index])
            candidates = candidates[np.all(overlap > 1e-9, axis=1)]
            if len(candidates):
                append_crossings(_surface_for_members(batch, [names[index]], member_indices), candidates, index)
    if not lines:
        return pv.PolyData()
    result = pv.PolyData(np.asarray(dash_points))
    result.verts = np.empty(0, dtype=np.int64)
    result.lines = np.asarray(lines)
    pairs = np.asarray(ownership, dtype=np.int32)
    result.cell_data['member_a'] = pairs[:, 0]
    result.cell_data['member_b'] = pairs[:, 1]
    result.cell_data['plate'] = pairs[:, 2]
    return result
