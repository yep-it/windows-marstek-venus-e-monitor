"""Tray icon: a rounded tile with the SOC number, colored by state (spec §7.1, option B)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.monitor import LiveState
from ..i18n import tr
from ..present import DEVICE_NAME, tile, tooltip
from .theme import COLORS

ICON_SIZES = (16, 20, 24, 32, 48, 64)


def render_tile(label: str | None, color: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    radius = size * 0.19
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    if label is None:
        pen = QPen(QColor("white"))
        pen.setWidthF(max(1.5, size * 0.12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = size * 0.3
        p.drawLine(QPointF(m, m), QPointF(size - m, size - m))
        p.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    else:
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(max(6, int(size * (0.62 if len(label) <= 2 else 0.46))))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return pixmap


def make_icon(label: str | None, color: str) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_tile(label, color, size))
    return icon


class Tray(QObject):
    open_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(make_icon("--", COLORS["idle"]))
        self.menu = QMenu()
        self._open = QAction(self.menu)
        self._settings = QAction(self.menu)
        self._exit = QAction(self.menu)
        self._open.triggered.connect(lambda: self.open_requested.emit())
        self._settings.triggered.connect(lambda: self.settings_requested.emit())
        self._exit.triggered.connect(lambda: self.exit_requested.emit())
        self.menu.addAction(self._open)
        self.menu.addAction(self._settings)
        self.menu.addSeparator()
        self.menu.addAction(self._exit)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.setToolTip(DEVICE_NAME)
        self._last_tile: tuple[str | None, str] | None = None
        self.retranslate()

    def retranslate(self) -> None:
        self._open.setText(tr("tray.open"))
        self._settings.setText(tr("tray.settings"))
        self._exit.setText(tr("tray.exit"))

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()

    def update_state(self, state: LiveState, now: float) -> None:
        current = tile(state)
        if current != self._last_tile:
            label, color_key = current
            self.icon.setIcon(make_icon(label, COLORS[color_key]))
            self._last_tile = current
        self.icon.setToolTip(tooltip(state, now))
