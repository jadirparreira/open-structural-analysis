"""Leitura e gravação atômica de arquivos de projeto."""

from __future__ import annotations

import json
from pathlib import Path

from osa.domain import StructuralModel
from osa.transcriptions import ImportOptions, import_project, is_import_path

from .project_serializer import ProjectSerializer


class ProjectRepository:
    def __init__(self, serializer: ProjectSerializer | None = None) -> None:
        self.serializer = serializer or ProjectSerializer()

    def save(self, model: StructuralModel, path: str | Path, thumbnail: str | None = None) -> None:
        target = Path(path)
        if is_import_path(target):
            raise ValueError("Salve o modelo convertido como .osa; o PRJ de origem é somente leitura.")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.serializer.dump(model, thumbnail), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)

    def load(self, model: StructuralModel, path: str | Path, *, import_options: ImportOptions | None = None) -> dict | None:
        if is_import_path(path):
            result = import_project(path, import_options)
            self.serializer.load_into(model, result.project_data)
            return result.report
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.serializer.load_into(model, data)
        return None

    def load_thumbnail(self, path: str | Path) -> str | None:
        if is_import_path(path):
            return None
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return self.serializer.thumbnail_from(data)
