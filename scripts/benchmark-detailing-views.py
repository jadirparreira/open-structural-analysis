"""Benchmark the live detailing viewport separately from DXF line generation.

Examples:
  .venv/bin/python scripts/benchmark-detailing-views.py --offscreen
  .venv/bin/python scripts/benchmark-detailing-views.py model.osa --output /tmp/detailing.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", type=Path)
    parser.add_argument("--members", type=int, default=240)
    parser.add_argument("--views", type=int, default=4)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.members < 1 or args.views < 1:
        parser.error("Informe pelo menos uma barra e uma vista.")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/osa-benchmark-matplotlib")

    import numpy as np
    import pyvista as pv
    import vtk

    from osa.domain.entities import ReferenceAxis
    from osa.model import StructuralModel
    from osa.ui.detailing_preview import DetailingViewPreview, _ViewGeometryCalculator

    model = StructuralModel()
    if args.project is not None:
        if not args.project.is_file():
            parser.error(f"Arquivo de projeto não encontrado: {args.project}")
        model.load(args.project.resolve())
    else:
        for index in range(args.members):
            row, column = divmod(index, 20)
            x0, y = column * 5.0, row * 5.0
            start_name, end_name = f"N{index}A", f"N{index}B"
            model.add_node(start_name, x0, y, 0.0)
            model.add_node(end_name, x0 + 4.0, y, 0.0)
            member = model.add_bar(f"B{index}", start_name, end_name)
            model.update_bar_section(member.name, "Barra Retangular")
            model.update_member_profile(member.name, member.name, {"b": 100, "h": 200})
        model.set_reference_axes(
            {"Z": tuple(ReferenceAxis(str(index + 1), index * 0.5) for index in range(args.views))}
        )

    calculator = _ViewGeometryCalculator()
    calculator._mesh_cache_owner = model
    started = perf_counter()
    DetailingViewPreview._ensure_model_meshes(calculator, model)
    mesh_build_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    DetailingViewPreview._ensure_model_edge_meshes(calculator, model)
    edge_build_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    surfaces = pv.merge(calculator._solid_meshes, merge_points=False)
    edge_mesh = pv.merge(calculator._solid_edge_meshes or (), merge_points=False)
    merge_ms = (perf_counter() - started) * 1000

    plotter = pv.Plotter(off_screen=True, window_size=(1000, 720))
    plotter.set_background("white")
    plotter.enable_parallel_projection()
    plotter.add_mesh(
        surfaces,
        color="#ffffff",
        lighting=False,
        show_edges=False,
        pickable=False,
        reset_camera=False,
        render=False,
    )
    edge_actor = plotter.add_mesh(
        edge_mesh,
        color="#24292f",
        line_width=1.35,
        lighting=False,
        pickable=False,
        reset_camera=False,
        render=False,
    )
    mapper = edge_actor.GetMapper()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetResolveCoincidentTopologyLineOffsetParameters(0.0, 0.0)
    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
    plotter.show(auto_close=False, interactive=False)
    plotter.iren.interactor.SetInteractorStyle(vtk.vtkInteractorStyleUser())

    directions = {
        "ISO-SE": (1.0, -1.0, 1.0),
        "ISO-NE": (1.0, 1.0, 1.0),
        "ISO-NW": (-1.0, 1.0, 1.0),
        "ISO-SW": (-1.0, -1.0, 1.0),
    }
    selected_views = tuple(directions.items())[: min(args.views, len(directions))]
    points = np.asarray(surfaces.points, dtype=float)
    center = (points.min(axis=0) + points.max(axis=0)) / 2.0
    viewport_times = []
    for name, raw_direction in selected_views:
        direction = np.asarray(raw_direction, dtype=float)
        direction /= np.linalg.norm(direction)
        view_up = np.asarray((0.0, 0.0, 1.0), dtype=float)
        view_up -= np.dot(view_up, direction) * direction
        view_up /= np.linalg.norm(view_up)
        plotter.camera_position = (
            tuple(center + direction * max(surfaces.length, 1.0) * 2.0),
            tuple(center),
            tuple(view_up),
        )
        plotter.reset_camera_clipping_range()
        started = perf_counter()
        plotter.render()
        viewport_ms = (perf_counter() - started) * 1000
        viewport_times.append({"view": name, "render_ms": round(viewport_ms, 1)})

    pan_zoom_times = []
    for index in range(20):
        if index % 2:
            plotter.camera.parallel_scale *= 1.002
        else:
            shift = np.asarray((0.01, 0.01, 0.0))
            plotter.camera.position = np.asarray(plotter.camera.position) + shift
            plotter.camera.focal_point = np.asarray(plotter.camera.focal_point) + shift
        started = perf_counter()
        plotter.render()
        pan_zoom_times.append((perf_counter() - started) * 1000)

    export_times = []
    for name, direction in selected_views:
        started = perf_counter()
        DetailingViewPreview.set_view(
            calculator,
            model,
            name,
            0.0,
            upper_offset_cm=50.0,
            lower_offset_cm=50.0,
            orientation="Superior para inferior",
            rotation_degrees=0.0,
        )
        export_times.append(
            {
                "view": name,
                "generation_ms": round((perf_counter() - started) * 1000, 1),
                "segments": len(calculator._segments_2d),
            }
        )

    report = {
        "project": str(args.project.resolve()) if args.project else None,
        "members": len(model.bars),
        "viewport_setup_ms": round(mesh_build_ms + edge_build_ms + merge_ms, 1),
        "mesh_build_ms": round(mesh_build_ms, 1),
        "edge_build_ms": round(edge_build_ms, 1),
        "mesh_merge_ms": round(merge_ms, 1),
        "viewport_render_ms": viewport_times,
        "pan_zoom_median_ms": round(median(pan_zoom_times), 1),
        "pan_zoom_p95_ms": round(float(np.percentile(pan_zoom_times, 95)), 1),
        "dxf_vector_generation": export_times,
        "image_captures": 0,
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded, flush=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    plotter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
