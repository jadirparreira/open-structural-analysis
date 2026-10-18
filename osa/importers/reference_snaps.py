"""Extract CAD snap features before dashing, curve tessellation and hatch generation."""

from math import isclose, tau
from struct import pack

from osa.domain.drawing_reference import ReferenceGeometry


class ReferenceSnapCollector:
    def __init__(self, scale):
        self.scale = scale
        self.endpoints = bytearray()
        self.centers = bytearray()
        self._seen = {"endpoint": set(), "center": set()}

    def _add(self, point, kind):
        xy = (float(point[0]) * self.scale, float(point[1]) * self.scale)
        if xy in self._seen[kind]:
            return
        self._seen[kind].add(xy)
        target = self.endpoints if kind == "endpoint" else self.centers
        target.extend(pack("<dd", *xy))
        if len(self.endpoints) + len(self.centers) > ReferenceGeometry.MAX_BYTES:
            raise ValueError("A referência excede o limite de pontos de captura.")

    def collect(self, entity):
        kind = entity.dxftype()
        if kind == "LINE":
            start, end = entity.dxf.start, entity.dxf.end
            self._add(start, "endpoint")
            self._add(end, "endpoint")
            self._add((start + end) * 0.5, "center")
        elif kind == "POINT":
            self._add(entity.dxf.location, "endpoint")
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            if kind == "POLYLINE" and not (entity.is_2d_polyline or entity.is_3d_polyline):
                return
            for segment in entity.virtual_entities():
                self.collect(segment)
        elif kind in ("ARC", "CIRCLE"):
            self._add(entity.ocs().to_wcs(entity.dxf.center), "center")
            if kind == "ARC":
                self._add(entity.start_point, "endpoint")
                self._add(entity.end_point, "endpoint")
                self._add(tuple(entity.vertices(entity.angles(3)))[1], "center")
        elif kind == "ELLIPSE":
            self._add(entity.dxf.center, "center")
            span = (entity.dxf.end_param - entity.dxf.start_param) % tau
            if not isclose(span, 0.0, abs_tol=1e-9):
                self._add(entity.start_point, "endpoint")
                self._add(entity.end_point, "endpoint")
                self._add(tuple(entity.vertices(entity.params(3)))[1], "center")
        elif kind == "SPLINE":
            curve = entity.construction_tool()
            parameters = tuple(curve.params(2))
            if not entity.closed:
                self._add(curve.point(parameters[0]), "endpoint")
                self._add(curve.point(parameters[-1]), "endpoint")
            self._add(curve.point(parameters[1]), "center")
