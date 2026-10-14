"""A versão publicada deve coincidir com a exibida no menu Ajuda > Sobre."""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from osa.ui.dialogs import AboutDialog


def test_about_dialog_displays_project_version():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None

    app = QApplication.instance() or QApplication([])
    dialog = AboutDialog()
    version_label = dialog.findChild(QLabel, "aboutVersion")
    assert version_label is not None
    assert version_label.text() == f"Versão {match.group(1)}"
    dialog.close()
    assert app is not None
