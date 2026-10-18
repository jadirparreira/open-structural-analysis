"""Planar visual references; geometry is immutable and independent of the source file."""

from dataclasses import dataclass
from math import isfinite
from struct import iter_unpack


@dataclass(frozen=True, slots=True, eq=False)
class ReferenceGeometry:
    # Little-endian float64 XY coordinates. Every 2/3 vertices form a line/triangle.
    lines: bytes = b""
    triangles: bytes = b""
    # None identifies legacy references; empty bytes mean there are no CAD snaps.
    snap_endpoints: bytes | None = None
    snap_centers: bytes | None = None

    MAX_BYTES = 64 * 1024 * 1024

    def __post_init__(self):
        if sum(len(buffer or b"") for buffer in (
            self.lines, self.triangles, self.snap_endpoints, self.snap_centers,
        )) > self.MAX_BYTES:
            raise ValueError("A referência excede o limite de geometria (64 MB).")
        for buffer, stride in (
            (self.lines, 32), (self.triangles, 48),
            (self.snap_endpoints or b"", 16), (self.snap_centers or b"", 16),
        ):
            if not isinstance(buffer, bytes) or len(buffer) % stride:
                raise ValueError("Geometria de referência inválida.")
            if any(not isfinite(value) for (value,) in iter_unpack("<d", buffer)):
                raise ValueError("A referência contém coordenadas inválidas.")


@dataclass(frozen=True, slots=True)
class DrawingReference:
    id: str
    name: str
    geometry: ReferenceGeometry
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0)
    plane: str = "XY"
    visible: bool = True

    def __post_init__(self):
        if not self.id or not self.name.strip():
            raise ValueError("Informe a identidade e o nome da referência.")
        if self.plane not in ("XY", "XZ", "YZ"):
            raise ValueError("Plano de referência inválido.")
        if len(self.origin) != 3 or not all(isfinite(v) for v in self.origin):
            raise ValueError("Informe coordenadas finitas para a origem da referência.")
