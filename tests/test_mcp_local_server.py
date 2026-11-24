"""Thread isolation and restart behavior for the local MCP server."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from osa.mcp import LocalMcpServer, McpApplication
from osa.model import StructuralModel
from osa.services import ModelService


def test_local_mcp_cannot_bind_to_a_network_interface():
    model = StructuralModel()
    with pytest.raises(ValueError, match="127.0.0.1"):
        LocalMcpServer(McpApplication(model, ModelService(model)), host="0.0.0.0")
    server = LocalMcpServer(McpApplication(model, ModelService(model)))
    assert server.server.settings.transport_security.enable_dns_rebinding_protection


def test_mcp_qt_dispatcher_in_isolated_process():
    script = Path(__file__).with_name("mcp_qt_dispatcher_smoke.py")
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_restarting_local_mcp_recreates_the_single_use_sdk_session(monkeypatch):
    model = StructuralModel()
    server = LocalMcpServer(McpApplication(model, ModelService(model)))
    monkeypatch.setattr(server, "_run", lambda: None)
    first_sdk_server = server.server

    server.start()
    server._thread.join(timeout=2)
    assert not server._thread.is_alive()
    server.start()
    server._thread.join(timeout=2)

    assert server.server is not first_sdk_server
    names = {tool.name for tool in server.server._tool_manager.list_tools()}
    assert {"create_plate", "run_verification", "get_capabilities", "set_analysis_view"} <= names
    assert len(names) == len(server.server._tool_manager.list_tools())


def test_uvicorn_configuration_works_without_console_streams(monkeypatch):
    import uvicorn
    model = StructuralModel()
    server = LocalMcpServer(McpApplication(model, ModelService(model)))
    captured = []

    class NoNetworkServer:
        def __init__(self, config):
            captured.append(config)
            config.load()  # Resolves protocol modules and logging without opening sockets.
            self.started = True
            self.should_exit = False
        def run(self):
            pass

    monkeypatch.setattr(uvicorn, 'Server', NoNetworkServer)
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    server._run()
    assert server.last_error is None
    assert captured[0].log_config is None
    assert captured[0].http == 'h11'
    assert captured[0].loop == 'asyncio'
    assert captured[0].ws == 'none'


def test_bind_system_exit_is_reported_in_settings(monkeypatch):
    import uvicorn
    model = StructuralModel()
    server = LocalMcpServer(McpApplication(model, ModelService(model)))
    class CannotBind:
        def __init__(self, config):
            self.started = False
        def run(self):
            raise SystemExit(1)
    monkeypatch.setattr(uvicorn, 'Server', CannotBind)
    server._run()
    assert 'SystemExit' in server.last_error
    assert not server.is_running
