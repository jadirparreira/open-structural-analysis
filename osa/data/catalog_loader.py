"""Carregamento validado dos catálogos JSON."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files


class CatalogLoader:
    @staticmethod
    @cache
    def _read(filename: str) -> dict:
        resource = files("osa.data").joinpath(filename)
        data = json.loads(resource.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError(f"Versão não suportada do catálogo {filename}.")
        return data

    def materials(self) -> tuple[dict, ...]:
        return tuple(dict(item) for item in self._read("materials.json")["materials"])

    def section_families(self, material_type: str) -> tuple[dict, ...]:
        filenames = {
            "Aço": "sections_steel.json",
            "Concreto": "sections_concrete.json",
            "Madeira": "sections_wood.json",
        }
        try:
            filename = filenames[material_type]
        except KeyError as error:
            raise ValueError(f"Tipo de material desconhecido: {material_type}") from error
        return tuple(dict(item) for item in self._read(filename)["families"])

    def profiles(self, material_type: str, family: str) -> tuple[dict, ...]:
        match = next((item for item in self.section_families(material_type) if item["name"] == family), None)
        return tuple(dict(item) for item in match.get("profiles", ())) if match else ()

    def w_profiles(self) -> tuple[dict, ...]:
        return self.profiles("Aço", "W Laminado")
