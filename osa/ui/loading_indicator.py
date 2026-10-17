"""Continuous busy indicator driven by Qt's frame animation clock."""

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget


class LoadingIndicator(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setAccessibleName("Carregando modelo")
        self._phase = 0.0
        self._animation = QPropertyAnimation(self, b"phase", self)
        self._animation.setDuration(1400)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.Type.Linear)

    def _get_phase(self) -> float:
        return self._phase

    def _set_phase(self, phase: float) -> None:
        self._phase = phase
        self.update()

    phase = Property(float, _get_phase, _set_phase)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._animation.start()

    def hideEvent(self, event) -> None:
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect())
        radius = self.height() / 2.0
        clip = QPainterPath()
        clip.addRoundedRect(track, radius, radius)
        painter.fillPath(clip, QColor("#eaeef2"))
        painter.setClipPath(clip)
        segment_width = self.width() * 0.38
        left = (self.width() + segment_width) * self._phase - segment_width
        segment = QPainterPath()
        segment.addRoundedRect(QRectF(left, 0, segment_width, self.height()), radius, radius)
        painter.fillPath(segment, QColor("#0969da"))
