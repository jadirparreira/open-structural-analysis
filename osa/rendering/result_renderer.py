"""Sobreposições gráficas dos resultados de análise."""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pyvista as pv

from osa.sections import section_shape

from .local_axes_renderer import LocalAxesRenderer
from .result_color_map import RESULT_COLOR_STOPS, RESULT_MESH_COLOR, result_colors
from .solid_member_renderer import SolidMemberRenderer


class ResultRenderer:
    """Renderiza diagramas de esforços internos sobre os eixos locais."""

    def __init__(self) -> None:
        self._solid_member_renderer = SolidMemberRenderer()

    POSITIVE_COLOR = "#0969da"
    NEGATIVE_COLOR = "#cf222e"
    MAX_HEIGHT = 1.0
    REACTION_FORCE_LENGTH = 0.50
    REACTION_MOMENT_DIAMETER = 0.50
    REACTION_LABEL_CLEARANCE = 0.12
    DEFORMATION_COLOR = "#8250df"
    UNDEFORMED_COLOR = "#8c959f"
    PLATE_CONTOUR_SUBDIVISIONS = 8
    _millimeters_to_model_units = 1e-3
    DISPLAY_DECIMALS = 3
    DIAGRAMS: ClassVar[dict[str, tuple[str, int, str, float, float]]] = {
        "Normal": ("axial", 1, "kN", 1.0, 1.0),
        "Cortante Y": ("shear_y", 1, "kN", 1.0, 1.0),
        "Cortante Z": ("shear_z", 2, "kN", 1.0, 1.0),
        # O momento torsor atua em torno de X; a faixa é projetada em Y
        # apenas como plano de leitura do seu valor escalar.
        "Torsor": ("torque", 1, "kN·m", 1.0, 1.0),
        # Momentos são exibidos no plano perpendicular ao seu eixo de ação.
        # A convenção gráfica brasileira adota momento superior negativo e
        # inferior positivo, sinal oposto ao retornado pelo PyNite.
        "Fletor Y": ("moment_y", 2, "kN·m", -1.0, 1.0),
        "Fletor Z": ("moment_z", 1, "kN·m", -1.0, 1.0),
    }
    REACTION_DIAGRAM = "Reações de apoio"
    _REACTION_FORCE_KEYS: ClassVar[tuple[str, ...]] = ("RXN_FX", "RXN_FY", "RXN_FZ")
    _REACTION_MOMENT_KEYS: ClassVar[tuple[str, ...]] = ("RXN_MX", "RXN_MY", "RXN_MZ")

    def render(
        self, plotter, model, result, diagram: str, *, solid_members_visible: bool = True,
        deformation_scale: float = 1.0, bar_diagrams_visible: bool = True,
        diagram_scale: float = 1.0,
        plate_diagrams_visible: bool = False,
        include_plate_surfaces: bool = True,
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        if result is None:
            return [], np.empty((0, 3)), ()
        if diagram.startswith("Deformação"):
            components = diagram.removeprefix("Deformação ") or "XYZ"
            return self._render_deformation(
                plotter, model, result, components, solid_members_visible,
                deformation_scale, bar_diagrams_visible, plate_diagrams_visible,
                include_plate_surfaces,
            )
        if diagram == self.REACTION_DIAGRAM:
            return self._render_reactions(plotter, model, result)
        if diagram not in self.DIAGRAMS:
            return [], np.empty((0, 3)), ()
        result_key, axis_index, unit, display_sign, geometry_sign = self.DIAGRAMS[diagram]
        samples_by_member = {
            name: values.get("samples", ())
            for name, values in result.member_results.items()
            if name in model.bars
        }
        maximum = max(
            (
                abs(self._display_value(float(sample.get(result_key, 0.0)) * display_sign))
                for samples in samples_by_member.values()
                for sample in samples
            ),
            default=0.0,
        )
        scale = (
            self.MAX_HEIGHT * max(0.1, min(1.0, float(diagram_scale))) / maximum
            if maximum > 0.0
            else 0.0
        )
        actors: list[object] = []
        face_batches: dict[str, tuple[list[np.ndarray], list[int]]] = {
            self.POSITIVE_COLOR: ([], []), self.NEGATIVE_COLOR: ([], []),
        }
        line_batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]] = {
            (self.POSITIVE_COLOR, 2.5): ([], []),
            (self.NEGATIVE_COLOR, 2.5): ([], []),
        }
        label_positions: list[np.ndarray] = []
        labels: list[str] = []
        endpoint_nodes: list[str | None] = []
        for name, samples in samples_by_member.items():
            member = model.bars.get(name)
            if member is None or len(samples) < 2:
                continue
            start_node, end_node = model.nodes[member.start_node], model.nodes[member.end_node]
            basis = LocalAxesRenderer.basis(start_node, end_node, member.rotation)
            if basis is None:
                continue
            local_x, local_y, local_z = basis
            diagram_axis = (local_y, local_z)[axis_index - 1]
            start = np.array((start_node.x, start_node.y, start_node.z), dtype=float)
            baseline = np.asarray([start + local_x * float(sample["x"]) for sample in samples])
            values = np.asarray([
                self._display_value(float(sample.get(result_key, 0.0)) * display_sign)
                for sample in samples
            ])
            geometry_values = np.asarray([
                self._display_value(float(sample.get(result_key, 0.0)) * geometry_sign)
                for sample in samples
            ])
            representative_value = float(values[np.argmax(np.abs(values))])
            center = len(values) // 2
            extreme = int(np.argmax(np.abs(values)))
            include_endpoints = diagram in {"Fletor Y", "Fletor Z"}
            # Mesmo sem faixa, o rótulo informa explicitamente que o esforço
            # naquela barra é nulo após o arredondamento de apresentação.
            if np.all(values == 0.0):
                label_positions.append(baseline[center] + diagram_axis * 0.10)
                labels.append(self._format_value(values[extreme], unit))
                endpoint_nodes.append(None)
                continue
            # O eixo analítico é a linha de referência do diagrama. A faixa
            # se projeta integralmente para um lado, tal como os diagramas de
            # esforço convencionais sobrepostos ao modelo.
            curve = baseline + diagram_axis * geometry_values[:, None] * scale
            if diagram == "Normal" and np.all(values == values[0]):
                color = self.NEGATIVE_COLOR if representative_value < 0.0 else self.POSITIVE_COLOR
                vertices = np.vstack((baseline, curve[::-1]))
                self._append_face(face_batches, color, vertices)
                # O contorno contínuo inclui as laterais nas duas extremidades,
                # deixando explícito o fechamento da faixa de esforço.
                outline_points = np.vstack((baseline, curve[::-1], baseline[0]))
                self._append_polyline(line_batches, (color, 2.5), outline_points)
            else:
                self._render_shear_geometry(face_batches, line_batches, baseline, curve, values)
            positions, member_labels = self._member_result_labels(
                values, geometry_values, baseline, curve, local_x, diagram_axis, unit,
                include_endpoints=include_endpoints,
            )
            label_positions.extend(positions)
            labels.extend(member_labels)
            endpoint_nodes.extend(
                member.start_node if index == 0 else member.end_node if index == len(values) - 1 else None
                for index in self._member_result_label_indices(values, include_endpoints=include_endpoints)
            )
        label_positions, labels = self._merge_shared_endpoint_labels(
            label_positions, labels, endpoint_nodes,
        )
        for color, (points, faces) in face_batches.items():
            if not points:
                continue
            face = pv.PolyData(np.asarray(points), faces=np.asarray(faces, dtype=np.int64))
            actors.append(plotter.add_mesh(
                face, color=color, opacity=0.30, lighting=False, pickable=False,
                reset_camera=False, render=False,
            ))
        for (color, line_width), (points, lines) in line_batches.items():
            if not points:
                continue
            line = pv.PolyData(np.asarray(points), lines=np.asarray(lines, dtype=np.int64))
            actors.append(plotter.add_mesh(
                line, color=color, line_width=line_width, lighting=False, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
            ))
        return actors, np.asarray(label_positions, dtype=float), tuple(labels)

    def result_range(
        self, result, diagram: str, display_mode: str = "nos_media_macro",
    ) -> tuple[float, float]:
        """Return the scalar range for the selected plate-result presentation."""
        values: list[float] = []
        if diagram.startswith("Deformação"):
            components = diagram.removeprefix("Deformação ") or "XYZ"
            plate_values = [
                self._deformation_scalar(node_values, components)
                for plate_result in result.plate_results.values()
                for node_values in plate_result.get("nodes", {}).values()
            ]
            # Bars and plates share one legend so the same displacement has
            # the same color regardless of which structural element carries it.
            values.extend(plate_values)
            values.extend(
                self._deformation_scalar(node_values, components)
                for node_values in result.node_results.values()
            )
            values.extend(
                self._deformation_scalar(sample, components)
                for member_result in result.member_results.values()
                for sample in member_result.get("samples", ())
            )
        else:
            macro_sums: dict[tuple[str, str], float] = {}
            macro_counts: dict[tuple[str, str], int] = {}
            node_sums: dict[str, float] = {}
            node_counts: dict[str, int] = {}
            for plate_name, plate_result in result.plate_results.items():
                element_values = self._plate_element_values(plate_result, diagram)
                if display_mode == "centros":
                    values.extend(center for center, _nodal in element_values.values())
                    continue
                for element_name, element in plate_result.get("elements", {}).items():
                    samples = element_values.get(element_name)
                    node_names = element.get("nodes", ())
                    if samples is None or len(node_names) != 4:
                        continue
                    _center, nodal = samples
                    values.extend(nodal)
                    for node_name, value in zip(node_names, nodal, strict=True):
                        key = (plate_name, node_name)
                        macro_sums[key] = macro_sums.get(key, 0.0) + value
                        macro_counts[key] = macro_counts.get(key, 0) + 1
                        node_sums[node_name] = node_sums.get(node_name, 0.0) + value
                        node_counts[node_name] = node_counts.get(node_name, 0) + 1
            if display_mode == "nos_media_macro":
                values = [macro_sums[key] / macro_counts[key] for key in macro_sums]
            elif display_mode == "nos_media":
                values = [node_sums[key] / node_counts[key] for key in node_sums]
        finite = np.asarray(values, dtype=float)
        finite = finite[np.isfinite(finite)]
        if not finite.size:
            return (0.0, 1.0)
        low, high = float(finite.min()), float(finite.max())
        return (low, high if high - low > 1e-12 else low + 1.0)

    def render_plate_contours(
        self, plotter, model, result, diagram: str, *, deformation_scale: float = 1.0,
        solid_members_visible: bool = True,
        value_range: tuple[float, float] | None = None,
        display_mode: str = "nos_media_macro",
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        """Render plate result contours using the selected FE interpolation mode."""
        if result is None:
            return [], np.empty((0, 3)), ()
        value_range = value_range or self.result_range(result, diagram, display_mode)
        components = diagram.removeprefix("Deformação ") if diagram.startswith("Deformação") else ""
        scale = max(1.0, min(100.0, float(deformation_scale)))
        actors: list[object] = []
        all_positions: list[np.ndarray] = []
        all_labels: list[str] = []
        plate_meshes = []
        macro_sums: dict[tuple[str, str], float] = {}
        macro_counts: dict[tuple[str, str], int] = {}
        node_sums: dict[str, float] = {}
        node_counts: dict[str, int] = {}
        for plate_name, plate_result in result.plate_results.items():
            plate = model.plates.get(plate_name)
            nodes = plate_result.get("nodes", {})
            elements = plate_result.get("elements", {})
            if plate is None or not nodes or not elements:
                continue
            node_names = tuple(nodes)
            node_index = {name: index for index, name in enumerate(node_names)}
            coordinates = np.asarray([
                nodes[name].get("coordinates", (0.0, 0.0, 0.0)) for name in node_names
            ], dtype=float)
            quads = [
                tuple(node_index[name] for name in element.get("nodes", ()))
                for element in elements.values()
                if len(element.get("nodes", ())) == 4
                and all(name in node_index for name in element["nodes"])
            ]
            if not quads:
                continue
            if components:
                base_scalars = np.asarray([
                    self._deformation_scalar(nodes[name], components) for name in node_names
                ], dtype=float)
                displacement = np.asarray([
                    self._deformation_vector(nodes[name], components) for name in node_names
                ], dtype=float)
                coordinates = coordinates + displacement * scale
                element_samples = {}
                for element_name, element in elements.items():
                    quad_names = element.get("nodes", ())
                    if len(quad_names) != 4 or not all(name in node_index for name in quad_names):
                        continue
                    nodal = tuple(base_scalars[node_index[name]] for name in quad_names)
                    element_samples[element_name] = (float(np.mean(nodal)), nodal)
            else:
                element_samples = self._plate_element_values(plate_result, diagram)
                if not element_samples:
                    continue
            sample_rows = []
            for element_name, element in elements.items():
                samples = element_samples.get(element_name)
                quad_names = element.get("nodes", ())
                if samples is None or len(quad_names) != 4 or not all(name in node_index for name in quad_names):
                    continue
                center, nodal = samples
                quad = tuple(node_index[name] for name in quad_names)
                sample_rows.append((quad, quad_names, center, nodal))
                for node_name, value in zip(quad_names, nodal, strict=True):
                    macro_key = (plate_name, node_name)
                    macro_sums[macro_key] = macro_sums.get(macro_key, 0.0) + value
                    macro_counts[macro_key] = macro_counts.get(macro_key, 0) + 1
                    node_sums[node_name] = node_sums.get(node_name, 0.0) + value
                    node_counts[node_name] = node_counts.get(node_name, 0) + 1
            if not sample_rows:
                continue
            plate_meshes.append((
                plate_name, plate_result, nodes, node_names, node_index, coordinates,
                sample_rows, displacement if components else None,
            ))

        for (
            plate_name, _plate_result, nodes, node_names, node_index, coordinates,
            sample_rows, displacement,
        ) in plate_meshes:
            if display_mode == "centros":
                mesh_faces = np.asarray([
                    value for quad, _names, _center, _nodal in sample_rows
                    for value in (4, *quad)
                ], dtype=np.int64)
                surface = pv.PolyData(coordinates, faces=mesh_faces)
                surface.cell_data["result_value"] = np.asarray(
                    [center for _quad, _names, center, _nodal in sample_rows], dtype=float,
                )
                scalar_preference = "cell"
                interpolate_before_map = False
            elif display_mode == "nos_sem_media":
                unshared_points = []
                unshared_faces = []
                unshared_values = []
                for _quad, quad_names, _center, nodal in sample_rows:
                    start = len(unshared_points)
                    unshared_points.extend(
                        coordinates[node_index[name]] for name in quad_names
                    )
                    unshared_faces.extend((4, start, start + 1, start + 2, start + 3))
                    unshared_values.extend(nodal)
                surface = pv.PolyData(
                    np.asarray(unshared_points, dtype=float),
                    faces=np.asarray(unshared_faces, dtype=np.int64),
                )
                surface.point_data["result_value"] = np.asarray(unshared_values, dtype=float)
                scalar_preference = "point"
                interpolate_before_map = True
                refinement_rows = sample_rows
            else:
                surface_faces = np.asarray([
                    value for quad, _names, _center, _nodal in sample_rows
                    for value in (4, *quad)
                ], dtype=np.int64)
                surface = pv.PolyData(coordinates, faces=surface_faces)
                if display_mode == "nos_media":
                    sums, counts = node_sums, node_counts
                else:
                    sums, counts = macro_sums, macro_counts
                node_values = np.asarray([
                    sums[(plate_name, name)] / counts[(plate_name, name)]
                    if display_mode == "nos_media_macro"
                    else sums[name] / counts[name]
                    for name in node_names
                ], dtype=float)
                surface.point_data["result_value"] = node_values
                scalar_preference = "point"
                interpolate_before_map = True
                refinement_rows = [
                    (
                        quad, names, center,
                        tuple(float(node_values[index]) for index in quad),
                    )
                    for quad, names, center, _nodal in sample_rows
                ]
            if scalar_preference == "point":
                # Refine each FE quad with bilinear shape functions so the
                # color bands and their isolines follow the same interpolation
                # instead of taking a diagonal shortcut across coarse quads.
                surface = self._refine_plate_result_surface(
                    coordinates, refinement_rows,
                )
            plate_opacity = 1.0 if solid_members_visible else 0.7
            surface_actor = plotter.add_mesh(
                surface, scalars="result_value", cmap=list(RESULT_COLOR_STOPS),
                n_colors=len(RESULT_COLOR_STOPS), clim=value_range,
                preference=scalar_preference,
                interpolate_before_map=interpolate_before_map,
                opacity=plate_opacity,
                smooth_shading=False, lighting=True, show_scalar_bar=False, pickable=False,
                reset_camera=False, render=False, name=f"result-plate:{plate_name}",
            )
            surface_actor.SetObjectName(f"result-plate:{plate_name}")
            actors.append(surface_actor)
            low, high = (float(value) for value in value_range)
            if scalar_preference == "point" and high - low > 1e-12:
                # Draw one continuous isoline at each boundary between the
                # displayed color bands. Scalar coloring reuses the surface
                # palette so every line stays in the same color family.
                interfaces = np.linspace(
                    low, high, len(RESULT_COLOR_STOPS) + 1,
                )[1:-1]
                interface_mesh = surface.contour(
                    isosurfaces=interfaces, scalars="result_value",
                )
                if interface_mesh.n_cells:
                    actor = plotter.add_mesh(
                        interface_mesh, scalars="result_value",
                        cmap=list(RESULT_COLOR_STOPS),
                        n_colors=len(RESULT_COLOR_STOPS), clim=value_range,
                        preference="point", line_width=1.5, opacity=1.0,
                        lighting=False, show_scalar_bar=False, pickable=False,
                        reset_camera=False, render=False,
                        name=f"result-plate-interfaces:{plate_name}",
                    )
                    mapper = actor.GetMapper()
                    mapper.SetResolveCoincidentTopologyToPolygonOffset()
                    mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
                    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
                    actors.append(actor)
            elif display_mode == "centros" and high - low > 1e-12:
                # Center-value plots have constant color per element, so
                # their color interfaces follow shared edges between elements.
                edge_bands: dict[tuple[int, int], list[int]] = {}
                for quad, _names, center, _nodal in sample_rows:
                    band = max(0, min(
                        int((float(center) - low) / (high - low) * len(RESULT_COLOR_STOPS)),
                        len(RESULT_COLOR_STOPS) - 1,
                    ))
                    for start, end in zip(quad, (quad[1], quad[2], quad[3], quad[0]), strict=True):
                        edge = (min(start, end), max(start, end))
                        edge_bands.setdefault(edge, []).append(band)
                edges_by_band: dict[int, list[tuple[int, int]]] = {}
                for edge, bands in edge_bands.items():
                    if len(bands) > 1 and min(bands) != max(bands):
                        edges_by_band.setdefault(max(bands), []).append(edge)
                for band, edges in edges_by_band.items():
                    line_mesh = pv.PolyData(
                        coordinates,
                        lines=np.asarray([
                            value for start, end in edges for value in (2, start, end)
                        ], dtype=np.int64),
                    )
                    actor = plotter.add_mesh(
                        line_mesh, color=RESULT_COLOR_STOPS[band],
                        line_width=1.5, opacity=1.0, lighting=False,
                        show_scalar_bar=False, pickable=False,
                        reset_camera=False, render=False,
                        name=f"result-plate-interfaces:{plate_name}:{band}",
                    )
                    mapper = actor.GetMapper()
                    mapper.SetResolveCoincidentTopologyToPolygonOffset()
                    mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
                    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
                    actors.append(actor)
            edge_pairs = {
                (min(start, end), max(start, end))
                for quad, _names, _center, _nodal in sample_rows
                for start, end in zip(quad, (quad[1], quad[2], quad[3], quad[0]), strict=True)
            }
            encoded_edges = np.asarray(
                [value for start, end in sorted(edge_pairs) for value in (2, start, end)],
                dtype=np.int64,
            )
            edge_mesh = pv.PolyData(coordinates, lines=encoded_edges)
            actors.append(plotter.add_mesh(
                edge_mesh, color=RESULT_MESH_COLOR, line_width=1.0,
                lighting=False, pickable=False, reset_camera=False, render=False,
                name=f"result-plate-mesh:{plate_name}",
            ))
            if components:
                magnitudes = np.linalg.norm(displacement, axis=1)
                maximum_index = int(np.argmax(magnitudes))
                if magnitudes[maximum_index] > 1e-12:
                    all_positions.append(coordinates[maximum_index])
                    all_labels.append(self._format_displacement(
                        self._deformation_display_value(nodes[node_names[maximum_index]], components),
                    ))
        return actors, np.asarray(all_positions, dtype=float).reshape(-1, 3), tuple(all_labels)

    @staticmethod
    def _deformation_vector(values, components: str) -> np.ndarray:
        return np.asarray((
            float(values.get("DX", values.get("deflection_x", 0.0))) if "X" in components else 0.0,
            float(values.get("DY", values.get("deflection_y", 0.0))) if "Y" in components else 0.0,
            float(values.get("DZ", values.get("deflection_z", 0.0))) if "Z" in components else 0.0,
        ), dtype=float)

    @classmethod
    def _deformation_scalar(cls, values, components: str) -> float:
        vector = cls._deformation_vector(values, components)
        if components == "XYZ":
            return float(np.linalg.norm(vector))
        return float(vector["XYZ".index(components)])

    @classmethod
    def _deformation_display_value(cls, values, components: str) -> float:
        return cls._deformation_scalar(values, components) * 1000.0

    @classmethod
    def _refine_plate_result_surface(cls, coordinates, sample_rows) -> pv.PolyData:
        """Build a bilinearly subdivided quad mesh for plate colors and isolines."""
        divisions = cls.PLATE_CONTOUR_SUBDIVISIONS
        local_axis = np.linspace(0.0, 1.0, divisions + 1)
        points: list[np.ndarray] = []
        values: list[float] = []
        faces: list[int] = []
        row_width = divisions + 1
        for quad, _names, _center, nodal in sample_rows:
            corners = np.asarray(coordinates[np.asarray(quad, dtype=int)], dtype=float)
            corner_values = np.asarray(nodal, dtype=float)
            start = len(points)
            for v in local_axis:
                for u in local_axis:
                    weights = np.asarray((
                        (1.0 - u) * (1.0 - v),
                        u * (1.0 - v),
                        u * v,
                        (1.0 - u) * v,
                    ))
                    points.append(weights @ corners)
                    values.append(float(weights @ corner_values))
            for row in range(divisions):
                for column in range(divisions):
                    lower_left = start + row * row_width + column
                    lower_right = lower_left + 1
                    upper_left = lower_left + row_width
                    upper_right = upper_left + 1
                    faces.extend((
                        4, lower_left, lower_right, upper_right, upper_left,
                    ))
        refined = pv.PolyData(
            np.asarray(points, dtype=float),
            faces=np.asarray(faces, dtype=np.int64),
        )
        refined.point_data["result_value"] = np.asarray(values, dtype=float)
        return refined

    @staticmethod
    def _plate_result_field(plate_result, diagram: str):
        field_by_diagram = {
            "Normal": ("membrane", 0),
            "Cortante Y": ("shear", 1),
            "Cortante Z": ("shear", 0),
            "Torsor": ("moment", 2),
            "Fletor Y": ("moment", 0),
            "Fletor Z": ("moment", 1),
        }
        field = field_by_diagram.get(diagram)
        if field is None:
            return None
        key, component = field
        # Keep plate flexural signs consistent with the convention used for
        # member Fletor Y/Z diagrams. PyNite's plate bending convention has
        # the opposite polarity to the convention used by this application.
        display_sign = -1.0 if diagram in {"Fletor Y", "Fletor Z"} else 1.0
        element_values = {}
        for name, element in plate_result.get("elements", {}).items():
            components = np.asarray(element.get(key, ()), dtype=float).reshape(-1)
            if len(components) <= component:
                continue
            element_values[name] = float(components[component]) * display_sign
        return (component, element_values) if element_values else None

    @classmethod
    def _plate_element_values(cls, plate_result, diagram: str):
        """Return each element's center value and its four extrapolated nodal values."""
        field = cls._plate_result_field(plate_result, diagram)
        nodal_field = cls._plate_result_nodal_field(plate_result, diagram)
        if field is None:
            return {}
        component, center_values = field
        nodal_values = nodal_field[1] if nodal_field is not None else {}
        result = {}
        for element_name, center in center_values.items():
            corners = nodal_values.get(element_name)
            if corners is None or len(corners) != 4:
                result[element_name] = (center, (center,) * 4)
            else:
                result[element_name] = (
                    center,
                    tuple(float(values[component]) for values in corners),
                )
        return result

    @staticmethod
    def _plate_result_nodal_field(plate_result, diagram: str):
        field_by_diagram = {
            "Normal": ("membrane_nodal", 0),
            "Cortante Y": ("shear_nodal", 1),
            "Cortante Z": ("shear_nodal", 0),
            "Torsor": ("moment_nodal", 2),
            "Fletor Y": ("moment_nodal", 0),
            "Fletor Z": ("moment_nodal", 1),
        }
        field = field_by_diagram.get(diagram)
        if field is None:
            return None
        key, component = field
        display_sign = -1.0 if diagram in {"Fletor Y", "Fletor Z"} else 1.0
        values_by_element = {}
        for name, element in plate_result.get("elements", {}).items():
            nodal = np.asarray(element.get(key, ()), dtype=float)
            if nodal.ndim != 2 or nodal.shape[0] != 4 or nodal.shape[1] <= component:
                continue
            if display_sign < 0.0:
                nodal = nodal.copy()
                nodal[:, component] *= display_sign
            values_by_element[name] = nodal
        return (component, values_by_element) if values_by_element else None

    def _render_reactions(self, plotter, model, result) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        """Renderiza reações nodais nos eixos globais, apontando para o nó.

        Reações só são relevantes visualmente em nós com pelo menos uma
        restrição (inclusive apoios elásticos). O sinal define a cor e o
        sentido do componente; a ponta da seta permanece no nó para que a
        leitura seja a mesma das cargas nodais globais.
        """
        supported_nodes = [
            node for node in model.nodes.values()
            if any(node.supports) or any(float(value) > 0.0 for value in node.support_stiffness)
        ]
        if not supported_nodes:
            return [], np.empty((0, 3)), ()

        node_values = {
            node.name: result.node_results.get(node.name, {})
            for node in supported_nodes
        }
        moment_radius = self.REACTION_MOMENT_DIAMETER * 0.5
        line_batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]] = {
            (self.POSITIVE_COLOR, 3.0): ([], []),
            (self.NEGATIVE_COLOR, 3.0): ([], []),
        }
        label_positions: list[np.ndarray] = []
        labels: list[str] = []
        global_basis = tuple(np.eye(3))

        for node in supported_nodes:
            values = node_values[node.name]
            node_position = np.asarray((node.x, node.y, node.z), dtype=float)
            for axis_index, key in enumerate(self._REACTION_FORCE_KEYS):
                value = self._display_value(float(values.get(key, 0.0)))
                if value == 0.0:
                    continue
                direction = np.zeros(3, dtype=float)
                direction[axis_index] = np.sign(value)
                # Reactions use a fixed visual scale. Their magnitude remains
                # available in the label and in the sign/color, but does not
                # change the length of the arrow.
                arrow_length = self.REACTION_FORCE_LENGTH
                line_start = node_position - direction * arrow_length
                chevron_size = arrow_length * 0.18
                chevron_normal = self._perpendicular_to(direction)
                arm_a = node_position - direction * chevron_size + chevron_normal * chevron_size * 0.55
                arm_b = node_position - direction * chevron_size - chevron_normal * chevron_size * 0.55
                points = np.asarray((line_start, node_position, arm_a, arm_b))
                lines = np.asarray((2, 0, 1, 2, 1, 2, 2, 1, 3), dtype=np.int64)
                self._append_lines(
                    line_batches, (self._result_color(value), 3.0), points, lines,
                )
                label_positions.append(line_start - direction * self.REACTION_LABEL_CLEARANCE)
                labels.append(self._format_force(value))

            for axis_index, key in enumerate(self._REACTION_MOMENT_KEYS):
                value = self._display_value(float(values.get(key, 0.0)))
                if value == 0.0:
                    continue
                axis, plane_u, plane_v = self._moment_plane(global_basis, "XYZ"[axis_index])
                points, lines = self._add_moment_symbol(
                    node_position, axis, plane_u, plane_v, value, moment_radius,
                )
                self._append_lines(
                    line_batches, (self._result_color(value), 3.0), points, lines,
                )
                label_direction = {
                    "X": global_basis[1],
                    "Y": global_basis[2],
                    "Z": global_basis[0],
                }["XYZ"[axis_index]]
                label_positions.append(node_position + label_direction * (moment_radius * 1.35))
                labels.append(self._format_value(value, "kN·m"))

        actors: list[object] = []
        for (color, line_width), (points, lines) in line_batches.items():
            if not points:
                continue
            mesh = pv.PolyData(np.asarray(points), lines=np.asarray(lines, dtype=np.int64))
            actors.append(plotter.add_mesh(
                mesh, color=color, line_width=line_width, lighting=False, pickable=False,
                reset_camera=False, render=False, render_lines_as_tubes=True,
            ))
        return actors, np.asarray(label_positions, dtype=float).reshape((-1, 3)), tuple(labels)

    @staticmethod
    def _perpendicular_to(vector: np.ndarray) -> np.ndarray:
        reference = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(vector, reference))) > 0.9:
            reference = np.array((0.0, 1.0, 0.0))
        perpendicular = np.cross(vector, reference)
        return perpendicular / np.linalg.norm(perpendicular)

    @staticmethod
    def _add_moment_symbol(
        center: np.ndarray,
        axis: np.ndarray,
        plane_u: np.ndarray,
        plane_v: np.ndarray,
        value: float,
        radius: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        orientation = -1.0 if value > 0 else 1.0
        angles = np.linspace(0.0, orientation * np.pi * 1.55, 25)
        arc = np.asarray([
            center + radius * (np.cos(angle) * plane_u + np.sin(angle) * plane_v)
            for angle in angles
        ])
        tangent = -np.sin(angles[-1]) * plane_u + np.cos(angles[-1]) * plane_v
        tangent *= orientation
        tip = arc[-1]
        back = tip - tangent * radius * 0.28
        side = np.cross(axis, tangent)
        side /= np.linalg.norm(side)
        side *= radius * 0.14
        points = np.vstack((arc, back + side, back - side, tip))
        last = len(arc)
        lines = [len(arc), *range(len(arc)), 2, last, last + 2, 2, last + 1, last + 2]
        return points, np.asarray(lines, dtype=np.int64)

    @staticmethod
    def _moment_plane(
        basis: tuple[np.ndarray, np.ndarray, np.ndarray], direction: str,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Retorna o eixo e o plano perpendicular da reação de momento."""
        local_x, local_y, local_z = basis
        if direction == "X":
            return local_x, local_y, local_z
        if direction == "Y":
            return local_y, local_x, -local_z
        return local_z, local_x, local_y

    @staticmethod
    def _append_face(
        batches: dict[str, tuple[list[np.ndarray], list[int]]],
        color: str,
        points: np.ndarray,
    ) -> None:
        point_batch, face_batch = batches.setdefault(color, ([], []))
        offset = len(point_batch)
        point_batch.extend(points)
        face_batch.extend((len(points), *range(offset, offset + len(points))))

    @staticmethod
    def _append_polyline(
        batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]],
        key: tuple[str, float],
        points: np.ndarray,
    ) -> None:
        point_batch, line_batch = batches.setdefault(key, ([], []))
        offset = len(point_batch)
        point_batch.extend(points)
        line_batch.extend((len(points), *range(offset, offset + len(points))))

    @staticmethod
    def _append_lines(
        batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]],
        key: tuple[str, float],
        points: np.ndarray,
        lines: np.ndarray,
    ) -> None:
        point_batch, line_batch = batches.setdefault(key, ([], []))
        offset = len(point_batch)
        point_batch.extend(points)
        values = np.asarray(lines, dtype=np.int64).copy()
        cursor = 0
        while cursor < len(values):
            count = int(values[cursor])
            values[cursor + 1:cursor + 1 + count] += offset
            cursor += count + 1
        line_batch.extend(values.tolist())

    def _member_result_labels(
        self, values, geometry_values, baseline, curve, local_x, diagram_axis, unit: str,
        *, include_endpoints: bool = False,
    ) -> tuple[list[np.ndarray], list[str]]:
        """Centraliza valores uniformes e evidencia os pontos relevantes."""
        indices = self._member_result_label_indices(values, include_endpoints=include_endpoints)
        if len(indices) == 1:
            center = indices[0]
            position = curve[center] + diagram_axis * (0.10 if geometry_values[center] >= 0.0 else -0.10)
            return (
                [self._clamp_label_position(position, baseline, local_x)],
                [self._format_value(values[center], unit)],
            )

        positions = [
            curve[index] + diagram_axis * (0.12 if geometry_values[index] >= 0.0 else -0.12)
            for index in indices
        ]
        # Em diagramas curtos, os extremos podem estar próximos. O afastamento
        # longitudinal oposto preserva a leitura dos dois rótulos.
        if np.linalg.norm(positions[1] - positions[0]) < 0.24:
            positions[0] -= local_x * 0.12
            positions[1] += local_x * 0.12
        positions = [self._clamp_label_position(position, baseline, local_x) for position in positions]
        return (
            positions,
            [self._format_value(values[index], unit) for index in indices],
        )

    @staticmethod
    def _member_result_label_indices(values, *, include_endpoints: bool) -> list[int]:
        if np.all(values == values[0]):
            return [len(values) // 2]
        indices = [int(np.argmin(values)), int(np.argmax(values))]
        if include_endpoints:
            # Em flexão, os valores nas extremidades representam os momentos
            # nodais e continuam relevantes mesmo quando não são o mínimo ou
            # máximo exclusivo da amostra.
            indices.extend((0, len(values) - 1))
            return sorted(set(indices))
        return list(dict.fromkeys(indices))

    @staticmethod
    def _merge_shared_endpoint_labels(
        positions: list[np.ndarray], labels: list[str], endpoint_nodes: list[str | None],
    ) -> tuple[list[np.ndarray], list[str]]:
        """Merge equal labels generated at the same connected node."""
        groups: dict[tuple[str, str], list[int]] = {}
        for index, (label, node) in enumerate(zip(labels, endpoint_nodes)):
            if node is not None:
                groups.setdefault((node, label), []).append(index)

        merged_positions = list(positions)
        removed: set[int] = set()
        for indices in groups.values():
            if len(indices) < 2:
                continue
            first = indices[0]
            merged_positions[first] = np.mean(
                [merged_positions[index] for index in indices], axis=0,
            )
            removed.update(indices[1:])

        kept_positions = [position for index, position in enumerate(merged_positions) if index not in removed]
        kept_labels = [label for index, label in enumerate(labels) if index not in removed]
        return kept_positions, kept_labels

    @staticmethod
    def _clamp_label_position(position, baseline, local_x) -> np.ndarray:
        """Mantém rótulos fora da zona de 10% junto a cada extremidade."""
        length = float(np.linalg.norm(baseline[-1] - baseline[0]))
        if length <= 1e-12:
            return position
        longitudinal = float(np.dot(position - baseline[0], local_x))
        clamped = float(np.clip(longitudinal, length * 0.10, length * 0.90))
        return position + local_x * (clamped - longitudinal)

    def _render_deformation(
        self, plotter, model, result, components: str, solid_members_visible: bool,
        deformation_scale: float, bar_diagrams_visible: bool = True,
        plate_diagrams_visible: bool = False,
        include_plate_surfaces: bool = True,
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        """Sobrepõe as linhas de centro das barras na configuração deformada."""
        samples_by_member = {
            name: values.get("samples", ())
            for name, values in result.member_results.items()
            if name in model.bars
        }
        member_maximum = max(
            (
                float(np.linalg.norm([
                    float(sample.get("deflection_x", 0.0)) if "X" in components else 0.0,
                    float(sample.get("deflection_y", 0.0)) if "Y" in components else 0.0,
                    float(sample.get("deflection_z", 0.0)) if "Z" in components else 0.0,
                ]))
                for samples in samples_by_member.values()
                for sample in samples
            ),
            default=0.0,
        )
        plate_results = getattr(result, "plate_results", {})
        plate_maximum = max((
            float(np.linalg.norm([
                float(values.get("DX", 0.0)) if "X" in components else 0.0,
                float(values.get("DY", 0.0)) if "Y" in components else 0.0,
                float(values.get("DZ", 0.0)) if "Z" in components else 0.0,
            ]))
            for plate_result in plate_results.values()
            for values in plate_result.get("nodes", {}).values()
        ), default=0.0)
        maximum = max(member_maximum, plate_maximum)
        actors: list[object] = []
        if maximum <= 1e-12:
            return actors, np.empty((0, 3)), ()
        # Results are in model units; 1× therefore draws the real deformation.
        # Larger values are an explicit visual amplification from the palette.
        scale = max(1.0, min(100.0, float(deformation_scale)))
        face_points: list[np.ndarray] = []
        faces: list[int] = []
        edge_points: list[np.ndarray] = []
        edges: list[int] = []
        face_colors: list[np.ndarray] = []
        edge_colors: list[np.ndarray] = []
        line_points: list[np.ndarray] = []
        lines: list[int] = []
        line_colors: list[np.ndarray] = []
        label_positions: list[np.ndarray] = []
        labels: list[str] = []
        deformation_value_range = (
            self.result_range(result, f"Deformação {components}")
            if bar_diagrams_visible else None
        )
        plate_actors: list[object] = []
        plate_positions = np.empty((0, 3), dtype=float)
        plate_labels: tuple[str, ...] = ()
        if include_plate_surfaces:
            if plate_diagrams_visible:
                plate_actors, plate_positions, plate_labels = self.render_plate_contours(
                    plotter, model, result, f"Deformação {components}",
                    deformation_scale=scale,
                    solid_members_visible=solid_members_visible,
                )
            else:
                plate_actors, plate_positions, plate_labels = self._render_plate_deformation(
                    plotter, model, plate_results, components, scale, solid_members_visible,
                )
        label_positions.extend(plate_positions)
        labels.extend(plate_labels)
        for name, samples in samples_by_member.items():
            member = model.bars.get(name)
            if member is None or len(samples) < 2:
                continue
            start_node, end_node = model.nodes[member.start_node], model.nodes[member.end_node]
            basis = LocalAxesRenderer.basis(start_node, end_node, member.rotation)
            if basis is None:
                continue
            local_x, local_y, local_z = basis
            start = np.array((start_node.x, start_node.y, start_node.z), dtype=float)
            deformed = []
            visual_displacements = []
            reported_displacements = []
            for sample in samples:
                displacement_x = float(sample.get("deflection_x", 0.0)) if "X" in components else 0.0
                displacement_y = float(sample.get("deflection_y", 0.0)) if "Y" in components else 0.0
                displacement_z = float(sample.get("deflection_z", 0.0)) if "Z" in components else 0.0
                reported_displacements.append((displacement_x, displacement_y, displacement_z))
                # Member displacement results are already expressed in global
                # XYZ by ResultMapper. Do not project them through the local
                # basis again; that would rotate them a second time.
                visual_displacement = np.array((displacement_x, displacement_y, displacement_z)) * scale
                visual_displacements.append(visual_displacement)
                deformed.append(
                    start
                    + local_x * float(sample["x"])
                    + visual_displacement
                )
            deformed_centerline = np.asarray(deformed)
            deformed_section_bases = self._deformed_section_bases(
                deformed_centerline, local_x, local_y, local_z,
            )
            reported = np.asarray(reported_displacements)
            magnitudes = np.linalg.norm(reported, axis=1)
            maximum_index = int(np.argmax(magnitudes))
            maximum_vector = visual_displacements[maximum_index]
            vector_length = float(np.linalg.norm(maximum_vector))
            outward = maximum_vector / vector_length * 0.12 if vector_length > 1e-12 else local_z * 0.12
            if bar_diagrams_visible:
                label_positions.append(deformed_centerline[maximum_index] + outward)
                if components == "XYZ":
                    value_mm = float(magnitudes[maximum_index] * 1000.0)
                else:
                    component_index = "XYZ".index(components)
                    value_mm = float(reported[maximum_index, component_index] * 1000.0)
                labels.append(self._format_displacement(value_mm))
            color = np.asarray(pv.Color(member.color).int_rgb, dtype=np.uint8)
            station_colors = None
            if bar_diagrams_visible:
                scalar_values = np.asarray([
                    self._deformation_scalar(sample, components) for sample in samples
                ], dtype=float)
                station_colors = result_colors(scalar_values, deformation_value_range)
            if not solid_members_visible:
                if station_colors is None:
                    self._append_colored_polyline(
                        line_points, lines, line_colors, deformed_centerline, color,
                    )
                else:
                    self._append_segmented_colored_polyline(
                        line_points, lines, line_colors, deformed_centerline, station_colors,
                    )
                continue
            try:
                shape = section_shape(
                    member.section, member.geometry_dict(), arc_steps=12,
                    mirror_z=member.section_mirrored,
                )
                if shape is None:
                    raise ValueError("Seção incompleta.")
                longitudinal_edge_indices = self._solid_member_renderer.longitudinal_edge_indices(shape)
                # Analysis results follow the analytical axis. Detailing-only
                # face offsets, section offsets and cut angles do not affect
                # the deformed profile.
                self._append_deformed_member_solid(
                    face_points, faces, face_colors, edge_points, edges, edge_colors,
                    deformed_centerline, deformed_section_bases, shape.loops,
                    longitudinal_edge_indices, color,
                    np.clip(color.astype(float) * 0.65, 0, 255).astype(np.uint8),
                    (0.0, 0.0, 0.0, 0.0), station_colors,
                )
            except (KeyError, TypeError, ValueError):
                if station_colors is None:
                    self._append_colored_polyline(
                        line_points, lines, line_colors, deformed_centerline, color,
                    )
                else:
                    self._append_segmented_colored_polyline(
                        line_points, lines, line_colors, deformed_centerline, station_colors,
                    )
        if face_points:
            mesh = pv.PolyData(np.asarray(face_points), faces=np.asarray(faces))
            mesh.cell_data["rgb"] = np.asarray(face_colors)
            mesh = mesh.compute_normals(
                cell_normals=True, point_normals=False, split_vertices=False,
                consistent_normals=True, auto_orient_normals=True, inplace=False,
            )
            face_actor = plotter.add_mesh(
                mesh, scalars="rgb", rgb=True, smooth_shading=False,
                lighting=True, pickable=False, reset_camera=False, render=False,
            )
            if hasattr(face_actor, "GetProperty"):
                face_property = face_actor.GetProperty()
                face_property.SetEdgeVisibility(False)
                face_property.SetInterpolationToFlat()
                face_property.SetSpecular(0.12)
            actors.append(face_actor)
        if edge_points:
            edge_mesh = pv.PolyData(np.asarray(edge_points), lines=np.asarray(edges))
            edge_mesh.cell_data["rgb"] = np.asarray(edge_colors)
            edge_actor = plotter.add_mesh(
                edge_mesh, scalars="rgb", rgb=True, line_width=1.5, lighting=False,
                pickable=False, reset_camera=False, render=False,
            )
            if hasattr(edge_actor, "GetMapper"):
                edge_mapper = edge_actor.GetMapper()
                edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()
                edge_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
                edge_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
            actors.append(edge_actor)
        if line_points:
            line_mesh = pv.PolyData(np.asarray(line_points), lines=np.asarray(lines))
            line_mesh.cell_data["rgb"] = np.asarray(line_colors)
            actors.append(plotter.add_mesh(
                line_mesh, scalars="rgb", rgb=True, line_width=1.25, lighting=False,
                pickable=False, reset_camera=False, render=False, render_lines_as_tubes=True,
            ))
        actors.extend(plate_actors)
        return actors, np.asarray(label_positions, dtype=float), tuple(labels)

    def _render_plate_deformation(
        self, plotter, model, plate_results, components, scale, solid_members_visible,
    ):
        """Draw deformed FE plate surfaces."""
        plates = getattr(model, "plates", {})
        deformed_actors: list[object] = []
        label_positions: list[np.ndarray] = []
        labels: list[str] = []

        for plate_name, plate_result in plate_results.items():
            plate = plates.get(plate_name)
            nodes = plate_result.get("nodes", {})
            elements = plate_result.get("elements", {})
            if plate is None or not nodes or not elements:
                continue
            node_names = tuple(nodes)
            node_index = {name: index for index, name in enumerate(node_names)}
            original = np.asarray([
                nodes[name].get("coordinates", (0.0, 0.0, 0.0)) for name in node_names
            ], dtype=float)
            displacement = np.asarray([
                (
                    float(nodes[name].get("DX", 0.0)) if "X" in components else 0.0,
                    float(nodes[name].get("DY", 0.0)) if "Y" in components else 0.0,
                    float(nodes[name].get("DZ", 0.0)) if "Z" in components else 0.0,
                )
                for name in node_names
            ], dtype=float)
            quads = [
                tuple(node_index[name] for name in element.get("nodes", ()))
                for element in elements.values()
                if len(element.get("nodes", ())) == 4
                and all(name in node_index for name in element["nodes"])
            ]
            if not quads:
                continue

            deformed = original + displacement * scale
            mesh_faces = np.asarray(
                [value for quad in quads for value in (4, *quad)], dtype=np.int64,
            )
            mesh = pv.PolyData(deformed, faces=mesh_faces)
            surface_actor = plotter.add_mesh(
                mesh, color=getattr(plate, "color", "#6e7781"),
                opacity=1.0 if solid_members_visible else 0.7,
                show_edges=False,
                smooth_shading=False, lighting=True, pickable=False,
                reset_camera=False, render=False,
            )
            surface_actor.SetObjectName(f"result-plate:{plate_name}")
            deformed_actors.append(surface_actor)
            edge_pairs = {
                (min(start, end), max(start, end))
                for quad in quads
                for start, end in zip(quad, (quad[1], quad[2], quad[3], quad[0]))
            }
            encoded_edges = np.asarray(
                [value for start, end in sorted(edge_pairs) for value in (2, start, end)],
                dtype=np.int64,
            )
            edge_mesh = pv.PolyData(deformed, lines=encoded_edges)
            edge_actor = plotter.add_mesh(
                edge_mesh, color="#57606a", opacity=1.0, line_width=1.0,
                lighting=False, pickable=False, reset_camera=False, render=False,
            )
            edge_actor.SetObjectName(f"result-plate-edges:{plate_name}")
            edge_mapper = edge_actor.GetMapper() if hasattr(edge_actor, "GetMapper") else None
            if edge_mapper is not None:
                edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()
                edge_mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
                edge_mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
            deformed_actors.append(edge_actor)

            magnitudes = np.linalg.norm(displacement, axis=1)
            maximum_index = int(np.argmax(magnitudes))
            if magnitudes[maximum_index] > 1e-12:
                vector = displacement[maximum_index]
                label_positions.append(
                    deformed[maximum_index] + vector / magnitudes[maximum_index] * 0.12,
                )
                if components == "XYZ":
                    value_mm = float(magnitudes[maximum_index] * 1000.0)
                else:
                    component_index = "XYZ".index(components)
                    value_mm = float(displacement[maximum_index, component_index] * 1000.0)
                labels.append(self._format_displacement(value_mm))

        return deformed_actors, label_positions, labels

    @staticmethod
    def _deformed_section_bases(centerline, original_x, original_y, original_z):
        """Keep each section normal to the displaced centerline without scaling it."""
        bases = []
        for index in range(len(centerline)):
            if index == 0:
                tangent = centerline[1] - centerline[0]
            elif index == len(centerline) - 1:
                tangent = centerline[-1] - centerline[-2]
            else:
                tangent = centerline[index + 1] - centerline[index - 1]
            length = float(np.linalg.norm(tangent))
            tangent = tangent / length if length > 1e-12 else original_x
            transverse_y = original_y - tangent * float(np.dot(original_y, tangent))
            transverse_length = float(np.linalg.norm(transverse_y))
            if transverse_length <= 1e-8:
                transverse_y = original_z - tangent * float(np.dot(original_z, tangent))
                transverse_length = float(np.linalg.norm(transverse_y))
            if transverse_length <= 1e-8:
                transverse_y = np.cross(original_z, tangent)
                transverse_length = float(np.linalg.norm(transverse_y))
            transverse_y /= transverse_length
            transverse_z = np.cross(tangent, transverse_y)
            transverse_z /= max(float(np.linalg.norm(transverse_z)), 1e-12)
            bases.append((tangent, transverse_y, transverse_z))
        return tuple(bases)

    def _append_deformed_member_solid(
        self, face_points, faces, face_colors, edge_points, edges, edge_colors,
        centerline, section_bases, loops, longitudinal_edge_indices,
        color, edge_color, face_angles, station_colors=None,
    ) -> None:
        """Extruda a seção real ao longo da configuração deformada calculada."""
        angle_tangents = np.tan(np.deg2rad(np.asarray(face_angles, dtype=float)))
        for loop_index, loop in enumerate(loops):
            ring_offsets: list[int] = []
            for ring_index, center in enumerate(centerline):
                local_x, local_y, local_z = section_bases[ring_index]
                ring_offsets.append(len(face_points))
                fraction_b = ring_index / max(1, len(centerline) - 1)
                face_points.extend(
                    center
                    - local_x * self._millimeters_to_model_units * (
                        y * ((1.0 - fraction_b) * angle_tangents[0] + fraction_b * angle_tangents[2])
                        + z * ((1.0 - fraction_b) * angle_tangents[1] + fraction_b * angle_tangents[3])
                    )
                    + local_y * y * self._millimeters_to_model_units
                    + local_z * z * self._millimeters_to_model_units
                    for y, z in loop
                )
            size = len(loop)
            for station_index, (ring_a, ring_b) in enumerate(pairwise(ring_offsets)):
                for index in range(size):
                    next_index = (index + 1) % size
                    faces.extend((4, ring_a + index, ring_a + next_index, ring_b + next_index, ring_b + index))
                    face_colors.append(
                        np.rint(np.mean(station_colors[station_index:station_index + 2], axis=0)).astype(np.uint8)
                        if station_colors is not None else color
                    )
            self._append_colored_polyline(edge_points, edges, edge_colors, [
                face_points[ring_offsets[0] + index] for index in (*range(size), 0)
            ], edge_color)
            self._append_colored_polyline(edge_points, edges, edge_colors, [
                face_points[ring_offsets[-1] + index] for index in (*range(size), 0)
            ], edge_color)
            for index in longitudinal_edge_indices[loop_index]:
                self._append_colored_polyline(edge_points, edges, edge_colors, [
                    face_points[ring + index] for ring in ring_offsets
                ], edge_color)

    @staticmethod
    def _append_colored_polyline(points, lines, colors, polyline, color) -> None:
        offset = len(points)
        points.extend(polyline)
        lines.extend((len(polyline), *range(offset, offset + len(polyline))))
        colors.append(color)

    @staticmethod
    def _append_segmented_colored_polyline(points, lines, colors, polyline, station_colors) -> None:
        for index, (start, end) in enumerate(pairwise(polyline)):
            offset = len(points)
            points.extend((start, end))
            lines.extend((2, offset, offset + 1))
            colors.append(np.rint(np.mean(station_colors[index:index + 2], axis=0)).astype(np.uint8))

    @classmethod
    def _format_displacement(cls, value_mm: float) -> str:
        rounded = cls._display_value(value_mm)
        number = f"{rounded:.{cls.DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{number} mm"

    def _render_shear_geometry(
        self,
        face_batches: dict[str, tuple[list[np.ndarray], list[int]]],
        line_batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]],
        baseline,
        curve,
        values: np.ndarray,
    ) -> None:
        """Acumula os trechos por cor, evitando atores por barra."""
        for index, (value_a, value_b) in enumerate(pairwise(values)):
            if value_a == 0.0 and value_b == 0.0:
                continue
            baseline_a, baseline_b = baseline[index], baseline[index + 1]
            curve_a, curve_b = curve[index], curve[index + 1]
            if value_a * value_b < 0.0:
                ratio = abs(value_a) / (abs(value_a) + abs(value_b))
                crossing = baseline_a + (baseline_b - baseline_a) * ratio
                self._append_shear_face(face_batches, (baseline_a, crossing, curve_a), value_a)
                self._append_shear_face(face_batches, (crossing, baseline_b, curve_b), value_b)
                self._append_shear_line(line_batches, (curve_a, crossing), value_a)
                self._append_shear_line(line_batches, (crossing, curve_b), value_b)
            else:
                result_value = value_a or value_b
                self._append_shear_face(face_batches, (baseline_a, baseline_b, curve_b, curve_a), result_value)
                self._append_shear_line(line_batches, (curve_a, curve_b), result_value)
        for baseline_point, curve_point, value in (
            (baseline[0], curve[0], values[0]),
            (baseline[-1], curve[-1], values[-1]),
        ):
            if value != 0.0:
                self._append_shear_line(line_batches, (baseline_point, curve_point), value)

    def _append_shear_face(self, batches, points, value: float) -> None:
        self._append_face(batches, self._result_color(value), np.asarray(points))

    def _append_shear_line(self, batches, points, value: float) -> None:
        self._append_polyline(batches, (self._result_color(value), 2.5), np.asarray(points))

    def _result_color(self, value: float) -> str:
        return self.NEGATIVE_COLOR if value < 0.0 else self.POSITIVE_COLOR

    @classmethod
    def _format_force(cls, value: float) -> str:
        return cls._format_value(value, "kN")

    @classmethod
    def _format_value(cls, value: float, unit: str) -> str:
        rounded = cls._display_value(value)
        number = f"{rounded:.{cls.DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{number} {unit}"

    @classmethod
    def _display_value(cls, value: float) -> float:
        """Arredonda para a precisão que o usuário vê, evitando ``-0``."""
        rounded = round(float(value), cls.DISPLAY_DECIMALS)
        return 0.0 if rounded == 0.0 else rounded
