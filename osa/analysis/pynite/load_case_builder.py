"""Tradução das ações do domínio para os casos de carga do PyNite."""

from __future__ import annotations

import numpy as np

from osa.domain import StructuralModel


class LoadCaseBuilder:
    DISTRIBUTED_MOMENT_SEGMENTS = 20

    def apply(self, target, model: StructuralModel) -> tuple[str, ...]:
        """Apply supported actions and return the load-case names used."""
        load_cases: list[str] = []
        for action in model.actions.values():
            if action.load_case not in load_cases:
                load_cases.append(action.load_case)
            self._apply_action(target, action)
        self._apply_plate_selfweight(target, model)
        return tuple(load_cases)

    @staticmethod
    def _apply_plate_selfweight(target, model) -> None:
        cases = {
            action.load_case for action in model.actions.values()
            if action.kind == "member_distributed_force_selfweight_Z"
        }
        if not cases:
            return
        for plate in model.plates.values():
            values = model.materials.get(plate.material)
            if values is None:
                continue
            unit_weight = float(values[3])
            thickness = plate.thickness_mm / 1000.0
            for load_case in cases:
                for _, node_names, coordinates in getattr(target, "_osa_plate_elements", {}).get(plate.name, ()):
                    p1, p2, p3, p4 = (np.asarray(point, dtype=float) for point in coordinates)
                    area = 0.5 * np.linalg.norm(np.cross(p2 - p1, p3 - p1))
                    area += 0.5 * np.linalg.norm(np.cross(p3 - p1, p4 - p1))
                    nodal_force = -unit_weight * thickness * area / 4.0
                    for node_name in node_names:
                        target.add_node_load(node_name, "FZ", nodal_force, load_case)

    @staticmethod
    def _apply_action(target, action) -> None:
        kind = action.kind
        if kind.startswith("member_distributed_force_"):
            direction = LoadCaseBuilder._member_force_direction(kind)
            initial, final = action.components
            segments = getattr(target, "_osa_member_segments", {}).get(action.target)
            if segments:
                for segment_name, start_ratio, end_ratio in segments:
                    start_value = initial + (final - initial) * start_ratio
                    end_value = initial + (final - initial) * end_ratio
                    target.add_member_dist_load(
                        segment_name, direction, start_value, end_value, case=action.load_case,
                        self_weight=kind == "member_distributed_force_selfweight_Z",
                    )
            else:
                target.add_member_dist_load(
                    action.target, direction, initial, final, case=action.load_case,
                    self_weight=kind == "member_distributed_force_selfweight_Z",
                )
            return
        if kind.startswith(("node_force_", "node_moment_")):
            axis = kind.rsplit("_", 1)[1].upper()
            direction = f"F{axis}" if kind.startswith("node_force_") else f"M{axis}"
            target.add_node_load(action.target, direction, action.components[0], action.load_case)
            return
        if kind == "plate_surface_pressure":
            plate_elements = getattr(target, "_osa_plate_elements", {}).get(action.target)
            if not plate_elements:
                raise ValueError(f"A laje '{action.target}' não possui elementos na malha analítica.")
            LoadCaseBuilder._apply_plate_surface_pressure(target, action, plate_elements)
            return
        if kind.startswith(("plate_edge_distributed_force_", "plate_edge_moment_local_")):
            prefix, edge_text = kind.rsplit(":", 1)
            try:
                edge_index = int(edge_text)
            except ValueError as error:
                raise ValueError(f"A aresta da ação '{action.name}' é inválida.") from error
            edge_nodes = getattr(target, "_osa_plate_edges", {}).get((action.target, edge_index), ())
            if len(edge_nodes) < 2:
                raise ValueError(f"A aresta {edge_index + 1} da placa '{action.target}' não possui malha.")
            coordinates_by_node = getattr(target, "_osa_node_coordinates", {})
            edge_start = np.asarray(coordinates_by_node[edge_nodes[0][0]], dtype=float)
            edge_end = np.asarray(coordinates_by_node[edge_nodes[-1][0]], dtype=float)
            tangent = edge_end - edge_start
            edge_length = float(np.linalg.norm(tangent))
            if edge_length <= 0.0:
                raise ValueError(f"A aresta {edge_index + 1} da placa '{action.target}' tem comprimento nulo.")
            tangent /= edge_length
            first_element = getattr(target, "_osa_plate_elements", {}).get(action.target, ())
            if not first_element:
                raise ValueError(f"A placa '{action.target}' não possui elementos na malha analítica.")
            points = np.asarray(first_element[0][2], dtype=float)
            normal_vector = np.cross(points[1] - points[0], points[2] - points[0])
            normal_vector += np.cross(points[2] - points[0], points[3] - points[0])
            normal_length = float(np.linalg.norm(normal_vector))
            if normal_length <= 0.0:
                raise ValueError(f"A placa '{action.target}' possui normal inválida.")
            normal = normal_vector / normal_length
            local_basis = (tangent, np.cross(normal, tangent), normal)
            local_basis = tuple(vector / np.linalg.norm(vector) for vector in local_basis)
            is_moment = prefix.startswith("plate_edge_moment_")
            direction_name = prefix.rsplit("_", 1)[1]
            direction_index = "XYZ".index(direction_name[-1])
            load_direction = (
                local_basis[direction_index]
                if "_local_" in prefix
                else np.eye(3)[direction_index]
            )
            initial = float(action.components[0])
            final = float(action.components[-1])
            for (first_name, first_ratio), (second_name, second_ratio) in zip(edge_nodes, edge_nodes[1:]):
                first_point = np.asarray(coordinates_by_node[first_name], dtype=float)
                second_point = np.asarray(coordinates_by_node[second_name], dtype=float)
                segment_length = float(np.linalg.norm(second_point - first_point))
                if segment_length <= 0.0:
                    continue
                first_value = initial + (final - initial) * first_ratio
                second_value = initial + (final - initial) * second_ratio
                if is_moment:
                    nodal_values = (
                        segment_length * (2.0 * first_value + second_value) / 6.0,
                        segment_length * (first_value + 2.0 * second_value) / 6.0,
                    )
                    directions = tuple(
                        (f"M{axis}", float(component))
                        for axis, component in zip("XYZ", load_direction)
                        if abs(component) > 1e-12
                    )
                    # PyNite nodal moments are global; rotate a local edge moment
                    # into its global components before distributing the couple.
                    for node_name, value in ((first_name, nodal_values[0]), (second_name, nodal_values[1])):
                        for load_type, component in directions:
                            target.add_node_load(node_name, load_type, value * component, action.load_case)
                else:
                    first_nodal = segment_length * (2.0 * first_value + second_value) / 6.0
                    second_nodal = segment_length * (first_value + 2.0 * second_value) / 6.0
                    for node_name, scalar in ((first_name, first_nodal), (second_name, second_nodal)):
                        for axis, component in zip("XYZ", load_direction):
                            if abs(component) > 1e-12:
                                target.add_node_load(
                                    node_name, f"F{axis}", scalar * float(component), action.load_case,
                                )
            return
        if kind.startswith("member_moment_"):
            LoadCaseBuilder._apply_distributed_member_moment(target, action)
            return
        raise ValueError(f"O tipo de ação '{kind}' não é suportado pelo PyNite.")

    @staticmethod
    def _apply_plate_surface_pressure(target, action, plate_elements) -> None:
        if len(action.components) == 1:
            x_initial = x_final = float(action.components[0])
            y_initial = y_final = 0.0
        elif len(action.components) == 4:
            x_initial, x_final, y_initial, y_final = map(float, action.components)
        else:
            raise ValueError(f"A ação na superfície '{action.name}' tem componentes inválidos.")

        axes = getattr(target, "_osa_plate_surface_axes", {}).get(action.target)
        if axes is None:
            if any(value != 0.0 for value in (x_initial, x_final, y_initial, y_final)):
                raise ValueError(f"A placa '{action.target}' não possui eixos locais de superfície.")
            return
        origin, local_x, local_y, x_min, x_max, y_min, y_max = axes
        x_length = x_max - x_min
        y_length = y_max - y_min
        gauss = (-1.0 / np.sqrt(3.0), 1.0 / np.sqrt(3.0))
        for _, node_names, coordinates in plate_elements:
            points = np.asarray(coordinates, dtype=float)
            nodal_forces = np.zeros((4, 3), dtype=float)
            for xi in gauss:
                for eta in gauss:
                    shape = 0.25 * np.array((
                        (1.0 - xi) * (1.0 - eta),
                        (1.0 + xi) * (1.0 - eta),
                        (1.0 + xi) * (1.0 + eta),
                        (1.0 - xi) * (1.0 + eta),
                    ))
                    dxi = 0.25 * np.array((
                        -(1.0 - eta), 1.0 - eta, 1.0 + eta, -(1.0 + eta),
                    ))
                    deta = 0.25 * np.array((
                        -(1.0 - xi), -(1.0 + xi), 1.0 + xi, 1.0 - xi,
                    ))
                    area_vector = np.cross(dxi @ points, deta @ points)
                    if np.linalg.norm(area_vector) <= 1e-14:
                        continue
                    position = shape @ points
                    local_position = position - origin
                    x_ratio = 0.5 if x_length <= 1e-12 else (
                        float(np.dot(local_position, local_x)) - x_min
                    ) / x_length
                    y_ratio = 0.5 if y_length <= 1e-12 else (
                        float(np.dot(local_position, local_y)) - y_min
                    ) / y_length
                    pressure_x = x_initial + (x_final - x_initial) * x_ratio
                    pressure_y = y_initial + (y_final - y_initial) * y_ratio
                    pressure = pressure_x + pressure_y
                    for index in range(4):
                        nodal_forces[index] += shape[index] * pressure * area_vector
            for node_name, force in zip(node_names, nodal_forces):
                for direction, component in zip(("FX", "FY", "FZ"), force):
                    if abs(component) > 1e-12:
                        target.add_node_load(node_name, direction, float(component), action.load_case)

    @staticmethod
    def _member_force_direction(kind: str) -> str:
        if kind == "member_distributed_force_selfweight_Z":
            return "FZ"
        suffix = kind.removeprefix("member_distributed_force_")
        if suffix.startswith("local_"):
            return f"F{suffix.removeprefix('local_')}"
        if suffix.startswith("global_"):
            return f"F{suffix.removeprefix('global_')}"
        return f"F{suffix}"

    @classmethod
    def _apply_distributed_member_moment(cls, target, action) -> None:
        """Approximate a uniform local moment density using point couples.

        PyNite accepts local member point moments (``Mx``, ``My`` and ``Mz``),
        but its distributed-load API accepts forces only. A midpoint rule keeps
        the resultant couple exact and converges to the uniform distribution.
        """
        axis = action.kind.rsplit("_", 1)[1].upper()
        if axis not in {"X", "Y", "Z"}:
            raise ValueError(f"A direção do momento distribuído '{axis}' é inválida.")
        density = float(action.components[0])
        member = target.members.get(action.target)
        if member is None:
            raise ValueError(f"A barra '{action.target}' não existe no modelo PyNite.")
        segments = getattr(target, "_osa_member_segments", {}).get(action.target, ())
        if segments:
            first_name, first_start, first_end = segments[0]
            first_length = float(target.members[first_name].L())
            length = first_length / (first_end - first_start)
        else:
            length = float(member.L())
        if length <= 0.0:
            raise ValueError(f"A barra '{action.target}' deve possuir comprimento positivo.")
        segment_length = length / cls.DISTRIBUTED_MOMENT_SEGMENTS
        direction = f"M{axis.lower()}"
        for index in range(cls.DISTRIBUTED_MOMENT_SEGMENTS):
            global_position = (index + 0.5) * segment_length
            applied = False
            for segment_name, start_ratio, end_ratio in segments:
                start_position, end_position = start_ratio * length, end_ratio * length
                if start_position - 1e-10 <= global_position <= end_position + 1e-10:
                    target.add_member_pt_load(
                        segment_name, direction, density * segment_length,
                        global_position - start_position, action.load_case,
                    )
                    applied = True
                    break
            if not applied:
                target.add_member_pt_load(
                    action.target, direction, density * segment_length, global_position, action.load_case,
                )
