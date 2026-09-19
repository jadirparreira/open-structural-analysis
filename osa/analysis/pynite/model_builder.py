"""Tradução do domínio para um modelo PyNite.

As propriedades da seção são calculadas a partir da geometria paramétrica e
convertidas explicitamente de mm para m na fronteira com o solver.
"""

from __future__ import annotations

from osa.domain import StructuralModel
from osa.services import SectionPropertyService


class ModelBuilder:
    def __init__(self, section_properties: SectionPropertyService | None = None) -> None:
        self.section_properties = section_properties or SectionPropertyService()

    def build(self, source: StructuralModel):
        try:
            from Pynite import FEModel3D
        except ImportError as error:
            raise RuntimeError("PyNiteFEA não está disponível neste ambiente.") from error
        target = FEModel3D()
        for node in source.nodes.values():
            target.add_node(node.name, node.x, node.y, node.z)
            if any(node.supports):
                target.def_support(node.name, *node.supports)
        for material_name, values in source.materials.items():
            elastic_modulus_gpa, shear_modulus_gpa, poisson_ratio, density_kg_m3 = values
            target.add_material(
                material_name,
                elastic_modulus_gpa * 1e9,
                shear_modulus_gpa * 1e9,
                poisson_ratio,
                density_kg_m3 * 9.80665,
            )
        for member in source.bars.values():
            if member.material not in source.materials:
                raise ValueError(f"O membro '{member.name}' não possui material válido.")
            if not member.section or not member.profile:
                raise ValueError(f"O membro '{member.name}' não possui uma seção selecionada.")
            properties = self.section_properties.calculate(
                member.section,
                member.geometry_dict(),
                source.materials[member.material][3],
            )
            section_name = f"section::{member.name}"
            target.add_section(
                section_name,
                properties.area_mm2 * 1e-6,
                properties.i_minor_mm4 * 1e-12,
                properties.i_major_mm4 * 1e-12,
                properties.j_mm4 * 1e-12,
            )
            # O eixo local y do PyNite recebe a inércia menor e z a maior.
            # Perfis não simétricos são inicializados pelos eixos principais;
            # a rotação escolhida pelo usuário é aplicada ao eixo local x.
            target.add_member(
                member.name, member.start_node, member.end_node, member.material,
                section_name, rotation=member.rotation,
            )
            if any(member.releases):
                # The application exposes the pair-by-pair order (a/b), while
                # PyNite groups all six local DOFs by member end.
                dxa, dxb, dya, dyb, dza, dzb, rxa, rxb, rya, ryb, rza, rzb = member.releases
                target.def_releases(
                    member.name, dxa, dya, dza, rxa, rya, rza,
                    dxb, dyb, dzb, rxb, ryb, rzb,
                )
        return target
