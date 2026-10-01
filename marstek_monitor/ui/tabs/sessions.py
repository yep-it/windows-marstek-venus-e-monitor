"""Sessions tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class SessionsTab(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor

    def refresh(self) -> None:
        pass
