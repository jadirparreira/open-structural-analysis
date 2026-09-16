from osa.domain import StructuralModel

PROTECTED_MATERIALS = {"Aço Estrutural", "Concreto Estrutural", "Madeira Estrutural"}


class MaterialService:
    def __init__(self, model: StructuralModel) -> None:
        self.model = model

    def upsert(self, name: str, material_type: str, values: tuple[float, float, float, float]) -> None:
        if not name.strip():
            raise ValueError("Informe o nome do material.")
        if material_type not in {"Aço", "Concreto", "Madeira"}:
            raise ValueError("Tipo de material inválido.")
        if len(values) != 4 or any(float(value) < 0 for value in values):
            raise ValueError("Informe quatro propriedades não negativas.")
        self.model.materials[name.strip()] = tuple(float(value) for value in values)
        self.model.material_types[name.strip()] = material_type
        self.model._touch()

    def remove(self, name: str) -> None:
        if name in PROTECTED_MATERIALS:
            raise ValueError("Os materiais padrão não podem ser removidos.")
        self.model.materials.pop(name, None)
        self.model.material_types.pop(name, None)
        self.model._touch()
