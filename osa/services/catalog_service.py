"""Consulta aos catálogos sem acoplar widgets aos arquivos JSON."""

from osa.data import CatalogLoader


class CatalogService:
    def __init__(self, loader: CatalogLoader | None = None) -> None:
        self.loader = loader or CatalogLoader()

    def w_profile_names(self) -> list[str]:
        return [profile["name"] for profile in self.loader.w_profiles()]

    def w_profile(self, name: str) -> dict | None:
        return next((profile for profile in self.loader.w_profiles() if profile["name"] == name), None)
