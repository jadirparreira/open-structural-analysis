"""End-to-end release diagnostic; uses a temporary model and never edits user settings."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path


def run_self_test(report_path: str) -> int:
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)), "executable": sys.executable}
    server = None
    standard_streams = sys.stdout, sys.stderr
    # Exercise Windows windowed semantics on Linux as well.
    sys.stdout = sys.stderr = None
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        from osa.integrations.mcp_local import LocalMcpIntegration
        from osa.model import StructuralModel
        from osa.services import ModelService

        from .application import McpApplication
        from .server import LocalMcpServer

        # Use a disposable registration destination and an arbitrary working directory.
        with tempfile.TemporaryDirectory(prefix="opensa-mcp-check-") as temp:
            root = Path(temp)
            integration = LocalMcpIntegration(
                config_path=root / "config.toml", marketplace_root=root / "home" / ".agents" / "plugins"
            )
            integration.ensure_installed()
            if not integration.is_installed():
                raise RuntimeError(f"Plugin resources missing from bundle: {integration.plugin_root}")
            report["plugin_resources"] = True
            model = StructuralModel()
            application = McpApplication(model, ModelService(model))
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = LocalMcpServer(application, port=port)
            server.start()
            deadline = time.monotonic() + 15
            while not server.is_running and server.last_error is None and time.monotonic() < deadline:
                time.sleep(0.02)
            if not server.is_running:
                raise RuntimeError(server.last_error or "MCP startup timed out")

            async def check_client():
                async with (
                    streamable_http_client(server.endpoint) as (read, write, _session_id),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    names = {tool.name for tool in tools}
                    required = {
                        "get_capabilities",
                        "create_node",
                        "list_nodes",
                        "list_plates",
                        "set_analysis_view",
                        "run_verification",
                    }
                    if not required <= names:
                        raise RuntimeError(f"Missing tools: {required - names}")
                    for name, args in (
                        ("get_capabilities", {}),
                        ("create_node", {"x": 1.0, "y": 2.0, "z": 3.0}),
                        ("list_nodes", {}),
                    ):
                        result = await session.call_tool(name, args)
                        if result.isError:
                            raise RuntimeError(f"{name}: {result.content}")
                    if len(model.nodes) != 1:
                        raise RuntimeError("HTTP write did not reach the live model")
                    return len(names)

            report["tool_count"] = asyncio.run(check_client())
            report["ok"] = True
    except BaseException as error:  # noqa: BLE001 - The report must survive GUI/no-console failures, including bind SystemExit.
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
    finally:
        sys.stdout, sys.stderr = standard_streams
        if server is not None:
            server.stop()
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
