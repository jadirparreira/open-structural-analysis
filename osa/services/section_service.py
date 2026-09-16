from osa.domain import StructuralModel


class SectionService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def set_included_families(self, material_type: str, families: list[str]) -> None:
        self.model.sections[material_type] = list(dict.fromkeys(families))
        self.model._touch()

    def available_for_material(self, material_name: str) -> list[str]:
        material_type = self.model.material_types.get(material_name)
        return list(self.model.sections.get(material_type, ()))
