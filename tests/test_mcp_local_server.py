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
    assert len(server.server._tool_manager.list_tools()) == 70
