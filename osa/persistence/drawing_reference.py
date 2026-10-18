"""Compact embedded reference geometry; opening a project never reads external paths."""

import zlib
from base64 import b64decode, b64encode

from osa.domain.drawing_reference import DrawingReference, ReferenceGeometry


def dump_reference(reference: DrawingReference) -> dict:
    geometry = reference.geometry
    return {
        "id": reference.id, "name": reference.name,
        "origin": list(reference.origin), "plane": reference.plane, "visible": reference.visible,
        "geometry": {
            "encoding": "xy-f64le-zlib-v2", "line_bytes": len(geometry.lines),
            "triangle_bytes": len(geometry.triangles),
            "endpoint_bytes": None if geometry.snap_endpoints is None else len(geometry.snap_endpoints),
            "center_bytes": None if geometry.snap_centers is None else len(geometry.snap_centers),
            "data": b64encode(zlib.compress(
                geometry.lines + geometry.triangles + (geometry.snap_endpoints or b"") + (geometry.snap_centers or b""),
            )).decode("ascii"),
        },
    }


def load_reference(data: dict) -> DrawingReference:
    geometry = data["geometry"]
    encoding = geometry.get("encoding")
    if encoding not in ("xy-f64le-zlib-v1", "xy-f64le-zlib-v2"):
        raise ValueError("Formato de geometria de referência não reconhecido.")
    decompressor = zlib.decompressobj()
    raw = decompressor.decompress(b64decode(geometry["data"], validate=True), ReferenceGeometry.MAX_BYTES + 1)
    if len(raw) > ReferenceGeometry.MAX_BYTES or not decompressor.eof or decompressor.unused_data:
        raise ValueError("Geometria de referência inválida ou muito grande.")
    line_bytes = geometry["line_bytes"]
    if not isinstance(line_bytes, int) or not 0 <= line_bytes <= len(raw):
        raise ValueError("Geometria de referência inválida.")
    if encoding == "xy-f64le-zlib-v1":
        drawing = ReferenceGeometry(raw[:line_bytes], raw[line_bytes:])
    else:
        triangle_bytes = geometry["triangle_bytes"]
        endpoint_bytes = geometry["endpoint_bytes"]
        center_bytes = geometry["center_bytes"]
        counts = (line_bytes, triangle_bytes, endpoint_bytes, center_bytes)
        if any(count is not None and (not isinstance(count, int) or count < 0) for count in counts):
            raise ValueError("Geometria de referência inválida.")
        if triangle_bytes is None or sum(count or 0 for count in counts) != len(raw):
            raise ValueError("Geometria de referência inválida.")
        first = line_bytes + triangle_bytes
        second = first + (endpoint_bytes or 0)
        drawing = ReferenceGeometry(
            raw[:line_bytes], raw[line_bytes:first],
            None if endpoint_bytes is None else raw[first:second],
            None if center_bytes is None else raw[second:],
        )
    return DrawingReference(
        str(data["id"]), str(data["name"]), drawing,
        tuple(float(v) for v in data.get("origin", (0, 0, 0))),
        data.get("plane", "XY"), bool(data.get("visible", True)),
    )
