"""Tela inicial e histórico de projetos do Open Structural Analysis."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from osa.persistence import ProjectRepository
from osa.services.thumbnail_service import thumbnail_to_bytes

from .palettes import PaletteTooltip


class RecentProjectStore:
    """Persiste caminhos e datas de acesso sem duplicar projetos."""

    _settings_key = "recentProjects"
    _maximum = 12

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

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(10)
        preview = QLabel(self)
        preview.setFixedSize(92, 54)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setPixmap(_preview_pixmap(thumbnail, preview.size()))
        layout.addWidget(preview)

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(2)
        name = QLabel(path.stem, self)
        name.setObjectName("recentProjectName")
        name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        name.setWordWrap(True)
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

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(str(self.path))
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    """Home apresentada quando nenhum modelo está aberto."""

    new_project_requested = Signal()
    open_project_requested = Signal()
    manual_requested = Signal()
    recent_project_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = RecentProjectStore()
        self.repository = ProjectRepository()
        self._cards: list[ProjectCard] = []
        self._remove_buttons: set[QToolButton] = set()
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
        recent_title = QLabel("Projetos recentes", self.recent_panel)
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
        self.recent_layout.setContentsMargins(0, 4, 0, 0)
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

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        actions.addWidget(self._action_button("Novo projeto", True, self.new_project_requested.emit))
        actions.addWidget(self._action_button("Abrir projeto", False, self.open_project_requested.emit))
        actions.addWidget(self._action_button("Ver manual", False, self.manual_requested.emit))
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
            if path.is_file():
                try:
                    thumbnail = self.repository.load_thumbnail(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    thumbnail = None
            card = ProjectCard(path, thumbnail, item.get("last_opened", 0), self.recent_content)
            card.clicked.connect(self.recent_project_requested.emit)
            card.remove_requested.connect(self._remove_recent_project)
            card.remove_button.installEventFilter(self)
            self._remove_buttons.add(card.remove_button)
            self._cards.append(card)
            self.recent_layout.addWidget(card)
        self.recent_layout.addStretch(1)

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
