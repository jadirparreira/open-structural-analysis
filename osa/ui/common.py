"""Importações compartilhadas pelos widgets durante a migração modular."""
from __future__ import annotations

import sys
from html import escape
from pathlib import Path

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from osa.commands import CommandSession
from osa.data import CatalogLoader
from osa.model import StructuralModel
from osa.scene import StructureScene
from osa.services import MaterialService, ModelService, ProjectService, SectionService

from .theme import APP_STYLESHEET

_catalog_profiles = CatalogLoader().w_profiles()
GERDAU_W_DATA = {
    item["name"]: (item["mass_kg_m"], item["d_mm"], item["bf_mm"], item["tw_mm"], item["tf_mm"], item["area_cm2"])
    for item in _catalog_profiles
}
GERDAU_W_PROFILES = list(GERDAU_W_DATA)
