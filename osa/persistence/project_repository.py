"""Leitura e gravação atômica de arquivos de projeto."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from osa.domain import StructuralModel
from osa.transcriptions import ImportOptions, import_project, is_import_path

from .project_reader import ProjectReader
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

    def load(
        self, model: StructuralModel, path: str | Path,
        *, import_options: ImportOptions | None = None,
        progress: Callable[[str], None] | None = None,
        yield_control: Callable[[], None] | None = None,
        defer_results: bool = True,
    ) -> dict | None:
        if is_import_path(path):
            result = import_project(path, import_options)
            if progress is not None:
                progress("Validando a estrutura importada…")
            self.serializer.load_into(
                model, result.project_data, yield_control=yield_control, consume=True,
            )
            return result.report
        if progress is not None:
            progress("Lendo os dados e resultados do modelo…")
        with Path(path).open(encoding="utf-8") as stream:
            data = ProjectReader(
                stream, yield_control=yield_control, defer_results=defer_results,
                skip_redundant_bars=True,
            ).read()
        if progress is not None:
            progress("Validando a estrutura…")
        self.serializer.load_into(model, data, yield_control=yield_control, consume=True)
        return None

    def load_thumbnail(self, path: str | Path) -> str | None:
        if is_import_path(path):
            return None
        # OSA writes previews last. Seek directly to the small tail instead of
        # decoding hundreds of MB of analysis data to display a recent project.
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 256 * 1024))
            tail = stream.read().decode("utf-8", errors="replace")
        matches = tuple(re.finditer(r'(?<!\\)"thumbnail"\s*:\s*', tail))
        if matches:
            try:
                value, end = json.JSONDecoder().raw_decode(tail, matches[-1].end())
                if tail[end:].strip() == "}":
                    return self.serializer.thumbnail_from({"thumbnail": value})
            except json.JSONDecodeError:
                pass
        with Path(path).open(encoding="utf-8") as stream:
            value = ProjectReader(stream).read_thumbnail()
        return self.serializer.thumbnail_from({"thumbnail": value})
