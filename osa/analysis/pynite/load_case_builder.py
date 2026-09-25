"""Tradução das ações do domínio para os casos de carga do PyNite."""

from __future__ import annotations

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
        return tuple(load_cases)

    @staticmethod
    def _apply_action(target, action) -> None:
        kind = action.kind
        if kind.startswith("member_distributed_force_"):
            direction = LoadCaseBuilder._member_force_direction(kind)
            initial, final = action.components
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
            raise ValueError(f"O membro '{action.target}' não existe no modelo PyNite.")
        length = float(member.L())
        if length <= 0.0:
            raise ValueError(f"O membro '{action.target}' deve possuir comprimento positivo.")
        segment_length = length / cls.DISTRIBUTED_MOMENT_SEGMENTS
        direction = f"M{axis.lower()}"
        for index in range(cls.DISTRIBUTED_MOMENT_SEGMENTS):
            position = (index + 0.5) * segment_length
            target.add_member_pt_load(
                action.target, direction, density * segment_length, position, action.load_case,
            )
