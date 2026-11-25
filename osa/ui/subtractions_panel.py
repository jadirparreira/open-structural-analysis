"""List and preview detailing cuts received by one element."""

from pathlib import Path

from PySide6.QtWidgets import QLayout, QScrollArea

from .common import *


class SubtractionsPanel(QFrame):
    WIDTH = 300

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self._target: tuple[str, str] | None = None
        self.setObjectName("propertyPanel")
        self.setFixedWidth(self.WIDTH)
        self.setMaximumHeight(520)
        # identityDisplay fields have a 36 px minimum height in the app theme.
        # Keep the row at least that tall so Qt does not clip their bottom border.
        self._row_height = 36
        self._visible_row_count = 6
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self.title = QLabel("Subtrações")
        self.title.setObjectName("propertyTitle")
        layout.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("subtractionsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(
            "QScrollArea#subtractionsScroll { background: transparent; border: 0; }"
            "QScrollArea#subtractionsScroll QWidget#qt_scrollarea_viewport { "
            "background: transparent; border: 0; }"
            "QWidget#subtractionsContent { background: transparent; }"
        )
        self.scroll.viewport().setAutoFillBackground(False)
        self.rows = QWidget()
        self.rows.setObjectName("subtractionsContent")
        self.rows.setAutoFillBackground(False)
        self.rows_layout = QVBoxLayout(self.rows)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.scroll.setWidget(self.rows)
        layout.addWidget(self.scroll)
        self.empty_label = QLabel("Nenhuma subtração")
        self.empty_label.setObjectName("propertySection")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        self.hide()

    def configure_for(self, kind: str, name: str) -> None:
        self._target = (kind, name)
        element = self._element()
        references = (
            (*element.detail_subtractions, *(('end_cut', cut.identifier) for cut in getattr(element, "detail_end_cuts", ())))
            if element is not None else ()
        )
        self.title.setText("Subtrações")
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.empty_label.setVisible(not references)
        for cutter_kind, cutter_name in references:
            row = self._make_row(cutter_kind, cutter_name)
            self.rows_layout.addWidget(row)
        visible_rows = min(len(references), self._visible_row_count)
        row_spacing = self.rows_layout.spacing()
        visible_height = (
            visible_rows * self._row_height
            + max(0, visible_rows - 1) * row_spacing
        )
        content_height = (
            len(references) * self._row_height
            + max(0, len(references) - 1) * row_spacing
        )
        self.rows.setMinimumHeight(content_height)
        self.scroll.setVisible(bool(references))
        if references:
            self.scroll.setFixedHeight(visible_height)
        else:
            self.scroll.setMinimumHeight(0)
            self.scroll.setMaximumHeight(0)
        self.layout().activate()
        self.adjustSize()

    def _element(self):
        if self._target is None:
            return None
        kind, name = self._target
        return (self.window.model.bars if kind == "bar" else self.window.model.plates).get(name)

    def _make_row(self, cutter_kind: str, cutter_name: str) -> QWidget:
        row = QWidget(self.rows)
        row.setFixedHeight(self._row_height)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        if cutter_kind == "end_cut":
            cut = next(
                (item for item in getattr(self._element(), "detail_end_cuts", ())
                 if item.identifier == cutter_name),
                None,
            )
            label = f"Extremidade — {cut.reference_label}" if cut is not None else "Extremidade cortada"
        else:
            label = f"{'Barra' if cutter_kind == 'bar' else 'Placa'} {cutter_name}"
        field = QLineEdit(label)
        field.setReadOnly(True)
        field.setObjectName("identityDisplay")
        field.setStyleSheet(
            "QLineEdit#identityDisplay { min-height: 30px; padding: 2px 9px; "
            "border: 1px solid #d0d7de; border-radius: 6px; "
            "background: #ffffff; color: #57606a; }"
        )
        field.setAccessibleName("Elemento recortador")
        field.setToolTip(f"Elemento que recortou: {cutter_name}")
        layout.addWidget(field, 1)

        reference = (cutter_kind, cutter_name)
        target = self._target
        preview_key = (*target, *reference) if target is not None else None
        visible = preview_key in self.window._detail_subtraction_visible_refs
        eye = QToolButton(row)
        eye.setFixedSize(34, 34)
        eye.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 6px; padding: 0; }"
            "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        eye.setCheckable(True)
        eye.setChecked(visible)
        eye.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" /
                               ("eye.svg" if visible else "eye-closed.svg"))))
        eye.setIconSize(QSize(18, 18))
        eye.setToolTip("Ocultar trecho recortado" if visible else "Visualizar trecho recortado")
        eye.setAccessibleName("Visualizar trecho recortado")
        eye.clicked.connect(
            lambda checked, t=target, r=reference, button=eye:
            self._toggle_preview(t, r, checked, button)
        )
        layout.addWidget(eye)

        delete = QToolButton(row)
        delete.setFixedSize(34, 34)
        delete.setStyleSheet(
            "QToolButton { background: #ffffff; border: 1px solid #d0d7de; "
            "border-radius: 6px; padding: 0; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
        )
        delete.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / "trash-2.svg")))
        delete.setIconSize(QSize(18, 18))
        delete.setToolTip("Remover subtração")
        delete.setAccessibleName("Remover subtração")
        delete.clicked.connect(lambda _checked=False, t=target, r=reference: self.window.remove_detail_subtraction(t, r))
        layout.addWidget(delete)
        return row

    def _toggle_preview(self, target, reference, visible: bool, button) -> None:
        self.window.set_detail_subtraction_preview(target, reference, visible)
        button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" /
                                 ("eye.svg" if visible else "eye-closed.svg"))))
        button.setToolTip("Ocultar trecho recortado" if visible else "Visualizar trecho recortado")

    def reposition(self) -> None:
        prop = self.window.properties
        self.move(prop.x() - self.width() - 12,
                  prop.y() + (prop.height() - self.height()) // 2)
        self.raise_()
