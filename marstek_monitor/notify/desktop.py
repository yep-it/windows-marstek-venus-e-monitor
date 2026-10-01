"""Desktop notifications as Windows toasts through the tray icon (spec §6.8)."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import QSystemTrayIcon

log = logging.getLogger(__name__)
TOAST_MS = 10_000


class DesktopNotifier:
    def __init__(self, icon: QSystemTrayIcon, open_tab: Callable[[str], None]):
        self.icon = icon
        self._tab = "now"
        icon.messageClicked.connect(lambda: open_tab(self._tab))

    def show(self, title: str, body: str, critical: bool, tab: str) -> bool:
        self._tab = tab
        if not QSystemTrayIcon.isSystemTrayAvailable() or not self.icon.isVisible():
            log.info("Desktop notification not shown (no system tray): %s", title)
            return False
        kind = QSystemTrayIcon.MessageIcon.Critical if critical else QSystemTrayIcon.MessageIcon.Information
        self.icon.showMessage(title, body, kind, TOAST_MS)
        return True
