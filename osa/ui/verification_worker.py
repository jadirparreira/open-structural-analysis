"""Background worker for steel member verifications."""

from __future__ import annotations

from math import isfinite

from PySide6.QtCore import QObject, Signal, Slot

from osa.domain.stability_inputs import CRITICAL_PROPERTIES, stability_signature
from osa.verification.circular_tube import verify as verify_circular_tube
from osa.verification.cold_formed_member import FAMILIES as COLD_FAMILIES
from osa.verification.cold_formed_member import verify as verify_cold_formed
from osa.verification.cold_formed_stability import stability_procedure
from osa.verification.elements import VerificationElement, verification_elements
from osa.verification.governing_trace import annotate_governing_sample
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
from osa.verification.rectangular_tube import verify as verify_rectangular_tube
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
from osa.verification.structured_checks import NAMES, valid_sample
from osa.verification.t_rolled import (
    verify_t_compression,
    verify_t_flexion_y,
    verify_t_flexion_z,
    verify_t_flexocompression,
    verify_t_flexotension,
    verify_t_oblique_bending,
    verify_t_shear_y,
    verify_t_shear_z,
    verify_t_slenderness,
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

_ELEMENT_ROUTINES = {"Tubular Circular": verify_circular_tube,
                     "Tubular Quadrado": verify_rectangular_tube,
                     "Tubular Retangular": verify_rectangular_tube,
                     **dict.fromkeys(COLD_FAMILIES, verify_cold_formed)}


def _torsion_summary(element, model, results) -> dict[str, object]:
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


def _input_integrity(element, model, analysis_results=None, stability_basis=None):
    """Keep missing/nonfinite or stale analysis data out of global approval."""
    issues = []
    analysis_results = model.analysis_results if analysis_results is None else analysis_results
    signatures = {(member.section, tuple(sorted(member.geometry_dict().items())), member.material,
                   member.section_mirrored, member.rotation % 360)
                  for name in element.member_names for member in (model.bars[name],)}
    if len(signatures) != 1:
        issues.append("Grupo com seções, materiais, espelhamentos ou rotações diferentes; verifique as barras individualmente.")
    if not analysis_results:
        issues.append("Resultados de análise indisponíveis.")
    for name in element.member_names:
        if not model.bars[name].section_geometry:
            issues.append(f"geometria da seção incompleta: {name}.")
        elif any(not isfinite(float(value)) for _, value in model.bars[name].section_geometry):
            issues.append(f"Dimensões não finitas na seção de {name}.")
        if (any(key in CRITICAL_PROPERTIES for key, _ in model.bars[name].calculation_property_overrides)
                and (not stability_basis or getattr(model, "_elastic_stability_basis", None) != stability_basis)):
            issues.append(f"Esforços críticos de estabilidade de {name} não correspondem ao modelo físico atual; informe os resultados da nova análise elástica.")
        values = model.materials.get(model.bars[name].material, ())
        try:
            valid_material = len(values) >= 6 and all(isfinite(float(values[i])) and float(values[i]) > 0 for i in (0, 1, 4, 5))
        except (TypeError, ValueError, OverflowError):
            valid_material = False
        if not valid_material:
            issues.append(f"Material incompleto, inválido ou não finito: {name}.")
        elif model.bars[name].section not in COLD_FAMILIES and (
                float(values[4]) > 450000 or float(values[5])/float(values[4]) < 1.15):
            issues.append(f"Material de {name} fora dos limites nominais de 4.6.2.2.1 da NBR 8800:2024 (fy <= 450 MPa e fu/fy >= 1,15).")
    for result in analysis_results:
        if result.model_revision != model.revision:
            issues.append("Resultados de análise desatualizados; processe novamente o modelo.")
        for name in element.member_names:
            data = result.member_results.get(name, {})
            samples = data.get("samples", ())
            if not samples:
                issues.append(f"Amostras ausentes: {name}, {result.load_reference}.")
            for sample in samples:
                invalid = not valid_sample(sample, data)
                if invalid:
                    issues.append(f"Amostra incompleta ou não finita: {name}, {result.load_reference}.")
                    break
    return {"status": "not_checked" if issues else "checked", **({} if issues else {"utilization": 0.}),
            "critical_check": "Integridade dos resultados de análise",
            "detail": " ".join(dict.fromkeys(issues))}


def verify_model(model, member_names: tuple[str, ...] | None = None) -> dict:
    """Run checks against a private model snapshot and return UI-ready results."""
    results = {}
    try:
        stability_basis = stability_signature(model) if any(
            key in CRITICAL_PROPERTIES for member in model.bars.values()
            for key, _ in member.calculation_property_overrides) else None
    except (TypeError, ValueError, OverflowError):
        stability_basis = None
    # The UI solves CAR, ELU and ELS together. Strength checks must consume
    # only the design combinations when they are explicitly classified.
    combinations = model.load_combinations
    design_names = {name for name, combo in combinations.items() if combo.limit_state == "ELU"}
    analysis_results = [item for item in model.analysis_results if item.load_reference in design_names] if design_names else model.analysis_results
    missing = design_names - {item.load_reference for item in analysis_results}
    load_detail = (
        "Não há combinação classificada como ELU; classifique as combinações de cálculo antes de concluir a verificação."
        if combinations and not design_names else
        "Resultados ELU ausentes: " + ", ".join(sorted(missing)) + "." if missing else "")
    load_scope = {"status": "not_checked" if load_detail else "checked",
                  "critical_check": "Combinações de cálculo", "detail": load_detail}
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
            name in model.bars and model.bars[name].section in (_ROUTINES | _ELEMENT_ROUTINES)
            for name in element.member_names
        )
        and len({model.bars[name].section for name in element.member_names}) == 1
    ]
    global_stability = (stability_procedure(model, analysis_results) if any(
        model.bars[element.member_names[0]].section in COLD_FAMILIES for element in elements_with_routine) else None)
    for element in elements_with_routine:
        integrity = _input_integrity(element, model, analysis_results, stability_basis)
        if integrity["status"] == "not_checked":
            if load_detail:
                integrity["detail"] += " " + load_detail
            results[element.key] = {**integrity, "checks": {
                **{key: {**integrity, "critical_check": name} for key, name in NAMES.items()},
                "input_data": integrity,
            }}
            continue
        profile = model.bars[element.member_names[0]].section
        extended_checks = {}
        routines = _ROUTINES.get(profile)
        if routines is None:
            extended_checks = (verify_cold_formed(element, model, analysis_results, stability_check=global_stability)
                               if profile in COLD_FAMILIES else _ELEMENT_ROUTINES[profile](element, model, analysis_results))
            routines = tuple(
                lambda *_args, key=key: extended_checks[key]
                for key in ("axial_tension", "axial_compression", "flexion_y", "flexion_z",
                            "shear_y", "shear_z", "flexao_obliqua", "flexotracao", "flexocompressao")
            )
        (verify_tension, verify_compression, verify_flexion_y, verify_flexion_z,
         verify_shear_y, verify_shear_z, verify_oblique_bending,
         verify_flexotension, verify_flexocompression) = routines
        tension = verify_tension(element, model, analysis_results)
        compression = verify_compression(element, model, analysis_results)
        flexion_y = verify_flexion_y(element, model, analysis_results)
        flexion_z = verify_flexion_z(element, model, analysis_results)
        shear_y = verify_shear_y(element, model, analysis_results)
        shear_z = verify_shear_z(element, model, analysis_results)
        oblique_bending = verify_oblique_bending(
            element, model, analysis_results, flexion_y, flexion_z,
        )
        flexotension = verify_flexotension(
            element, model, analysis_results, tension, flexion_y, flexion_z,
        )
        flexocompression = verify_flexocompression(
            element, model, analysis_results, compression, flexion_y, flexion_z,
        )
        if profile.endswith("Laminado"):
            trace_issues = []
            for key, item in {"axial_tension": tension, "axial_compression": compression,
                              "flexion_y": flexion_y, "flexion_z": flexion_z,
                              "shear_y": shear_y, "shear_z": shear_z,
                              "flexao_obliqua": oblique_bending, "flexotracao": flexotension,
                              "flexocompressao": flexocompression}.items():
                issue = annotate_governing_sample(key, item, analysis_results)
                if issue:
                    trace_issues.append(NAMES[key]+": "+issue)
            if trace_issues:
                extended_checks["traceability"] = {"status": "not_checked",
                    "critical_check": "Rastreabilidade do caso governante", "detail": " ".join(trace_issues)}
        checks = (
            tension, compression, flexion_y, flexion_z, shear_y, shear_z,
            oblique_bending, flexotension, flexocompression,
            *(check for key, check in extended_checks.items()
              if key not in {"axial_tension", "axial_compression", "flexion_y", "flexion_z",
                             "shear_y", "shear_z", "flexao_obliqua", "flexotracao", "flexocompressao"}),
        )
        profile_type = model.bars[element.member_names[0]].section
        is_w_profile = profile_type in {"W Laminado", "HP Laminado"}
        is_u_profile = profile_type == "U Laminado"
        is_i_profile = profile_type == "I Laminado"
        is_l_profile = profile_type == "L Laminado"
        is_t_profile = profile_type == "T Laminado"
        w_slenderness_summary = (
            verify_w_slenderness(element, model, analysis_results) if is_w_profile else
            verify_u_slenderness(element, model, analysis_results) if is_u_profile else
            verify_i_slenderness(element, model, analysis_results) if is_i_profile else
            verify_l_slenderness(element, model, analysis_results) if is_l_profile else
            verify_t_slenderness(element, model, analysis_results) if is_t_profile else None
        )
        torsion_summary = (
            _torsion_summary(element, model, analysis_results)
            if is_w_profile or is_u_profile or is_i_profile or is_l_profile or is_t_profile else None
        )
        integrity = _input_integrity(element, model, analysis_results, stability_basis)
        checks = (*checks, integrity) if integrity["status"] == "not_checked" else checks
        if load_detail:
            checks = (*checks, load_scope)
        checked = [item for item in checks if item.get("status") == "checked"]
        failed = [item for item in checked if item.get("utilization", 0.0) > 1.0]
        controlling = max(
            failed or checked,
            key=lambda item: item.get("utilization", 0.0),
            default=None,
        )
        unverified = [item for item in checks
                      if item.get("status") == "not_checked" and not item.get("memorandum_only")]
        pending_details = [item.get("detail", "") for item in unverified]
        if pending_details:
            summary = dict(controlling or (unverified[0] if unverified else tension))
            summary["status"] = "not_checked"
            summary["detail"] = "; ".join(dict.fromkeys(detail for detail in pending_details if detail))
            summary["has_rejected_check"] = bool(failed)
        else:
            summary = dict(controlling or tension)
        if torsion_summary is not None:
            summary["torsion_summary"] = torsion_summary
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
            **extended_checks,
            **({"load_scope": load_scope} if load_detail else {}),
            **({"input_data": integrity} if integrity["status"] == "not_checked" else {}),
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
