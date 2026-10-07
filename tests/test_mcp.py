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


def test_local_mcp_server_uses_loopback_streamable_http():
    _model, application = make_application()

    server = LocalMcpServer(application, port=9876)

    assert server.endpoint == "http://127.0.0.1:9876/mcp-opensa"
