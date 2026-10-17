"""Local member frame shared by analysis and presentation (global Z up)."""

from math import cos, hypot, radians, sin


def member_basis(start, end, rotation: float = 0):
    x, y, z = end.x - start.x, end.y - start.y, end.z - start.z
    length = hypot(x, y, z)
    if length <= 1e-12:
        return None
    x, y, z = x / length, y / length, z / length
    yx, yy, yz = (z, 0.0, -x) if abs(z) > 0.99 else (-y, x, 0.0)
    y_length = hypot(yx, yy, yz)
    local_y = (yx / y_length, yy / y_length, yz / y_length)
    yx, yy, yz = local_y
    local_z = (y * yz - z * yy, z * yx - x * yz, x * yy - y * yx)
    if rotation == 0:
        return (x, y, z), local_y, local_z
    cosine, sine = cos(radians(rotation)), sin(radians(rotation))
    return (
        (x, y, z),
        tuple(a * cosine + b * sine for a, b in zip(local_y, local_z)),
        tuple(b * cosine - a * sine for a, b in zip(local_y, local_z)),
    )
