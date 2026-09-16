from .common import QFrame, QLabel, QVBoxLayout


class AnalysisPanel(QFrame):
    """Base visual para casos, combinações e processamento."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyPanel")
        layout = QVBoxLayout(self)
        title = QLabel("Análise"); title.setObjectName("propertyTitle")
        layout.addWidget(title)
