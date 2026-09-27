"""Equivalent stiffnesses for idealized rigid links.

PyNite models frame members with finite ``E``, ``G``, ``A``, ``Iy``, ``Iz``
and ``J`` values.  A rigid link has no physical section of its own, so an
actual infinite value cannot be sent to the solver.  This service derives a
finite equivalent from the members attached to the link and applies a large,
controlled multiplier to their sectional rigidities.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from osa.domain import RigidBar, StructuralModel
from osa.sections import calculate_section_properties


# A finite penalty avoids the singular/ill-conditioned system that an
# infinite stiffness would create. Four orders of magnitude above the
# connected members is a conservative engineering approximation for this
# idealized link while keeping the PyNite matrix numerically usable.
RIGID_LINK_STIFFNESS_FACTOR = 10_000.0
_UNIT_WEIGHT_CONVERSION = 9.80665e-3


@dataclass(frozen=True, slots=True)
class RigidBarMechanicalProperties:
    """One coherent finite material/section definition for a rigid link."""

    elastic_modulus_kn_m2: float
    shear_modulus_kn_m2: float
    poisson_ratio: float
    area_m2: float
    iy_m4: float
    iz_m4: float
    j_m4: float

    @property
    def stiffness(self) -> "RigidBarStiffness":
        return RigidBarStiffness(
            axial_ea_kn=self.elastic_modulus_kn_m2 * self.area_m2,
            bending_eiy_kn_m2=self.elastic_modulus_kn_m2 * self.iy_m4,
            bending_eiz_kn_m2=self.elastic_modulus_kn_m2 * self.iz_m4,
            torsional_gj_kn_m2=self.shear_modulus_kn_m2 * self.j_m4,
        )


@dataclass(frozen=True, slots=True)
class RigidBarStiffness:
    """Equivalent sectional rigidities in the model's kN-m unit system."""

    axial_ea_kn: float
    bending_eiy_kn_m2: float
    bending_eiz_kn_m2: float
    torsional_gj_kn_m2: float


def calculate_rigid_bar_stiffness(
    model: StructuralModel,
    rigid_bar: RigidBar,
) -> RigidBarStiffness | None:
    """Return the equivalent rigidities shown in the property panel."""

    properties = calculate_rigid_bar_properties(model, rigid_bar)
    return properties.stiffness if properties is not None else None


def calculate_rigid_bar_properties(
    model: StructuralModel,
    rigid_bar: RigidBar,
) -> RigidBarMechanicalProperties | None:
    """Build one coherent finite PyNite material/section for a rigid bar.

    The material moduli are amplified, while the section uses the largest
    valid geometric properties among the members attached to either end.
    A single material and section keeps the solver inputs consistent with the
    displayed ``EA``, ``EIy``, ``EIz`` and ``GJ`` values.
    """

    attached = tuple(
        member
        for member in model.bars.values()
        if rigid_bar.start_node in (member.start_node, member.end_node)
        or rigid_bar.end_node in (member.start_node, member.end_node)
    )
    member_data = [_member_properties(model, member) for member in attached]
    member_data = [values for values in member_data if values is not None]
    if not member_data:
        return None

    reference_material = max(member_data, key=lambda values: values[0])
    return RigidBarMechanicalProperties(
        elastic_modulus_kn_m2=reference_material[0] * RIGID_LINK_STIFFNESS_FACTOR,
        shear_modulus_kn_m2=reference_material[1] * RIGID_LINK_STIFFNESS_FACTOR,
        poisson_ratio=reference_material[2],
        area_m2=max(values[3] for values in member_data),
        iy_m4=max(values[4] for values in member_data),
        iz_m4=max(values[5] for values in member_data),
        j_m4=max(values[6] for values in member_data),
    )


def _member_properties(
    model: StructuralModel,
    member,
) -> tuple[float, float, float, float, float, float, float] | None:
    if not member.section or not member.section_geometry:
        return None
    material = model.materials.get(member.material)
    if material is None:
        return None
    try:
        properties = calculate_section_properties(
            member.section,
            member.geometry_dict(),
            material[3] / _UNIT_WEIGHT_CONVERSION,
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None

    elastic_modulus, shear_modulus, poisson_ratio = material[:3]
    if not all(
        isfinite(value) and value > 0
        for value in (
            elastic_modulus,
            shear_modulus,
            properties.area_mm2,
            properties.i_minor_mm4,
            properties.i_major_mm4,
            properties.j_mm4,
        )
    ):
        return None
    return (
        elastic_modulus,
        shear_modulus,
        poisson_ratio,
        properties.area_mm2 * 1e-6,
        properties.i_minor_mm4 * 1e-12,
        properties.i_major_mm4 * 1e-12,
        properties.j_mm4 * 1e-12,
    )
