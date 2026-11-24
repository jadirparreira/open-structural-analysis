"""MCP v5 coverage: live domain operations, schemas and desktop display controls."""

import asyncio
import copy

import pytest

from osa.domain import AnalysisResult
from osa.mcp import LocalMcpServer, McpApplication
from osa.model import StructuralModel
from osa.services import ModelService


@pytest.fixture
def api():
    model = StructuralModel()
    return McpApplication(model, ModelService(model))


def test_capabilities_match_the_registered_tools_and_schemas(api):
    server = LocalMcpServer(api)
    tools = {tool.name: tool for tool in server.server._tool_manager.list_tools()}
    assert set(api.get_capabilities()["tools"]) == set(tools)
    schema = tools["create_plate"].parameters
    assert schema["properties"]["contour"]["type"] == "array"
    assert "self" not in schema["properties"] and "_name" not in schema["properties"]
    assert tools["delete_plate"].annotations.destructiveHint
    assert tools["get_verification_results"].annotations.readOnlyHint
    assert "result_kind" in tools["set_analysis_view"].parameters["properties"]
    assert api.list_profiles("Aço", "W Laminado")["profiles"]
    assert "Detalhamento" in api.get_capabilities()["sessions"]


def test_plate_lifecycle_and_shared_vertices(api):
    plate = api.create_plate([[0, 0, 0], [4, 0, 0], [4, 3, 0], [0, 3, 0]], thickness_mm=120)["plate"]
    assert len(plate["vertex_nodes"]) == 4
    assert api.get_project_summary()["plates"] == 1
    api.set_element_display_name("plate", "P1", "Laje")
    api.update_plate_properties(
        "P1",
        restrictions=[False, False, True],
        restriction_stiffness=[0, 0, 1000],
        restriction_directions=["=", "=", "-"],
    )
    assert api.list_plates()["plates"][0]["display_name"] == "Laje"
    first_node = plate["vertex_nodes"][0]
    moved = api.move_elements([["plate", "P1"], ["node", first_node]], [1, 0, 0])
    assert len(moved["moved_nodes"]) == 4
    assert api.model.nodes[first_node].x == 1
    # Split and join exercise the same topology operations used by the GUI.
    split = api.split_plate("P1", [3, 0, 0], [3, 3, 0])["plates"]
    assert len(split) == 2
    joined = api.join_plates(split[0]["name"], split[1]["name"])["plate"]
    api.delete_plate(joined["name"])
    assert not api.model.plates


def test_plate_loads_validate_reference_and_preserve_selfweight_rules(api):
    api.create_plate([[0, 0, 0], [4, 0, 0], [4, 3, 0], [0, 3, 0]])
    api.action_service.ensure_default_combinations()
    case = api.action_service.selected_group().actions[0].name
    action = api.add_plate_pressure_profiles("P1", case, -1, -2, 0, 0)["action"]
    assert action["components"] == [-1, -2, 0, 0]
    action = api.update_applied_load(action["name"], load_case=case)["action"]
    assert action["components"] == [-1, -2, 0, 0]
    action = api.update_applied_load(action["name"], pressure_profiles=[-2, -4, 0, 0])["action"]
    assert action["components"] == [-2, -4, 0, 0]
    action = api.add_plate_edge_load("P1", 0, case, "force", "Z", -2, -3)["action"]
    assert action["components"] == [-2, -3]
    action = api.update_applied_load(action["name"], edge_index=1, initial=-4, final=-5)["action"]
    assert action["kind"].endswith(":1") and action["components"] == [-4, -5]
    before = copy.deepcopy(api.model.actions)
    with pytest.raises(ValueError):
        api.add_plate_edge_load("P1", 0, case, "moment", "Z", 2, reference="global")
    assert api.model.actions == before


def test_components_support_directions_and_detailing_properties(api):
    api.create_node(0, 0, 0)
    api.create_node(1, 0, 0)
    api.create_member("N1", "N2")
    revision = api.model.revision
    api.set_node_component("N1", "base_plate", {"largura_mm": 400})
    assert api.model.revision == revision  # visual-only component
    assert api.list_node_components()["assignments"]["N1"]["component_id"] == "base_plate"
    assert api.list_nodes()["nodes"][0]["component"]["component_id"] == "base_plate"
    api.set_node_component("N1", None)
    api.update_node_properties("N1", support_directions=["=", "=", "=", "=", "-", "+"])
    assert api.model.nodes["N1"].support_directions[-2:] == ("-", "+")
    api.update_member_properties(["B1"], section_mirrored=True, solid_face_angles_deg=[1, 2, 3, 4])
    assert api.list_members()["members"][0]["solid_face_angles_deg"] == [1, 2, 3, 4]
    api.set_member_end_cuts(
        "B1", [{"identifier": "cut1", "point": [1, 0, 0], "normal": [1, 0, 0], "reference_label": "N2"}]
    )
    assert len(api.model.bars["B1"].detail_end_cuts) == 1
    with pytest.raises(ValueError, match="snap_enabled"):
        api.set_view_options({"snap_enabled": False})


def test_analysis_selection_disambiguates_shared_labels_and_preserves_combination(api):
    state = {}
    api._on_analysis_display_changed = state.update
    api.model.analysis_results = [AnalysisResult(api.model.revision, "Combo")]
    selected = api.set_analysis_view(
        "Combo", "Fletor Y (My)", result_kind="plate", deformation_scale=20, plate_result_display_mode="nos_sem_media"
    )
    assert state["selected_diagram"] == "Fletor Y (My)"
    assert selected["result_kind"] == "plate"
    selected = api.set_analysis_view(diagram="Fletor Y (My)", result_kind="bar", diagram_scale=0.5)
    assert selected["selected_combination"] == "Combo"
    assert selected["selected_diagram"] == "Fletor Y"
    before = dict(state)
    with pytest.raises(ValueError):
        api.set_analysis_view(diagram="Normal", result_kind="plate")
    with pytest.raises(ValueError):
        api.set_analysis_view(deformation_scale=7)
    assert state == before


def test_verification_uses_the_domain_runner_and_rejects_stale_publication(api):
    from osa.verification.runner import verify_model

    api.create_node(0, 0, 0)
    api.create_node(0, 0, 0.5)
    api.create_member("N1", "N2", material="ASTM A36", section="Barra Retangular", geometry={"b": 10, "h": 20})
    api.update_node_properties("N1", supports=[True] * 6)
    api.update_node_properties("N2", supports=[True] * 6)
    api.model.analysis_results = [
        AnalysisResult(
            api.model.revision,
            "ELU",
            member_results={
                "B1": {
                    "samples": [{"x": 0, "axial": 10, "moment_y": 0.1, "moment_z": 0.1, "shear_y": 1, "shear_z": 1}]
                },
            },
        )
    ]
    expected = verify_model(copy.deepcopy(api.model))
    result = api.run_verification()
    assert result["results"] == expected["results"]
    assert api.get_verification_results()["results"] == expected["results"]
    signature, _snapshot, names = api._prepare_verification(None)
    api.set_member_calculation_properties("B1", {"Lb": 0.3})
    assert api.model.analysis_results
    with pytest.raises(ValueError, match="alterados"):
        api._publish_verification(signature, expected, names)
    with pytest.raises(ValueError):
        api.set_member_calculation_properties("B1", {"Lb": 0.4, "Ct": 2})
    assert dict(api.model.bars["B1"].calculation_property_overrides)["Lb"] == 0.3


def test_new_tools_are_callable_through_fastmcp(api):
    server = LocalMcpServer(api)

    async def run():
        result = await server.server.call_tool(
            "create_plate",
            {
                "contour": [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]],
                "thickness_mm": 110,
            },
        )
        return result

    asyncio.run(run())
    assert api.model.plates["P1"].thickness_mm == 110


def test_copy_properties_supports_bar_categories_and_detailing(api):
    for x in (0, 1, 2):
        api.create_node(x, 0, 0)
    api.create_member('N1', 'N2')
    api.create_member('N2', 'N3')
    api.update_member_properties(['B1'], rotation=30)
    api.copy_element_properties('bar', 'B1', 'B2', ['rotation'])
    assert api.model.bars['B2'].rotation == 30
    api.set_node_component('N1', 'base_plate')
    api.copy_element_properties('node', 'N1', 'N3', ['component'])
    assert api.model.nodes['N3'].component == api.model.nodes['N1'].component
    api.set_detail_subtractions('bar', 'B1', [['bar', 'B2']])
    assert api.list_members()['members'][0]['detail_subtractions']
    api.set_detail_subtractions('bar', 'B1', [])
    api.group_verification_elements(['B1', 'B2'])
    api.ungroup_verification_elements('B1')
    assert not api.get_verification_state()['groups']
