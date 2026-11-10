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
            pressure = float(action.components[0])
            for _, node_names, coordinates in plate_elements:
                points = tuple(np.asarray(point, dtype=float) for point in coordinates)
                area = 0.5 * np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0]))
                area += 0.5 * np.linalg.norm(np.cross(points[2] - points[0], points[3] - points[0]))
                nodal_force = pressure * area / 4.0
                for node_name in node_names:
                    target.add_node_load(node_name, "FZ", nodal_force, action.load_case)
            return
        if kind.startswith("member_moment_"):
            LoadCaseBuilder._apply_distributed_member_moment(target, action)
            return
        raise ValueError(f"O tipo de ação '{kind}' não é suportado pelo PyNite.")

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
