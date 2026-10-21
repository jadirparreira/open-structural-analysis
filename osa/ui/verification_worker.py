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


def verify_model(model) -> dict:
    """Run checks against a private model snapshot and return UI-ready results."""
    results = {}
    elements = verification_elements(model)
    elements_with_routine = [
        element for element in elements
        if all(
            name in model.bars and model.bars[name].section == "W Laminado"
            for name in element.member_names
        )
    ]
    for element in elements_with_routine:
        tension = verify_w_tension(element, model, model.analysis_results)
        compression = verify_w_compression(element, model, model.analysis_results)
        flexion_y = verify_w_flexion_y(element, model, model.analysis_results)
        flexion_z = verify_w_flexion_z(element, model, model.analysis_results)
        shear_y = verify_w_shear_y(element, model, model.analysis_results)
        shear_z = verify_w_shear_z(element, model, model.analysis_results)
        oblique_bending = verify_w_oblique_bending(
            element, model, model.analysis_results, flexion_y, flexion_z,
        )
        flexotension = verify_w_flexotension(
            element, model, model.analysis_results, tension, flexion_y, flexion_z,
        )
        flexocompression = verify_w_flexocompression(
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
