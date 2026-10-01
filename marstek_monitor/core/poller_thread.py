"""QThread loop around Poller: one cycle, emit, wait (interruptible)."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from ..api.client import ClientStopped
from .poller import Poller

log = logging.getLogger(__name__)


class PollerThread(QThread):
    result = Signal(object)

    def __init__(self, poller: Poller, interval_s: float, parent=None):
        super().__init__(parent)
        self.poller = poller
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    r = self.poller.cycle()
                except ClientStopped:
                    break
                except Exception:
                    log.exception("Poll cycle failed")
                    r = None
                if r is not None and not self._stop.is_set():
                    self.result.emit(r)
                remaining = max(1.0, self.interval_s - (time.monotonic() - started))
                self._wake.wait(remaining)
                self._wake.clear()
        finally:
            self.poller.close()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.poller.stop()
