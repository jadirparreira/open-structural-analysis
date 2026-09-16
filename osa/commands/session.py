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
        coordinates = [
            (2, -2, 0), (-2, -2, 0), (-2, 2, 0), (2, 2, 0),
            (2, -2, 4), (-2, -2, 4), (-2, 2, 4), (2, 2, 4),
        ]
        names = [self.service.create_node(*point).name for point in coordinates]
        for name in names[:4]:
            self.service.model.update_node_supports(name, (True, True, True, False, False, False))
        for start, end in [(0, 4), (1, 5), (2, 6), (3, 7), (4, 5), (5, 6), (6, 7), (7, 4)]:
            self.service.create_member(names[start], names[end])
