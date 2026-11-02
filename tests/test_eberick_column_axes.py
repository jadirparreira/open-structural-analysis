"""Column axes inferred from the geometry around the support, in PRJ units."""

import math

import pytest

from osa.transcriptions import ImportOptions
from osa.transcriptions.eberick import _LaunchBuilder


def column(ident, name, floor, xy, rotation=0):
    return {
        "object_id": ident,
        "name": name,
        "floor_id": floor,
        "xy_raw": list(xy),
        "rotation_candidate_rad": rotation,
        "rectangular_dimensions_candidate_raw": [19.0, 40.0],
    }


def beam(ident, start, end, support_i=-1, support_j=-1):
    return {
        "object_id": ident,
        "name": f"V{ident}",
        "xy_i_raw": list(start),
        "xy_j_raw": list(end),
        "support_i_id": support_i,
        "support_j_id": support_j,
    }


def test_opposite_beam_faces_locate_rotated_and_centered_columns():
    # The first support is inserted at a face; the second is already centered.
    pillars = [
        column(1, "P36", 2, (120.5, 1850), 3 * math.pi / 2),
        column(2, "P29", 2, (372.5, 107.5)),
    ]
    beams = [
        beam(1, (10, 1850), (120.5, 1850), support_j=1),
        beam(2, (160.5, 1850), (285, 1850), support_i=1),
        beam(3, (70, 107.5), (363, 107.5), support_j=2),
        beam(4, (382, 107.5), (617.96, 107.5), support_i=2),
    ]
    builder = _LaunchBuilder({"internal_version_code": 3219, "beams": beams}, ImportOptions(), 0.01, 1)
    builder._resolve_column_axes(pillars)
    assert builder.column_axes[1] == pytest.approx((140.5, 1850))
    assert builder.column_axes[2] == pytest.approx((372.5, 107.5))


def test_axis_uses_other_floor_and_records_incompatible_beam_endpoint():
    pillars = [
        column(1, "P17", 1, (379.5, 769.5), math.pi / 2),
        column(2, "P17", 2, (379.5, 769.5), math.pi / 2),
    ]
    beams = [
        beam(1, (339.5, 760), (100, 760), support_i=1),
        beam(2, (372.5, 519.5), (372.5, 674.5), support_j=1),
        beam(3, (372.5, 769.5), (372.5, 1000), support_i=1),
    ]
    builder = _LaunchBuilder({"internal_version_code": 3219, "beams": beams}, ImportOptions(), 0.01, 1)
    builder._resolve_column_axes(pillars)
    assert builder.column_axes[1] == pytest.approx((359.5, 760))
    assert builder.column_axes[2] == pytest.approx((359.5, 760))
    assert builder.column_axis_evidence[1]["coordinate_sources"] == ["other_floors", "other_floors"]
    assert [item["beam_name"] for item in builder.column_axis_rejected] == ["V2"]
