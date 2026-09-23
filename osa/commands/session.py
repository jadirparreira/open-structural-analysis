"""Máquina de estados dos comandos de modelagem."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees

from osa.domain import ReferenceAxis
from osa.services import ActionService, ModelService

from .parser import parse_coordinates, parse_distributed_force, parse_load_value, parse_member_nodes


@dataclass(frozen=True, slots=True)
class DistributedMemberForce:
    target: str
    direction: str
    initial: float
    final: float
    reference: str = "global"


@dataclass(frozen=True, slots=True)
class MemberMoment:
    target: str
    direction: str
    value: float


@dataclass(frozen=True, slots=True)
class NodeForce:
    target: str
    direction: str
    value: float


@dataclass(frozen=True, slots=True)
class NodeMoment:
    target: str
    direction: str
    value: float


@dataclass(frozen=True, slots=True)
class SelfWeight:
    target: str
    value: float


@dataclass(frozen=True, slots=True)
class CommandResponse:
    command: str
    message: str
    level: str = "instruction"
    model_changed: bool = False
    distributed_member_forces: tuple[DistributedMemberForce, ...] = ()
    member_moments: tuple[MemberMoment, ...] = ()
    node_forces: tuple[NodeForce, ...] = ()
    node_moments: tuple[NodeMoment, ...] = ()
    selfweights: tuple[SelfWeight, ...] = ()
    remove_selfweight: bool = False


class CommandSession:
    def __init__(self, service: ModelService) -> None:
        self.service = service
        self.pending: str | None = None
        self.load_target: tuple[str, tuple[str, ...]] | None = None
        self.load_direction: str | None = None
        self.load_reference: str = "global"
        self._pending_selfweights: tuple[SelfWeight, ...] = ()
        self.active_load_case: str | None = None

    def set_active_load_case(self, name: str | None) -> None:
        self.active_load_case = name or None

    def cancel(self) -> None:
        self.pending = None
        self.load_target = None
        self.load_direction = None
        self.load_reference = "global"
        self._pending_selfweights = ()

    def submit(self, text: str) -> CommandResponse:
        value = text.strip()
        if self.pending == "node":
            self.pending = None
            try:
                coordinates = parse_coordinates(value)
                self.service.create_node(*coordinates)
                return CommandResponse(value, "Nó criado.", "success", True)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
        if self.pending == "member":
            self.pending = None
            try:
                start, end = parse_member_nodes(value)
                resolved_start = self.service.resolve_node_name(start)
                resolved_end = self.service.resolve_node_name(end)
                if not resolved_start or not resolved_end:
                    raise ValueError("Um dos nós informados não existe.")
                self.service.create_member(resolved_start, resolved_end)
                return CommandResponse(value, "Membro criado.", "success", True)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
        if self.pending == "load_target":
            try:
                self.load_target = self._resolve_load_targets(value)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            self.pending = "load_type"
            return CommandResponse(value, "Informe o tipo de ação: Força ou Momento.")
        if self.pending == "load_type":
            kind = value.casefold()
            if self.load_target is None:
                self.cancel()
                return CommandResponse(value, "A sequência de carga foi interrompida.", "error")
            if kind in ("força", "forca"):
                if self.load_target[0] == "member":
                    self.pending = "member_force_reference"
                    return CommandResponse(value, "Informe o sistema de direção: Global ou Local.")
                self.pending = "load_direction"
                return CommandResponse(value, "Informe a direção global: X, Y ou Z.")
            if kind in ("momento", "moment"):
                if self.load_target[0] == "member":
                    self.pending = "member_moment_direction"
                    return CommandResponse(value, "Informe a direção local: X, Y ou Z.")
                self.pending = "node_moment_direction"
                return CommandResponse(value, "Informe a direção global: X, Y ou Z.")
            self.cancel()
            return CommandResponse(value, "Informe Força ou Momento.", "error")
        if self.pending == "member_force_reference":
            reference = value.casefold()
            if reference in {"global", "g"}:
                self.load_reference = "global"
                self.pending = "load_direction"
                return CommandResponse(value, "Informe a direção global: X, Y ou Z.")
            if reference in {"local", "l"}:
                self.load_reference = "local"
                self.pending = "local_force_direction"
                return CommandResponse(value, "Informe a direção local: X, Y ou Z.")
            return CommandResponse(value, "Informe Global ou Local.", "error")
        if self.pending == "load_direction":
            direction = value.upper()
            if direction not in {"X", "Y", "Z"}:
                return CommandResponse(value, "Informe uma direção global válida: X, Y ou Z.", "error")
            self.load_direction = direction
            if self.load_target and self.load_target[0] == "node":
                self.pending = "node_force"
                return CommandResponse(value, "Informe a força no nó (kN).")
            self.pending = "load_force"
            return CommandResponse(value, "Informe a força linear no membro (kN/m).")
        if self.pending == "local_force_direction":
            direction = value.upper()
            if direction not in {"X", "Y", "Z"}:
                return CommandResponse(value, "Informe uma direção local válida: X, Y ou Z.", "error")
            self.load_direction = direction
            self.pending = "load_force"
            return CommandResponse(value, "Informe a força linear no membro (kN/m).")
        if self.pending == "load_force":
            try:
                initial, final = parse_distributed_force(value)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            target = self.load_target
            direction = self.load_direction
            reference = self.load_reference
            self.cancel()
            if target is None or direction is None or initial is None:
                return CommandResponse(value, "A sequência de carga foi interrompida.", "error")
            return CommandResponse(
                value,
                "Forças distribuídas criadas.",
                "success",
                distributed_member_forces=tuple(
                    DistributedMemberForce(name, direction, initial, final, reference)
                    for name in target[1]
                ),
            )
        if self.pending == "node_force":
            try:
                force = parse_load_value(value)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            target = self.load_target
            direction = self.load_direction
            self.cancel()
            if target is None or direction is None:
                return CommandResponse(value, "A sequência de carga foi interrompida.", "error")
            return CommandResponse(
                value,
                "Forças nodais criadas.",
                "success",
                node_forces=tuple(NodeForce(name, direction, force) for name in target[1]),
            )
        if self.pending == "member_moment":
            try:
                value_moment = parse_load_value(value)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            target = self.load_target
            direction = self.load_direction
            self.cancel()
            if target is None or direction is None:
                return CommandResponse(value, "A sequência de carga foi interrompida.", "error")
            return CommandResponse(
                value,
                "Momentos criados.",
                "success",
                member_moments=tuple(
                    MemberMoment(name, direction, value_moment)
                    for name in target[1]
                ),
            )
        if self.pending == "member_moment_direction":
            direction = value.upper()
            if direction not in {"X", "Y", "Z"}:
                return CommandResponse(value, "Informe uma direção local válida: X, Y ou Z.", "error")
            self.load_direction = direction
            self.pending = "member_moment"
            return CommandResponse(value, "Informe o momento (kNm/m).")
        if self.pending == "node_moment_direction":
            direction = value.upper()
            if direction not in {"X", "Y", "Z"}:
                return CommandResponse(value, "Informe uma direção global válida: X, Y ou Z.", "error")
            self.load_direction = direction
            self.pending = "node_moment"
            return CommandResponse(value, "Informe o momento no nó (kNm).")
        if self.pending == "node_moment":
            try:
                value_moment = parse_load_value(value)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            target = self.load_target
            direction = self.load_direction
            self.cancel()
            if target is None or direction is None:
                return CommandResponse(value, "A sequência de carga foi interrompida.", "error")
            return CommandResponse(
                value,
                "Momentos nodais criados.",
                "success",
                node_moments=tuple(
                    NodeMoment(name, direction, value_moment)
                    for name in target[1]
                ),
            )
        if self.pending == "selfweight_confirmation":
            answer = value.casefold()
            if answer in {"sim", "s"}:
                weights = self._pending_selfweights
                self.cancel()
                return CommandResponse(
                    value,
                    "Pesos próprios criados.",
                    "success",
                    selfweights=weights,
                )
            if answer in {"não", "nao", "n"}:
                self.cancel()
                return CommandResponse(value, "Operação cancelada.")
            return CommandResponse(value, "Responda apenas Sim ou Não.", "error")
        if self.pending == "selfweight_material":
            materials = tuple(self.service.model.materials)
            all_materials = value.casefold() == "todos"
            material = next(
                (name for name in materials if name.casefold() == value.casefold()),
                None,
            )
            if not all_materials and material is None:
                options = ", ".join((*materials, "Todos"))
                return CommandResponse(
                    value,
                    f"Material inválido. Escolha uma das opções: {options}.",
                    "error",
                )
            try:
                weights = self.service.member_selfweights(None if all_materials else material)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
            if not weights:
                scope = "nenhum material" if all_materials else f"o material '{material}'"
                return CommandResponse(
                    value,
                    f"Não há membros com {scope} para aplicar o peso próprio. Escolha outro material.",
                    "error",
                )
            self._pending_selfweights = tuple(SelfWeight(name, weight) for name, weight in weights)
            self.pending = "selfweight_confirmation"
            scope = "todos os materiais" if all_materials else f"o material '{material}'"
            return CommandResponse(
                value,
                f"Todos os pesos da ação atual serão apagados e substituídos pelo peso próprio dos elementos de {scope}. Confirma? (Sim/Não)",
            )

        command = value.casefold()
        if command == "node":
            self.pending = "node"
            return CommandResponse(value, "Informe as coordenadas do nó em X,Y,Z")
        if command == "member":
            self.pending = "member"
            return CommandResponse(value, "Informe o nó inicial e final A,B")
        if command == "load":
            if self.active_load_case and any(
                action.load_case == self.active_load_case
                and action.kind == "member_distributed_force_selfweight_Z"
                for action in self.service.model.actions.values()
            ):
                return CommandResponse(
                    value,
                    "A ação atual está restrita apenas a cargas de peso próprio.",
                    "error",
                )
            self.pending = "load_target"
            self.load_target = None
            return CommandResponse(value, "Informe a identidade do nó ou do membro.")
        if command == "selfweight":
            if self.active_load_case and any(
                action.load_case == self.active_load_case
                and action.kind == "member_distributed_force_selfweight_Z"
                for action in self.service.model.actions.values()
            ):
                return CommandResponse(
                    value,
                    "Pesos próprios removidos. A ação está liberada para novas cargas.",
                    "success",
                    remove_selfweight=True,
                )
            if not self.service.model.bars:
                return CommandResponse(value, "Não há membros no modelo para aplicar o peso próprio.", "error")
            materials = tuple(self.service.model.materials)
            if not materials:
                return CommandResponse(value, "Não há materiais cadastrados para aplicar o peso próprio.", "error")
            self.pending = "selfweight_material"
            options = ", ".join((*materials, "Todos"))
            return CommandResponse(
                value,
                f"Informe o material para aplicar o peso próprio. Disponíveis: {options}.",
            )
        if command == "galpao":
            try:
                self._create_galpao()
                return CommandResponse(value, "Galpão criado.", "success", True)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
        if command == "mezanino":
            try:
                self._create_mezanino()
                return CommandResponse(value, "Mezanino criado.", "success", True)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
        return CommandResponse(value, "Não é um comando válido", "error")

    def _resolve_load_targets(self, value: str) -> tuple[str, tuple[str, ...]]:
        identifiers = [identifier.strip() for identifier in value.split(",")]
        if not identifiers or not all(identifiers):
            raise ValueError("Informe uma ou mais identidades separadas por vírgula.")
        targets: list[tuple[str, str]] = []
        for identifier in identifiers:
            node_name = self.service.resolve_node_name(identifier)
            member_name = self.service.resolve_member_name(identifier)
            if node_name:
                targets.append(("node", node_name))
            elif member_name:
                targets.append(("member", member_name))
            else:
                raise ValueError(f"Não existe nó ou membro chamado '{identifier}'.")
        kinds = {kind for kind, _name in targets}
        if len(kinds) != 1:
            raise ValueError("Os elementos informados devem ser todos nós ou todos membros.")
        names = tuple(dict.fromkeys(name for _kind, name in targets))
        return targets[0][0], names

    def _create_mezanino(self) -> None:
        """Create a three-bay, all-steel mezzanine frame (21 x 4 x 4 m)."""
        model = self.service.model
        action_service = ActionService(model)
        model.set_selected_action_group("PP+AP+AV")
        module_length = 7.0
        module_width = 4.0
        height = 4.0
        x_grid = tuple(index * module_length for index in range(4))
        y_grid = (0.0, module_width)
        supports = (True, True, True, False, False, False)
        member_color = "#6e7781"
        profiles = {
            "column": ("W 250 x 44.8", {"d": 266.0, "bf": 148.0, "tw": 7.6, "tf": 13.0}),
            "girder": ("W 310 x 44.5", {"d": 313.0, "bf": 166.0, "tw": 6.6, "tf": 11.2}),
            "joist": ("W 200 x 22.5", {"d": 206.0, "bf": 102.0, "tw": 6.2, "tf": 8.0}),
            "brace": ("BC 10.0", {"d": 10.0}),
        }
        joist_releases = (False,) * 8 + (True,) * 4
        brace_releases = (False,) * 6 + (True,) * 6
        base_nodes: dict[tuple[float, float], str] = {}
        top_nodes: dict[tuple[float, float], str] = {}
        joist_x_grid = tuple(index * module_length / 3.0 for index in range(10))

        def add_w_member(start: str, end: str, profile_kind: str):
            profile, geometry = profiles[profile_kind]
            member = self.service.create_member(start, end)
            model.update_bar_material(member.name, "Aço Estrutural", model.materials["Aço Estrutural"])
            section = "Barra Circular" if profile_kind == "brace" else "W Laminado"
            model.update_bar_section(member.name, section)
            model.update_member_profile(member.name, profile, geometry)
            model.update_member_color(member.name, member_color)
            if profile_kind == "joist":
                model.update_member_releases(member.name, joist_releases)
            elif profile_kind == "brace":
                model.update_member_releases(member.name, brace_releases)
            elif profile_kind == "girder":
                start_x = model.nodes[start].x
                end_x = model.nodes[end].x
                is_middle_module = module_length < (start_x + end_x) / 2 < 2 * module_length
                start_on_column = not is_middle_module and start_x in x_grid
                end_on_column = not is_middle_module and end_x in x_grid
                if start_on_column or end_on_column:
                    model.update_member_releases(
                        member.name,
                        (False,) * 8 + (
                            start_on_column, end_on_column,
                            start_on_column, end_on_column,
                        ),
                    )
            return member

        # Pilares em cada canto dos três módulos, todos com 4 m de altura.
        for x in x_grid:
            for y in y_grid:
                base = self.service.create_node(x, y, 0.0)
                top = self.service.create_node(x, y, height)
                model.update_node_supports(base.name, supports)
                base_nodes[(x, y)] = base.name
                top_nodes[(x, y)] = top.name
                column = add_w_member(base.name, top.name, "column")
                model.update_member_rotation(column.name, 90)

        # Nós nas longarinas em cada travessa, inclusive nas duas internas de
        # cada módulo, para que o piso fique conectado topologicamente.
        for x in joist_x_grid:
            for y in y_grid:
                if (x, y) not in top_nodes:
                    top_nodes[(x, y)] = self.service.create_node(x, y, height).name

        # Duas longarinas contínuas, segmentadas em todos os apoios das travessas.
        for y in y_grid:
            for start_x, end_x in zip(joist_x_grid, joist_x_grid[1:]):
                add_w_member(top_nodes[(start_x, y)], top_nodes[(end_x, y)], "girder")

        # Travessas nos eixos dos pilares e duas vigas secundárias por módulo.
        external_portal_apexes: dict[float, str] = {}
        middle_joists: list[str] = []
        edge_joists: list[str] = []
        for x in joist_x_grid:
            if x in (x_grid[0], x_grid[-1]):
                apex = self.service.create_node(x, module_width / 2, height)
                external_portal_apexes[x] = apex.name
                edge_joists.extend((
                    add_w_member(top_nodes[(x, 0.0)], apex.name, "joist").name,
                    add_w_member(apex.name, top_nodes[(x, module_width)], "joist").name,
                ))
            else:
                middle_joists.append(
                    add_w_member(top_nodes[(x, 0.0)], top_nodes[(x, module_width)], "joist").name
                )

        # As cargas do piso recaem apenas sobre as travessas.
        for name in middle_joists:
            action_service.add_member_distributed_force(
                name, "Z", -1.17, -1.17, "Ação permanente", "global"
            )
        for name in edge_joists:
            action_service.add_member_distributed_force(
                name, "Z", -0.58, -0.58, "Ação permanente", "global"
            )
        for name in middle_joists:
            action_service.add_member_distributed_force(
                name, "Z", -4.67, -4.67, "Ação variável", "global"
            )
        for name in edge_joists:
            action_service.add_member_distributed_force(
                name, "Z", -2.34, -2.34, "Ação variável", "global"
            )

        # Pórticos externos: V invertido até o centro da viga superior.
        for x, apex in external_portal_apexes.items():
            add_w_member(base_nodes[(x, 0.0)], apex, "brace")
            add_w_member(base_nodes[(x, module_width)], apex, "brace")

        # Pórticos internos: composição de dois conjuntos em leque, espelhados
        # no mesmo plano YZ e ligados aos dois nós superiores.
        for x in x_grid[1:-1]:
            left_hub = self.service.create_node(x, module_width / 4, height * 3 / 4)
            right_hub = self.service.create_node(x, module_width * 3 / 4, height * 3 / 4)
            for node in (base_nodes[(x, 0.0)], top_nodes[(x, 0.0)], top_nodes[(x, module_width)]):
                add_w_member(node, left_hub.name, "brace")
            for node in (base_nodes[(x, module_width)], top_nodes[(x, 0.0)], top_nodes[(x, module_width)]):
                add_w_member(node, right_hub.name, "brace")

        # O peso próprio usa os pesos lineares calculados para todos os
        # elementos, tal como o comando ``selfweight`` com a opção "Todos".
        # Isso ocorre após a criação dos contraventamentos para incluí-los.
        action_service.replace_action_with_selfweight(
            "Peso próprio",
            self.service.member_selfweights(),
        )

        self.service.set_reference_axes({
            "X": tuple(
                ReferenceAxis(label, y)
                for label, y in zip(("A", "B"), y_grid)
            ),
            "Y": tuple(
                ReferenceAxis(str(index), x)
                for index, x in enumerate(x_grid, start=1)
            ),
            "Z": (
                ReferenceAxis("0", 0.0),
                ReferenceAxis(str(int(height * 100)), height),
            ),
        })

    def _create_galpao(self) -> None:
        model = self.service.model
        span_x = 12.0
        supports = (True, True, True, False, False, False)
        column_geometry = {"b": 250.0, "h": 500.0}
        beam_geometry = {"b": 200.0, "h": 400.0}
        truss_geometry = {"d": 100.0, "bf": 50.0, "t": 3.0}
        member_color = "#6e7781"
        column_tops: dict[tuple[float, float], str] = {}
        column_nodes: dict[tuple[float, float, int], str] = {}

        def configure_member(
            name: str,
            material: str,
            section: str,
            profile: str,
            geometry: dict[str, float],
            color: str,
        ) -> None:
            model.update_bar_material(name, material, model.materials[material])
            model.update_bar_section(name, section)
            model.update_member_profile(name, profile, geometry)
            model.update_member_color(name, color)

        # Galpão inicial: duas linhas de pilares em x, com cinco eixos em y.
        # As coordenadas do modelo são expressas em metros; a seção permanece
        # em milímetros, conforme o restante do sistema de seções.
        for x in (0.0, span_x):
            for y in (0.0, 5.0, 10.0, 15.0, 20.0):
                base = self.service.create_node(x, y, 0.0)
                middle = self.service.create_node(x, y, 3.0)
                top = self.service.create_node(x, y, 6.0)
                column_tops[(x, y)] = top.name
                column_nodes[(x, y, 0)] = base.name
                column_nodes[(x, y, 1)] = middle.name
                column_nodes[(x, y, 2)] = top.name
                model.update_node_supports(base.name, supports)
                for start, end in ((base, middle), (middle, top)):
                    member = self.service.create_member(start.name, end.name)
                    configure_member(
                        member.name,
                        "Concreto Estrutural",
                        "Retangular",
                        "R 250 x 500",
                        column_geometry,
                        member_color,
                    )
                    model.update_member_rotation(member.name, 90)

        column_y_positions = (0.0, 5.0, 10.0, 15.0, 20.0)
        for x in (0.0, span_x):
            for level in range(3):
                for start_y, end_y in zip(column_y_positions, column_y_positions[1:]):
                    beam = self.service.create_member(
                        column_nodes[(x, start_y, level)],
                        column_nodes[(x, end_y, level)],
                    )
                    configure_member(
                        beam.name,
                        "Concreto Estrutural",
                        "Retangular",
                        "R 200 x 400",
                        beam_geometry,
                        member_color,
                    )

        cantilever_geometry = {"d": 200.0, "bf": 100.0, "tw": 4.3, "tf": 5.2}
        cantilever_tip_x = -2.0
        cantilever_tip_z = 3.2
        cantilever_break_ratio = 0.20
        cantilever_break_x = cantilever_tip_x * cantilever_break_ratio
        overhang_purlin_nodes: dict[tuple[float, float], str] = {}
        for y in column_y_positions:
            start = model.nodes[column_nodes[(0.0, y, 1)]]
            middle = self.service.create_node(
                start.x + (cantilever_tip_x - start.x) * cantilever_break_ratio,
                y,
                start.z + (cantilever_tip_z - start.z) * cantilever_break_ratio,
            )
            tip = self.service.create_node(cantilever_tip_x, y, cantilever_tip_z)
            overhang_purlin_nodes[(cantilever_break_x, y)] = middle.name
            overhang_purlin_nodes[(cantilever_tip_x, y)] = tip.name
            for start_name, end_name in ((start.name, middle.name), (middle.name, tip.name)):
                cantilever = self.service.create_member(start_name, end_name)
                configure_member(
                    cantilever.name,
                    "Aço Estrutural",
                    "W Laminado",
                    "W 200 x 15.0",
                    cantilever_geometry,
                    member_color,
                )

        # Cada treliça tem duas águas com inclinação de 5% a partir das
        # extremidades, sobre um vão de 12 m dividido em módulos de 0,5 m.
        panel_length = 0.5
        panel_count = int(span_x / panel_length)
        eave_height = 6.5
        roof_slope = 0.05
        roof_nodes: dict[tuple[float, float], str] = {}
        truss_lower_nodes: dict[tuple[float, float], str] = {}
        for y in (0.0, 5.0, 10.0, 15.0, 20.0):
            bottom_nodes = [column_tops[(0.0, y)]]
            for index in range(1, panel_count):
                bottom_nodes.append(self.service.create_node(index * panel_length, y, 6.0).name)
            bottom_nodes.append(column_tops[(span_x, y)])
            for index, name in enumerate(bottom_nodes):
                truss_lower_nodes[(index * panel_length, y)] = name
            top_nodes = [
                self.service.create_node(
                    index * panel_length,
                    y,
                    eave_height + roof_slope * min(
                        index * panel_length, span_x - index * panel_length
                    ),
                ).name
                for index in range(panel_count + 1)
            ]
            for index, name in enumerate(top_nodes):
                roof_nodes[(index * panel_length, y)] = name

            def add_truss_member(
                start: str, end: str, rotation: int, color: str
            ) -> None:
                member = self.service.create_member(start, end)
                configure_member(
                    member.name,
                    "Aço Estrutural",
                    "U Formado",
                    "U 100 x 50 x 3",
                    truss_geometry,
                    color,
                )
                model.update_member_rotation(member.name, rotation)

            for index in range(panel_count):
                add_truss_member(
                    bottom_nodes[index], bottom_nodes[index + 1],
                    90, member_color,
                )
                add_truss_member(
                    top_nodes[index], top_nodes[index + 1],
                    270, member_color,
                )
            for index in range(panel_count + 1):
                add_truss_member(
                    bottom_nodes[index],
                    top_nodes[index],
                    180 if index > panel_count // 2 else 0,
                    member_color,
                )
            for index in range(panel_count):
                if index % 2 == 0:
                    add_truss_member(
                        bottom_nodes[index], top_nodes[index + 1],
                        270, member_color,
                    )
                else:
                    add_truss_member(
                        top_nodes[index], bottom_nodes[index + 1],
                        270, member_color,
                    )

        purlin_geometry = {"d": 127.0, "bf": 50.0, "c": 17.0, "t": 3.0}
        purlin_profile = "C Laminado 127 x 50 x 17 x 3.00"
        overhang_slope = 0.10
        overhang_purlin_rotation = (180 + round(degrees(atan(overhang_slope)))) % 360
        purlin_x_positions = range(0, int(span_x) + 1, 2)
        frame_y_positions = (0.0, 5.0, 10.0, 15.0, 20.0)
        roof_angle = round(degrees(atan(roof_slope)))
        purlin_nodes: dict[tuple[float, float], str] = {}
        for x in (cantilever_break_x, cantilever_tip_x):
            for start_y, end_y in zip(frame_y_positions, frame_y_positions[1:]):
                segment_nodes = [overhang_purlin_nodes[(x, start_y)]]
                for part in (1, 2):
                    y = start_y + (end_y - start_y) * part / 3.0
                    intermediate = self.service.create_node(x, y, 3.0 - overhang_slope * x)
                    overhang_purlin_nodes[(x, y)] = intermediate.name
                    segment_nodes.append(intermediate.name)
                segment_nodes.append(overhang_purlin_nodes[(x, end_y)])
                for start_node, end_node in zip(segment_nodes, segment_nodes[1:]):
                    purlin = self.service.create_member(start_node, end_node)
                    configure_member(
                        purlin.name,
                        "Aço Estrutural",
                        "C Formado",
                        purlin_profile,
                        purlin_geometry,
                        member_color,
                    )
                    model.update_member_rotation(purlin.name, overhang_purlin_rotation)

        for x in purlin_x_positions:
            if x < span_x / 2.0:
                purlin_rotation = (-roof_angle) % 360
            elif x > span_x / 2.0:
                purlin_rotation = 180 + roof_angle
            else:
                purlin_rotation = 0
            for start_y, end_y in zip(frame_y_positions, frame_y_positions[1:]):
                segment_nodes = [roof_nodes[(float(x), start_y)]]
                intermediate_y_positions = (
                    start_y + 0.6,
                    start_y + (end_y - start_y) / 3.0,
                    start_y + (end_y - start_y) * 2.0 / 3.0,
                    end_y - 0.6,
                )
                for y in intermediate_y_positions:
                    intermediate = self.service.create_node(
                        float(x),
                        y,
                        eave_height + roof_slope * min(x, span_x - x),
                    )
                    purlin_nodes[(float(x), y)] = intermediate.name
                    segment_nodes.append(intermediate.name)
                segment_nodes.append(roof_nodes[(float(x), end_y)])

                for start_node, end_node in zip(segment_nodes, segment_nodes[1:]):
                    purlin = self.service.create_member(start_node, end_node)
                    configure_member(
                        purlin.name,
                        "Aço Estrutural",
                        "C Formado",
                        purlin_profile,
                        purlin_geometry,
                        member_color,
                    )
                    model.update_member_rotation(purlin.name, purlin_rotation)

        ridge_x = span_x / 2.0
        internal_purlin_y_positions = tuple(
            start_y + (end_y - start_y) * part / 3.0
            for start_y, end_y in zip(frame_y_positions, frame_y_positions[1:])
            for part in (1, 2)
        )
        l_bracing_geometry = {"d": 30.0, "bf": 30.0, "t": 3.0}
        for x in map(float, purlin_x_positions):
            if x in (0.0, span_x):
                continue
            for start_y, end_y in zip(frame_y_positions, frame_y_positions[1:]):
                for brace_y, support_y in (
                    (start_y + 0.6, start_y),
                    (end_y - 0.6, end_y),
                ):
                    knee_brace = self.service.create_member(
                        purlin_nodes[(x, brace_y)],
                        truss_lower_nodes[(x, support_y)],
                    )
                    configure_member(
                        knee_brace.name,
                        "Aço Estrutural",
                        "L Formado",
                        "L Formado 30 x 30 x 3.00",
                        l_bracing_geometry,
                        member_color,
                    )

        for y in internal_purlin_y_positions:
            l_brace = self.service.create_member(
                overhang_purlin_nodes[(cantilever_break_x, y)],
                overhang_purlin_nodes[(cantilever_tip_x, y)],
            )
            configure_member(
                l_brace.name,
                "Aço Estrutural",
                "L Formado",
                "L Formado 30 x 30 x 3.00",
                l_bracing_geometry,
                member_color,
            )
        for x in (ridge_x - 2.0, ridge_x + 2.0):
            for y in internal_purlin_y_positions:
                l_brace = self.service.create_member(
                    purlin_nodes[(ridge_x, y)], purlin_nodes[(x, y)]
                )
                configure_member(
                    l_brace.name,
                    "Aço Estrutural",
                    "L Formado",
                    "L Formado 30 x 30 x 3.00",
                    l_bracing_geometry,
                    member_color,
                )

        bracing_geometry = {"d": 10.0}
        for frame_index, frame_y in enumerate(frame_y_positions):
            adjacent_purlin_y_positions = []
            if frame_index > 0:
                previous_y = frame_y_positions[frame_index - 1]
                adjacent_purlin_y_positions.append(
                    previous_y + (frame_y - previous_y) * 2.0 / 3.0
                )
            if frame_index < len(frame_y_positions) - 1:
                next_y = frame_y_positions[frame_index + 1]
                adjacent_purlin_y_positions.append(
                    frame_y + (next_y - frame_y) / 3.0
                )
            for x in (ridge_x - 2.0, ridge_x + 2.0):
                for y in adjacent_purlin_y_positions:
                    brace = self.service.create_member(
                        roof_nodes[(ridge_x, frame_y)], purlin_nodes[(x, y)]
                    )
                    configure_member(
                        brace.name,
                        "Aço Estrutural",
                        "Barra Circular",
                        "Barra Redonda Ø10 mm",
                        bracing_geometry,
                        member_color,
                    )

        for start_y, end_y in ((frame_y_positions[0], frame_y_positions[1]),
                               (frame_y_positions[-2], frame_y_positions[-1])):
            for start_x, end_x in zip(purlin_x_positions, tuple(purlin_x_positions)[1:]):
                for diagonal_start_x, diagonal_end_x in (
                    (float(start_x), float(end_x)),
                    (float(end_x), float(start_x)),
                ):
                    brace = self.service.create_member(
                        roof_nodes[(diagonal_start_x, start_y)],
                        roof_nodes[(diagonal_end_x, end_y)],
                    )
                    configure_member(
                        brace.name,
                        "Aço Estrutural",
                        "Barra Circular",
                        "Barra Redonda Ø10 mm",
                        bracing_geometry,
                        member_color,
                    )

        left_purlin_x_positions = tuple(
            float(x) for x in purlin_x_positions if x < ridge_x
        )
        right_purlin_x_positions = tuple(
            float(x) for x in purlin_x_positions if x > ridge_x
        )
        adjacent_purlin_pairs = (
            *zip(reversed(left_purlin_x_positions), reversed(left_purlin_x_positions[:-1])),
            *zip(right_purlin_x_positions, right_purlin_x_positions[1:]),
        )
        for start_x, end_x in adjacent_purlin_pairs:
            for y in internal_purlin_y_positions:
                tie = self.service.create_member(
                    purlin_nodes[(start_x, y)], purlin_nodes[(end_x, y)]
                )
                configure_member(
                    tie.name,
                    "Aço Estrutural",
                    "Barra Circular",
                    "Barra Redonda Ø10 mm",
                    bracing_geometry,
                    member_color,
                )
