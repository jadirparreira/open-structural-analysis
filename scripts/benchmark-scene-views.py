"""Measure scene switches without modifying the project or user settings.

Example: .venv/bin/python scripts/benchmark-scene-views.py model.osa --offscreen
Offscreen measures CPU costs; omit it to also exercise the native viewport.
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
    parser.add_argument("project", type=Path)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--solid", action="store_true")
    parser.add_argument(
        "--prepared", action="store_true",
        help="Emulate opening: prepare scene geometry and prewarm saved views before timing switches",
    )
    parser.add_argument("--toggle-solids", action="store_true", help="Measure analytical/solid toggles in each view")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("Informe pelo menos uma rodada.")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtWidgets import QApplication

    from osa.model import StructuralModel
    from osa.rendering.batched_renderer import prepare_scene_geometry
    from osa.rendering.scene_batched import StructureScene

    app = QApplication([])
    model = StructuralModel()
    model.load(args.project.resolve())
    model.select_scene_view("Completo")
    scene = StructureScene()
    scene.resize(1200, 800)
    scene.set_solid_members_visible(args.solid and not args.toggle_solids)
    scene.show()
    prepared_geometry = prepare_scene_geometry(
        model, solid_members_visible=args.solid and not args.toggle_solids,
        solid_positioning_enabled=False,
    ) if args.prepared else None
    scene.render_model(model, preserve_camera=False, prepared_geometry=prepared_geometry)
    app.processEvents()
    measurements = (
        {f"{name}:{mode}": [] for name in model.scene_views for mode in ("solid", "analytical")}
        if args.toggle_solids else {name: [] for name in model.scene_views}
    )
    try:
        for _ in range(args.rounds):
            for name in (*tuple(model.scene_views)[1:], "Completo"):
                model.select_scene_view(name)
                if args.toggle_solids:
                    scene.render_model(model)
                    app.processEvents()
                    for visible, mode in ((True, "solid"), (False, "analytical")):
                        started = perf_counter()
                        scene.set_solid_members_visible(visible)
                        app.processEvents()
                        measurements[f"{name}:{mode}"].append(round((perf_counter() - started) * 1000, 1))
                    continue
                started = perf_counter()
                scene.render_model(model)
                app.processEvents()
                measurements[name].append(round((perf_counter() - started) * 1000, 1))
        report = {
            "platform": QApplication.platformName(),
            "solid": args.solid,
            "prepared": args.prepared,
            "operation": "solid-toggle" if args.toggle_solids else "scene-view",
            "nodes": len(model.nodes),
            "members": len(model.bars),
            "switch_ms": measurements,
            "median_ms": {name: round(median(values), 1) for name, values in measurements.items()},
            "p95_ms": {name: round(_percentile(values, 0.95), 1) for name, values in measurements.items()},
            "first_switch_ms": {name: round(values[0], 1) for name, values in measurements.items()},
            "warm_median_ms": {
                name: round(median(values[1:] or values), 1) for name, values in measurements.items()
            },
            "warm_p95_ms": {
                name: round(_percentile(values[1:] or values, 0.95), 1)
                for name, values in measurements.items()
            },
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        print(encoded, flush=True)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
    finally:
        scene.close()
    return 0


def _percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile for small benchmark samples."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    fraction = position - lower
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


if __name__ == "__main__":
    raise SystemExit(main())
