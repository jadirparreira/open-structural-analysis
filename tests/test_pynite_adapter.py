import numpy as np
import pytest

from osa.analysis import AnalysisRequest
from osa.analysis.pynite import PyniteAdapter
from osa.analysis.pynite.load_case_builder import LoadCaseBuilder
from osa.analysis.pynite.plate_mesh import generate_plate_mesh
from osa.commands import CommandSession
from osa.domain import Action, AnalysisResult, Bar, Node
from osa.model import StructuralModel
from osa.rendering.action_renderer import ActionRenderer
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


def test_slab_supported_beam_results_keep_the_full_original_member_length():
    model = StructuralModel()
    coordinates = {
        "N1": (0, 0, 3), "N2": (4, 0, 3), "N3": (4, 3, 3), "N4": (0, 3, 3),
        "N5": (0, 0, 0), "N6": (4, 0, 0), "N7": (4, 3, 0), "N8": (0, 3, 0),
    }
    for name, point in coordinates.items():
        model.add_node(name, *point)
    edges = (("N1", "N2"), ("N2", "N3"), ("N3", "N4"), ("N4", "N1"))
    for index, (start, end) in enumerate(edges, start=1):
        name = f"B{index}"
        model.add_bar(name, start, end)
        model.update_bar_material(name, "ASTM A36", model.materials["ASTM A36"])
        model.update_bar_section(name, "Retangular")
        model.update_member_profile(name, "Retangular", {"b": 200, "h": 400})
    for index, (start, end) in enumerate((("N1", "N5"), ("N2", "N6"), ("N3", "N7"), ("N4", "N8")), start=5):
        name = f"B{index}"
        model.add_bar(name, start, end)
        model.update_bar_material(name, "ASTM A36", model.materials["ASTM A36"])
        model.update_bar_section(name, "Retangular")
        model.update_member_profile(name, "Retangular", {"b": 200, "h": 400})
    for name in ("N5", "N6", "N7", "N8"):
        model.update_node_supports(name, (True,) * 6)
    model.add_plate(
        ((0, 0, 3), (4, 0, 3), (4, 3, 3), (0, 3, 3)),
        supports=tuple(("bar", f"B{index}") for index in range(1, 5)),
        material="Concreto Estrutural", thickness_mm=150,
    )
    ActionService(model).add_plate_surface_pressure("P1", -5, "Caso")

    result = PyniteAdapter().run(model, AnalysisRequest())[0]
    samples = result.member_results["B1"]["samples"]

    assert len(samples) == 21
    assert samples[0]["x"] == pytest.approx(0)
    assert samples[-1]["x"] == pytest.approx(4)
    assert max(abs(sample["moment_y"]) for sample in samples[1:-1]) > 0

    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    plotter = Plotter()
    actors, _positions, _labels = ResultRenderer().render(plotter, model, result, "Fletor Y")

    assert actors
    assert min(mesh.points[:, 0].min() for mesh, _options in plotter.meshes) == pytest.approx(0)
    assert max(mesh.points[:, 0].max() for mesh, _options in plotter.meshes) == pytest.approx(4)

    deformation_plotter = Plotter()
    deformation_actors, _positions, _labels = ResultRenderer().render(
        deformation_plotter, model, result, "Deformação Z", deformation_scale=100,
    )
    deformed_plate_meshes = [
        mesh for mesh, _options in deformation_plotter.meshes if mesh.faces.size
    ]
    assert deformation_actors
    assert deformed_plate_meshes
    assert any(np.ptp(mesh.points[:, 2]) > 1e-4 for mesh in deformed_plate_meshes)
    deformed_plate_options = next(
        options for mesh, options in deformation_plotter.meshes if mesh.faces.size
    )
    assert deformed_plate_options["opacity"] == 1.0
    deformed_edge_options = next(
        options for mesh, options in deformation_plotter.meshes
        if mesh.n_lines and options.get("line_width") == 1.0
    )
    assert deformed_edge_options["color"] == "#57606a"
    assert deformed_edge_options["opacity"] == 1.0

    line_deformation_plotter = Plotter()
    ResultRenderer().render(
        line_deformation_plotter, model, result, "Deformação Z",
        solid_members_visible=False, deformation_scale=100,
    )
    line_deformed_plate_options = next(
        options for mesh, options in line_deformation_plotter.meshes if mesh.faces.size
    )
    assert line_deformed_plate_options["opacity"] == 0.7

    model.plate_mesh = generate_plate_mesh(model.plates)
    action_plotter = Plotter()
    action_actors, _positions, action_labels = ActionRenderer().render(
        action_plotter, model, "Caso",
    )
    assert action_actors
    assert "-5 kN/m²" in action_labels
    assert max(mesh.n_cells for mesh, _options in action_plotter.meshes) > 3
    action_surfaces = [
        mesh for mesh, _options in action_plotter.meshes if mesh.faces.size > 0
    ]
    assert action_surfaces
    assert max(float(mesh.points[:, 2].max()) for mesh in action_surfaces) > 3.0
    hidden_actors, _positions, hidden_labels = ActionRenderer().render(
        Plotter(), model, "Caso", {"plate_pressures": False},
    )
    assert hidden_actors == []
    assert hidden_labels == ()


def test_plate_result_contours_color_faces_and_mesh_from_plate_result_values():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)))
    nodes = {
        "FE::1": {"coordinates": (0, 0, 0)},
        "FE::2": {"coordinates": (2, 0, 0)},
        "FE::3": {"coordinates": (2, 2, 0)},
        "FE::4": {"coordinates": (0, 2, 0)},
    }
    result = AnalysisResult(0, "Combo", plate_results={
        "P1": {
            "nodes": nodes,
            "elements": {"Q1": {
                "nodes": tuple(nodes), "moment": [1.0, 2.0, 3.0],
                "shear": [4.0, 5.0], "membrane": [6.0, 7.0, 8.0],
            }},
        },
    })

    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    plotter = Plotter()
    actors, _positions, labels = ResultRenderer().render_plate_contours(
        plotter, model, result, "Fletor Y",
    )
    assert len(actors) == 2
    assert labels == ()
    surface, surface_options = plotter.meshes[0]
    mesh, mesh_options = plotter.meshes[1]
    assert surface.faces.size > 0
    assert surface_options["scalars"] == "result_value"
    assert surface.point_data["result_value"].shape == (4,)
    assert surface_options["n_colors"] == 14
    assert surface_options["interpolate_before_map"] is True
    assert surface_options["show_scalar_bar"] is False
    assert mesh.n_lines == 4
    assert mesh_options["line_width"] == 1.0
    assert mesh_options["color"] == "#20242A"
    ActionService(model).add_member_selfweight("B1", -2.0, "Peso próprio")
    selfweight_actors, _positions, selfweight_labels = ActionRenderer().render(
        Plotter(), model, "Peso próprio",
    )
    assert selfweight_actors
    assert any(label.endswith("kN/m²") for label in selfweight_labels)


def test_plate_result_interpolation_modes_apply_element_node_and_macro_averaging():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)))
    model.add_plate(((1, 0, 0), (2, 0, 0), (2, 1, 0), (1, 1, 0)))
    nodes = {
        "FE::1": {"coordinates": (0, 0, 0)},
        "FE::2": {"coordinates": (1, 0, 0)},
        "FE::3": {"coordinates": (1, 1, 0)},
        "FE::4": {"coordinates": (0, 1, 0)},
        "FE::5": {"coordinates": (2, 0, 0)},
        "FE::6": {"coordinates": (2, 1, 0)},
    }
    def plate_result(names, nodal_values, center):
        return {
            "nodes": {name: nodes[name] for name in names},
            "elements": {"Q1": {
                "nodes": names,
                "moment": [center, 0.0, 0.0],
                "moment_nodal": [[value, 0.0, 0.0] for value in nodal_values],
            }},
        }

    result = AnalysisResult(0, "Combo", plate_results={
        "P1": plate_result(("FE::1", "FE::2", "FE::3", "FE::4"), (0, 0, 0, 0), 1),
        "P2": plate_result(("FE::2", "FE::5", "FE::6", "FE::3"), (10, 10, 10, 10), 11),
    })

    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    renderer = ResultRenderer()
    centers_plotter = Plotter()
    renderer.render_plate_contours(
        centers_plotter, model, result, "Fletor Y", display_mode="centros",
    )
    center_surface, center_options = centers_plotter.meshes[0]
    second_center_surface = centers_plotter.meshes[2][0]
    assert center_surface.cell_data["result_value"] == pytest.approx((1.0,))
    assert second_center_surface.cell_data["result_value"] == pytest.approx((11.0,))
    assert center_options["preference"] == "cell"
    assert center_options["interpolate_before_map"] is False

    raw_plotter = Plotter()
    renderer.render_plate_contours(
        raw_plotter, model, result, "Fletor Y", display_mode="nos_sem_media",
    )
    raw_surface, _options = raw_plotter.meshes[0]
    raw_second_surface = raw_plotter.meshes[2][0]
    assert len(raw_surface.points) == len(raw_second_surface.points) == 4
    assert raw_surface.point_data["result_value"] == pytest.approx((0, 0, 0, 0))
    assert raw_second_surface.point_data["result_value"] == pytest.approx((10, 10, 10, 10))

    averaged_plotter = Plotter()
    renderer.render_plate_contours(
        averaged_plotter, model, result, "Fletor Y", display_mode="nos_media",
    )
    averaged_first = averaged_plotter.meshes[0][0].point_data["result_value"]
    averaged_second = averaged_plotter.meshes[2][0].point_data["result_value"]
    assert averaged_first[1:3] == pytest.approx((5.0, 5.0))
    assert averaged_second[0] == pytest.approx(5.0)

    macro_plotter = Plotter()
    renderer.render_plate_contours(
        macro_plotter, model, result, "Fletor Y", display_mode="nos_media_macro",
    )
    macro_first = macro_plotter.meshes[0][0].point_data["result_value"]
    macro_second = macro_plotter.meshes[2][0].point_data["result_value"]
    assert macro_first == pytest.approx((0, 0, 0, 0))
    assert macro_second == pytest.approx((10, 10, 10, 10))


def test_result_color_map_uses_equal_width_discrete_bands():
    from osa.rendering.result_color_map import RESULT_COLOR_STOPS, result_colors

    colors = result_colors(np.asarray((0.0, 0.1, 0.12, 0.9, 1.0)), (0.0, 1.0))
    assert len(RESULT_COLOR_STOPS) == 14
    assert tuple(colors[0]) == tuple(int(RESULT_COLOR_STOPS[0][i:i + 2], 16) for i in (1, 3, 5))
    assert tuple(colors[-1]) == tuple(int(RESULT_COLOR_STOPS[-1][i:i + 2], 16) for i in (1, 3, 5))
    assert np.array_equal(colors[1], colors[2])
    assert not np.array_equal(colors[2], colors[3])


def test_plate_deformation_color_range_uses_plate_mesh_displacements():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)))
    coordinates = ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))
    node_names = ("FE::1", "FE::2", "FE::3", "FE::4")
    result = AnalysisResult(
        0, "Combo",
        node_results={"N1": {"DX": 0.0, "DY": 0.0, "DZ": -0.03}},
        member_results={"B1": {"samples": ({
            "deflection_x": 0.0, "deflection_y": 0.0, "deflection_z": -0.30,
        },)}},
        plate_results={"P1": {
            "nodes": {
                name: {
                    "coordinates": point, "DX": 0.0, "DY": 0.0,
                    "DZ": -index * 0.01,
                }
                for index, (name, point) in enumerate(zip(node_names, coordinates))
            },
            "elements": {"Q1": {"nodes": node_names}},
        }},
    )

    assert ResultRenderer().result_range(result, "Deformação Z") == pytest.approx((-0.03, 0.0))
    assert ResultRenderer().result_range(result, "Deformação XYZ") == pytest.approx((0.0, 0.03))

    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    plotter = Plotter()
    ResultRenderer().render_plate_contours(plotter, model, result, "Deformação XYZ")
    surface, options = plotter.meshes[0]
    assert surface.point_data["result_value"] == pytest.approx((0.0, 0.01, 0.02, 0.03))
    assert options["clim"] == pytest.approx((0.0, 0.03))

    import pyvista as pv

    real_plotter = pv.Plotter(off_screen=True)
    try:
        actors, _positions, _labels = ResultRenderer().render_plate_contours(
            real_plotter, model, result, "Deformação XYZ",
        )
        lookup_table = actors[0].mapper.lookup_table
        mapped_colors = [lookup_table.map_value(value) for value in (0.0, 0.015, 0.03)]
        assert len({tuple(color) for color in mapped_colors}) == 3
        assert not real_plotter.scalar_bars
    finally:
        real_plotter.close()


def test_plate_pressure_is_resolved_into_global_z_nodal_forces():
    class Target:
        def __init__(self):
            self.loads = []
            self._osa_plate_elements = {
                "P1": (("P1::Q1", ("N1", "N2", "N3", "N4"),
                        ((0, 0, 0), (2, 0, 0), (2, 3, 1), (0, 3, 1))),)
            }
        def add_node_load(self, *load):
            self.loads.append(load)

    target = Target()
    action = Action("Carga 1", "plate_surface_pressure", "P1", (5.0,), "Caso")

    LoadCaseBuilder._apply_action(target, action)

    assert len(target.loads) == 4
    assert all(load[1] == "FZ" and load[2] > 0 for load in target.loads)
    assert sum(load[2] for load in target.loads) == pytest.approx(5 * np.sqrt(40))
    assert all(load[3] == "Caso" for load in target.loads)


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


def test_support_reactions_point_to_restrained_nodes_and_skip_free_nodes():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    model.nodes = {
        "N1": Node("N1", 0, 0, 0, (True, True, False, False, False, False)),
        "N2": Node("N2", 2, 0, 0),
    }
    result = AnalysisResult(0, "Combinação", node_results={
        "N1": {"RXN_FX": 4.0, "RXN_FY": -2.0},
        "N2": {"RXN_FX": 100.0},
    })
    plotter = Plotter()

    actors, positions, labels = ResultRenderer().render(
        plotter, model, result, "Reações de apoio",
    )

    assert actors
    assert len(positions) == len(labels) == 2
    assert {options["color"] for _mesh, options in plotter.meshes} == {
        ResultRenderer.POSITIVE_COLOR, ResultRenderer.NEGATIVE_COLOR,
    }
    arrow_lengths = [float(np.linalg.norm(mesh.points[1] - mesh.points[0])) for mesh, _options in plotter.meshes]
    assert arrow_lengths == pytest.approx([0.5, 0.5])
    assert all(np.any(np.all(np.isclose(mesh.points, (0, 0, 0)), axis=1)) for mesh, _options in plotter.meshes)


def test_support_reaction_moments_render_as_circular_symbols():
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **options):
            self.meshes.append((mesh, options))
            return object()

    model = StructuralModel()
    model.nodes = {
        "N1": Node("N1", 0, 0, 0, (False, False, False, True, True, True)),
    }
    result = AnalysisResult(0, "Combinação", node_results={
        "N1": {"RXN_MX": 1.0, "RXN_MY": -2.0, "RXN_MZ": 3.0},
    })
    plotter = Plotter()

    actors, positions, labels = ResultRenderer().render(
        plotter, model, result, "Reações de apoio",
    )

    assert actors
    assert len(positions) == len(labels) == 3
    assert labels == ("1 kN·m", "-2 kN·m", "3 kN·m")
    np.testing.assert_allclose(
        positions,
        ((0.0, 0.3375, 0.0), (0.0, 0.0, 0.3375), (0.3375, 0.0, 0.0)),
    )
    assert len(plotter.meshes) == 2
    assert sorted(mesh.n_points for mesh, _options in plotter.meshes) == [28, 56]
    for mesh, _options in plotter.meshes:
        arc_points = mesh.points[:25]
        assert np.max(np.linalg.norm(arc_points, axis=1)) == pytest.approx(0.25)
    assert {options["color"] for _mesh, options in plotter.meshes} == {
        ResultRenderer.POSITIVE_COLOR, ResultRenderer.NEGATIVE_COLOR,
    }


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


def test_bending_labels_keep_both_relevant_member_end_values():
    positions, labels = ResultRenderer()._member_result_labels(
        np.asarray((-1.567, 2.273, -1.567)),
        np.asarray((-1.567, 2.273, -1.567)),
        np.asarray(((0, 0, 0), (1, 0, 0), (2, 0, 0))),
        np.asarray(((0, 0, -0.2), (1, 0, 0.3), (2, 0, -0.2))),
        np.asarray((1, 0, 0)), np.asarray((0, 0, 1)), "kN·m",
        include_endpoints=True,
    )

    assert labels == ["-1,567 kN·m", "2,273 kN·m", "-1,567 kN·m"]
    assert [position[0] for position in positions] == pytest.approx([0.2, 1.0, 1.8])


def test_result_labels_merge_equal_bending_values_at_a_shared_node():
    class Plotter:
        def add_mesh(self, *_args, **_options):
            return object()

    model = StructuralModel()
    model.nodes = {
        "N1": Node("N1", 0, 0, 0),
        "N2": Node("N2", 1, 0, 0),
        "N3": Node("N3", 2, 0, 0),
    }
    model.bars = {
        "B1": Bar("B1", "N1", "N2"),
        "B2": Bar("B2", "N2", "N3"),
    }
    result = AnalysisResult(0, "Combinação", member_results={
        name: {"samples": (
            {"x": 0, "moment_y": 1},
            {"x": 0.5, "moment_y": -2},
            {"x": 1, "moment_y": 1},
        )}
        for name in ("B1", "B2")
    })

    _actors, positions, labels = ResultRenderer().render(Plotter(), model, result, "Fletor Y")

    assert labels == ("-1 kN·m", "2 kN·m", "-1 kN·m", "2 kN·m", "-1 kN·m")
    assert positions[:, 0] == pytest.approx((0.1, 0.5, 1.0, 1.5, 1.9))


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
    assert positions[0][1] == pytest.approx(0.13)
    assert len(plotter.meshes) == 2
    assert np.max(plotter.meshes[0].points[:, 1]) == pytest.approx(0.11, abs=2e-6)

    line_plotter = Plotter()
    line_actors, _positions, _labels = ResultRenderer().render(
        line_plotter, model, result, "Deformação XYZ", solid_members_visible=False,
    )
    assert len(line_actors) == len(line_plotter.meshes) == 1
    assert line_plotter.options[0]["line_width"] == 1.25
    assert tuple(line_plotter.meshes[0].cell_data["rgb"][0]) == (110, 119, 129)

    colored_plotter = Plotter()
    ResultRenderer().render(
        colored_plotter, model, result, "Deformação XYZ",
        solid_members_visible=False, plate_diagrams_visible=True,
    )
    assert tuple(colored_plotter.meshes[0].cell_data["rgb"][0]) != (110, 119, 129)

    colored_solid_plotter = Plotter()
    ResultRenderer().render(
        colored_solid_plotter, model, result, "Deformação XYZ",
        solid_members_visible=True, plate_diagrams_visible=True,
    )
    assert tuple(colored_solid_plotter.meshes[0].cell_data["rgb"][0]) != (110, 119, 129)


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

    assert np.max(plotter_x.meshes[0].points[:, 0]) == pytest.approx(2.006)
    assert np.max(plotter_y.meshes[0].points[:, 1]) == pytest.approx(0.108, abs=2e-6)
    assert np.max(plotter_xyz.meshes[0].points[:, 0]) == pytest.approx(2.0064, abs=2e-6)
    assert np.max(plotter_xyz.meshes[0].points[:, 1]) == pytest.approx(0.108, abs=2e-6)


def test_deformed_member_sections_stay_normal_to_the_centerline_without_scaling():
    centerline = np.asarray(((0, 0, 0), (1, 0.5, 0), (2, 0, 0)), dtype=float)
    bases = ResultRenderer._deformed_section_bases(
        centerline, np.array((1.0, 0.0, 0.0)),
        np.array((0.0, 1.0, 0.0)), np.array((0.0, 0.0, 1.0)),
    )

    for tangent, local_y, local_z in bases:
        assert np.linalg.norm(tangent) == pytest.approx(1.0)
        assert np.linalg.norm(local_y) == pytest.approx(1.0)
        assert np.linalg.norm(local_z) == pytest.approx(1.0)
        assert np.dot(tangent, local_y) == pytest.approx(0.0, abs=1e-12)
        assert np.dot(tangent, local_z) == pytest.approx(0.0, abs=1e-12)
        assert np.dot(local_y, local_z) == pytest.approx(0.0, abs=1e-12)


def test_deformation_ignores_detailing_positioning_and_keeps_section_dimensions():
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
        solid_face_offsets=(0.2, 0.3), solid_section_offsets=(0.05, 0.07),
        solid_face_angles=(10.0, 5.0, 8.0, 4.0),
    )}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "deflection_x": 0, "deflection_y": 0, "deflection_z": 0},
            {"x": 2, "deflection_x": 0, "deflection_y": 0.01, "deflection_z": 0},
        )}
    })
    plotter = Plotter()

    ResultRenderer().render(plotter, model, result, "Deformação XYZ")

    assert len(plotter.meshes) == 2
    deformed_face = plotter.meshes[0]
    assert np.min(deformed_face.points[:, 0]) == pytest.approx(-0.0005, abs=2e-6)
    assert np.max(deformed_face.points[:, 0]) == pytest.approx(2.0005, abs=2e-6)

    assert np.ptp(deformed_face.points[:, 1]) == pytest.approx(0.21, abs=3e-6)
    assert np.ptp(deformed_face.points[:, 2]) == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("section", "geometry", "expected_longitudinal_edges"),
    (
        ("W Laminado", (("d", 200), ("bf", 100), ("tw", 6), ("tf", 8)), 16),
        ("Barra Circular", (("d", 100),), 0),
    ),
)
def test_deformation_solid_uses_the_model_edge_convention(
    section, geometry, expected_longitudinal_edges,
):
    class Plotter:
        def __init__(self):
            self.meshes = []

        def add_mesh(self, mesh, **_options):
            self.meshes.append(mesh)
            return object()

    model = StructuralModel()
    model.nodes = {"N1": Node("N1", 0, 0, 0), "N2": Node("N2", 2, 0, 0)}
    model.bars = {"B1": Bar(
        "B1", "N1", "N2", section=section, profile="Teste",
        section_geometry=geometry,
    )}
    result = AnalysisResult(0, "Combinação", member_results={
        "B1": {"samples": (
            {"x": 0, "deflection_y": 0, "deflection_z": 0},
            {"x": 1, "deflection_y": 0.01, "deflection_z": 0},
            {"x": 2, "deflection_y": 0.02, "deflection_z": 0},
        )}
    })
    plotter = Plotter()

    ResultRenderer().render(plotter, model, result, "Deformação XYZ")

    # The edge mesh has one closed profile line at each end plus the selected
    # longitudinal edges; circular profiles therefore keep only their caps.
    assert plotter.meshes[1].n_cells == 2 + expected_longitudinal_edges
