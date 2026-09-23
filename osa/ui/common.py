"""Importações compartilhadas pelos widgets durante a migração modular."""
from __future__ import annotations

import sys
from html import escape
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QAction, QColor, QIcon, QIntValidator, QKeySequence, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
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
from osa.services import (
    ActionService,
    MaterialService,
    ModelService,
    ProjectService,
    SectionPropertyService,
    SectionService,
)

from .theme import APP_STYLESHEET

_catalog_profiles = CatalogLoader().w_profiles()
GERDAU_W_PROFILES = [item["name"] for item in _catalog_profiles]
GERDAU_W_CATALOG = {item["name"]: item for item in _catalog_profiles}

def _catalog_profiles_for(family_name: str) -> tuple[dict, ...]:
    return next(
        (tuple(family.get("profiles", ()))
         for family in CatalogLoader().section_families("Aço")
         if family.get("name") == family_name),
        (),
    )

_catalog_u_profiles = _catalog_profiles_for("U Laminado")
GERDAU_U_PROFILES = [item["name"] for item in _catalog_u_profiles]
GERDAU_U_CATALOG = {item["name"]: item for item in _catalog_u_profiles}
_catalog_i_profiles = _catalog_profiles_for("I Laminado")
GERDAU_I_PROFILES = [item["name"] for item in _catalog_i_profiles]
GERDAU_I_CATALOG = {item["name"]: item for item in _catalog_i_profiles}

_catalog_l_profiles = _catalog_profiles_for("L Laminado")
GERDAU_L_PROFILES = [item["name"] for item in _catalog_l_profiles]
GERDAU_L_DATA = {item["name"]: item for item in _catalog_l_profiles}

_catalog_t_profiles = _catalog_profiles_for("T Laminado")
GERDAU_T_PROFILES = [item["name"] for item in _catalog_t_profiles]
GERDAU_T_DATA = {item["name"]: item for item in _catalog_t_profiles}

SECTION_PROFILE_OPTIONS = {
    "W Laminado": GERDAU_W_PROFILES,
    "I Laminado": GERDAU_I_PROFILES,
    "U Laminado": GERDAU_U_PROFILES,
    "L Laminado": GERDAU_L_PROFILES,
    "T Laminado": GERDAU_T_PROFILES,
}
SECTION_PROFILE_DATA = {
    "W Laminado": GERDAU_W_CATALOG,
    "I Laminado": GERDAU_I_CATALOG,
    "U Laminado": GERDAU_U_CATALOG,
    "L Laminado": GERDAU_L_DATA,
    "T Laminado": GERDAU_T_DATA,
}

# Families manufactured from sheet, tube or bar stock are intentionally not
# catalogued. Their dimensions are entered directly in the section panel.
SECTION_PARAMETRIC_SPECS = {
    "U Formado": (
        ("d", "Altura total da seção", "mm"),
        ("bf", "Largura da aba", "mm"),
        ("t", "Espessura da chapa", "mm"),
    ),
    "C Formado": (
        ("d", "Altura total da seção", "mm"),
        ("bf", "Largura da aba", "mm"),
        ("c", "Comprimento do enrijecedor", "mm"),
        ("t", "Espessura da chapa", "mm"),
    ),
    "Z Formado": (
        ("d", "Altura total da seção", "mm"),
        ("bf", "Largura da aba", "mm"),
        ("t", "Espessura da chapa", "mm"),
    ),
    "L Formado": (
        ("d", "Altura da aba vertical", "mm"),
        ("bf", "Largura da aba horizontal", "mm"),
        ("t", "Espessura da chapa", "mm"),
    ),
    "Cartola Formado": (
        ("d", "Altura total da seção", "mm"),
        ("bf", "Largura da mesa", "mm"),
        ("t", "Espessura da chapa", "mm"),
        ("c", "Comprimento do enrijecedor", "mm"),
    ),
    "Tubular Circular": (
        ("D", "Diâmetro externo", "mm"),
        ("t", "Espessura da parede", "mm"),
    ),
    "Tubular Quadrado": (
        ("b", "Lado externo", "mm"),
        ("t", "Espessura da parede", "mm"),
    ),
    "Tubular Retangular": (
        ("b", "Largura externa", "mm"),
        ("h", "Altura externa", "mm"),
        ("t", "Espessura da parede", "mm"),
    ),
    "Barra Circular": (("d", "Diâmetro", "mm"),),
    "Barra Quadrada": (("b", "Lado", "mm"),),
    "Barra Retangular": (
        ("b", "Largura", "mm"),
        ("h", "Altura", "mm"),
    ),
    # Wood sections use the same solid-bar geometry as the steel bar
    # families, but keep the material catalog names Circular/Quadrada/
    # Retangular.
    "Quadrada": (("b", "Lado", "mm"),),
    # Concrete families use the same parameter-entry panel as the other
    # non-catalogued sections. These are the initial idealized dimensions;
    # their analytical properties and drawings can evolve independently.
    "Retangular": (
        ("b", "Largura total da seção", "mm"),
        ("h", "Altura total da seção", "mm"),
    ),
    "Circular": (("d", "Diâmetro externo", "mm"),),
    "Tipo L": (
        ("b", "Largura da aba horizontal", "mm"),
        ("h", "Altura da aba vertical", "mm"),
        ("t", "Espessura das abas", "mm"),
    ),
    "Tipo T": (
        ("b", "Largura total da seção", "mm"),
        ("h", "Altura total da seção", "mm"),
        ("t", "Espessura da seção", "mm"),
    ),
    "Tipo I": (
        ("b", "Largura total da seção", "mm"),
        ("h", "Altura total da seção", "mm"),
        ("t", "Espessura da seção", "mm"),
    ),
    "Tipo U": (
        ("b", "Largura total da seção", "mm"),
        ("h", "Altura total da seção", "mm"),
        ("t", "Espessura da seção", "mm"),
    ),
    "Tipo +": (
        ("b", "Largura total da seção", "mm"),
        ("h", "Altura total da seção", "mm"),
        ("t", "Espessura da seção", "mm"),
    ),
    "Retangular Vazado": (
        ("b", "Largura externa", "mm"),
        ("h", "Altura externa", "mm"),
        ("t", "Espessura das paredes", "mm"),
    ),
    "Circular Vazado": (
        ("d", "Diâmetro externo", "mm"),
        ("t", "Espessura da parede", "mm"),
    ),
}
