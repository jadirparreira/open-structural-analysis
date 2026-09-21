from .common import *


class TitleBar(QFrame):
    """Client-side title bar with Ubuntu-inspired window controls."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self._drag_origin: QPoint | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        file_menu_button = QToolButton()
        file_menu_button.setText("Arquivo")
        file_menu_button.setObjectName("menuButton")
        file_menu = QMenu(file_menu_button)
        file_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        file_menu.addAction("Novo modelo")
        file_menu.addAction("Abrir modelo…")
        file_menu.addAction("Salvar")
        file_menu.addAction("Salvar como…")
        file_menu.addSeparator()
        file_menu.addAction("Configurações")
        file_menu.addSeparator()
        file_menu.addAction("Sair")
        file_menu_button.setMenu(file_menu)
        file_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(file_menu_button)
        edit_menu_button = QToolButton()
        edit_menu_button.setText("Editar")
        edit_menu_button.setObjectName("menuButton")
        edit_menu = QMenu(edit_menu_button)
        edit_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        edit_menu.addAction("Desfazer"); edit_menu.addAction("Refazer")
        edit_menu.addSeparator(); edit_menu.addAction("Recortar")
        edit_menu.addAction("Copiar"); edit_menu.addAction("Colar")
        edit_menu.addSeparator()
        properties_action = edit_menu.addAction("Propriedades")
        properties_action.triggered.connect(window.open_settings)
        edit_menu_button.setMenu(edit_menu)
        edit_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(edit_menu_button)
        layout.addStretch()
        self.title = QLabel("Open Structural Analysis", self)
        self.title.setObjectName("windowTitle")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self._add_control(layout, "", "Minimizar", window.showMinimized, "window-minus.svg")
        self.maximize_button = self._add_control(layout, "", "Maximizar", self.toggle_maximized, "window-square.svg")
        self._add_control(layout, "", "Fechar", window.close, "window-x.svg")
        self.set_maximized(False)
        self._position_title()

    def set_maximized(self, maximized: bool) -> None:
        if maximized:
            self.maximize_button.setText("")
            self.maximize_button.setIcon(
                QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "window-copy.svg"))
            )
            self.maximize_button.setIconSize(QSize(15, 15))
            self.maximize_button.setToolTip("Restaurar")
        else:
            self.maximize_button.setText("")
            self.maximize_button.setIcon(
                QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "window-square.svg"))
            )
            self.maximize_button.setIconSize(QSize(15, 15))
            self.maximize_button.setToolTip("Maximizar")

    def _position_title(self) -> None:
        self.title.adjustSize()
        self.title.move(
            (self.width() - self.title.width()) // 2,
            (self.height() - self.title.height()) // 2,
        )
        self.title.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_title()

    def _add_control(
        self,
        layout: QHBoxLayout,
        symbol: str,
        tooltip: str,
        callback,
        icon_filename: str | None = None,
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("windowControl")
        if icon_filename is None:
            button.setText(symbol)
        else:
            button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_filename)))
            button.setIconSize(QSize(15, 15))
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
            self.set_maximized(False)
        else:
            self.window.showMaximized()
            self.set_maximized(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window.windowHandle()
            if handle and not self.window.isMaximized() and handle.startSystemMove():
                event.accept()
                return
            self._drag_origin = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin and event.buttons() & Qt.MouseButton.LeftButton:
            current = event.globalPosition().toPoint()
            if not self.window.isMaximized():
                self.window.move(self.window.pos() + current - self._drag_origin)
            self._drag_origin = current
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        super().mouseDoubleClickEvent(event)


class WindowFrame(QWidget):
    """Paint the shadow separately from VTK and expose native resize handles."""

    MARGIN = 18
    BORDER = 5

    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setMouseTracking(True)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
        self.body = QVBoxLayout(self)
        self.body.setSpacing(0)
        self.update_state()

    def update_state(self):
        margin = 0 if self.owner.isMaximized() else self.MARGIN
        self.body.setContentsMargins(margin, margin, margin, margin)
        self.unsetCursor()
        self.update()

    def paintEvent(self, event):
        if self.owner.isMaximized():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        rect = QRectF(self.rect()).adjusted(18, 18, -18, -18)
        for spread in range(17, 0, -1):
            painter.setBrush(QColor(0, 0, 0, 3 if spread > 8 else 6))
            painter.drawRoundedRect(rect.adjusted(-spread, -spread + 2, spread, spread + 2),
                                    spread, spread)

    def edges_at(self, point):
        edges = Qt.Edge(0)
        if self.owner.isMaximized():
            return edges
        left = self.MARGIN
        right = self.width() - self.MARGIN
        top = self.MARGIN
        bottom = self.height() - self.MARGIN
        # Only the five-pixel frame immediately around the content is active.
        if left <= point.x() < left + self.BORDER:
            edges |= Qt.Edge.LeftEdge
        elif right - self.BORDER < point.x() <= right:
            edges |= Qt.Edge.RightEdge
        if top <= point.y() < top + self.BORDER:
            edges |= Qt.Edge.TopEdge
        elif bottom - self.BORDER < point.y() <= bottom:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            global_point = event.globalPosition().toPoint()
            local_point = self.mapFromGlobal(global_point)
            inside = self.rect().contains(local_point)
            edges = self.edges_at(local_point) if inside else Qt.Edge(0)
            if event.type() == QEvent.Type.MouseMove:
                self._set_resize_cursor(edges)
            elif event.button() == Qt.MouseButton.LeftButton and edges:
                handle = self.owner.windowHandle()
                if handle and handle.startSystemResize(edges):
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def _set_resize_cursor(self, edges) -> None:
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            same = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if same else Qt.CursorShape.SizeBDiagCursor)
        elif horizontal or vertical:
            self.setCursor(Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mouseMoveEvent(self, event):
        self._set_resize_cursor(self.edges_at(event.position()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        edges = self.edges_at(event.position())
        handle = self.owner.windowHandle()
        if (event.button() == Qt.MouseButton.LeftButton and edges and handle
                and handle.startSystemResize(edges)):
            event.accept()
            return
        super().mousePressEvent(event)
