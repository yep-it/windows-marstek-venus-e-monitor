"""Events tab (spec §7.2): history with per-channel delivery status, filters and search."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import day_label, delivery_text, event_icon, hm, render_event
from ..widgets import Segmented, clear_layout, label

MAX_EVENTS = 500


class EventsTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = Segmented([("all", tr("events.all")), ("critical", tr("events.critical")),
                                 ("notification", tr("events.notifications")), ("system", tr("events.system"))])
        self.filter.changed.connect(lambda _key: self.refresh())
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("events.search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        top.addWidget(self.filter, 1)
        top.addWidget(self.search)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setSpacing(2)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        root.addWidget(label(tr("events.legend"), "muted", 0.85, wrap=True))

    def row_count(self) -> int:
        count = 0
        for i in range(self.list.count()):
            widget = self.list.itemAt(i).widget()
            if widget is not None and widget.property("role") == "event-row":
                count += 1
        return count

    def refresh(self) -> None:
        now = time.time()
        mode = self.filter.value()
        query = self.search.text().strip().lower()
        rows = []
        for e in self.monitor.event_list(MAX_EVENTS):
            if mode == "critical" and e.priority != "critical":
                continue
            if mode in ("notification", "system") and e.kind != mode:
                continue
            title, body = render_event(e)
            if query and query not in f"{title} {body}".lower():
                continue
            rows.append((e, title, body))

        clear_layout(self.list)
        if not rows:
            self.list.addWidget(label(tr("events.empty"), "muted"))
        current_day = None
        for e, title, body in rows:
            day = day_label(e.ts, now)
            if day != current_day:
                self.list.addWidget(label(day.upper(), "card-title", 0.8))
                current_day = day
            self.list.addWidget(self._row(e, title, body))
        self.list.addStretch(1)

    @staticmethod
    def _row(e, title: str, body: str) -> QFrame:
        row = QFrame()
        row.setProperty("role", "event-row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.addWidget(label(hm(e.ts), "muted", 0.9))
        layout.addWidget(label(event_icon(e)))
        badge = f' <span style="color:#e5534b">[{html.escape(tr("badge.critical"))}]</span>' \
            if e.priority == "critical" else ""
        text = QLabel(f"<b>{html.escape(title)}</b>{badge}"
                      + (f"<br><span style='color:gray'>{html.escape(body)}</span>" if body else ""))
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        layout.addWidget(label(delivery_text(e), "muted", 0.9))
        return row
