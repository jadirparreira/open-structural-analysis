"""Representação visual das ações estruturais."""

from __future__ import annotations

import numpy as np
import pyvista as pv

from .local_axes_renderer import LocalAxesRenderer


class ActionRenderer:
    """Renderiza ações em poucas malhas agrupadas.

    A aparência das ações continua sendo a mesma, mas a geometria é acumulada
    antes de chegar ao VTK. Isso evita um ator por seta, faixa ou símbolo de
    momento em modelos com muitas ações.
    """

    COLOR = "#cf222e"
    LOCAL_COLOR = "#0969da"
    SELFWEIGHT_COLOR = "#2da44e"
    MOMENT_COLOR = "#0969da"
    MOMENT_RADIUS = 0.30
    MOMENT_SPACING = 1.0
    MAX_HEIGHT = 1.0
    MIN_HEIGHT = 0.1
    LABEL_CLEARANCE = 0.12
    AXIAL_TAIL_LENGTH = 1.0

    def render(
        self, plotter, model, active_load_case: str | None = None,
        visibility: dict[str, bool] | None = None,
    ) -> tuple[list[object], np.ndarray, tuple[str, ...]]:
        actors: list[object] = []
        face_batches: dict[str, tuple[list[np.ndarray], list[int]]] = {}
        line_batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]] = {}
        label_positions: list[np.ndarray] = []
        labels: list[str] = []
        visibility = visibility or {}
        visible_actions = [
            action for action in model.actions.values()
            if (active_load_case is None or action.load_case == active_load_case)
            and self._has_nonzero_component(action.components)
        ]
        distributed_actions = [
            action for action in visible_actions
            if visibility.get("member_forces", True)
            and action.kind.startswith("member_distributed_force_") and len(action.components) == 2
        ]
        node_force_actions = [
            action for action in visible_actions
            if visibility.get("node_forces", True)
            and action.kind.startswith("node_force_") and len(action.components) == 1
        ]
        member_moment_actions = [
            action for action in visible_actions
            if visibility.get("member_moments", True)
            and action.kind.startswith("member_moment_") and len(action.components) == 1
        ]
        node_moment_actions = [
            action for action in visible_actions
            if visibility.get("node_moments", True)
            and action.kind.startswith("node_moment_") and len(action.components) == 1
        ]
        maximum_intensity = max(
            (
                abs(component)
                for action in (*distributed_actions, *node_force_actions)
                for component in action.components
            ),
            default=0.0,
        )
        for action in distributed_actions if maximum_intensity else ():
            member = model.bars.get(action.target)
            if member is None:
                continue
            start_node = model.nodes[member.start_node]
            end_node = model.nodes[member.end_node]
            start = np.array((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.array((end_node.x, end_node.y, end_node.z), dtype=float)
            member_vector = end - start
            length = float(np.linalg.norm(member_vector))
            if length == 0:
                continue

            direction_name = action.kind.removeprefix("member_distributed_force_")
            is_local = direction_name.startswith("local_")
            is_selfweight = direction_name.startswith("selfweight_")
            direction = (
                direction_name.removeprefix("local_")
                .removeprefix("global_")
                .removeprefix("selfweight_")
            )
            if direction not in {"X", "Y", "Z"}:
                continue
            if is_local:
                basis = LocalAxesRenderer.basis(start_node, end_node, member.rotation)
                if basis is None:
                    continue
                force_direction = basis["XYZ".index(direction)]
                force_color = self.LOCAL_COLOR
            elif is_selfweight:
                force_direction = np.array((0.0, 0.0, 1.0))
                force_color = self.SELFWEIGHT_COLOR
            else:
                force_direction = np.zeros(3)
                force_direction["XYZ".index(direction)] = 1.0
                force_color = self.COLOR

            initial, final = action.components
            tangent = member_vector / length
            if np.isclose(abs(np.dot(tangent, force_direction)), 1.0, atol=1e-9):
                points, lines, axial_positions, axial_labels = self._render_axial_force(
                    plotter, start, end, tangent, force_direction, initial, final, force_color,
                )
                self._append_lines(line_batches, (force_color, 2.0), points, lines)
                label_positions.extend(axial_positions)
                labels.extend(axial_labels)
                continue

            reference_sign = np.sign(initial + final) or np.sign(initial) or np.sign(final) or 1.0
            initial_sign = np.sign(initial) or reference_sign
            final_sign = np.sign(final) or reference_sign
            # A faixa fica no lado oposto ao sentido da ação, como convenção
            # gráfica para diagramas de cargas distribuídas.
            initial_offset = (
                -force_direction * initial_sign * self._force_height(initial, maximum_intensity)
            )
            final_offset = (
                -force_direction * final_sign * self._force_height(final, maximum_intensity)
            )
            top_start = start + initial_offset
            top_end = end + final_offset
            vertices = np.array((start, end, top_end, top_start))
            self._append_face(face_batches, force_color, vertices)
            # A linha 0-1 coincidiria com a barra, portanto é omitida.
            self._append_lines(
                line_batches, (force_color, 2.0), vertices,
                (2, 1, 2, 2, 2, 3, 2, 3, 0),
            )

            if np.isclose(initial, final):
                outward = self._outward_vector(initial_offset, force_direction, reference_sign)
                label_positions.append(
                    (top_start + top_end) / 2.0 + outward * self.LABEL_CLEARANCE
                )
                labels.append(self._format_force(initial))
            else:
                inward_offset = member_vector * 0.08
                label_positions.extend((
                    top_start + inward_offset
                    + self._outward_vector(initial_offset, force_direction, reference_sign)
                    * self.LABEL_CLEARANCE,
                    top_end - inward_offset
                    + self._outward_vector(final_offset, force_direction, reference_sign)
                    * self.LABEL_CLEARANCE,
                ))
                labels.extend((self._format_force(initial), self._format_force(final)))

        for action in node_force_actions:
            prefix = "node_force_"
            if not action.kind.startswith(prefix) or len(action.components) != 1:
                continue
            node = model.nodes.get(action.target)
            direction = action.kind.removeprefix(prefix)
            if node is None or direction not in {"X", "Y", "Z"}:
                continue
            force = action.components[0]
            if np.isclose(force, 0.0):
                continue
            global_direction = np.zeros(3)
            global_direction["XYZ".index(direction)] = 1.0
            force_direction = global_direction * np.sign(force)
            node_position = np.array((node.x, node.y, node.z), dtype=float)
            arrow_length = self._force_height(force, maximum_intensity)
            line_start = node_position - force_direction * arrow_length
            points, lines = self._add_node_force_arrow(
                plotter, line_start, node_position, force_direction, arrow_length,
            )
            self._append_lines(line_batches, (self.COLOR, 3.0), points, lines)
            label_positions.append(line_start - force_direction * self.LABEL_CLEARANCE)
            labels.append(self._format_node_force(force))

        for action in member_moment_actions:
            member = model.bars.get(action.target)
            direction = action.kind.removeprefix("member_moment_")
            if member is None or direction not in {"X", "Y", "Z"}:
                continue
            start_node = model.nodes[member.start_node]
            end_node = model.nodes[member.end_node]
            basis = LocalAxesRenderer.basis(start_node, end_node, member.rotation)
            if basis is None:
                continue
            axis, plane_u, plane_v = self._moment_plane(basis, direction)
            start = np.array((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.array((end_node.x, end_node.y, end_node.z), dtype=float)
            member_length = float(np.linalg.norm(end - start))
            radius = self.MOMENT_RADIUS
            centers = [
                start + (end - start) * fraction
                for fraction in np.linspace(
                    0.15, 0.85, max(2, min(8, int(member_length / self.MOMENT_SPACING) + 1)),
                )
            ]
            for center in centers:
                points, lines = self._add_moment_symbol(
                    plotter, center, axis, plane_u, plane_v, float(action.components[0]), radius,
                    self.MOMENT_COLOR,
                )
                self._append_lines(line_batches, (self.MOMENT_COLOR, 3.0), points, lines)
            label_positions.append(centers[len(centers) // 2] + plane_u * (radius * 1.35))
            labels.append(self._format_moment(action.components[0]))

        global_basis = tuple(np.eye(3))
        for action in node_moment_actions:
            node = model.nodes.get(action.target)
            direction = action.kind.removeprefix("node_moment_")
            if node is None or direction not in {"X", "Y", "Z"}:
                continue
            axis, plane_u, plane_v = self._moment_plane(global_basis, direction)
            center = np.array((node.x, node.y, node.z), dtype=float)
            points, lines = self._add_moment_symbol(
                plotter, center, axis, plane_u, plane_v, float(action.components[0]),
                self.MOMENT_RADIUS, self.COLOR,
            )
            self._append_lines(line_batches, (self.COLOR, 3.0), points, lines)
            label_positions.append(center + plane_u * (self.MOMENT_RADIUS * 1.35))
            labels.append(self._format_node_moment(action.components[0]))

        for color, (points, faces) in face_batches.items():
            if not points:
                continue
            mesh = pv.PolyData(np.asarray(points), faces=np.asarray(faces, dtype=np.int64))
            actors.append(plotter.add_mesh(
                mesh, color=color, opacity=0.5, lighting=False, pickable=False,
                reset_camera=False, render=False,
            ))
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
    def _has_nonzero_component(components: tuple[float, ...]) -> bool:
        """Keep only actions that can contribute visible geometry or labels.

        This culling happens before action classification and batching, so a
        zero action does not allocate VTK points, enter intensity scaling, or
        reach the label overlay.  Exact zero is intentional here: very small
        but nonzero actions remain inspectable instead of being silently
        discarded by a visual tolerance.
        """
        return any(float(component) != 0.0 for component in components)

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
    def _append_lines(
        batches: dict[tuple[str, float], tuple[list[np.ndarray], list[int]]],
        key: tuple[str, float],
        points: np.ndarray,
        lines: tuple[int, ...] | list[int] | np.ndarray,
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

    @staticmethod
    def _force_height(value: float, maximum_intensity: float) -> float:
        """Escala uma força entre 0,1 e 1 unidade, sem engrossar cargas nulas."""
        value = abs(float(value))
        if np.isclose(value, 0.0) or maximum_intensity <= 0.0:
            return 0.0
        return max(ActionRenderer.MIN_HEIGHT, ActionRenderer.MAX_HEIGHT * value / maximum_intensity)

    @staticmethod
    def _format_number(value: float) -> str:
        rounded = round(float(value), 3)
        if np.isclose(rounded, 0.0):
            rounded = 0.0
        return f"{rounded:.3f}".rstrip("0").rstrip(".").replace(".", ",")

    @staticmethod
    def _format_force(value: float) -> str:
        return ActionRenderer._format_number(value) + " kN/m"

    @staticmethod
    def _format_node_force(value: float) -> str:
        return ActionRenderer._format_number(value) + " kN"

    @staticmethod
    def _format_moment(value: float) -> str:
        return ActionRenderer._format_number(value) + " kNm/m"

    @staticmethod
    def _format_node_moment(value: float) -> str:
        return ActionRenderer._format_number(value) + " kNm"

    def _add_moment_symbol(
        self,
        plotter,
        center: np.ndarray,
        axis: np.ndarray,
        plane_u: np.ndarray,
        plane_v: np.ndarray,
        value: float,
        radius: float,
        color: str,
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
        """Retorna o plano cuja normal coincide com o eixo local informado."""
        local_x, local_y, local_z = basis
        if direction == "X":
            return local_x, local_y, local_z
        if direction == "Y":
            return local_y, local_x, -local_z
        return local_z, local_x, local_y

    def _add_node_force_arrow(
        self,
        plotter,
        line_start: np.ndarray,
        node_position: np.ndarray,
        force_direction: np.ndarray,
        arrow_length: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        chevron_size = arrow_length * 0.18
        chevron_normal = self._perpendicular_to(force_direction)
        arm_a = node_position - force_direction * chevron_size + chevron_normal * chevron_size * 0.55
        arm_b = node_position - force_direction * chevron_size - chevron_normal * chevron_size * 0.55
        points = np.asarray((line_start, node_position, arm_a, arm_b))
        lines = np.asarray((2, 0, 1, 2, 2, 1, 2, 3, 1))
        return points, lines

    @staticmethod
    def _outward_vector(offset: np.ndarray, direction: np.ndarray, reference_sign: float) -> np.ndarray:
        length = float(np.linalg.norm(offset))
        if length > 0:
            return offset / length
        return -direction * reference_sign

    def _render_axial_force(
        self,
        plotter,
        start: np.ndarray,
        end: np.ndarray,
        tangent: np.ndarray,
        force_direction: np.ndarray,
        initial: float,
        final: float,
        color: str,
    ) -> tuple[np.ndarray, np.ndarray, list[np.ndarray], list[str]]:
        """Desenha a carga axial sobre a barra, com uma extensão de 1 unidade."""
        member_vector = end - start
        length = float(np.linalg.norm(member_vector))
        reference_sign = np.sign(initial + final) or np.sign(initial) or np.sign(final) or 1.0
        load_direction = force_direction * reference_sign
        line_start = start.copy()
        line_end = end.copy()
        if np.dot(member_vector, load_direction) >= 0:
            line_start -= load_direction * self.AXIAL_TAIL_LENGTH
            tail_end = line_start
        else:
            line_end -= load_direction * self.AXIAL_TAIL_LENGTH
            tail_end = line_end
        line_vector = line_end - line_start
        line_length = float(np.linalg.norm(line_vector))
        chevron_size = min(0.14, length * 0.035)
        count = max(2, min(12, int(line_length / 0.60) + 1))
        chevron_normal = self._perpendicular_to(tangent)
        points = [line_start, line_end]
        lines = [2, 0, 1]
        for fraction in np.linspace(0.10, 0.90, count):
            line_point = line_start + line_vector * fraction
            member_fraction = np.clip(
                np.dot(line_point - start, member_vector) / (length * length), 0.0, 1.0,
            )
            intensity = initial + (final - initial) * member_fraction
            sign = np.sign(intensity) or np.sign(initial + final) or 1.0
            chevron_direction = force_direction * sign
            arm_a = line_point - chevron_direction * chevron_size + chevron_normal * chevron_size * 0.55
            arm_b = line_point - chevron_direction * chevron_size - chevron_normal * chevron_size * 0.55
            tip = line_point + chevron_direction * chevron_size * 0.75
            first_index = len(points)
            points.extend((arm_a, arm_b, tip))
            lines.extend((2, first_index, first_index + 2, 2, first_index + 1, first_index + 2))
        if np.isclose(initial, final):
            positions = [tail_end - load_direction * self.LABEL_CLEARANCE]
            labels = [self._format_force(initial)]
        else:
            positions = [
                tail_end - load_direction * self.LABEL_CLEARANCE,
                tail_end - load_direction * (self.LABEL_CLEARANCE + 0.28),
            ]
            labels = [self._format_force(initial), self._format_force(final)]
        return np.asarray(points), np.asarray(lines, dtype=np.int64), positions, labels

    @staticmethod
    def _perpendicular_to(vector: np.ndarray) -> np.ndarray:
        reference = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(vector, reference))) > 0.9:
            reference = np.array((0.0, 1.0, 0.0))
        perpendicular = np.cross(vector, reference)
        return perpendicular / np.linalg.norm(perpendicular)
