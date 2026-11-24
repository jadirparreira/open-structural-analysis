"""Derived plate results in a common plate frame, independent of Qt and VTK.

PyNite moments are integrals of z*sigma: positive values cause tension on +z.
Wood-Armer uses positive sagging moments, so its input tensor is negated.
"""

from __future__ import annotations

from math import hypot, isfinite, sqrt

import numpy as np

POSTPROCESSING_VERSION = 1
POSTPROCESSING_INFO = {
    "wood_armer": {
        "unit": "kN·m/m",
        "components": ["x_superior", "y_superior", "x_inferior", "y_inferior"],
        "description": "Magnitudes não negativas para armaduras ortogonais nos eixos X/Y da placa; somente flexão e torção, sem dimensionar armaduras ou incluir membrana.",
    },
    "von_mises": {
        "unit": "MPa",
        "components": ["superior", "inferior", "maximo_faces"],
        "description": "Estado plano de tensões nas faces: membrana + flexão, sem cisalhamento transversal. Não constitui verificação de resistência do concreto.",
    },
    "faces": "Superior = +Z local da placa; inferior = -Z local da placa, independentemente da câmera.",
    "interpolation": "Calculado no centro e nos nós de cada elemento antes da média escalar do modo de visualização.",
}


def wood_armer(mx: float, my: float, mxy: float) -> tuple[float, float, float, float]:
    """Return top X/Y and bottom X/Y magnitudes; inputs use sagging-positive signs.

    Wood-Armer orthogonal reinforcement, including the one-direction correction
    when a trial design moment is negative (Mxy² / |M|).
    """
    twisting = abs(mxy)

    def tension_face(x, y):
        if x < -twisting:
            return 0.0, max(0.0, y + twisting * (twisting / -x))
        if y < -twisting:
            return max(0.0, x + twisting * (twisting / -y)), 0.0
        return max(0.0, x + twisting), max(0.0, y + twisting)

    return (*tension_face(-mx, -my), *tension_face(mx, my))


def von_mises_faces(moment, membrane, thickness_m: float) -> tuple[float, float, float]:
    """Plane-stress equivalents in MPa for raw PyNite moment/stress components.

    Rectangular homogeneous section: sigma(+/-t/2) = sigma_mem +/- 6*M/t².
    kN/m² is converted to MPa by dividing by 1000. Transverse shear vanishes
    at the free faces and is not included in this face-based output.
    """
    if not isfinite(thickness_m) or thickness_m <= 0:
        raise ValueError("A espessura deve ser positiva e finita para calcular von Mises.")
    bending = np.asarray(moment, dtype=float) * (6.0 / thickness_m**2)
    stress = np.asarray(membrane, dtype=float)

    def equivalent(values):
        sx, sy, txy = values
        # Equivalent to sqrt(sx² - sx*sy + sy² + 3*txy²), with stable positive terms.
        return hypot(0.5 * (sx + sy), sqrt(3.0) * 0.5 * (sx - sy), sqrt(3.0) * txy) / 1000.0

    top, bottom = equivalent(stress + bending), equivalent(stress - bending)
    return top, bottom, max(top, bottom)


def _vector(value):
    array = np.asarray(value, dtype=float)
    return array if array.shape == (3,) and np.isfinite(array).all() else None


def _element_basis(coordinates):
    points = np.asarray(coordinates, dtype=float)
    if points.shape != (4, 3) or not np.isfinite(points).all():
        return None
    x = points[1] - points[0]
    z = np.cross(x, points[3] - points[0])
    if np.linalg.norm(x) <= 1e-12 or np.linalg.norm(z) <= 1e-12:
        return None
    x /= np.linalg.norm(x)
    z /= np.linalg.norm(z)
    return np.asarray((x, np.cross(z, x), z))


def _rotate_tensor(components, rotation):
    x, y, xy = components
    tensor = rotation @ np.asarray(((x, xy), (xy, y))) @ rotation.T
    return np.asarray((tensor[0, 0], tensor[1, 1], tensor[0, 1]))


def enrich_plate_result(plate_result, *, plate=None, axes=None, thickness_m=None):
    """Return an enriched copy; preserve raw solver fields and accept older saved results."""
    if plate_result.get("postprocessing_version") == POSTPROCESSING_VERSION:
        return plate_result
    if plate is not None:
        # Imported lazily so the calculation functions have no meshing dependency.
        from osa.analysis.pynite.plate_mesh import _plate_local_basis

        axes = _plate_local_basis(plate.contour)
        thickness_m = plate.thickness_mm / 1000.0
    if axes is None:
        axes = plate_result.get("axes")
    if thickness_m is None:
        thickness_m = plate_result.get("thickness_m")
    basis = np.asarray(axes, dtype=float) if axes is not None else None
    if basis is None or basis.shape != (3, 3) or not np.isfinite(basis).all():
        return plate_result
    thickness_valid = thickness_m is not None and isfinite(float(thickness_m)) and float(thickness_m) > 0
    nodes = plate_result.get("nodes", {})
    elements = {}
    for name, source in plate_result.get("elements", {}).items():
        element = dict(source)
        coordinates = [nodes.get(node, {}).get("coordinates", ()) for node in source.get("nodes", ())]
        local_basis = _element_basis(coordinates)
        if local_basis is None:
            elements[name] = element
            continue
        normal_sign = 1.0 if np.dot(basis[2], local_basis[2]) >= 0 else -1.0
        # Project the common X axis onto the element plane. This keeps an
        # orthonormal frame even for the small warping accepted by the mesher.
        x = basis[0] - np.dot(basis[0], local_basis[2]) * local_basis[2]
        if np.linalg.norm(x) <= 1e-12:
            elements[name] = element
            continue
        x /= np.linalg.norm(x)
        y = np.cross(local_basis[2] * normal_sign, x)
        rotation = np.asarray((x, y)) @ local_basis[:2].T

        def derive(moment, membrane, rotation=rotation, normal_sign=normal_sign):
            m = _vector(moment)
            if m is None:
                return None, None
            m = _rotate_tensor(m, rotation) * normal_sign
            wa = list(wood_armer(*(-m)))
            s = _vector(membrane)
            vm = (
                list(von_mises_faces(m, _rotate_tensor(s, rotation), float(thickness_m)))
                if s is not None and thickness_valid
                else None
            )
            return wa, vm

        wa, vm = derive(source.get("moment", ()), source.get("membrane", ()))
        if wa is not None:
            element["wood_armer"] = wa
        if vm is not None:
            element["von_mises"] = vm
        moment_nodal, membrane_nodal = source.get("moment_nodal", ()), source.get("membrane_nodal", ())
        if len(moment_nodal) == 4:
            nodal = [
                derive(m, membrane_nodal[i] if len(membrane_nodal) == 4 else ()) for i, m in enumerate(moment_nodal)
            ]
            if all(wa is not None for wa, _vm in nodal):
                element["wood_armer_nodal"] = [wa for wa, _vm in nodal]
            if all(vm is not None for _wa, vm in nodal):
                element["von_mises_nodal"] = [vm for _wa, vm in nodal]
        elements[name] = element
    return {
        **plate_result,
        "elements": elements,
        "axes": basis.tolist(),
        "thickness_m": float(thickness_m) if thickness_valid else None,
        "postprocessing_version": POSTPROCESSING_VERSION,
        "postprocessing": POSTPROCESSING_INFO,
    }


def ensure_plate_postprocessing(model):
    """Upgrade cached results without changing the structural or visual revisions."""
    for result in model.analysis_results:
        if result.model_revision != model.revision:
            continue
        for name, values in tuple(result.plate_results.items()):
            plate = model.plates.get(name)
            if plate is not None and values.get("postprocessing_version") != POSTPROCESSING_VERSION:
                result.plate_results[name] = enrich_plate_result(values, plate=plate)
