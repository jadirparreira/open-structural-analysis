"""Ponte stdio e plugin do Claude Code para o MCP local."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from osa.integrations import claude_code
from osa.integrations.claude_code import MARKETPLACE_NAME, PLUGIN_NAME, ClaudeCodeIntegration
from osa.mcp import LocalMcpServer, McpApplication, stdio_bridge
from osa.model import StructuralModel
from osa.services import ModelService

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def running_server():
    model = StructuralModel()
    ModelService(model).create_node(0.0, 0.0, 0.0)
    server = LocalMcpServer(McpApplication(model, ModelService(model)), port=_free_port())
    server.start()
    deadline = time.monotonic() + 10
    while not server.is_running and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.is_running, server.last_error
    yield server
    server.stop()


def test_bridge_lists_the_same_tools_and_instructions_as_the_embedded_server():
    tools, instructions = stdio_bridge.local_catalog()
    model = StructuralModel()
    embedded = LocalMcpServer(McpApplication(model, ModelService(model)))
    expected = {tool.name for tool in embedded.server._tool_manager.list_tools()}

    assert {tool.name for tool in tools} == expected
    assert instructions == embedded.server.instructions
    summary = next(tool for tool in tools if tool.name == "get_project_summary")
    assert summary.annotations.readOnlyHint is True


def test_bridge_explains_how_to_enable_the_server_when_opensa_is_closed():
    result = anyio.run(stdio_bridge.forward_call, f"http://127.0.0.1:{_free_port()}/mcp-opensa", "list_nodes", {})

    assert result.isError is True
    assert "Servidor MCP" in result.content[0].text


def test_bridge_forwards_calls_and_structured_results_to_the_open_project(running_server):
    result = anyio.run(stdio_bridge.forward_call, running_server.endpoint, "get_project_summary", {})

    assert result.isError is False
    assert result.structuredContent["nodes"] == 1


def test_stdio_process_serves_tools_to_a_real_mcp_client(running_server):
    async def session_round_trip():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "osa", "--mcp-stdio", "--mcp-endpoint", running_server.endpoint],
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            initialized = await session.initialize()
            tools = (await session.list_tools()).tools
            result = await session.call_tool("list_nodes", {})
            return initialized.serverInfo.name, len(tools), result

    name, tool_count, result = anyio.run(session_round_trip)

    assert name == "mcp-opensa"
    assert tool_count > 90
    assert result.isError is False and "N1" in json.dumps(result.structuredContent)


def test_main_routes_mcp_stdio_without_starting_the_interface(monkeypatch):
    from osa import main as entry

    monkeypatch.setattr(sys, "argv", ["open-structural-analysis", "--mcp-stdio"])
    monkeypatch.setattr(stdio_bridge, "main", lambda: 7)
    with pytest.raises(SystemExit) as raised:
        entry.main()
    assert raised.value.code == 7


def test_claude_plugin_and_marketplace_manifests_are_valid_json():
    plugin = json.loads((ROOT / "plugins" / PLUGIN_NAME / ".claude-plugin" / "plugin.json").read_text("utf-8"))
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text("utf-8"))

    assert plugin["name"] == PLUGIN_NAME
    assert marketplace["plugins"][0]["source"] == f"./plugins/{PLUGIN_NAME}"


def test_integration_writes_a_local_plugin_that_starts_this_installation_bridge(tmp_path):
    calls = []
    integration = ClaudeCodeIntegration(
        marketplace_root=tmp_path / "marketplace",
        command=("C:/OpenSA/open-structural-analysis.exe", ["--mcp-stdio"]),
        cli="claude",
        runner=lambda arguments: calls.append(list(arguments)) or 0,
    )

    assert integration.ensure_installed(background=False) is True

    plugin = tmp_path / "marketplace" / PLUGIN_NAME
    server = json.loads((plugin / ".mcp.json").read_text("utf-8"))["mcpServers"]["mcp-opensa"]
    assert server["command"] == "C:/OpenSA/open-structural-analysis.exe"
    assert server["args"] == ["--mcp-stdio"]
    assert server["env"] == {"PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "1"}
    assert (plugin / ".claude-plugin" / "plugin.json").is_file()
    assert not (plugin / ".codex-plugin").exists()
    marketplace = json.loads((tmp_path / "marketplace" / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    assert marketplace["name"] == MARKETPLACE_NAME
    assert [call[1:4] for call in calls] == [
        ["plugin", "marketplace", "add"],
        ["plugin", "marketplace", "update"],
        ["plugin", "install", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"],
        ["plugin", "update", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"],
    ]
    assert integration.is_current()

    calls.clear()
    assert integration.ensure_installed(background=False) is True
    assert calls == []


def test_integration_reinstalls_when_the_executable_moves(tmp_path):
    calls = []
    options = {"marketplace_root": tmp_path, "cli": "claude", "runner": lambda arguments: calls.append(arguments) or 0}
    ClaudeCodeIntegration(command=("C:/antigo/osa.exe", ["--mcp-stdio"]), **options).ensure_installed(background=False)
    calls.clear()

    ClaudeCodeIntegration(command=("C:/novo/osa.exe", ["--mcp-stdio"]), **options).ensure_installed(background=False)

    assert calls, "o plugin deve ser atualizado quando o caminho do executável muda"


def test_integration_does_nothing_without_claude_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "find_claude_cli", lambda: None)
    integration = ClaudeCodeIntegration(marketplace_root=tmp_path / "marketplace", runner=lambda _arguments: 0)

    assert integration.ensure_installed(background=False) is False
    assert not (tmp_path / "marketplace").exists()


def test_bridge_command_uses_the_appimage_file_instead_of_its_mount(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/home/user/OpenSA.AppImage")
    assert claude_code.bridge_command() == ("/home/user/OpenSA.AppImage", ["--mcp-stdio"])
    monkeypatch.delenv("APPIMAGE")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert claude_code.bridge_command() == (sys.executable, ["--mcp-stdio"])
