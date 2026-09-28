"""Ligações rotacionais semirrígidas para os membros do PyNite.

O PyNite oferece liberações booleanas nas extremidades dos membros, mas não
uma mola rotacional entre a extremidade de um membro e o nó estrutural. Este
módulo representa essa mola por condensação estática do grau de liberdade de
rotação da extremidade.
"""

from __future__ import annotations

from types import MethodType

import numpy as np

_START_ROTATION_DOFS = (3, 4, 5)
_END_ROTATION_DOFS = (9, 10, 11)
_PERCENT_POSITIONS = {
    "start": (0, 2, 4),
    "end": (1, 3, 5),
}


def install_semirigid_connections(target, source) -> None:
    """Instala as ligações semirrígidas nos membros físicos do PyNite.

    A instalação é feita no ``descritize`` do membro físico porque o PyNite
    recria seus submembros durante a preparação de cada análise.
    """

    for name, source_member in source.bars.items():
        if not any(0 < value < 100 for value in source_member.rotation_flexibility_percent):
            continue

        physical_member = target.members.get(name)
        if physical_member is None or getattr(physical_member, "_osa_semirigid_installed", False):
            continue

        original_descritize = physical_member.descritize
        endpoint_springs = {
            "start": _spring_stiffnesses(physical_member, source_member, "start"),
            "end": _spring_stiffnesses(physical_member, source_member, "end"),
        }
        all_springs = {**endpoint_springs["start"], **endpoint_springs["end"]}
        if not all_springs:
            continue
        _patch_member(physical_member, all_springs)

        def descritize_with_connections(
            original_descritize=original_descritize,
            physical_member=physical_member,
            endpoint_springs=endpoint_springs,
        ) -> None:
            original_descritize()
            submembers = tuple(physical_member.sub_members.values())
            if not submembers:
                return
            if len(submembers) == 1:
                _patch_member(
                    submembers[0],
                    {**endpoint_springs["start"], **endpoint_springs["end"]},
                )
                return
            _patch_member(submembers[0], endpoint_springs["start"])
            _patch_member(submembers[-1], endpoint_springs["end"])

        physical_member.descritize = descritize_with_connections
        physical_member._osa_semirigid_installed = True


def _spring_stiffnesses(submember, source_member, endpoint: str) -> dict[int, float]:
    percent_positions = _PERCENT_POSITIONS[endpoint]
    if endpoint == "start":
        dofs = _START_ROTATION_DOFS
    else:
        dofs = _END_ROTATION_DOFS

    springs: dict[int, float] = {}
    for dof, percent_position in zip(dofs, percent_positions):
        percent = source_member.rotation_flexibility_percent[percent_position]
        if not 0 < percent < 100:
            continue
        if submember.Releases[dof]:
            continue
        reference_stiffness = float(submember.ke()[dof, dof])
        if reference_stiffness <= 0.0 or not np.isfinite(reference_stiffness):
            raise ValueError(
                f"Não foi possível calcular a rigidez rotacional da vinculação "
                f"semirrígida no membro '{source_member.name}'."
            )
        # The UI percentage is the reduction of the effective end rigidity.
        # A series spring with this value produces the requested reduction for
        # the uncoupled reference DOF: Keff = (1 - p/100) * Kreference.
        spring_stiffness = reference_stiffness * (100.0 - percent) / percent
        springs[dof] = spring_stiffness

    return springs


def _patch_member(submember, springs: dict[int, float]) -> None:
    """Replace the member's local stiffness and fixed-end vector by condensed forms."""

    original_ke = submember.ke
    original_fer = submember.fer
    base_ke = np.asarray(original_ke(), dtype=float)
    spring_dofs = tuple(springs)
    regular_dofs = tuple(index for index in range(12) if index not in spring_dofs)
    spring_matrix = np.diag([springs[index] for index in spring_dofs])
    condensed_matrix = _condense_stiffness(base_ke, regular_dofs, spring_dofs, spring_matrix)

    def semirigid_ke(_self):
        return condensed_matrix.copy()

    def semirigid_fer(_self, combo_name="Combo 1"):
        base_fer = np.asarray(original_fer(combo_name), dtype=float).reshape(12, 1)
        return _condense_fixed_end_vector(
            base_ke, base_fer, regular_dofs, spring_dofs, spring_matrix
        )

    submember.ke = MethodType(semirigid_ke, submember)
    submember.fer = MethodType(semirigid_fer, submember)


def _condense_stiffness(
    base_ke: np.ndarray,
    regular_dofs: tuple[int, ...],
    spring_dofs: tuple[int, ...],
    spring_matrix: np.ndarray,
) -> np.ndarray:
    k_rr = base_ke[np.ix_(regular_dofs, regular_dofs)]
    k_ri = base_ke[np.ix_(regular_dofs, spring_dofs)]
    k_ir = base_ke[np.ix_(spring_dofs, regular_dofs)]
    k_ii = base_ke[np.ix_(spring_dofs, spring_dofs)]
    connection_matrix = k_ii + spring_matrix
    connection_solution = np.linalg.solve(connection_matrix, k_ir)
    spring_solution = np.linalg.solve(connection_matrix, spring_matrix)
    condensed = np.zeros((12, 12), dtype=float)
    condensed[np.ix_(regular_dofs, regular_dofs)] = (
        k_rr - k_ri @ connection_solution
    )
    coupling = k_ri @ spring_solution
    condensed[np.ix_(regular_dofs, spring_dofs)] = coupling
    condensed[np.ix_(spring_dofs, regular_dofs)] = coupling.T
    condensed[np.ix_(spring_dofs, spring_dofs)] = (
        spring_matrix - spring_matrix @ spring_solution
    )
    return condensed


def _condense_fixed_end_vector(
    base_ke: np.ndarray,
    base_fer: np.ndarray,
    regular_dofs: tuple[int, ...],
    spring_dofs: tuple[int, ...],
    spring_matrix: np.ndarray,
) -> np.ndarray:
    k_ri = base_ke[np.ix_(regular_dofs, spring_dofs)]
    k_ii = base_ke[np.ix_(spring_dofs, spring_dofs)]
    connection_solution = np.linalg.solve(k_ii + spring_matrix, base_fer[list(spring_dofs), :])
    fer_regular = base_fer[list(regular_dofs), :] - (
        k_ri @ connection_solution
    )
    fer_spring = spring_matrix @ connection_solution
    condensed = np.zeros((12, 1), dtype=float)
    condensed[list(regular_dofs), :] = fer_regular
    condensed[list(spring_dofs), :] = fer_spring
    return condensed
