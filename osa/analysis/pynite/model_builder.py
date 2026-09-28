"""Tradução do domínio para um modelo PyNite no sistema m–kN.

As propriedades da seção são calculadas a partir da geometria paramétrica e
convertidas explicitamente de mm para m na fronteira com o solver.
"""

from __future__ import annotations

from osa.domain import StructuralModel
from osa.services import SectionPropertyService, calculate_rigid_bar_properties


class ModelBuilder:
    def __init__(self, section_properties: SectionPropertyService | None = None) -> None:
        self.section_properties = section_properties or SectionPropertyService()

    def build(self, source: StructuralModel):
        try:
            from Pynite import FEModel3D
        except ImportError as error:
            raise RuntimeError("PyNiteFEA não está disponível neste ambiente.") from error
        target = FEModel3D()
        rotationally_unconnected = self._rotationally_unconnected_nodes(source)
        for node in source.nodes.values():
            target.add_node(node.name, node.x, node.y, node.z)
            supports = list(node.supports)
            stiffness = node.support_stiffness
            if node.name in rotationally_unconnected:
                # Um nó ligado somente a extremidades articuladas não possui
                # rigidez rotacional no modelo de barras. O PyNite mantém os
                # seis GL nodais, então esses três GL puramente cinemáticos
                # precisam ser restringidos para a matriz global ser definida,
                # exceto quando o usuário já informou uma mola rotacional.
                for index in range(3, 6):
                    if stiffness[index] <= 0.0 and not supports[index]:
                        supports[index] = True

            fixed_supports = [
                supports[index] and stiffness[index] <= 0.0
                for index in range(6)
            ]
            if any(fixed_supports):
                target.def_support(node.name, *fixed_supports)

            for index, dof in enumerate(("DX", "DY", "DZ", "RX", "RY", "RZ")):
                if supports[index] and stiffness[index] > 0.0:
                    target.def_support_spring(node.name, dof, stiffness[index])
        for material_name, values in source.materials.items():
            elastic_modulus_kn_m2, shear_modulus_kn_m2, poisson_ratio, unit_weight_kn_m3 = values
            target.add_material(
                material_name,
                elastic_modulus_kn_m2,
                shear_modulus_kn_m2,
                poisson_ratio,
                unit_weight_kn_m3,
            )
        for member in source.bars.values():
            if member.material not in source.materials:
                raise ValueError(f"O membro '{member.name}' não possui material válido.")
            if not member.section or not member.profile:
                raise ValueError(f"O membro '{member.name}' não possui uma seção selecionada.")
            properties = self.section_properties.calculate(
                member.section,
                member.geometry_dict(),
                source.materials[member.material][3] / 9.80665e-3,
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
            releases = list(member.releases)
            for index, percent in zip((6, 7, 8, 9, 10, 11), member.rotation_flexibility_percent):
                releases[index] = releases[index] or percent >= 100
            if any(releases):
                # The application exposes the pair-by-pair order (a/b), while
                # PyNite groups all six local DOFs by member end.
                dxa, dxb, dya, dyb, dza, dzb, rxa, rxb, rya, ryb, rza, rzb = releases
                target.def_releases(
                    member.name, dxa, dya, dza, rxa, rya, rza,
                    dxb, dyb, dzb, rxb, ryb, rzb,
                )
        for rigid in source.rigid_bars.values():
            properties = calculate_rigid_bar_properties(source, rigid)
            if properties is None:
                raise ValueError(
                    f"A barra rígida '{rigid.name}' não possui um membro conectado "
                    "com material e seção válidos."
                )
            material_name = f"rigid_material::{rigid.name}"
            section_name = f"rigid_section::{rigid.name}"
            # PyNite does not receive EA/EI/GJ directly. The equivalent rigid
            # link is therefore a finite frame member built from one coherent
            # material/section pair, with zero density so it has no self-weight.
            target.add_material(
                material_name,
                properties.elastic_modulus_kn_m2,
                properties.shear_modulus_kn_m2,
                properties.poisson_ratio,
                0.0,
            )
            target.add_section(
                section_name,
                properties.area_m2,
                properties.iy_m4,
                properties.iz_m4,
                properties.j_m4,
            )
            target.add_member(
                rigid.name,
                rigid.start_node,
                rigid.end_node,
                material_name,
                section_name,
            )
        return target

    @staticmethod
    def _rotationally_unconnected_nodes(source: StructuralModel) -> set[str]:
        """Return nodes whose incident members all release local RY and RZ."""
        incident: dict[str, list[tuple[bool, bool]]] = {name: [] for name in source.nodes}
        for member in source.bars.values():
            # Application order is A/B by local degree of freedom.
            incident[member.start_node].append((member.releases[8], member.releases[10]))
            incident[member.end_node].append((member.releases[9], member.releases[11]))
        for rigid in source.rigid_bars.values():
            incident[rigid.start_node].append((False, False))
            incident[rigid.end_node].append((False, False))
        return {
            name for name, releases in incident.items()
            if releases and all(release_y and release_z for release_y, release_z in releases)
        }
