"""Conversão entre o agregado de domínio e o formato de projeto."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from osa.domain import (
    Action,
    ActionDefinition,
    ActionGroup,
    AnalysisResult,
    Bar,
    LoadCase,
    LoadCombination,
    Node,
    ReferenceAxis,
    RigidBar,
    StructuralModel,
)

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
            "rigid_bars": [asdict(rigid) for rigid in model.rigid_bars.values()],
            "axes": {direction: [asdict(axis) for axis in axes] for direction, axes in model.axes.items()},
            "materials": {
                name: {"type": model.material_types.get(name, ""), "values": list(values)}
                for name, values in model.materials.items()
            },
            "included_sections": model.sections,
            "actions": [asdict(item) for item in model.actions.values()],
            "action_groups": [asdict(item) for item in model.action_groups.values()],
            "action_group_aliases": model.action_group_aliases,
            "selected_action_group": model.selected_action_group,
            "load_cases": [asdict(item) for item in model.load_cases.values()],
            "load_combinations": [asdict(item) for item in model.load_combinations.values()],
            "combination_groups_initialized": sorted(model.combination_groups_initialized),
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
                candidate._member_rotation(item.get("rotation", 0)),
                candidate._member_releases(tuple(bool(value) for value in item.get("releases", (False,) * 12))),
                candidate._member_color(item.get("color", "#6e7781")),
                candidate._member_solid_face_offsets(
                    tuple(float(value) for value in item.get("solid_face_offsets", (0.0, 0.0)))
                ),
            )
            candidate.bars[member.name] = member

        for item in data.get("rigid_bars", ()):
            candidate._validate_rigid_bar_nodes(item["start_node"], item["end_node"])
            rigid = RigidBar(item["name"], item["start_node"], item["end_node"])
            if rigid.name != f"{rigid.start_node}-{rigid.end_node}":
                raise ValueError("A identidade da barra rígida deve indicar seus nós.")
            candidate.rigid_bars[rigid.name] = rigid

        candidate.set_reference_axes({
            direction: tuple(
                ReferenceAxis(str(axis["label"]), float(axis["value"]))
                for axis in data.get("axes", {}).get(direction, ())
            )
            for direction in ("X", "Y", "Z")
        })

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
            candidate.action_groups = {
                item["name"]: ActionGroup(
                    item["name"], tuple(
                        ActionDefinition(action["name"], action["abbreviation"])
                        for action in item.get("actions", ())
                    ),
                )
                for item in data.get("action_groups", ())
            }
            candidate.action_group_aliases = {
                str(template): str(group)
                for template, group in data.get("action_group_aliases", {}).items()
            }
            candidate.selected_action_group = str(data.get("selected_action_group", "PP+AP+AV"))
            candidate.load_cases = {
                item["name"]: LoadCase(item["name"], tuple(item.get("actions", ())))
                for item in data.get("load_cases", ())
            }
            candidate.load_combinations = {
                item["name"]: LoadCombination(
                    item["name"],
                    tuple((str(name), float(factor)) for name, factor in item.get("factors", ())),
                    tuple((str(name), float(factor)) for name, factor in item.get("factors_2", ())),
                    tuple((str(name), float(factor)) for name, factor in item.get("factors_3", ())),
                    None if item.get("active_actions") is None else tuple(
                        str(action) for action in item["active_actions"]
                    ),
                    None if item.get("action_group") is None else str(item["action_group"]),
                    str(item.get("limit_state", "CAR")),
                )
                for item in data.get("load_combinations", ())
            }
            candidate.combination_groups_initialized = {
                str(group) for group in data.get("combination_groups_initialized", ())
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
        model.rigid_bars = candidate.rigid_bars
        model.axes = candidate.axes
        model.materials = candidate.materials
        model.material_types = candidate.material_types
        model.sections = candidate.sections
        model.actions = candidate.actions
        model.action_groups = candidate.action_groups
        model.action_group_aliases = candidate.action_group_aliases
        model.selected_action_group = candidate.selected_action_group
        model.load_cases = candidate.load_cases
        model.load_combinations = candidate.load_combinations
        model.combination_groups_initialized = candidate.combination_groups_initialized
        model.analysis_results = candidate.analysis_results
        model.revision += 1
