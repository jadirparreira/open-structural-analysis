"""Contrato de transferência de lajes para o futuro domínio de placas do OSA.

Preparar e salvar candidatos não cria elementos analíticos. A implementação
nativa futura recebe o lote completo somente após validar todos os registros.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .contracts import ProjectImportError

PLATE_SCHEMA = "osa-plate-transfer/v1"


@dataclass(frozen=True)
class PlateDefinition:
    source_id: str
    name: str
    floor_id: int
    contour_m: tuple[tuple[float, float, float], ...]
    openings_m: tuple[tuple[tuple[float, float, float], ...], ...]
    thickness_m: float
    material_name: str


class PlateTarget(Protocol):
    def import_plates(self, plates: tuple[PlateDefinition, ...]) -> dict[str, str]:
        """Cria o lote em uma transação e retorna source_id → ID nativo."""
        ...


def prepare_plate_transfer(slabs, elevations, length):
    records = []
    for slab in slabs:
        floor_id = slab.get("floor_id")
        offset = slab.get("elevation_offset_raw")
        z = elevations.get(floor_id)
        if z is not None and offset is not None:
            z += float(offset) * length
        else:
            z = None

        def contour(points, elevation=z):
            if points is None or elevation is None:
                return None
            return [
                [float(x) * length, float(y) * length, elevation] for x, y in points
            ]

        holes = slab.get("openings_xy_raw")
        geometry = {
            "contour_m": contour(slab.get("contour_xy_raw")),
            "openings_m": None
            if holes is None or z is None
            else [contour(points) for points in holes],
            "thickness_m": None
            if slab.get("thickness_raw") is None
            else float(slab["thickness_raw"]) * length,
            "material_name": slab.get("material_name"),
        }
        missing = [name for name, value in geometry.items() if value is None]
        if floor_id not in elevations:
            missing.append("floor_id")
        records.append(
            {
                "source_id": f"eberick:{slab['object_id']}",
                "source_object_id": slab["object_id"],
                "name": slab.get("name") or f"Laje_{slab['object_id']}",
                "floor_id": floor_id,
                "floor_name": slab.get("floor_name"),
                "floor_elevation_m": elevations.get(floor_id),
                "geometry": geometry,
                "boundary_element_ids": list(slab.get("boundary_element_ids", ())),
                "status": "pending_plate_support",
                "mapping_status": "incomplete" if missing else "prepared",
                "missing_fields": missing,
            }
        )
    return {
        "schema": PLATE_SCHEMA,
        "units": "m",
        "representation": "plate",
        "records": records,
    }


def pending_plate_count(report):
    return sum(
        record.get("status") != "imported"
        for record in report.get("plate_transfer", {}).get("records", ())
    )


def require_no_pending_plates(report):
    count = pending_plate_count(report)
    if count:
        raise ValueError(
            f"Há {count} laje(s) preservada(s) para a futura integração com placas. "
            "Elas ainda não participam do modelo de cálculo; o processamento "
            "ficará disponível após sua implementação e transcrição."
        )


def _contour(value, label):
    try:
        points = tuple(tuple(float(v) for v in point) for point in value)
    except (TypeError, ValueError) as error:
        raise ProjectImportError(f"{label}: contorno inválido.") from error
    if any(
        len(point) != 3 or not all(math.isfinite(v) for v in point) for point in points
    ):
        raise ProjectImportError(f"{label}: coordenadas inválidas.")
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(points) < 3 or len(set(points)) != len(points):
        raise ProjectImportError(
            f"{label}: contorno precisa de três vértices distintos."
        )
    # Os candidatos atuais são horizontais. Outras orientações exigem um
    # contrato de referência de superfície antes da conexão com o mesher.
    if any(
        not math.isclose(p[2], points[0][2], rel_tol=0, abs_tol=1e-9) for p in points
    ):
        raise ProjectImportError(f"{label}: placa não horizontal ainda não mapeada.")
    area = sum(
        a[0] * b[1] - b[0] * a[1] for a, b in zip(points, (*points[1:], points[0]))
    )
    if abs(area) <= 1e-12:
        raise ProjectImportError(f"{label}: contorno degenerado.")
    return points


def connect_plates(transfer, target: PlateTarget):
    """Ponto de integração futuro; não altera as pendências do projeto por si só.

    O domínio nativo deve persistir os IDs retornados e o status imported junto
    aos elementos de placa criados, na mesma transação do projeto.
    """
    if transfer.get("schema") != PLATE_SCHEMA or transfer.get("units") != "m":
        raise ProjectImportError("Contrato de placas não reconhecido.")
    definitions = []
    for record in transfer.get("records", ()):
        if record.get("status") == "imported":
            continue
        if record.get("missing_fields") or record.get("mapping_status") != "prepared":
            raise ProjectImportError(
                f"A laje {record['name']} ainda possui campos sem mapeamento."
            )
        geometry = record["geometry"]
        thickness = float(geometry["thickness_m"])
        if (
            not math.isfinite(thickness)
            or thickness <= 0
            or not geometry.get("material_name")
        ):
            raise ProjectImportError(
                f"Espessura/material de {record['name']} inválido."
            )
        definitions.append(
            PlateDefinition(
                source_id=record["source_id"],
                name=record["name"],
                floor_id=record["floor_id"],
                contour_m=_contour(geometry["contour_m"], record["name"]),
                openings_m=tuple(
                    _contour(points, record["name"])
                    for points in geometry["openings_m"]
                ),
                thickness_m=thickness,
                material_name=geometry["material_name"],
            )
        )
    if len({p.source_id for p in definitions}) != len(definitions):
        raise ProjectImportError("IDs de laje repetidos.")
    return target.import_plates(tuple(definitions))
