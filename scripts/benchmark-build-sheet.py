"""Create a temporary project copy with three real projected views for benchmarking.

Example: .venv/bin/python scripts/benchmark-build-sheet.py input.osa /tmp/osa-sheet-benchmark.osa
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/osa-benchmark-matplotlib")

from osa.model import StructuralModel
from osa.ui.detailing_preview import DetailingViewPreview, _ViewGeometryCalculator
from osa.ui.detailing_viewport import _DetachedDetailingScene
from osa.ui.project_sheet import default_project_settings, default_project_sheet_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.project.resolve() == args.output.resolve():
        parser.error("A saída deve ser um arquivo diferente do projeto original.")
    data = json.loads(args.project.read_text(encoding="utf-8"))
    model = StructuralModel()
    model.load(args.project.resolve())
    calculator = _ViewGeometryCalculator()
    calculator._detail_scene = _DetachedDetailingScene(SimpleNamespace())
    views = []
    for plane, coordinate in (("XY", 0.0), ("XZ", 0.0), ("YZ", 0.0)):
        started = perf_counter()
        DetailingViewPreview.set_view(
            calculator, model, plane, coordinate, upper_offset_cm=50, lower_offset_cm=50,
            orientation="Superior para inferior", rotation_degrees=0,
        )
        segments = tuple(calculator._segments_2d)
        views.append({
            "name": plane, "projection": {"plane": plane, "coordinate": coordinate},
            "segments": segments, "segment_owners": tuple(calculator._segment_sources),
            "axes_visible": True, "scale_denominator": 150,
        })
        print(f"{plane}: {len(segments)} segmentos em {perf_counter() - started:.2f} s", flush=True)
    name = "Folha de teste"
    data["detailing_data"] = {"sheets": {
        "sheet_names": [name], "active_sheet": name,
        "sheet_settings": {name: default_project_sheet_settings(name)},
        "project_settings": default_project_settings(), "sheet_views": {name: views},
    }}
    args.output.write_text(json.dumps(data), encoding="utf-8")


if __name__ == "__main__":
    main()
