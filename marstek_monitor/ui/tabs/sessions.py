"""Sessions tab (spec §7.2): summary cards, filters, cards grouped by day."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...core.sessions import Session, longest_backup, typical_full_charge_s
from ...i18n import fmt_duration, tr
from ...present import day_label, session_detail, session_quality, session_summary, session_title
from ..theme import COLORS
from ..widgets import Card, Segmented, clear_layout, label

MAX_CARDS = 200


class SessionsTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        root = QVBoxLayout(self)

        summary = QGridLayout()
        self.typical = Card(tr("sessions.typical"))
        self.longest = Card(tr("sessions.longest"))
        summary.addWidget(self.typical, 0, 0)
        summary.addWidget(self.longest, 0, 1)
        root.addLayout(summary)

        filters = QHBoxLayout()
        self.kind = Segmented([("all", tr("sessions.all")), ("charge", tr("sessions.charging")),
                               ("discharge", tr("sessions.discharging")), ("outage", tr("sessions.outages"))])
        self.kind.changed.connect(lambda _key: self.refresh())
        self.period = QComboBox()
        for text, days in ((tr("sessions.p7"), 7), (tr("sessions.p30"), 30), (tr("sessions.p90"), 90),
                           (tr("sessions.pall"), 0)):
            self.period.addItem(text, days)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(lambda _index: self.refresh())
        filters.addWidget(self.kind, 1)
        filters.addWidget(self.period)
        root.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setSpacing(8)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.count = label("", "muted", 0.85)
        root.addWidget(self.count)

    def card_count(self) -> int:
        count = 0
        for i in range(self.list.count()):
            widget = self.list.itemAt(i).widget()
            if widget is not None and widget.property("role") == "card":
                count += 1
        return count

    def refresh(self) -> None:
        now = time.time()
        sessions = self.monitor.session_list()
        typical = typical_full_charge_s(sessions)
        self.typical.set("≈ " + fmt_duration(typical) if typical else "—", tr("sessions.typical_sub"))
        longest = longest_backup(sessions)
        if longest is None:
            self.longest.set("—")
        else:
            self.longest.set(fmt_duration(longest.duration_s), tr(
                "sessions.longest_sub", from_soc=longest.start_soc, to_soc=longest.end_soc,
                date=f"{datetime.fromtimestamp(longest.start_ts):%d.%m}"))

        days = self.period.currentData()
        since = now - days * 86400 if days else None
        kind = self.kind.value()
        items = [s for s in sessions if since is None or s.start_ts >= since]
        if kind in ("charge", "discharge"):
            items = [s for s in items if s.kind == kind]
        elif kind == "outage":
            items = [s for s in items if s.cause == "outage"]
        items = sorted(items, key=lambda s: s.start_ts, reverse=True)[:MAX_CARDS]

        clear_layout(self.list)
        if not items:
            self.list.addWidget(label(tr("sessions.empty"), "muted"))
        current_day = None
        for session in items:
            day = day_label(session.start_ts, now)
            if day != current_day:
                self.list.addWidget(label(day.upper(), "card-title", 0.8))
                current_day = day
            self.list.addWidget(self._card(session))
        self.list.addStretch(1)
        self.count.setText(tr("sessions.count", n=len(items)))

    @staticmethod
    def _card(session: Session) -> QFrame:
        card = QFrame()
        card.setProperty("role", "card")
        color = COLORS["charging"] if session.kind == "charge" else COLORS["discharging"]
        card.setStyleSheet(f'QFrame[role="card"] {{ border-left: 4px solid {color}; }}')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        head = QHBoxLayout()
        head.addWidget(label(session_title(session).upper(), "card-title", 0.8))
        quality, warn = session_quality(session)
        head.addWidget(label(quality, "badge-warn" if warn else "muted", 0.8))
        head.addStretch(1)
        layout.addLayout(head)
        layout.addWidget(label(session_summary(session), None, 1.1, True, wrap=True))
        detail = session_detail(session)
        if detail:
            layout.addWidget(label(detail, "muted", 0.85, wrap=True))
        return card
