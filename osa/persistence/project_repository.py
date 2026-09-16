"""Leitura e gravação atômica de arquivos de projeto."""

from __future__ import annotations

import json
from pathlib import Path

from osa.domain import StructuralModel

from .project_serializer import ProjectSerializer


class ProjectRepository:
    def __init__(self, serializer: ProjectSerializer | None = None) -> None:
        self.serializer = serializer or ProjectSerializer()

    def save(self, model: StructuralModel, path: str | Path) -> None:
        target = Path(path)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.serializer.dump(model), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(target)

    def load(self, model: StructuralModel, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.serializer.load_into(model, data)
