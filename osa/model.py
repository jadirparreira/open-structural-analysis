"""Fachada de compatibilidade para a antiga API ``osa.model``."""

from osa.data import CatalogLoader
from osa.domain import ActionDefinition, ActionGroup, Bar, Member, Node, ReferenceAxis
from osa.domain.model import StructuralModel as _StructuralModel
from osa.persistence import ProjectRepository, ProjectSerializer


class StructuralModel(_StructuralModel):
    def __init__(self) -> None:
        loader = CatalogLoader()
        catalog = loader.materials()
        materials = {
            item["name"]: (
                item["elastic_modulus_gpa"], item["shear_modulus_gpa"],
                item["poisson_ratio"], item["density_kg_m3"],
            )
            for item in catalog
        }
        material_types = {item["name"]: item["type"] for item in catalog}
        defaults = {
            material_type: [family["name"] for family in loader.section_families(material_type)]
            for material_type in ("Aço", "Concreto", "Madeira")
        }
        super().__init__(materials=materials, material_types=material_types, sections=defaults)

    def as_dict(self) -> dict:
        return ProjectSerializer().dump(self)

    def load_dict(self, data: dict) -> None:
        ProjectSerializer().load_into(self, data)

    def save(self, path) -> None:
        ProjectRepository().save(self, path)

    def load(self, path) -> None:
        ProjectRepository().load(self, path)


__all__ = ["ActionDefinition", "ActionGroup", "Bar", "Member", "Node", "ReferenceAxis", "StructuralModel"]
