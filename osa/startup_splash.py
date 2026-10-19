"""Lightweight cross-platform startup window shown before the main UI loads."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEventLoop, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class StartupSplash(QWidget):
    """Show honest, indeterminate startup feedback without a console window."""

    MINIMUM_VISIBLE_MS = 2000

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowTitle("Open Structural Analysis")
        self.setFixedSize(460, 176)
        self._visible_timer = QElapsedTimer()

        frame = QFrame(self)
        frame.setObjectName("startupCard")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(24, 20, 24, 20)
        frame_layout.setSpacing(12)

        icon_path = (
            Path(__file__).resolve().parent
            / "resources"
            / "icons"
            / "openstructuralanalysis-wordmark.png"
        )
        wordmark = QLabel(frame)
        wordmark.setPixmap(
            QPixmap(str(icon_path)).scaledToWidth(396, Qt.TransformationMode.SmoothTransformation)
        )
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wordmark.setAccessibleName("Open Structural Analysis")
        frame_layout.addWidget(wordmark)

        tagline = QLabel("Feito pra ser livre", frame)
        tagline.setObjectName("startupTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(tagline)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(frame)
        self.setStyleSheet(
            "QWidget { background: transparent; }"
            "QFrame#startupCard { background: #ffffff; border: 1px solid #d0d7de; }"
            "QLabel#startupTagline { color: #24292f; font-size: 15px; }"
        )
        self._center_on_primary_screen()

    def _center_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._visible_timer.start()

    def finish(self, window: QWidget) -> None:
        """Show the ready window before taking the splash off screen."""
        remaining_ms = max(0, self.MINIMUM_VISIBLE_MS - self._visible_timer.elapsed())
        if remaining_ms:
            wait_loop = QEventLoop(self)
            QTimer.singleShot(remaining_ms, wait_loop.quit)
            wait_loop.exec()
        window.show()
        QApplication.processEvents()
        self.close()
