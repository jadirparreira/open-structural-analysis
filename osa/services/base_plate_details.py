"""Automatic, model-linked annotations for base/top plate detail views."""
from __future__ import annotations

import math
import textwrap

from osa.domain.node_components import base_plate_anchor_offsets
from .component_accessories import base_plate_fastener_name


COMPONENT_IDENTIFIER_KINDS = {"component_plate", "component_fastener"}


def component_identifier(model, kind, node_name):
    node = model.nodes.get(node_name)
    assignment = node.component if node is not None else None
    if assignment is None or assignment.component_id not in {"base_plate", "stair_plate"}:
        return "", 0
    parameters = dict(assignment.parameters)
    if kind == "component_fastener":
        if assignment.component_id != "base_plate":
            return "", 0
        return base_plate_fastener_name(parameters), len(base_plate_anchor_offsets(parameters))
    return "CH " + f'{float(parameters.get("espessura_mm", 6.3 if assignment.component_id == "stair_plate" else 20)):g}'.replace(".", ","), 0


def minimum_connected_thickness(model, node_name):
    """Apply the user's drafting rule; all dimensions here are in millimetres."""
    thicknesses = []
    for member in model.bars.values():
        if node_name not in (member.start_node, member.end_node):
            continue
        geometry = member.geometry_dict()
        values = [geometry[key] for key in ("t", "tw", "tf", "espessura") if key in geometry]
        if not values and member.section in {"Barra Circular", "Barra Redonda"}:
            values = [geometry.get("d", 0)]
        if not values and member.section in {"Barra Quadrada", "Quadrada", "Barra Retangular", "Retangular"}:
            values = [geometry.get(key, 0) for key in ("b", "h")]
        thicknesses.extend(float(value) for value in values if math.isfinite(float(value)) and float(value) > 0)
    return min(thicknesses, default=0.0)


def identifier_lines(identity, quantity=0):
    paragraphs = identity.splitlines() or [identity]
    if quantity:
        # Keep the quantity with the last word, instead of an isolated line.
        paragraphs[-1] += f"\u00a0({quantity}X)"
    return [line.replace("\u00a0", " ") for paragraph in paragraphs
            for line in (textwrap.wrap(paragraph, width=29, break_on_hyphens=False) or [""])]


def update_component_identifier(model, identification):
    identity, quantity = component_identifier(model, identification["kind"], identification["element"])
    identification.setdefault("show_identity", True)
    identification.setdefault("show_name", False)
    identification.setdefault("show_section", False)
    lines = identifier_lines(identity, quantity)
    width = max((len(line) for line in lines), default=0) * float(identification.get("auto_text_height_mm", 3.)) * .6
    if ("width_mm" not in identification and "auto_label_center" in identification
            and tuple(identification.get("projected_point", ())) == tuple(identification["auto_label_center"])):
        factor = float(identification.get("auto_label_scale", 10.)) / 1000
        position = (identification["auto_label_left_x"] + width/2*factor,
                    identification["projected_point"][1])
        identification["projected_point"] = identification["auto_label_center"] = position
    identification["unwrapped_text"] = identity + (f" ({quantity}X)" if quantity else "")
    identification["auto_label_width_mm"] = width
    identification.update(text="\n".join(lines), text_lines=lines,
                          text_runs=[[{"text": line, "role": "element"}] for line in lines])


def _bounds(points):
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _geometry_from_view(view):
    plate, anchors, members = [], [], []
    for segment, owner in zip(view.get("segments", ()), view.get("segment_owners", ())):
        if owner == "componente:chapa_base:0":
            plate.extend(segment)
        elif owner.startswith("componente:chapa_base:"):
            anchors.extend(segment)
        else:
            members.extend(segment)
    all_points = [p for segment in view.get("segments", ()) for p in segment]
    if not all_points:
        return None
    plate_bounds = _bounds(plate or all_points)
    cx, cy = (plate_bounds[0]+plate_bounds[2])/2, (plate_bounds[1]+plate_bounds[3])/2
    candidates = sorted(members, key=lambda p: math.hypot(p[0]-cx, p[1]-cy))[:16]
    return dict(plate_bounds=plate_bounds, body_bounds=_bounds(all_points),
                weld_points=candidates, anchor_points=anchors)


def add_base_plate_annotations(model, view, text_height_mm=3.):
    group = view.get("component_detail_group", {})
    nodes = group.get("members", ())
    if not nodes or nodes[0] not in model.nodes:
        return False
    node = nodes[0]
    geometry = view.get("component_annotation_geometry") or _geometry_from_view(view)
    if geometry is None:
        return False
    plate = geometry["plate_bounds"]
    body = geometry["body_bounds"]
    factor = max(1.0, float(view.get("scale_denominator", 10))) / 1000  # m per paper mm
    right = max(body[2], plate[2]) + 6 * factor
    top = max(body[3], plate[3])
    cy = (plate[1] + plate[3]) / 2
    # The bottom/left dimension chains stay clear of this right-hand callout column.
    positions = {"component_fastener": (right, top + 2*factor),
                 "component_plate": (right, min(plate[1] + 2*factor, cy - 8*factor))}
    elevation = group.get("direction") not in {"Superior", "Inferior"}
    if elevation:
        positions = {"component_fastener": (right, cy + 11*factor),
                     "component_plate": (right, cy)}
    for kind, position in positions.items():
        identification = dict(kind=kind, element=node, projected_point=position,
                              auto_component_role=kind, show_identity=True, show_name=False,
                              show_section=False, visibility_customized=True,
                              auto_text_height_mm=text_height_mm)
        update_component_identifier(model, identification)
        center = (position[0] + identification["auto_label_width_mm"]/2*factor, position[1])
        identification.update(projected_point=center, auto_label_center=center,
                              auto_label_left_x=position[0], auto_label_scale=float(view.get("scale_denominator", 10)))
        view.setdefault("identifications", []).append(identification)
    targets = geometry.get("weld_points", ())
    if targets:
        # Prefer the visible right edge of the bar at the plate connection.
        target = max(targets, key=lambda p: p[0] - abs(p[1]-cy)*.35)
        reference_y = cy + 23*factor if elevation else max(cy, positions["component_plate"][1] + 8*factor)
        size = minimum_connected_thickness(model, node)
        view.setdefault("weld_marks", []).append(dict(
            kind="fillet", side="arrow", size=size, length=0., pitch=0., root=0., angle=0.,
            contour="none", all_around=True, field=False, tail="", direction="right",
            point=tuple(target), offset_mm=((right-target[0])/factor, (target[1]-reference_y)/factor),
            auto_component_role="base_plate_weld", source_node=node, auto_size_mm=size,
        ))
    view["base_plate_auto_annotations_version"] = 2
    return True


def ensure_base_plate_annotations(model, views, text_height_mm=3.):
    """Migrate each group once and update automatic sizes without duplicating labels."""
    changed = False
    groups = {}
    for view in views:
        group = view.get("component_detail_group", {})
        if group.get("component_id") == "base_plate":
            groups.setdefault(group.get("id", ""), []).append(view)
    for members in groups.values():
        for view in members:
            version = view.get("base_plate_auto_annotations_version", 0)
            if not version:
                changed |= add_base_plate_annotations(model, view, text_height_mm)
            elif version < 2:
                # Keep existing annotations and manual edits when upgrading a group.
                view["base_plate_auto_annotations_version"] = 2
                changed = True
            if version < 2 and view["component_detail_group"].get("direction") not in {"Superior", "Inferior"}:
                geometry = view.get("component_annotation_geometry") or _geometry_from_view(view)
                if geometry:
                    factor = float(view.get("scale_denominator", 10)) / 1000
                    for dimension in view.get("dimensions", ()):
                        if dimension.get("orthogonal_axis") == "y" and dimension.get("offset", (0, 0))[0] > 0:
                            left = geometry["body_bounds"][0] - 8*factor
                            dimension["offset"] = (left-dimension["start"][0], 0.)
                            changed = True
            for mark in view.get("weld_marks", ()):
                if mark.get("auto_component_role") != "base_plate_weld":
                    continue
                # Preserve an explicit size edited by the user in the weld inspector.
                if mark.get("size") == mark.get("auto_size_mm"):
                    size = minimum_connected_thickness(model, mark["source_node"])
                    changed |= size != mark["size"]
                    mark["size"] = mark["auto_size_mm"] = size
    return changed


def arrange_base_plate_views(views, available_width_mm=340, available_height_mm=277,
                             reserved_top_mm=0., reserved_bottom_mm=80.):
    """Pack new detail views with room for dimensions and model identifiers."""
    if not views:
        return
    extents = []
    for view in views:
        geometry = view.get("component_annotation_geometry") or _geometry_from_view(view)
        if geometry is None:
            return
        x0,y0,x1,y1 = geometry["body_bounds"]
        cx,cy = (x0+x1)/2,(y0+y1)/2
        factor = 1000 / float(view.get("scale_denominator", 10))
        left, right = (x0-cx)*factor-5, (x1-cx)*factor+5
        top, bottom = (cy-y1)*factor-6, (cy-y0)*factor+12
        for dimension in view.get("dimensions", ()):
            start, end = dimension["start"], dimension["end"]
            dx, dy = dimension.get("offset", (0., 0.))
            left = min(left, (min(start[0],end[0])+min(0,dx)-cx)*factor-5)
            right = max(right, (max(start[0],end[0])+max(0,dx)-cx)*factor+5)
            bottom = max(bottom, (cy-min(start[1],end[1])-min(0,dy))*factor+12)
            top = min(top, (cy-max(start[1],end[1])-max(0,dy))*factor-6)
        for identification in view.get("identifications", ()):
            x,y = identification.get("projected_point", (cx,cy))
            lines = identification.get("text_lines", ())
            right = max(right, (x-cx)*factor + identification.get("auto_label_width_mm", max((len(line) for line in lines), default=0)*1.8)/2 + 4)
            top = min(top, (cy-y)*factor-4)
            bottom = max(bottom, (cy-y)*factor+len(lines)*4)
        if view.get("weld_marks"):
            right = max(right, (x1-cx)*factor + 30)
        extents.append((left,top,right,bottom))
    rows, current, width = [], [], 0.
    for i, bounds in enumerate(extents):
        size = bounds[2]-bounds[0]
        if current and width + size + 10 > available_width_mm:
            rows.append(current); current=[]; width=0.
        current.append(i); width += size + (10 if width else 0)
    if current:
        rows.append(current)
    row_heights = [max(extents[i][3]-extents[i][1] for i in row) for row in rows]
    total_height = sum(row_heights) + 8*(len(rows)-1)
    center_y = min(available_height_mm*.53,
                   available_height_mm-reserved_bottom_mm-total_height/2-10)
    center_y = max(reserved_top_mm+total_height/2+16, center_y)
    y = -total_height/2
    for row, height in zip(rows, row_heights):
        total = sum(extents[i][2]-extents[i][0] for i in row) + 10*(len(row)-1)
        x = -total/2
        for i in row:
            left, top, right, bottom = extents[i]
            views[i]["component_detail_group"]["paper_offset_mm"] = (x-left, y-top)
            x += right-left+10
        y += height+8
    for view in views:
        group = view["component_detail_group"]
        group["group_position"] = (.5, center_y/available_height_mm)
        group["label_position"] = (.5, (center_y-total_height/2-11)/available_height_mm)
