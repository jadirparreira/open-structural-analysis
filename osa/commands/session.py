"""Máquina de estados dos comandos de modelagem."""

from __future__ import annotations

from dataclasses import dataclass

from osa.services import ModelService

from .parser import parse_coordinates, parse_member_nodes


@dataclass(frozen=True, slots=True)
class CommandResponse:
    command: str
    message: str
    level: str = "instruction"
    model_changed: bool = False


class CommandSession:
    def __init__(self, service: ModelService) -> None:
        self.service = service
        self.pending: str | None = None

    def cancel(self) -> None:
        self.pending = None

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

        command = value.casefold()
        if command == "node":
            self.pending = "node"
            return CommandResponse(value, "Informe as coordenadas do nó em X,Y,Z")
        if command == "member":
            self.pending = "member"
            return CommandResponse(value, "Informe o nó inicial e final A,B")
        if command == "portico":
            try:
                self._create_portico()
                return CommandResponse(value, "Pórtico criado.", "success", True)
            except ValueError as error:
                return CommandResponse(value, str(error), "error")
        return CommandResponse(value, "Não é um comando válido", "error")

    def _create_portico(self) -> None:
        model = self.service.model
        supports = (True, True, True, False, False, False)
        column_geometry = {"b": 250.0, "h": 500.0}
        truss_geometry = {"d": 100.0, "bf": 50.0, "t": 3.0}
        column_tops: dict[tuple[float, float], str] = {}

        def configure_member(
            name: str,
            material: str,
            section: str,
            profile: str,
            geometry: dict[str, float],
        ) -> None:
            model.update_bar_material(name, material, model.materials[material])
            model.update_bar_section(name, section)
            model.update_member_profile(name, profile, geometry)

        # Galpão inicial: duas linhas de pilares em x, com cinco eixos em y.
        # As coordenadas do modelo são expressas em metros; a seção permanece
        # em milímetros, conforme o restante do sistema de seções.
        for x in (0.0, 10.0):
            for y in (0.0, 5.0, 10.0, 15.0, 20.0):
                base = self.service.create_node(x, y, 0.0)
                top = self.service.create_node(x, y, 6.0)
                column_tops[(x, y)] = top.name
                model.update_node_supports(base.name, supports)
                member = self.service.create_member(base.name, top.name)
                configure_member(
                    member.name, "Concreto Estrutural", "Retangular", "R 250 x 500", column_geometry
                )

        # Com 500 mm de altura, um módulo horizontal de 500 mm produz
        # diagonais exatamente a 45 graus. Cada treliça tem 20 módulos.
        panel_count = 20
        panel_length = 0.5
        for y in (0.0, 5.0, 10.0, 15.0, 20.0):
            bottom_nodes = [column_tops[(0.0, y)]]
            for index in range(1, panel_count):
                bottom_nodes.append(self.service.create_node(index * panel_length, y, 6.0).name)
            bottom_nodes.append(column_tops[(10.0, y)])
            top_nodes = [
                self.service.create_node(index * panel_length, y, 6.5).name
                for index in range(panel_count + 1)
            ]

            def add_truss_member(start: str, end: str) -> None:
                member = self.service.create_member(start, end)
                configure_member(
                    member.name, "Aço Estrutural", "U Formado", "U 100 x 50 x 3", truss_geometry
                )

            for index in range(panel_count):
                add_truss_member(bottom_nodes[index], bottom_nodes[index + 1])
                add_truss_member(top_nodes[index], top_nodes[index + 1])
            for index in range(panel_count + 1):
                add_truss_member(bottom_nodes[index], top_nodes[index])
            for index in range(panel_count):
                if index % 2 == 0:
                    add_truss_member(bottom_nodes[index], top_nodes[index + 1])
                else:
                    add_truss_member(top_nodes[index], bottom_nodes[index + 1])
