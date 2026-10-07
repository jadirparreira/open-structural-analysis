"""Servidor MCP local integrado ao processo do OpenSA."""

from __future__ import annotations

import threading
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .application import McpApplication

TemplateName = Literal["barrabieng", "galpao", "mezanino", "portico"]


class LocalMcpServer:
    """Expõe o modelo aberto em ``127.0.0.1`` via Streamable HTTP."""

    def __init__(
        self,
        application: McpApplication,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self.application = application
        self.host = host
        self.port = port
        self.server = FastMCP(
            "mcp-opensa",
            instructions=(
                "Você está conectado ao Open Structural Analysis. "
                "Consulte o projeto atual antes de fazer alterações. "
                "As coordenadas do modelo usam as unidades do projeto; "
                "se elas não estiverem claras, pergunte ao usuário."
            ),
            host=host,
            port=port,
            streamable_http_path="/mcp-opensa",
            stateless_http=True,
        )
        self._thread: threading.Thread | None = None
        self._register_tools()

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/mcp-opensa"

    def start(self) -> None:
        """Inicia o servidor uma única vez em uma thread daemon."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="osa-mcp-server",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        self.server.run(transport="streamable-http")

    def _register_tools(self) -> None:
        read_only = ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            openWorldHint=False,
        )
        write = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            openWorldHint=False,
        )

        @self.server.tool(
            name="get_project_summary",
            title="Consultar resumo do projeto",
            description=(
                "Use esta ferramenta para saber o estado do projeto estrutural "
                "atualmente aberto no OpenSA antes de executar outras ações."
            ),
            annotations=read_only,
        )
        def get_project_summary() -> dict[str, Any]:
            return self.application.get_project_summary()

        @self.server.tool(
            name="list_nodes",
            title="Listar nós",
            description="Use esta ferramenta para consultar os nós do projeto aberto.",
            annotations=read_only,
        )
        def list_nodes() -> dict[str, Any]:
            return self.application.list_nodes()

        @self.server.tool(
            name="list_members",
            title="Listar membros",
            description="Use esta ferramenta para consultar os membros do projeto aberto.",
            annotations=read_only,
        )
        def list_members() -> dict[str, Any]:
            return self.application.list_members()

        @self.server.tool(
            name="create_node",
            title="Criar nó",
            description=(
                "Cria um nó no projeto estrutural atualmente aberto. "
                "Use coordenadas numéricas e confirme as unidades com o usuário quando necessário."
            ),
            annotations=write,
        )
        def create_node(x: float, y: float, z: float, name: str | None = None) -> dict[str, Any]:
            return self.application.create_node(x, y, z, name=name)

        @self.server.tool(
            name="create_member",
            title="Criar membro",
            description=(
                "Cria um membro entre dois nós existentes no projeto aberto. "
                "Consulte os nós antes de chamar esta ferramenta."
            ),
            annotations=write,
        )
        def create_member(
            start_node: str,
            end_node: str,
            name: str | None = None,
        ) -> dict[str, Any]:
            return self.application.create_member(start_node, end_node, name=name)

        @self.server.tool(
            name="create_template",
            title="Criar estrutura inicial",
            description=(
                "Cria uma estrutura inicial pré-configurada no projeto aberto. "
                "Use uma das opções: barrabieng, galpao, mezanino ou portico. "
                "Use esta ferramenta quando o usuário pedir um modelo inicial desse tipo."
            ),
            annotations=write,
        )
        def create_template(template: TemplateName) -> dict[str, Any]:
            return self.application.create_template(template)
