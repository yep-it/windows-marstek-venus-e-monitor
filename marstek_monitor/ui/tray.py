"""Tray icon: a battery that fills with the charge level, with a bolt while charging.

(The owner replaced the spec's option B "number tile" after seeing it at 16 px.)
The "M" tile is kept for the window and exe icon.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap, QPolygonF
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


BOLT_COLOR = "#ffd33d"
EDGE_COLOR = QColor(20, 20, 20, 210)
OUTLINE = {"offline": "#9aa0a6", "error": COLORS["red"]}
# Lightning bolt in a unit box (x, y from the top-left corner).
BOLT = ((0.62, 0.0), (0.12, 0.56), (0.46, 0.56), (0.34, 1.0), (0.88, 0.40), (0.54, 0.40), (0.74, 0.0))


def fill_color(level: int) -> str:
    if level > 40:
        return COLORS["charging"]
    if level >= 20:
        return COLORS["orange"]
    return COLORS["red"]


def render_battery(kind: str, level: int | None, size: int) -> QPixmap:
    """Upright battery: outline + terminal, filled from the bottom; bolt when charging."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    stroke = max(1.0, size * 0.06)  # thin outline: most of the icon is the colored fill
    body = QRectF(size * 0.18 + stroke / 2, size * 0.12 + stroke / 2, size * 0.64 - stroke, size * 0.88 - stroke)
    terminal = QRectF(size * 0.36, 0, size * 0.28, size * 0.12)
    outline = QColor(OUTLINE.get(kind, "#ffffff"))
    radius = size * 0.07

    # filling first, so the outline is drawn crisply over its edge
    if level is not None and kind in ("normal", "charging"):
        inner = body.adjusted(stroke * 0.75, stroke * 0.75, -stroke * 0.75, -stroke * 0.75)
        height = max(1.0, inner.height() * max(0, min(100, level)) / 100)
        p.fillRect(QRectF(inner.left(), inner.bottom() - height, inner.width(), height), QColor(fill_color(level)))

    for color, width in ((EDGE_COLOR, stroke + 1), (outline, stroke)):  # dark edge keeps it visible on light taskbars
        pen = QPen(color)
        pen.setWidthF(width)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, radius, radius)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(EDGE_COLOR)
    p.drawRect(terminal.adjusted(-1, -1, 1, 0))
    p.setBrush(outline)
    p.drawRect(terminal)

    if kind == "charging":
        # a narrow bolt in the middle, so the fill level stays visible on both sides
        box = QRectF(body.center().x() - body.width() * 0.25, body.center().y() - body.height() * 0.3,
                     body.width() * 0.5, body.height() * 0.6)
        bolt = QPolygonF([QPointF(box.left() + x * box.width(), box.top() + y * box.height()) for x, y in BOLT])
        edge = QPen(EDGE_COLOR)
        edge.setWidthF(max(0.5, size * 0.018))
        p.setPen(edge)
        p.setBrush(QColor(BOLT_COLOR))
        p.drawPolygon(bolt)
    elif kind in ("offline", "error"):
        pen = QPen(outline)
        pen.setWidthF(max(1.3, size * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        cx, cy, r = body.center().x(), body.center().y(), body.width() * 0.25
        if kind == "offline":
            p.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
            p.drawLine(QPointF(cx + r, cy - r), QPointF(cx - r, cy + r))
        else:
            p.drawLine(QPointF(cx, cy - body.height() * 0.25), QPointF(cx, cy + body.height() * 0.08))
            p.drawPoint(QPointF(cx, cy + body.height() * 0.25))
    p.end()
    return pixmap


def make_battery_icon(kind: str, level: int | None) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_battery(kind, level, size))
    return icon


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
        self.icon = QSystemTrayIcon(make_battery_icon("unknown", None))
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
        self._last_tile: tuple[str, int | None] | None = None
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
            self.icon.setIcon(make_battery_icon(*current))
            self._last_tile = current
        self.icon.setToolTip(tooltip(state, now))
