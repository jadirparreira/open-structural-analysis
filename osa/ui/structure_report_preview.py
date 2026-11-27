"""In-app PDF preview and background generation for the general report."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal, Slot, QModelIndex
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfBookmarkModel, QPdfDocument
from PySide6.QtPdf import QPdfPageRenderer
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from osa.reports.structure_report import ReportOptions, export_structure_report


class StructureReportPreview(QWidget):
    """Scrollable multipage preview of the general structural report."""

    export_requested = Signal()
    document_ready = Signal()
    document_unavailable = Signal()
    document_failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("structureReportPreview")
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            "QWidget#structureReportPreview { background: #f6f8fa; }"
            "QLabel#reportPreviewMessage { color: #57606a; font-size: 13px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.pages = QStackedWidget(self)
        self.pdf_document = QPdfDocument(self)
        self.pdf_document.statusChanged.connect(self._document_status_changed)
        self.bookmark_model = QPdfBookmarkModel(self)
        self.bookmark_model.setDocument(self.pdf_document)
        self.page_renderer = QPdfPageRenderer(self)
        self.page_renderer.setDocument(self.pdf_document)
        self.page_renderer.setRenderMode(QPdfPageRenderer.RenderMode.MultiThreaded)
        self.page_renderer.pageRendered.connect(self._page_rendered)
        self.scroll_area = QScrollArea(self.pages)
        self.scroll_area.setObjectName("reportPdfScrollArea")
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea#reportPdfScrollArea { background: #f6f8fa; border: 0; }"
            "QScrollArea#reportPdfScrollArea QWidget#reportPdfPages { background: #f6f8fa; }"
        )
        self.page_container = QWidget(self.scroll_area)
        self.page_container.setObjectName("reportPdfPages")
        self.page_layout = QVBoxLayout(self.page_container)
        self.page_layout.setContentsMargins(24, 24, 24, 100)
        self.page_layout.setSpacing(20)
        self.scroll_area.setWidget(self.page_container)
        self.pages.addWidget(self.scroll_area)
        self._page_frames: list[QWidget] = []
        self._page_labels: list[QLabel] = []
        self._page_sizes: list[QSize] = []
        self._page_requested: list[bool] = []
        self._page_render_generation = 0
        self._render_requests: dict[int, tuple[int, int]] = {}
        self._zoom_percent = 60
        self._last_layout_viewport_width = 0
        self._has_document = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(100)
        self._render_timer.timeout.connect(self._refresh_preview_layout)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._schedule_visible_pages)
        self.scroll_area.viewport().installEventFilter(self)

        self.message_page = QWidget(self.pages)
        message_layout = QVBoxLayout(self.message_page)
        message_layout.setContentsMargins(32, 32, 32, 32)
        message_layout.addStretch()
        self.message = QLabel("Selecione Memorial para preparar a visualização.", self.message_page)
        self.message.setObjectName("reportPreviewMessage")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        message_layout.addWidget(self.message)
        message_layout.addStretch()
        self.pages.addWidget(self.message_page)
        self.pages.setCurrentWidget(self.message_page)
        layout.addWidget(self.pages, 1)

        self.export_button = QPushButton("Exportar memorial", self)
        self.export_button.setObjectName("primaryButton")
        self.export_button.setToolTip("Salvar o memorial geral em PDF")
        self.export_button.setAccessibleName("Exportar memorial para PDF")
        self.export_button.clicked.connect(self.export_requested.emit)
        self.export_button.adjustSize()
        self.export_button.setEnabled(False)

    def show_message(self, text: str) -> None:
        self.message.setText(text)
        self.pages.setCurrentWidget(self.message_page)
        self.export_button.setEnabled(False)
        self.document_unavailable.emit()

    def load_pdf(self, path: str | Path) -> str | None:
        self._has_document = False
        self.pdf_document.close()
        error = self.pdf_document.load(str(path))
        if error != QPdfDocument.Error.None_:
            self.show_message(f"Não foi possível abrir a prévia do memorial. ({error.name})")
            return error.name
        self._has_document = True
        self._zoom_percent = 60
        if self.pdf_document.status() == QPdfDocument.Status.Ready:
            self._display_document()
        else:
            self.show_message("Carregando páginas do memorial…")
        return None

    def _document_status_changed(self, status: QPdfDocument.Status) -> None:
        if status == QPdfDocument.Status.Ready and self._has_document:
            self._display_document()
        elif status == QPdfDocument.Status.Error and self._has_document:
            self._has_document = False
            self.show_message("Não foi possível carregar as páginas do memorial.")
            self.document_failed.emit("Não foi possível carregar as páginas do memorial.")

    def _display_document(self) -> None:
        self.pages.setCurrentWidget(self.scroll_area)
        self._build_page_placeholders()
        self._update_visible_pages()
        self.export_button.setEnabled(True)
        self.document_ready.emit()
        QTimer.singleShot(0, self._refresh_preview_layout)

    def set_zoom_percent(self, percent: int) -> None:
        self._zoom_percent = max(30, min(80, int(percent)))
        self._build_page_placeholders()
        self._update_visible_pages()

    def zoom_percent(self) -> int:
        return self._zoom_percent

    def chapter_bookmarks(self) -> list[tuple[str, int]]:
        chapters: list[tuple[str, int]] = []
        root = QModelIndex()
        for row in range(self.bookmark_model.rowCount(root)):
            index = self.bookmark_model.index(row, 0, root)
            title = str(self.bookmark_model.data(index, QPdfBookmarkModel.Role.Title) or "").strip()
            page = self.bookmark_model.data(index, QPdfBookmarkModel.Role.Page)
            if title and page is not None:
                chapters.append((title, int(page)))
        return chapters

    def go_to_page(self, page: int) -> None:
        if not self._page_frames:
            return
        index = max(0, min(len(self._page_frames) - 1, int(page)))
        self.scroll_area.verticalScrollBar().setValue(self._page_frames[index].y())

    def _clear_pages(self) -> None:
        self._page_frames.clear()
        self._page_labels.clear()
        self._page_sizes.clear()
        self._page_requested.clear()
        self._render_requests.clear()
        self._page_render_generation += 1
        while self.page_layout.count():
            item = self.page_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_page_placeholders(self) -> None:
        if not self._has_document or self.pdf_document.status() != QPdfDocument.Status.Ready:
            return
        viewport_width = self.scroll_area.viewport().width()
        available_width = max(5, viewport_width - 48)
        page_width = max(3, round(available_width * self._zoom_percent / 100))
        self._last_layout_viewport_width = viewport_width
        previous_scroll = self.scroll_area.verticalScrollBar().value()
        self._clear_pages()
        for index in range(self.pdf_document.pageCount()):
            point_size = self.pdf_document.pagePointSize(index)
            if point_size.width() <= 0 or point_size.height() <= 0:
                continue
            image_size = QSize(page_width - 2, round((page_width - 2) * point_size.height() / point_size.width()))
            holder = QWidget(self.page_container)
            holder.setFixedSize(image_size.width() + 4, image_size.height() + 5)
            shadow = QFrame(holder)
            shadow.setGeometry(2, 3, image_size.width() + 2, image_size.height() + 2)
            shadow.setStyleSheet("background: #d8dee4; border: 0;")
            page = QFrame(holder)
            page.setGeometry(0, 0, image_size.width() + 2, image_size.height() + 2)
            page.setObjectName("reportPdfPage")
            page.setStyleSheet(
                "QFrame#reportPdfPage { background: #ffffff; border: 1px solid #d0d7de; }"
            )
            image_label = QLabel(page)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setGeometry(1, 1, image_size.width(), image_size.height())
            self.page_layout.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
            self._page_frames.append(holder)
            self._page_labels.append(image_label)
            self._page_sizes.append(image_size)
            self._page_requested.append(False)
        self.page_layout.addStretch(1)
        self.page_layout.activate()
        self.page_container.adjustSize()
        self.scroll_area.verticalScrollBar().setValue(previous_scroll)

    def _refresh_preview_layout(self) -> None:
        if not self._has_document:
            return
        if self.scroll_area.viewport().width() != self._last_layout_viewport_width:
            self._build_page_placeholders()
        self._update_visible_pages()

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.scroll_area.viewport()
            and event.type() == QEvent.Type.Resize
            and self._has_document
        ):
            self._render_timer.start()
        return super().eventFilter(watched, event)

    def _schedule_visible_pages(self, _value: int) -> None:
        if self._has_document:
            self._render_timer.start()

    def _update_visible_pages(self) -> None:
        if not self._has_document or not self._page_labels:
            return
        scrollbar = self.scroll_area.verticalScrollBar()
        viewport_height = self.scroll_area.viewport().height()
        retain_top = max(0, scrollbar.value() - viewport_height * 2)
        retain_bottom = scrollbar.value() + viewport_height * 3
        visible_top = max(0, scrollbar.value() - viewport_height)
        visible_bottom = scrollbar.value() + viewport_height * 2
        generation = self._page_render_generation
        for index, holder in enumerate(self._page_frames):
            top = holder.y()
            bottom = top + holder.height()
            if bottom < retain_top or top > retain_bottom:
                self._page_labels[index].clear()
                self._page_requested[index] = False
                self._render_requests = {
                    request_id: pending
                    for request_id, pending in self._render_requests.items()
                    if pending[0] != index
                }
                continue
            if bottom < visible_top or top > visible_bottom or self._page_requested[index]:
                continue
            self._page_requested[index] = True
            request_id = self.page_renderer.requestPage(index, self._page_sizes[index])
            self._render_requests[request_id] = (index, generation)

    def _page_rendered(self, page_number, image_size, image, _options, request_id) -> None:
        del image_size
        pending = self._render_requests.pop(request_id, None)
        if pending is None:
            return
        index, generation = pending
        if generation != self._page_render_generation or page_number != index:
            return
        if image.isNull() or index >= len(self._page_labels):
            return
        holder = self._page_frames[index]
        scrollbar = self.scroll_area.verticalScrollBar()
        viewport_height = self.scroll_area.viewport().height()
        if (
            holder.y() + holder.height() < max(0, scrollbar.value() - viewport_height * 2)
            or holder.y() > scrollbar.value() + viewport_height * 3
        ):
            self._page_requested[index] = False
            return
        self._page_labels[index].setPixmap(QPixmap.fromImage(image))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.export_button.adjustSize()
        self.export_button.move(
            max(0, self.width() - self.export_button.width() - 24),
            max(0, self.height() - self.export_button.height() - 24),
        )
        self.export_button.raise_()
        if self._has_document:
            self._render_timer.start()


class StructureReportPreviewWorker(QObject):
    """Generate the general report PDF without blocking the application window."""

    finished = Signal(object, str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, model, model_file: str = "") -> None:
        super().__init__()
        self.model = model
        self.model_file = model_file
        self._temporary_directory: TemporaryDirectory | None = None

    @Slot()
    def run(self) -> None:
        self._temporary_directory = TemporaryDirectory(prefix="opensa-general-report-")
        destination = Path(self._temporary_directory.name) / "Memorial-geral.pdf"
        try:
            export = export_structure_report(
                self.model,
                destination,
                ReportOptions(model_file=self.model_file),
                compile_pdf=True,
                progress=self.progress.emit,
            )
            if export.error or export.pdf_path is None:
                raise RuntimeError(export.error or "O PDF do memorial não foi gerado.")
        except Exception as error:  # noqa: BLE001 - send report errors to the UI thread
            self._temporary_directory.cleanup()
            self._temporary_directory = None
            self.failed.emit(str(error))
            return
        self.finished.emit(self._temporary_directory, str(export.pdf_path))

