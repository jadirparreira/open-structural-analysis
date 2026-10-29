from .common import *


class ProfileComboBox(QComboBox):
    """Compact profile picker with a bounded, scrollable popup."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup: QFrame | None = None
        self._list: QListWidget | None = None

    def paintEvent(self, event) -> None:
        secondary_name = self.currentData(Qt.ItemDataRole.UserRole + 1)
        if not secondary_name or not self.currentText():
            super().paintEvent(event)
            return

        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        text_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        ).adjusted(2, 0, -2, 0)
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(self.font())
        document.setHtml(
            f'<span style="color:#57606a;font-size:11pt">{escape(self.currentText())}</span>'
            f'&nbsp;&nbsp;<span style="color:#8c959f;font-size:9pt">{escape(str(secondary_name))}</span>'
        )
        document.setTextWidth(text_rect.width())
        document_height = document.documentLayout().documentSize().height()
        painter.save()
        painter.setClipRect(text_rect)
        painter.translate(text_rect.left(), text_rect.top() + max(0.0, (text_rect.height() - document_height) / 2.0))
        document.drawContents(painter)
        painter.restore()

    def showPopup(self) -> None:
        self.hidePopup()
        popup = QFrame(self, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("profilePopup")
        popup.setStyleSheet("QFrame#profilePopup { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; } QListWidget { border: 0; background: transparent; outline: 0; color: #24292f; } QListWidget::item { padding: 7px 9px; color: #24292f; } QListWidget::item:selected { background: #eaeef2; color: #24292f; }")
        screen = self.screen().availableGeometry()
        items = [self.itemText(i) for i in range(self.count())]
        secondary_label_role = Qt.ItemDataRole.UserRole + 1
        popup_width = min(self.width(), screen.width())
        popup.setFixedWidth(popup_width)
        box = QVBoxLayout(popup); box.setContentsMargins(2, 2, 2, 2); box.setSpacing(0)
        listing = QListWidget(); listing.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        for index, text in enumerate(items):
            secondary_name = self.itemData(index, secondary_label_role)
            item = QListWidgetItem("" if secondary_name else text)
            item.setData(Qt.ItemDataRole.UserRole, text)
            listing.addItem(item)
            if secondary_name:
                row = QWidget(listing)
                row.setStyleSheet("background: transparent;")
                row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(9, 0, 9, 0)
                row_layout.setSpacing(8)
                secondary = QLabel(str(secondary_name), row)
                secondary.setStyleSheet("color: #8c959f; font-size: 9pt; background: transparent;")
                primary = QLabel(text, row)
                primary.setStyleSheet("color: #24292f; font-size: 10pt; background: transparent;")
                row_layout.addWidget(primary)
                row_layout.addWidget(secondary)
                row_layout.addStretch(1)
                listing.setItemWidget(item, row)
        listing.setUniformItemSizes(True); listing.setCurrentRow(self.currentIndex())
        # Explicit item heights make the vertical rhythm deterministic across
        # Qt styles (stylesheet padding alone is not honored consistently).
        for index in range(listing.count()):
            listing.item(index).setSizeHint(QSize(popup_width - 28, 32))
        box.addWidget(listing)
        row_h = 32
        listing.setFixedHeight(min(8, len(items)) * row_h + 2 if items else 2)
        listing.itemClicked.connect(
            lambda item: (self.setCurrentText(item.data(Qt.ItemDataRole.UserRole)), self.hidePopup())
        )
        self._popup, self._list = popup, listing
        popup.adjustSize()
        point = self.mapToGlobal(QPoint(0, self.height()))
        x = min(max(point.x(), screen.left()), screen.right() - popup.width() + 1)
        y = point.y()
        if y + popup.height() > screen.bottom() + 1:
            y = max(screen.top(), self.mapToGlobal(QPoint(0, 0)).y() - popup.height())
        popup.move(x, y)
        popup.show()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.close(); self._popup.deleteLater()
            self._popup = None; self._list = None
        super().hidePopup()
