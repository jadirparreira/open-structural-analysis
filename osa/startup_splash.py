"""Lightweight cross-platform startup window shown before the main UI loads."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEventLoop, QThread, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget


class StartupSplash(QWidget):
    """Paint the official vector artwork at the screen's pixel density."""

    MINIMUM_VISIBLE_MS = 2000
    EXPOSE_TIMEOUT_MS = 1000

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Open Structural Analysis")
        self._visible_timer = QElapsedTimer()
        artwork_path = (
            Path(__file__).resolve().parent
            / "resources"
            / "icons"
            / "openstructuralanalysis-startup.svg"
        )
        self._artwork = QSvgRenderer(str(artwork_path), self)
        self.setFixedSize(self._artwork.defaultSize())
        self.setAccessibleName("Open Structural Analysis")
        self._center_on_primary_screen()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._artwork.render(painter)
        painter.end()

    def wait_until_exposed(self, app: QApplication) -> None:
        """Wait briefly for the window system to actually present the splash."""
        window = self.windowHandle()
        elapsed = QElapsedTimer()
        elapsed.start()
        while (
            window is not None
            and not window.isExposed()
            and elapsed.elapsed() < self.EXPOSE_TIMEOUT_MS
        ):
            app.processEvents()
            QThread.msleep(10)
        # Start the minimum-visible interval after the compositor exposes the
        # splash, not when QWidget.show() merely queues the window request.
        self._visible_timer.start()

    def _center_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def finish(self, window: QWidget) -> None:
        """Show the ready window before taking the splash off screen."""
        if not self._visible_timer.isValid():
            self._visible_timer.start()
        remaining_ms = max(0, self.MINIMUM_VISIBLE_MS - self._visible_timer.elapsed())
        if remaining_ms:
            wait_loop = QEventLoop(self)
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setTimerType(Qt.TimerType.PreciseTimer)
            timer.timeout.connect(wait_loop.quit)
            # Leave a small margin for platform timer granularity so the
            # measured visible interval never ends just under the minimum.
            timer.start(remaining_ms + 10)
            wait_loop.exec()
            timer.deleteLater()
            wait_loop.deleteLater()
        window.show()
        QApplication.processEvents()
        self.close()
