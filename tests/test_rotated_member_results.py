import numpy as np
import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.pynite.model_builder import ModelBuilder
from osa.domain import AnalysisResult, Bar, Node
from osa.model import StructuralModel
from osa.rendering.local_axes_renderer import LocalAxesRenderer
from osa.rendering.result_renderer import ResultRenderer
from osa.services import ActionService, ResultService


def cantilever(end, rotation=0):
    model = StructuralModel()
    model.add_node("N1", 0, 0, 0)
    model.add_node("N2", *end)
    model.add_bar("B1", "N1", "N2")
    model.update_node_supports("N1", (True,) * 6)
    material = "Concreto Estrutural"
    model.update_bar_material("B1", material, model.materials[material])
    model.update_bar_section("B1", "Retangular")
    model.update_member_profile("B1", "Retangular", {"b": 200, "h": 400})
    model.update_member_rotation("B1", rotation)
    return model


@pytest.mark.parametrize("end", [
    (4, 0, 0), (-4, 0, 0), (0, 4, 0), (0, -4, 0), (0, 0, 4), (0, 0, -4),
    (2, 3, 4), (-2, -3, -4), (0.01, 0.01, 4),
])
@pytest.mark.parametrize("rotation", [0, 30, 90, 180, 270])
def test_solver_axes_match_drawn_section_for_every_member_direction(end, rotation):
    model = cantilever(end, rotation)
    target = ModelBuilder().build(model)
    expected = LocalAxesRenderer.basis(model.nodes["N1"], model.nodes["N2"], rotation)

    np.testing.assert_allclose(target.members["B1"].T()[:3, :3], expected, atol=1e-12)


@pytest.mark.parametrize("rotation", [0, 30, 90, 180, 270])
def test_vertical_cantilever_uses_inertia_about_its_drawn_local_y(rotation):
    model = cantilever((0, 0, 4), rotation)
    _x, _y, z = LocalAxesRenderer.basis(model.nodes["N1"], model.nodes["N2"], rotation)
    for axis, component in zip("XYZ", -10 * z):
        ActionService(model).add_node_force("N2", axis, float(component), "Caso")

    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    displacement = np.array([result.node_results["N2"][f"D{axis}"] for axis in "XYZ"])
    elastic_modulus = model.materials["Concreto Estrutural"][0]
    iy = 0.2 * 0.4**3 / 12
    np.testing.assert_allclose(displacement, z * (-10 * 4**3 / (3 * elastic_modulus * iy)), atol=1e-12)
    assert result.member_results["B1"]["start"]["moment_y"] == pytest.approx(40)
    assert result.member_results["B1"]["start"]["moment_z"] == pytest.approx(0, abs=1e-10)


class Plotter:
    def __init__(self):
        self.meshes = []

    def add_mesh(self, mesh, **options):
        self.meshes.append((mesh, options))
        return object()


def test_local_moment_geometry_follows_the_rolled_column_axes():
    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 0, 0, 3)}
    model.bars = {"B1": Bar("B1", "N1", "N2", rotation=90)}
    result = AnalysisResult(0, "Caso", member_results={
        "B1": {"samples": [{"x": 0, "moment_y": 10}, {"x": 3, "moment_y": 10}]},
    })
    plotter = Plotter()
    ResultRenderer().render(plotter, model, result, "Fletor Y")
    points = plotter.meshes[0][0].points
    assert points[:, 0].min() < 0
    np.testing.assert_allclose(points[:, 1], 0, atol=1e-12)


def test_rolled_columns_and_beam_have_balanced_joint_moments_in_the_frame_plane():
    model = StructuralModel()
    for name, point in zip(("N1", "N2", "N3", "N4"), ((-2, 0, 0), (-2, 0, 3), (2, 0, 3), (2, 0, 0))):
        model.add_node(name, *point)
    for name, start, end, rotation in (("B1", "N1", "N2", 90), ("B2", "N2", "N3", 0),
                                        ("B3", "N4", "N3", 90)):
        model.add_bar(name, start, end)
        model.update_bar_material(name, "Aço Estrutural", model.materials["Aço Estrutural"])
        model.update_bar_section(name, "W Laminado")
        model.update_member_profile(name, "W 410 x 38.8", {"d": 399, "bf": 140, "tw": 6.4, "tf": 8.8})
        model.update_member_rotation(name, rotation)
    for name in ("N1", "N4"):
        model.update_node_supports(name, (True,) * 6)
    ActionService(model).add_member_distributed_force("B2", "Z", -20, -20, "Caso")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    left, beam, right = (result.member_results[name] for name in ("B1", "B2", "B3"))
    assert abs(left["end"]["moment_y"]) > 10
    assert left["end"]["moment_y"] == pytest.approx(beam["start"]["moment_y"])
    assert right["end"]["moment_y"] == pytest.approx(-beam["end"]["moment_y"])
    assert sum(n["RXN_FZ"] for n in result.node_results.values()) == pytest.approx(80)
    for values in (left, beam, right):
        assert values["end"]["moment_z"] == pytest.approx(0, abs=1e-10)
    actors, _positions, labels = ResultRenderer().render(Plotter(), model, result, "Fletor Y")
    assert actors and len(labels) == 6
    assert "0 kN·m" not in labels


def test_legacy_saved_analysis_requires_reprocessing_after_axis_correction():
    model = cantilever((0, 0, 4), 90)
    model.analysis_results = [AnalysisResult(model.revision, "Caso", member_results={"B1": {"old": 1}})]
    data = model.as_dict()
    restored = StructuralModel()
    restored.load_dict(data)
    restored.revision = model.revision
    assert ResultService(restored).current()

    data.pop("analysis_axes")
    restored.load_dict(data)
    restored.revision = model.revision
    assert not ResultService(restored).current()
    assert restored.analysis_results[0].member_results["B1"] == {"old": 1}
    # Re-saving the project must not accidentally make the old result current.
    restored.load_dict(restored.as_dict())
    assert not ResultService(restored).current()
