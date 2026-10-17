"""Conversão entre o agregado de domínio e o formato de projeto."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from itertools import product
from math import floor, isfinite
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
from osa.domain.errors import DuplicateNodeCoordinatesError

FORMAT_V1 = "open-structural-analysis/v1"
FORMAT_V2 = "open-structural-analysis/v2"


def _coordinate_cell(coordinates: tuple[float, ...], width: float) -> tuple[int, ...]:
    cells = []
    for value in coordinates:
        scaled = value / width
        if isfinite(scaled):
            cells.append(floor(scaled))
        else:
            # Preserve support for finite coordinates near the float range.
            numerator, denominator = value.as_integer_ratio()
            width_numerator, width_denominator = width.as_integer_ratio()
            cells.append((numerator * width_denominator) // (denominator * width_numerator))
    return tuple(cells)


class ProjectSerializer:
    @staticmethod
    def _material_values(values: Any) -> tuple[float, float, float, float]:
        """Normaliza materiais legados (GPa e kg/m³) para kN/m² e kN/m³."""
        elastic_modulus, shear_modulus, poisson_ratio, unit_weight = (
            float(value) for value in values
        )
        if elastic_modulus < 1e5 and shear_modulus < 1e5 and unit_weight > 100.0:
            return (
                elastic_modulus * 1e6,
                shear_modulus * 1e6,
                poisson_ratio,
                unit_weight * 9.80665e-3,
            )
        return elastic_modulus, shear_modulus, poisson_ratio, unit_weight

    def dump(self, model: StructuralModel, thumbnail: str | None = None) -> dict[str, Any]:
        data = {
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
            "scene_views": [
                {"name": name, "hidden_members": sorted(hidden)}
                for name, hidden in model.scene_views.items()
            ],
            "active_scene_view": model.active_scene_view,
        }
        if thumbnail:
            data["thumbnail"] = {"format": "png", "data": thumbnail}
        return data

    @staticmethod
    def thumbnail_from(data: dict[str, Any]) -> str | None:
        value = data.get("thumbnail")
        if not isinstance(value, dict) or value.get("format") != "png":
            return None
        thumbnail = value.get("data")
        return thumbnail if isinstance(thumbnail, str) else None

    def load_into(
        self, model: StructuralModel, data: dict[str, Any],
        *, yield_control: Callable[[], None] | None = None,
        consume: bool = False,
    ) -> None:
        file_format = data.get("format")
        if file_format not in (FORMAT_V1, FORMAT_V2):
            raise ValueError("Arquivo de modelo não reconhecido.")
        if consume and "members" in data:
            data.pop("bars", None)

        candidate = type(model)()
        # Only nearby spatial cells can contain a duplicate. The previous
        # all-pairs scan made opening a model quadratic in its node count.
        tolerance = candidate.coordinate_tolerance
        cell_width = tolerance * 2.0
        neighbors = tuple(product((-1, 0, 1), repeat=3))
        coordinate_cells: dict[tuple[int, ...], dict[str, tuple[float, ...]]] = {}
        for index, item in enumerate(data.get("nodes", [])):
            if yield_control is not None and index % 128 == 0:
                yield_control()
            coordinates = candidate._coordinates(item["x"], item["y"], item["z"])
            node = Node(
                item["name"], *coordinates,
                tuple(bool(value) for value in item.get("supports", (False,) * 6)),
                tuple(float(value) for value in item.get("support_stiffness", (0.0,) * 6)),
            )
            cell = _coordinate_cell(coordinates, cell_width)
            for delta in neighbors:
                nearby = tuple(value + offset for value, offset in zip(cell, delta))
                if any(
                    all(abs(a - b) <= tolerance for a, b in zip(coordinates, other))
                    for other in coordinate_cells.get(nearby, {}).values()
                ):
                    raise DuplicateNodeCoordinatesError("Já existe um nó nessa coordenada.")
            previous = candidate.nodes.get(node.name)
            if previous is not None:
                old_cell = _coordinate_cell((previous.x, previous.y, previous.z), cell_width)
                coordinate_cells[old_cell].pop(node.name)
            coordinate_cells.setdefault(cell, {})[node.name] = coordinates
            candidate.nodes[node.name] = node
            if consume:
                data["nodes"][index] = None

        members = data.get("members", data.get("bars", []))
        member_pairs: set[frozenset[str]] = set()
        for index, item in enumerate(members):
            if yield_control is not None and index % 128 == 0:
                yield_control()
            candidate._validate_member_nodes(
                item["start_node"], item["end_node"], existing_pairs=member_pairs,
            )
            geometry = item.get("section_geometry", ())
            if isinstance(geometry, dict):
                geometry = tuple(geometry.items())
            releases = candidate._member_releases(
                tuple(bool(value) for value in item.get("releases", (False,) * 12))
            )
            raw_rotation_percent = item.get("rotation_flexibility_percent")
            if raw_rotation_percent is None:
                rotation_percent = (0,) * 6
            else:
                rotation_percent = candidate._member_rotation_flexibility_percent(
                    tuple(0 if int(value) >= 100 else int(value) for value in raw_rotation_percent)
                )
            member = Bar(
                item["name"], item["start_node"], item["end_node"],
                item.get("material", "Indefinido"),
                self._material_values(item.get("material_values", (200000000.0, 76900000.0, 0.30, 76.9822025))),
                item.get("section", ""), item.get("profile", ""),
                tuple((str(key), float(value)) for key, value in geometry),
                rotation=candidate._member_rotation(item.get("rotation", 0)),
                releases=releases,
                color=candidate._member_color(item.get("color", "#6e7781")),
                solid_face_offsets=candidate._member_solid_face_offsets(
                    tuple(float(value) for value in item.get("solid_face_offsets", (0.0, 0.0)))
                ),
                solid_section_offsets=candidate._member_solid_section_offsets(
                    tuple(float(value) for value in item.get("solid_section_offsets", (0.0, 0.0)))
                ),
                section_mirrored=bool(item.get("section_mirrored", False)),
                rotation_flexibility_percent=rotation_percent,
            )
            previous = candidate.bars.get(member.name)
            if previous is not None:
                member_pairs.remove(frozenset((previous.start_node, previous.end_node)))
            member_pairs.add(frozenset((member.start_node, member.end_node)))
            candidate.bars[member.name] = member
            if consume:
                members[index] = None

        rigid_pairs: set[frozenset[str]] = set()
        for item in data.get("rigid_bars", ()):
            candidate._validate_rigid_bar_nodes(
                item["start_node"], item["end_node"], existing_pairs=rigid_pairs,
            )
            rigid = RigidBar(item["name"], item["start_node"], item["end_node"])
            if rigid.name != f"{rigid.start_node}-{rigid.end_node}":
                raise ValueError("A identidade da barra rígida deve indicar seus nós.")
            rigid_pairs.add(frozenset((rigid.start_node, rigid.end_node)))
            candidate.rigid_bars[rigid.name] = rigid

        candidate.set_reference_axes({
            direction: tuple(
                ReferenceAxis(str(axis["label"]), float(axis["value"]))
                for axis in data.get("axes", {}).get(direction, ())
            )
            for direction in ("X", "Y", "Z")
        })

        if file_format == FORMAT_V2:
            raw_views = data.get("scene_views", [])
            if not isinstance(raw_views, list):
                raise ValueError("As vistas da cena são inválidas.")
            for item in raw_views:
                if not isinstance(item, dict):
                    raise ValueError("As vistas da cena são inválidas.")  # noqa: TRY004
                name = item.get("name")
                hidden = item.get("hidden_members", ())
                if not isinstance(name, str) or not name.strip() or not isinstance(hidden, list):
                    raise ValueError("As vistas da cena são inválidas.")
                if name == "Completo":
                    if hidden:
                        raise ValueError("A vista Completo não pode ocultar membros.")
                    continue
                if name in candidate.scene_views or any(
                    not isinstance(member, str) or member not in candidate.bars for member in hidden
                ):
                    raise ValueError("As vistas da cena são inválidas.")
                candidate.scene_views[name] = set(hidden)
            active_view = data.get("active_scene_view", "Completo")
            if active_view not in candidate.scene_views:
                raise ValueError("A vista ativa é inválida.")
            candidate.active_scene_view = active_view
            materials = data.get("materials", {})
            if materials:
                candidate.materials = {
                    name: self._material_values(item["values"])
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
            candidate.remove_orphaned_actions()
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
                    item.get("node_results", {}) if consume else dict(item.get("node_results", {})),
                    item.get("member_results", {}) if consume else dict(item.get("member_results", {})),
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
        model.scene_views = candidate.scene_views
        model.active_scene_view = candidate.active_scene_view
        model.view_revision += 1
        model.revision += 1
