"""Column axes inferred from the geometry around the support, in PRJ units."""

import math
import os

import pytest

from osa.transcriptions import ImportOptions
from osa.transcriptions.prj import PrjImporter, _LaunchBuilder


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


def test_3575_uses_beam_faces_with_small_transverse_slope():
    pillars = [
        {**column(1, "P20", 1, (165.5, 1162.43), math.pi),
         "rectangular_dimensions_candidate_raw": [14, 30]},
        {**column(2, "P23", 1, (469.53, 1176.38), 3 * math.pi / 2),
         "rectangular_dimensions_candidate_raw": [14, 30]},
    ]
    beams = [
        beam(1, (179.5, 1169.43), (439.53, 1169.38), 1, 2),
        beam(2, (172.5, 1192.43), (172.5, 1427.43), support_i=1),
        beam(3, (462.53, 891.38), (462.53, 1162.38), support_j=2),
    ]
    builder = _LaunchBuilder({"internal_version_code": 3575, "beams": beams}, ImportOptions(), 0.01, 1)
    builder._resolve_column_axes(pillars)
    assert builder.column_axes[1] == pytest.approx((172.5, 1177.43))
    assert builder.column_axes[2] == pytest.approx((454.53, 1169.38))


def test_3575_does_not_treat_a_sloping_beam_as_axis_aligned():
    pillar = column(1, "P1", 1, (100, 100))
    beams = [beam(1, (109.5, 100), (369.5, 100.2), support_i=1)]
    builder = _LaunchBuilder({"internal_version_code": 3575, "beams": beams}, ImportOptions(), 0.01, 1)
    builder._resolve_column_axes([pillar])
    assert builder.column_axes[1] == pytest.approx((100, 100))
    assert builder.column_axis_evidence[0]["coordinate_sources"] == [
        "insertion_fallback", "insertion_fallback"
    ]


def test_3075_insertion_at_column_face_and_eccentric_beam():
    pillars = [
        {**column(1, "P1", 1, (179.71, 2054.7)),
         "rectangular_dimensions_candidate_raw": [19, 60]},
        {**column(2, "P10", 1, (160.71, 1157.7)),
         "rectangular_dimensions_candidate_raw": [19, 60]},
        {**column(3, "P10", 5, (160.71, 1157.7)),
         "rectangular_dimensions_candidate_raw": [19, 50]},
    ]
    beams = [
        beam(1, (179.71, 2054.7), (185.21, 2054.7), support_i=1),
        beam(2, (170.21, 1794.7), (170.21, 2024.7), support_j=1),
        beam(3, (179.71, 1187.7), (185.21, 1187.7), support_i=2),
        beam(4, (170.21, 1217.7), (170.21, 1467.2), support_i=2),
        beam(5, (179.71, 1200.7), (302.75, 1200.7), support_i=3),
        beam(6, (170.21, 987.24), (170.21, 1157.7), support_j=3),
    ]
    builder = _LaunchBuilder({"internal_version_code": 3075, "beams": beams}, ImportOptions(), 0.01, 1)
    builder._resolve_column_axes(pillars)
    assert builder.column_axes[1] == pytest.approx((170.21, 2054.7))
    assert builder.column_axes[2] == pytest.approx((170.21, 1187.7))
    assert builder.column_axes[3] == pytest.approx((170.21, 1182.7))
    assert beams[4]["xy_i_raw"] == [179.71, 1200.7]
