"""Tema visual central da aplicação."""

APP_STYLESHEET = """
QMainWindow, QDialog { background: #ffffff; color: #24292f; }
QWidget#appFrame { background: #ffffff; }
QDialog { border: 1px solid #d0d7de; border-radius: 10px; }
QLabel#dialogTitle { font-size: 20px; font-weight: 700; color: #24292f; }
QLabel#hint { color: #57606a; }
QDoubleSpinBox, QComboBox {
    min-height: 34px; padding: 2px 9px; border: 1px solid #d0d7de;
    border-radius: 6px; background: #ffffff; color: #24292f;
}
QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid #0969da; }
QCheckBox { color: #57606a; spacing: 6px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #d0d7de;
    border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #0969da; }
QCheckBox::indicator:checked { background: #0969da; border-color: #0969da; }
QFrame#propertyPanel QDoubleSpinBox, QFrame#propertyPanel QComboBox {
    min-height: 30px; height: 30px;
}
QLineEdit#identityDisplay { min-height: 30px; padding: 2px 9px; border: 1px solid #d0d7de;
    border-radius: 6px; background: #ffffff; color: #57606a; }
QFrame#propertyPanel QComboBox::drop-down { width: 0px; border: 0; }
QFrame#propertyPanel QComboBox::down-arrow { image: none; }
QToolButton#menuButton { border: 0; border-radius: 6px; padding: 5px 10px; color: #24292f; }
QToolButton#menuButton:hover { background: #eaeef2; }
QToolButton#menuButton::menu-indicator { image: none; }
QMenu { background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px; padding: 5px; color: #24292f; }
QMenu::item { padding: 7px 28px 7px 10px; border-radius: 5px; }
QMenu::item:selected { background: #eaeef2; }
QMenu::separator { height: 1px; background: #d8dee4; margin: 5px 6px; }
QPushButton#primaryButton {
    min-height: 34px; padding: 4px 16px; border: 0; border-radius: 7px;
    background: #0969da; color: white; font-weight: 700;
}
QPushButton#primaryButton:hover { background: #0550ae; }
QPushButton#secondaryButton {
    min-height: 34px; padding: 4px 16px; border: 1px solid #d0d7de;
    border-radius: 7px; background: #f6f8fa; color: #24292f;
}
QPushButton#secondaryButton:hover { background: #eaeef2; }
QToolButton#palettePrimary {
    border: 1px solid #d0d7de; border-radius: 6px; padding: 0;
    background: #ffffff; color: #24292f;
}
QToolButton#palettePrimary:hover { background: #eaeef2; }
QToolButton#palettePrimary:checked,
QToolButton#palettePrimary:checked:hover { background: #eaeef2; color: #24292f; }
QToolButton#paletteSecondary {
    border: 0; border-radius: 7px; padding: 0;
    background: transparent; color: #57606a;
}
QToolButton#paletteSecondary:hover { background: #eaeef2; color: #24292f; }
QToolButton#paletteSecondary:pressed { background: #d0d7de; }
QLabel#paletteTooltip {
    min-height: 28px; padding: 4px 9px; border: 1px solid #57606a;
    border-radius: 6px; background: #24292f; color: #ffffff;
}
QFrame#titleBar { background: #e1e4e8; border-bottom: 1px solid #d0d7de; }
QLabel#windowTitle { color: #24292f; font-weight: 600; }
QToolButton#windowControl {
    min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
    border: 0; border-radius: 16px; color: #24292f; background: #e1e4e8; font-size: 16px;
}
QToolButton#windowControl:hover { background: #d0d7de; }
QToolButton#windowControl:pressed { background: #afb8c1; }
QFrame#commandBar { background: rgba(246, 248, 250, 248); border: 1px solid #d0d7de; border-radius: 12px; }
QFrame#commandHistory { background: rgba(246, 248, 250, 215); border: 1px solid #d0d7de; border-radius: 10px; }
QFrame#propertyPanel { background: rgba(246, 248, 250, 248); border: 1px solid #d0d7de; border-radius: 14px; }
QLabel#propertyTitle { color: #24292f; font-size: 15px; font-weight: 700; }
QLabel#propertyName { color: #57606a; font-size: 13px; padding-bottom: 5px; }
QLabel#propertySection { color: #57606a; font-size: 12px; font-weight: 600; padding-top: 4px; }
QScrollArea#historyScroll, QScrollArea#historyScroll QWidget#qt_scrollarea_viewport { background: transparent; border: 0; }
QScrollBar:vertical {
    background: transparent; width: 12px; margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical { background: #afb8c1; min-height: 28px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: #8c959f; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLabel#historyLine { color: #57606a; padding: 1px 8px; }
QLineEdit#commandInput { min-height: 36px; border: 1px solid #d0d7de; border-radius: 8px; background: #ffffff; color: #24292f; padding: 0 10px; }
QLineEdit#commandInput:focus { border: 2px solid #0969da; }
QToolTip { background: #24292f; color: #ffffff; border: 1px solid #57606a; }
"""
