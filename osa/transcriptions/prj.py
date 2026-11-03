"""Transcrição experimental do lançamento PRJ por compatibilidade de layout.

A leitura interpreta os dados serializados sem executar código do arquivo.
Vínculos e cargas ainda não calibrados ficam no relatório, sem serem apresentados
como cargas ou apoios analíticos recuperados.
"""

from __future__ import annotations

import math
import re
import statistics
import struct
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .contracts import ImportOptions, ImportResult, ProjectImportError
from .prj_reader import LayoutError, Reader, extract, load_stream
from .prj_reader.slabs import is_slab_element_class
from .plates import prepare_plate_transfer

_REFERENCE_CODE = 3419
_COLUMN_AXIS_LAYOUT_CODES = frozenset({3075, 3219, 3575})
# Estes dados não geram ações no OSA. Se um deles falhar dentro de uma viga
# ou pilar, o decodificador do elemento também falha e impede a importação.
_EVIDENCE_ONLY_CLASSES = frozenset(
    {
        "AcaoPermanente",
        "AcaoAcidental",
        "Combinacao",
        "GrupoAcoes",
        "TCarregamentosAtivos",
        "TIdCarregamento",
        "ElPilarFundacao",
        "Parede",
        "Escada",
        "TRampa",
        "ElementoEscada",
    }
)

_IMPORTED_LAUNCH_CLASSES = frozenset(
    {"ElementoViga", "ElementoTrecho", "ElementoPilar", "ElPilarFundacao"}
)
_LAUNCH_METADATA_CLASSES = frozenset({"Pavimento", "CroquiPavimento"})


def _importable_column(column):
    if column.get("referenced_by_beam"):
        return True
    foundation = column.get("foundation_raw") or {}
    return column.get("class_name") == "ElPilarFundacao" and (
        (foundation.get("kind") == "pile_cap" and foundation.get("bar_height_raw") is not None)
        or (foundation.get("kind") == "pad_footing" and foundation.get("settlement_depth_raw") is not None)
    )


def _same_column_geometry(first, second):
    return (
        first.get("name") == second.get("name")
        and first.get("xy_raw") == second.get("xy_raw")
        and first.get("rectangular_dimensions_candidate_raw")
        == second.get("rectangular_dimensions_candidate_raw")
    )


def _beam_section_candidate_3075(section):
    """Perfil observado com dois campos adicionais ainda sem semântica confirmada."""
    values = section.get("geometric_values_raw", ())
    return (
        len(values) == 7
        and section.get("shape_code_raw") == 0
        and values[0] > 0 and values[1] > 0
        and values[4] > 0 and values[5] > 0 and values[1] < values[5]
        and all(abs(values[index]) < 1e-12 for index in (2, 3, 6))
    )


def _active_columns(data):
    """Include CAD-only column records when they bridge native columns across floors."""
    columns = list(data.get("columns", ()))
    active = [column for column in columns if _importable_column(column)]
    active_ids = {column["object_id"] for column in active}
    floor_order = [item["floor_id"] for item in data.get("croquis", ())]
    floor_indices = {floor_id: index for index, floor_id in enumerate(floor_order)}
    by_floor = {}
    for column in active:
        by_floor.setdefault(column.get("floor_id"), []).append(column)

    for column in columns:
        if (
            column.get("object_id") in active_ids
            or column.get("class_name") != "ElementoPilar"
            or column.get("region_role") != "base_cad"
        ):
            continue
        index = floor_indices.get(column.get("floor_id"))
        if index is None or index == 0 or index + 1 >= len(floor_order):
            continue
        previous_floor = floor_order[index - 1]
        next_floor = floor_order[index + 1]
        has_previous_column = any(
            candidate.get("class_name") == "ElPilarFundacao"
            and _same_column_geometry(candidate, column)
            for candidate in by_floor.get(previous_floor, ())
        )
        has_next_column = any(
            candidate.get("referenced_by_beam")
            and _same_column_geometry(candidate, column)
            for candidate in by_floor.get(next_floor, ())
        )
        if has_previous_column and has_next_column:
            active.append(column)
            active_ids.add(column["object_id"])
            by_floor.setdefault(column.get("floor_id"), []).append(column)
    return active


class PrjImporter:
    name = "PRJ"
    extensions = (".prj", ".prj.zip")

    def read(self, path: str | Path, options: ImportOptions) -> ImportResult:
        options.validate()
        try:
            raw, source = load_stream(path)
            reader = Reader(raw, source)
            if len(reader.classes.get("Projeto", ())) != 1:
                raise ProjectImportError(
                    "Não foi identificado um único registro de projeto no PRJ. "
                    "O modelo aberto foi mantido."
                )
            data = extract(reader)
        except (LayoutError, struct.error, zipfile.BadZipFile) as error:
            raise ProjectImportError(
                f"Não foi possível interpretar o PRJ: {error}"
            ) from error
        try:
            return self.convert(data, options)
        except ProjectImportError as error:
            raise ProjectImportError(
                f"PRJ com código interno {reader.version}: {error} "
                "O modelo aberto foi mantido. O registro indicado precisa "
                "ser conferido antes de ampliar o mapeamento desse layout."
            ) from error

    def convert(self, data: dict, options: ImportOptions) -> ImportResult:
        """Recebe evidências do leitor; permite testes sem dependências gráficas."""
        options.validate()
        self._validate_launch(data)
        length = {"mm": 0.001, "cm": 0.01, "m": 1.0}[options.length_unit]
        force = {"N": 0.001, "kN": 1.0, "kgf": 0.01, "tf": 10.0}[
            options.force_unit
        ]
        builder = _LaunchBuilder(data, options, length, force)
        return builder.build()

    @staticmethod
    def _validate_launch(data: dict) -> None:
        blocking_errors = [
            item
            for item in data.get("decode_errors", ())
            if item["class_name"] not in _EVIDENCE_ONLY_CLASSES
        ]
        if blocking_errors:
            first = blocking_errors[0]
            raise ProjectImportError(
                f"O layout de {first['class_name']} não foi reconhecido "
                f"em {first['offset_hex']}: {first.get('error', 'registro incompatível')}."
            )
        if not data.get("beams") or not data.get("floors") or not data.get("croquis"):
            raise ProjectImportError(
                "Não foi possível recuperar o lançamento com pavimentos, croquis "
                "e vigas no layout conhecido."
            )
        inventory = {
            item["class_name"]: item["count"] for item in data.get("inventory", ())
        }
        expected = {
            "pavimentos": (inventory.get("Pavimento", 0), data["floors"]),
            "croquis": (inventory.get("CroquiPavimento", 0), data["croquis"]),
            "vigas": (
                inventory.get("ElementoViga", 0),
                data.get("beam_groups", data["beams"]),
            ),
            "pontos intermediários": (
                inventory.get("ElementoNo", 0),
                data.get("points", ()),
            ),
            "pilares": (
                inventory.get("ElementoPilar", 0) + inventory.get("ElPilarFundacao", 0),
                data.get("columns", ()),
            ),
            "registros de laje": (
                sum(
                    count
                    for name, count in inventory.items()
                    if is_slab_element_class(name)
                ),
                data.get("slabs", ()),
            ),
        }
        for label, (count, records) in expected.items():
            if count != len(records):
                raise ProjectImportError(
                    f"A contagem de {label} não confere: {len(records)} lidos "
                    f"de {count} registros. Importação cancelada para evitar omissões."
                )
        if "beam_groups" in data:
            declared = sum(beam["segment_count"] for beam in data["beam_groups"])
            complete_lists = all(
                beam.get("segment_count", 0) + beam.get("null_segment_slots", 0)
                == beam.get("declared_segment_count", beam.get("segment_count", 0))
                for beam in data["beam_groups"]
            )
            inventory_matches = (
                data.get("internal_version_code") != _REFERENCE_CODE
                or inventory.get("ElementoTrecho", 0) == len(data["beams"])
            )
            if (
                declared != len(data["beams"])
                or not complete_lists
                or not inventory_matches
            ):
                raise ProjectImportError(
                    "A contagem dos trechos de viga não confere com o lançamento."
                )
            segment_ids = [beam["segment_id"] for beam in data["beams"]]
            if len(set(segment_ids)) != len(segment_ids):
                raise ProjectImportError(
                    "Um trecho de viga foi associado a mais de uma posição do lançamento."
                )
        floors = {f["floor_id"] for f in data["floors"]}
        if len(floors) != len(data["floors"]):
            raise ProjectImportError("IDs de pavimento repetidos não são suportados.")
        sketch_floors = [item["floor_id"] for item in data["croquis"]]
        if len(set(sketch_floors)) != len(sketch_floors):
            raise ProjectImportError("Mais de um croqui para o mesmo pavimento.")
        for record in (
            *data["beams"],
            *data.get("columns", ()),
            *data.get("points", ()),
        ):
            if record.get("floor_id") not in floors:
                raise ProjectImportError("Há elementos sem pavimento identificado.")
            if record["floor_id"] not in sketch_floors:
                raise ProjectImportError("Há elementos sem croqui identificado.")
        for sketch in data["croquis"]:
            count = sum(
                b.get("floor_id") == sketch["floor_id"]
                for b in data.get("beam_groups", data["beams"])
            )
            if sketch["floor_id"] not in floors or count != sketch["beam_count"]:
                raise ProjectImportError(
                    "A contagem de vigas/pavimentos do croqui não confere."
                )
        active = _active_columns(data)
        anchor_records = [
            *active,
            *(
                point
                for point in data.get("points", ())
                if point.get("referenced_by_beam")
            ),
        ]
        columns_by_id = {column["object_id"]: column for column in anchor_records}
        if len(columns_by_id) != len(anchor_records):
            raise ProjectImportError("Referências de pilares/pontos repetidas.")
        for beam in data["beams"]:
            for endpoint in ("support_i_id", "support_j_id"):
                column = columns_by_id.get(beam[endpoint])
                if column is None or column["floor_id"] != beam["floor_id"]:
                    raise ProjectImportError(
                        "Referência entre trecho, pilar/ponto e pavimento não resolvida."
                    )
        for column in data.get("columns", ()):
            if _importable_column(column):
                continue
            if column.get("class_name") == "ElPilarFundacao":
                continue
            if (
                data.get("internal_version_code") == 3219
                and column.get("class_name") == "ElementoPilar"
                and column.get("region_role") == "base_cad"
            ):
                continue
            duplicate = any(
                other["name"] == column["name"]
                and other["xy_raw"] == column["xy_raw"]
                and other["rectangular_dimensions_candidate_raw"]
                == column["rectangular_dimensions_candidate_raw"]
                and (
                    other.get("floor_id") == column.get("floor_id")
                    or (
                        column.get("region_role") == "base_cad"
                        and column.get("class_name") == "ElementoPilar"
                        and other.get("class_name") == "ElPilarFundacao"
                    )
                )
                for other in active
            )
            if column.get("region_role") != "base_cad" or not duplicate:
                raise ProjectImportError(
                    "Há um pilar cuja função/continuidade não foi resolvida. Importação cancelada para não omiti-lo."
                )
        sections = {
            section["object_id"]: section for section in data.get("sections", ())
        }
        for kind, records in (("beam", data["beams"]), ("column", active)):
            for record in records:
                section = sections.get(record["section_id"])
                if section is None:
                    raise ProjectImportError("Referência de seção não resolvida.")
                values = section["geometric_values_raw"]
                zeros = (0, 1, 2, 3, 6) if kind == "beam" else (1, 3, 4, 6)
                rectangular = (
                    len(values) == 7
                    and section["shape_code_raw"] == 0
                    and all(abs(values[index]) < 1e-12 for index in zeros)
                    and (
                        kind == "beam"
                        or math.isclose(values[0], values[2], abs_tol=1e-12)
                    )
                )
                supported_candidate = (
                    kind == "beam"
                    and data.get("internal_version_code") == 3075
                    and _beam_section_candidate_3075(section)
                )
                if not rectangular and not supported_candidate:
                    raise ProjectImportError(
                        "A seção não corresponde ao perfil retangular estudado; importação cancelada."
                    )


class _LaunchBuilder:
    def __init__(self, data, options, length, force):
        self.data, self.options = data, options
        self.length, self.force = length, force
        self.nodes: list[dict] = []
        self.members: list[dict] = []
        self.rigid: list[dict] = []
        self.coordinates: dict[tuple[float, float, float], str] = {}
        self.next_node_index = 1
        self.next_member_index = 1
        self.next_foundation_member_index: int | None = None
        self.node_sources: dict[str, dict] = {}
        self.member_pairs: set[frozenset[str]] = set()
        self.materials: dict[str, dict] = {}
        self.sections_by_id = {
            section["object_id"]: section for section in data.get("sections", ())
        }
        self.member_sources: dict[str, dict] = {}
        self.anchor_nodes: dict[int, str] = {}
        self.column_axes: dict[int, tuple[float, float]] = {}
        self.column_axis_evidence: list[dict] = []
        self.column_axis_rejected: list[dict] = []
        self.section_review: list[dict] = []
        self.support_candidates: list[dict] = []
        self.omitted_lower_columns = 0
        self.omitted_column_segments = 0
        self.omitted_column_details: list[dict] = []
        self.warnings = [
            "Unidades e cotas foram interpretadas segundo as opções desta importação.",
            (
                "Apoios, molas e liberações não foram transcritos. Nós ficam livres e "
                "barras sem liberações até a revisão no OSA."
            ),
            (
                "Cargas, paredes e combinações não foram aplicados ao modelo "
                "de cálculo. As evidências recuperadas permanecem neste relatório."
            ),
        ]
        source_code = data.get("internal_version_code")
        if source_code != _REFERENCE_CODE:
            self.warnings.insert(
                0,
                f"O código interno {source_code} foi lido por reconhecimento de layout. "
                "A validação de uma amostra real não garante cobertura de todos os "
                "projetos desse código nem equivalência entre versões.",
            )
        optional_errors = data.get("decode_errors", ())
        if optional_errors:
            names = sorted({item["class_name"] for item in optional_errors})
            self.warnings.append(
                f"{len(optional_errors)} registros auxiliares não foram interpretados "
                f"({', '.join(names)}). Esses dados não foram aplicados ao modelo; "
                "os detalhes das falhas acompanham o relatório salvo no .osa."
            )

    @staticmethod
    def _number(value, label):
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ProjectImportError(
                f"{label}: valor numérico ausente ou inválido."
            ) from error
        if not math.isfinite(result):
            raise ProjectImportError(f"{label}: valor não finito.")
        return result

    def _node(self, xyz, preferred):
        xyz = tuple(self._number(value, "Coordenada") for value in xyz)
        key = tuple(round(value, 9) for value in xyz)
        if key in self.coordinates:
            name = self.coordinates[key]
            sources = self.node_sources[name]["original_names"]
            if preferred not in sources:
                sources.append(preferred)
            return name
        name = f"N{self.next_node_index}"
        self.next_node_index += 1
        self.nodes.append(
            {
                "name": name,
                "x": xyz[0],
                "y": xyz[1],
                "z": xyz[2],
                "supports": [False] * 6,
                "support_stiffness": [0.0] * 6,
            }
        )
        self.coordinates[key] = name
        self.node_sources[name] = {"original_names": [preferred]}
        return name

    @staticmethod
    def _floor_name(floor):
        clean = re.sub(r"\s+", "_", str(floor["name"]).strip())
        return clean or str(floor["floor_id"])

    def _resolve_column_axes(self, columns):
        """Infer section centers from beam faces in the observed PRJ layouts.

        An insertion can be at the center or at a face. Each orthogonal beam
        endpoint supplies only the coordinate along the beam; the transverse
        coordinate may carry a genuine eccentricity.
        """
        by_id = {column["object_id"]: column for column in columns}
        tolerance = 0.0001 / self.length  # 0.1 mm, in the source length unit
        half_extents = {}
        candidates = {ident: [[], []] for ident in by_id}
        for ident, column in by_id.items():
            width, height = (
                self._number(value, "Seção do pilar")
                for value in column["rectangular_dimensions_candidate_raw"]
            )
            angle = self._number(column.get("rotation_candidate_rad", 0.0), "Rotação")
            cosine, sine = abs(math.cos(angle)), abs(math.sin(angle))
            half_extents[ident] = (
                (width * cosine + height * sine) / 2,
                (width * sine + height * cosine) / 2,
            )

        version = self.data.get("internal_version_code")
        if version in _COLUMN_AXIS_LAYOUT_CODES:
            for beam in self.data["beams"]:
                start, end = beam["xy_i_raw"], beam["xy_j_raw"]
                dx, dy = end[0] - start[0], end[1] - start[1]
                length = math.hypot(dx, dy)
                if length <= 1e-12:
                    continue
                direction = (dx / length, dy / length)
                # Algumas vigas variam menos de 1 mm na direção transversal.
                # Só as consideramos alinhadas quando ambos os limites são atendidos.
                def aligned(transverse, component):
                    return abs(component) < 1e-6 or (
                        version in (3075, 3575)
                        and abs(component) <= 0.001
                        and abs(transverse) * self.length <= 0.001
                    )

                axis = (
                    0 if aligned(dy, direction[1])
                    else 1 if aligned(dx, direction[0])
                    else None
                )
                if axis is None:
                    continue
                for side, sign in (("i", -1), ("j", 1)):
                    ident = beam[f"support_{side}_id"]
                    column = by_id.get(ident)
                    if column is None:
                        continue
                    angle = self._number(column.get("rotation_candidate_rad", 0.0), "Rotação")
                    if abs(math.sin(2 * angle)) > 1e-6:
                        continue
                    half = half_extents[ident][axis]
                    value = beam[f"xy_{side}_raw"][axis] + sign * math.copysign(
                        half, direction[axis]
                    )
                    if abs(value - column["xy_raw"][axis]) > half + tolerance:
                        self.column_axis_rejected.append(
                            {"column_id": ident, "column_name": column["name"],
                             "floor_id": column["floor_id"], "beam_id": beam["object_id"],
                             "beam_name": beam["name"], "axis": "xy"[axis],
                             "candidate_raw": value}
                        )
                        continue
                    candidates[ident][axis].append(value)

        direct = {}
        for ident, axes in candidates.items():
            direct[ident] = []
            for values in axes:
                if values and max(values) - min(values) <= tolerance:
                    direct[ident].append(statistics.median(values))
                else:
                    direct[ident].append(None)

        for ident, column in by_id.items():
            center, methods = [], []
            for axis in (0, 1):
                value = direct[ident][axis]
                method = "beam_faces"
                if value is None:
                    others = [
                        direct[other_id][axis]
                        for other_id, other in by_id.items()
                        if other["name"] == column["name"]
                        and direct[other_id][axis] is not None
                    ]
                    if others and max(others) - min(others) <= tolerance:
                        candidate = statistics.median(others)
                        if abs(candidate - column["xy_raw"][axis]) <= half_extents[ident][axis] + tolerance:
                            value, method = candidate, "other_floors"
                if value is None:
                    value, method = column["xy_raw"][axis], "insertion_fallback"
                center.append(value)
                methods.append(method)
            self.column_axes[ident] = (center[0], center[1])
            self.column_axis_evidence.append(
                {"object_id": ident, "name": column["name"], "floor_id": column["floor_id"],
                 "insertion_xy_raw": list(column["xy_raw"]), "axis_xy_raw": center,
                 "coordinate_sources": methods,
                 "beam_face_candidates_raw": candidates[ident]}
            )

    def _column_axis_xy(self, column):
        center = self.column_axes.get(column["object_id"], column["xy_raw"])
        return tuple(value * self.length for value in center)

    def _member(self, name, start, end, dimensions, floor, kind, record, *, foundation_bar=False):
        source_label = name
        pair = frozenset((start, end))
        if start == end or pair in self.member_pairs:
            raise ProjectImportError(
                f"Membro degenerado ou coincidente: {source_label}."
            )
        if len(dimensions) != 2:
            raise ProjectImportError(f"Seção de {source_label} não reconhecida.")
        b, h = (
            self._number(value, "Seção") * self.length * 1000 for value in dimensions
        )
        if not all(math.isfinite(value) and value > 0 for value in (b, h)):
            raise ProjectImportError(f"Seção sem dimensões positivas: {source_label}.")
        # O PRJ grava a rotação dos pilares em radianos. O modelo OSA usa
        # graus em torno do eixo longitudinal da barra. Trechos de viga não têm
        # esse campo por elemento; a rotação fixa da definição de seção não é
        # a rotação da viga no pórtico.
        rotation = 0.0
        if kind == "column":
            rotation = math.degrees(
                self._number(record.get("rotation_candidate_rad", 0.0), "Rotação")
            )
        material, values = self._material(floor, kind, record)
        if foundation_bar and self.next_foundation_member_index is not None:
            name = f"B{self.next_foundation_member_index}"
            self.next_foundation_member_index += 1
        else:
            name = f"B{self.next_member_index}"
            self.next_member_index += 1
        section = self.sections_by_id.get(record.get("section_id"))
        section_needs_review = (
            kind == "beam"
            and self.data.get("internal_version_code") == 3075
            and section is not None
            and _beam_section_candidate_3075(section)
        )
        if section_needs_review:
            self.section_review.append({
                "member_name": name,
                "beam_name": record["name"],
                "floor_id": floor["floor_id"],
                "section_values_raw": list(section["geometric_values_raw"]),
                "rectangular_candidate_mm": [b, h],
            })
        self.members.append(
            {
                "name": name,
                "start_node": start,
                "end_node": end,
                "material": material,
                "material_values": values,
                "section": "Retangular",
                "profile": f"{b:g} × {h:g} mm",
                "section_geometry": [["b", b], ["h", h]],
                "rotation": rotation,
                "releases": [False] * 12,
                "rotation_flexibility_percent": [0] * 6,
                "color": "#2996b5" if kind == "beam" else "#547a94",
            }
        )
        self.member_pairs.add(pair)
        self.member_sources[name] = {
            "object_id": record["object_id"],
            "floor_id": floor["floor_id"],
            "original_name": record["name"],
            "source_group_name": record.get("beam_name") if kind == "beam" else None,
            "source_label": source_label,
            "kind": kind,
            "foundation_bar": foundation_bar,
            "referenced_by_beam": record.get("referenced_by_beam", False),
            "segment_id": record.get("segment_id"),
            "beam_object_id": record.get("beam_object_id"),
            "section_requires_review": section_needs_review,
            "material_override": record.get("material_override"),
            "rotation_source_rad": record.get("rotation_candidate_rad")
            if kind == "column"
            else None,
        }

    def _material(self, floor, kind, record):
        override = record.get("material_override") if kind == "beam" else None
        if override:
            if override.get("type") != "Madeira":
                raise ProjectImportError(
                    f"Material individual {override.get('type')!r} da viga não mapeado."
                )
            from osa.data import CatalogLoader

            reference = next(
                item for item in CatalogLoader().materials()
                if item["name"] == "Madeira Estrutural"
            )
            name = f"Madeira para revisão ({override['class_name']})"
            values = [
                reference["elastic_modulus_kn_m2"], reference["shear_modulus_kn_m2"],
                reference["poisson_ratio"], reference["unit_weight_kn_m3"],
            ]
            self.materials[name] = {"type": "Madeira", "values": values}
            warning = (
                "Vigas de madeira usam propriedades de referência do OSA; "
                "os valores nativos foram preservados no relatório e precisam ser revisados."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)
            return name, values
        config = "CfgPavViga" if kind == "beam" else "CfgPavPilar"
        source_name = floor.get("material_defaults", {}).get(config)
        concrete = next(
            (c for c in self.data.get("concretes", ()) if c["name"] == source_name),
            None,
        )
        if not self.options.import_material_properties:
            name = "Concreto para revisão"
            values = [30000000.0, 12500000.0, 0.2, 23.53596]
        else:
            if concrete is None:
                raise ProjectImportError(
                    f"Material de {floor['name']} não identificado. Desative a leitura de propriedades para usar o concreto de referência do OSA."
                )
            name = f"Concreto {source_name}"
            e = (
                self._number(concrete["elastic_modulus_raw"], "Módulo")
                * self.force
                / self.length**2
            )
            weight = (
                self._number(concrete["specific_weight_raw"], "Peso específico")
                * self.force
                / self.length**3
            )
            nu = self.options.poisson_ratio
            if (
                not math.isfinite(e)
                or not math.isfinite(weight)
                or e <= 0
                or weight < 0
            ):
                raise ProjectImportError("Propriedades do material não são válidas.")
            values = [e, e / (2 * (1 + nu)), nu, weight]
        self.materials[name] = {"type": "Concreto", "values": values}
        return name, values

    def _link(self, start, end):
        if start == end:
            return
        pair = frozenset((start, end))
        if any(frozenset((v["start_node"], v["end_node"])) == pair for v in self.rigid):
            return
        self.rigid.append(
            {"name": f"{start}-{end}", "start_node": start, "end_node": end}
        )

    def build(self):
        floors = self.data["floors"]
        by_floor = {f["floor_id"]: f for f in floors}
        elevations = {}
        for index, floor in enumerate(floors):
            height = (
                self._number(floor["height_raw"], "Altura do pavimento") * self.length
            )
            if height < 0 or (height == 0 and index > 0):
                raise ProjectImportError(
                    "Alturas nulas/negativas não são suportadas nesta importação."
                )
            elevations[floor["floor_id"]] = (
                self.options.first_floor_elevation_m
                if index == 0
                else elevations[floors[index - 1]["floor_id"]] + height
            )
        active = _active_columns(self.data)
        lookup = {(c["floor_id"], c["name"]): c for c in active}
        if len(lookup) != len(active):
            raise ProjectImportError(
                "Pilares de identidade ambígua no mesmo pavimento."
            )
        if self.data.get("internal_version_code") == 3219:
            # As barras já importadas conservam seus nomes; os novos pilares
            # de fundação são numerados depois das vigas e pilares existentes.
            regular_columns = sum(
                column.get("class_name") != "ElPilarFundacao"
                and (floors[index - 1]["floor_id"], column["name"]) in lookup
                for index, floor in enumerate(floors) if index > 0
                for column in active if column["floor_id"] == floor["floor_id"]
            )
            self.next_foundation_member_index = regular_columns + len(self.data["beams"]) + 1
        self._resolve_column_axes(active)
        unresolved = sum(
            "insertion_fallback" in entry["coordinate_sources"]
            for entry in self.column_axis_evidence
        )
        if self.data.get("internal_version_code") in _COLUMN_AXIS_LAYOUT_CODES:
            self.warnings.append(
                "Eixos de pilares foram estimados a partir das faces das vigas e "
                "da continuidade entre pavimentos. "
                f"{unresolved} pilar(es) conservam a inserção em alguma coordenada sem evidência suficiente."
            )
            if self.column_axis_rejected:
                self.warnings.append(
                    f"{len(self.column_axis_rejected)} extremidade(s) de viga divergem "
                    "das faces esperadas dos pilares; confira os detalhes de geometria no relatório."
                )
        for column in active:
            floor = by_floor.get(column.get("floor_id"))
            if floor is None:
                raise ProjectImportError("Pilar sem pavimento resolvido.")
            x, y = self._column_axis_xy(column)
            z = elevations[floor["floor_id"]]
            self.anchor_nodes[column["object_id"]] = self._node(
                (x, y, z), f"{self._floor_name(floor)}_{column['name']}"
            )
        for point in self.data.get("points", ()):
            if point.get("referenced_by_beam"):
                floor = by_floor[point["floor_id"]]
                x, y = (value * self.length for value in point["xy_raw"])
                self.anchor_nodes[point["object_id"]] = self._node(
                    (x, y, elevations[point["floor_id"]]),
                    f"{self._floor_name(floor)}_{point['name']}",
                )
        for index, floor in enumerate(floors):
            for column in (c for c in active if c["floor_id"] == floor["floor_id"]):
                end = self.anchor_nodes[column["object_id"]]
                foundation_bar = column.get("class_name") == "ElPilarFundacao" or index == 0
                if foundation_bar:
                    if not self.options.include_lower_columns:
                        self.omitted_lower_columns += 1
                        self.omitted_column_details.append({
                            "name": column["name"], "floor_id": floor["floor_id"],
                            "reason": "prolongamento inferior desativado na importação",
                        })
                        continue
                    foundation = column.get("foundation_raw") or {}
                    if foundation.get("kind") == "pile_cap" and foundation.get("height_reference") == "floor_to_foundation_bar_bottom":
                        height_raw = foundation.get("bar_height_raw")
                    elif foundation.get("kind") == "pad_footing" and foundation.get("depth_reference") == "baldrame_top_to_footing_bottom":
                        height_raw = foundation.get("settlement_depth_raw")
                    else:
                        self.omitted_lower_columns += 1
                        self.omitted_column_details.append({
                            "name": column["name"], "floor_id": floor["floor_id"],
                            "reason": "cota inferior não mapeada",
                        })
                        continue
                    depth = (
                        self._number(height_raw, "Altura do pilar de fundação")
                        * self.length
                    )
                    if depth <= 0:
                        raise ProjectImportError(
                            "A altura do pilar de fundação deve ser positiva."
                        )
                    x, y = self._column_axis_xy(column)
                    support_z = elevations[floor["floor_id"]] - depth
                    start = self._node(
                        (x, y, support_z),
                        f"Base_{column['name']}",
                    )
                    candidate = {
                            "node_name": start,
                            "column_name": column["name"],
                            "source_object_id": column["object_id"],
                            "floor_id": floor["floor_id"],
                            "foundation_kind": foundation["kind"],
                            "baldrame_top_elevation_m": elevations[floor["floor_id"]],
                            "bar_height_m": depth,
                            "elevation_m": support_z,
                            "mapping_status": "pending_support_calibration",
                            "source_flags_raw": foundation.get("six_flags_raw", []),
                            "source_values_raw": foundation.get("six_values_raw", []),
                            "height_corroboration": foundation.get("height_corroboration"),
                    }
                    if foundation["kind"] == "pad_footing":
                        candidate["settlement_depth_m"] = depth
                    self.support_candidates.append(candidate)
                else:
                    previous = lookup.get(
                        (floors[index - 1]["floor_id"], column["name"])
                    )
                    if previous is None:
                        self.omitted_column_segments += 1
                        self.omitted_column_details.append({
                            "name": column["name"], "floor_id": floor["floor_id"],
                            "reason": "continuidade no pavimento anterior não identificada",
                        })
                        continue
                    start = self.anchor_nodes[previous["object_id"]]
                self._member(
                    f"{self._floor_name(floor)}_{column['name']}",
                    start,
                    end,
                    column["rectangular_dimensions_candidate_raw"],
                    floor,
                    "column",
                    column,
                    foundation_bar=foundation_bar,
                )
        for beam in self.data["beams"]:
            floor = by_floor.get(beam.get("floor_id"))
            if floor is None:
                raise ProjectImportError("Viga sem pavimento resolvido.")
            label = f"{self._floor_name(floor)}_{beam['name']}"
            try:
                start = self.anchor_nodes[beam["support_i_id"]]
                end = self.anchor_nodes[beam["support_j_id"]]
            except KeyError as error:
                raise ProjectImportError(
                    "Referência de pilar/ponto da viga não resolvida."
                ) from error
            if self.options.preserve_end_offsets:
                z = elevations[floor["floor_id"]]
                si = self._node(
                    (*[value * self.length for value in beam["xy_i_raw"]], z),
                    label + "_A",
                )
                sj = self._node(
                    (*[value * self.length for value in beam["xy_j_raw"]], z),
                    label + "_B",
                )
                self._link(start, si)
                self._link(end, sj)
                start, end = si, sj
            self._member(
                label,
                start,
                end,
                beam["rectangular_dimensions_candidate_raw"],
                floor,
                "beam",
                beam,
            )
        incident_counts = {}
        for item in (*self.members, *self.rigid):
            for node in (item["start_node"], item["end_node"]):
                incident_counts[node] = incident_counts.get(node, 0) + 1
        isolated_foundations = [
            {
                "member_name": member["name"],
                "column_name": self.member_sources[member["name"]]["original_name"],
                "floor_id": self.member_sources[member["name"]]["floor_id"],
                "source_object_id": self.member_sources[member["name"]]["object_id"],
            }
            for member in self.members
            if self.member_sources[member["name"]].get("foundation_bar")
            and incident_counts[member["start_node"]] == 1
            and incident_counts[member["end_node"]] == 1
        ]
        if isolated_foundations:
            self.warnings.append(
                f"{len(isolated_foundations)} pilar(es) de fundação foram importados "
                "sem ligação identificada com outras barras; confira os pilares isolados no resumo."
            )
        if self.options.preserve_end_offsets:
            self.warnings.append(
                "Deslocamentos de extremidade foram representados por ligações rígidas do OSA. A equivalência analítica com o modelo original ainda deve ser verificada."
            )
        else:
            self.warnings.append(
                "Vigas foram ligadas diretamente às inserções dos pilares/pontos; os deslocamentos de extremidade não foram aplicados."
            )
        if self.omitted_lower_columns:
            self.warnings.append(
                f"{self.omitted_lower_columns} prolongamento(s) inferior(es) de pilar foram "
                + (
                    "omitidos porque a geometria/cota inferior da fundação ainda não foi mapeada."
                    if self.options.include_lower_columns
                    else "omitidos pela opção selecionada na importação."
                )
            )
        if self.omitted_column_segments:
            self.warnings.append(
                f"{self.omitted_column_segments} trecho(s) de pilar sem continuidade "
                "identificada no pavimento anterior foram omitidos."
            )
        if self.section_review:
            self.warnings.append(
                f"{len(self.section_review)} trecho(s) de viga têm dados adicionais de seção "
                "não mapeados e usam uma seção retangular candidata; confira o resumo."
            )
        self.warnings.append(
            "Materiais de concreto usam configurações de pavimento, sem mapear outras sobreposições por elemento. O coeficiente de Poisson é informado nesta importação."
            if self.options.import_material_properties
            else "Os membros usam o concreto de referência do OSA; propriedades nativas não foram aplicadas."
        )
        source = self.data["source"]
        evidence = {
            key: self.data.get(key, [])
            for key in (
                "columns",
                "beams",
                "beam_groups",
                "points",
                "walls",
                "actions",
                "concretes",
                "floors",
                "sections",
                "active_action_keys",
                "slabs",
            )
        }
        plate_transfer = prepare_plate_transfer(
            self.data.get("slabs", ()), elevations, self.length
        )
        for plate in plate_transfer["records"]:
            plate["status"] = "excluded_by_import_scope"
        boundary_members = {}
        for name, source_record in self.member_sources.items():
            for ident in {
                source_record["object_id"],
                source_record.get("segment_id"),
                source_record.get("beam_object_id"),
            } - {None}:
                boundary_members.setdefault(ident, []).append(name)
        for plate in plate_transfer["records"]:
            plate["boundary_members"] = [
                {
                    "source_object_id": ident,
                    "member_names": boundary_members.get(ident, []),
                    "member_name": boundary_members[ident][0]
                    if len(boundary_members.get(ident, ())) == 1
                    else None,
                }
                for ident in plate["boundary_element_ids"]
            ]
        if plate_transfer["records"]:
            self.warnings.insert(
                0,
                f"{len(plate_transfer['records'])} registro(s) de laje não importado(s); "
                "esta importação inclui somente vigas e pilares.",
            )
        inventory = {
            item["class_name"]: item["count"]
            for item in self.data.get("inventory", ())
        }
        excluded_records = [
            {"class_name": name, "count": count}
            for name, count in sorted(inventory.items())
            if count
            and name not in _IMPORTED_LAUNCH_CLASSES
            and name not in _LAUNCH_METADATA_CLASSES
        ]
        active_column_ids = {
            column["object_id"] for column in _active_columns(self.data)
        }
        excluded_element_counts = {
            "sapatas": sum(
                (column.get("foundation_raw") or {}).get("kind") == "pad_footing"
                for column in self.data.get("columns", ())
                if column.get("class_name") == "ElPilarFundacao"
            ) + inventory.get("Sapata", 0) + inventory.get("ElementoSapata", 0),
            "blocos": sum(
                (column.get("foundation_raw") or {}).get("kind") == "pile_cap"
                for column in self.data.get("columns", ())
                if column.get("class_name") == "ElPilarFundacao"
            ),
            "lajes": sum(
                count
                for name, count in inventory.items()
                if is_slab_element_class(name)
            ),
            "paredes": inventory.get("Parede", 0),
            "escadas": sum(
                inventory.get(name, 0)
                for name in ("Escada", "TRampa", "ElementoEscada", "TElementoRampa")
            ),
            "pontos_sem_referencia": sum(
                not point.get("referenced_by_beam")
                for point in self.data.get("points", ())
            ),
            "pilares_sem_referencia": sum(
                column.get("class_name") == "ElementoPilar"
                and not column.get("referenced_by_beam")
                and column.get("region_role") == "base_cad"
                and column.get("object_id") not in active_column_ids
                for column in self.data.get("columns", ())
            ),
            "pilares_fundacao_sem_referencia": sum(
                column.get("class_name") == "ElPilarFundacao"
                and not column.get("referenced_by_beam")
                and (not self.options.include_lower_columns or not _importable_column(column))
                for column in self.data.get("columns", ())
            ),
            "trechos_sem_vinculo": max(
                0, inventory.get("ElementoTrecho", 0) - len(self.data.get("beams", ()))
            ),
            "trechos_nulos": sum(
                beam.get("null_segment_slots", 0)
                for beam in self.data.get("beam_groups", ())
            ),
            "outros_elementos": sum(
                item["count"]
                for item in excluded_records
                if item["class_name"].startswith(("Elemento", "TElemento"))
                and item["class_name"]
                not in {
                    "ElementoNo",
                    "ElementoEscada",
                    "TElementoRampa",
                }
                and not is_slab_element_class(item["class_name"])
            ),
        }
        report = {
            "schema": "osa-import/v1",
            "importer": "prj",
            "importer_version": "0.5",
            "source": source,
            "internal_version_code": self.data.get("internal_version_code"),
            "compatibility": {
                "layout": self.data.get("launch_layout", "prj-native-launch-v1"),
                "reference_internal_code": _REFERENCE_CODE,
                "mode": "reference_code"
                if self.data.get("internal_version_code") == _REFERENCE_CODE
                else "structural_probe",
                "status": "matched_known_layout",
            },
            "decode_warnings": list(self.data.get("decode_errors", ())),
            "imported_at": datetime.now(UTC).isoformat(),
            "options": asdict(self.options),
            "requires_review": True,
            "counts": {
                "nodes": len(self.nodes),
                "members": len(self.members),
                "beams": len(self.data["beams"]),
                "beam_groups": len(self.data.get("beam_groups", self.data["beams"])),
                "beam_segments": len(self.data["beams"]),
                "intermediate_points": sum(
                    point.get("referenced_by_beam", False)
                    for point in self.data.get("points", ())
                ),
                "columns": len(self.members) - len(self.data["beams"]),
                "foundation_columns": sum(
                    source.get("foundation_bar", False)
                    for source in self.member_sources.values()
                ),
                "foundation_columns_without_beams": sum(
                    source.get("foundation_bar", False)
                    and not source.get("referenced_by_beam", False)
                    for source in self.member_sources.values()
                ),
                "isolated_foundation_columns": len(isolated_foundations),
                "rotated_columns": sum(
                    member["rotation"] % 360 != 0
                    and self.member_sources[member["name"]]["kind"] == "column"
                    for member in self.members
                ),
                "rigid_links": len(self.rigid),
                "applied_loads": 0,
                "support_candidates": len(self.support_candidates),
                "pending_plates": 0,
                "excluded_elements": excluded_element_counts,
                "excluded_lower_column_segments": self.omitted_lower_columns,
                "excluded_column_segments": self.omitted_column_segments,
                "preserved_wall_records": len(evidence["walls"]),
            },
            "geometry_mapping": {
                "column_axis": "beam faces, matching floors, or insertion fallback",
                "beam_endpoints": "native EL_Linha endpoints",
                "beam_to_support": "rigid links from corrected column axis to native beam endpoints",
                "column_axes": self.column_axis_evidence,
                "unmatched_beam_endpoints": self.column_axis_rejected,
                "section_review": self.section_review,
                "omitted_columns": self.omitted_column_details,
            },
            "floor_elevations_m": [
                {"id": f["floor_id"], "name": f["name"], "z": elevations[f["floor_id"]]}
                for f in floors
            ],
            "warnings": self.warnings,
            "member_sources": self.member_sources,
            "node_sources": self.node_sources,
            "support_candidates": self.support_candidates,
            "isolated_foundation_columns": isolated_foundations,
            "plate_transfer": plate_transfer,
            "excluded_records": excluded_records,
            "source_evidence": evidence,
            "omitted": {
                "combinations": len(self.data.get("combinations", ())),
                "cad_column_representations": len(self.data["columns"]) - len(active),
            },
        }
        result = {
            "format": "open-structural-analysis/v2",
            "nodes": self.nodes,
            "members": sorted(self.members, key=lambda member: int(member["name"][1:])),
            "rigid_bars": self.rigid,
            "materials": self.materials,
            "included_sections": {
                "Concreto": ["Retangular"],
                **({"Madeira": ["Retangular"]} if any(
                    item["type"] == "Madeira" for item in self.materials.values()
                ) else {}),
            },
            "actions": [],
            "action_groups": [],
            "load_cases": [],
            "load_combinations": [],
            "results": [],
            "import_metadata": report,
        }
        return ImportResult(result, report)
