"""Shared appearance and scrolling behavior for selector lists."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QListView, QStyledItemDelegate


MAX_VISIBLE_ITEMS = 12

SELECTOR_LIST_STYLE = """
QListView {
    background: #ffffff;
    color: #24292f;
    border: 1px solid #d0d7de;
    outline: 0;
    selection-background-color: #eaeef2;
    selection-color: #24292f;
}
QListView::item {
    min-height: 24px;
    padding: 4px 9px;
    border: 0;
    color: #24292f;
}
QListView::item:hover, QListView::item:selected {
    background: #eaeef2;
    color: #24292f;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #afb8c1;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover { background: #8c959f; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""



class _SelectorListView(QListView):
    def showEvent(self, event) -> None:
        # QComboBox can reset the view's scrollbar policy when opening its popup.
        model = self.model()
        overflowing = model is not None and model.rowCount(self.rootIndex()) > MAX_VISIBLE_ITEMS
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
            if overflowing else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        super().showEvent(event)


class SelectorComboBox(QComboBox):
    """Standard selector with a bounded popup and visible overflow scrollbar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMaxVisibleItems(MAX_VISIBLE_ITEMS)
        view = _SelectorListView(self)
        view.setItemDelegate(QStyledItemDelegate(view))
        view.setStyleSheet(SELECTOR_LIST_STYLE)
        view.setUniformItemSizes(True)
        view.setMouseTracking(True)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.setView(view)

    def showPopup(self) -> None:
        # Apply after any field-specific stylesheet, which controls the closed field.
        popup_style = "QComboBox { combobox-popup: 0; }"
        if popup_style not in self.styleSheet():
            self.setStyleSheet(self.styleSheet() + "\n" + popup_style)
        super().showPopup()
