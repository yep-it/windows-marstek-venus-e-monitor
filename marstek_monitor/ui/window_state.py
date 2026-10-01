"""Remember window size and position in window_state.json (separate from settings.json,
so Save/Cancel in Settings never touches it). Off-screen positions fall back to a centered default."""
from __future__ import annotations

import json
import logging

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from .. import paths

log = logging.getLogger(__name__)
FILE_NAME = "window_state.json"
STATUS_DEFAULT = (820, 720)
SETTINGS_DEFAULT = (1200, 860)
MIN_VISIBLE = (120, 60)  # this much of a restored window must be on some screen


def _load() -> dict:
    try:
        data = json.loads((paths.data_dir() / FILE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(widget: QWidget, key: str) -> None:
    rect = widget.normalGeometry() if widget.isMaximized() else widget.geometry()
    data = _load()
    data[key] = [rect.x(), rect.y(), rect.width(), rect.height()]
    try:
        (paths.data_dir() / FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        log.exception("Could not save the window position")


def _visible(rect: QRect) -> bool:
    for screen in QGuiApplication.screens():
        shown = screen.availableGeometry().intersected(rect)
        if shown.width() >= MIN_VISIBLE[0] and shown.height() >= MIN_VISIBLE[1]:
            return True
    return False


def restore(widget: QWidget, key: str, default_width: int, default_height: int) -> None:
    saved = _load().get(key)
    if isinstance(saved, list) and len(saved) == 4 and all(isinstance(v, int) for v in saved):
        rect = QRect(*saved)
        if rect.width() > 0 and rect.height() > 0 and _visible(rect):
            widget.setGeometry(rect)
            return
    screen = QGuiApplication.primaryScreen().availableGeometry()
    width, height = min(default_width, screen.width()), min(default_height, screen.height())
    widget.resize(width, height)
    widget.move(screen.center() - QPoint(width // 2, height // 2))
