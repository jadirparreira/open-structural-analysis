from .common import QFrame, QLabel, QVBoxLayout


class ActionPanel(QFrame):
    """Base visual para a futura edição das ações estruturais."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyPanel")
        layout = QVBoxLayout(self)
        title = QLabel("Ações"); title.setObjectName("propertyTitle")
        layout.addWidget(title)
