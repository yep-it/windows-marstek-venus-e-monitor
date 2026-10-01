"""Only one running copy (spec §8): a named mutex, plus a local socket that wakes the running copy."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, suffix: str = "", parent=None):
        super().__init__(parent)
        tag = f".{suffix}" if suffix else ""
        self.mutex_name = f"Local\\MarstekMonitor{tag}"
        self.server_name = f"MarstekMonitor{tag}"
        self._mutex = None
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, self.mutex_name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            if handle:
                _kernel32.CloseHandle(handle)
            self._notify_running()
            return False
        self._mutex = handle
        QLocalServer.removeServer(self.server_name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self.server_name)
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            self._server.nextPendingConnection().disconnectFromServer()
        self.activated.emit()

    def _notify_running(self) -> None:
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if sock.waitForConnected(1000):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._mutex:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None
