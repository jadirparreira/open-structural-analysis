"""Manage drawing references without exposing selectable objects in the viewport."""

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QListWidgetItem

from .common import *
from .loading_indicator import LoadingIndicator
from .property_panel import CompactDoubleSpinBox, PropertyPanel
from .window_frame import WindowFrame


class _ImportWorker(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, filename):
        super().__init__()
        self.filename = filename

    @Slot()
    def run(self):
        try:
            from osa.importers.drawing_reference import import_drawing_reference
            self.loaded.emit(import_drawing_reference(self.filename))
        except Exception as error:  # noqa: BLE001 - report worker failures without leaving a running dialog
            self.failed.emit(str(error))
        finally:
            self.finished.emit()


class ReferenceImportDialog(QDialog):
    def __init__(self, parent, filename):
        super().__init__(parent)
        self.setWindowTitle("Importar referência")
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setFixedWidth(360)
        layout = QVBoxLayout(self)
        label = QLabel("Importando o desenho e preparando a geometria…")
        label.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(LoadingIndicator(self))
        self.result_data = None
        self.error = None
        self.thread = QThread(self)
        self.worker = _ImportWorker(filename)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.loaded.connect(self._loaded)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.accept)
        QTimer.singleShot(0, self.thread.start)

    @Slot(object)
    def _loaded(self, result):
        self.result_data = result

    @Slot(str)
    def _failed(self, error):
        self.error = error

    def reject(self):
        if not self.thread.isRunning():
            super().reject()


class ReferenceRow(QFrame):
    selected = Signal()
    remove_requested = Signal()

    def __init__(self, reference, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 4, 4, 4)
        layout.setSpacing(7)
        self.checkbox = QCheckBox()
        self.checkbox.setAccessibleName(f"Exibir referência {reference.name}")
        self.checkbox.setChecked(reference.visible)
        layout.addWidget(self.checkbox)
        self._name = reference.name
        self.label = QLabel()
        self.label.setToolTip(reference.name)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.label, 1)
        self.remove_button = QToolButton()
        self.remove_button.setObjectName("paletteSecondary")
        self.remove_button.setFixedSize(22, 22)
        self.remove_button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources/icons/x.svg")))
        self.remove_button.setIconSize(QSize(14, 14))
        self.remove_button.setToolTip("Remover referência")
        self.remove_button.setAccessibleName(f"Remover referência {reference.name}")
        policy = self.remove_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.remove_button.setSizePolicy(policy)
        self.remove_button.clicked.connect(self.remove_requested)
        layout.addWidget(self.remove_button)
        self.remove_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.label.setText(self.label.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight,
                                                            self.label.width()))

    def enterEvent(self, event):
        self.remove_button.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.remove_button.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit()
        super().mousePressEvent(event)


class ReferencePanel(QFrame):
    visibility_changed = Signal(bool)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._loading = False
        self.setObjectName("propertyPanel")
        self.setFixedWidth(window.properties.width())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(7)
        title = QLabel("Referências")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        self.list = QListWidget()
        self.list.setFixedHeight(120)
        self.list.setStyleSheet(
            "QListWidget { border: 1px solid #d0d7de; border-radius: 6px; background: white; color: #24292f; }"
            "QListWidget::item { padding: 0; border: 0; }"
            "QListWidget::item:selected { background: #ddf4ff; color: #24292f; }"
        )
        self.list.currentRowChanged.connect(self._load_selection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.list)
        self.empty_label = QLabel("Nenhuma referência importada.")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        subtitle = QLabel("Parâmetros")
        subtitle.setObjectName("propertySection")
        layout.addWidget(subtitle)
        self.form = QWidget()
        form = QFormLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        self.plane = QComboBox()
        self.plane.addItems(("XY", "XZ", "YZ"))
        self.plane.currentTextChanged.connect(self._commit)
        form.addRow("Plano", self.plane)
        self.coordinates = []
        for axis in ("X", "Y", "Z"):
            coordinate = CompactDoubleSpinBox()
            coordinate.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            coordinate.setRange(-1e12, 1e12)
            coordinate.setDecimals(6)
            coordinate.setKeyboardTracking(False)
            coordinate.setAccessibleName(f"Origem {axis} da referência")
            coordinate.valueChanged.connect(self._commit)
            self.coordinates.append(coordinate)
            form.addRow(axis, PropertyPanel._editable_unit_box(coordinate, "m"))
        layout.addWidget(self.form)
        hint = QLabel("Marque a referência para exibi-la. As coordenadas deslocam a origem do desenho.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #57606a; font-size: 11px;")
        layout.addWidget(hint)
        self.hide()

    def showEvent(self, event):
        self.reload()
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.window.scene.set_selected_drawing_reference(None)
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            trigger = self.window.top_icon_palette.configure_reference_button
            position = event.globalPosition().toPoint()
            inside = self.rect().contains(self.mapFromGlobal(position)) or self is watched or self.isAncestorOf(watched)
            on_trigger = (
                trigger.rect().contains(trigger.mapFromGlobal(position))
                or trigger is watched or trigger.isAncestorOf(watched)
            )
            in_window = watched is self.window or self.window.isAncestorOf(watched)
            if not inside and not on_trigger and in_window:
                # Popup controls (e.g. Plano) are descendants of this panel and
                # remain interactive even when their window extends outside it.
                self.hide()
        return super().eventFilter(watched, event)

    def reload(self, selected_id=None):
        if selected_id is None and self.list.currentItem():
            selected_id = self.list.currentItem().data(Qt.ItemDataRole.UserRole)
        self._loading = True
        self.list.clear()
        selected_row = 0
        for row, reference in enumerate(self.window.model.references.values()):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, reference.id)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, reference.name)
            item.setSizeHint(QSize(0, 32))
            self.list.addItem(item)
            widget = ReferenceRow(reference, self.list)
            widget.selected.connect(lambda item=item: self.list.setCurrentItem(item))
            widget.checkbox.toggled.connect(
                lambda visible, item=item: self._visibility_changed(item, visible)
            )
            widget.remove_requested.connect(lambda reference_id=reference.id: self._remove(reference_id))
            self.list.setItemWidget(item, widget)
            if reference.id == selected_id:
                selected_row = row
        self.list.setCurrentRow(selected_row)
        self._loading = False
        self.empty_label.setVisible(not self.list.count())
        self._load_selection()

    def _selected(self):
        item = self.list.currentItem()
        return self.window.model.references.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _load_selection(self, *_):
        if self._loading:
            return
        reference = self._selected()
        self.form.setEnabled(reference is not None)
        self._loading = True
        self.plane.setCurrentText(reference.plane if reference else "XY")
        for field, value in zip(self.coordinates, reference.origin if reference else (0, 0, 0)):
            field.setValue(value)
        self._loading = False
        if self.isVisible():
            self.window.scene.set_selected_drawing_reference(reference.id if reference else None)

    def _commit(self, *_):
        reference = self._selected()
        if not self._loading and reference:
            self.window.model.update_reference(
                reference.id, origin=tuple(field.value() for field in self.coordinates),
                plane=self.plane.currentText(),
            )
            self.window.scene.refresh_drawing_references(self.window.model)

    def _visibility_changed(self, item, visible):
        if not self._loading:
            self.list.setCurrentItem(item)
            self.window.model.update_reference(
                item.data(Qt.ItemDataRole.UserRole), visible=visible,
            )
            self.window.scene.refresh_drawing_references(self.window.model)

    def _remove(self, reference_id=None):
        reference = self._selected()
        reference_id = reference_id or (reference.id if reference else None)
        if reference_id:
            self.window.model.remove_reference(reference_id)
            self.window.scene.refresh_drawing_references(self.window.model)
            self.reload()

    def reposition(self):
        self.adjustSize()
        margin = 0 if self.window.isMaximized() else WindowFrame.MARGIN
        self.move(self.window.width() - margin - self.width() - 24,
                  max(margin + 60, (self.window.height() - self.height()) // 2))
        self.raise_()
