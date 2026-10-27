"""Helpers for treating collinear grouped bars as one detailing element."""

from __future__ import annotations

import numpy as np


def group_endpoint_faces(model, member_names: tuple[str, ...] | list[str]):
    """Map logical group ends A/B to the member face that forms each outer end.

    For an ungrouped single member, A/B are its start/end faces. For a grouped
    chain, the physical terminal nodes are ordered along the first member's
    local direction, so reversed member directions are handled per face.
    Returns an empty mapping for branched or incomplete groups.
    """
    names = tuple(dict.fromkeys(name for name in member_names if name in model.bars))
    if not names:
        return {}
    if len(names) == 1:
        member = model.bars[names[0]]
        return {"A": (member.name, 0), "B": (member.name, 1)}

    members = [model.bars[name] for name in names]
    node_members: dict[str, list[str]] = {}
    for member in members:
        node_members.setdefault(member.start_node, []).append(member.name)
        node_members.setdefault(member.end_node, []).append(member.name)
    terminal_nodes = [node for node, attached in node_members.items() if len(attached) == 1]
    if len(terminal_nodes) != 2:
        return {}

    reference = members[0]
    start = model.nodes.get(reference.start_node)
    end = model.nodes.get(reference.end_node)
    if start is None or end is None:
        return {}
    origin = np.asarray((start.x, start.y, start.z), dtype=float)
    direction = np.asarray((end.x - start.x, end.y - start.y, end.z - start.z), dtype=float)
    length = float(np.linalg.norm(direction))
    if length <= 1e-12:
        return {}
    direction /= length
    terminal_nodes.sort(key=lambda node_name: float(np.dot(
        np.asarray((model.nodes[node_name].x, model.nodes[node_name].y, model.nodes[node_name].z)) - origin,
        direction,
    )))

    result = {}
    for logical_end, node_name in zip(("A", "B"), terminal_nodes):
        member_name = node_members[node_name][0]
        member = model.bars[member_name]
        if member.start_node == node_name:
            result[logical_end] = (member_name, 0)
        elif member.end_node == node_name:
            result[logical_end] = (member_name, 1)
    return result if len(result) == 2 else {}
