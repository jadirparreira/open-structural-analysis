from osa.commands import CommandSession
from osa.mcp import LocalMcpServer, McpApplication
from osa.model import StructuralModel
from osa.services import ModelService


def make_application(on_model_changed=None):
    model = StructuralModel()
    model_service = ModelService(model)
    application = McpApplication(
        model,
        model_service,
        on_model_changed=on_model_changed,
    )
    return model, application


def test_mcp_application_switches_visual_sessions():
    _model, application = make_application()
    sessions = []
    active_session = ["Geometria"]
    application._get_session = lambda: active_session[0]

    assert application.get_session_state() == {
        "active_session": "Geometria",
        "available_sessions": ["Geometria", "Ações", "Análise"],
    }

    application._on_session_changed = lambda session: (sessions.append(session), active_session.__setitem__(0, session))
    selected = application.set_session("Análise")

    assert selected["active_session"] == "Análise"
    assert sessions == ["Análise"]
    assert application.get_session_state()["active_session"] == "Análise"


def test_mcp_application_reads_and_changes_the_open_model():
    model, application = make_application()
    changes = []
    application._on_model_changed = lambda: changes.append(model.revision)

    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    result = application.create_member("N1", "N2")

    assert result["member"] == {
        "name": "B1",
        "start_node": "N1",
        "end_node": "N2",
        "material": "Indefinido",
        "section": "",
        "profile": "",
        "geometry": {},
        "rotation": 0,
        "releases": [False] * 12,
        "rotation_flexibility_percent": [0] * 6,
        "solid_face_offsets_mm": [0.0, 0.0],
        "solid_section_offsets_mm": [0.0, 0.0],
        "color": "#6e7781",
    }
    assert application.get_project_summary() == {
        "revision": 3,
        "nodes": 2,
        "members": 1,
        "rigid_bars": 0,
        "actions": 0,
        "load_cases": 0,
        "load_combinations": 0,
        "analysis_results": 0,
        "materials": 3,
    }
    assert application.list_nodes()["nodes"][0]["name"] == "N1"
    assert application.list_members()["members"][0]["name"] == "B1"
    assert len(changes) == 3


def test_mcp_application_can_assign_concrete_properties_and_supports():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(8.0, 0.0, 0.0)
    application.create_member("N1", "N2")

    supports = application.set_node_supports("N1", True, True, True)
    result = application.set_member_properties(
        ["B1"],
        "Concreto Estrutural",
        "Retangular",
        {"b": 150.0, "h": 300.0},
    )

    assert supports["node"]["supports"] == [True, True, True, False, False, False]
    assert result["members"][0]["material"] == "Concreto Estrutural"
    assert result["members"][0]["section"] == "Retangular"
    assert result["members"][0]["profile"] == "R 150 x 300"
    assert result["members"][0]["geometry"] == {"b": 150.0, "h": 300.0}


def test_mcp_application_can_delete_members_and_nodes():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    application.create_member("N1", "N2")

    deleted_member = application.delete_member("B1")
    deleted_node = application.delete_node("N2")

    assert deleted_member["deleted_member"] == "B1"
    assert deleted_node["deleted_node"] == "N2"


def test_mcp_application_deletes_structural_elements_in_batches():
    model, application = make_application()
    for coordinates in ((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (8.0, 0.0, 0.0)):
        application.create_node(*coordinates)
    application.create_member("N1", "N2")
    application.create_member("N2", "N3")
    application.create_rigid_bar("N1", "N3")

    preview = application.delete_elements(nodes=["N1"], dry_run=True)
    assert preview["status"] == "preview"
    assert preview["blocked"] == [{"node": "N1", "members": ["B1"], "rigid_bars": ["N1-N3"]}]
    assert set(model.nodes) == {"N1", "N2", "N3"}

    blocked = application.delete_elements(nodes=["N1"])
    assert blocked["status"] == "blocked"
    assert set(model.bars) == {"B1", "B2"}

    deleted = application.delete_elements(nodes=["N1"], cascade=True)
    assert deleted["status"] == "deleted"
    assert deleted["cascade_added"] == {"members": ["B1"], "rigid_bars": ["N1-N3"]}
    assert deleted["nodes"] == ["N1"]
    assert set(model.nodes) == {"N2", "N3"}
    assert set(model.bars) == {"B2"}
    assert not model.rigid_bars

    final = application.delete_elements(nodes=["N2"], members=["B2", "B2"])
    assert final["status"] == "deleted"
    assert final["nodes"] == ["N2"]
    assert final["members"] == ["B2"]
    assert set(model.nodes) == {"N3"}
    assert not model.bars


def test_mcp_application_lists_catalog_materials_and_sections():
    _model, application = make_application()

    materials = application.list_materials()
    sections = application.list_sections("Concreto Estrutural")

    assert any(item["name"] == "Concreto Estrutural" for item in materials["materials"])
    assert sections["sections"] == [{
        "material_type": "Concreto",
        "families": [
            {"name": "Retangular", "profiles": []},
            {"name": "Circular", "profiles": []},
            {"name": "Tipo L", "profiles": []},
            {"name": "Tipo T", "profiles": []},
            {"name": "Tipo I", "profiles": []},
            {"name": "Tipo U", "profiles": []},
            {"name": "Tipo +", "profiles": []},
            {"name": "Retangular Vazado", "profiles": []},
            {"name": "Circular Vazado", "profiles": []},
        ],
    }]


def test_mcp_application_exposes_geometry_operations():
    model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    application.create_member("N1", "N2")
    application.set_member_rectangular_section(["B1"], 200.0, 400.0)

    axes = application.set_reference_axes({
        "X": [{"label": "A", "value": 0.0}, {"label": "B", "value": 4.0}],
        "Y": [],
        "Z": [{"label": "0", "value": 0.0}],
    })
    assert axes["axes"]["X"][-1] == {"label": "B", "value": 4.0}
    assert application.list_reference_axes()["axes"] == axes["axes"]

    split = application.split_member("B1", 2)
    assert split["created_nodes"] == ["N3"]
    assert split["created_members"] == ["B1", "B2"]
    assert model.bars["B2"].geometry_dict() == {"b": 200.0, "h": 400.0}

    reversed_member = application.reverse_member("B1")
    assert (reversed_member["member"]["start_node"], reversed_member["member"]["end_node"]) == (
        "N3", "N1",
    )
    application.reverse_member("B1")
    joined = application.join_members("B1", "B2")
    assert joined["member"]["name"] == "B1"
    assert set((joined["member"]["start_node"], joined["member"]["end_node"])) == {"N1", "N2"}
    assert "N3" not in model.nodes

    rigid = application.create_rigid_bar("N1", "N2")
    assert rigid["rigid_bar"] == {"name": "N1-N2", "start_node": "N1", "end_node": "N2"}
    assert application.list_rigid_bars()["rigid_bars"][0]["name"] == "N1-N2"

    application.create_node(0.0, 4.0, 0.0)
    application.create_node(4.0, 4.0, 0.0)
    application.create_member("N3", "N4")
    application.set_member_rectangular_section(["B2"], 100.0, 100.0)
    copied = application.copy_member_properties("B1", "B2", ["material", "section"])
    assert copied["member"]["geometry"] == {"b": 200.0, "h": 400.0}

    translated = application.copy_elements([], ["B1"], (0.0, 8.0, 0.0))
    assert translated["created_members"] == ["B3"]
    assert len(translated["created_nodes"]) == 2


def test_mcp_application_rejects_invalid_reference_axis_direction():
    _model, application = make_application()

    try:
        application.set_reference_axes({"W": [{"label": "1", "value": 0.0}]})
    except ValueError as error:
        assert "X, Y ou Z" in str(error)
    else:
        raise AssertionError("Uma direção de eixo inválida deveria ser rejeitada.")


def test_mcp_application_updates_any_combination_of_member_properties():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    application.create_member("N1", "N2")

    result = application.update_member_properties(
        ["B1"],
        material="Concreto Estrutural",
        section="Retangular",
        geometry={"b": 200.0, "h": 400.0},
        rotation=45,
        releases=[False, False, False, False, False, False, True, False, False, False, False, False],
        rotation_flexibility_percent=[10, 20, 30, 40, 50, 60],
        solid_face_offsets_mm=[25.0, -10.0],
        solid_section_offsets_mm=[15.0, -5.0],
        color="#ABCDEF",
    )

    member = result["members"][0]
    assert member["profile"] == "R 200 x 400"
    assert member["rotation"] == 45
    assert member["releases"][6] is True
    assert member["rotation_flexibility_percent"] == [10, 20, 30, 40, 50, 60]
    assert member["solid_face_offsets_mm"] == [25.0, -10.0]
    assert member["solid_section_offsets_mm"] == [15.0, -5.0]
    assert member["color"] == "#abcdef"


def test_mcp_application_rejects_invalid_member_property_shapes():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    application.create_member("N1", "N2")

    for kwargs in (
        {"rotation": True},
        {"releases": [False] * 11},
        {"rotation_flexibility_percent": [0] * 5},
        {"solid_face_offsets_mm": [0.0]},
        {"color": "blue"},
    ):
        try:
            application.update_member_properties(["B1"], **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"As propriedades inválidas deveriam ser rejeitadas: {kwargs}")


def test_mcp_application_updates_node_without_changing_its_name():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)

    result = application.update_node_properties(
        "N1",
        x=2.0,
        y=3.0,
        z=4.0,
        supports=[True, True, True, False, False, True],
        support_stiffness=[10.0, 20.0, 30.0, 1.0, 2.0, 3.0],
    )

    assert result["node"] == {
        "name": "N1",
        "x": 2.0,
        "y": 3.0,
        "z": 4.0,
        "supports": [True, True, True, False, False, True],
        "support_stiffness": [10.0, 20.0, 30.0, 1.0, 2.0, 3.0],
    }
    assert application.list_nodes()["nodes"][0]["support_stiffness"] == [
        10.0, 20.0, 30.0, 1.0, 2.0, 3.0,
    ]


def test_mcp_application_rejects_partial_node_coordinates_and_invalid_stiffness():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)

    for kwargs in (
        {"x": 1.0},
        {"supports": [False] * 5},
        {"support_stiffness": [-1.0] * 6},
    ):
        try:
            application.update_node_properties("N1", **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"As propriedades inválidas deveriam ser rejeitadas: {kwargs}")


def test_mcp_application_manages_node_and_member_actions():
    _model, application = make_application()
    application.create_node(0.0, 0.0, 0.0)
    application.create_node(4.0, 0.0, 0.0)
    application.create_member("N1", "N2")
    application.set_member_rectangular_section(["B1"], 200.0, 300.0)

    node_force = application.add_node_force("N1", "X", 10.0, "Ação permanente")
    node_moment = application.add_node_moment("N1", "Z", 5.0, "Ação permanente")
    member_load = application.add_member_distributed_load(
        "B1", "Z", -2.0, -4.0, "Ação permanente", "global",
    )
    member_moment = application.add_member_moment("B1", "Y", 3.0, "Ação permanente")

    assert node_force["action"]["kind"] == "node_force_X"
    assert node_moment["action"]["kind"] == "node_moment_Z"
    assert member_load["action"]["components"] == [-2.0, -4.0]
    assert member_moment["action"]["kind"] == "member_moment_Y"
    assert len(application.list_actions("Ação permanente")["actions"]) == 4

    updated_member_load = application.update_applied_load(
        member_load["action"]["name"],
        direction="Y",
        initial=-3.0,
        final=-5.0,
    )
    assert updated_member_load["action"] == {
        "name": member_load["action"]["name"],
        "kind": "member_distributed_force_Y",
        "target": "B1",
        "components": [-3.0, -5.0],
        "load_case": "Ação permanente",
    }
    assert len(application.list_actions("Ação permanente", "B1")["actions"]) == 2

    deleted = application.delete_action(node_force["action"]["name"])
    assert deleted["deleted_action"]["target"] == "N1"
    cleared = application.clear_actions(target="B1", load_case="Ação permanente")
    assert len(cleared["deleted_actions"]) == 2

    selfweight = application.apply_selfweight("Peso próprio")
    assert selfweight["actions"][0]["kind"] == "member_distributed_force_selfweight_Z"
    assert application.list_actions("Peso próprio")["actions"]
    application.remove_selfweight("Peso próprio")
    assert not application.list_actions("Peso próprio")["actions"]


def test_mcp_application_manages_action_groups_and_active_action():
    _model, application = make_application()
    active_actions = []
    application._on_active_action_changed = active_actions.append

    created = application.create_action_group(
        "Grupo IA",
        [{"name": "Carga de uso", "abbreviation": "CU"}],
    )
    assert created["group"]["custom"] is True
    application.set_action_group("Grupo IA")
    selected = application.set_active_action("Carga de uso")
    assert selected["active_action"] == "Carga de uso"
    assert active_actions == ["Carga de uso"]

    updated = application.update_action_group(
        "Grupo IA",
        "Grupo IA 2",
        [{"name": "Vento", "abbreviation": "V0"}],
    )
    assert updated["group"]["name"] == "Grupo IA 2"
    deleted = application.delete_action_group("Grupo IA 2")
    assert deleted["deleted_group"] == "Grupo IA 2"


def test_mcp_application_manages_load_combinations():
    _model, application = make_application()

    created = application.create_load_combination(
        "ELU IA",
        factors={"PP": 1.25, "AP": 1.35, "AV": 1.50},
        factors_2={"PP": 1.0, "AP": 1.0, "AV": 1.0},
        factors_3={"PP": 1.0, "AP": 1.0, "AV": 1.0},
        active_actions=["PP", "AP", "AV"],
        limit_state="ELU",
    )
    assert created["combination"]["limit_state"] == "ELU"
    assert created["combination"]["factors"]["AV"] == 1.50

    updated = application.update_load_combination(
        "ELU IA",
        name="ELU IA 2",
        active_actions=["PP", "AV"],
    )
    assert updated["combination"]["name"] == "ELU IA 2"
    assert updated["combination"]["factors"]["AP"] == 1.35
    assert updated["combination"]["active_actions"] == ["PP", "AV"]

    listed = application.list_load_combinations()
    assert [item["name"] for item in listed["combinations"]] == ["ELU IA 2"]
    deleted = application.delete_load_combination("ELU IA 2")
    assert deleted["deleted_combination"] == "ELU IA 2"
    assert application.list_load_combinations()["combinations"] == []


def test_mcp_application_runs_analysis_and_reads_results():
    model = StructuralModel()
    CommandSession(ModelService(model)).submit("mezanino")
    view = {
        "selected_combination": None,
        "selected_diagram": "Normal",
        "result_diagrams_visible": True,
    }
    application = McpApplication(
        model,
        ModelService(model),
        on_analysis_view_changed=lambda combination, diagram: view.update(
            {"selected_combination": combination or None, "selected_diagram": diagram}
        ),
        get_analysis_view_state=lambda: dict(view),
        on_analysis_diagrams_changed=lambda visible: view.update(
            {"result_diagrams_visible": visible}
        ),
    )

    processed = application.run_analysis(["Combinação 01"])
    assert processed["status"] == "completed"
    assert processed["processed_combinations"] == ["Combinação 01"]

    state = application.get_analysis_state()
    assert state["ready"] is True
    assert state["result_combinations"] == ["Combinação 01"]
    assert application.list_analysis_results()["results"][0]["members"] > 0

    nodes = application.get_node_analysis_results("Combinação 01", ["N1"])
    assert nodes["nodes"][0]["name"] == "N1"
    members = application.get_member_analysis_results("Combinação 01", ["B1"], include_samples=True)
    assert len(members["members"][0]["samples"]) == 21
    reactions = application.get_support_reactions("Combinação 01")
    assert reactions["reactions"]

    selected = application.set_analysis_view("Combinação 01", "Fletor Z")
    assert selected["selected_combination"] == "Combinação 01"
    assert selected["selected_diagram"] == "Fletor Z"
    hidden = application.set_analysis_diagrams_visible(False)
    assert hidden["result_diagrams_visible"] is False


def test_mcp_application_controls_action_visibility_options():
    model = StructuralModel()
    view = {
        "node_forces_visible": True,
        "node_moments_visible": True,
        "member_forces_visible": True,
        "member_moments_visible": True,
    }
    application = McpApplication(
        model,
        ModelService(model),
        on_view_changed=lambda option, visible: view.update({option: visible}),
        get_view_state=lambda: dict(view),
    )

    result = application.set_view_options({"node_forces_visible": False})

    assert result["view"]["node_forces_visible"] is False


def test_mcp_application_updates_and_deletes_rigid_bars_and_member_endpoints():
    model, application = make_application()
    for coordinates in ((0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (8.0, 0.0, 0.0)):
        application.create_node(*coordinates)
    application.create_member("N1", "N2")
    changed_member = application.update_member_endpoints("B1", "N2", "N3")
    assert changed_member["member"]["start_node"] == "N2"
    assert changed_member["member"]["end_node"] == "N3"

    application.create_rigid_bar("N1", "N2")
    changed_rigid = application.update_rigid_bar_endpoints("N1-N2", "N1", "N3")
    assert changed_rigid["rigid_bar"]["name"] == "N1-N3"
    deleted = application.delete_rigid_bar("N1-N3")
    assert deleted["deleted_rigid_bar"] == "N1-N3"
    assert not model.rigid_bars


def test_mcp_application_controls_geometry_view_options():
    model = StructuralModel()
    view = {
        "grid_visible": True,
        "reference_axes_visible": True,
        "node_labels_visible": True,
        "member_labels_visible": True,
        "local_axes_visible": True,
        "nodes_visible": True,
        "solid_members_visible": True,
        "member_releases_visible": True,
        "semirigid_links_visible": True,
        "node_supports_visible": True,
        "snap_enabled": True,
    }
    changes = []
    application = McpApplication(
        model,
        ModelService(model),
        on_view_changed=lambda option, visible: (changes.append((option, visible)), view.update({option: visible})),
        get_view_state=lambda: dict(view),
    )

    result = application.set_view_options({"grid_visible": False, "snap_enabled": False})

    assert result["view"]["grid_visible"] is False
    assert result["view"]["snap_enabled"] is False
    assert changes == [("grid_visible", False), ("snap_enabled", False)]
    assert application.get_view_options()["view"]["grid_visible"] is False


def test_local_mcp_server_uses_loopback_streamable_http():
    _model, application = make_application()

    server = LocalMcpServer(application, port=9876)

    assert server.endpoint == "http://127.0.0.1:9876/mcp-opensa"
