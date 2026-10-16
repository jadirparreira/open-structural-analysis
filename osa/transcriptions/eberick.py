"""Transcrição experimental do lançamento PRJ por compatibilidade de layout.

Não utiliza executáveis, DLLs ou bibliotecas do Eberick. Os vínculos e as
cargas ainda não calibrados ficam no relatório, sem serem apresentados como
cargas/apoios analíticos recuperados.
"""

from __future__ import annotations

import math
import re
import struct
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .contracts import ImportOptions, ImportResult, ProjectImportError
from .eberick_reader import LayoutError, Reader, extract, load_stream
from .eberick_reader.slabs import is_slab_element_class
from .plates import prepare_plate_transfer

_REFERENCE_CODE = 3419
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
    }
)


class EberickImporter:
    name = "Eberick"
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
        force = {"N": 0.001, "kN": 1.0, "kgf": 0.00980665, "tf": 9.80665}[
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
            if declared != len(data["beams"]) or inventory.get(
                "ElementoTrecho", 0
            ) != len(data["beams"]):
                raise ProjectImportError(
                    "A contagem dos trechos de viga não confere com o lançamento."
                )
            segment_ids = [beam["segment_id"] for beam in data["beams"]]
            if len(set(segment_ids)) != len(segment_ids):
                raise ProjectImportError(
                    "Um trecho de viga foi associado a mais de uma posição do lançamento."
                )
        unsupported = ("Escada", "TRampa", "ElementoEscada")
        present = [name for name in unsupported if inventory.get(name, 0)]
        if present:
            raise ProjectImportError(
                "O lançamento contém elementos ainda não suportados: "
                + ", ".join(present)
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
        active = [
            column
            for column in data.get("columns", ())
            if column.get("referenced_by_beam")
        ]
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
            if column.get("referenced_by_beam"):
                continue
            duplicate = any(
                other.get("floor_id") == column.get("floor_id")
                and other["name"] == column["name"]
                and other["xy_raw"] == column["xy_raw"]
                and other["rectangular_dimensions_candidate_raw"]
                == column["rectangular_dimensions_candidate_raw"]
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
                if not rectangular:
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
        self.member_pairs: set[frozenset[str]] = set()
        self.names: set[str] = set()
        self.materials: dict[str, dict] = {}
        self.member_sources: dict[str, dict] = {}
        self.anchor_nodes: dict[int, str] = {}
        self.support_candidates: list[dict] = []
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
            (
                "Pontos de inserção foram usados como referência dos pilares; centros de "
                "seção, eixos locais e rotações das seções ainda exigem revisão."
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
            return self.coordinates[key]
        name = preferred
        index = 2
        existing = {node["name"] for node in self.nodes}
        while name in existing:
            name = f"{preferred}_{index}"
            index += 1
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
        return name

    @staticmethod
    def _floor_name(floor):
        clean = re.sub(r"\s+", "_", str(floor["name"]).strip())
        return clean or str(floor["floor_id"])

    def _member(self, name, start, end, dimensions, floor, kind, record):
        pair = frozenset((start, end))
        if start == end or pair in self.member_pairs or name in self.names:
            raise ProjectImportError(f"Membro degenerado ou coincidente: {name}.")
        if len(dimensions) != 2:
            raise ProjectImportError(f"Seção de {name} não reconhecida.")
        b, h = (
            self._number(value, "Seção") * self.length * 1000 for value in dimensions
        )
        if not all(math.isfinite(value) and value > 0 for value in (b, h)):
            raise ProjectImportError(f"Seção sem dimensões positivas: {name}.")
        material, values = self._material(floor, kind)
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
                "rotation": 0,
                "releases": [False] * 12,
                "rotation_flexibility_percent": [0] * 6,
                "color": "#2996b5" if kind == "beam" else "#547a94",
            }
        )
        self.member_pairs.add(pair)
        self.names.add(name)
        self.member_sources[name] = {
            "object_id": record["object_id"],
            "floor_id": floor["floor_id"],
            "original_name": record["name"],
            "kind": kind,
            "segment_id": record.get("segment_id"),
            "beam_object_id": record.get("beam_object_id"),
        }

    def _material(self, floor, kind):
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
            name = f"Eberick {source_name}"
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
        active = [c for c in self.data["columns"] if c.get("referenced_by_beam")]
        lookup = {(c["floor_id"], c["name"]): c for c in active}
        if len(lookup) != len(active):
            raise ProjectImportError(
                "Pilares de identidade ambígua no mesmo pavimento."
            )
        for column in active:
            floor = by_floor.get(column.get("floor_id"))
            if floor is None:
                raise ProjectImportError("Pilar sem pavimento resolvido.")
            x, y = (value * self.length for value in column["xy_raw"])
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
                if index == 0:
                    if not self.options.include_lower_columns:
                        continue
                    foundation = column.get("foundation_raw") or {}
                    if (
                        foundation.get("kind") != "pad_footing"
                        or foundation.get("depth_reference")
                        != "baldrame_top_to_footing_bottom"
                    ):
                        raise ProjectImportError(
                            "Trecho inferior sem profundidade de sapata reconhecida; "
                            "blocos e outros tipos ainda não foram mapeados. Desative "
                            "essa opção para importar somente os pavimentos."
                        )
                    depth = (
                        self._number(
                            foundation.get("settlement_depth_raw"),
                            "Profundidade de assentamento",
                        )
                        * self.length
                    )
                    if depth <= 0:
                        raise ProjectImportError(
                            "A profundidade de assentamento da sapata deve ser positiva."
                        )
                    x, y = (value * self.length for value in column["xy_raw"])
                    support_z = elevations[floor["floor_id"]] - depth
                    start = self._node(
                        (x, y, support_z),
                        f"Base_{column['name']}",
                    )
                    self.support_candidates.append(
                        {
                            "node_name": start,
                            "column_name": column["name"],
                            "source_object_id": column["object_id"],
                            "floor_id": floor["floor_id"],
                            "foundation_kind": "pad_footing",
                            "baldrame_top_elevation_m": elevations[floor["floor_id"]],
                            "settlement_depth_m": depth,
                            "elevation_m": support_z,
                            "mapping_status": "pending_support_calibration",
                            "source_flags_raw": foundation.get("six_flags_raw", []),
                            "source_values_raw": foundation.get("six_values_raw", []),
                        }
                    )
                else:
                    previous = lookup.get(
                        (floors[index - 1]["floor_id"], column["name"])
                    )
                    if previous is None:
                        raise ProjectImportError(
                            f"Continuidade de {column['name']} não identificada; importação cancelada."
                        )
                    start = self.anchor_nodes[previous["object_id"]]
                self._member(
                    f"{self._floor_name(floor)}_{column['name']}",
                    start,
                    end,
                    column["rectangular_dimensions_candidate_raw"],
                    floor,
                    "column",
                    column,
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
        if self.options.preserve_end_offsets:
            self.warnings.append(
                "Deslocamentos de extremidade foram representados por ligações rígidas do OSA. A equivalência analítica com o Eberick ainda deve ser verificada."
            )
        else:
            self.warnings.append(
                "Vigas foram ligadas diretamente às inserções dos pilares/pontos; os deslocamentos de extremidade não foram aplicados."
            )
        if self.options.include_lower_columns:
            self.warnings.append(
                "As bases dos pilares de sapata usam a profundidade individual de assentamento "
                "lida do PRJ. A cota do primeiro pavimento é a referência de topo do baldrame; "
                "desníveis precisam ser conferidos. Os tipos de vínculo permanecem pendentes de calibração."
            )
        self.warnings.append(
            "Materiais usam configurações de pavimento, sem mapear sobreposições por elemento. O coeficiente de Poisson é informado nesta importação."
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
                f"{len(plate_transfer['records'])} registro(s) de laje preservado(s) para a futura "
                "integração com elementos de placa. As lajes ainda não participam do modelo "
                "de cálculo e não geram ações. O processamento permanece pendente dessa integração.",
            )
        report = {
            "schema": "osa-import/v1",
            "importer": "eberick",
            "importer_version": "0.5",
            "source": source,
            "internal_version_code": self.data.get("internal_version_code"),
            "compatibility": {
                "layout": self.data.get("launch_layout", "eberick-native-launch-v1"),
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
                "rigid_links": len(self.rigid),
                "applied_loads": 0,
                "support_candidates": len(self.support_candidates),
                "pending_plates": len(plate_transfer["records"]),
                "preserved_wall_records": len(evidence["walls"]),
            },
            "floor_elevations_m": [
                {"id": f["floor_id"], "name": f["name"], "z": elevations[f["floor_id"]]}
                for f in floors
            ],
            "warnings": self.warnings,
            "member_sources": self.member_sources,
            "support_candidates": self.support_candidates,
            "plate_transfer": plate_transfer,
            "source_evidence": evidence,
            "omitted": {
                "combinations": len(self.data.get("combinations", ())),
                "cad_column_representations": len(self.data["columns"]) - len(active),
            },
        }
        result = {
            "format": "open-structural-analysis/v2",
            "nodes": self.nodes,
            "members": self.members,
            "rigid_bars": self.rigid,
            "materials": self.materials,
            "included_sections": {"Concreto": ["Retangular"]},
            "actions": [],
            "action_groups": [],
            "load_cases": [],
            "load_combinations": [],
            "results": [],
            "import_metadata": report,
        }
        return ImportResult(result, report)
