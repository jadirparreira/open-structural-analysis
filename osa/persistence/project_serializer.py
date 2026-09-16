"""Conversão entre o agregado de domínio e o formato de projeto."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from osa.domain import Action, AnalysisResult, Bar, LoadCase, LoadCombination, Node, StructuralModel

FORMAT_V1 = "open-structural-analysis/v1"
FORMAT_V2 = "open-structural-analysis/v2"


class ProjectSerializer:
    def dump(self, model: StructuralModel) -> dict[str, Any]:
        return {
            "format": FORMAT_V2,
            "nodes": [asdict(node) for node in model.nodes.values()],
            "members": [asdict(member) for member in model.bars.values()],
            # "bars" mantém interoperabilidade com leitores antigos.
            "bars": [asdict(member) for member in model.bars.values()],
            "materials": {
                name: {"type": model.material_types.get(name, ""), "values": list(values)}
                for name, values in model.materials.items()
            },
            "included_sections": model.sections,
            "actions": [asdict(item) for item in model.actions.values()],
            "load_cases": [asdict(item) for item in model.load_cases.values()],
            "load_combinations": [asdict(item) for item in model.load_combinations.values()],
            "results": [asdict(item) for item in model.analysis_results],
        }

    def load_into(self, model: StructuralModel, data: dict[str, Any]) -> None:
        file_format = data.get("format")
        if file_format not in (FORMAT_V1, FORMAT_V2):
            raise ValueError("Arquivo de modelo não reconhecido.")

        candidate = type(model)()
        for item in data.get("nodes", []):
            node = Node(
                item["name"], float(item["x"]), float(item["y"]), float(item["z"]),
                tuple(bool(value) for value in item.get("supports", (False,) * 6)),
            )
            candidate._ensure_unique_coordinates((node.x, node.y, node.z))
            candidate.nodes[node.name] = node

        members = data.get("members", data.get("bars", []))
        for item in members:
            candidate._validate_member_nodes(item["start_node"], item["end_node"])
            geometry = item.get("section_geometry", ())
            if isinstance(geometry, dict):
                geometry = tuple(geometry.items())
            member = Bar(
                item["name"], item["start_node"], item["end_node"],
                item.get("material", "Indefinido"),
                tuple(float(value) for value in item.get("material_values", (200.0, 76.9, 0.30, 7850.0))),
                item.get("section", ""), item.get("profile", ""),
                tuple((str(key), float(value)) for key, value in geometry),
            )
            candidate.bars[member.name] = member

        if file_format == FORMAT_V2:
            materials = data.get("materials", {})
            if materials:
                candidate.materials = {
                    name: tuple(float(value) for value in item["values"])
                    for name, item in materials.items()
                }
                candidate.material_types = {name: item.get("type", "") for name, item in materials.items()}
            candidate.sections = {
                str(kind): [str(section) for section in sections]
                for kind, sections in data.get("included_sections", candidate.sections).items()
            }
            candidate.actions = {
                item["name"]: Action(
                    item["name"], item["kind"], item["target"],
                    tuple(float(value) for value in item.get("components", ())), item["load_case"],
                )
                for item in data.get("actions", ())
            }
            candidate.load_cases = {
                item["name"]: LoadCase(item["name"], tuple(item.get("actions", ())))
                for item in data.get("load_cases", ())
            }
            candidate.load_combinations = {
                item["name"]: LoadCombination(
                    item["name"], tuple((str(name), float(factor)) for name, factor in item.get("factors", ()))
                )
                for item in data.get("load_combinations", ())
            }
            candidate.analysis_results = [
                AnalysisResult(
                    int(item["model_revision"]), item["load_reference"],
                    dict(item.get("node_results", {})), dict(item.get("member_results", {})),
                )
                for item in data.get("results", ())
            ]

        model.nodes = candidate.nodes
        model.bars = candidate.bars
        model.materials = candidate.materials
        model.material_types = candidate.material_types
        model.sections = candidate.sections
        model.actions = candidate.actions
        model.load_cases = candidate.load_cases
        model.load_combinations = candidate.load_combinations
        model.analysis_results = candidate.analysis_results
        model.revision += 1
