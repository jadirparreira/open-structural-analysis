"""Regenerate older sheet linework away from the interface thread."""
from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Signal

from .detailing_preview import DetailingViewPreview, _ViewGeometryCalculator

_LOG = logging.getLogger(__name__)


class SheetLineworkSignals(QObject):
    finished = Signal(object, object, int, object, object, object, object, bool)


class SheetLineworkTask(QRunnable):
    def __init__(self, signals, model, source, revision, group_revision, jobs, cancelled: Event):
        super().__init__()
        self.signals = signals
        self.model = model
        self.source = source
        self.revision = revision
        self.group_revision = group_revision
        self.jobs = jobs
        self.cancelled = cancelled

    def run(self) -> None:
        calculator = _ViewGeometryCalculator()
        calculator._detail_scene = self.source
        for sheet_name, view, projection, had_segments in self.jobs:
            if self.cancelled.is_set():
                return
            segments, owners, success = (), (), False
            try:
                DetailingViewPreview.set_view(
                    calculator, self.model, projection["plane"], projection["coordinate"],
                    upper_offset_cm=float(projection.get("upper_offset_cm", 50.0)),
                    lower_offset_cm=float(projection.get("lower_offset_cm", 50.0)),
                    orientation=str(projection.get("orientation", "Superior para inferior")),
                    rotation_degrees=float(projection.get("rotation_degrees", 0.0)),
                )
                segments, owners = tuple(calculator._segments_2d), tuple(calculator._segment_sources)
                # Do not replace an existing drawing with an empty result if
                # the projection pipeline silently failed.
                success = bool(segments) or not had_segments
            except Exception:  # noqa: BLE001 - keep the saved view if regeneration fails
                _LOG.exception("Não foi possível atualizar a vista %s", sheet_name)
            if not self.cancelled.is_set():
                try:
                    self.signals.finished.emit(
                        sheet_name, view, self.revision, self.group_revision, projection, segments, owners, success,
                    )
                except RuntimeError:
                    # The application can close while this global-pool task is
                    # running. Its window then owns no live signal receiver.
                    return
