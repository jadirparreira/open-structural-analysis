import numpy as np
import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.pynite.load_case_builder import LoadCaseBuilder
from osa.commands import CommandSession
from osa.domain import Action, AnalysisResult, Bar, Node
from osa.model import StructuralModel
from osa.rendering.result_renderer import ResultRenderer
from osa.services import ModelService
from osa.services.action_service import ActionService


def test_mezanino_is_analyzed_with_its_actions_and_an_implicit_combination():
    model = StructuralModel()
    CommandSession(ModelService(model)).submit("mezanino")

    stages: list[str] = []
    results = PyniteAdapter().run(model, AnalysisRequest(), stages.append)

    assert len(results) == 1
    result = results[0]
    assert result.load_reference == "Combo 1"
    assert len(result.node_results) == 34
    assert len(result.member_results) == 54
    assert stages == ["model", "loads", "combinations", "solve", "results"]
    assert sum(node["RXN_FZ"] for node in result.node_results.values()) == pytest.approx(252.968, abs=0.001)
    assert max(abs(node["DZ"]) for node in result.node_results.values()) > 0


def test_explicit_combination_multiplies_all_three_factor_columns():
    model = StructuralModel()
    commands = CommandSession(ModelService(model))
    commands.submit("mezanino")
    from osa.domain import LoadCombination
    from osa.services import ActionService

    ActionService(model).set_combination(LoadCombination(
        "ELU", (("PP", 1.25), ("AP", 1.35), ("AV", 1.50)),
        (("PP", 1.0), ("AP", 1.0), ("AV", 1.0)),
        (("PP", 1.0), ("AP", 1.0), ("AV", 1.0)),
        ("PP", "AP", "AV"), "PP+AP+AV", "ELU",
    ))

    result = PyniteAdapter().run(model, AnalysisRequest(("ELU",)))[0]

    assert sum(node["RXN_FZ"] for node in result.node_results.values()) == pytest.approx(362.458, abs=0.001)


def test_default_analysis_combinations_are_available_for_mezanino():
    model = StructuralModel()
    CommandSession(ModelService(model)).submit("mezanino")

    assert ActionService(model).ensure_default_combinations()
    assert tuple(model.load_combinations) == ("Combinação 01", "Combinação 02", "Combinação 03")


def test_node_actions_use_pynite_global_force_and_moment_directions():
    class Target:
        def __init__(self):
            self.loads = []

        def add_node_load(self, target, direction, value, load_case):
            self.loads.append((target, direction, value, load_case))

    model = StructuralModel()
    actions = ActionService(model)
    for axis in "XYZ":
        actions.add_node_force("N1", axis, 1.0, "Caso")
        actions.add_node_moment("N1", axis, 2.0, "Caso")

    target = Target()
    LoadCaseBuilder().apply(target, model)

    assert [direction for _target, direction, _value, _case in target.loads] == [
        "FX", "MX", "FY", "MY", "FZ", "MZ",
    ]


def test_clearing_a_node_action_removes_it_from_the_solver_model():
    model = StructuralModel()
    actions = ActionService(model)
    actions.add_node_force("N1", "Y", 12.0, "Caso")
    actions.add_node_moment("N1", "Z", 3.0, "Caso")

    actions.add_node_force("N1", "Y", 0.0, "Caso")
    actions.add_node_moment("N1", "Z", 0.0, "Caso")

    assert not model.actions


def test_distributed_member_moment_is_translated_to_local_point_couples():
    class Member:
        @staticmethod
        def L():
            return 5.0

    class Target:
        def __init__(self):
            self.members = {"B1": Member()}
            self.moments = []

        def add_member_pt_load(self, target, direction, value, position, load_case):
            self.moments.append((target, direction, value, position, load_case))

    model = StructuralModel()
    model.actions["Carga 1"] = Action("Carga 1", "member_moment_Y", "B1", (-1.1,), "Caso")
    target = Target()

    LoadCaseBuilder().apply(target, model)

    assert len(target.moments) == LoadCaseBuilder.DISTRIBUTED_MOMENT_SEGMENTS
    assert {moment[1] for moment in target.moments} == {"My"}
    assert sum(moment[2] for moment in target.moments) == pytest.approx(-5.5)


def test_normal_result_renderer_uses_sampled_axial_forces():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    CommandSession(ModelService(model)).submit("mezanino")
    result = PyniteAdapter().run(model, AnalysisRequest())[0]

    actors, positions, labels = ResultRenderer().render(Plotter(), model, result, "Normal")

    assert len(result.member_results["B1"]["samples"]) == 21
    assert actors
    assert len(positions) == len(labels)


def test_normal_result_labels_do_not_render_negative_zero():
    assert ResultRenderer._format_force(-0.0004) == "0 kN"
    assert ResultRenderer._format_force(-1.1234) == "-1,123 kN"
    assert ResultRenderer._format_force(-1.1) == "-1,1 kN"


def test_zero_after_three_decimal_rounding_hides_only_the_normal_diagram():
    class Plotter:
        def add_mesh(self, *_args, **_options):
            raise AssertionError("Esforço nulo não deve criar a geometria do diagrama.")

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar("B1", "N1", "N2")}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": ({"x": 0, "axial": -0.0004}, {"x": 2, "axial": -0.0004})}
    })

    actors, positions, labels = ResultRenderer().render(Plotter(), model, result, "Normal")

    assert not actors
    assert len(positions) == 1
    assert labels == ("0 kN",)


def test_shear_diagrams_use_their_respective_sampled_results_and_sign_colors():
    class Plotter:
        def __init__(self):
            self.options = []

        def add_mesh(self, _mesh, **options):
            self.options.append(options)
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar("B1", "N1", "N2")}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "shear_y": -4, "shear_z": 5},
            {"x": 2, "shear_y": 4, "shear_z": 5},
        )}
    })

    plotter_y = Plotter()
    actors_y, _positions_y, labels_y = ResultRenderer().render(plotter_y, model, result, "Cortante Y")
    actors_z, _positions_z, labels_z = ResultRenderer().render(Plotter(), model, result, "Cortante Z")

    assert actors_y and actors_z
    assert len(actors_y) <= 4
    assert len(actors_z) <= 4
    assert labels_y == ("-4 kN", "4 kN")
    assert labels_z == ("5 kN",)
    assert {options["color"] for options in plotter_y.options} == {"#0969da", "#cf222e"}


def test_torsion_diagram_uses_torque_samples_and_moment_unit():
    class Plotter:
        def add_mesh(self, _mesh, **_options):
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar("B1", "N1", "N2")}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": ({"x": 0, "torque": -1.25}, {"x": 2, "torque": -1.25})}
    })

    actors, positions, labels = ResultRenderer().render(Plotter(), model, result, "Torsor")

    assert actors
    assert len(positions) == 1
    assert labels == ("-1,25 kN·m",)


def test_bending_diagrams_use_their_respective_local_moments():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, _mesh, **_options):
            self.meshes.append(_mesh)
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar("B1", "N1", "N2")}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "moment_y": 2.75, "moment_z": -3.5},
            {"x": 2, "moment_y": 2.75, "moment_z": -3.5},
        )}
    })

    plotter_y, plotter_z = Plotter(), Plotter()
    actors_y, positions_y, labels_y = ResultRenderer().render(plotter_y, model, result, "Fletor Y")
    actors_z, positions_z, labels_z = ResultRenderer().render(plotter_z, model, result, "Fletor Z")

    assert actors_y and actors_z
    assert len(positions_y) == len(positions_z) == 1
    assert labels_y == ("-2,75 kN·m",)
    assert labels_z == ("3,5 kN·m",)
    # A inversão brasileira altera o valor mostrado, não o lado da curva.
    assert plotter_y.meshes[0].points[2][2] > 0.0


def test_bending_labels_are_placed_outside_the_drawn_curve():
    positions, labels = ResultRenderer()._member_result_labels(
        np.asarray((-1.667, 0.833)),
        np.asarray((1.667, -0.833)),
        np.asarray(((0, 0, 0), (2, 0, 0))),
        np.asarray(((0, 0, 0.5), (2, 0, -0.25))),
        np.asarray((1, 0, 0)), np.asarray((0, 0, 1)), "kN·m",
    )

    assert labels == ["-1,667 kN·m", "0,833 kN·m"]
    assert positions[0][0] == pytest.approx(0.2)
    assert positions[1][0] == pytest.approx(1.8)
    assert positions[0][2] > 0.5
    assert positions[1][2] < -0.25


def test_deformation_draws_an_amplified_deformed_member_centerline():
    class Plotter:
        def __init__(self):
            self.meshes = []
            self.options = []

        def add_mesh(self, mesh, **_options):
            self.meshes.append(mesh)
            self.options.append(_options)
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar(
        "B1", "N1", "N2", section="Retangular", profile="R 200 x 400",
        section_geometry=(("b", 200), ("h", 400)),
    )}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "deflection_y": 0, "deflection_z": 0},
            {"x": 2, "deflection_y": 0.01, "deflection_z": 0},
        )}
    })
    plotter = Plotter()

    actors, positions, labels = ResultRenderer().render(plotter, model, result, "Deformação XYZ")

    assert actors
    assert len(positions) == 1
    assert labels == ("10 mm",)
    assert positions[0][1] > 1.0
    assert len(plotter.meshes) == 3
    assert np.max(plotter.meshes[1].points[:, 1]) == pytest.approx(1.1)

    line_plotter = Plotter()
    line_actors, _positions, _labels = ResultRenderer().render(
        line_plotter, model, result, "Deformação XYZ", solid_members_visible=False,
    )
    assert len(line_actors) == len(line_plotter.meshes) == 2
    assert line_plotter.options[0]["line_width"] == 1.0
    assert line_plotter.options[1]["line_width"] == 2.0
    assert tuple(line_plotter.meshes[1].cell_data["rgb"][0]) == (110, 119, 129)


def test_deformation_components_share_the_xyz_scale():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **_options):
            self.meshes.append(mesh)
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar(
        "B1", "N1", "N2", section="Retangular", profile="R 200 x 400",
        section_geometry=(("b", 200), ("h", 400)),
    )}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "deflection_x": 0, "deflection_y": 0, "deflection_z": 0},
            {"x": 2, "deflection_x": 0.006, "deflection_y": 0.008, "deflection_z": 0},
        )}
    })
    plotter_x, plotter_y, plotter_xyz = Plotter(), Plotter(), Plotter()

    ResultRenderer().render(plotter_x, model, result, "Deformação X")
    ResultRenderer().render(plotter_y, model, result, "Deformação Y")
    ResultRenderer().render(plotter_xyz, model, result, "Deformação XYZ")

    assert np.max(plotter_x.meshes[1].points[:, 0]) == pytest.approx(2.6)
    assert np.max(plotter_y.meshes[1].points[:, 1]) == pytest.approx(0.9)
    assert np.max(plotter_xyz.meshes[1].points[:, 0]) == pytest.approx(2.6)
    assert np.max(plotter_xyz.meshes[1].points[:, 1]) == pytest.approx(0.9)
