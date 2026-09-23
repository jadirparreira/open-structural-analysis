"""Conversores de argumentos da barra de comandos."""

import math


def parse_coordinates(text: str) -> tuple[float, float, float]:
    parts = [part.strip().replace(",", ".") for part in text.split(";")] if ";" in text else [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ValueError("Informe as coordenadas no formato X,Y,Z.")
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except ValueError as error:
        raise ValueError("Informe as coordenadas no formato X,Y,Z.") from error


def parse_member_nodes(text: str) -> tuple[str, str]:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("Informe o nó inicial e final no formato A,B.")
    return parts[0], parts[1]


def parse_load_value(text: str) -> float:
    """Lê uma intensidade de carga aceitando vírgula ou ponto decimal."""
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as error:
        raise ValueError("Informe um valor numérico para a força.") from error
    if not math.isfinite(value):
        raise ValueError("Informe um valor numérico finito para a força.")
    return value


def parse_distributed_force(text: str) -> tuple[float, float]:
    """Lê uma carga uniforme ou variável, separada por ponto e vírgula."""
    values = [value.strip() for value in text.split(";")]
    if len(values) not in (1, 2) or not all(values):
        raise ValueError("Informe a carga como valor ou inicial;final.")
    initial = parse_load_value(values[0])
    final = parse_load_value(values[-1])
    return initial, final
