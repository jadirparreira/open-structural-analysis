from osa.domain import StructuralModel

PROTECTED_MATERIALS = {
    "ASTM A36", "ASTM A572 Gr 50", "NBR MR 250", "NBR AR 350", "NBR AR 415", "SAE 1020",
    "Concreto Estrutural", "Madeira Estrutural",
}


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
        self.model.materials[name.strip()] = tuple(float(value) for value in values)
        self.model.material_types[name.strip()] = material_type
        self.model._touch()

    def remove(self, name: str) -> None:
        if name in PROTECTED_MATERIALS:
            raise ValueError("Os materiais padrão não podem ser removidos.")
        self.model.materials.pop(name, None)
        self.model.material_types.pop(name, None)
        self.model._touch()
