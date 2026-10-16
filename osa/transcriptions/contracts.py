"""Contrato independente da interface para leitores de formatos externos."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


class ProjectImportError(ValueError):
    """Formato não suportado ou conteúdo que não pode ser convertido com segurança."""


@dataclass(frozen=True)
class ImportOptions:
    """Hipóteses explícitas do primeiro importador experimental.

    Os valores nativos de tensão são força/comprimento²; peso específico usa
    força/comprimento³. O destino OSA usa m, mm e kN.
    """

    length_unit: str = "cm"
    force_unit: str = "kgf"
    first_floor_elevation_m: float = 0.0
    include_lower_columns: bool = True
    preserve_end_offsets: bool = True
    import_material_properties: bool = True
    poisson_ratio: float = 0.2

    def validate(self) -> None:
        if self.length_unit not in ("mm", "cm", "m"):
            raise ProjectImportError("Unidade de comprimento não suportada.")
        if self.force_unit not in ("N", "kN", "kgf", "tf"):
            raise ProjectImportError("Unidade de força não suportada.")
        if not math.isfinite(self.first_floor_elevation_m):
            raise ProjectImportError("A cota do primeiro pavimento deve ser finita.")
        if not math.isfinite(self.poisson_ratio) or not -1.0 < self.poisson_ratio < 0.5:
            raise ProjectImportError(
                "O coeficiente de Poisson deve estar entre -1 e 0,5."
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImportResult:
    project_data: dict[str, Any]
    report: dict[str, Any]


class ProjectImporter(Protocol):
    name: str
    extensions: tuple[str, ...]

    def read(self, path: str | Path, options: ImportOptions) -> ImportResult: ...


def require_import_review(model) -> None:
    from .plates import require_no_pending_plates

    report = getattr(model, "import_metadata", {})
    require_no_pending_plates(report)
    if report.get("requires_review"):
        raise ValueError(
            "Este modelo veio de uma importação experimental. Revise unidades, "
            "geometria, materiais, apoios, vínculos e cargas no OSA e confirme "
            "a revisão antes de processar."
        )
