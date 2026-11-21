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
        plate_edge_actions = [
            action for action in visible_actions
            if (visibility.get("member_forces", True) if action.kind.startswith("plate_edge_distributed_force_")
                else visibility.get("member_moments", True))
            if action.kind.startswith(("plate_edge_distributed_force_", "plate_edge_moment_local_"))
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
        plate_pressure_actions = [
            action for action in visible_actions
            if visibility.get("plate_pressures", True)
            and action.kind == "plate_surface_pressure" and len(action.components) in {1, 4}
        ]
        plate_loads = []
        for action in plate_pressure_actions:
            if action.target not in getattr(model, "plates", {}):
                continue
            sample_points, normal = self._plate_action_samples(model, action.target)
            surface_faces, surface_edges = self._plate_action_surface(model, action.target)
            if not sample_points or not surface_faces:
                continue
            components = tuple(float(value) for value in action.components)
            pressure = self._plate_pressure_peak(components)
            plate_loads.append((
                components, normal, sample_points, self.COLOR, surface_faces, surface_edges,
                self._plate_pressure_axis_parameters(model, action.target), action.target,
            ))

        selfweight_actions = [
            action for action in visible_actions
            if visibility.get("plate_pressures", True)
            and action.kind == "member_distributed_force_selfweight_Z"
        ]
        if selfweight_actions:
            for plate_name, plate in getattr(model, "plates", {}).items():
                sample_points, _normal = self._plate_action_samples(model, plate_name)
                material = getattr(model, "materials", {}).get(plate.material)
                if not sample_points or material is None:
                    continue
                pressure = -float(material[3]) * float(plate.thickness_mm) / 1000.0
                if np.isclose(pressure, 0.0):
                    continue
                surface_faces, surface_edges = self._plate_action_surface(model, plate_name)
                if not surface_faces:
                    continue
                plate_loads.append((
                    (pressure,), np.array((0.0, 0.0, np.sign(pressure))), sample_points,
                    self.SELFWEIGHT_COLOR, surface_faces, surface_edges, None, plate_name,
                ))
        maximum_intensity = max(
            (
                abs(component)
                for action in (*distributed_actions, *node_force_actions, *plate_pressure_actions,
                               *(action for action in plate_edge_actions
                                 if action.kind.startswith("plate_edge_distributed_force_")))
                for component in action.components
            ),
            default=0.0,
        )
        maximum_intensity = max(
            maximum_intensity,
            max((self._plate_pressure_peak(load[0]) for load in plate_loads), default=0.0),
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

        for action in plate_edge_actions:
            plate = getattr(model, "plates", {}).get(action.target)
            if plate is None:
                continue
            try:
                prefix, edge_text = action.kind.rsplit(":", 1)
                edge_index = int(edge_text)
                start_node = model.nodes[plate.vertex_nodes[edge_index]]
                end_node = model.nodes[plate.vertex_nodes[(edge_index + 1) % len(plate.vertex_nodes)]]
            except (ValueError, IndexError, KeyError):
                continue
            start = np.array((start_node.x, start_node.y, start_node.z), dtype=float)
            end = np.array((end_node.x, end_node.y, end_node.z), dtype=float)
            vector = end - start
            length = float(np.linalg.norm(vector))
            if length <= 1e-12:
                continue
            tangent = vector / length
            contour = np.asarray(plate.contour, dtype=float)
            normal = np.zeros(3, dtype=float)
            for index, point in enumerate(contour):
                normal += np.cross(point - contour[0], contour[(index + 1) % len(contour)] - contour[0])
            normal_length = float(np.linalg.norm(normal))
            if normal_length <= 1e-12:
                continue
            dominant_axis = int(np.argmax(np.abs(normal)))
            if normal[dominant_axis] < 0.0:
                normal = -normal
            normal /= normal_length
            local_basis = (tangent, np.cross(normal, tangent), normal)
            local_basis = tuple(axis / np.linalg.norm(axis) for axis in local_basis)
            axis_name = prefix.rsplit("_", 1)[1][-1]
            axis_index = "XYZ".index(axis_name)
            is_local = "_local_" in prefix
            direction = local_basis[axis_index] if is_local else np.eye(3)[axis_index]
            if prefix.startswith("plate_edge_moment_"):
                moment = float(action.components[0])
                axis, plane_u, plane_v = self._moment_plane(local_basis, axis_name)
                centers = [start + vector * fraction for fraction in (0.25, 0.5, 0.75)]
                for center in centers:
                    points, lines = self._add_moment_symbol(
                        plotter, center, axis, plane_u, plane_v, moment, self.MOMENT_RADIUS,
                        self.LOCAL_COLOR,
                    )
                    self._append_lines(line_batches, (self.LOCAL_COLOR, 3.0), points, lines)
                label_positions.append(centers[1] + plane_u * (self.MOMENT_RADIUS * 1.35))
                labels.append(self._format_moment(moment))
                continue
            initial, final = action.components
            if np.isclose(initial, 0.0) and np.isclose(final, 0.0):
                continue
            color = self.LOCAL_COLOR if is_local else self.COLOR
            initial_sign = np.sign(initial) or np.sign(final) or 1.0
            final_sign = np.sign(final) or initial_sign
            top_start = start - direction * initial_sign * self._force_height(initial, maximum_intensity)
            top_end = end - direction * final_sign * self._force_height(final, maximum_intensity)
            vertices = np.array((start, end, top_end, top_start))
            self._append_face(face_batches, color, vertices)
            self._append_lines(
                line_batches, (color, 2.0), vertices,
                (2, 1, 2, 2, 2, 3, 2, 3, 0),
            )
            label_positions.extend((top_start + tangent * length * 0.08, top_end - tangent * length * 0.08))
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

        for components, normal, positions, color, surface_faces, surface_edges, pressure_axes, plate_name in plate_loads:
            if np.isclose(self._plate_pressure_peak(components), 0.0):
                continue
            for vertices in surface_faces:
                offsets = []
                for point in vertices:
                    pressure = self._plate_pressure_value(components, point, pressure_axes)
                    offsets.append(
                        -normal * np.sign(pressure) * self._force_height(pressure, maximum_intensity)
                    )
                self._append_face(face_batches, color, vertices + np.asarray(offsets))
            if surface_edges:
                edge_points = np.asarray([
                    point - normal * np.sign(self._plate_pressure_value(components, point, pressure_axes))
                    * self._force_height(self._plate_pressure_value(components, point, pressure_axes), maximum_intensity)
                    for edge in surface_edges for point in edge
                ])
                edge_lines = tuple(
                    value
                    for index in range(len(surface_edges))
                    for value in (2, index * 2, index * 2 + 1)
                )
                self._append_lines(
                    line_batches, (color, 2.0), edge_points, edge_lines,
                )
            label_data = None
            for center in positions:
                pressure = self._plate_pressure_value(components, center, pressure_axes)
                if np.isclose(pressure, 0.0):
                    continue
                direction = normal * np.sign(pressure)
                arrow_length = self._force_height(pressure, maximum_intensity)
                line_start = center - direction * arrow_length
                points, lines = self._add_node_force_arrow(
                    plotter, line_start, center, direction, arrow_length,
                )
                self._append_lines(line_batches, (color, 2.5), points, lines)
                if label_data is None:
                    label_data = (line_start - direction * self.LABEL_CLEARANCE, pressure)
            variable_axes = self._variable_plate_pressure_axes(components)
            if variable_axes and pressure_axes is not None:
                for axis, start, end in variable_axes:
                    for ratio, pressure in ((0.0, start), (1.0, end)):
                        edge_point = self._plate_pressure_edge_point(
                            model, plate_name, pressure_axes, axis, ratio,
                        )
                        total_pressure = self._plate_pressure_value(components, edge_point, pressure_axes)
                        if np.isclose(total_pressure, 0.0):
                            continue
                        direction = normal * np.sign(total_pressure)
                        label_positions.append(
                            edge_point - direction * (
                                self._force_height(total_pressure, maximum_intensity) + self.LABEL_CLEARANCE
                            )
                        )
                        labels.append(self._format_pressure(total_pressure))
            elif label_data is not None:
                label_positions.append(label_data[0])
                labels.append(self._format_pressure(label_data[1]))

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
    def _format_pressure(value: float) -> str:
        return ActionRenderer._format_number(value) + " kN/m²"

    @staticmethod
    def _format_node_moment(value: float) -> str:
        return ActionRenderer._format_number(value) + " kNm"

    @staticmethod
    def _plate_pressure_peak(components) -> float:
        if len(components) == 1:
            return abs(float(components[0]))
        if len(components) != 4:
            return 0.0
        x_start, x_end, y_start, y_end = map(float, components)
        x_active = not (np.isclose(x_start, 0.0) and np.isclose(x_end, 0.0))
        y_active = not (np.isclose(y_start, 0.0) and np.isclose(y_end, 0.0))
        samples = np.linspace(0.0, 1.0, 17)
        return max(
            abs(ActionRenderer._plate_pressure_envelope(
                x_start + (x_end - x_start) * x_ratio,
                y_start + (y_end - y_start) * y_ratio,
                x_active, y_active,
            ))
            for x_ratio in samples for y_ratio in samples
        )

    @staticmethod
    def _plate_pressure_envelope(pressure_x, pressure_y, x_active=True, y_active=True) -> float:
        """Return the upper envelope of active profiles, ignoring blank axes."""
        if x_active and y_active:
            return max(float(pressure_x), float(pressure_y))
        if x_active:
            return float(pressure_x)
        if y_active:
            return float(pressure_y)
        return 0.0

    @staticmethod
    def _plate_pressure_axis_parameters(model, plate_name: str):
        plate = getattr(model, "plates", {}).get(plate_name)
        if plate is None or len(plate.contour) < 3:
            return None
        from osa.analysis.pynite.plate_mesh import _plate_local_basis

        points = np.asarray(plate.contour, dtype=float)
        origin = points[0]
        local_x, local_y, _normal = _plate_local_basis(points)
        relative = points - origin
        x_values, y_values = relative @ local_x, relative @ local_y
        return (
            origin, local_x, local_y,
            float(x_values.min()), float(x_values.max()),
            float(y_values.min()), float(y_values.max()),
        )

    @staticmethod
    def _plate_pressure_value(components, point, parameters) -> float:
        if len(components) == 1 or parameters is None:
            return float(components[0])
        x_start, x_end, y_start, y_end = map(float, components)
        origin, local_x, local_y, x_min, x_max, y_min, y_max = parameters
        relative = np.asarray(point, dtype=float) - origin
        x_length, y_length = x_max - x_min, y_max - y_min
        x_ratio = 0.5 if x_length <= 1e-12 else (float(np.dot(relative, local_x)) - x_min) / x_length
        y_ratio = 0.5 if y_length <= 1e-12 else (float(np.dot(relative, local_y)) - y_min) / y_length
        pressure_x = x_start + (x_end - x_start) * x_ratio
        pressure_y = y_start + (y_end - y_start) * y_ratio
        x_active = not (np.isclose(x_start, 0.0) and np.isclose(x_end, 0.0))
        y_active = not (np.isclose(y_start, 0.0) and np.isclose(y_end, 0.0))
        return ActionRenderer._plate_pressure_envelope(
            pressure_x, pressure_y, x_active, y_active,
        )

    @staticmethod
    def _variable_plate_pressure_axes(components):
        """Return the active linear pressure profiles for local X and Y."""
        if len(components) != 4:
            return ()
        x_start, x_end, y_start, y_end = map(float, components)
        axes = []
        if not np.isclose(x_start, x_end):
            axes.append(("X", x_start, x_end))
        if not np.isclose(y_start, y_end):
            axes.append(("Y", y_start, y_end))
        return tuple(axes)

    @staticmethod
    def _plate_pressure_edge_point(model, plate_name: str, parameters, axis: str, ratio: float) -> np.ndarray:
        """Return the midpoint of the plate edge at one end of a local axis."""
        origin, local_x, local_y, x_min, x_max, y_min, y_max = parameters
        plate = getattr(model, "plates", {}).get(plate_name)
        if plate is None:
            return np.asarray(origin, dtype=float)
        contour = np.asarray(plate.contour, dtype=float)
        relative = contour - origin
        use_x = axis == "X"
        basis = local_x if use_x else local_y
        low, high = (x_min, x_max) if use_x else (y_min, y_max)
        target = low + (high - low) * ratio
        coordinates = relative @ basis
        scale = max(1.0, abs(low), abs(high))
        selected = contour[np.isclose(coordinates, target, atol=scale * 1e-7, rtol=0.0)]
        if len(selected):
            return selected.mean(axis=0)
        return np.asarray(origin) + basis * target

    @staticmethod
    def _plate_action_samples(model, plate_name: str, maximum_count: int = 16):
        """Return spread quad centroids and the mesh's positive normal."""
        mesh = getattr(model, "plate_mesh", None)
        if mesh is not None:
            connectivity = getattr(mesh, "elements", {}).get(plate_name, ())
            nodes = np.asarray(getattr(mesh, "nodes", ()), dtype=float)
            if len(connectivity) and len(nodes):
                quads = nodes[np.asarray(connectivity, dtype=int)]
                centroids = quads.mean(axis=1)
                normal = np.cross(quads[0, 1] - quads[0, 0], quads[0, 3] - quads[0, 0])
                length = float(np.linalg.norm(normal))
                if length > 1e-12:
                    return ActionRenderer._spread_points(centroids, maximum_count), normal / length

        plate = getattr(model, "plates", {}).get(plate_name)
        if plate is None or len(plate.contour) < 3:
            return (), np.array((0.0, 0.0, 1.0))
        points = np.asarray(plate.contour, dtype=float)
        normal = np.zeros(3, dtype=float)
        for second, third in zip(points[1:-1], points[2:]):
            normal = np.cross(second - points[0], third - points[0])
            if np.linalg.norm(normal) > 1e-12:
                break
        length = float(np.linalg.norm(normal))
        if length <= 1e-12:
            return (), np.array((0.0, 0.0, 1.0))
        dominant_axis = int(np.argmax(np.abs(normal)))
        if normal[dominant_axis] < 0.0:
            normal = -normal
        return (points.mean(axis=0),), normal / length

    @staticmethod
    def _plate_action_surface(model, plate_name: str):
        """Return FE surface cells and only their exterior edges."""
        mesh = getattr(model, "plate_mesh", None)
        connectivity = getattr(mesh, "elements", {}).get(plate_name, ()) if mesh is not None else ()
        nodes = np.asarray(getattr(mesh, "nodes", ()), dtype=float) if mesh is not None else np.empty((0, 3))
        if len(connectivity) and len(nodes):
            quads = tuple(nodes[np.asarray(element, dtype=int)] for element in connectivity)
            edge_counts: dict[tuple[int, int], int] = {}
            for element in connectivity:
                for start, end in zip(element, (*element[1:], element[0])):
                    edge = (min(start, end), max(start, end))
                    edge_counts[edge] = edge_counts.get(edge, 0) + 1
            boundary = tuple(
                (nodes[start], nodes[end]) for (start, end), count in edge_counts.items()
                if count == 1
            )
            return quads, boundary

        plate = getattr(model, "plates", {}).get(plate_name)
        if plate is None or len(plate.contour) < 3:
            return (), ()
        contour = np.asarray(plate.contour, dtype=float)
        edges = tuple((contour[index], contour[(index + 1) % len(contour)])
                      for index in range(len(contour)))
        return (contour,), edges

    @staticmethod
    def _spread_points(points: np.ndarray, maximum_count: int) -> tuple[np.ndarray, ...]:
        if len(points) <= maximum_count:
            return tuple(points)
        center = points.mean(axis=0)
        selected = [int(np.argmin(np.linalg.norm(points - center, axis=1)))]
        distances = np.linalg.norm(points - points[selected[0]], axis=1)
        while len(selected) < maximum_count:
            index = int(np.argmax(distances))
            selected.append(index)
            distances = np.minimum(distances, np.linalg.norm(points - points[index], axis=1))
        return tuple(points[index] for index in selected)

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
