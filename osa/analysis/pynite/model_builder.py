"""Tradução do domínio para um modelo PyNite no sistema m–kN.

As propriedades da seção são calculadas a partir da geometria paramétrica e
convertidas explicitamente de mm para m na fronteira com o solver.
"""

from __future__ import annotations

import math
from itertools import pairwise
from math import atan2, degrees

import numpy as np

from osa.domain import StructuralModel
from osa.domain.member_axes import member_basis
from osa.services import SectionPropertyService, calculate_rigid_bar_properties

from .plate_mesh import generate_plate_mesh


class ModelBuilder:
    def __init__(self, section_properties: SectionPropertyService | None = None) -> None:
        self.section_properties = section_properties or SectionPropertyService()

    def build(self, source: StructuralModel):
        try:
            from Pynite import FEModel3D
        except ImportError as error:
            raise RuntimeError("PyNiteFEA não está disponível neste ambiente.") from error
        target = FEModel3D()
        target._osa_member_segments = {}
        target._osa_plate_elements = {}
        target._osa_original_node_names = set(source.nodes)
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
            elastic_modulus_kn_m2, shear_modulus_kn_m2, poisson_ratio, unit_weight_kn_m3 = values[:4]
            target.add_material(
                material_name,
                elastic_modulus_kn_m2,
                shear_modulus_kn_m2,
                poisson_ratio,
                unit_weight_kn_m3,
            )
        plate_mesh = generate_plate_mesh(source.plates)
        plate_node_names = []
        for index, point in enumerate(plate_mesh.nodes, start=1):
            coordinates = tuple(float(value) for value in point)
            existing = next(
                (node.name for node in source.nodes.values()
                 if math.dist(coordinates, (node.x, node.y, node.z)) <= 1e-8),
                None,
            )
            if existing is None:
                existing = f"FE::N{index}"
                target.add_node(existing, *coordinates)
            plate_node_names.append(existing)
        for plate in source.plates.values():
            if plate.material not in source.materials:
                raise ValueError(f"A laje '{plate.name}' não possui um material cadastrado.")
            if source.material_types and source.material_types.get(plate.material) != "Concreto":
                raise ValueError(f"A laje '{plate.name}' deve usar um material do tipo Concreto.")
            plate_elements = []
            for index, connectivity in enumerate(plate_mesh.elements[plate.name], start=1):
                element_name = f"{plate.name}::Q{index}"
                node_names = tuple(plate_node_names[node_index] for node_index in connectivity)
                coordinates = tuple(tuple(float(value) for value in plate_mesh.nodes[node_index])
                                    for node_index in connectivity)
                target.add_quad(
                    element_name, *node_names, plate.thickness_mm / 1000.0, plate.material,
                )
                plate_elements.append((element_name, node_names, coordinates))
            target._osa_plate_elements[plate.name] = tuple(plate_elements)

        supported_bars = {
            name for plate in source.plates.values()
            for kind, name in plate.supports if kind == "bar"
        }
        supported_rigid_bars = {
            name for plate in source.plates.values()
            for kind, name in plate.supports if kind == "rigid_bar"
        }
        for member in source.bars.values():
            if member.material not in source.materials:
                raise ValueError(f"A barra '{member.name}' não possui material válido.")
            if not member.section or not member.profile:
                raise ValueError(f"A barra '{member.name}' não possui uma seção selecionada.")
            properties = self.section_properties.calculate(
                member.section,
                member.geometry_dict(),
                source.materials[member.material][3] / 9.80665e-3,
                mirror_z=member.section_mirrored,
            )
            section_name = f"section::{member.name}"
            target.add_section(
                section_name,
                properties.area_mm2 * 1e-6,
                # In PyNite, the local-z displacement bends about local y.
                # The section geometry used by OSA has its major inertia about
                # y for the usual b x h orientation, so Iy must receive the
                # major inertia and Iz the minor one.
                properties.i_major_mm4 * 1e-12,
                properties.i_minor_mm4 * 1e-12,
                properties.j_mm4 * 1e-12,
            )
            releases = list(member.releases)
            for index, percent in zip((6, 7, 8, 9, 10, 11), member.rotation_flexibility_percent):
                releases[index] = releases[index] or percent >= 100
            stations = self._mesh_stations(
                source, member.start_node, member.end_node, plate_node_names, plate_mesh.nodes,
                member.name in supported_bars,
            )
            self._add_member_segments(
                target, source, member.name, stations, member.material, section_name,
                member.rotation, releases, target._osa_member_segments,
            )
        for rigid in source.rigid_bars.values():
            properties = calculate_rigid_bar_properties(source, rigid)
            if properties is None:
                raise ValueError(
                    f"A barra rígida '{rigid.name}' não possui uma barra conectada "
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
            stations = self._mesh_stations(
                source, rigid.start_node, rigid.end_node, plate_node_names, plate_mesh.nodes,
                rigid.name in supported_rigid_bars,
            )
            self._add_member_segments(
                target, source, rigid.name, stations, material_name, section_name,
                0, [False] * 12, target._osa_member_segments,
            )
        return target

    @staticmethod
    def _mesh_stations(source, start_name, end_name, mesh_node_names, mesh_nodes, enabled):
        start, end = source.nodes[start_name], source.nodes[end_name]
        a = np.array((start.x, start.y, start.z), dtype=float)
        vector = np.array((end.x - start.x, end.y - start.y, end.z - start.z), dtype=float)
        length_squared = float(np.dot(vector, vector))
        stations = [(0.0, start_name), (1.0, end_name)]
        if enabled and length_squared > 0.0:
            for name, coordinates in zip(mesh_node_names, mesh_nodes):
                point = np.asarray(coordinates, dtype=float)
                ratio = float(np.dot(point - a, vector) / length_squared)
                if 1e-8 < ratio < 1.0 - 1e-8 and np.linalg.norm(point - (a + ratio * vector)) <= 1e-7:
                    stations.append((ratio, name))
        ordered = []
        for ratio, name in sorted(stations):
            if ordered and abs(ratio - ordered[-1][0]) <= 1e-8:
                continue
            ordered.append((ratio, name))
        return tuple(ordered)

    @staticmethod
    def _add_member_segments(target, source, original_name, stations, material, section, rotation, releases, mapping):
        rows = []
        for index, ((start_ratio, start_node), (end_ratio, end_node)) in enumerate(pairwise(stations)):
            name = original_name if index == 0 else f"{original_name}::FE{index + 1}"
            target.add_member(name, start_node, end_node, material, section)
            analysis_member = target.members[name]
            member = source.bars.get(original_name)
            if member is not None:
                basis = member_basis(source.nodes[member.start_node], source.nodes[member.end_node], rotation)
                if basis is not None:
                    reference = analysis_member.T()[:3, :3]
                    analysis_member.rotation = degrees(atan2(
                        float(np.dot(basis[1], reference[2])),
                        float(np.dot(basis[1], reference[1])),
                    ))
            segment_releases = list(releases)
            if index > 0:
                segment_releases[0::2] = [False] * 6
            if index < len(stations) - 2:
                segment_releases[1::2] = [False] * 6
            if any(segment_releases):
                dxa, dxb, dya, dyb, dza, dzb, rxa, rxb, rya, ryb, rza, rzb = segment_releases
                target.def_releases(
                    name, dxa, dya, dza, rxa, rya, rza,
                    dxb, dyb, dzb, rxb, ryb, rzb,
                )
            rows.append((name, start_ratio, end_ratio))
        mapping[original_name] = tuple(rows)

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
        plate_points = [point for plate in source.plates.values() for point in plate.contour]
        return {
            name for name, releases in incident.items()
            if releases and all(release_y and release_z for release_y, release_z in releases)
            and not any(math.dist((source.nodes[name].x, source.nodes[name].y, source.nodes[name].z), point) <= 1e-8
                        for point in plate_points)
        }
