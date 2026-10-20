"""Modal dialog for configuring a member split by segment lengths."""

import math
from PySide6.QtCore import QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QScrollArea

from .common import *


class SegmentLengthEditor(QLineEdit):
    focusChanged = Signal(bool)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focusChanged.emit(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.focusChanged.emit(False)


class SegmentLengthInput(QFrame):
    """Positive numeric input with a three-decimal display and full value precision."""

    textChanged = Signal(str)
    focusChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._display_text = ""
        self._was_edited = False
        self._previous_value = 0.0
        self._focused = False
        self.setObjectName("segmentLengthInput")
        self.setFixedHeight(34)
        self._muted = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.editor = SegmentLengthEditor(self)
        self.editor.setObjectName("segmentLengthEditor")
        self.editor.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"(?:\d+(?:[.,]\d*)?|[.,]\d+)"), self,
        ))
        self.editor.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.editor.setStyleSheet(
            "QLineEdit#segmentLengthEditor { min-width: 0; border: 0; background: transparent; "
            "color: #24292f; padding: 2px 9px; }"
        )
        self.unit_label = QLabel("m", self)
        self.unit_label.setObjectName("hint")
        self.unit_label.setContentsMargins(0, 0, 9, 0)
        row.addWidget(self.editor, 1)
        row.addWidget(self.unit_label)
        self.setFocusProxy(self.editor)
        self.editor.textEdited.connect(self._mark_edited)
        self.editor.textChanged.connect(self.textChanged.emit)
        self.editor.editingFinished.connect(self.commit_edit)
        self.editor.focusChanged.connect(self._set_focused)
        self.set_muted(False)

    def setValue(self, value: float) -> None:
        self._value = float(value)
        self._previous_value = self._value
        self._display_text = f"{self._value:.3f}"
        self._was_edited = False
        self.editor.setText(self._display_text)

    def value(self) -> float:
        if not self._was_edited:
            return self._value
        try:
            value = float(self.editor.text().strip().replace(",", "."))
        except ValueError:
            return 0.0
        return value if math.isfinite(value) and value > 0 else 0.0

    def previous_value(self) -> float:
        return self._previous_value

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        background = "#f6f8fa" if muted else "#ffffff"
        text_color = "#57606a" if muted else "#24292f"
        border_color = "#0969da" if self._focused else "#d0d7de"
        border_width = 2 if self._focused else 1
        self.setStyleSheet(
            "QFrame#segmentLengthInput { min-width: 0; "
            f"border: {border_width}px solid {border_color}; border-radius: 6px; background: {background}; }}"
        )
        self.editor.setStyleSheet(
            "QLineEdit#segmentLengthEditor { min-width: 0; border: 0; background: transparent; "
            f"color: {text_color}; padding: 2px 9px; }}"
        )
        self.unit_label.setStyleSheet(f"color: {text_color};")

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self.set_muted(self._muted)
        self.focusChanged.emit(focused)

    def _mark_edited(self, _text: str) -> None:
        if not self._was_edited:
            self._previous_value = self._value
        self._was_edited = True

    def commit_edit(self) -> None:
        value = self.value()
        if self._was_edited and value > 0:
            self._value = value
            self._display_text = f"{value:.3f}"
            self._was_edited = False
            self.editor.setText(self._display_text)
        elif self._was_edited:
            self._value = self._previous_value
            self._display_text = f"{self._value:.3f}"
            self._was_edited = False
            self.editor.setText(self._display_text)


class SplitMemberDialog(QDialog):
    """Configure custom segment lengths in a centered modal window."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window
        self.member_name: str | None = None
        self.member_length: float | None = None
        self._segment_rows: list[QWidget] = []
        self._segment_inputs: list[SegmentLengthInput] = []
        self._segment_lock_buttons: list[QToolButton] = []
        self._selected_segment: SegmentLengthInput | None = None
        self.setObjectName("splitMemberDialog")
        self.setWindowTitle("Dividir barra")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(400, 440)
        self.setMinimumWidth(400)
        self.setStyleSheet(
            "QDialog#splitMemberDialog { background: #ffffff; border: 1px solid #d0d7de; border-radius: 0px; }"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        titlebar = QFrame(self)
        titlebar.setObjectName("titleBar")
        titlebar.setFixedHeight(40)
        title_layout = QHBoxLayout(titlebar)
        title_layout.setContentsMargins(12, 6, 8, 6)
        title = QLabel("Dividir barra", titlebar)
        title.setObjectName("windowTitle")
        title_layout.addWidget(title)
        title_layout.addStretch(1)
        outer.addWidget(titlebar)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        member_info = QWidget(content)
        member_info_layout = QGridLayout(member_info)
        member_info_layout.setContentsMargins(0, 0, 0, 0)
        member_info_layout.setHorizontalSpacing(10)
        member_info_layout.setVerticalSpacing(4)
        identity_label = QLabel("Identidade", member_info)
        identity_label.setObjectName("propertySection")
        member_info_layout.addWidget(identity_label, 0, 0)
        total_label = QLabel("Comprimento", member_info)
        total_label.setObjectName("propertySection")
        member_info_layout.addWidget(total_label, 0, 1)
        self.member_identity = QLineEdit(content)
        self.member_identity.setReadOnly(True)
        self.member_identity.setObjectName("identityDisplay")
        member_info_layout.addWidget(self.member_identity, 1, 0)
        self.total_length_display = QLineEdit(content)
        self.total_length_display.setReadOnly(True)
        self.total_length_display.setObjectName("identityDisplay")
        member_info_layout.addWidget(self.total_length_display, 1, 1)
        member_info_layout.setColumnStretch(0, 1)
        member_info_layout.setColumnStretch(1, 1)
        layout.addWidget(member_info)

        header = QWidget(content)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(10)
        segments_title = QLabel("Segmentos")
        segments_title.setObjectName("propertySection")
        header_layout.addWidget(segments_title)
        header_layout.addStretch(1)
        self.remove_segment_button = self._step_button(
            "minus.svg", "Remover segmento", self._remove_segment,
        )
        self.add_segment_button = self._step_button(
            "plus.svg", "Adicionar segmento", self._add_segment,
        )
        self.equalize_segments_button = self._equalize_button()
        header_layout.addWidget(self.remove_segment_button)
        header_layout.addWidget(self.add_segment_button)
        header_layout.addWidget(self.equalize_segments_button)
        layout.addWidget(header)

        self.segment_list = QWidget(content)
        self.segment_list_layout = QVBoxLayout(self.segment_list)
        self.segment_list_layout.setContentsMargins(0, 0, 0, 0)
        self.segment_list_layout.setSpacing(6)
        self.segment_scroll = QScrollArea(content)
        self.segment_scroll.setWidgetResizable(True)
        self.segment_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.segment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.segment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.segment_scroll.setMaximumHeight(220)
        self.segment_scroll.setWidget(self.segment_list)
        self.segment_scroll.verticalScrollBar().rangeChanged.connect(
            self._update_scrollbar_gutter
        )
        layout.addWidget(self.segment_scroll)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_button = QPushButton("Cancelar", content)
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.apply_button = QPushButton("Dividir", content)
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(window.apply_split_member)
        footer.addWidget(self.apply_button)
        layout.addLayout(footer)
        outer.addWidget(content, 1)

    def open_for_member(self, member_name: str) -> None:
        """Show the modal window with two equal initial segments."""
        self._reset_form()
        self.member_name = member_name
        member = self.window.model.bars.get(member_name)
        if member is None:
            self.member_length = None
            self.member_identity.setText("Barra não encontrado")
            self.total_length_display.clear()
            self.apply_button.setEnabled(False)
            self._set_segment_lengths(())
        else:
            start = self.window.model.nodes[member.start_node]
            end = self.window.model.nodes[member.end_node]
            self.member_length = math.dist(
                (start.x, start.y, start.z),
                (end.x, end.y, end.z),
            )
            self.member_identity.setText(member_name)
            self.total_length_display.setText(f"{self.member_length:.3f} m")
            first = self.member_length / 2.0
            self._set_segment_lengths((first, self.member_length - first))
        self.move(self.window.geometry().center() - self.rect().center())
        self.exec()

    def done(self, result: int) -> None:
        """Discard all dialog state whenever this opening is closed."""
        self._reset_form()
        super().done(result)

    def _reset_form(self) -> None:
        self.member_name = None
        self.member_length = None
        self.member_identity.clear()
        self.total_length_display.clear()
        self._set_segment_lengths(())

    def split_configuration(self) -> tuple[str, tuple[float, ...]] | None:
        if self.member_name is None:
            return None
        lengths = tuple(field.value() for field in self._segment_inputs)
        if not self._segment_lengths_valid(lengths):
            return None
        return self.member_name, lengths

    def _step_button(self, icon_name: str, tooltip: str, callback) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(30, 30)
        button.setIcon(QIcon(str(Path(__file__).parents[1] / "resources" / "icons" / icon_name)))
        button.setIconSize(QSize(17, 17))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
            "QToolButton:disabled { color: #8c959f; background: #f6f8fa; }"
        )
        button.clicked.connect(callback)
        return button

    def _equalize_button(self) -> QToolButton:
        button = QToolButton(self)
        button.setFixedSize(30, 30)
        button.setText("=")
        button.setToolTip("Igualar segmentos destravados")
        button.setAccessibleName(button.toolTip())
        button.setStyleSheet(
            "QToolButton { border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; "
            "color: #24292f; font-size: 16px; font-weight: 600; }"
            "QToolButton:hover { background: #eaeef2; }"
            "QToolButton:pressed { background: #d0d7de; }"
            "QToolButton:disabled { color: #8c959f; background: #f6f8fa; }"
        )
        button.clicked.connect(self._equalize_unlocked_segments)
        return button

    def _set_segment_lengths(
        self,
        values: tuple[float, ...],
        locked: tuple[bool, ...] | None = None,
    ) -> None:
        while self.segment_list_layout.count():
            item = self.segment_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._segment_rows.clear()
        self._segment_inputs.clear()
        self._segment_lock_buttons.clear()
        self._selected_segment = None
        if locked is None or len(locked) != len(values):
            locked = (False,) * len(values)
        for index, value in enumerate(values, start=1):
            row = QWidget(self.segment_list)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 0, 0, 0)
            row_layout.setSpacing(10)
            label = QLabel(str(index), row)
            label.setObjectName("hint")
            row_layout.addWidget(label)
            field = SegmentLengthInput(row)
            field.setValue(value)
            field.editor.setReadOnly(locked[index - 1])
            field.setAccessibleName(f"Comprimento do segmento {index}")
            field.textChanged.connect(self._update_segment_summary)
            field.focusChanged.connect(
                lambda focused, field=field: self._segment_focused(field, focused)
            )
            row_layout.addWidget(field, 1)
            lock_button = QToolButton(row)
            lock_button.setFixedSize(30, 30)
            lock_button.setCheckable(True)
            lock_button.setChecked(locked[index - 1])
            lock_button.toggled.connect(
                lambda checked, button=lock_button: self._set_segment_locked(button, checked)
            )
            lock_button.setStyleSheet(
                "QToolButton { border: 1px solid #d0d7de; border-radius: 6px; background: #ffffff; }"
                "QToolButton:hover, QToolButton:checked { background: #eaeef2; }"
            )
            self._segment_lock_buttons.append(lock_button)
            self._set_lock_button_icon(lock_button, locked[index - 1])
            row_layout.addWidget(lock_button)
            field.editor.editingFinished.connect(
                lambda field=field: self._adjust_other_segments(field)
            )
            self._segment_rows.append(row)
            self._segment_inputs.append(field)
            self.segment_list_layout.addWidget(row)
        self.segment_list_layout.addStretch(1)
        self._refresh_segment_editability()
        self._update_segment_summary()
        QTimer.singleShot(0, self._update_scrollbar_gutter)

    def _update_scrollbar_gutter(self, *_args) -> None:
        scrollbar = self.segment_scroll.verticalScrollBar()
        right_margin = 10 if scrollbar.maximum() > scrollbar.minimum() else 0
        self.segment_list_layout.setContentsMargins(0, 0, right_margin, 0)

    def _add_segment(self) -> None:
        if len(self._segment_inputs) >= 100 or self.member_length is None:
            return
        values = tuple(field.value() for field in self._segment_inputs)
        locks = tuple(button.isChecked() for button in self._segment_lock_buttons)
        self._set_equal_segments(len(values) + 1, (*values, 0.0), (*locks, False))

    def _remove_segment(self) -> None:
        if len(self._segment_inputs) <= 2 or self.member_length is None:
            return
        values = tuple(field.value() for field in self._segment_inputs)
        locks = tuple(button.isChecked() for button in self._segment_lock_buttons)
        removable = (
            self._segment_inputs.index(self._selected_segment)
            if self._selected_segment in self._segment_inputs
            else len(self._segment_inputs) - 1
        )
        remaining_values = values[:removable] + values[removable + 1:]
        remaining_locks = locks[:removable] + locks[removable + 1:]
        if any(not locked for locked in remaining_locks):
            self._set_equal_segments(len(remaining_values), remaining_values, remaining_locks)
        else:
            self._set_segment_lengths(remaining_values, remaining_locks)

    def _segment_focused(self, field: SegmentLengthInput, focused: bool) -> None:
        if focused:
            self._selected_segment = field

    def _equalize_unlocked_segments(self) -> None:
        if not self._segment_inputs:
            return
        values = tuple(field.value() for field in self._segment_inputs)
        locks = tuple(button.isChecked() for button in self._segment_lock_buttons)
        self._set_equal_segments(len(values), values, locks)

    def _set_equal_segments(
        self,
        segment_count: int,
        values: tuple[float, ...],
        locked: tuple[bool, ...],
    ) -> None:
        if self.member_length is None or segment_count <= 0:
            return
        locked_total = math.fsum(value for value, is_locked in zip(values, locked) if is_locked)
        unlocked_count = sum(not is_locked for is_locked in locked)
        if unlocked_count == 0:
            return
        tolerance = max(self.window.model.coordinate_tolerance, 1e-9)
        remaining = self.member_length - locked_total
        if remaining <= tolerance * unlocked_count:
            return
        equal_length = remaining / unlocked_count
        lengths = tuple(
            value if is_locked else equal_length
            for value, is_locked in zip(values, locked)
        )
        last_unlocked = max(index for index, is_locked in enumerate(locked) if not is_locked)
        lengths = lengths[:last_unlocked] + (
            self.member_length - math.fsum(lengths[:last_unlocked]) - math.fsum(
                value for value, is_locked in zip(lengths[last_unlocked + 1:], locked[last_unlocked + 1:])
                if is_locked
            ),
        ) + lengths[last_unlocked + 1:]
        self._set_segment_lengths(lengths, locked)

    def _set_segment_locked(
        self,
        button: QToolButton,
        locked: bool,
    ) -> None:
        self._set_lock_button_icon(button, locked)
        self._refresh_segment_editability()
        self._update_segment_summary()

    def _refresh_segment_editability(self) -> None:
        count = len(self._segment_inputs)
        for index, field in enumerate(self._segment_inputs):
            locked = self._segment_lock_buttons[index].isChecked()
            left_unlocked = index > 0 and not self._segment_lock_buttons[index - 1].isChecked()
            right_unlocked = index + 1 < count and not self._segment_lock_buttons[index + 1].isChecked()
            unavailable = locked or not (left_unlocked or right_unlocked)
            field.editor.setReadOnly(unavailable)
            field.set_muted(unavailable)

    def _set_lock_button_icon(self, button: QToolButton, locked: bool) -> None:
        icon_name = "lock.svg" if locked else "lock-open.svg"
        icon_path = Path(__file__).parents[1] / "resources" / "icons" / icon_name
        button.setIcon(QIcon(str(icon_path)))
        button.setIconSize(QSize(17, 17))
        button.setToolTip("Destravar segmento" if locked else "Travar segmento")
        button.setAccessibleName(button.toolTip())

    def _adjust_other_segments(self, changed: SegmentLengthInput) -> None:
        """Keep the edited length and redistribute the remaining member length."""
        if self.member_length is None or changed not in self._segment_inputs:
            return
        target = changed.value()
        changed_index = self._segment_inputs.index(changed)
        adjacent_indices = tuple(
            index for index in (changed_index - 1, changed_index + 1)
            if 0 <= index < len(self._segment_inputs)
        )
        adjustable_indices = tuple(
            index for index in adjacent_indices
            if not self._segment_lock_buttons[index].isChecked()
        )
        if not adjustable_indices:
            changed.setValue(changed.previous_value())
            self._update_segment_summary()
            return
        fixed_total = math.fsum(
            field.value()
            for index, field in enumerate(self._segment_inputs)
            if index != changed_index and index not in adjustable_indices
        )
        others = [self._segment_inputs[index] for index in adjustable_indices]
        tolerance = max(self.window.model.coordinate_tolerance, 1e-9)
        available = self.member_length - target - fixed_total
        if target <= tolerance or available <= tolerance * len(others):
            changed.setValue(changed.previous_value())
            self._update_segment_summary()
            return

        old_values = [field.value() for field in others]
        old_total = math.fsum(old_values)
        distributable = available - tolerance * len(others)
        weights_total = old_total if old_total > 0 else float(len(others))
        adjusted = [
            tolerance + distributable * (value / weights_total if old_total > 0 else 1 / len(others))
            for value in old_values
        ]
        adjusted[-1] = available - math.fsum(adjusted[:-1])
        for field, value in zip(others, adjusted):
            field.setValue(value)
        changed.setValue(target)
        self._update_segment_summary()

    def _segment_lengths_valid(self, values: tuple[float, ...]) -> bool:
        if self.member_length is None or len(values) < 2 or any(value <= 0 for value in values):
            return False
        tolerance = max(
            self.window.model.coordinate_tolerance,
            self.member_length * 1e-9,
            0.0000005 * len(values),
        )
        return math.isclose(
            math.fsum(values), self.member_length, rel_tol=1e-9, abs_tol=tolerance,
        )

    def _update_segment_summary(self, *_args) -> None:
        lengths = tuple(field.value() for field in self._segment_inputs)
        if self.member_length is None:
            self.apply_button.setEnabled(False)
            self.add_segment_button.setEnabled(False)
            self.remove_segment_button.setEnabled(False)
            self.equalize_segments_button.setEnabled(False)
            return
        valid = self._segment_lengths_valid(lengths)
        self.apply_button.setEnabled(valid)
        locked_total = math.fsum(
            field.value() for field, button in zip(self._segment_inputs, self._segment_lock_buttons)
            if button.isChecked()
        )
        unlocked_count = len(lengths) - sum(button.isChecked() for button in self._segment_lock_buttons)
        tolerance = max(self.window.model.coordinate_tolerance, 1e-9)
        self.add_segment_button.setEnabled(
            len(lengths) < 100
            and self.member_length - locked_total > tolerance * (unlocked_count + 1)
        )
        self.equalize_segments_button.setEnabled(
            unlocked_count > 0
            and self.member_length - locked_total > tolerance * unlocked_count
        )
        self.remove_segment_button.setEnabled(
            len(lengths) > 2
        )

    def reposition(self) -> None:
        if self.isVisible():
            self.move(self.window.geometry().center() - self.rect().center())
