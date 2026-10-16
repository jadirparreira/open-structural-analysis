"""Transcrição experimental do lançamento PRJ (perfil interno 3419) para OSA.

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


class EberickImporter:
    name = "Eberick"
    extensions = (".prj", ".prj.zip")

    def read(self, path: str | Path, options: ImportOptions) -> ImportResult:
        options.validate()
        try:
            raw, source = load_stream(path)
            reader = Reader(raw, source)
            if reader.version != 3419:
                raise ProjectImportError(
                    f"O PRJ usa o código interno {reader.version}. Esta primeira "
                    "integração suporta o lançamento do perfil 3419. O arquivo "
                    "original não foi alterado."
                )
            data = extract(reader)
        except (LayoutError, struct.error, zipfile.BadZipFile) as error:
            raise ProjectImportError(
                f"Não foi possível interpretar o PRJ: {error}"
            ) from error
        return self.convert(data, options)

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
        if data.get("internal_version_code") != 3419:
            raise ProjectImportError("Perfil de lançamento não suportado.")
        if data.get("decode_errors"):
            first = data["decode_errors"][0]
            raise ProjectImportError(
                f"O lançamento contém um layout não suportado: {first['class_name']} "
                f"em {first['offset_hex']}. Nenhum modelo foi substituído."
            )
        if not data.get("beams") or not data.get("floors"):
            raise ProjectImportError(
                "Não foram recuperados pavimentos e vigas para importar."
            )
        inventory = {
            item["class_name"]: item["count"] for item in data.get("inventory", ())
        }
        if inventory.get("ElementoViga", 0) != len(data["beams"]):
            raise ProjectImportError(
                "Nem todas as vigas foram lidas; importação cancelada."
            )
        unsupported = ("Laje", "ElementoLaje", "Escada", "TRampa", "ElementoEscada")
        present = [name for name in unsupported if inventory.get(name, 0)]
        if present:
            raise ProjectImportError(
                "O lançamento contém elementos ainda não suportados: "
                + ", ".join(present)
            )
        floors = {f["floor_id"] for f in data["floors"]}
        if len(floors) != len(data["floors"]):
            raise ProjectImportError("IDs de pavimento repetidos não são suportados.")
        for sketch in data.get("croquis", ()):
            count = sum(b.get("floor_id") == sketch["floor_id"] for b in data["beams"])
            if sketch["floor_id"] not in floors or count != sketch["beam_count"]:
                raise ProjectImportError(
                    "A contagem de vigas/pavimentos do croqui não confere."
                )
        active = [
            column
            for column in data.get("columns", ())
            if column.get("referenced_by_beam")
        ]
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
        self.column_nodes: dict[int, str] = {}
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

    @staticmethod
    def _number(value, label):
        result = float(value)
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
            if height < 0 or (
                height == 0 and (index > 0 or self.options.include_lower_columns)
            ):
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
            self.column_nodes[column["object_id"]] = self._node(
                (x, y, z), f"{self._floor_name(floor)}_{column['name']}"
            )
        for index, floor in enumerate(floors):
            for column in (c for c in active if c["floor_id"] == floor["floor_id"]):
                end = self.column_nodes[column["object_id"]]
                if index == 0:
                    if not self.options.include_lower_columns:
                        continue
                    if not column.get("foundation_raw"):
                        raise ProjectImportError(
                            "Trecho inferior sem fundação reconhecida; desative essa opção para importar somente os pavimentos."
                        )
                    x, y = (value * self.length for value in column["xy_raw"])
                    start = self._node(
                        (
                            x,
                            y,
                            elevations[floor["floor_id"]]
                            - floor["height_raw"] * self.length,
                        ),
                        f"Base_{column['name']}",
                    )
                else:
                    previous = lookup.get(
                        (floors[index - 1]["floor_id"], column["name"])
                    )
                    if previous is None:
                        raise ProjectImportError(
                            f"Continuidade de {column['name']} não identificada; importação cancelada."
                        )
                    start = self.column_nodes[previous["object_id"]]
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
                start = self.column_nodes[beam["support_i_id"]]
                end = self.column_nodes[beam["support_j_id"]]
            except KeyError as error:
                raise ProjectImportError(
                    "Referência de pilar da viga não resolvida."
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
                "Vigas foram ligadas diretamente às inserções dos pilares; os deslocamentos de extremidade não foram aplicados."
            )
        if self.options.include_lower_columns:
            self.warnings.append(
                "A altura do primeiro pavimento foi usada para o trecho inferior dos pilares. A cota de apoio é uma hipótese geométrica a conferir."
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
                "walls",
                "actions",
                "concretes",
                "floors",
                "sections",
                "active_action_keys",
            )
        }
        report = {
            "schema": "osa-import/v1",
            "importer": "eberick",
            "importer_version": "0.1",
            "source": source,
            "internal_version_code": 3419,
            "imported_at": datetime.now(UTC).isoformat(),
            "options": asdict(self.options),
            "requires_review": True,
            "counts": {
                "nodes": len(self.nodes),
                "members": len(self.members),
                "beams": len(self.data["beams"]),
                "columns": len(self.members) - len(self.data["beams"]),
                "rigid_links": len(self.rigid),
                "applied_loads": 0,
                "preserved_wall_records": len(evidence["walls"]),
            },
            "floor_elevations_m": [
                {"id": f["floor_id"], "name": f["name"], "z": elevations[f["floor_id"]]}
                for f in floors
            ],
            "warnings": self.warnings,
            "member_sources": self.member_sources,
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
