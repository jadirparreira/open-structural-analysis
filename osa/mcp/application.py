"""Casos de uso expostos pelo MCP local.

Esta camada mantém o protocolo MCP separado da janela Qt. Ela reutiliza os
serviços e a sessão de comandos do aplicativo para que uma chamada de IA
altere o mesmo modelo que está aberto na interface.
"""

from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

from osa.data import CatalogLoader
from osa.domain import StructuralModel
from osa.services import ModelService
from osa.services.section_property_service import SectionPropertyService


class McpApplication:
    """Fachada thread-safe no nível da aplicação para o servidor MCP."""

    def __init__(
        self,
        model: StructuralModel,
        model_service: ModelService,
        *,
        on_model_changed: Callable[[], None] | None = None,
    ) -> None:
        self.model = model
        self.model_service = model_service
        self._on_model_changed = on_model_changed
        self._section_properties = SectionPropertyService()
        self._catalog = CatalogLoader()

    def get_project_summary(self) -> dict[str, Any]:
        """Retorna um resumo pequeno e estável do modelo aberto."""
        return {
            "revision": self.model.revision,
            "nodes": len(self.model.nodes),
            "members": len(self.model.bars),
            "rigid_bars": len(self.model.rigid_bars),
            "actions": len(self.model.actions),
            "load_cases": len(self.model.load_cases),
            "load_combinations": len(self.model.load_combinations),
            "analysis_results": len(self.model.analysis_results),
            "materials": len(self.model.materials),
        }

    def list_materials(self) -> dict[str, Any]:
        """Retorna os materiais disponíveis no catálogo do projeto."""
        return {
            "materials": [
                {
                    "name": name,
                    "type": self.model.material_types.get(name, "Indefinido"),
                    "elastic_modulus_kn_m2": values[0],
                    "shear_modulus_kn_m2": values[1],
                    "poisson_ratio": values[2],
                    "unit_weight_kn_m3": values[3],
                }
                for name, values in self.model.materials.items()
            ],
        }

    def list_sections(self, material: str | None = None) -> dict[str, Any]:
        """Retorna famílias e perfis compatíveis com um material."""
        material_type = None
        if material is not None:
            material_type = self.model.material_types.get(material, material)
            if material_type not in self.model.sections:
                raise ValueError(f"Material ou tipo de material '{material}' não encontrado.")
        material_types = (material_type,) if material_type else tuple(self.model.sections)
        return {
            "sections": [
                {
                    "material_type": material_kind,
                    "families": [
                        {
                            "name": family,
                            "profiles": list(self._catalog.profiles(material_kind, family)),
                        }
                        for family in self.model.sections.get(material_kind, ())
                    ],
                }
                for material_kind in material_types
            ],
        }

    def list_nodes(self) -> dict[str, Any]:
        """Retorna os nós do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "nodes": [
                {
                    "name": node.name,
                    "x": node.x,
                    "y": node.y,
                    "z": node.z,
                    "supports": list(node.supports),
                }
                for node in self.model.nodes.values()
            ],
        }

    def list_members(self) -> dict[str, Any]:
        """Retorna os membros do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "members": [
                {
                    "name": member.name,
                    "start_node": member.start_node,
                    "end_node": member.end_node,
                    "material": member.material,
                    "section": member.section,
                    "profile": member.profile,
                    "geometry": member.geometry_dict(),
                }
                for member in self.model.bars.values()
            ],
        }

    def create_node(self, x: float, y: float, z: float, name: str | None = None) -> dict[str, Any]:
        """Cria um nó no modelo aberto."""
        node = self.model_service.create_node(x, y, z, name=name)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": {
                "name": node.name,
                "x": node.x,
                "y": node.y,
                "z": node.z,
            },
        }

    def set_node_supports(
        self,
        node_name: str,
        dx: bool,
        dy: bool,
        dz: bool,
        rx: bool = False,
        ry: bool = False,
        rz: bool = False,
    ) -> dict[str, Any]:
        """Aplica restrições aos seis graus de liberdade de um nó."""
        node = self.model_service.update_supports(node_name, (dx, dy, dz, rx, ry, rz))
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": {"name": node.name, "supports": list(node.supports)},
        }

    def create_member(
        self,
        start_node: str,
        end_node: str,
        name: str | None = None,
        material: str | None = None,
        section: str | None = None,
        geometry: dict[str, float] | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Cria um membro entre dois nós existentes."""
        if any(value is not None for value in (material, section, geometry, profile)):
            if material is None or section is None or geometry is None:
                raise ValueError("Material, seção e geometria devem ser informados juntos.")
            self._validate_member_properties(material, section, geometry)
        member = self.model_service.create_member(start_node, end_node, name=name)
        if material is not None and section is not None and geometry is not None:
            member = self._apply_member_properties(member.name, material, section, geometry, profile)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def set_member_properties(
        self,
        member_names: list[str],
        material: str,
        section: str,
        geometry: dict[str, float],
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Atribui material e seção paramétrica a vários membros."""
        if not member_names:
            raise ValueError("Informe pelo menos um membro.")
        self._validate_member_properties(material, section, geometry)
        names = tuple(dict.fromkeys(member_names))
        if any(name not in self.model.bars for name in names):
            missing = next(name for name in names if name not in self.model.bars)
            raise ValueError(f"Membro '{missing}' não encontrado.")
        members = [
            self._apply_member_properties(name, material, section, geometry, profile)
            for name in names
        ]
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "members": [self._member_payload(member) for member in members],
        }

    def _validate_member_properties(
        self,
        material: str,
        section: str,
        geometry: dict[str, float],
    ) -> None:
        values = self.model.materials.get(material)
        if values is None:
            raise ValueError(f"Material '{material}' não encontrado.")
        material_type = self.model.material_types.get(material)
        if section not in self.model.sections.get(material_type, ()):
            raise ValueError(f"A seção '{section}' não é compatível com o material '{material}'.")
        normalized_geometry = {str(key): float(value) for key, value in geometry.items()}
        if not normalized_geometry or any(not isfinite(value) or value <= 0.0 for value in normalized_geometry.values()):
            raise ValueError("As dimensões da seção devem ser números positivos.")
        self._section_properties.calculate(section, normalized_geometry, values[3] / 9.80665e-3)

    def _apply_member_properties(
        self,
        name: str,
        material: str,
        section: str,
        geometry: dict[str, float],
        profile: str | None,
    ):
        self.model_service.assign_material(name, material)
        self.model_service.assign_section(name, section)
        geometry = {str(key): float(value) for key, value in geometry.items()}
        profile_name = profile or self._default_profile_name(section, geometry)
        return self.model_service.assign_profile(name, profile_name, geometry)

    @staticmethod
    def _default_profile_name(section: str, geometry: dict[str, float]) -> str:
        if section == "Retangular" and {"b", "h"} <= geometry.keys():
            return f"R {geometry['b']:g} x {geometry['h']:g}"
        return section

    @staticmethod
    def _member_payload(member) -> dict[str, Any]:
        return {
            "name": member.name,
            "start_node": member.start_node,
            "end_node": member.end_node,
            "material": member.material,
            "section": member.section,
            "profile": member.profile,
            "geometry": member.geometry_dict(),
        }

    def _notify_model_changed(self) -> None:
        if self._on_model_changed is not None:
            self._on_model_changed()
