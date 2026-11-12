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
    ordered = sorted(times)
    print(json.dumps({'sheet': name, 'views': len(views), 'segments': sum(len(v.get('segments', ())) for v in views), 'navigation': args.navigation, 'rounds': len(times), 'median_ms': round(median(times), 2), 'p95_ms': round(ordered[min(len(ordered)-1, int(len(ordered)*0.95))], 2)}, ensure_ascii=False, indent=2))
    widget.close()

if __name__ == '__main__':
    main()
