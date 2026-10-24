"""Measure opening and navigation responsiveness for detailing view previews.

Examples:
  .venv/bin/python scripts/benchmark-detailing-views.py --offscreen
  .venv/bin/python scripts/benchmark-detailing-views.py model.osa --offscreen
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import median
from time import perf_counter, sleep

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
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/osa-benchmark-matplotlib")

    from PySide6.QtWidgets import QApplication, QWidget

    from osa.domain.entities import ReferenceAxis
    from osa.model import StructuralModel
    from osa.ui.dialogs import DetailingViewsDialog

    app = QApplication([])
    model = StructuralModel()
    if args.project is not None:
        if not args.project.is_file():
            parser.error(f"Arquivo de projeto não encontrado: {args.project}")
        model.load(args.project.resolve())
    else:
        for index in range(args.members):
            row, column = divmod(index, 20)
            x0, y, z = column * 5.0, row * 5.0, 0.0
            start_name, end_name = f"N{index}A", f"N{index}B"
            model.add_node(start_name, x0, y, z)
            model.add_node(end_name, x0 + 4.0, y, z)
            member = model.add_bar(f"B{index}", start_name, end_name)
            model.update_bar_section(member.name, "Barra Retangular")
            model.update_member_profile(member.name, member.name, {"b": 100, "h": 200})
        model.set_reference_axes(
            {
                "Z": tuple(
                    ReferenceAxis(str(index + 1), index * 0.5)
                    for index in range(args.views)
                )
            }
        )

    parent = QWidget()
    parent.model = model
    parent._detailing_view_names = {}
    parent._detailing_view_settings = {}
    parent._detailing_custom_planes = {}

    started = perf_counter()
    dialog = DetailingViewsDialog(parent)
    dialog.show()
    app.processEvents()
    opening_ms = (perf_counter() - started) * 1000

    def await_preview() -> tuple[float, float, int]:
        started_wait = last = perf_counter()
        longest_gap = 0.0
        while dialog._preview._render_pending and perf_counter() - started_wait < 60:
            app.processEvents()
            now = perf_counter()
            longest_gap = max(longest_gap, now - last)
            last = now
            sleep(0.005)
        app.processEvents()
        return (
            (perf_counter() - started_wait) * 1000,
            longest_gap * 1000,
            len(dialog._preview.segments_2d),
        )

    initial_preview_ms, initial_gap_ms, initial_segments = await_preview()
    navigation = []
    view_keys = (
        dialog._view_keys
        if args.project is not None
        else dialog._view_keys[: args.views]
    )
    for key in view_keys:
        started_switch = perf_counter()
        dialog._select_detail_view(key)
        app.processEvents()
        request_ms = (perf_counter() - started_switch) * 1000
        render_ms, event_gap_ms, segments = await_preview()
        navigation.append(
            {
                "name": dialog._view_titles[key].text(),
                "plane": dialog._view_definitions[key][0],
                "coordinate": dialog._view_definitions[key][1],
                "request_ms": round(request_ms, 1),
                "preview_ms": round(render_ms, 1),
                "longest_event_gap_ms": round(event_gap_ms, 1),
                "segments": segments,
            }
        )

    report = {
        "platform": QApplication.platformName(),
        "project": str(args.project.resolve()) if args.project is not None else None,
        "members": len(model.bars),
        "views": len(view_keys),
        "dialog_open_ms": round(opening_ms, 1),
        "initial_preview_ms": round(initial_preview_ms, 1),
        "initial_longest_event_gap_ms": round(initial_gap_ms, 1),
        "initial_segments": initial_segments,
        "navigation": navigation,
        "median_navigation_request_ms": round(
            median(item["request_ms"] for item in navigation), 1
        ),
        "median_preview_ms": round(median(item["preview_ms"] for item in navigation), 1),
        "max_longest_event_gap_ms": round(
            max(item["longest_event_gap_ms"] for item in navigation), 1
        ),
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded, flush=True)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    dialog.close()
    parent.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
