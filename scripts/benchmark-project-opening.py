"""Measure real Qt opening time and event-loop stalls without editing a project.

Example: .venv/bin/python scripts/benchmark-project-opening.py model.osa --offscreen
Offscreen runs measure CPU/event-loop costs; a native run also exercises OpenGL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    if not project.is_file():
        parser.error("O arquivo de modelo não foi encontrado.")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="osa-opening-") as config:
        os.environ["XDG_CONFIG_HOME"] = config
        os.environ["MPLCONFIGDIR"] = config
        from PySide6.QtCore import QSettings, QTimer
        from PySide6.QtWidgets import QApplication

        from osa.app import create_application

        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, config)
        app, window = create_application([])
        window.show()
        gaps = []
        errors = []
        started = None
        last_frame = perf_counter()
        finished = False

        def heartbeat() -> None:
            nonlocal last_frame
            now = perf_counter()
            if started is not None:
                gaps.append(now - last_frame)
            last_frame = now

        def open_project() -> None:
            nonlocal started, last_frame
            started = last_frame = perf_counter()
            window._open_model_path(project)

        def check_finished() -> None:
            nonlocal finished
            if started is None or finished or window._project_loading_path is not None:
                return
            if window._project_load_thread is not None:
                return
            finished = True
            elapsed = perf_counter() - started
            report = {
                "file_bytes": project.stat().st_size,
                "platform": QApplication.platformName(),
                "opening_seconds": round(elapsed, 3),
                "longest_event_gap_ms": round(max(gaps, default=0) * 1000, 1),
                "event_gaps_over_100_ms": sum(gap > 0.1 for gap in gaps),
                "nodes": len(window.model.nodes),
                "members": len(window.model.bars),
                "results": len(window.model.analysis_results),
                "errors": errors,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            if args.output:
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            # Close the measurement window without a save prompt.
            window._saved_revision = window.model.revision
            window._saved_view_revision = window.model.view_revision
            window.close()
            app.quit()

        window.show_error = errors.append
        timer = QTimer()
        timer.setInterval(16)
        timer.timeout.connect(heartbeat)
        timer.start()
        monitor = QTimer()
        monitor.setInterval(10)
        monitor.timeout.connect(check_finished)
        monitor.start()
        QTimer.singleShot(200, open_project)
        app.exec()
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
