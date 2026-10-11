"""Serviço de propriedades calculadas para as seções estruturais."""

from __future__ import annotations

from collections.abc import Mapping

from osa.sections import SectionProperties, calculate_section_properties


class SectionPropertyService:
    def calculate(
        self,
        family: str,
        geometry: Mapping[str, float],
        density_kg_m3: float,
        *,
        mirror_z: bool = False,
    ) -> SectionProperties:
        return calculate_section_properties(
            family, geometry, density_kg_m3, mirror_z=mirror_z,
        )
