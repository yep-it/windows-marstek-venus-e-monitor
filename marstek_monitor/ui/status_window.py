"""Status window with the Now · Energy · Live · Sessions · Events tabs (spec §7.2)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..i18n import tr
from .tabs.energy import EnergyTab
from .tabs.events import EventsTab
from .tabs.live import LiveTab
from .tabs.now import NowTab
from .tabs.sessions import SessionsTab


class StatusWindow(QWidget):
    TAB_KEYS = ("now", "energy", "live", "sessions", "events")

    def __init__(self, monitor, get_settings: Callable[[], dict], icon: QIcon | None = None):
        super().__init__()
        self.setWindowTitle(tr("app.window_title"))
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(780, 660)
        self.now = NowTab(monitor, get_settings)
        self.energy = EnergyTab(monitor)
        self.live = LiveTab(monitor, get_settings)
        self.sessions = SessionsTab(monitor)
        self.events = EventsTab(monitor)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.now, tr("tab.now"))
        self.tabs.addTab(self.energy, tr("tab.energy"))
        self.tabs.addTab(self.live, tr("tab.live"))
        self.tabs.addTab(self.sessions, tr("tab.sessions"))
        self.tabs.addTab(self.events, tr("tab.events"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())

    def current_tab(self) -> str:
        return self.TAB_KEYS[self.tabs.currentIndex()]

    def show_tab(self, key: str) -> None:
        self.tabs.setCurrentIndex(self.TAB_KEYS.index(key))
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh(self) -> None:
        widget = self.tabs.currentWidget()
        if hasattr(widget, "refresh"):
            widget.refresh()

    def on_update(self) -> None:
        if self.isVisible():
            self.refresh()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
