import numpy as np
import pytest

from osa.rendering.solid_member_renderer import SolidMemberRenderer
from osa.sections.geometry import section_shape


@pytest.mark.parametrize(
    ("family", "geometry"),
    (
        ("W Laminado", {"d": 200, "bf": 100, "tw": 6, "tf": 8}),
        ("T Laminado", {"d": 100, "bf": 100, "tw": 6, "tf": 8}),
        ("C Formado", {"d": 100, "bf": 50, "c": 10, "t": 2}),
        ("Tubular Circular", {"D": 100, "t": 3}),
        ("Retangular Vazado", {"b": 200, "h": 400, "t": 40}),
        ("Tipo L", {"b": 200, "h": 400, "t": 40}),
    ),
)
def test_section_shape_supports_solid_and_hollow_families(family, geometry):
    shape = section_shape(family, geometry)

    assert shape is not None
    assert all(len(loop) >= 3 for loop in shape.loops)
    assert shape.bounds[0] < shape.bounds[1]
    assert shape.bounds[2] < shape.bounds[3]


def test_section_shape_centers_hollow_section_at_its_composite_centroid():
    shape = section_shape("Tubular Circular", {"D": 100, "t": 3})

    assert shape is not None
    assert len(shape.loops) == 2
    assert shape.centroid == pytest.approx((0.0, 0.0), abs=1e-10)


@pytest.mark.parametrize(
    ("family", "geometry"),
    (
        ("Tubular Quadrado", {"b": 100, "t": 3}),
        ("Tubular Retangular", {"b": 120, "h": 80, "t": 3}),
    ),
)
def test_rectangular_tubes_keep_rounded_outer_and_inner_corners(family, geometry):
    shape = section_shape(family, geometry)

    assert shape is not None
    assert len(shape.loops) == 2
    assert len(shape.loops[0]) > 4
    assert len(shape.loops[1]) > 4
    assert not any(abs(abs(y) - max(abs(point[0]) for point in shape.loops[0])) < 1e-9
                   and abs(abs(z) - max(abs(point[1]) for point in shape.loops[0])) < 1e-9
                   for y, z in shape.loops[0])


def test_rectangular_tube_caps_keep_the_inner_opening():
    shape = section_shape("Tubular Quadrado", {"b": 100, "t": 3})
    assert shape is not None
    mesh = SolidMemberRenderer()._mesh_for(shape)

    faces = mesh.faces
    offset = 0
    center_covering_caps = 0
    while offset < len(faces):
        count = int(faces[offset])
        ids = faces[offset + 1:offset + 1 + count]
        points = mesh.points[ids]
        if count == 3 and np.allclose(points[:, 0], 0.0):
            first, second, third = points[:, 1:]
            denominator = (
                (second[1] - third[1]) * (first[0] - third[0])
                + (third[0] - second[0]) * (first[1] - third[1])
            )
            barycentric = (
                ((second[1] - third[1]) * -third[0] + (third[0] - second[0]) * -third[1])
                / denominator,
                ((third[1] - first[1]) * -third[0] + (first[0] - third[0]) * -third[1])
                / denominator,
            )
            if barycentric[0] >= 0 and barycentric[1] >= 0 and sum(barycentric) <= 1:
                center_covering_caps += 1
        offset += count + 1

    assert center_covering_caps == 0


def test_solid_mesh_is_unit_length_and_cached_by_section_shape():
    renderer = SolidMemberRenderer()
    shape = section_shape("W Laminado", {"d": 200, "bf": 100, "tw": 6, "tf": 8})

    assert shape is not None
    first = renderer._mesh_for(shape)
    second = renderer._mesh_for(shape)
    edges = renderer._edge_mesh_for(shape)

    assert first is second
    assert first.bounds[0] == pytest.approx(0.0)
    assert first.bounds[1] == pytest.approx(1.0)
    assert first.n_cells > 0
    assert edges.n_cells == 3 * len(shape.loops[0])
    assert {edges.GetCellType(index) for index in range(edges.n_cells)} == {3}
