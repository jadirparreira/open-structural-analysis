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
from osa.domain import ReferenceAxis, StructuralModel
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
                    "support_stiffness": list(node.support_stiffness),
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

    def list_rigid_bars(self) -> dict[str, Any]:
        """Retorna as barras rígidas do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "rigid_bars": [
                {
                    "name": rigid.name,
                    "start_node": rigid.start_node,
                    "end_node": rigid.end_node,
                }
                for rigid in self.model.rigid_bars.values()
            ],
        }

    def list_reference_axes(self) -> dict[str, Any]:
        """Retorna os eixos de referência configurados no projeto."""
        return {
            "revision": self.model.revision,
            "axes": self._axes_payload(),
        }

    def set_reference_axes(self, axes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """Substitui os eixos de referência por uma configuração serializável."""
        directions = {"X", "Y", "Z"}
        unknown = set(axes) - directions
        if unknown:
            raise ValueError(
                "As direções dos eixos devem ser somente X, Y ou Z."
            )
        normalized: dict[str, tuple[ReferenceAxis, ...]] = {}
        for direction in ("X", "Y", "Z"):
            entries: list[ReferenceAxis] = []
            for item in axes.get(direction, []):
                if not isinstance(item, dict) or "label" not in item or "value" not in item:
                    raise ValueError("Cada eixo deve possuir 'label' e 'value'.")
                try:
                    entries.append(ReferenceAxis(str(item["label"]), float(item["value"])))
                except (TypeError, ValueError) as error:
                    raise ValueError("O valor de cada eixo deve ser numérico.") from error
            normalized[direction] = tuple(entries)
        self.model_service.set_reference_axes(normalized)
        self._notify_model_changed()
        return {"revision": self.model.revision, "axes": self._axes_payload()}

    def create_node(self, x: float, y: float, z: float) -> dict[str, Any]:
        """Cria um nó usando a identidade sequencial padrão do OpenSA."""
        node = self.model_service.create_node(x, y, z)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": self._node_payload(node),
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
            "node": self._node_payload(node),
        }

    def update_node_properties(
        self,
        node_name: str,
        *,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        supports: list[bool] | None = None,
        support_stiffness: list[float] | None = None,
    ) -> dict[str, Any]:
        """Atualiza propriedades de um nó sem permitir alterar sua identidade."""
        node = self.model.nodes.get(node_name)
        if node is None:
            raise ValueError(f"Nó '{node_name}' não encontrado.")
        coordinates = (x, y, z)
        if any(value is not None for value in coordinates) and not all(
            value is not None for value in coordinates
        ):
            raise ValueError("Informe x, y e z juntos para alterar as coordenadas.")
        normalized_coordinates: tuple[float, float, float] | None = None
        if all(value is not None for value in coordinates):
            try:
                normalized_coordinates = tuple(float(value) for value in coordinates)  # type: ignore[arg-type]
            except (TypeError, ValueError) as error:
                raise ValueError("As coordenadas devem ser numéricas.") from error
            if any(not isfinite(value) for value in normalized_coordinates):
                raise ValueError("As coordenadas devem ser números finitos.")

        normalized_supports = self._normalize_bool_values(supports, 6, "apoios")
        normalized_stiffness = self._normalize_nonnegative_values(
            support_stiffness, 6, "rigidezes de mola",
        )
        if (
            normalized_coordinates is None
            and normalized_supports is None
            and normalized_stiffness is None
        ):
            raise ValueError("Informe pelo menos uma propriedade do nó para alterar.")

        if normalized_coordinates is not None:
            node = self.model_service.update_node(node_name, *normalized_coordinates)
        if normalized_supports is not None:
            node = self.model_service.update_supports(node_name, normalized_supports)
        if normalized_stiffness is not None:
            node = self.model_service.update_support_stiffness(node_name, normalized_stiffness)
        self._notify_model_changed()
        return {"revision": self.model.revision, "node": self._node_payload(node)}

    def create_member(
        self,
        start_node: str,
        end_node: str,
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
        member = self.model_service.create_member(start_node, end_node)
        if material is not None and section is not None and geometry is not None:
            member = self._apply_member_properties(member.name, material, section, geometry, profile)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def set_member_rectangular_section(
        self,
        member_names: list[str],
        width_mm: float,
        height_mm: float,
        material: str = "Concreto Estrutural",
    ) -> dict[str, Any]:
        """Aplica uma seção retangular com dimensões explícitas em milímetros."""
        return self.set_member_properties(
            member_names,
            material,
            "Retangular",
            {"b": width_mm, "h": height_mm},
        )

    def delete_node(self, node_name: str) -> dict[str, Any]:
        """Exclui um nó, respeitando as regras de integridade do modelo."""
        if node_name not in self.model.nodes:
            raise ValueError(f"Nó '{node_name}' não encontrado.")
        self.model_service.remove_node(node_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_node": node_name}

    def delete_member(self, member_name: str) -> dict[str, Any]:
        """Exclui um membro e suas ações associadas."""
        if member_name not in self.model.bars:
            raise ValueError(f"Membro '{member_name}' não encontrado.")
        self.model_service.remove_member(member_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "deleted_member": member_name}

    def split_member(self, member_name: str, parts: int) -> dict[str, Any]:
        """Divide um membro em partes iguais, criando nós intermediários."""
        node_names, member_names = self.model_service.split_member(member_name, parts)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "source_member": member_name,
            "created_nodes": list(node_names),
            "created_members": list(member_names),
            "members": [self._member_payload(self.model.bars[name]) for name in member_names],
        }

    def join_members(self, first_member: str, second_member: str) -> dict[str, Any]:
        """Une dois membros adjacentes e colineares."""
        joined = self.model_service.join_members(first_member, second_member)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "deleted_member": second_member,
            "member": self._member_payload(joined),
        }

    def reverse_member(self, member_name: str) -> dict[str, Any]:
        """Inverte os nós inicial e final de um membro."""
        member = self.model_service.reverse_member(member_name)
        self._notify_model_changed()
        return {"revision": self.model.revision, "member": self._member_payload(member)}

    def create_rigid_bar(self, start_node: str, end_node: str) -> dict[str, Any]:
        """Cria uma barra rígida entre dois nós existentes."""
        rigid = self.model_service.create_rigid_bar(start_node, end_node)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "rigid_bar": {
                "name": rigid.name,
                "start_node": rigid.start_node,
                "end_node": rigid.end_node,
            },
        }

    def copy_elements(
        self,
        node_names: list[str] | None,
        member_names: list[str] | None,
        offset: tuple[float, float, float],
    ) -> dict[str, Any]:
        """Copia nós e membros por translação, preservando suas propriedades."""
        copied_nodes, copied_members = self.model_service.copy_elements(
            tuple(node_names or ()),
            tuple(member_names or ()),
            offset,
        )
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "created_nodes": list(copied_nodes),
            "created_members": list(copied_members),
            "members": [self._member_payload(self.model.bars[name]) for name in copied_members],
        }

    def copy_member_properties(
        self,
        source_member: str,
        target_member: str,
        properties: list[str] | None = None,
    ) -> dict[str, Any]:
        """Copia propriedades selecionadas de um membro para outro."""
        available = {"color", "material", "section", "rotation", "offsets", "releases"}
        selected = frozenset(available if properties is None else properties)
        member = self.model_service.copy_member_properties(source_member, target_member, selected)
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

    def update_member_properties(
        self,
        member_names: list[str],
        *,
        material: str | None = None,
        section: str | None = None,
        geometry: dict[str, float] | None = None,
        profile: str | None = None,
        rotation: int | None = None,
        releases: list[bool] | None = None,
        rotation_flexibility_percent: list[int] | None = None,
        solid_face_offsets_mm: list[float] | None = None,
        solid_section_offsets_mm: list[float] | None = None,
        color: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza qualquer combinação de propriedades editáveis dos membros."""
        if not member_names:
            raise ValueError("Informe pelo menos um membro.")
        names = tuple(dict.fromkeys(member_names))
        missing = next((name for name in names if name not in self.model.bars), None)
        if missing is not None:
            raise ValueError(f"Membro '{missing}' não encontrado.")

        if rotation is not None:
            if isinstance(rotation, bool) or not isinstance(rotation, int):
                raise ValueError("A rotação deve ser um número inteiro em graus.")
        normalized_releases = self._normalize_bool_values(releases, 12, "vinculações")
        normalized_flexibility = self._normalize_int_values(
            rotation_flexibility_percent, 6, 0, 99, "percentuais de semirrígidez",
        )
        face_offsets = self._normalize_offsets(solid_face_offsets_mm, "offsets das faces")
        section_offsets = self._normalize_offsets(solid_section_offsets_mm, "offsets da seção")

        if material is not None and material not in self.model.materials:
            raise ValueError(f"Material '{material}' não encontrado.")
        if color is not None:
            self._validate_color(color)

        for name in names:
            member = self.model.bars[name]
            target_material = material or member.material
            target_section = section if section is not None else member.section
            if section is not None:
                material_type = self.model.material_types.get(target_material)
                if section not in self.model.sections.get(material_type, ()):
                    raise ValueError(
                        f"A seção '{section}' não é compatível com o material '{target_material}'."
                    )
            if geometry is not None:
                if target_material not in self.model.materials or not target_section:
                    raise ValueError(
                        "Para alterar a geometria, informe material e seção válidos "
                        "ou mantenha essas propriedades já definidas no membro."
                    )
                self._validate_member_properties(target_material, target_section, geometry)
            elif material is not None and member.section:
                material_type = self.model.material_types.get(material)
                if member.section not in self.model.sections.get(material_type, ()):
                    raise ValueError(
                        "A troca de material tornaria a seção atual incompatível; "
                        "informe também uma seção compatível."
                    )
            if profile is not None and geometry is None and not member.geometry_dict():
                raise ValueError(
                    "Para alterar o perfil sem informar geometria, o membro precisa "
                    "já possuir uma geometria de seção."
                )

        for name in names:
            member = self.model.bars[name]
            if geometry is not None:
                member = self._apply_member_properties(
                    name,
                    material or member.material,
                    section or member.section,
                    geometry,
                    profile,
                )
            else:
                if material is not None:
                    member = self.model_service.assign_material(name, material)
                if section is not None:
                    member = self.model_service.assign_section(name, section)
                if profile is not None:
                    member = self.model_service.assign_profile(
                        name, profile, member.geometry_dict(),
                    )
            if rotation is not None:
                member = self.model_service.update_member_rotation(name, rotation)
            if normalized_releases is not None:
                member = self.model_service.update_member_releases(name, normalized_releases)
            if normalized_flexibility is not None:
                member = self.model_service.update_member_rotation_flexibility_percent(
                    name, normalized_flexibility,
                )
            if face_offsets is not None:
                member = self.model_service.update_member_solid_face_offsets(name, face_offsets)
            if section_offsets is not None:
                member = self.model_service.update_member_solid_section_offsets(
                    name, section_offsets,
                )
            if color is not None:
                member = self.model_service.update_member_color(name, color)

        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "members": [self._member_payload(self.model.bars[name]) for name in names],
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
            "rotation": member.rotation,
            "releases": list(member.releases),
            "rotation_flexibility_percent": list(member.rotation_flexibility_percent),
            "solid_face_offsets_mm": [value * 1000.0 for value in member.solid_face_offsets],
            "solid_section_offsets_mm": [value * 1000.0 for value in member.solid_section_offsets],
            "color": member.color,
        }

    @staticmethod
    def _node_payload(node) -> dict[str, Any]:
        return {
            "name": node.name,
            "x": node.x,
            "y": node.y,
            "z": node.z,
            "supports": list(node.supports),
            "support_stiffness": list(node.support_stiffness),
        }

    @staticmethod
    def _normalize_bool_values(
        values: list[bool] | None,
        expected: int,
        label: str,
    ) -> tuple[bool, ...] | None:
        if values is None:
            return None
        if len(values) != expected or any(not isinstance(value, bool) for value in values):
            raise ValueError(f"As {label} devem possuir exatamente {expected} valores booleanos.")
        return tuple(values)

    @staticmethod
    def _normalize_int_values(
        values: list[int] | None,
        expected: int,
        minimum: int,
        maximum: int,
        label: str,
    ) -> tuple[int, ...] | None:
        if values is None:
            return None
        if (
            len(values) != expected
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
                for value in values
            )
        ):
            raise ValueError(
                f"Os {label} devem possuir {expected} inteiros entre {minimum} e {maximum}."
            )
        return tuple(values)

    @staticmethod
    def _normalize_nonnegative_values(
        values: list[float] | None,
        expected: int,
        label: str,
    ) -> tuple[float, ...] | None:
        if values is None:
            return None
        if len(values) != expected:
            raise ValueError(f"As {label} devem possuir exatamente {expected} valores.")
        try:
            normalized = tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise ValueError(f"As {label} devem ser numéricas.") from error
        if any(not isfinite(value) or value < 0.0 for value in normalized):
            raise ValueError(f"As {label} devem ser números não negativos.")
        return normalized

    @staticmethod
    def _normalize_offsets(
        values: list[float] | None,
        label: str,
    ) -> tuple[float, float] | None:
        if values is None:
            return None
        if len(values) != 2:
            raise ValueError(f"Os {label} devem possuir exatamente dois valores em milímetros.")
        normalized = tuple(float(value) / 1000.0 for value in values)
        if any(not isfinite(value) for value in normalized):
            raise ValueError(f"Os {label} devem ser números finitos.")
        return normalized  # type: ignore[return-value]

    @staticmethod
    def _validate_color(color: str) -> None:
        if not isinstance(color, str) or len(color) != 7 or color[0] != "#":
            raise ValueError("A cor deve estar no formato hexadecimal #RRGGBB.")
        try:
            int(color[1:], 16)
        except ValueError as error:
            raise ValueError("A cor deve estar no formato hexadecimal #RRGGBB.") from error

    def _axes_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            direction: [
                {"label": axis.label, "value": axis.value}
                for axis in self.model.axes.get(direction, ())
            ]
            for direction in ("X", "Y", "Z")
        }

    def _notify_model_changed(self) -> None:
        if self._on_model_changed is not None:
            self._on_model_changed()
