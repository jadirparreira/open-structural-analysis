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
        destructive = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
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
            name="list_rigid_bars",
            title="Listar barras rígidas",
            description="Consulta as barras rígidas do projeto aberto.",
            annotations=read_only,
        )
        def list_rigid_bars() -> dict[str, Any]:
            return self.application.list_rigid_bars()

        @self.server.tool(
            name="list_reference_axes",
            title="Consultar eixos de referência",
            description="Consulta os eixos de referência configurados no projeto aberto.",
            annotations=read_only,
        )
        def list_reference_axes() -> dict[str, Any]:
            return self.application.list_reference_axes()

        @self.server.tool(
            name="set_reference_axes",
            title="Configurar eixos de referência",
            description=(
                "Substitui os eixos de referência do projeto. Informe um objeto com as chaves "
                "X, Y e Z; cada uma contém uma lista de objetos {label, value}."
            ),
            annotations=write,
        )
        def set_reference_axes(axes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
            return self.application.set_reference_axes(axes)

        @self.server.tool(
            name="create_node",
            title="Criar nó",
            description=(
                "Cria um nó no projeto estrutural atualmente aberto. "
                "Use coordenadas numéricas e confirme as unidades com o usuário quando necessário."
            ),
            annotations=write,
        )
        def create_node(x: float, y: float, z: float) -> dict[str, Any]:
            return self.application.create_node(x, y, z)

        @self.server.tool(
            name="delete_node",
            title="Excluir nó",
            description=(
                "Exclui um nó pelo nome padrão retornado por list_nodes. "
                "O nó não pode ainda estar conectado a membros."
            ),
            annotations=destructive,
        )
        def delete_node(node_name: str) -> dict[str, Any]:
            return self.application.delete_node(node_name)

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
                "Consulte os nós antes de chamar esta ferramenta. O nome do membro "
                "é atribuído automaticamente pelo OpenSA."
            ),
            annotations=write,
        )
        def create_member(
            start_node: str,
            end_node: str,
        ) -> dict[str, Any]:
            return self.application.create_member(start_node, end_node)

        @self.server.tool(
            name="delete_member",
            title="Excluir membro",
            description="Exclui um membro pelo nome padrão retornado por list_members.",
            annotations=destructive,
        )
        def delete_member(member_name: str) -> dict[str, Any]:
            return self.application.delete_member(member_name)

        @self.server.tool(
            name="split_member",
            title="Dividir membro",
            description=(
                "Divide um membro em partes iguais, criando nós intermediários. "
                "Informe o nome padrão do membro e o número de partes maior que 1."
            ),
            annotations=write,
        )
        def split_member(member_name: str, parts: int) -> dict[str, Any]:
            return self.application.split_member(member_name, parts)

        @self.server.tool(
            name="join_members",
            title="Unir membros",
            description=(
                "Une dois membros que compartilham um nó e são colineares. "
                "O primeiro nome é preservado."
            ),
            annotations=write,
        )
        def join_members(first_member: str, second_member: str) -> dict[str, Any]:
            return self.application.join_members(first_member, second_member)

        @self.server.tool(
            name="reverse_member",
            title="Inverter membro",
            description="Inverte a orientação de um membro, trocando seus nós inicial e final.",
            annotations=write,
        )
        def reverse_member(member_name: str) -> dict[str, Any]:
            return self.application.reverse_member(member_name)

        @self.server.tool(
            name="create_rigid_bar",
            title="Criar barra rígida",
            description="Cria uma barra rígida entre dois nós existentes.",
            annotations=write,
        )
        def create_rigid_bar(start_node: str, end_node: str) -> dict[str, Any]:
            return self.application.create_rigid_bar(start_node, end_node)

        @self.server.tool(
            name="copy_elements",
            title="Copiar elementos",
            description=(
                "Copia nós e/ou membros por uma translação. Informe listas de nomes e "
                "um deslocamento [dx, dy, dz] nas unidades do projeto. Membros copiados "
                "preservam suas propriedades."
            ),
            annotations=write,
        )
        def copy_elements(
            offset: list[float],
            node_names: list[str] | None = None,
            member_names: list[str] | None = None,
        ) -> dict[str, Any]:
            if len(offset) != 3:
                raise ValueError("O deslocamento deve possuir exatamente três valores.")
            return self.application.copy_elements(
                node_names,
                member_names,
                (float(offset[0]), float(offset[1]), float(offset[2])),
            )

        @self.server.tool(
            name="copy_member_properties",
            title="Copiar propriedades entre membros",
            description=(
                "Copia propriedades de um membro de referência para um membro de destino. "
                "As propriedades possíveis são color, material, section, rotation, "
                "offsets e releases. Se omitidas, todas são copiadas."
            ),
            annotations=write,
        )
        def copy_member_properties(
            source_member: str,
            target_member: str,
            properties: list[str] | None = None,
        ) -> dict[str, Any]:
            return self.application.copy_member_properties(source_member, target_member, properties)

        @self.server.tool(
            name="set_member_rectangular_section",
            title="Atribuir seção retangular",
            description=(
                "Atribui uma seção retangular a um ou mais membros. Informe largura e "
                "altura em milímetros; 15 x 30 cm corresponde a 150 x 300 mm. "
                "O material padrão é Concreto Estrutural."
            ),
            annotations=write,
        )
        def set_member_rectangular_section(
            member_names: list[str],
            width_mm: float,
            height_mm: float,
            material: str = "Concreto Estrutural",
        ) -> dict[str, Any]:
            return self.application.set_member_rectangular_section(
                member_names, width_mm, height_mm, material,
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

        @self.server.tool(
            name="update_member_properties",
            title="Atualizar propriedades dos membros",
            description=(
                "Atualiza qualquer combinação de propriedades dos membros. Informe uma lista "
                "de nomes e somente os campos que deseja alterar. Pode alterar material, "
                "section, geometry, profile, rotation, releases (12 booleanos na ordem "
                "Dxa,Dxb,Dya,Dyb,Dza,Dzb,Rxa,Rxb,Rya,Ryb,Rza,Rzb), "
                "rotation_flexibility_percent (6 inteiros), offsets em milímetros e color. "
                "Para geometry, informe ou mantenha material e section válidos."
            ),
            annotations=write,
        )
        def update_member_properties(
            member_names: list[str],
            material: str | None = None,
            section: str | None = None,
            geometry: dict[str, float] | None = None,
            profile: str | None = None,
            rotation: int | None = None,
            releases: list[bool] | None = None,
            rotation_flexibility_percent: list[int] | None = None,
            solid_face_offsets_mm: list[float] | None = None,
            solid_section_offsets_mm: list[float] | None = None,
            color: str | None = None,
        ) -> dict[str, Any]:
            return self.application.update_member_properties(
                member_names,
                material=material,
                section=section,
                geometry=geometry,
                profile=profile,
                rotation=rotation,
                releases=releases,
                rotation_flexibility_percent=rotation_flexibility_percent,
                solid_face_offsets_mm=solid_face_offsets_mm,
                solid_section_offsets_mm=solid_section_offsets_mm,
                color=color,
            )
