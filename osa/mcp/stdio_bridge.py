"""Ponte MCP por ``stdio`` para o servidor HTTP do OpenSA aberto.

Clientes como Claude Code e Claude Desktop iniciam servidores MCP como
processos ``stdio`` e listam as ferramentas uma única vez, ao abrir a sessão.
Conectados direto ao endpoint HTTP, eles ficam sem ferramentas quando a sessão
começa antes de o OpenSA ser aberto. Esta ponte resolve isso:

- lista sempre as mesmas ferramentas do servidor integrado (catálogo local,
  sem depender do programa aberto);
- encaminha cada chamada ao endpoint ``http://127.0.0.1:8765/mcp-opensa``;
- com o OpenSA fechado ou o servidor desativado, devolve um erro explicando
  como ativá-lo, em vez de derrubar a conexão.

Uso: ``open-structural-analysis --mcp-stdio [--mcp-endpoint URL]``.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpx
from mcp import ClientSession, types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

DEFAULT_ENDPOINT = "http://127.0.0.1:8765/mcp-opensa"
OFFLINE_MESSAGE = (
    "O Open Structural Analysis não está aberto ou o Servidor MCP está desativado. "
    "Abra o OpenSA, ative Arquivo > Configurações > MCP > Servidor MCP e repita o pedido."
)

logger = logging.getLogger(__name__)


def local_catalog() -> tuple[list[types.Tool], str | None]:
    """Ferramentas e instruções do servidor integrado, sem abrir a interface."""
    from .server import LocalMcpServer

    # O registro das ferramentas não usa a aplicação; ela só é chamada ao executar.
    local = LocalMcpServer(application=None)  # type: ignore[arg-type]
    tools = anyio.run(local.server.list_tools)
    return tools, local.server.instructions


def endpoint_is_listening(endpoint: str, timeout: float = 0.3) -> bool:
    parts = urlsplit(endpoint)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", parts.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


@asynccontextmanager
async def _http_streams(endpoint: str):
    """Cliente Streamable HTTP; análises longas podem levar vários minutos."""
    try:
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:  # SDK anterior à função nova.
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(endpoint, timeout=30, sse_read_timeout=3600) as streams:
            yield streams
        return
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=3600.0)) as client,
        streamable_http_client(endpoint, http_client=client) as streams,
    ):
        yield streams


def _error_result(message: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=message)], isError=True)


async def forward_call(endpoint: str, name: str, arguments: dict[str, Any] | None) -> types.CallToolResult:
    """Executa a ferramenta no OpenSA aberto e devolve o resultado sem alterações."""
    if not endpoint_is_listening(endpoint):
        return _error_result(OFFLINE_MESSAGE)
    try:
        # O servidor do OpenSA é stateless: uma sessão curta por chamada
        # continua funcionando depois que o programa é fechado e reaberto.
        async with _http_streams(endpoint) as (read, write, _), ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(name, arguments or {})
    except Exception as error:
        logger.debug("Falha ao encaminhar %s para %s", name, endpoint, exc_info=True)
        if not endpoint_is_listening(endpoint):
            return _error_result(OFFLINE_MESSAGE)
        return _error_result(f"Falha ao comunicar com o OpenSA em {endpoint}: {error}")


def build_server(endpoint: str, tools: list[types.Tool], instructions: str | None) -> Server:
    from importlib.metadata import PackageNotFoundError, version

    try:
        server_version = version("open-structural-analysis")
    except PackageNotFoundError:
        server_version = None
    server: Server = Server("mcp-opensa", version=server_version, instructions=instructions)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return tools

    # A validação fica com o servidor do OpenSA, que conhece os esquemas atuais.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return await forward_call(endpoint, name, arguments)

    return server


def _ensure_standard_streams() -> bool:
    """Executáveis gráficos (sem console) recebem os pipes do cliente pelos descritores 0 e 1."""
    try:
        if sys.stdin is None:
            sys.stdin = open(0, encoding="utf-8", closefd=False)  # noqa: SIM115
        if sys.stdout is None:
            sys.stdout = open(1, "w", encoding="utf-8", closefd=False)  # noqa: SIM115
    except OSError:
        return False
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    return True


def run_stdio_bridge(endpoint: str = DEFAULT_ENDPOINT) -> int:
    if not _ensure_standard_streams():
        return 2
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    tools, instructions = local_catalog()
    server = build_server(endpoint, tools, instructions)

    async def serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(
                read,
                write,
                server.create_initialization_options(NotificationOptions()),
            )

    anyio.run(serve)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    endpoint = os.environ.get("OSA_MCP_ENDPOINT", DEFAULT_ENDPOINT)
    if "--mcp-endpoint" in arguments:
        index = arguments.index("--mcp-endpoint")
        if index + 1 >= len(arguments):
            print("--mcp-endpoint exige uma URL.", file=sys.stderr)
            return 2
        endpoint = arguments[index + 1]
    return run_stdio_bridge(endpoint)
