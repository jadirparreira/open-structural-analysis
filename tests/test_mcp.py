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

    application.create_node(0.0, 0.0, 0.0, name="N1")
    application.create_node(4.0, 0.0, 0.0, name="N2")
    result = application.create_member("N1", "N2", name="B1")

    assert result["member"] == {
        "name": "B1",
        "start_node": "N1",
        "end_node": "N2",
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
    }
    assert application.list_nodes()["nodes"][0]["name"] == "N1"
    assert application.list_members()["members"][0]["name"] == "B1"
    assert len(changes) == 3


def test_local_mcp_server_uses_loopback_streamable_http():
    _model, application = make_application()

    server = LocalMcpServer(application, port=9876)

    assert server.endpoint == "http://127.0.0.1:9876/mcp-opensa"
