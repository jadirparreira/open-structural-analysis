"""Convert modelspace to batched monochrome primitives, resolving CAD line/hatch patterns."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from struct import pack
from time import perf_counter, sleep
from uuid import uuid4

import ezdxf
from ezdxf import path as dxf_path
from ezdxf import units
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.backend import Backend
from ezdxf.addons.drawing.config import Configuration, HatchPolicy, ImagePolicy, LinePolicy
from ezdxf.render import hatching

from osa.domain.drawing_reference import DrawingReference, ReferenceGeometry

from .dwg_converter import read_dwg
from .reference_snaps import ReferenceSnapCollector


@dataclass(frozen=True)
class ImportResult:
    reference: DrawingReference
    warnings: tuple[str, ...]


class _GeometryBackend(Backend):
    def __init__(self, scale):
        super().__init__()
        self.scale = scale
        self.lines = bytearray()
        self.triangles = bytearray()
        self.last_yield = perf_counter()
        self.images = False

    def _append(self, buffer, vertices):
        for vertex in vertices:
            buffer.extend(pack("<dd", vertex[0] * self.scale, vertex[1] * self.scale))
        if len(self.lines) + len(self.triangles) > ReferenceGeometry.MAX_BYTES:
            raise ValueError("A referência excede o limite de geometria (64 MB).")
        if perf_counter() - self.last_yield > 0.008:
            sleep(0.001)  # Let Qt animate while a large document is being converted.
            self.last_yield = perf_counter()

    def set_background(self, color):
        pass

    def draw_point(self, pos, properties):
        radius = 0.0005 / self.scale
        self.draw_line((pos[0] - radius, pos[1]), (pos[0] + radius, pos[1]), properties)

    def draw_line(self, start, end, properties):
        self._append(self.lines, (start, end))

    def draw_solid_lines(self, lines, properties):
        for start, end in lines:
            self.draw_line(start, end, properties)

    def draw_filled_paths(self, paths, properties):
        # Triangulate the whole group together, preserving holes in hatches/text.
        for triangle in dxf_path.triangulate(
            (path.to_path() for path in paths), self.config.max_flattening_distance,
        ):
            self._append(self.triangles, triangle)

    def draw_filled_polygon(self, points, properties):
        polygon = dxf_path.from_vertices(points.vertices(), close=True)
        for triangle in dxf_path.triangulate((polygon,), self.config.max_flattening_distance):
            self._append(self.triangles, triangle)

    def draw_image(self, image_data, properties):
        self.images = True

    def clear(self):
        self.lines.clear()
        self.triangles.clear()


class _ReferenceFrontend(Frontend):
    def __init__(self, *args, **kwargs):
        self.skipped = Counter()
        self.messages = set()
        super().__init__(*args, **kwargs)
        self.snap_collector = ReferenceSnapCollector(self.pipeline.backend.scale)

    def draw_entity(self, entity, properties):
        # Frontend traverses visible INSERT children in world coordinates, so
        # block transformations and hidden layers are shared with the drawing.
        self.snap_collector.collect(entity)
        super().draw_entity(entity, properties)

    def skip_entity(self, entity, msg):
        # Hidden layers are intentional, not failed imports.
        if "invisible" not in msg.lower():
            self.skipped[entity.dxftype()] += 1

    def log_message(self, message):
        self.messages.add(str(message))

    def draw_hatch_pattern(self, polygon, paths, properties):
        """Stream hatch strokes in bounded batches and never silently truncate a hatch."""
        properties.linetype_pattern = ()
        started = perf_counter()

        def timed_out():
            if perf_counter() - started > self.config.hatching_timeout:
                raise ValueError("A hachura é muito complexa para importar. Simplifique o padrão no CAD.")
            return False

        batch = []
        ocs = polygon.ocs()
        elevation = polygon.dxf.elevation.z
        try:
            baselines = hatching.pattern_baselines(
                polygon, min_hatch_line_distance=self.config.min_hatch_line_distance, jiggle_origin=True,
            )
            for baseline in baselines:
                for span in hatching.hatch_paths(baseline, paths, timed_out):
                    strokes = baseline.pattern_renderer(span.distance).render(span.start, span.end)
                    for start, end in strokes:
                        if ocs.transform:
                            start = ocs.to_wcs((start.x, start.y, elevation))
                            end = ocs.to_wcs((end.x, end.y, elevation))
                        batch.append((start, end))
                        if len(batch) >= 2048:
                            self.pipeline.draw_solid_lines(batch, properties)
                            batch.clear()
                            timed_out()
            if batch:
                self.pipeline.draw_solid_lines(batch, properties)
        except hatching.DenseHatchingLinesError as error:
            raise ValueError("O espaçamento da hachura é muito pequeno para importar. Ajuste-o no CAD.") from error


def import_drawing_reference(filename: str | Path) -> ImportResult:
    filename = Path(filename)
    extension = filename.suffix.lower()
    warnings = []
    if extension == ".dwg":
        document, conversion_warnings = read_dwg(filename)
        warnings.extend(conversion_warnings)
    elif extension == ".dxf":
        try:
            document = ezdxf.readfile(filename)
        except (OSError, ezdxf.DXFError) as error:
            raise ValueError("Não foi possível ler o DXF. Verifique o arquivo e sua integridade.") from error
    else:
        raise ValueError("Selecione um arquivo DXF ou DWG.")
    source_units = int(document.header.get("$INSUNITS", 0))
    if source_units == 0:
        scale = 1.0
        warnings.append("O desenho não informa unidades; foi considerado 1 unidade = 1 metro.")
    else:
        scale = units.conversion_factor(source_units, units.M)
    backend = _GeometryBackend(scale)
    config = Configuration(
        line_policy=LinePolicy.ACCURATE, hatch_policy=HatchPolicy.NORMAL,
        image_policy=ImagePolicy.DISPLAY,
        max_flattening_distance=0.001 / scale,
        min_dash_length=0.00001 / scale,
        min_hatch_line_distance=0.00001 / scale,
        pdsize=0.001 / scale,
    )
    frontend = _ReferenceFrontend(RenderContext(document), backend, config=config)
    frontend.draw_layout(document.modelspace())
    snaps = frontend.snap_collector
    geometry = ReferenceGeometry(
        bytes(backend.lines), bytes(backend.triangles), bytes(snaps.endpoints), bytes(snaps.centers),
    )
    if not geometry.lines and not geometry.triangles:
        raise ValueError("O desenho não contém geometria visível no espaço de modelo.")
    if frontend.skipped:
        warnings.append("Entidades não importadas: " + ", ".join(
            f"{kind} ({count})" for kind, count in sorted(frontend.skipped.items())
        ) + ".")
    if backend.images:
        warnings.append("Imagens raster externas não são importadas nesta versão.")
    if frontend.messages:
        warnings.append("Avisos do desenho: " + "; ".join(sorted(frontend.messages)))
    if document.modelspace().query("INSERT"):
        xrefs = [block.name for block in document.blocks if block.block.is_xref]
        if xrefs:
            warnings.append("Referências externas não incorporadas ao desenho: " + ", ".join(xrefs))
    # Enforce planarity by intentionally using the top-view XY projection, just
    # like the drawing frontend. The original CAD origin is never recentered.
    return ImportResult(DrawingReference(uuid4().hex, filename.name, geometry), tuple(warnings))
