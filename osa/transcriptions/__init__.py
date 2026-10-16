"""Registro dos conversores de formatos externos para o projeto nativo OSA."""

from pathlib import Path

from .contracts import ImportOptions, ImportResult, ProjectImporter, ProjectImportError

__all__ = [
    "ImportOptions",
    "ImportResult",
    "ProjectImportError",
    "import_project",
    "is_import_path",
    "register_importer",
]

_importers: list[ProjectImporter] = []


def register_importer(importer: ProjectImporter) -> None:
    """Novos formatos implementam o contrato sem alterar a persistência nativa."""
    if any(item.name == importer.name for item in _importers):
        raise ValueError(f"Conversor já registrado: {importer.name}")
    _importers.append(importer)


def _registered_importers() -> tuple[ProjectImporter, ...]:
    # Importação tardia evita ciclos entre domínio e persistência.
    from .eberick import EberickImporter

    return (EberickImporter(), *_importers)


def is_import_path(path: str | Path) -> bool:
    name = Path(path).name.casefold()
    return any(
        name.endswith(extension)
        for item in _registered_importers()
        for extension in item.extensions
    )


def import_project(
    path: str | Path, options: ImportOptions | None = None
) -> ImportResult:
    options = options or ImportOptions()
    options.validate()
    name = Path(path).name.casefold()
    for importer in _registered_importers():
        if any(name.endswith(extension) for extension in importer.extensions):
            return importer.read(path, options)
    raise ProjectImportError("Não há conversor registrado para este formato.")
