"""Measure project-sheet painting using saved views without changing the project.

Example: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark-project-sheet.py model.osa
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
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from osa.model import StructuralModel
from osa.ui.project_sheet import ProjectSheetWorkspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--rounds', type=int, default=30)
    parser.add_argument('--zoom', type=float, default=1.0)
    parser.add_argument('--pan-step', type=float, default=2.0)
    parser.add_argument('--fixed-zoom', action='store_true', help='Measure pan without zoom changes')
    parser.add_argument('--empty', action='store_true')
    parser.add_argument('--navigation', action='store_true', help='Measure the interactive navigation path')
    parser.add_argument(
        '--interactions', action='store_true',
        help='Measure cold/warm dimension snapping and element identification picking',
    )
    parser.add_argument('--profile', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    data = json.loads(args.project.read_text(encoding='utf-8'))['detailing_data']['sheets']
    name = data['active_sheet']
    views = [] if args.empty else data['sheet_views'][name]
    parent = QWidget()
    parent.model = StructuralModel()
    parent.model.load(args.project.resolve())
    widget = ProjectSheetWorkspace(parent)
    widget.resize(1200, 800)
    widget.set_sheet_settings(name, data['sheet_settings'][name], data['project_settings'], len(data['sheet_names']))
    widget.set_sheet_views(views)
    widget.show()
    app.processEvents()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    widget._zoom_factor = args.zoom
    warmup = QPainter(image)
    widget.render(warmup, QPointF().toPoint())
    warmup.end()
    if args.navigation:
        widget._begin_navigation()
    times = []
    import cProfile
    profile = cProfile.Profile()
    if args.profile:
        profile.enable()
    for index in range(args.rounds):
        widget._pan_offset = QPointF(index * args.pan_step, index * args.pan_step / 2)
        widget._zoom_factor = args.zoom if args.fixed_zoom else args.zoom * (1.0 + (index % 10) * 0.05)
        painter = QPainter(image)
        start = perf_counter()
        widget.render(painter, QPointF().toPoint())
        times.append((perf_counter() - start) * 1000)
        painter.end()
    if args.profile:
        profile.disable()
        profile.dump_stats("/tmp/osa-project-sheet.prof")
    report = {
        'sheet': name,
        'views': len(views),
        'segments': sum(len(v.get('segments', ())) for v in views),
        'navigation': args.navigation,
        'rounds': len(times),
        'median_ms': round(median(times), 2),
        'p95_ms': round(sorted(times)[min(len(times)-1, int(len(times)*0.95))], 2),
    }
    if args.interactions and views:
        import copy
        from types import SimpleNamespace

        from osa.ui.main_window import MainWindow

        view_index = next((i for i, view in enumerate(views) if view.get('segments')), None)
        if view_index is not None:
            first_segment = views[view_index]['segments'][0]
            cursor = widget._screen_point(view_index, first_segment[0])
        else:
            cursor = None
        if cursor is not None:
            widget._dimension_snap_cache.clear()
            started = perf_counter()
            first_snap = widget._dimension_snap_at(cursor, view_index)
            cold_snap_ms = (perf_counter() - started) * 1000
            snap_times = []
            for _ in range(max(10, min(30, args.rounds))):
                started = perf_counter()
                widget._dimension_snap_at(cursor, view_index)
                snap_times.append((perf_counter() - started) * 1000)
            pick_times = []
            identifier_hit = False
            for _ in range(max(10, min(30, args.rounds))):
                started = perf_counter()
                identifier_hit = widget._element_at(cursor) is not None
                pick_times.append((perf_counter() - started) * 1000)
            selector = SimpleNamespace(currentText=lambda: name)
            palette = SimpleNamespace(
                _sheet_names=data['sheet_names'], sheet_selector=selector,
                _sheet_settings=data['sheet_settings'],
                _project_settings=data['project_settings'], _sheet_views=data['sheet_views'],
            )
            state_context = SimpleNamespace(
                model=parent.model, project_sheets_palette=palette,
            )
            started = perf_counter()
            copy.deepcopy(data['sheet_views'])
            deepcopy_snapshot_ms = (perf_counter() - started) * 1000
            snapshot_times = []
            for _ in range(5):
                started = perf_counter()
                MainWindow._detailing_state_snapshot(state_context)
                snapshot_times.append((perf_counter() - started) * 1000)
            identifier_add_times = []
            picked = widget._element_at(cursor)
            identifier_added = False
            if picked is not None:
                state_context.section_profiles = {}
                state_context.project_sheet_workspace = widget
                state_context.history = SimpleNamespace(append=lambda _message: None)
                state_context._update_project_identification_text = lambda _item: None
                state_context._detailing_state_snapshot = lambda: MainWindow._detailing_state_snapshot(
                    state_context,
                )
                state_context._store_detailing_state = lambda: MainWindow._store_detailing_state(
                    state_context,
                )
                for _ in range(10):
                    views[view_index]['identifications'] = []
                    started = perf_counter()
                    MainWindow._add_project_view_identification(
                        state_context, view_index, picked[2], picked[3],
                    )
                    identifier_add_times.append((perf_counter() - started) * 1000)
                    identifier_added = bool(views[view_index]['identifications'])
            report['interactions'] = {
                'dimension_snap_cold_ms': round(cold_snap_ms, 2),
                'dimension_snap_warm_median_ms': round(median(snap_times), 2),
                'dimension_snap_found': first_snap is not None,
                'identifier_pick_median_ms': round(median(pick_times), 2),
                'identifier_pick_found': identifier_hit,
                'state_snapshot_deepcopy_ms': round(deepcopy_snapshot_ms, 2),
                'state_snapshot_shared_linework_median_ms': round(median(snapshot_times), 2),
                'identifier_add_median_ms': (
                    round(median(identifier_add_times), 2) if identifier_add_times else None
                ),
                'identifier_add_succeeded': identifier_added,
            }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    widget.close()

if __name__ == '__main__':
    main()
