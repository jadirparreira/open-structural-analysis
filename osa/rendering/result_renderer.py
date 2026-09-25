"""Sobreposições gráficas dos resultados de análise."""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pyvista as pv

from osa.sections import section_shape

from .local_axes_renderer import LocalAxesRenderer


class ResultRenderer:
    """Renderiza diagramas de esforços internos sobre os eixos locais."""

    POSITIVE_COLOR = "#0969da"
    NEGATIVE_COLOR = "#cf222e"
    MAX_HEIGHT = 0.75
    MAX_DEFORMATION = 1.0
    DEFORMATION_COLOR = "#8250df"
    UNDEFORMED_COLOR = "#8c959f"
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

    def render(
        self, plotter, model, result, diagram: str, *, solid_members_visible: bool = True,
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        if result is None:
            return [], np.empty((0, 3)), ()
        if diagram.startswith("Deformação"):
            components = diagram.removeprefix("Deformação ") or "XYZ"
            return self._render_deformation(plotter, model, result, components, solid_members_visible)
        if diagram not in self.DIAGRAMS:
            return [], np.empty((0, 3)), ()
        result_key, axis_index, unit, display_sign, geometry_sign = self.DIAGRAMS[diagram]
        samples_by_member = {
            name: values.get("samples", ())
            for name, values in result.member_results.items()
        }
        maximum = max(
            (
                abs(self._display_value(float(sample.get(result_key, 0.0)) * display_sign))
                for samples in samples_by_member.values()
                for sample in samples
            ),
            default=0.0,
        )
        span = self._model_span(model)
        scale = (
            min(self.MAX_HEIGHT, max(0.18, span * 0.035)) / maximum
            if maximum > 0.0
            else 0.0
        )
        actors: list[object] = []
        label_positions: list[np.ndarray] = []
        labels: list[str] = []
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
            # Mesmo sem faixa, o rótulo informa explicitamente que o esforço
            # naquela barra é nulo após o arredondamento de apresentação.
            if np.all(values == 0.0):
                label_positions.append(baseline[center] + diagram_axis * 0.10)
                labels.append(self._format_value(values[extreme], unit))
                continue
            # O eixo analítico é a linha de referência do diagrama. A faixa
            # se projeta integralmente para um lado, tal como os diagramas de
            # esforço convencionais sobrepostos ao modelo.
            curve = baseline + diagram_axis * geometry_values[:, None] * scale
            if diagram == "Normal" and np.all(values == values[0]):
                color = self.NEGATIVE_COLOR if representative_value < 0.0 else self.POSITIVE_COLOR
                vertices = np.vstack((baseline, curve[::-1]))
                count = len(baseline)
                face = pv.PolyData(vertices, faces=np.asarray((2 * count, *range(2 * count))))
                actors.append(plotter.add_mesh(
                    face, color=color, opacity=0.30, lighting=False, pickable=False,
                    reset_camera=False, render=False,
                ))
                # O contorno contínuo inclui as laterais nas duas extremidades,
                # deixando explícito o fechamento da faixa de esforço.
                outline_points = np.vstack((baseline, curve[::-1], baseline[0]))
                outline_count = len(outline_points)
                line = pv.PolyData(outline_points, lines=np.asarray((outline_count, *range(outline_count))))
                actors.append(plotter.add_mesh(
                    line, color=color, line_width=2.5, lighting=False, pickable=False,
                    reset_camera=False, render=False, render_lines_as_tubes=True,
                ))
            else:
                actors.extend(self._render_shear_geometry(plotter, baseline, curve, values))
            positions, member_labels = self._member_result_labels(
                values, geometry_values, baseline, curve, local_x, diagram_axis, unit,
            )
            label_positions.extend(positions)
            labels.extend(member_labels)
        return actors, np.asarray(label_positions, dtype=float), tuple(labels)

    def _member_result_labels(
        self, values, geometry_values, baseline, curve, local_x, diagram_axis, unit: str,
    ) -> tuple[list[np.ndarray], list[str]]:
        """Centraliza valores uniformes e evidencia mínimo/máximo nos demais."""
        if np.all(values == values[0]):
            center = len(values) // 2
            position = curve[center] + diagram_axis * (0.10 if geometry_values[center] >= 0.0 else -0.10)
            return (
                [self._clamp_label_position(position, baseline, local_x)],
                [self._format_value(values[center], unit)],
            )

        indices = (int(np.argmin(values)), int(np.argmax(values)))
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
            [
                self._format_value(values[indices[0]], unit),
                self._format_value(values[indices[1]], unit),
            ],
        )

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
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        """Sobrepõe as linhas de centro das barras na configuração deformada."""
        samples_by_member = {
            name: values.get("samples", ())
            for name, values in result.member_results.items()
        }
        maximum = max(
            (
                float(np.linalg.norm([
                    float(sample.get("deflection_x", 0.0)),
                    float(sample.get("deflection_y", 0.0)),
                    float(sample.get("deflection_z", 0.0)),
                ]))
                for samples in samples_by_member.values()
                for sample in samples
            ),
            default=0.0,
        )
        actors = self._render_undeformed_reference(plotter, model)
        if maximum <= 1e-12:
            return actors, np.empty((0, 3)), ()
        # A referência é comum às quatro opções X/Y/Z/XYZ para que elas
        # possam ser comparadas diretamente. A resultante máxima ocupa 1 u.
        scale = self.MAX_DEFORMATION / maximum
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
                visual_displacement = (
                    local_x * displacement_x + local_y * displacement_y + local_z * displacement_z
                ) * scale
                visual_displacements.append(visual_displacement)
                deformed.append(
                    start
                    + local_x * float(sample["x"])
                    + visual_displacement
                )
            reported = np.asarray(reported_displacements)
            magnitudes = np.linalg.norm(reported, axis=1)
            maximum_index = int(np.argmax(magnitudes))
            maximum_vector = visual_displacements[maximum_index]
            vector_length = float(np.linalg.norm(maximum_vector))
            outward = maximum_vector / vector_length * 0.12 if vector_length > 1e-12 else local_z * 0.12
            label_positions.append(deformed[maximum_index] + outward)
            if components == "XYZ":
                value_mm = float(magnitudes[maximum_index] * 1000.0)
            else:
                component_index = "XYZ".index(components)
                value_mm = float(reported[maximum_index, component_index] * 1000.0)
            labels.append(self._format_displacement(value_mm))
            color = np.asarray(pv.Color(member.color).int_rgb, dtype=np.uint8)
            if not solid_members_visible:
                self._append_colored_polyline(line_points, lines, line_colors, deformed, color)
                continue
            try:
                shape = section_shape(member.section, member.geometry_dict(), arc_steps=12)
                if shape is None:
                    raise ValueError("Seção incompleta.")
                self._append_deformed_member_solid(
                    face_points, faces, face_colors, edge_points, edges, edge_colors,
                    np.asarray(deformed), local_y, local_z, shape.loops, color,
                    np.clip(color.astype(float) * 0.65, 0, 255).astype(np.uint8),
                )
            except (KeyError, TypeError, ValueError):
                self._append_colored_polyline(line_points, lines, line_colors, deformed, color)
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
                line_mesh, scalars="rgb", rgb=True, line_width=2.0, lighting=False,
                pickable=False, reset_camera=False, render=False, render_lines_as_tubes=True,
            ))
        return actors, np.asarray(label_positions, dtype=float), tuple(labels)

    def _append_deformed_member_solid(
        self, face_points, faces, face_colors, edge_points, edges, edge_colors,
        centerline, local_y, local_z, loops, color, edge_color,
    ) -> None:
        """Extruda a seção real ao longo da configuração deformada calculada."""
        for loop in loops:
            ring_offsets: list[int] = []
            for center in centerline:
                ring_offsets.append(len(face_points))
                face_points.extend(
                    center + local_y * y * self._millimeters_to_model_units + local_z * z * self._millimeters_to_model_units
                    for y, z in loop
                )
            size = len(loop)
            for ring_a, ring_b in pairwise(ring_offsets):
                for index in range(size):
                    next_index = (index + 1) % size
                    faces.extend((4, ring_a + index, ring_a + next_index, ring_b + next_index, ring_b + index))
                    face_colors.append(color)
            self._append_colored_polyline(edge_points, edges, edge_colors, [
                face_points[ring_offsets[0] + index] for index in (*range(size), 0)
            ], edge_color)
            self._append_colored_polyline(edge_points, edges, edge_colors, [
                face_points[ring_offsets[-1] + index] for index in (*range(size), 0)
            ], edge_color)
            for index in range(size):
                self._append_colored_polyline(edge_points, edges, edge_colors, [
                    face_points[ring + index] for ring in ring_offsets
                ], edge_color)

    @staticmethod
    def _append_colored_polyline(points, lines, colors, polyline, color) -> None:
        offset = len(points)
        points.extend(polyline)
        lines.extend((len(polyline), *range(offset, offset + len(polyline))))
        colors.append(color)

    @classmethod
    def _format_displacement(cls, value_mm: float) -> str:
        rounded = cls._display_value(value_mm)
        number = f"{rounded:.{cls.DISPLAY_DECIMALS}f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{number} mm"

    def _render_undeformed_reference(self, plotter, model) -> list[object]:
        """Cria um único ator tracejado como referência para a deformada."""
        points: list[np.ndarray] = []
        lines: list[int] = []
        for member in model.bars.values():
            start_node = model.nodes[member.start_node]
            end_node = model.nodes[member.end_node]
            start = np.asarray((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.asarray((end_node.x, end_node.y, end_node.z), dtype=float)
            delta = end - start
            length = float(np.linalg.norm(delta))
            if length <= 1e-12:
                continue
            dash_count = max(3, round(length / 0.16))
            dash_length = length / dash_count * 0.60
            spacing = length / dash_count
            for index in range(dash_count):
                dash_start = start + delta * (index * spacing / length)
                dash_end = start + delta * min((index * spacing + dash_length) / length, 1.0)
                offset = len(points)
                points.extend((dash_start, dash_end))
                lines.extend((2, offset, offset + 1))
        if not points:
            return []
        mesh = pv.PolyData(np.asarray(points), lines=np.asarray(lines))
        return [plotter.add_mesh(
            mesh, color=self.UNDEFORMED_COLOR, line_width=1.0, lighting=False,
            pickable=False, reset_camera=False, render=False, render_lines_as_tubes=True,
        )]

    def _render_shear_geometry(self, plotter, baseline, curve, values: np.ndarray) -> list[object]:
        """Agrupa os trechos por cor, evitando milhares de atores VTK."""
        batches = {
            self.POSITIVE_COLOR: {"face_points": [], "faces": [], "line_points": [], "lines": []},
            self.NEGATIVE_COLOR: {"face_points": [], "faces": [], "line_points": [], "lines": []},
        }
        for index, (value_a, value_b) in enumerate(pairwise(values)):
            if value_a == 0.0 and value_b == 0.0:
                continue
            baseline_a, baseline_b = baseline[index], baseline[index + 1]
            curve_a, curve_b = curve[index], curve[index + 1]
            if value_a * value_b < 0.0:
                ratio = abs(value_a) / (abs(value_a) + abs(value_b))
                crossing = baseline_a + (baseline_b - baseline_a) * ratio
                self._append_shear_face(batches, (baseline_a, crossing, curve_a), value_a)
                self._append_shear_face(batches, (crossing, baseline_b, curve_b), value_b)
                self._append_shear_line(batches, (curve_a, crossing), value_a)
                self._append_shear_line(batches, (crossing, curve_b), value_b)
            else:
                result_value = value_a or value_b
                self._append_shear_face(batches, (baseline_a, baseline_b, curve_b, curve_a), result_value)
                self._append_shear_line(batches, (curve_a, curve_b), result_value)
        for baseline_point, curve_point, value in (
            (baseline[0], curve[0], values[0]),
            (baseline[-1], curve[-1], values[-1]),
        ):
            if value != 0.0:
                self._append_shear_line(batches, (baseline_point, curve_point), value)
        actors: list[object] = []
        for color, batch in batches.items():
            if batch["face_points"]:
                face = pv.PolyData(np.asarray(batch["face_points"]), faces=np.asarray(batch["faces"]))
                actors.append(plotter.add_mesh(
                    face, color=color, opacity=0.30, lighting=False, pickable=False,
                    reset_camera=False, render=False,
                ))
            if batch["line_points"]:
                line = pv.PolyData(np.asarray(batch["line_points"]), lines=np.asarray(batch["lines"]))
                actors.append(plotter.add_mesh(
                    line, color=color, line_width=2.5, lighting=False, pickable=False,
                    reset_camera=False, render=False, render_lines_as_tubes=True,
                ))
        return actors

    def _append_shear_face(self, batches, points, value: float) -> None:
        batch = batches[self._result_color(value)]
        offset = len(batch["face_points"])
        batch["face_points"].extend(points)
        batch["faces"].extend((len(points), *range(offset, offset + len(points))))

    def _append_shear_line(self, batches, points, value: float) -> None:
        batch = batches[self._result_color(value)]
        offset = len(batch["line_points"])
        batch["line_points"].extend(points)
        batch["lines"].extend((len(points), *range(offset, offset + len(points))))

    def _result_color(self, value: float) -> str:
        return self.NEGATIVE_COLOR if value < 0.0 else self.POSITIVE_COLOR

    @staticmethod
    def _model_span(model) -> float:
        coordinates = np.asarray([(node.x, node.y, node.z) for node in model.nodes.values()])
        return float(np.max(np.ptp(coordinates, axis=0))) if len(coordinates) else 1.0

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
