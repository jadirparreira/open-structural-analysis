"""Servidor MCP local integrado ao processo do OpenSA."""

from __future__ import annotations

import socket
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
                "A interface possui as sessões Geometria, Ações e Análise. "
                "Antes de executar uma operação relacionada a uma sessão, consulte "
                "get_session_state e abra a sessão correspondente com set_session. "
                "Mantenha essa sessão aberta durante a sequência de operações para "
                "que o usuário acompanhe visualmente onde as alterações estão ocorrendo. "
                "As coordenadas do modelo usam as unidades do projeto; "
                "se elas não estiverem claras, pergunte ao usuário."
            ),
            host=host,
            port=port,
            streamable_http_path="/mcp-opensa",
            stateless_http=True,
        )
        self._thread: threading.Thread | None = None
        self._uvicorn_server: Any | None = None
        self._last_error: str | None = None
        self._stop_requested = False
        self._state_lock = threading.Lock()
        self._register_tools()

    @property
    def endpoint(self) -> str:
        return f"http://{self.host}:{self.port}/mcp-opensa"

    def start(self) -> None:
        """Inicia o servidor em uma thread daemon, se ainda não estiver ativo."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._last_error = None
            self._stop_requested = False
            self._uvicorn_server = None
            self._thread = threading.Thread(
                target=self._run,
                name="osa-mcp-server",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Solicita o encerramento do servidor e aguarda sua thread."""
        with self._state_lock:
            server = self._uvicorn_server
            thread = self._thread
            self._stop_requested = True
        if server is not None:
            server.should_exit = True
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    @property
    def is_running(self) -> bool:
        """Indica se o Uvicorn concluiu a inicialização do endpoint."""
        with self._state_lock:
            server = self._uvicorn_server
            thread = self._thread
        return bool(thread is not None and thread.is_alive() and server is not None and server.started)

    @property
    def last_error(self) -> str | None:
        """Retorna o último erro de inicialização, se houver."""
        with self._state_lock:
            return self._last_error

    def is_listening(self) -> bool:
        """Confirma que a porta local aceita conexões TCP."""
        try:
            with socket.create_connection((self.host, self.port), timeout=0.2):
                return True
        except OSError:
            return False

    def _run(self) -> None:
        server = None
        try:
            import uvicorn

            application = self.server.streamable_http_app()
            config = uvicorn.Config(
                application,
                host=self.host,
                port=self.port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            with self._state_lock:
                self._uvicorn_server = server
                stop_requested = self._stop_requested
            if stop_requested:
                server.should_exit = True
            server.run()
        except Exception as error:  # noqa: BLE001  # depende do ambiente de rede
            with self._state_lock:
                self._last_error = str(error)
        finally:
            with self._state_lock:
                if (
                    server is not None
                    and not server.started
                    and not self._stop_requested
                    and self._last_error is None
                ):
                    self._last_error = (
                        f"Não foi possível abrir {self.endpoint}. "
                        "A porta pode estar em uso por outro programa."
                    )
                self._uvicorn_server = None

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
            name="get_session_state",
            title="Consultar sessão aberta",
            description="Consulta se Geometria, Ações ou Análise está aberta na interface.",
            annotations=read_only,
        )
        def get_session_state() -> dict[str, Any]:
            return self.application.get_session_state()

        @self.server.tool(
            name="set_session",
            title="Abrir sessão do programa",
            description=(
                "Abre uma sessão visual do OpenSA. Use exatamente Geometria, Ações ou Análise "
                "antes das operações relacionadas à respectiva sessão."
            ),
            annotations=write,
        )
        def set_session(session: str) -> dict[str, Any]:
            return self.application.set_session(session)

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
            name="list_action_groups",
            title="Listar grupos de ações",
            description="Consulta os grupos de ações e as ações disponíveis em cada grupo.",
            annotations=read_only,
        )
        def list_action_groups() -> dict[str, Any]:
            return self.application.list_action_groups()

        @self.server.tool(
            name="list_actions",
            title="Listar carregamentos",
            description=(
                "Consulta os carregamentos aplicados. Pode filtrar por load_case ou target. "
                "Use esta ferramenta antes de editar ou excluir uma carga."
            ),
            annotations=read_only,
        )
        def list_actions(
            load_case: str | None = None,
            target: str | None = None,
        ) -> dict[str, Any]:
            return self.application.list_actions(load_case, target)

        @self.server.tool(
            name="get_action_state",
            title="Consultar estado das ações",
            description="Consulta o grupo e a ação atualmente selecionados no OpenSA.",
            annotations=read_only,
        )
        def get_action_state() -> dict[str, Any]:
            return self.application.get_action_state()

        @self.server.tool(
            name="set_action_group",
            title="Selecionar grupo de ações",
            description="Seleciona um grupo de ações existente ou um modelo padrão.",
            annotations=write,
        )
        def set_action_group(group_name: str) -> dict[str, Any]:
            return self.application.set_action_group(group_name)

        @self.server.tool(
            name="set_active_action",
            title="Selecionar ação ativa",
            description=(
                "Seleciona a ação/caso de carregamento usado pela interface. "
                "Use o nome da ação retornado por list_action_groups."
            ),
            annotations=write,
        )
        def set_active_action(action_name: str) -> dict[str, Any]:
            return self.application.set_active_action(action_name)

        @self.server.tool(
            name="create_action_group",
            title="Criar grupo de ações",
            description=(
                "Cria um grupo personalizado. Cada ação deve ter name e abbreviation, "
                "por exemplo {name: 'Ação permanente', abbreviation: 'AP'}."
            ),
            annotations=write,
        )
        def create_action_group(
            name: str,
            actions: list[dict[str, str]],
        ) -> dict[str, Any]:
            return self.application.create_action_group(name, actions)

        @self.server.tool(
            name="update_action_group",
            title="Atualizar grupo de ações",
            description="Atualiza o nome e as ações de um grupo personalizado existente.",
            annotations=write,
        )
        def update_action_group(
            old_name: str,
            name: str,
            actions: list[dict[str, str]],
        ) -> dict[str, Any]:
            return self.application.update_action_group(old_name, name, actions)

        @self.server.tool(
            name="delete_action_group",
            title="Excluir grupo de ações",
            description="Exclui um grupo personalizado de ações.",
            annotations=destructive,
        )
        def delete_action_group(name: str) -> dict[str, Any]:
            return self.application.delete_action_group(name)

        @self.server.tool(
            name="list_load_combinations",
            title="Listar combinações de carga",
            description="Consulta as combinações de carregamento configuradas no projeto.",
            annotations=read_only,
        )
        def list_load_combinations() -> dict[str, Any]:
            return self.application.list_load_combinations()

        @self.server.tool(
            name="create_load_combination",
            title="Criar combinação de carga",
            description=(
                "Cria uma combinação. factors, factors_2 e factors_3 usam as siglas das ações "
                "como chaves; active_actions informa as siglas participantes. limit_state pode ser CAR, ELU ou ELS."
            ),
            annotations=write,
        )
        def create_load_combination(
            name: str,
            factors: dict[str, float] | None = None,
            factors_2: dict[str, float] | None = None,
            factors_3: dict[str, float] | None = None,
            active_actions: list[str] | None = None,
            action_group: str | None = None,
            limit_state: str = "CAR",
        ) -> dict[str, Any]:
            return self.application.create_load_combination(
                name, factors, factors_2, factors_3, active_actions, action_group, limit_state,
            )

        @self.server.tool(
            name="update_load_combination",
            title="Atualizar combinação de carga",
            description="Atualiza uma combinação existente; informe somente os campos desejados.",
            annotations=write,
        )
        def update_load_combination(
            old_name: str,
            name: str | None = None,
            factors: dict[str, float] | None = None,
            factors_2: dict[str, float] | None = None,
            factors_3: dict[str, float] | None = None,
            active_actions: list[str] | None = None,
            action_group: str | None = None,
            limit_state: str | None = None,
        ) -> dict[str, Any]:
            return self.application.update_load_combination(
                old_name,
                name=name,
                factors=factors,
                factors_2=factors_2,
                factors_3=factors_3,
                active_actions=active_actions,
                action_group=action_group,
                limit_state=limit_state,
            )

        @self.server.tool(
            name="delete_load_combination",
            title="Excluir combinação de carga",
            description="Exclui uma combinação existente pelo nome.",
            annotations=destructive,
        )
        def delete_load_combination(name: str) -> dict[str, Any]:
            return self.application.delete_load_combination(name)

        @self.server.tool(
            name="get_analysis_state",
            title="Consultar estado da análise",
            description="Consulta o estado da análise, resultados disponíveis e visualização atual.",
            annotations=read_only,
        )
        def get_analysis_state() -> dict[str, Any]:
            return self.application.get_analysis_state()

        @self.server.tool(
            name="run_analysis",
            title="Processar estrutura",
            description=(
                "Executa a análise estrutural. Se combinations não for informado, processa todas as "
                "combinações configuradas e retorna os resultados gerados."
            ),
            annotations=write,
        )
        def run_analysis(combinations: list[str] | None = None) -> dict[str, Any]:
            return self.application.run_analysis(combinations)

        @self.server.tool(
            name="list_analysis_results",
            title="Listar resultados da análise",
            description="Lista as combinações que possuem resultados válidos na revisão atual.",
            annotations=read_only,
        )
        def list_analysis_results() -> dict[str, Any]:
            return self.application.list_analysis_results()

        @self.server.tool(
            name="get_node_analysis_results",
            title="Consultar resultados dos nós",
            description="Consulta deslocamentos, rotações e reações nodais de uma combinação analisada.",
            annotations=read_only,
        )
        def get_node_analysis_results(
            combination: str,
            node_names: list[str] | None = None,
        ) -> dict[str, Any]:
            return self.application.get_node_analysis_results(combination, node_names)

        @self.server.tool(
            name="get_member_analysis_results",
            title="Consultar resultados dos membros",
            description=(
                "Consulta esforços e deslocamentos dos membros. include_samples inclui as 21 amostras "
                "ao longo de cada membro para reconstruir diagramas."
            ),
            annotations=read_only,
        )
        def get_member_analysis_results(
            combination: str,
            member_names: list[str] | None = None,
            include_samples: bool = False,
        ) -> dict[str, Any]:
            return self.application.get_member_analysis_results(
                combination, member_names, include_samples,
            )

        @self.server.tool(
            name="get_support_reactions",
            title="Consultar reações de apoio",
            description="Consulta forças e momentos de reação nos nós apoiados.",
            annotations=read_only,
        )
        def get_support_reactions(
            combination: str,
            node_names: list[str] | None = None,
        ) -> dict[str, Any]:
            return self.application.get_support_reactions(combination, node_names)

        @self.server.tool(
            name="set_analysis_view",
            title="Selecionar visualização da análise",
            description=(
                "Seleciona a combinação e o diagrama exibido. Diagramas: Normal, Cortante Y, Cortante Z, "
                "Torsor, Fletor Y, Fletor Z, Reações de apoio, Deformação X, Deformação Y, "
                "Deformação Z e Deformação XYZ."
            ),
            annotations=write,
        )
        def set_analysis_view(
            combination: str | None = None,
            diagram: str | None = None,
        ) -> dict[str, Any]:
            return self.application.set_analysis_view(combination, diagram)

        @self.server.tool(
            name="set_analysis_diagrams_visible",
            title="Mostrar ou ocultar diagramas",
            description="Mostra ou oculta os diagramas de resultados na cena do OpenSA.",
            annotations=write,
        )
        def set_analysis_diagrams_visible(visible: bool) -> dict[str, Any]:
            return self.application.set_analysis_diagrams_visible(visible)

        @self.server.tool(
            name="add_node_force",
            title="Aplicar força no nó",
            description="Aplica ou atualiza uma força nodal em kN nas direções X, Y ou Z.",
            annotations=write,
        )
        def add_node_force(
            node_name: str,
            direction: str,
            value_kn: float,
            load_case: str,
        ) -> dict[str, Any]:
            return self.application.add_node_force(node_name, direction, value_kn, load_case)

        @self.server.tool(
            name="add_node_moment",
            title="Aplicar momento no nó",
            description="Aplica ou atualiza um momento nodal em kN·m nas direções X, Y ou Z.",
            annotations=write,
        )
        def add_node_moment(
            node_name: str,
            direction: str,
            value_knm: float,
            load_case: str,
        ) -> dict[str, Any]:
            return self.application.add_node_moment(node_name, direction, value_knm, load_case)

        @self.server.tool(
            name="add_member_distributed_load",
            title="Aplicar carga distribuída no membro",
            description=(
                "Aplica ou atualiza uma força distribuída em kN/m no membro. "
                "Use initial e final para uma carga linearmente variável; valores iguais "
                "representam carga uniforme. reference pode ser global ou local."
            ),
            annotations=write,
        )
        def add_member_distributed_load(
            member_name: str,
            direction: str,
            initial_kn_m: float,
            final_kn_m: float,
            load_case: str,
            reference: str = "global",
        ) -> dict[str, Any]:
            return self.application.add_member_distributed_load(
                member_name, direction, initial_kn_m, final_kn_m, load_case, reference,
            )

        @self.server.tool(
            name="add_member_moment",
            title="Aplicar momento no membro",
            description=(
                "Aplica ou atualiza um momento distribuído em kN·m/m no eixo local "
                "X, Y ou Z do membro."
            ),
            annotations=write,
        )
        def add_member_moment(
            member_name: str,
            direction: str,
            value_knm_m: float,
            load_case: str,
        ) -> dict[str, Any]:
            return self.application.add_member_moment(member_name, direction, value_knm_m, load_case)

        @self.server.tool(
            name="update_applied_load",
            title="Atualizar carregamento aplicado",
            description=(
                "Atualiza um carregamento existente pelo nome retornado por list_actions, "
                "preservando sua identidade automática (por exemplo, Carga 5). "
                "Para cargas distribuídas use initial_kn_m e final_kn_m; para forças e momentos "
                "concentrados use value. Também é possível alterar target, direction, load_case e reference."
            ),
            annotations=write,
        )
        def update_applied_load(
            action_name: str,
            target: str | None = None,
            direction: str | None = None,
            initial_kn_m: float | None = None,
            final_kn_m: float | None = None,
            value: float | None = None,
            load_case: str | None = None,
            reference: str | None = None,
        ) -> dict[str, Any]:
            return self.application.update_applied_load(
                action_name,
                target=target,
                direction=direction,
                initial=initial_kn_m,
                final=final_kn_m,
                value=value,
                load_case=load_case,
                reference=reference,
            )

        @self.server.tool(
            name="apply_selfweight",
            title="Aplicar peso próprio",
            description=(
                "Substitui os carregamentos do caso informado pelo peso próprio dos membros. "
                "Informe materials para filtrar materiais; omitindo, todos os materiais serão usados."
            ),
            annotations=write,
        )
        def apply_selfweight(
            load_case: str,
            materials: list[str] | None = None,
        ) -> dict[str, Any]:
            return self.application.apply_selfweight(load_case, materials)

        @self.server.tool(
            name="remove_selfweight",
            title="Remover peso próprio",
            description="Remove as cargas de peso próprio do caso de carregamento informado.",
            annotations=write,
        )
        def remove_selfweight(load_case: str) -> dict[str, Any]:
            return self.application.remove_selfweight(load_case)

        @self.server.tool(
            name="delete_action",
            title="Excluir carregamento",
            description="Exclui um carregamento específico pelo nome retornado por list_actions.",
            annotations=destructive,
        )
        def delete_action(action_name: str) -> dict[str, Any]:
            return self.application.delete_action(action_name)

        @self.server.tool(
            name="clear_actions",
            title="Limpar carregamentos",
            description=(
                "Remove carregamentos por load_case, target ou ambos. Informe pelo menos um filtro."
            ),
            annotations=destructive,
        )
        def clear_actions(
            load_case: str | None = None,
            target: str | None = None,
        ) -> dict[str, Any]:
            return self.application.clear_actions(load_case=load_case, target=target)

        @self.server.tool(
            name="list_rigid_bars",
            title="Listar barras rígidas",
            description="Consulta as barras rígidas do projeto aberto.",
            annotations=read_only,
        )
        def list_rigid_bars() -> dict[str, Any]:
            return self.application.list_rigid_bars()

        @self.server.tool(
            name="get_view_options",
            title="Consultar opções visuais",
            description="Consulta o que está visível na cena do OpenSA.",
            annotations=read_only,
        )
        def get_view_options() -> dict[str, Any]:
            return self.application.get_view_options()

        @self.server.tool(
            name="set_view_options",
            title="Controlar visualização",
            description=(
                "Controla a visualização da cena sem alterar o modelo. Opções: "
                "grid_visible, reference_axes_visible, node_labels_visible, "
                "member_labels_visible, local_axes_visible, nodes_visible, "
                "solid_members_visible, member_releases_visible, semirigid_links_visible, "
                "node_supports_visible, snap_enabled, node_forces_visible, node_moments_visible, "
                "member_forces_visible e member_moments_visible. Informe somente os campos desejados."
            ),
            annotations=write,
        )
        def set_view_options(options: dict[str, bool]) -> dict[str, Any]:
            return self.application.set_view_options(options)

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
            name="update_node_properties",
            title="Atualizar propriedades do nó",
            description=(
                "Atualiza propriedades de um nó existente sem alterar seu nome. Informe "
                "somente os campos desejados. Para coordenadas, informe x, y e z juntos. "
                "supports possui seis booleanos na ordem Dx,Dy,Dz,Rx,Ry,Rz. "
                "support_stiffness possui seis valores, com rigidezas translacionais em "
                "kN/m e rotacionais em kN·m/rad."
            ),
            annotations=write,
        )
        def update_node_properties(
            node_name: str,
            x: float | None = None,
            y: float | None = None,
            z: float | None = None,
            supports: list[bool] | None = None,
            support_stiffness: list[float] | None = None,
        ) -> dict[str, Any]:
            return self.application.update_node_properties(
                node_name,
                x=x,
                y=y,
                z=z,
                supports=supports,
                support_stiffness=support_stiffness,
            )

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
            name="delete_elements",
            title="Excluir elementos em lote",
            description=(
                "Exclui vários nós, membros e barras rígidas em uma operação validada. "
                "Use dry_run para visualizar o plano sem alterar o modelo. Por segurança, "
                "nós com dependências bloqueiam a operação; use cascade=true para incluir "
                "automaticamente os membros e barras rígidas conectados."
            ),
            annotations=destructive,
        )
        def delete_elements(
            nodes: list[str] | None = None,
            members: list[str] | None = None,
            rigid_bars: list[str] | None = None,
            cascade: bool = False,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            return self.application.delete_elements(
                nodes=nodes,
                members=members,
                rigid_bars=rigid_bars,
                cascade=cascade,
                dry_run=dry_run,
            )

        @self.server.tool(
            name="update_member_endpoints",
            title="Alterar extremidades do membro",
            description=(
                "Altera os nós inicial e final de um membro, preservando sua identidade e propriedades."
            ),
            annotations=write,
        )
        def update_member_endpoints(
            member_name: str,
            start_node: str,
            end_node: str,
        ) -> dict[str, Any]:
            return self.application.update_member_endpoints(member_name, start_node, end_node)

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
            name="delete_rigid_bar",
            title="Excluir barra rígida",
            description="Exclui uma barra rígida pelo nome retornado por list_rigid_bars.",
            annotations=destructive,
        )
        def delete_rigid_bar(rigid_bar_name: str) -> dict[str, Any]:
            return self.application.delete_rigid_bar(rigid_bar_name)

        @self.server.tool(
            name="update_rigid_bar_endpoints",
            title="Alterar extremidades da barra rígida",
            description=(
                "Altera os nós de uma barra rígida. O nome da barra rígida será atualizado "
                "automaticamente para refletir os novos nós."
            ),
            annotations=write,
        )
        def update_rigid_bar_endpoints(
            rigid_bar_name: str,
            start_node: str,
            end_node: str,
        ) -> dict[str, Any]:
            return self.application.update_rigid_bar_endpoints(
                rigid_bar_name, start_node, end_node,
            )

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
