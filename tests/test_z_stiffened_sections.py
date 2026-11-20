"""Geometric validation against NBR 6355:2012, tables A.4 and A.5."""

import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.pynite.model_builder import ModelBuilder
from osa.data import CatalogLoader
from osa.model import StructuralModel
from osa.persistence.project_serializer import ProjectSerializer
from osa.sections.contours import polygon_properties
from osa.sections.geometry import section_shape
from osa.sections.properties import calculate_section_properties
from osa.services.action_service import ActionService


@pytest.mark.parametrize("points", [((0., 0.), (2., 0.), (0., 1.)),
                                    ((0., 1.), (2., 0.), (0., 0.))])
def test_polygon_product_of_inertia_is_independent_of_winding(points):
    # Triangle integration about its centroid: Iyz = -b²h²/72.
    assert polygon_properties(points)[-1] == pytest.approx(-1 / 18)


@pytest.mark.parametrize(
    ("family", "area_cm2", "ix_cm4", "iy_cm4", "ixy_cm4"),
    [("Z45 Formado", 4.51, 73.48, 34.91, 38.52),
     ("Z90 Formado", 4.42, 70.26, 28.27, 33.95)],
)
def test_z_properties_agree_with_nbr_6355_tables(family, area_cm2, ix_cm4, iy_cm4, ixy_cm4):
    # Tables A.4/A.5, 100 × 50 × 17 × 2 mm; internal radius 2 mm.
    # Tables are rounded; contours sample circular arcs and their formulas
    # use slightly different rounding, so allow 0.2%.
    geometry = {"d": 100, "bf": 50, "c": 17, "t": 2, "r": 2}
    props = calculate_section_properties(family, geometry)
    assert props.area_cm2 == pytest.approx(area_cm2, rel=0.002)
    assert props.iy_cm4 == pytest.approx(ix_cm4, rel=0.002)
    assert props.iz_cm4 == pytest.approx(iy_cm4, rel=0.002)
    assert props.iyz_mm4 / 10000 == pytest.approx(ixy_cm4, rel=0.002)
    assert section_shape(family, geometry) is not None
    mirrored = calculate_section_properties(family, geometry, mirror_z=True)
    assert mirrored.iyz_mm4 == pytest.approx(-props.iyz_mm4)


@pytest.mark.parametrize("family", ["Z45 Formado", "Z90 Formado"])
def test_z_sections_round_trip_with_explicit_radius(family):
    names = {entry["name"] for entry in CatalogLoader().section_families("Aço")}
    assert {"Z Formado", family} <= names
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 0, 0, 3)
    model.add_bar("B1", "A", "B")
    model.update_bar_section("B1", family)
    geometry = {"d": 100, "bf": 50, "c": 17, "t": 2, "r": 2}
    model.update_member_profile("B1", "teste", geometry)
    serializer = ProjectSerializer()
    restored = StructuralModel()
    serializer.load_into(restored, serializer.dump(model))
    assert restored.bars["B1"].section == family
    assert restored.bars["B1"].geometry_dict() == geometry


def test_z_stiffener_rejects_bends_that_do_not_fit():
    with pytest.raises(ValueError, match="não comportam"):
        calculate_section_properties("Z90 Formado", {"d": 100, "bf": 50, "c": 3, "t": 2, "r": 4})


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0])
def test_z_section_rejects_nonfinite_or_nonpositive_dimensions(invalid):
    with pytest.raises(ValueError):
        calculate_section_properties("Z45 Formado", {"d": 100, "bf": 50, "c": 17, "t": 2, "r": invalid})


def _cantilever(family):
    model = StructuralModel()
    model.add_node("A", 0, 0, 0)
    model.add_node("B", 3, 0, 0)
    model.update_node_supports("A", (True,) * 6)
    model.add_bar("B1", "A", "B")
    model.update_bar_material("B1", "ASTM A36", model.materials["ASTM A36"])
    model.update_bar_section("B1", family)
    model.update_member_profile("B1", "teste", {"d": 100, "bf": 50, "c": 17, "t": 2, "r": 2})
    return model


@pytest.mark.parametrize("family", ["Z45 Formado", "Z90 Formado"])
@pytest.mark.parametrize("mirrored", [False, True])
def test_principal_axes_cantilever_matches_coupled_elasticity(family, mirrored):
    model = _cantilever(family)
    model.update_member_section_mirrored("B1", mirrored)
    ActionService(model).add_node_force("B", "Z", -1, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    props = calculate_section_properties(family, model.bars["B1"].geometry_dict(), mirror_z=mirrored)
    determinant = (props.iy_mm4 * props.iz_mm4 - props.iyz_mm4**2) * 1e-24
    expected_z = -3**3 / (3 * model.materials["ASTM A36"][0]) * (props.iz_mm4 * 1e-12) / determinant
    assert result.node_results["B"]["DZ"] == pytest.approx(expected_z, rel=1e-8)
    assert abs(result.node_results["B"]["DY"]) > 0
    start = result.member_results["B1"]["start"]
    assert abs(start["moment_y"]) == pytest.approx(3.0)
    assert start["moment_z"] == pytest.approx(0, abs=1e-9)
    assert start["shear_y"] == pytest.approx(0, abs=1e-9)
    assert abs(start["shear_z"]) == pytest.approx(1.0)


@pytest.mark.parametrize("axis", ["Y", "Z"])
def test_local_distributed_force_matches_global_force_along_member_basis(axis):
    local = _cantilever("Z90 Formado")
    global_model = _cantilever("Z90 Formado")
    ActionService(local).add_member_distributed_force("B1", axis, -1, -2, "Caso", reference="local")
    ActionService(global_model).add_member_distributed_force("B1", axis, -1, -2, "Caso")
    local_result = PyniteAdapter().run(local, AnalysisRequest())[0]
    global_result = PyniteAdapter().run(global_model, AnalysisRequest())[0]
    for component in ("DY", "DZ", "RY", "RZ"):
        assert local_result.node_results["B"][component] == pytest.approx(
            global_result.node_results["B"][component], abs=1e-10,
        )
    for component in ("shear_y", "shear_z", "moment_y", "moment_z"):
        assert local_result.member_results["B1"]["start"][component] == pytest.approx(
            global_result.member_results["B1"]["start"][component], abs=1e-10,
        )


@pytest.mark.parametrize("axis", ["Y", "Z"])
def test_distributed_local_moment_preserves_global_equilibrium(axis):
    model = _cantilever("Z45 Formado")
    ActionService(model).add_member_moment("B1", axis, 2.0, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    reaction = result.node_results["A"]
    assert reaction[f"RXN_M{axis}"] == pytest.approx(-6.0, abs=1e-8)
    assert reaction[f"RXN_M{'Z' if axis == 'Y' else 'Y'}"] == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("axis", ["Y", "Z"])
@pytest.mark.parametrize("mirrored", [False, True])
def test_member_moments_are_returned_in_geometric_axes(axis, mirrored):
    model = _cantilever("Z45 Formado")
    model.update_member_section_mirrored("B1", mirrored)
    ActionService(model).add_node_moment("B", axis, 2.0, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    start = result.member_results["B1"]["start"]
    assert abs(start[f"moment_{axis.lower()}"]) == pytest.approx(2.0, abs=1e-8)
    assert start[f"moment_{'z' if axis == 'Y' else 'y'}"] == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("family", ["Z45 Formado", "Z90 Formado"])
def test_unsupported_local_releases_are_not_silently_rotated(family):
    model = _cantilever(family)
    model.update_member_rotation_flexibility_percent("B1", (0, 0, 50, 0, 0, 0))
    with pytest.raises(ValueError, match="semirrígidas"):
        ModelBuilder().build(model)


@pytest.mark.parametrize(("family", "geometry"), [
    ("Z Formado", {"d": 100, "bf": 50, "t": 2}),
    ("L Laminado", {"b": 100, "t": 10}),
])
def test_existing_unsymmetric_sections_use_their_principal_axes(family, geometry):
    model = _cantilever("Z90 Formado")
    model.update_bar_section("B1", family)
    model.update_member_profile("B1", "teste", geometry)
    ActionService(model).add_node_force("B", "Z", -1, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    props = calculate_section_properties(family, geometry)
    determinant = (props.iy_mm4 * props.iz_mm4 - props.iyz_mm4**2) * 1e-24
    expected_z = -3**3 / (3 * model.materials["ASTM A36"][0]) * (props.iz_mm4 * 1e-12) / determinant
    assert result.node_results["B"]["DZ"] == pytest.approx(expected_z, rel=1e-8)


def test_rectangular_section_wider_than_high_keeps_its_geometric_axes():
    model = _cantilever("Z90 Formado")
    model.update_bar_section("B1", "Barra Retangular")
    geometry = {"b": 100, "h": 50}
    model.update_member_profile("B1", "teste", geometry)
    ActionService(model).add_node_force("B", "Z", -1, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    inertia_y = 100 * 50**3 / 12 * 1e-12
    expected = -3**3 / (3 * model.materials["ASTM A36"][0] * inertia_y)
    assert result.node_results["B"]["DZ"] == pytest.approx(expected, rel=1e-8)
    assert result.node_results["B"]["DY"] == pytest.approx(0, abs=1e-10)
