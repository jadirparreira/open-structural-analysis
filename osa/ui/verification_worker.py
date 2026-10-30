"""Background worker for steel member verifications."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from osa.verification.elements import VerificationElement, verification_elements
from osa.verification.i_rolled import (
    verify_i_compression,
    verify_i_flexion_y,
    verify_i_flexion_z,
    verify_i_flexocompression,
    verify_i_flexotension,
    verify_i_oblique_bending,
    verify_i_shear_y,
    verify_i_shear_z,
    verify_i_slenderness,
    verify_i_tension,
)
from osa.verification.l_rolled import (
    verify_l_compression,
    verify_l_flexion_y,
    verify_l_flexion_z,
    verify_l_flexocompression,
    verify_l_flexotension,
    verify_l_oblique_bending,
    verify_l_shear_y,
    verify_l_shear_z,
    verify_l_slenderness,
    verify_l_tension,
)
from osa.verification.rectangular_bar import (
    verify_rectangular_bar_compression,
    verify_rectangular_bar_flexion_y,
    verify_rectangular_bar_flexion_z,
    verify_rectangular_bar_flexocompression,
    verify_rectangular_bar_flexotension,
    verify_rectangular_bar_oblique,
    verify_rectangular_bar_shear_y,
    verify_rectangular_bar_shear_z,
    verify_rectangular_bar_tension,
)
from osa.verification.round_bar import (
    verify_round_bar_compression,
    verify_round_bar_flexion_y,
    verify_round_bar_flexion_z,
    verify_round_bar_flexocompression,
    verify_round_bar_flexotension,
    verify_round_bar_oblique,
    verify_round_bar_shear_y,
    verify_round_bar_shear_z,
    verify_round_bar_tension,
)
from osa.verification.square_bar import (
    verify_square_bar_compression,
    verify_square_bar_flexion_y,
    verify_square_bar_flexion_z,
    verify_square_bar_flexocompression,
    verify_square_bar_flexotension,
    verify_square_bar_oblique,
    verify_square_bar_shear_y,
    verify_square_bar_shear_z,
    verify_square_bar_tension,
)
from osa.verification.t_rolled import (
    verify_t_compression,
    verify_t_flexion_y,
    verify_t_flexion_z,
    verify_t_flexocompression,
    verify_t_flexotension,
    verify_t_oblique_bending,
    verify_t_shear_y,
    verify_t_shear_z,
    verify_t_tension,
)
from osa.verification.u_rolled import (
    verify_u_compression,
    verify_u_flexion_y,
    verify_u_flexion_z,
    verify_u_flexocompression,
    verify_u_flexotension,
    verify_u_oblique_bending,
    verify_u_shear_y,
    verify_u_shear_z,
    verify_u_slenderness,
    verify_u_tension,
)
from osa.verification.w_rolled import (
    verify_w_compression,
    verify_w_flexion_y,
    verify_w_flexion_z,
    verify_w_flexocompression,
    verify_w_flexotension,
    verify_w_oblique_bending,
    verify_w_shear_y,
    verify_w_shear_z,
    verify_w_slenderness,
    verify_w_tension,
)

_ROUTINES = {
    "W Laminado": (
        verify_w_tension, verify_w_compression,
        verify_w_flexion_y, verify_w_flexion_z,
        verify_w_shear_y, verify_w_shear_z,
        verify_w_oblique_bending, verify_w_flexotension,
        verify_w_flexocompression,
    ),
    "HP Laminado": (
        verify_w_tension, verify_w_compression,
        verify_w_flexion_y, verify_w_flexion_z,
        verify_w_shear_y, verify_w_shear_z,
        verify_w_oblique_bending, verify_w_flexotension,
        verify_w_flexocompression,
    ),
    "I Laminado": (
        verify_i_tension, verify_i_compression,
        verify_i_flexion_y, verify_i_flexion_z,
        verify_i_shear_y, verify_i_shear_z,
        verify_i_oblique_bending, verify_i_flexotension,
        verify_i_flexocompression,
    ),
    "U Laminado": (
        verify_u_tension, verify_u_compression,
        verify_u_flexion_y, verify_u_flexion_z,
        verify_u_shear_y, verify_u_shear_z,
        verify_u_oblique_bending, verify_u_flexotension,
        verify_u_flexocompression,
    ),
    "L Laminado": (
        verify_l_tension, verify_l_compression,
        verify_l_flexion_y, verify_l_flexion_z,
        verify_l_shear_y, verify_l_shear_z,
        verify_l_oblique_bending, verify_l_flexotension,
        verify_l_flexocompression,
    ),
    "T Laminado": (
        verify_t_tension, verify_t_compression,
        verify_t_flexion_y, verify_t_flexion_z,
        verify_t_shear_y, verify_t_shear_z,
        verify_t_oblique_bending, verify_t_flexotension,
        verify_t_flexocompression,
    ),
    "Barra Retangular": (
        verify_rectangular_bar_tension, verify_rectangular_bar_compression,
        verify_rectangular_bar_flexion_y, verify_rectangular_bar_flexion_z,
        verify_rectangular_bar_shear_y, verify_rectangular_bar_shear_z,
        verify_rectangular_bar_oblique, verify_rectangular_bar_flexotension,
        verify_rectangular_bar_flexocompression,
    ),
    "Barra Quadrada": (
        verify_square_bar_tension, verify_square_bar_compression,
        verify_square_bar_flexion_y, verify_square_bar_flexion_z,
        verify_square_bar_shear_y, verify_square_bar_shear_z,
        verify_square_bar_oblique, verify_square_bar_flexotension,
        verify_square_bar_flexocompression,
    ),
    "Barra Circular": (
        verify_round_bar_tension, verify_round_bar_compression,
        verify_round_bar_flexion_y, verify_round_bar_flexion_z,
        verify_round_bar_shear_y, verify_round_bar_shear_z,
        verify_round_bar_oblique, verify_round_bar_flexotension,
        verify_round_bar_flexocompression,
    ),
}


def _w_torsion_summary(element, model, results) -> dict[str, object]:
    """Find the largest meaningful torque for the memorial notice."""
    witness = None
    available = bool(results)
    for result in results or ():
        for member_name in element.member_names:
            member_result = result.member_results.get(member_name, {})
            member = model.bars.get(member_name)
            geometry = member.geometry_dict() if member is not None else {}
            depth_m = max(
                float(geometry.get("d", geometry.get("d_mm", 0.0))),
                float(geometry.get("bf", geometry.get("bf_mm", 0.0))),
            ) / 1000.0
            for sample in member_result.get("samples", ()):
                torque = abs(float(sample.get("torque", 0.0)))
                reference_moment = max(
                    abs(float(sample.get("moment_y", 0.0))),
                    abs(float(sample.get("moment_z", 0.0))),
                    max(
                        abs(float(sample.get("shear_y", 0.0))),
                        abs(float(sample.get("shear_z", 0.0))),
                    ) * depth_m,
                )
                # Suppress numerical residuals while retaining meaningful torque.
                tolerance = max(0.005, 0.0001 * reference_moment)
                if torque >= tolerance and (witness is None or torque > witness[0]):
                    witness = (
                        torque, member_name, result.load_reference,
                        float(sample.get("x", 0.0)),
                    )
    if witness is None:
        return {"available": available, "has_torsion": False}
    torque, member_name, combination, position_m = witness
    return {
        "available": True,
        "has_torsion": True,
        "torque_kn_m": torque,
        "member": member_name,
        "combination": combination,
        "position_m": position_m,
    }


def verify_model(model, member_names: tuple[str, ...] | None = None) -> dict:
    """Run checks against a private model snapshot and return UI-ready results."""
    results = {}
    elements = verification_elements(model)
    if member_names is not None:
        selected_members = set(member_names)
        matching_elements = [
            element for element in elements
            if set(element.member_names) == selected_members
        ]
        if not matching_elements and len(member_names) == 1:
            member_name = member_names[0]
            if member_name in model.bars:
                custom_name = model.verification_element_names.get(member_name, "").strip()
                display_name = f"{custom_name} ({member_name})" if custom_name else member_name
                matching_elements = [
                    VerificationElement(f"bar:{member_name}", display_name, (member_name,))
                ]
        elements = matching_elements
    elements_with_routine = [
        element for element in elements
        if all(
            name in model.bars and model.bars[name].section in _ROUTINES
            for name in element.member_names
        )
        and len({model.bars[name].section for name in element.member_names}) == 1
    ]
    for element in elements_with_routine:
        (verify_tension, verify_compression, verify_flexion_y, verify_flexion_z,
         verify_shear_y, verify_shear_z, verify_oblique_bending,
         verify_flexotension, verify_flexocompression) = _ROUTINES[
            model.bars[element.member_names[0]].section
        ]
        tension = verify_tension(element, model, model.analysis_results)
        compression = verify_compression(element, model, model.analysis_results)
        flexion_y = verify_flexion_y(element, model, model.analysis_results)
        flexion_z = verify_flexion_z(element, model, model.analysis_results)
        shear_y = verify_shear_y(element, model, model.analysis_results)
        shear_z = verify_shear_z(element, model, model.analysis_results)
        oblique_bending = verify_oblique_bending(
            element, model, model.analysis_results, flexion_y, flexion_z,
        )
        flexotension = verify_flexotension(
            element, model, model.analysis_results, tension, flexion_y, flexion_z,
        )
        flexocompression = verify_flexocompression(
            element, model, model.analysis_results, compression, flexion_y, flexion_z,
        )
        checks = (
            tension, compression, flexion_y, flexion_z, shear_y, shear_z,
            oblique_bending, flexotension, flexocompression,
        )
        profile_type = model.bars[element.member_names[0]].section
        is_w_profile = profile_type in {"W Laminado", "HP Laminado"}
        is_u_profile = profile_type == "U Laminado"
        is_i_profile = profile_type == "I Laminado"
        is_l_profile = profile_type == "L Laminado"
        w_slenderness_summary = (
            verify_w_slenderness(element, model, model.analysis_results) if is_w_profile else
            verify_u_slenderness(element, model, model.analysis_results) if is_u_profile else
            verify_i_slenderness(element, model, model.analysis_results) if is_i_profile else
            verify_l_slenderness(element, model, model.analysis_results) if is_l_profile else None
        )
        w_torsion_summary = (
            _w_torsion_summary(element, model, model.analysis_results)
            if is_w_profile or is_u_profile or is_i_profile else None
        )
        checked = [item for item in checks if item.get("status") == "checked"]
        failed = [item for item in checked if item.get("utilization", 0.0) > 1.0]
        controlling = max(
            failed or checked,
            key=lambda item: item.get("utilization", 0.0),
            default=None,
        )
        unverified = [item for item in checks if item.get("status") == "not_checked"]
        if failed:
            summary = dict(controlling)
        elif unverified:
            summary = dict(controlling or unverified[0])
            summary["status"] = "not_checked"
            summary["detail"] = "; ".join(item.get("detail", "") for item in unverified)
        else:
            summary = dict(controlling or tension)
        if w_torsion_summary is not None:
            summary["torsion_summary"] = w_torsion_summary
        if w_slenderness_summary is not None:
            summary["slenderness_summary"] = w_slenderness_summary
        summary["checks"] = {
            "axial_tension": tension,
            "axial_compression": compression,
            **({"slenderness": w_slenderness_summary}
               if w_slenderness_summary is not None else {}),
            "flexion_y": flexion_y,
            "flexion_z": flexion_z,
            "shear_y": shear_y,
            "shear_z": shear_z,
            "flexao_obliqua": oblique_bending,
            "flexotracao": flexotension,
            "flexocompressao": flexocompression,
        }
        results[element.key] = summary

    approved = sum(
        item.get("status") == "checked" and item.get("utilization", 2.0) <= 1.0
        for item in results.values()
    )
    rejected = sum(
        item.get("has_rejected_check") or (
            item.get("status") == "checked" and item.get("utilization", 0.0) > 1.0
        )
        for item in results.values()
    )
    return {
        "results": results,
        "summary": {
            "total": len(elements),
            "with_routine": len(elements_with_routine),
            "without_routine": len(elements) - len(elements_with_routine),
            "approved": approved,
            "rejected": rejected,
            "unverified": sum(item.get("status") == "not_checked" for item in results.values()),
        },
    }


class VerificationWorker(QObject):
    """Run member checks without blocking Qt's application thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, model, member_names: tuple[str, ...] | None = None) -> None:
        super().__init__()
        self.model = model
        self.member_names = member_names

    @Slot()
    def run(self) -> None:
        try:
            result = verify_model(self.model, self.member_names)
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "erro inesperado durante as verificações")
            return
        self.finished.emit(result)
