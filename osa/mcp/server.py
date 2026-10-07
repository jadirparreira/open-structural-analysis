"""Servidor MCP local integrado ao processo do OpenSA."""

from __future__ import annotations

import threading
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .application import McpApplication


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
            name="list_materials",
            title="Listar materiais",
            description="Consulta os materiais disponíveis no projeto aberto.",
            annotations=read_only,
        )
        def list_materials() -> dict[str, Any]:
            return self.application.list_materials()

        @self.server.tool(
            name="list_sections",
            title="Listar seções",
            description=(
                "Consulta as famílias de seção disponíveis. Informe o nome do material "
                "ou o tipo do material, como 'Concreto'."
            ),
            annotations=read_only,
        )
        def list_sections(material: str | None = None) -> dict[str, Any]:
            return self.application.list_sections(material)

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
            name="set_node_supports",
            title="Definir apoios do nó",
            description=(
                "Define as restrições translacionais e rotacionais de um nó. "
                "Use true para restringir cada grau de liberdade, na ordem X, Y, Z, Rx, Ry e Rz."
            ),
            annotations=write,
        )
        def set_node_supports(
            node_name: str,
            dx: bool,
            dy: bool,
            dz: bool,
            rx: bool = False,
            ry: bool = False,
            rz: bool = False,
        ) -> dict[str, Any]:
            return self.application.set_node_supports(node_name, dx, dy, dz, rx, ry, rz)

        @self.server.tool(
            name="create_member",
            title="Criar membro",
            description=(
                "Cria um membro entre dois nós existentes no projeto aberto. "
                "Consulte os nós antes de chamar esta ferramenta. Opcionalmente, "
                "material, seção e geometria podem ser informados no mesmo passo; "
                "as dimensões da seção usam milímetros."
            ),
            annotations=write,
        )
        def create_member(
            start_node: str,
            end_node: str,
            name: str | None = None,
            material: str | None = None,
            section: str | None = None,
            geometry: dict[str, float] | None = None,
            profile: str | None = None,
        ) -> dict[str, Any]:
            return self.application.create_member(
                start_node,
                end_node,
                name=name,
                material=material,
                section=section,
                geometry=geometry,
                profile=profile,
            )

        @self.server.tool(
            name="set_member_properties",
            title="Atribuir propriedades aos membros",
            description=(
                "Atribui material e seção paramétrica a um ou mais membros. "
                "As dimensões da geometria usam milímetros; por exemplo, uma seção "
                "retangular de 15 x 30 cm usa {b: 150, h: 300}."
            ),
            annotations=write,
        )
        def set_member_properties(
            member_names: list[str],
            material: str,
            section: str,
            geometry: dict[str, float],
            profile: str | None = None,
        ) -> dict[str, Any]:
            return self.application.set_member_properties(
                member_names, material, section, geometry, profile,
            )
