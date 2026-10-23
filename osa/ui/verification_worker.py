"""Background worker for steel member verifications."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from osa.verification.elements import verification_elements
from osa.verification.w_rolled import (
    verify_w_compression,
    verify_w_flexion_y,
    verify_w_flexion_z,
    verify_w_flexocompression,
    verify_w_flexotension,
    verify_w_oblique_bending,
    verify_w_shear_y,
    verify_w_shear_z,
    verify_w_tension,
)
from osa.verification.i_rolled import (
    verify_i_compression,
    verify_i_flexion_y,
    verify_i_flexion_z,
    verify_i_flexocompression,
    verify_i_flexotension,
    verify_i_oblique_bending,
    verify_i_shear_y,
    verify_i_shear_z,
    verify_i_tension,
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
    verify_u_tension,
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
    verify_l_tension,
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


_ROUTINES = {
    "W Laminado": (
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
    "U Inclinado Laminado": (
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
}


def verify_model(model) -> dict:
    """Run checks against a private model snapshot and return UI-ready results."""
    results = {}
    elements = verification_elements(model)
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
        summary["checks"] = {
            "axial_tension": tension,
            "axial_compression": compression,
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
        item.get("status") == "checked" and item.get("utilization", 0.0) > 1.0
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

    def __init__(self, model) -> None:
        super().__init__()
        self.model = model

    @Slot()
    def run(self) -> None:
        try:
            result = verify_model(self.model)
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "erro inesperado durante as verificações")
            return
        self.finished.emit(result)
