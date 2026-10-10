"""Sobreposições gráficas dos resultados de análise."""

from __future__ import annotations

from itertools import pairwise
from typing import ClassVar

import numpy as np
import pyvista as pv

from osa.sections import section_shape

from .local_axes_renderer import LocalAxesRenderer
from .solid_member_renderer import SolidMemberRenderer


class ResultRenderer:
    """Renderiza diagramas de esforços internos sobre os eixos locais."""

    def __init__(self) -> None:
        self._solid_member_renderer = SolidMemberRenderer()

    POSITIVE_COLOR = "#0969da"
    NEGATIVE_COLOR = "#cf222e"
    MAX_HEIGHT = 0.75
    MAX_DEFORMATION = 1.0
    REACTION_FORCE_LENGTH = 0.50
    REACTION_MOMENT_DIAMETER = 0.50
    REACTION_LABEL_CLEARANCE = 0.12
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
    REACTION_DIAGRAM = "Reações de apoio"
    _REACTION_FORCE_KEYS: ClassVar[tuple[str, ...]] = ("RXN_FX", "RXN_FY", "RXN_FZ")
    _REACTION_MOMENT_KEYS: ClassVar[tuple[str, ...]] = ("RXN_MX", "RXN_MY", "RXN_MZ")

    def render(
        self, plotter, model, result, diagram: str, *, solid_members_visible: bool = True,
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        if result is None:
            return [], np.empty((0, 3)), ()
        if diagram.startswith("Deformação"):
            components = diagram.removeprefix("Deformação ") or "XYZ"
            return self._render_deformation(plotter, model, result, components, solid_members_visible)
        if diagram == self.REACTION_DIAGRAM:
            return self._render_reactions(plotter, model, result)
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
            base_basis = LocalAxesRenderer.basis(start_node, end_node, rotation=0)
            if base_basis is None:
                continue
            _base_x, base_local_y, base_local_z = base_basis
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
            positioned_centerline = self._apply_solid_member_positioning(
                deformed_centerline, member, local_x, base_local_y, base_local_z,
            )
            display_centerline = positioned_centerline if solid_members_visible else deformed_centerline
            reported = np.asarray(reported_displacements)
            magnitudes = np.linalg.norm(reported, axis=1)
            maximum_index = int(np.argmax(magnitudes))
            maximum_vector = visual_displacements[maximum_index]
            vector_length = float(np.linalg.norm(maximum_vector))
            outward = maximum_vector / vector_length * 0.12 if vector_length > 1e-12 else local_z * 0.12
            label_positions.append(display_centerline[maximum_index] + outward)
            if components == "XYZ":
                value_mm = float(magnitudes[maximum_index] * 1000.0)
            else:
                component_index = "XYZ".index(components)
                value_mm = float(reported[maximum_index, component_index] * 1000.0)
            labels.append(self._format_displacement(value_mm))
            color = np.asarray(pv.Color(member.color).int_rgb, dtype=np.uint8)
            if not solid_members_visible:
                self._append_colored_polyline(
                    line_points, lines, line_colors, deformed_centerline, color,
                )
                continue
            try:
                shape = section_shape(member.section, member.geometry_dict(), arc_steps=12)
                if shape is None:
                    raise ValueError("Seção incompleta.")
                longitudinal_edge_indices = self._solid_member_renderer.longitudinal_edge_indices(shape)
                self._append_deformed_member_solid(
                    face_points, faces, face_colors, edge_points, edges, edge_colors,
                    positioned_centerline, local_y, local_z, shape.loops,
                    longitudinal_edge_indices, color,
                    np.clip(color.astype(float) * 0.65, 0, 255).astype(np.uint8),
                )
            except (KeyError, TypeError, ValueError):
                self._append_colored_polyline(
                    line_points, lines, line_colors, deformed_centerline, color,
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
                line_mesh, scalars="rgb", rgb=True, line_width=2.0, lighting=False,
                pickable=False, reset_camera=False, render=False, render_lines_as_tubes=True,
            ))
        return actors, np.asarray(label_positions, dtype=float), tuple(labels)

    @staticmethod
    def _apply_solid_member_positioning(
        centerline: np.ndarray,
        member,
        local_x: np.ndarray,
        base_local_y: np.ndarray,
        base_local_z: np.ndarray,
    ) -> np.ndarray:
        """Apply the member's visual placement to a deformed centerline.

        The analysis remains tied to the original analytical member axis.  The
        returned points are only the visual geometry used by the deformation
        overlay, following the same rules as the solid-member renderer:
        endpoint offsets act along the member axis and section offsets act in
        the unrotated local Y/Z reference plane.
        """
        positioned = np.asarray(centerline, dtype=float).copy()
        if len(positioned) < 2:
            return positioned

        face_offsets = getattr(member, "solid_face_offsets", (0.0, 0.0))
        if len(face_offsets) == 2:
            candidate_start = positioned[0] - local_x * float(face_offsets[0])
            candidate_end = positioned[-1] + local_x * float(face_offsets[1])
            if float(np.dot(candidate_end - candidate_start, local_x)) > 1e-9:
                positioned[0], positioned[-1] = candidate_start, candidate_end

        section_offsets = getattr(member, "solid_section_offsets", (0.0, 0.0))
        if len(section_offsets) == 2:
            positioned += (
                base_local_y * float(section_offsets[0])
                + base_local_z * float(section_offsets[1])
            )
        return positioned

    def _append_deformed_member_solid(
        self, face_points, faces, face_colors, edge_points, edges, edge_colors,
        centerline, local_y, local_z, loops, longitudinal_edge_indices, color, edge_color,
    ) -> None:
        """Extruda a seção real ao longo da configuração deformada calculada."""
        for loop_index, loop in enumerate(loops):
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

    def _render_shear_geometry(
        self,
        face_batches: dict[str, tuple[list[np.ndarray], list[int]]],
        line_batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]],
        baseline,
        curve,
        values: np.ndarray,
    ) -> None:
        """Acumula os trechos por cor, evitando atores por membro."""
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
