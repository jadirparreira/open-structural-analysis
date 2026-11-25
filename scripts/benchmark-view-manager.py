"""Measure the detailing view manager without modifying the project.

Example: .venv/bin/python scripts/benchmark-view-manager.py model.osa --offscreen
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
            nonlocal finished, last_frame
            if started is None or finished or window._project_loading_path is not None:
                return
            if window._project_load_thread is not None:
                return
            finished = True
            from PySide6.QtCore import QEventLoop

            from osa.ui.dialogs import DetailingViewsDialog
            window.palette.toggle_group("Detalhamento", animate=False)
            app.processEvents()
            t = perf_counter()
            dialog = DetailingViewsDialog(window)
            construct = (perf_counter() - t) * 1000
            dialog.show()
            loop = QEventLoop()
            ready = []
            dialog._preview.view_ready.connect(lambda ok: (ready.append(ok), loop.quit()) if ok else None)
            gaps.clear()
            t = last_frame = perf_counter()
            dialog._start_initial_preview()
            request = (perf_counter() - t) * 1000
            QTimer.singleShot(90000, loop.quit)
            if not ready:
                loop.exec()
            elapsed = (perf_counter() - t) * 1000
            dialog._preview.shutdown()
            dialog.close()
            reopened = DetailingViewsDialog(window)
            reopened.show()
            again = []
            reopened._preview.view_ready.connect(again.append)
            restart = perf_counter()
            reopened._start_initial_preview()
            reopen_ms = (perf_counter() - restart) * 1000
            report = {
                "construct_ms": round(construct, 1), "request_ms": round(request, 1),
                "ready_ms": round(elapsed, 1), "ready": bool(ready),
                "reopen_preview_ms": round(reopen_ms, 1), "reopen_ready": bool(again and again[-1]),
                "longest_event_gap_ms": round(max(gaps, default=0) * 1000, 1),
                "nodes": len(window.model.nodes), "bars": len(window.model.bars),
            }
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            print(encoded, flush=True)
            if args.output:
                args.output.write_text(encoded + "\n", encoding="utf-8")
            if not report["ready"] or not report["reopen_ready"]:
                errors.append("A prévia não ficou pronta dentro do prazo.")
            reopened._preview.shutdown()
            reopened.close()
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
