"""Now tab (spec §7.2): banners, grid line, big SOC, current session, device details."""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QToolButton, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import (
    banners, current_session_line, details_line, energy_line, footer, grid_line, state_line, time_left_line,
)
from ..theme import COLORS
from ..widgets import Card, clear_layout, label


class NowTab(QWidget):
    def __init__(self, monitor, get_settings: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.banners = QVBoxLayout()
        root.addLayout(self.banners)
        self.grid = label("", None, 1.05)
        root.addWidget(self.grid)

        hero = QHBoxLayout()
        hero.setSpacing(18)
        self.soc = label("--%", None, 4.2, True)
        column = QVBoxLayout()
        column.setSpacing(4)
        self.state = label("", None, 1.6, True)
        self.left = label("", None, 1.35, True)
        self.energy = label("", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        for widget in (self.state, self.left, self.energy, self.bar):
            column.addWidget(widget)
        hero.addWidget(self.soc)
        hero.addLayout(column, 1)
        root.addLayout(hero)

        self.session = Card(tr("now.current_session"))
        root.addWidget(self.session)

        self.details_button = QToolButton()
        self.details_button.setText(tr("now.details"))
        self.details_button.setCheckable(True)
        self.details_button.setAutoRaise(True)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.toggled.connect(self._toggle_details)
        self.details = label("", "muted", 0.95, wrap=True)
        self.details.hide()
        root.addWidget(self.details_button)
        root.addWidget(self.details)
        root.addStretch(1)

        bottom = QHBoxLayout()
        self.footer_left = label("", "muted", 0.85)
        self.footer_right = label("", "muted", 0.85)
        bottom.addWidget(self.footer_left)
        bottom.addStretch(1)
        bottom.addWidget(self.footer_right)
        root.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.render)
        self._timer.start(1000)
        self.render()

    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def refresh(self) -> None:
        self.render()

    def render(self) -> None:
        state = self.monitor.state
        now = time.time()

        clear_layout(self.banners)
        for level, text in banners(state, self.get_settings(), now):
            self.banners.addWidget(label(text, f"banner-{level}", wrap=True))

        grid_text, grid_color = grid_line(state, now)
        self.grid.setText(grid_text)
        self.grid.setStyleSheet(f"color: {COLORS[grid_color]};")

        s = state.snapshot
        soc = s.soc_pct if s is not None and state.online else None
        self.soc.setText(f"{soc}%" if soc is not None else "--%")
        text, color = state_line(state)
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {COLORS[color]};")
        left = time_left_line(state)
        self.left.setText(left)
        self.left.setVisible(bool(left))
        self.energy.setText(energy_line(state))
        self.bar.setValue(soc or 0)
        self.bar.setStyleSheet(
            "QProgressBar { border: none; border-radius: 7px; background: rgba(128, 128, 128, 0.25); }"
            f"QProgressBar::chunk {{ border-radius: 7px; background: {COLORS[color]}; }}"
        )

        session = state.current_session
        if session is not None and session.is_open:
            self.session.set(current_session_line(session, now))
            self.session.set_accent(COLORS["charging" if session.kind == "charge" else "discharging"])
        else:
            self.session.set(tr("now.no_session"))
            self.session.set_accent(None)

        self.details.setText(details_line(state))
        left_text, right_text = footer(state, now)
        self.footer_left.setText(left_text)
        self.footer_right.setText(right_text)
