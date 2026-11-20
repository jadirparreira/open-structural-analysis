"""Explicit connection data for NBR 8800 tensile resistance checks."""
from math import isfinite

from osa.verification.calculation_properties import calculation_property


def tension_net_data(model, element, results, gross_area):
    """Require An and Ct when tension is present; do not infer holes/connection."""
    has_tension = any(float(sample.get("axial", 0)) < -1e-6
        for result in results for name in element.member_names
        for sample in result.member_results.get(name, {}).get("samples", ()))
    if not has_tension:
        return gross_area, 1.
    an = calculation_property(model, element, "An", None)
    ct = calculation_property(model, element, "Ct", None)
    if an is None or ct is None:
        raise ValueError("Informe An (cm²) e Ct conforme os furos e a transferência de força da ligação (NBR 8800:2024, 5.2.2–5.2.5).")
    if not all(isfinite(v) for v in (an, ct)) or not 0 < an <= gross_area or not 0 < ct <= 1:
        raise ValueError("An deve ser positiva e não superar Ag; Ct deve estar entre zero e 1.")
    return an, ct
