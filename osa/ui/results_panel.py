from .common import QFrame, QLabel, QVBoxLayout


class ResultsPanel(QFrame):
    """Base visual para consulta dos resultados mapeados pelo solver."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyPanel")
        layout = QVBoxLayout(self)
        title = QLabel("Resultados"); title.setObjectName("propertyTitle")
        layout.addWidget(title)
