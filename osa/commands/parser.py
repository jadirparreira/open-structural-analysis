"""Conversores de argumentos da barra de comandos."""


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
