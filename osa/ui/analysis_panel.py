from .common import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class AnalysisPanel(QFrame):
    """Base visual para casos, combinações e processamento."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyPanel")
        layout = QVBoxLayout(self)
        title = QLabel("Análise"); title.setObjectName("propertyTitle")
        layout.addWidget(title)


class ProcessingPanel(QFrame):
    """Central progress card for the structural-analysis lifecycle."""

    steps = (
        ("model", "Preparando o modelo estrutural"),
        ("loads", "Aplicando ações de carga"),
        ("combinations", "Montando combinações de carga"),
        ("solve", "Resolvendo o sistema estrutural"),
        ("results", "Organizando os resultados"),
    )

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.setObjectName("processingPanel")
        self.setFixedWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(9)
        title = QLabel("Processamento estrutural")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        self.status = QLabel("Aguardando processamento.")
        self.status.setObjectName("processingStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.step_labels: dict[str, QLabel] = {}
        for key, text in self.steps:
            row = QFrame()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            marker = QLabel("○")
            marker.setObjectName("processingMarker")
            label = QLabel(text)
            label.setObjectName("processingStep")
            row_layout.addWidget(marker)
            row_layout.addWidget(label, 1)
            self.step_labels[key] = label
            label.setProperty("marker", marker)
            layout.addWidget(row)
        self.close_button = QPushButton("Fechar")
        self.close_button.setObjectName("secondaryButton")
        self.close_button.clicked.connect(self.hide)
        self.close_button.hide()
        layout.addWidget(self.close_button)
        self.hide()

    def start(self) -> None:
        self.close_button.hide()
        self.status.setText("Iniciando o processamento da estrutura…")
        self.status.setProperty("state", "active")
        self._refresh_style(self.status)
        for key, _text in self.steps:
            self._set_step(key, "pending")
        self.show()
        self.reposition()
        self.raise_()

    def set_stage(self, stage: str) -> None:
        keys = tuple(key for key, _text in self.steps)
        if stage not in keys:
            return
        active_index = keys.index(stage)
        for index, key in enumerate(keys):
            self._set_step(key, "complete" if index < active_index else "active" if index == active_index else "pending")
        self.status.setText(self.step_labels[stage].text() + "…")

    def succeed(self, result_count: int) -> None:
        for key, _text in self.steps:
            self._set_step(key, "complete")
        suffix = "combinação processada" if result_count == 1 else "combinações processadas"
        self.status.setText(f"Processamento da estrutura concluído com sucesso. {result_count} {suffix}.")
        self.status.setProperty("state", "success")
        self._refresh_style(self.status)
        self.close_button.show()
        self.reposition()

    def fail(self, message: str) -> None:
        self.status.setText(f"Não foi possível processar a estrutura: {message}")
        self.status.setProperty("state", "error")
        self._refresh_style(self.status)
        self.close_button.show()
        self.reposition()

    def _set_step(self, key: str, state: str) -> None:
        label = self.step_labels[key]
        marker = label.property("marker")
        marker.setText({"pending": "○", "active": "◉", "complete": "✓"}[state])
        marker.setProperty("state", state)
        label.setProperty("state", state)
        self._refresh_style(marker)
        self._refresh_style(label)

    @staticmethod
    def _refresh_style(widget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def reposition(self) -> None:
        self.adjustSize()
        self.move((self.window.width() - self.width()) // 2, (self.window.height() - self.height()) // 2)
        self.raise_()
