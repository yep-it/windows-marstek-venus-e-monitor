"""Hand-painted charts that inherit the app font and palette (spec §7.2 Energy / Live)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from ..core.energy import EnergyBar
from ..core.snapshot import Snapshot
from ..i18n import tr
from .theme import COLORS


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * magnitude >= value:
            return step * magnitude
    return 10 * magnitude


def split_segments(samples: list[Snapshot], gap_s: float) -> list[list[Snapshot]]:
    segments: list[list[Snapshot]] = []
    current: list[Snapshot] = []
    for s in samples:
        if current and s.ts - current[-1].ts > gap_s:
            segments.append(current)
            current = []
        current.append(s)
    if current:
        segments.append(current)
    return segments


def _colors(widget: QWidget) -> tuple[QColor, QColor, QColor]:
    text = widget.palette().color(QPalette.ColorRole.WindowText)
    muted = QColor(text)
    muted.setAlpha(160)
    grid = QColor(text)
    grid.setAlpha(35)
    return text, muted, grid


class BarChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._bars: list[EnergyBar] = []
        self._labels: list[str] = []
        self._tips: list[str] = []

    def set_bars(self, bars: list[EnergyBar], labels: list[str], tips: list[str]) -> None:
        self._bars, self._labels, self._tips = list(bars), list(labels), list(tips)
        self.update()

    def plot_rect(self) -> QRectF:
        fm = self.fontMetrics()
        left = fm.horizontalAdvance("00.0") + 10
        bottom = fm.height() + 8
        return QRectF(left, 10, max(1.0, self.width() - left - 8), max(1.0, self.height() - bottom - 10))

    def slot_at(self, x: float) -> int | None:
        r = self.plot_rect()
        n = len(self._bars)
        if n == 0 or not (r.left() <= x <= r.right()):
            return None
        return min(n - 1, int((x - r.left()) / (r.width() / n)))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _, muted, grid = _colors(self)
        fm = self.fontMetrics()
        r = self.plot_rect()
        top = nice_max(max((max(b.charged_wh, b.discharged_wh) for b in self._bars), default=0.0) / 1000)
        for i in range(5):
            value = top * i / 4
            y = r.bottom() - value / top * r.height()
            p.setPen(grid)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - fm.height() / 2, r.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:g}")
        n = len(self._bars)
        if n:
            slot = r.width() / n
            width = slot * 0.34
            hatch = QBrush(QColor(255, 255, 255, 120), Qt.BrushStyle.BDiagPattern)
            for i, bar in enumerate(self._bars):
                x0 = r.left() + i * slot + slot * 0.14
                for j, (wh, color) in enumerate(((bar.charged_wh, COLORS["charging"]),
                                                 (bar.discharged_wh, COLORS["discharging"]))):
                    height = wh / 1000 / top * r.height()
                    rect = QRectF(x0 + j * (width + 2), r.bottom() - height, width, height)
                    p.fillRect(rect, QColor(color))
                    if bar.combined:
                        p.fillRect(rect, hatch)
                p.setPen(muted)
                text = self._labels[i] if i < len(self._labels) else ""
                p.drawText(QRectF(r.left() + i * slot, r.bottom() + 4, slot, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        i = self.slot_at(event.position().x())
        if i is not None and i < len(self._tips):
            QToolTip.showText(event.globalPosition().toPoint(), self._tips[i], self)
        else:
            QToolTip.hideText()


class LiveChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self._samples: list[Snapshot] = []
        self._t0, self._t1 = 0.0, 1.0
        self._marks: list[float] = []
        self._gap_s = 180.0
        self._tip_fn: Callable[[Snapshot], str] | None = None

    def set_data(self, samples: list[Snapshot], t0: float, t1: float, outage_marks: list[float],
                 gap_s: float, tip_fn: Callable[[Snapshot], str]) -> None:
        self._t0, self._t1 = t0, max(t1, t0 + 1)
        self._samples = [s for s in samples if self._t0 <= s.ts <= self._t1]
        self._marks = [m for m in outage_marks if self._t0 <= m <= self._t1]
        self._gap_s = gap_s
        self._tip_fn = tip_fn
        self.update()

    def plot_rect(self) -> QRectF:
        fm = self.fontMetrics()
        left = fm.horizontalAdvance("100%") + 10
        right = fm.horizontalAdvance("-2.5 kW") + 10
        bottom = fm.height() + 8
        return QRectF(left, 8, max(1.0, self.width() - left - right), max(1.0, self.height() - bottom - 8))

    def _x(self, r: QRectF, ts: float) -> float:
        return r.left() + (ts - self._t0) / (self._t1 - self._t0) * r.width()

    def _pmax(self) -> float:
        peak = max((abs(s.power_w) for s in self._samples if s.power_w is not None), default=0.0)
        return nice_max(max(2000.0, peak) / 1000) * 1000

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text, muted, grid = _colors(self)
        fm = self.fontMetrics()
        r = self.plot_rect()
        mid = r.center().y()
        pmax = self._pmax()

        def y_power(w: float) -> float:
            return mid - w / pmax * (r.height() / 2)

        def y_soc(soc: float) -> float:
            return r.bottom() - soc / 100 * r.height()

        for w in (-pmax, -pmax / 2, 0.0, pmax / 2, pmax):
            y = y_power(w)
            p.setPen(muted if w == 0 else grid)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(r.right() + 4, y - fm.height() / 2, 200, fm.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "0" if w == 0 else f"{w / 1000:+g} kW")
        p.setPen(QColor(COLORS["blue"]))
        for soc in (0, 50, 100):
            y = y_soc(soc)
            p.drawText(QRectF(0, y - fm.height() / 2, r.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{soc}%")

        segments = split_segments(self._samples, self._gap_s)
        shade = QColor(text)
        shade.setAlpha(22)
        for a, b in zip(segments, segments[1:]):
            x0, x1 = self._x(r, a[-1].ts), self._x(r, b[0].ts)
            p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), shade)
            p.setPen(muted)
            p.drawText(QRectF(x0, r.top(), x1 - x0, fm.height() + 4), Qt.AlignmentFlag.AlignCenter,
                       tr("live.no_data"))
        for segment in segments:
            for sign, color in ((1, COLORS["charging"]), (-1, COLORS["discharging"])):
                points = [(self._x(r, s.ts), y_power(sign * max(0.0, sign * (s.power_w or 0.0))))
                          for s in segment]
                if len(points) < 2:
                    continue
                path = QPainterPath(QPointF(points[0][0], mid))
                for x, y in points:
                    path.lineTo(x, y)
                path.lineTo(points[-1][0], mid)
                path.closeSubpath()
                fill = QColor(color)
                fill.setAlpha(90)
                p.fillPath(path, fill)
            line = QPolygonF([QPointF(self._x(r, s.ts), y_soc(s.soc_pct)) for s in segment if s.soc_pct is not None])
            if line.size() >= 2:
                pen = QPen(QColor(COLORS["blue"]))
                pen.setWidthF(2.2)
                p.setPen(pen)
                p.drawPolyline(line)
        dash = QPen(QColor(COLORS["discharging"]))
        dash.setStyle(Qt.PenStyle.DashLine)
        p.setPen(dash)
        for mark in self._marks:
            x = self._x(r, mark)
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setPen(muted)
        for i in range(4):
            ts = self._t0 + (self._t1 - self._t0) * i / 3
            x = self._x(r, ts)
            p.drawText(QRectF(x - 40, r.bottom() + 4, 80, fm.height()), Qt.AlignmentFlag.AlignCenter,
                       datetime.fromtimestamp(ts).strftime("%H:%M"))
        p.end()

    def mouseMoveEvent(self, event) -> None:
        if not self._samples or self._tip_fn is None:
            return
        r = self.plot_rect()
        ts = self._t0 + (event.position().x() - r.left()) / r.width() * (self._t1 - self._t0)
        nearest = min(self._samples, key=lambda s: abs(s.ts - ts))
        QToolTip.showText(event.globalPosition().toPoint(), self._tip_fn(nearest), self)
