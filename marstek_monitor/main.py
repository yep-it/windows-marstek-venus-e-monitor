"""Entry point: python -m marstek_monitor (or MarstekMonitor.exe)."""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading

from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .platform.single_instance import SingleInstance

log = logging.getLogger("marstek_monitor")


def _set_app_user_model_id() -> None:
    try:  # groups toasts and the taskbar entry under "MarstekMonitor"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MarstekMonitor")
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marstek_monitor")
    parser.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _set_app_user_model_id()
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(os.environ.get("MARSTEK_MONITOR_INSTANCE", ""))
    if not instance.acquire():
        return 0

    from .app import App  # imported late so a second copy exits fast

    app = App(qapp, instance, exit_after=args.exit_after)

    def excepthook(exc_type, exc, tb) -> None:
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        app.show_unexpected_error()

    def thread_excepthook(hook_args) -> None:
        log.critical("Unhandled exception in thread %s", hook_args.thread.name if hook_args.thread else "?",
                     exc_info=(hook_args.exc_type, hook_args.exc_value, hook_args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return qapp.exec()
