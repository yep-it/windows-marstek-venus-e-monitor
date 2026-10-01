"""Live tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class LiveTab(QWidget):
    def __init__(self, monitor, get_settings, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings

    def refresh(self) -> None:
        pass
