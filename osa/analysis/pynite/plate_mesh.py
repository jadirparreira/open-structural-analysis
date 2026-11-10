"""Geração de malhas quadrilaterais conformes para as placas do modelo."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from itertools import pairwise

import numpy as np

_GMSH_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class PlateMesh:
    nodes: np.ndarray
    elements: dict[str, tuple[tuple[int, int, int, int], ...]]


def generate_plate_mesh(plates, *, max_element_size: float | None = None) -> PlateMesh:
    """Mesh all plates together so shared edges receive shared nodes.

    Gmsh's Python module owns process-global state, so initialization, model
    construction and finalization are serialized. The returned arrays contain
    only primitive values and can safely be consumed by the PyNite builder.
    """
    if not plates:
        return PlateMesh(np.empty((0, 3), dtype=float), {})
    sizes_by_plate = {}
    if max_element_size is None:
        for plate in plates.values():
            points = np.asarray(plate.contour, dtype=float)
            centered = points - points[0]
            _, singular, basis = np.linalg.svd(centered, full_matrices=False)
            if len(singular) < 2 or singular[1] <= 1e-8:
                raise ValueError(f"O contorno da laje '{plate.name}' não possui área suficiente para gerar a malha.")
            dimensions = np.ptp(centered @ basis[:2].T, axis=0)
            sizes_by_plate[plate.name] = max(
                0.05, min(float(dimensions.max()) / 6.0, float(dimensions.min()) / 3.0),
            )
        max_element_size = max(sizes_by_plate.values())
    else:
        sizes_by_plate = {plate.name: max_element_size for plate in plates.values()}
    if not math.isfinite(max_element_size) or max_element_size <= 0:
        raise ValueError("O tamanho máximo dos elementos da laje deve ser positivo.")

    try:
        import gmsh
    except (ImportError, OSError) as error:
        raise RuntimeError("O gerador de malhas Gmsh não está disponível neste ambiente.") from error

    with _GMSH_LOCK:
        initialized_here = not gmsh.isInitialized()
        if initialized_here:
            # Analysis runs in a QThread. Gmsh's default interrupt handler
            # installs Python signal handlers, which are restricted to the
            # main interpreter thread and make the first analysis fail.
            gmsh.initialize(interruptible=False)
        model_name = "osa_plates"
        try:
            gmsh.model.add(model_name)
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("Mesh.Algorithm", 8)
            gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 2)
            gmsh.option.setNumber("Mesh.RecombineAll", 1)
            gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 1)
            gmsh.option.setNumber("Mesh.MeshSizeMin", min(sizes_by_plate.values()) * 0.35)
            gmsh.option.setNumber("Mesh.MeshSizeMax", max_element_size)
            gmsh.option.setNumber("Mesh.ElementOrder", 1)

            point_tags: dict[tuple[int, int, int], int] = {}
            point_sizes: dict[tuple[int, int, int], float] = {}
            curve_tags: dict[tuple[tuple[int, int, int], tuple[int, int, int]], int] = {}
            surface_tags: dict[str, int] = {}
            all_contour_points = [
                np.asarray(point, dtype=float)
                for plate in plates.values() for point in plate.contour
            ]

            def key(point) -> tuple[int, int, int]:
                return tuple(round(float(value) * 1e8) for value in point)

            def point_tag(point, mesh_size) -> int:
                point_key = key(point)
                tag = point_tags.get(point_key)
                if tag is None:
                    tag = gmsh.model.geo.addPoint(*map(float, point), mesh_size)
                    point_tags[point_key] = tag
                    point_sizes[point_key] = mesh_size
                else:
                    point_sizes[point_key] = min(point_sizes[point_key], mesh_size)
                return tag

            for plate in plates.values():
                mesh_size = sizes_by_plate[plate.name]
                contour = _canonical_contour(plate.contour)
                loop_curves = []
                for index, start in enumerate(contour):
                    end = contour[(index + 1) % len(contour)]
                    start_vector = np.asarray(start, dtype=float)
                    edge_vector = np.asarray(end, dtype=float) - start_vector
                    edge_length_squared = float(np.dot(edge_vector, edge_vector))
                    split_points = [(0.0, start_vector), (1.0, np.asarray(end, dtype=float))]
                    if edge_length_squared > 0.0:
                        for point in all_contour_points:
                            ratio = float(np.dot(point - start_vector, edge_vector) / edge_length_squared)
                            projected = start_vector + ratio * edge_vector
                            if 1e-8 < ratio < 1.0 - 1e-8 and np.linalg.norm(point - projected) <= 1e-7:
                                split_points.append((ratio, point))
                    split_points.sort(key=lambda item: item[0])
                    unique_split_points = []
                    for split_point in split_points:
                        if unique_split_points and abs(split_point[0] - unique_split_points[-1][0]) <= 1e-8:
                            continue
                        unique_split_points.append(split_point)
                    for (_, first), (_, second) in pairwise(unique_split_points):
                        first_key, second_key = key(first), key(second)
                        edge_key = (first_key, second_key) if first_key < second_key else (second_key, first_key)
                        tag = curve_tags.get(edge_key)
                        if tag is None:
                            ordered_points = (first, second) if first_key < second_key else (second, first)
                            tag = gmsh.model.geo.addLine(
                                point_tag(ordered_points[0], mesh_size),
                                point_tag(ordered_points[1], mesh_size),
                            )
                            curve_tags[edge_key] = tag
                        loop_curves.append(tag if first_key < second_key else -tag)
                loop = gmsh.model.geo.addCurveLoop(loop_curves)
                surface_tags[plate.name] = gmsh.model.geo.addPlaneSurface([loop])

            gmsh.model.geo.synchronize()
            for point_key, tag in point_tags.items():
                gmsh.model.mesh.setSize([(0, tag)], point_sizes[point_key])
            gmsh.model.mesh.generate(2)

            node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
            nodes = np.asarray(coordinates, dtype=float).reshape(-1, 3)
            node_index = {int(tag): index for index, tag in enumerate(node_tags)}
            elements_by_plate: dict[str, tuple[tuple[int, int, int, int], ...]] = {}
            for name, surface_tag in surface_tags.items():
                local_x, local_y, _normal = _plate_local_basis(plates[name].contour)
                element_types, _, element_nodes = gmsh.model.mesh.getElements(2, surface_tag)
                quads: list[tuple[int, int, int, int]] = []
                for element_type, tags in zip(element_types, element_nodes):
                    properties = gmsh.model.mesh.getElementProperties(int(element_type))
                    node_count = int(properties[3])
                    if int(element_type) != 3 or node_count != 4:
                        raise ValueError(
                            f"A malha da laje '{name}' contém elementos que não são quadriláteros lineares. "
                            "Ajuste o contorno ou o tamanho da malha."
                        )
                    connectivity = np.asarray(tags, dtype=np.int64).reshape(-1, 4)
                    quads.extend(
                        _orient_quad(
                            tuple(node_index[int(tag)] for tag in row), nodes,
                            local_x, local_y,
                        )
                        for row in connectivity
                    )
                if not quads:
                    raise ValueError(f"Não foi possível gerar elementos para a laje '{name}'.")
                elements_by_plate[name] = tuple(quads)
            return PlateMesh(nodes, elements_by_plate)
        finally:
            try:
                gmsh.model.remove()
            finally:
                if initialized_here:
                    gmsh.finalize()


def _canonical_contour(contour):
    points = np.asarray(contour, dtype=float)
    normal = np.zeros(3, dtype=float)
    for index, point in enumerate(points):
        normal += np.cross(point - points[0], points[(index + 1) % len(points)] - points[0])
    dominant_axis = int(np.argmax(np.abs(normal)))
    return tuple(tuple(point) for point in (points if normal[dominant_axis] >= 0 else points[::-1]))


def _plate_local_basis(contour):
    """Create a deterministic plate basis aligned with global X when possible."""
    points = np.asarray(_canonical_contour(contour), dtype=float)
    normal = np.zeros(3, dtype=float)
    for index, point in enumerate(points):
        normal += np.cross(point - points[0], points[(index + 1) % len(points)] - points[0])
    normal /= np.linalg.norm(normal)
    local_x = np.array((1.0, 0.0, 0.0))
    local_x -= np.dot(local_x, normal) * normal
    if np.linalg.norm(local_x) <= 1e-8:
        local_x = np.array((0.0, 1.0, 0.0))
        local_x -= np.dot(local_x, normal) * normal
    local_x /= np.linalg.norm(local_x)
    local_y = np.cross(normal, local_x)
    return local_x, local_y, normal


def _orient_quad(connectivity, nodes, local_x, local_y):
    """Align each quad's local x axis with the same plate-wide direction.

    PyNite defines a Quad's local x direction from node i to node j. Gmsh may
    start neighboring quads on different edges, which otherwise swaps local
    x/y result components from element to element. Preserve the cyclic order,
    orient it to the plate normal, then rotate the node sequence so i->j is
    the edge most aligned with the plate's local x axis.
    """
    ordered = list(connectivity)
    points = np.asarray([nodes[index] for index in ordered], dtype=float)
    planar = np.column_stack((points @ local_x, points @ local_y))
    signed_area = 0.5 * sum(
        planar[index, 0] * planar[(index + 1) % 4, 1]
        - planar[(index + 1) % 4, 0] * planar[index, 1]
        for index in range(4)
    )
    if signed_area < 0:
        ordered.reverse()
        points = points[::-1]
    edges = np.roll(points, -1, axis=0) - points
    directions = edges @ local_x
    start = int(np.argmax(directions))
    return tuple(ordered[start:] + ordered[:start])
