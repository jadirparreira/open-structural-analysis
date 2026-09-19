import pytest

from osa.analysis.pynite.model_builder import ModelBuilder
from osa.model import StructuralModel
from osa.sections import calculate_section_properties
from osa.sections.contours import contour_points, polygon_properties


def test_w_profile_is_calculated_from_the_reference_contour():
    properties = calculate_section_properties(
        "W Laminado", {"d": 200, "bf": 100, "tw": 6, "tf": 8}, 7850
    )
    expected_area, expected_y, expected_z, expected_iy, expected_iz, expected_iyz = polygon_properties(
        contour_points("W Laminado", {"d": 200, "bf": 100}, arc_steps=16)
    )

    assert properties.area_mm2 == pytest.approx(expected_area)
    assert properties.centroid_y_mm == pytest.approx(expected_y)
    assert properties.centroid_z_mm == pytest.approx(expected_z)
    assert properties.iy_mm4 == pytest.approx(expected_iy)
    assert properties.iz_mm4 == pytest.approx(expected_iz)
    assert properties.iyz_mm4 == pytest.approx(expected_iyz)
    assert properties.j_mm4 == pytest.approx((2 * 100 * 8**3 + 184 * 6**3) / 3)
    assert properties.mass_kg_m == pytest.approx(expected_area * 1e-6 * 7850)


def test_l_profile_uses_principal_inertias_for_an_unsymmetrical_section():
    properties = calculate_section_properties("L Laminado", {"b": 50, "t": 5}, 7850)

    assert properties.area_mm2 == pytest.approx(475)
    assert properties.iyz_mm4 != pytest.approx(0)
    assert properties.i_major_mm4 > properties.i_minor_mm4 > 0
    assert properties.j_mm4 == pytest.approx((50 * 5**3 + 45 * 5**3) / 3)


def test_t_profile_uses_the_single_dimension_and_thickness():
    properties = calculate_section_properties("T Laminado", {"d": 50, "t": 5}, 7850)

    assert properties.area_mm2 == pytest.approx(475)
    assert properties.iyz_mm4 == pytest.approx(0)
    assert properties.iy_mm4 > properties.iz_mm4


@pytest.mark.parametrize(
    ("family", "geometry"),
    (
        ("U Formado", {"d": 100, "bf": 50, "t": 2}),
        ("C Formado", {"d": 100, "bf": 50, "t": 2, "c": 10}),
        ("Z Formado", {"d": 100, "bf": 50, "t": 2}),
        ("L Formado", {"d": 60, "bf": 50, "t": 2}),
        ("Cartola Formado", {"d": 100, "bf": 60, "t": 2, "c": 10}),
        ("Tubular Circular", {"D": 100, "t": 3}),
        ("Tubular Quadrado", {"b": 100, "t": 3}),
        ("Tubular Retangular", {"b": 100, "h": 60, "t": 3}),
        ("Barra Redonda", {"d": 20}),
        ("Barra Quadrada", {"b": 20}),
        ("Barra Retangular", {"b": 20, "h": 30}),
    ),
)
def test_non_catalogued_families_are_calculated_from_user_dimensions(family, geometry):
    properties = calculate_section_properties(family, geometry, 7850)

    assert properties.area_mm2 > 0
    assert properties.iy_mm4 > 0
    assert properties.iz_mm4 > 0
    assert properties.j_mm4 > 0
    assert properties.mass_kg_m > 0


def test_circular_tube_and_bar_use_exact_closed_form_properties():
    tube = calculate_section_properties("Tubular Circular", {"D": 100, "t": 3}, 7850)
    outer = 100.0
    inner = 94.0
    expected_area = 3.141592653589793 * (outer**2 - inner**2) / 4.0
    expected_i = 3.141592653589793 * (outer**4 - inner**4) / 64.0
    assert tube.area_mm2 == pytest.approx(expected_area)
    assert tube.iy_mm4 == pytest.approx(expected_i)
    assert tube.iz_mm4 == pytest.approx(expected_i)
    assert tube.j_mm4 == pytest.approx(2.0 * expected_i)

    bar = calculate_section_properties("Barra Circular", {"d": 12.5}, 7850)
    expected_bar_area = 3.141592653589793 * 12.5**2 / 4.0
    expected_bar_i = 3.141592653589793 * 12.5**4 / 64.0
    assert bar.area_mm2 == pytest.approx(expected_bar_area)
    assert bar.iy_mm4 == pytest.approx(expected_bar_i)
    assert bar.j_mm4 == pytest.approx(2.0 * expected_bar_i)


@pytest.mark.parametrize(
    ("family", "geometry", "expected_area"),
    (
        ("Retangular", {"b": 200.0, "h": 400.0}, 80_000.0),
        ("Circular", {"d": 200.0}, 3.141592653589793 * 200.0**2 / 4.0),
        ("Tipo L", {"b": 200.0, "h": 400.0, "t": 40.0}, 22_400.0),
        ("Tipo T", {"b": 200.0, "h": 400.0, "t": 40.0}, 22_400.0),
        ("Tipo I", {"b": 200.0, "h": 400.0, "t": 40.0}, 28_800.0),
        ("Tipo U", {"b": 200.0, "h": 400.0, "t": 40.0}, 36_800.0),
        ("Tipo +", {"b": 200.0, "h": 400.0, "t": 40.0}, 22_400.0),
        ("Retangular Vazado", {"b": 200.0, "h": 400.0, "t": 40.0}, 41_600.0),
        (
            "Circular Vazado",
            {"d": 200.0, "t": 40.0},
            3.141592653589793 * (200.0**2 - 120.0**2) / 4.0,
        ),
    ),
)
def test_concrete_section_areas_and_symmetry(family, geometry, expected_area):
    properties = calculate_section_properties(family, geometry, 2500.0)

    assert properties.area_mm2 == pytest.approx(expected_area)
    assert properties.mass_kg_m == pytest.approx(expected_area * 1e-6 * 2500.0)
    assert properties.iy_mm4 > 0
    assert properties.iz_mm4 > 0
    assert properties.j_mm4 > 0
    if family in {"Circular", "Circular Vazado"}:
        assert properties.iy_mm4 == pytest.approx(properties.iz_mm4)
        assert properties.iyz_mm4 == pytest.approx(0.0)
    elif family != "Tipo L":
        assert properties.iyz_mm4 == pytest.approx(0.0)


def test_concrete_rectangular_and_circular_inertias_are_closed_form():
    rectangular = calculate_section_properties(
        "Retangular", {"b": 200.0, "h": 400.0}, 2500.0
    )
    assert rectangular.iy_mm4 == pytest.approx(200.0 * 400.0**3 / 12.0)
    assert rectangular.iz_mm4 == pytest.approx(400.0 * 200.0**3 / 12.0)

    circular = calculate_section_properties("Circular", {"d": 200.0}, 2500.0)
    expected_i = 3.141592653589793 * 200.0**4 / 64.0
    assert circular.iy_mm4 == pytest.approx(expected_i)
    assert circular.iz_mm4 == pytest.approx(expected_i)
    assert circular.j_mm4 == pytest.approx(2.0 * expected_i)


@pytest.mark.parametrize(
    ("family", "geometry", "expected_area"),
    (
        ("Circular", {"d": 200.0}, 3.141592653589793 * 200.0**2 / 4.0),
        ("Quadrada", {"b": 200.0}, 40_000.0),
        ("Retangular", {"b": 150.0, "h": 300.0}, 45_000.0),
    ),
)
def test_wood_solid_sections_reuse_bar_geometry_and_density(
    family, geometry, expected_area
):
    properties = calculate_section_properties(family, geometry, 500.0)

    assert properties.area_mm2 == pytest.approx(expected_area)
    assert properties.mass_kg_m == pytest.approx(expected_area * 1e-6 * 500.0)
    assert properties.iy_mm4 > 0
    assert properties.iz_mm4 > 0
    assert properties.j_mm4 > 0


def test_rounded_tube_properties_match_the_rounded_section_geometry():
    side, thickness = 100.0, 3.0
    tube = calculate_section_properties("Tubular Quadrado", {"b": side, "t": thickness}, 7850)
    corner_factor = 4.0 - 3.141592653589793
    expected_area = (
        side**2 - corner_factor * (2.0 * thickness) ** 2
        - ((side - 2.0 * thickness) ** 2 - corner_factor * thickness**2)
    )
    assert tube.area_mm2 == pytest.approx(expected_area)
    assert tube.iy_mm4 == pytest.approx(tube.iz_mm4)

    rectangular = calculate_section_properties(
        "Tubular Retangular", {"b": 120, "h": 80, "t": 2.25}, 7850
    )
    swapped = calculate_section_properties(
        "Tubular Retangular", {"b": 80, "h": 120, "t": 2.25}, 7850
    )
    assert rectangular.area_mm2 == pytest.approx(swapped.area_mm2)
    assert rectangular.iy_mm4 == pytest.approx(swapped.iz_mm4)
    assert rectangular.iz_mm4 == pytest.approx(swapped.iy_mm4)


@pytest.mark.parametrize(
    ("family", "geometry", "expected_area", "expected_j"),
    (
        ("U Formado", {"d": 100, "bf": 50, "t": 2}, 392.0, 522.6666666667),
        ("C Formado", {"d": 100, "bf": 50, "t": 2, "c": 10}, 432.0, 576.0),
        ("Z Formado", {"d": 100, "bf": 50, "t": 2}, 392.0, 522.6666666667),
        ("L Formado", {"d": 60, "bf": 50, "t": 2}, 216.0, 288.0),
        ("Cartola Formado", {"d": 100, "bf": 60, "t": 2, "c": 10}, 544.0, 725.3333333333),
    ),
)
def test_formed_profiles_use_non_overlapping_rectangular_walls(
    family, geometry, expected_area, expected_j
):
    properties = calculate_section_properties(family, geometry, 7850)

    assert properties.area_mm2 == pytest.approx(expected_area)
    assert properties.j_mm4 == pytest.approx(expected_j)
    assert properties.mass_kg_m == pytest.approx(expected_area * 1e-6 * 7850)


def test_formed_profile_axes_follow_the_section_symmetry():
    u = calculate_section_properties("U Formado", {"d": 100, "bf": 50, "t": 2})
    c = calculate_section_properties("C Formado", {"d": 100, "bf": 50, "t": 2, "c": 10})
    z = calculate_section_properties("Z Formado", {"d": 100, "bf": 50, "t": 2})
    l = calculate_section_properties("L Formado", {"d": 60, "bf": 50, "t": 2})
    hat = calculate_section_properties("Cartola Formado", {"d": 100, "bf": 60, "t": 2, "c": 10})

    assert u.centroid_z_mm == pytest.approx(50.0)
    assert c.centroid_z_mm == pytest.approx(50.0)
    assert z.centroid_z_mm == pytest.approx(50.0)
    assert z.iyz_mm4 != pytest.approx(0.0)
    assert l.iyz_mm4 != pytest.approx(0.0)
    assert hat.centroid_y_mm == pytest.approx(0.0)
    assert hat.iyz_mm4 == pytest.approx(0.0)


def test_unknown_or_invalid_section_geometry_is_rejected():
    with pytest.raises(ValueError, match="indisponível"):
        calculate_section_properties("Perfil inexistente", {"d": 1})
    with pytest.raises(ValueError, match="d > 2 tf"):
        calculate_section_properties("W Laminado", {"d": 10, "bf": 100, "tw": 6, "tf": 8})


def test_pynite_builder_receives_calculated_area_inertias_and_torsion():
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", 3, 0, 0)
    model.add_bar("B1", "N1", "N2")
    model.update_bar_material("B1", "Aço Estrutural", model.materials["Aço Estrutural"])
    model.update_bar_section("B1", "W Laminado")
    geometry = {"d": 200, "bf": 100, "tw": 6, "tf": 8}
    model.update_member_profile("B1", "W 200 x 15.0", geometry)

    target = ModelBuilder().build(model)
    expected = calculate_section_properties("W Laminado", geometry, 7850)
    section = target.sections["section::B1"]

    assert section.A == pytest.approx(expected.area_mm2 * 1e-6)
    assert section.Iy == pytest.approx(expected.i_minor_mm4 * 1e-12)
    assert section.Iz == pytest.approx(expected.i_major_mm4 * 1e-12)
    assert section.J == pytest.approx(expected.j_mm4 * 1e-12)
