from .common import *


class ProfileComboBox(QComboBox):
    """Compact profile picker with a bounded, scrollable popup."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: QFrame | None = None
        self._list: QListWidget | None = None

    def showPopup(self) -> None:
        self.hidePopup()
        popup = QFrame(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("profilePopup")
        popup.setStyleSheet("QFrame#profilePopup { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } QListWidget { border: 0; background: transparent; outline: 0; color: #24292f; } QListWidget::item { padding: 7px 9px; color: #24292f; } QListWidget::item:selected { background: #eaeef2; color: #24292f; }")
        popup.setFixedWidth(max(self.width(), 220))
        box = QVBoxLayout(popup); box.setContentsMargins(2, 2, 2, 2); box.setSpacing(0)
        items = [self.itemText(i) for i in range(self.count())]
        listing = QListWidget(); listing.addItems(items); listing.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        listing.setUniformItemSizes(True); listing.setCurrentRow(self.currentIndex())
        # Explicit item heights make the vertical rhythm deterministic across
        # Qt styles (stylesheet padding alone is not honored consistently).
        for index in range(listing.count()):
            listing.item(index).setSizeHint(QSize(0, 32))
        box.addWidget(listing)
        row_h = 32
        listing.setFixedHeight(min(8, len(items)) * row_h + 2 if items else 2)
        popup.adjustSize()
        listing.itemClicked.connect(lambda item: (self.setCurrentText(item.text()), self.hidePopup()))
        self._popup, self._list = popup, listing
        popup.move(self.mapToGlobal(QPoint(0, self.height())))
        popup.show()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.close(); self._popup.deleteLater()
            self._popup = None; self._list = None
