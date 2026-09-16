"""Operações geométricas reutilizadas pela renderização e pela análise."""

from __future__ import annotations

import numpy as np

from osa.domain import StructuralModel


class GeometryService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def member_local_axes(self, member_name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        member = self.model.bars[member_name]
        start = self.model.nodes[member.start_node]
        end = self.model.nodes[member.end_node]
        x_axis = np.asarray((end.x - start.x, end.y - start.y, end.z - start.z), dtype=float)
        length = np.linalg.norm(x_axis)
        if length <= self.model.coordinate_tolerance:
            raise ValueError("Um membro deve possuir comprimento diferente de zero.")
        x_axis /= length
        reference = np.array((0.0, 0.0, 1.0))
        if abs(float(np.dot(x_axis, reference))) > 0.99:
            reference = np.array((0.0, 1.0, 0.0))
        y_axis = np.cross(reference, x_axis); y_axis /= np.linalg.norm(y_axis)
        z_axis = np.cross(x_axis, y_axis)
        return x_axis, y_axis, z_axis
