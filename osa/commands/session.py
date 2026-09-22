"""Máquina de estados dos comandos de modelagem."""

from __future__ import annotations

from dataclasses import dataclass
from math import atan, degrees

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
