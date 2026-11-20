"""Physical-model provenance for externally computed elastic buckling inputs."""
import json
from dataclasses import asdict
from hashlib import sha256

CRITICAL_PROPERTIES = frozenset({"KL1", "KL2", "KLt", "ForkSupports", "NcrG", "NcrL", "NcrD", "McrGy", "McrLy", "McrDy", "McrGz", "McrLz", "McrDz"})


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return 0.0 if value == 0 else float(value)
    return value


def stability_signature(model):
    """Exclude view/name/design-override changes, include analysis conditions."""
    member_fields = ("name", "start_node", "end_node", "material", "section", "section_geometry",
                     "section_mirrored", "rotation", "releases", "rotation_flexibility_percent")
    node_fields = ("name", "x", "y", "z", "supports", "support_stiffness")
    plate_fields = ("name", "contour", "supports", "thickness_mm", "material")
    materials_in_use = {item.material for collection in (model.bars, model.plates) for item in collection.values()}
    groups_in_use = {item.action_group or model.selected_action_group for item in model.load_combinations.values()}
    state = {
        "analysis_options": (model.second_order_analysis, model.ultimate_stiffness_factor),
        "schema": "elastic-stability-physical-v1",
        "nodes": {name: {key: getattr(value, key) for key in node_fields} for name, value in model.nodes.items()},
        "bars": {name: {key: getattr(value, key) for key in member_fields} for name, value in model.bars.items()},
        "plates": {name: {key: getattr(value, key) for key in plate_fields} for name, value in model.plates.items()},
        "rigid_bars": {name: asdict(value) for name, value in model.rigid_bars.items()},
        "materials": {name: model.materials.get(name) for name in sorted(materials_in_use)},
        "actions": {name: asdict(value) for name, value in model.actions.items()},
        "load_combinations": {name: asdict(value) for name, value in model.load_combinations.items()},
        "action_groups": {name: asdict(model.action_groups[name]) if name in model.action_groups else None
                          for name in sorted(groups_in_use)},
    }
    if model.warping_analysis:
        state['warping_analysis'] = True
    for name, member in state["bars"].items():
        member["section_geometry"] = dict(member["section_geometry"])
        if model.bars[name].warping_restraints != (None, None):
            member['warping_restraints'] = model.bars[name].warping_restraints
    return sha256(json.dumps(_canonical(state), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
