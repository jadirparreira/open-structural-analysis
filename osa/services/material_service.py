from dataclasses import replace

from osa.data import CatalogLoader
from osa.domain import StructuralModel

PROTECTED_MATERIALS = frozenset(item["name"] for item in CatalogLoader().materials())


class MaterialService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def upsert(self, name: str, material_type: str, values: tuple[float, ...]) -> None:
        if not name.strip():
            raise ValueError("Informe o nome do material.")
        if material_type not in {"Aço", "Concreto", "Madeira"}:
            raise ValueError("Tipo de material inválido.")
        if len(values) != 6 or any(float(value) < 0 for value in values):
            raise ValueError("Informe seis propriedades não negativas.")
        name = name.strip()
        properties = tuple(float(value) for value in values)
        self.model.materials[name] = properties
        self.model.material_types[name] = material_type
        # Member quantities use a material snapshot; keep it consistent with
        # the catalog values used by the solver and by plate self-weight.
        for member_name, member in tuple(self.model.bars.items()):
            if member.material == name:
                self.model.bars[member_name] = replace(member, material_values=properties[:4])
        self.model._touch()

    def remove(self, name: str) -> None:
        if name in PROTECTED_MATERIALS:
            raise ValueError("Os materiais padrão não podem ser removidos.")
        self.model.materials.pop(name, None)
        self.model.material_types.pop(name, None)
        self.model._touch()
