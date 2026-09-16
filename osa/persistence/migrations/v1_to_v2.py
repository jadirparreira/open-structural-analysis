"""Normalização documental do formato v1.

O serializador lê v1 diretamente para preservar os campos opcionais presentes
em arquivos antigos; uma gravação posterior produz automaticamente o v2.
"""


def migrate(data: dict) -> dict:
    migrated = dict(data)
    migrated["format"] = "open-structural-analysis/v2"
    migrated["members"] = list(data.get("bars", ()))
    migrated.setdefault("materials", {})
    migrated.setdefault("included_sections", {})
    migrated.setdefault("actions", [])
    migrated.setdefault("load_cases", [])
    migrated.setdefault("load_combinations", [])
    migrated.setdefault("results", [])
    return migrated
