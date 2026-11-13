"""Shared solid meshes for visual node components."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pyvista as pv
import vtk

from osa.domain.node_components import base_plate_anchor_offsets, default_hook_headings

_BASE_PLATE_PLANE_BASES = {
    # Map the plate's local X, Y and positive thickness axes to global axes.
    "XY+": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "XY-": ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)),
    "XZ+": ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "XZ-": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "YZ+": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    "YZ-": ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0), (-1.0, 0.0, 0.0)),
}


def _orient_base_plate_mesh(mesh: pv.PolyData, origin, plane: str) -> None:
    basis = np.asarray(_BASE_PLATE_PLANE_BASES.get(plane, _BASE_PLATE_PLANE_BASES["XY+"]))
    rotation = basis.T
    point_origin = np.asarray(origin, dtype=float)
    mesh.points = (np.asarray(mesh.points) - point_origin) @ rotation.T + point_origin
    for attributes in (mesh.point_data, mesh.cell_data):
        normals = attributes.get("Normals")
        if normals is not None and normals.ndim == 2 and normals.shape[1] == 3:
            attributes["Normals"] = np.asarray(normals) @ rotation.T


def _annular_prism(
    center: tuple[float, float], z: float, thickness: float,
    outer_points: np.ndarray, inner_radius: float,
) -> pv.PolyData:
    count = len(outer_points)
    angles = np.arctan2(outer_points[:, 1], outer_points[:, 0])
    inner_points = np.column_stack((np.cos(angles), np.sin(angles))) * inner_radius
    cx, cy = center
    outer_bottom = np.column_stack((outer_points + (cx, cy), np.full(count, z)))
    outer_top = outer_bottom.copy()
    outer_top[:, 2] += thickness
    inner_bottom = np.column_stack((inner_points + (cx, cy), np.full(count, z)))
    inner_top = inner_bottom.copy()
    inner_top[:, 2] += thickness
    points = np.vstack((outer_bottom, outer_top, inner_bottom, inner_top))
    faces: list[int] = []
    for index in range(count):
        nxt = (index + 1) % count
        faces.extend((4, count + index, count + nxt, 3 * count + nxt, 3 * count + index))
        faces.extend((4, index, 2 * count + index, 2 * count + nxt, nxt))
        faces.extend((4, index, nxt, count + nxt, count + index))
        faces.extend((4, 2 * count + index, 3 * count + index, 3 * count + nxt, 2 * count + nxt))
    mesh = pv.PolyData(points, np.asarray(faces, dtype=np.int64))
    return mesh.compute_normals(
        cell_normals=True, point_normals=False, consistent_normals=True,
        auto_orient_normals=True, inplace=False,
    )


@lru_cache(maxsize=64)
def _annular_prism_template(
    outer_points: tuple[tuple[float, float], ...], thickness: float, inner_radius: float,
) -> pv.PolyData:
    return _annular_prism((0.0, 0.0), 0.0, thickness, np.asarray(outer_points), inner_radius)


def _placed_mesh(
    template: pv.PolyData, translation: tuple[float, float, float], rotation_degrees: float = 0.0,
) -> pv.PolyData:
    """Copy a cached local mesh into place without running a VTK transform filter."""
    mesh = template.copy(deep=True)
    points = np.asarray(mesh.points).copy()
    if rotation_degrees:
        angle = math.radians(rotation_degrees)
        cosine, sine = math.cos(angle), math.sin(angle)
        x, y = points[:, 0].copy(), points[:, 1].copy()
        points[:, 0] = cosine * x - sine * y
        points[:, 1] = sine * x + cosine * y
        for attributes in (mesh.point_data, mesh.cell_data):
            normals = attributes.get("Normals")
            if normals is not None and normals.ndim == 2 and normals.shape[1] == 3:
                normal_x, normal_y = normals[:, 0].copy(), normals[:, 1].copy()
                normals[:, 0] = cosine * normal_x - sine * normal_y
                normals[:, 1] = sine * normal_x + cosine * normal_y
    points += np.asarray(translation, dtype=float)
    mesh.points = points
    return mesh


@lru_cache(maxsize=32)
def _straight_fastener_template(radius: float, length: float) -> pv.PolyData:
    return pv.Cylinder(
        center=(0.0, 0.0, length / 2.0), direction=(0.0, 0.0, 1.0),
        radius=radius, height=length, resolution=48,
    )


@lru_cache(maxsize=64)
def _hook_fastener_template(
    diameter: float, length: float, embedment: float, leg: float,
) -> pv.PolyData:
    radius = min(diameter * 1.5, leg, length * 0.95)
    rod_bottom = -embedment
    bend_start_z = rod_bottom + radius
    top_z = rod_bottom + length
    path = [(0.0, 0.0, top_z), (0.0, 0.0, bend_start_z)]
    for step in range(1, 25):
        angle = math.pi + (math.pi / 2.0) * step / 24.0
        path.append((
            radius + radius * math.cos(angle), 0.0,
            bend_start_z + radius * math.sin(angle),
        ))
    path.append((leg, 0.0, rod_bottom))
    points = np.asarray(path, dtype=float)
    lines = np.concatenate((
        np.asarray((len(points),), dtype=np.int64),
        np.arange(len(points), dtype=np.int64),
    ))
    return pv.PolyData(points, lines=lines).tube(
        radius=diameter / 2.0, n_sides=48, capping=True,
    ).triangulate()


def append_polydata_meshes(meshes: tuple[pv.PolyData, ...]) -> pv.PolyData:
    """Combine disconnected polygonal parts into one renderable mesh."""
    if not meshes:
        return pv.PolyData()
    if len(meshes) == 1:
        return meshes[0]
    append = vtk.vtkAppendPolyData()
    for mesh in meshes:
        append.AddInputData(mesh)
    append.Update()
    return pv.wrap(append.GetOutput()).copy(deep=True)


def _regular_polygon_boundary(radius: float, sides: int, samples_per_side: int) -> np.ndarray:
    vertices = np.asarray([
        (radius * math.cos(2.0 * math.pi * index / sides + math.pi / 6.0),
         radius * math.sin(2.0 * math.pi * index / sides + math.pi / 6.0))
        for index in range(sides)
    ])
    return np.asarray([
        vertices[index] * (1.0 - step / samples_per_side)
        + vertices[(index + 1) % sides] * (step / samples_per_side)
        for index in range(sides) for step in range(samples_per_side)
    ])


def base_plate_component_meshes(
    parameters: dict[str, object], origin: tuple[float, float, float],
) -> tuple[pv.PolyData, tuple[pv.PolyData, ...], tuple[pv.PolyData, ...], tuple[pv.PolyData, ...]]:
    """Return the plate and solid fastener parts, positioned at the node."""
    width = float(parameters.get("largura_mm", 300.0)) / 1000.0
    length = float(parameters.get("comprimento_mm", 300.0)) / 1000.0
    thickness = float(parameters.get("espessura_mm", 20.0)) / 1000.0
    rotation = math.radians(float(parameters.get("rotacao_deg", 0.0)))
    diameter = float(parameters.get("diametro_mm", 16.0)) / 1000.0
    fastener_length = float(parameters.get("comprimento_fixador_mm", 300.0)) / 1000.0
    embedment = float(parameters.get("embutimento_mm", 150.0)) / 1000.0
    leg = float(parameters.get("perna_mm", 200.0)) / 1000.0
    fastener_kind = str(parameters.get("fixador", "Reto"))
    displacement_a = float(parameters.get("deslocamento_a_mm", 0.0)) / 1000.0
    displacement_b = float(parameters.get("deslocamento_b_mm", 0.0)) / 1000.0
    washer_diameter, washer_thickness = diameter * 1.9, diameter * 0.15
    nut_diameter, nut_height = diameter * 1.7, diameter * 0.8
    ox, oy, oz = origin
    cosine, sine = math.cos(rotation), math.sin(rotation)

    def rotate_xy(x: float, y: float) -> tuple[float, float]:
        return x * cosine - y * sine, x * sine + y * cosine

    shift_x, shift_y = rotate_xy(displacement_a, displacement_b)
    center_x, center_y = ox + shift_x, oy + shift_y
    plate = pv.Cube(
        center=(center_x, center_y, oz + thickness / 2.0), x_length=width,
        y_length=length, z_length=thickness,
    )
    if rotation:
        plate.rotate_z(math.degrees(rotation), point=(center_x, center_y, oz), inplace=True)

    anchor_offsets = tuple(
        (x / 1000.0, y / 1000.0) for x, y in base_plate_anchor_offsets(parameters)
    )
    hook_headings = default_hook_headings(parameters)
    anchors = [
        (center_x + dx, center_y + dy)
        for dx, dy in (rotate_xy(x, y) for x, y in anchor_offsets)
    ]
    rods: list[pv.PolyData] = []
    washers: list[pv.PolyData] = []
    nuts: list[pv.PolyData] = []
    outer_circle = np.column_stack((
        washer_diameter / 2.0 * np.cos(np.linspace(0.0, 2.0 * math.pi, 48, endpoint=False)),
        washer_diameter / 2.0 * np.sin(np.linspace(0.0, 2.0 * math.pi, 48, endpoint=False)),
    ))
    washer_template = _annular_prism_template(
        tuple(map(tuple, outer_circle.tolist())), washer_thickness, diameter * 0.55,
    )
    nut_boundary = _regular_polygon_boundary(nut_diameter / 2.0, 6, 8)
    nut_template = _annular_prism_template(
        tuple(map(tuple, nut_boundary.tolist())), nut_height, diameter * 0.525,
    )
    hook_template = (
        _hook_fastener_template(diameter, fastener_length, embedment, leg)
        if fastener_kind == "Gancho" else None
    )
    straight_template = (
        _straight_fastener_template(diameter / 2.0, fastener_length)
        if fastener_kind != "Gancho" else None
    )
    for index, ((local_x, local_y), (x, y)) in enumerate(zip(anchor_offsets, anchors)):
        rod_bottom = oz - embedment
        if fastener_kind == "Gancho":
            radial_length = math.hypot(local_x, local_y)
            radial_x, radial_y = local_x / radial_length, local_y / radial_length
            default_heading = math.degrees(math.atan2(radial_y, radial_x)) % 360.0
            global_key = f"rotacao_global_gancho_{index}_deg"
            legacy_key = f"rotacao_gancho_{index}_deg"
            if global_key in parameters:
                heading = float(parameters[global_key])
            elif legacy_key in parameters:
                heading = default_heading + float(parameters[legacy_key])
            else:
                heading = hook_headings[index] + float(parameters.get("rotacao_gancho_deg", 0.0))
            rods.append(_placed_mesh(
                hook_template, (x, y, oz), (heading + math.degrees(rotation)) % 360.0,
            ))
        else:
            rods.append(_placed_mesh(straight_template, (x, y, rod_bottom)))

        washers.append(_placed_mesh(washer_template, (x, y, oz + thickness)))

        nuts.append(_placed_mesh(nut_template, (x, y, oz + thickness + washer_thickness)))
    plane = str(parameters.get("plano", "XY+"))
    for mesh in (plate, *rods, *washers, *nuts):
        _orient_base_plate_mesh(mesh, origin, plane)
    return plate, tuple(rods), tuple(washers), tuple(nuts)
