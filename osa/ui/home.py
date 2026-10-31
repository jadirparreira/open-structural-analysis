"""Tela inicial e histórico de projetos do Open Structural Analysis."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from osa.persistence import ProjectRepository
from osa.services.thumbnail_service import thumbnail_to_bytes

from .palettes import PaletteTooltip


class _ThumbnailSignals(QObject):
    ready = Signal(object, object, object)


class _ThumbnailTask(QRunnable):
    def __init__(self, path: Path, signature: tuple[int, int]) -> None:
        super().__init__()
        self.path = path
        self.signature = signature
        self.signals = _ThumbnailSignals()

    def run(self) -> None:
        try:
            thumbnail = ProjectRepository().load_thumbnail(self.path)
        except (OSError, ValueError, TypeError):
            thumbnail = None
        self.signals.ready.emit(self.path, self.signature, thumbnail)


class RecentProjectStore:
    """Persiste caminhos e datas de acesso sem duplicar projetos."""

    _settings_key = "recentProjects"
    _maximum = 16

    def __init__(self) -> None:
        self.settings = QSettings("OpenStructuralAnalysis", "OpenStructuralAnalysis")

    def items(self) -> list[dict[str, object]]:
        try:
            raw = json.loads(str(self.settings.value(self._settings_key, "[]")))
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        items = [item for item in raw if isinstance(item, dict) and isinstance(item.get("path"), str)]
        return sorted(items, key=lambda item: float(item.get("last_opened", 0)), reverse=True)

    def add(self, path: str | Path) -> None:
        resolved = str(Path(path).expanduser().resolve())
        items = [item for item in self.items() if item.get("path") != resolved]
        items.insert(0, {"path": resolved, "last_opened": time.time()})
        self.settings.setValue(self._settings_key, json.dumps(items[: self._maximum], ensure_ascii=False))
        self.settings.sync()

    def remove(self, path: str | Path) -> None:
        resolved = str(Path(path).expanduser().resolve())
        items = [item for item in self.items() if item.get("path") != resolved]
        self.settings.setValue(self._settings_key, json.dumps(items, ensure_ascii=False))
        self.settings.sync()


class ScrollingNameLabel(QLabel):
    """Nome de modelo em uma linha, com fade e revelação no hover."""

    _fade_width = 28

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self._scroll_offset = 0.0
        self._animation = QPropertyAnimation(self, b"scrollOffset", self)
        self._animation.finished.connect(self._on_animation_finished)
        self._cycle_timer = QTimer(self)
        self._cycle_timer.setSingleShot(True)
        self._cycle_timer.timeout.connect(self._advance_cycle)
        self._cycle_state = "idle"
        self.setObjectName("recentProjectName")
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        super().setText(text)

    def _get_scroll_offset(self) -> float:
        return self._scroll_offset

    def _set_scroll_offset(self, value: float) -> None:
        self._scroll_offset = float(value)
        self.update()

    scrollOffset = Property(float, _get_scroll_offset, _set_scroll_offset)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self._animation.stop()
        self._cycle_timer.stop()
        self._cycle_state = "idle"
        self._scroll_offset = 0.0
        super().setText(self._full_text)
        self.update()

    def _text_width(self) -> int:
        return QFontMetrics(self.font()).horizontalAdvance(self._full_text)

    def _overflow(self) -> int:
        return max(0, self._text_width() - max(0, self.width()))

    def _animate_to(self, target: float, duration: int, easing: QEasingCurve.Type) -> None:
        if self._overflow() <= 0:
            return
        self._animation.stop()
        self._animation.setStartValue(self._scroll_offset)
        self._animation.setEndValue(float(target))
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(easing)
        self._animation.start()

    def start_scrolling(self) -> None:
        overflow = self._overflow()
        if overflow > 0:
            self._cycle_timer.stop()
            self._animation.stop()
            self._scroll_offset = 0.0
            self._cycle_state = "pause_start"
            self._cycle_timer.start(1000)

    def stop_scrolling(self) -> None:
        self._cycle_timer.stop()
        self._animation.stop()
        if self._overflow() > 0 and self._scroll_offset != 0.0:
            self._cycle_state = "idle"
            self._animate_to(0.0, 220, QEasingCurve.Type.OutCubic)
        else:
            self._cycle_state = "idle"
            self._scroll_offset = 0.0

    def _advance_cycle(self) -> None:
        overflow = self._overflow()
        if overflow <= 0:
            self._cycle_state = "idle"
            return
        if self._cycle_state == "pause_start":
            self._cycle_state = "forward"
            slide_duration = round(overflow * 25)
            self._animate_to(-overflow, slide_duration, QEasingCurve.Type.Linear)
        elif self._cycle_state == "pause_end":
            self._cycle_state = "backward"
            self._animate_to(0.0, 240, QEasingCurve.Type.OutCubic)

    def _on_animation_finished(self) -> None:
        if self._cycle_state == "forward":
            self._cycle_state = "pause_end"
            self._cycle_timer.start(2000)
        elif self._cycle_state == "backward":
            self._cycle_state = "pause_start"
            self._cycle_timer.start(1000)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._overflow() <= 0:
            self._animation.stop()
            self._cycle_timer.stop()
            self._cycle_state = "idle"
            self._scroll_offset = 0.0
        self.update()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        return QSize(1, metrics.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(1, QFontMetrics(self.font()).height())

    def enterEvent(self, event) -> None:
        self.start_scrolling()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.stop_scrolling()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        del event
        if not self._full_text:
            return

        metrics = QFontMetrics(self.font())
        baseline = (self.height() - metrics.height()) // 2 + metrics.ascent()
        text_width = max(1, self._text_width() + 2)
        overflow = self._overflow()
        surface = QPixmap(text_width, max(1, self.height()))
        surface.fill(Qt.GlobalColor.transparent)

        surface_painter = QPainter(surface)
        surface_painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        surface_painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        surface_painter.setFont(self.font())
        surface_painter.drawText(0, baseline, self._full_text)
        if overflow > 0:
            visible_start = max(0.0, -self._scroll_offset)
            visible_end = min(float(text_width), self.width() - self._scroll_offset)
            fade_width = min(28.0, max(4.0, self.width() / 4.0))
            progress = min(1.0, max(0.0, -self._scroll_offset / overflow))
            left_edge_alpha = round(255 * (1.0 - progress))
            right_edge_alpha = round(255 * progress)
            fade = QLinearGradient(0, 0, text_width, 0)
            opaque = QColor(255, 255, 255, 255)
            left_edge = QColor(255, 255, 255, left_edge_alpha)
            right_edge = QColor(255, 255, 255, right_edge_alpha)
            fade.setColorAt(max(0.0, visible_start / text_width), left_edge)
            fade.setColorAt(min(1.0, (visible_start + fade_width) / text_width), opaque)
            fade.setColorAt(max(0.0, (visible_end - fade_width) / text_width), opaque)
            fade.setColorAt(min(1.0, visible_end / text_width), right_edge)
            fade.setColorAt(1.0, right_edge)
            surface_painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationIn
            )
            surface_painter.fillRect(surface.rect(), QBrush(fade))
        surface_painter.end()

        painter = QPainter(self)
        painter.setClipRect(self.rect())
        painter.drawPixmap(round(self._scroll_offset), 0, surface)
        painter.end()


class ProjectCard(QFrame):
    clicked = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, path: Path, thumbnail: str | None, last_opened: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setObjectName("recentProjectCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(path))
        self.setMinimumHeight(78)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(10)
        preview = QLabel(self)
        preview.setFixedSize(92, 54)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(_preview_pixmap(thumbnail, preview.size()))
        self.preview = preview
        layout.addWidget(preview)

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(2)
        name = ScrollingNameLabel(path.stem, self)
        self.name_label = name
        details.addWidget(name)
        state = "Arquivo não encontrado" if not path.is_file() else "Projeto OSA"
        meta_text = f"{_relative_date(last_opened)} · {state}"
        meta = QLabel(meta_text, self)
        meta.setObjectName("recentProjectMeta")
        details.addWidget(meta)
        details.addStretch()
        layout.addLayout(details, 1)

        remove_button = QToolButton(self)
        remove_button.setObjectName("recentProjectRemoveButton")
        remove_button.setFixedSize(28, 28)
        remove_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "x.svg")))
        remove_button.setIconSize(QSize(15, 15))
        remove_button.setToolTip("Remover da lista")
        remove_button.setAccessibleName("Remover da lista")
        remove_button.clicked.connect(lambda: self.remove_requested.emit(str(self.path)))
        self.remove_button = remove_button
        layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignTop)

    def set_thumbnail(self, thumbnail: str | None) -> None:
        self.preview.setPixmap(_preview_pixmap(thumbnail, self.preview.size()))

    def enterEvent(self, event) -> None:
        self.name_label.start_scrolling()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.name_label.stop_scrolling()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(str(self.path))
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    """Home apresentada quando nenhum modelo está aberto."""

    new_project_requested = Signal()
    open_project_requested = Signal()
    import_project_requested = Signal()
    manual_requested = Signal()
    recent_project_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = RecentProjectStore()
        self.repository = ProjectRepository()
        self._cards: list[ProjectCard] = []
        self._remove_buttons: set[QToolButton] = set()
        self._thumbnail_cache: dict[Path, tuple[tuple[int, int], str | None]] = {}
        self._thumbnail_pending: dict[tuple[Path, tuple[int, int]], _ThumbnailTask] = {}
        self._thumbnail_pool = QThreadPool(self)
        self._thumbnail_pool.setMaxThreadCount(2)
        self.setObjectName("homePage")
        self._recent_tooltip = PaletteTooltip(self)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.recent_panel = QFrame(self)
        self.recent_panel.setObjectName("homeRecentPanel")
        recent_layout = QVBoxLayout(self.recent_panel)
        recent_layout.setContentsMargins(24, 30, 20, 24)
        recent_layout.setSpacing(14)
        recent_title = QLabel("Modelos recentes", self.recent_panel)
        recent_title.setObjectName("homeSectionTitle")
        recent_layout.addWidget(recent_title)

        scroll = QScrollArea(self.recent_panel)
        scroll.setObjectName("homeRecentScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_content = QWidget()
        self.recent_content.setObjectName("homeRecentContent")
        self.recent_layout = QVBoxLayout(self.recent_content)
        self.recent_layout.setContentsMargins(0, 4, 8, 0)
        self.recent_layout.setSpacing(8)
        scroll.setWidget(self.recent_content)
        recent_layout.addWidget(scroll, 1)
        root.addWidget(self.recent_panel, 1)

        self.main_panel = QFrame(self)
        self.main_panel.setObjectName("homeMainPanel")
        main_layout = QVBoxLayout(self.main_panel)
        main_layout.setContentsMargins(64, 56, 64, 32)
        main_layout.setSpacing(0)

        main_layout.addStretch(1)
        welcome = QLabel("Bem-vindo ao", self.main_panel)
        welcome.setObjectName("homeWelcome")
        main_layout.addWidget(welcome, 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addSpacing(14)
        main_layout.addWidget(_brand_lockup(self.main_panel), 0, Qt.AlignmentFlag.AlignHCenter)
        main_layout.addSpacing(64)

        actions = QGridLayout()
        actions.setHorizontalSpacing(10)
        actions.setVerticalSpacing(10)
        actions.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        actions.addWidget(self._action_button("Novo modelo", True, self.new_project_requested.emit), 0, 0)
        actions.addWidget(self._action_button("Abrir modelo", False, self.open_project_requested.emit), 0, 1)
        self.import_model_button = self._action_button("Importar modelo", False, self.import_project_requested.emit)
        self.import_model_button.setToolTip("Importar um projeto PRJ (.prj ou .prj.zip)")
        actions.addWidget(self.import_model_button, 1, 0)
        actions.addWidget(self._action_button("Ver manual", False, self.manual_requested.emit), 1, 1)
        main_layout.addLayout(actions)
        main_layout.addStretch(2)

        separator = QFrame(self.main_panel)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("homeSeparator")
        main_layout.addWidget(separator)
        main_layout.addSpacing(14)
        disclaimer = QLabel(
            "A interpretação e o aceite dos resultados obtidos pelo Open Structural Analysis "
            "são de responsabilidade do usuário.",
            self.main_panel,
        )
        disclaimer.setObjectName("homeDisclaimer")
        disclaimer.setWordWrap(True)
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(disclaimer)
        root.addWidget(self.main_panel, 3)

        self.refresh()

    def _action_button(self, text: str, primary: bool, callback) -> QPushButton:
        button = QPushButton(text, self.main_panel)
        button.setObjectName("homePrimaryButton" if primary else "homeSecondaryButton")
        button.setMinimumHeight(44)
        button.setMinimumWidth(200)
        button.clicked.connect(callback)
        return button

    def refresh(self) -> None:
        self._recent_tooltip.dismiss()
        self._remove_buttons.clear()
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            if item.widget() is not None and item.widget() not in self._cards:
                item.widget().deleteLater()

        items = self.store.items()
        for item in items:
            path = Path(str(item["path"]))
            thumbnail = None
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                signature = None
            if signature is not None:
                cached = self._thumbnail_cache.get(path)
                if cached is not None and cached[0] == signature:
                    thumbnail = cached[1]
                elif (path, signature) not in self._thumbnail_pending:
                    task = _ThumbnailTask(path, signature)
                    task.signals.ready.connect(self._thumbnail_ready, Qt.ConnectionType.QueuedConnection)
                    self._thumbnail_pending[path, signature] = task
                    self._thumbnail_pool.start(task)
            card = ProjectCard(path, thumbnail, item.get("last_opened", 0), self.recent_content)
            card.clicked.connect(self.recent_project_requested.emit)
            card.remove_requested.connect(self._remove_recent_project)
            card.remove_button.installEventFilter(self)
            self._remove_buttons.add(card.remove_button)
            self._cards.append(card)
            self.recent_layout.addWidget(card)
        self.recent_layout.addStretch(1)

    @Slot(object, object, object)
    def _thumbnail_ready(self, path: Path, signature: tuple[int, int], thumbnail: str | None) -> None:
        self._thumbnail_pending.pop((path, signature), None)
        try:
            stat = path.stat()
        except OSError:
            return
        if signature != (stat.st_mtime_ns, stat.st_size):
            return
        self._thumbnail_cache[path] = (signature, thumbnail)
        for card in self._cards:
            if card.path == path:
                card.set_thumbnail(thumbnail)

    def _remove_recent_project(self, path: str) -> None:
        self.store.remove(path)
        self.refresh()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in self._remove_buttons:
            if event.type() == QEvent.Type.Enter:
                self._recent_tooltip.schedule_for(watched, "Remover da lista", gap=15)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._recent_tooltip.dismiss()
            elif event.type() == QEvent.Type.ToolTip:
                return True
        return super().eventFilter(watched, event)


def _brand_lockup(parent: QWidget, subtitle: str | None = None) -> QWidget:
    container = QWidget(parent)
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    logo = QLabel(container)
    logo.setPixmap(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "openstructuralanalysis.svg")).pixmap(QSize(80, 80)))
    logo.setFixedSize(80, 80)
    layout.addWidget(logo)
    wordmark = QWidget(container)
    wordmark_layout = QVBoxLayout(wordmark)
    wordmark_layout.setContentsMargins(0, 0, 0, 0)
    wordmark_layout.setSpacing(2)
    first_line = QLabel("Open Structural", wordmark)
    first_line.setObjectName("homeWordmark")
    second_line = QLabel("Analysis", wordmark)
    second_line.setObjectName("homeWordmark")
    second_font = second_line.font()
    second_font.setBold(True)
    second_line.setFont(second_font)
    wordmark_layout.addWidget(first_line)
    wordmark_layout.addWidget(second_line)
    if subtitle:
        wordmark_layout.addSpacing(6)
        subtitle_label = QLabel(subtitle, wordmark)
        subtitle_label.setObjectName("aboutVersion")
        wordmark_layout.addWidget(subtitle_label)
    wordmark_layout.addStretch(1)
    layout.addWidget(wordmark)
    return container


def _relative_date(value: object) -> str:
    try:
        opened = datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone()  # noqa: UP017 - Python 3.10 support
    except (TypeError, ValueError, OSError):
        return "Acesso recente"
    days = max(0, (datetime.now().astimezone().date() - opened.date()).days)
    if days == 0:
        return "Hoje"
    if days == 1:
        return "Ontem"
    if days < 7:
        return f"Há {days} dias"
    return opened.strftime("%d/%m/%Y")


def _preview_pixmap(thumbnail: str | None, size: QSize) -> QPixmap:
    data = thumbnail_to_bytes(thumbnail)
    if data:
        pixmap = QPixmap()
        if pixmap.loadFromData(data, "PNG"):
            return pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    pixmap = QPixmap(size)
    pixmap.fill(QColor("#ffffff"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#d0d7de"), 1.0))
    painter.drawRect(0, 0, size.width() - 1, size.height() - 1)
    painter.setPen(QColor("#8c959f"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Sem prévia")
    painter.end()
    return pixmap
