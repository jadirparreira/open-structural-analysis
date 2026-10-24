import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from osa.ui.dialogs import DetailingExportSuccessDialog


def test_export_success_modal_uses_compact_program_style():
    app = QApplication.instance() or QApplication([])
    dialog = DetailingExportSuccessDialog()

    labels = dialog.findChildren(QLabel)
    buttons = dialog.findChildren(QPushButton)
    assert len(labels) == 1
    assert labels[0].text() == "Arquivo DXF exportado com sucesso"
    assert not labels[0].wordWrap()
    assert len(buttons) == 1
    assert buttons[0].text() == "Fechar"
    assert buttons[0].icon().isNull()
    assert buttons[0].objectName() == "closeProperties"
    assert dialog.width() == 360
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert "border-radius: 0px" in dialog.styleSheet()
    dialog.close()
    assert app is not None
