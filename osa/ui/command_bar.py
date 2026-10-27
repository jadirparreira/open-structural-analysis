from .common import *
from .window_frame import WindowFrame


class CommandInput(QLineEdit):
    def __init__(self, owner: "CommandBar") -> None:
        super().__init__(owner)
        self.owner = owner

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.owner.window.history.show_history()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.owner.window.history.schedule_fade()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self.owner, "mcp_working_indicator"):
            self.owner._position_mcp_working_indicator()


class CommandHistory(QFrame):
    """Independent translucent, scrollable history panel."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("commandHistory")
        self.setFixedWidth(580)
        self._lines: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.fade_out)
        self._animation = QPropertyAnimation(self)
        self._animation.setPropertyName(b"opacity")
        self._animation.finished.connect(self._on_animation_finished)
        from PySide6.QtWidgets import QScrollArea
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("historyScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("""
            QScrollArea#historyScroll { border: 0; background: transparent; }
            QScrollArea#historyScroll QWidget#qt_scrollarea_viewport { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 2px 4px 0; }
            QScrollBar::handle:vertical { background: #afb8c1; min-height: 28px; border-radius: 6px; }
            QScrollBar::handle:vertical:hover { background: #8c959f; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
        self.scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content = QWidget()
        self.content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(0)
        self.content_layout.addStretch()
        self.scroll.setWidget(self.content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.scroll)
        self.hide()

    def append(self, text: str) -> None:
        self._lines.append(text)
        self._lines = self._lines[-20:]
        while self.content_layout.count() > 1:
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for line in self._lines:
            label = QLabel(line)
            label.setObjectName("historyLine")
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            label.setMinimumWidth(0)
            self.content_layout.insertWidget(self.content_layout.count() - 1, label)
        self.setFixedHeight(min(220, 24 * min(len(self._lines), 5) + 12))
        self.show_history()
        self.reposition()
        if not self.window.command_bar.input.hasFocus():
            self.schedule_fade()
        QTimer.singleShot(0, self._refresh_layout)

    def _scroll_to_latest(self) -> None:
        scrollbar = self.scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _refresh_layout(self) -> None:
        """Dimensiona as linhas conforme a largura real do histórico."""
        viewport_width = self.scroll.viewport().width()
        margins = self.content_layout.contentsMargins()
        line_width = max(1, viewport_width - margins.left() - margins.right() - 2)
        for label in self.content.findChildren(QLabel, "historyLine"):
            label.setFixedWidth(line_width)
            label.setFixedHeight(max(24, label.heightForWidth(line_width)))
        self.content_layout.activate()
        content_height = self.content.sizeHint().height() + 8
        self.setFixedHeight(min(220, max(40, content_height)))
        self.reposition()
        self._scroll_to_latest()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_layout)

    def show_history(self) -> None:
        if not self._lines:
            return
        self._timer.stop()
        self.show()
        effect = self._effect()
        self._animation.stop()
        effect.setOpacity(1.0)

    def schedule_fade(self) -> None:
        if self._lines:
            self._timer.start()

    def fade_out(self) -> None:
        if self.window.command_bar.input.hasFocus():
            return
        effect = self._effect()
        self._animation.stop(); self._animation.setTargetObject(effect)
        self._animation.setStartValue(effect.opacity()); self._animation.setEndValue(0.0)
        self._animation.setDuration(450)
        self._animation.start()
        # Keep the visibility guarantee even on compositors that do not animate
        # QGraphicsOpacityEffect reliably for an off-screen/VTK child.
        QTimer.singleShot(500, self._hide_if_faded)

    def _on_animation_finished(self) -> None:
        effect = self._effect()
        if effect.opacity() <= 0.01 and not self.window.command_bar.input.hasFocus():
            self.hide()

    def _hide_if_faded(self) -> None:
        if not self.window.command_bar.input.hasFocus():
            self._effect().setOpacity(0.0)
            self.hide()

    def _effect(self) -> QGraphicsOpacityEffect:
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self); effect.setOpacity(1.0); self.setGraphicsEffect(effect)
        return effect

    def reposition(self) -> None:
        command_bar = self.window.command_bar
        # The history bottom edge always touches the command input top edge.
        self.move((self.window.width() - self.width()) // 2,
                  command_bar.y() - self.height() - 6)
        self.raise_()


class CommandBar(QFrame):
    _mcp_idle_grace_ms = 10_000

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("commandBar")
        self.setFixedWidth(620)
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 8, 8, 8)
        self.input = CommandInput(self)
        self.input.setObjectName("commandInput")
        self.input.setPlaceholderText("Digite um comando…")
        self.input.returnPressed.connect(self.submit)
        self.input.textEdited.connect(self.window.history._scroll_to_latest)
        self.mcp_working_indicator = QLabel(self.input)
        self.mcp_working_indicator.setObjectName("mcpWorkingIndicator")
        self.mcp_working_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.mcp_working_indicator.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mcp_working_indicator.setAccessibleName("MCP Trabalhando")
        self.mcp_working_indicator.setFixedSize(32, 28)
        self.mcp_working_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bot_icon = Path(__file__).parents[1] / "resources" / "icons" / "bot-white.svg"
        self.mcp_working_indicator.setPixmap(QIcon(str(bot_icon)).pixmap(QSize(18, 18)))
        self.mcp_working_indicator.hide()
        self._mcp_indicator_active = False
        self._mcp_idle_timer = QTimer(self)
        self._mcp_idle_timer.setSingleShot(True)
        self._mcp_idle_timer.setInterval(self._mcp_idle_grace_ms)
        self._mcp_idle_timer.timeout.connect(self._hide_mcp_working_indicator)
        layout.addWidget(self.input)
        self.adjustSize()

    def set_mcp_busy(self, busy: bool) -> None:
        if busy:
            self._mcp_idle_timer.stop()
            self._mcp_indicator_active = True
            self.mcp_working_indicator.setVisible(True)
            self.input.setTextMargins(0, 0, self.mcp_working_indicator.width() + 18, 0)
            self._position_mcp_working_indicator()
            self.mcp_working_indicator.raise_()
            self.mcp_working_indicator.repaint()
        elif self._mcp_indicator_active:
            # MCP does not expose an agent-turn-complete event. Keep the icon
            # through the gaps between tool calls and clear it after inactivity.
            self._mcp_idle_timer.start()

    def _hide_mcp_working_indicator(self) -> None:
        self._mcp_indicator_active = False
        self.mcp_working_indicator.hide()
        self.input.setTextMargins(0, 0, 0, 0)

    def _position_mcp_working_indicator(self) -> None:
        indicator = self.mcp_working_indicator
        vertical_inset = (self.input.height() - indicator.height()) // 2
        indicator.move(
            max(vertical_inset, self.input.width() - indicator.width() - vertical_inset),
            vertical_inset,
        )

    def submit(self) -> None:
        command = self.input.text().strip()
        if command:
            self.window.handle_command(command)
            self.input.clear()

    def reposition(self) -> None:
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move((self.window.width() - self.width()) // 2,
                  self.window.height() - margin - self.height() - 24)
        self.raise_()
