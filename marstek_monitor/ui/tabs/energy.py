"""Energy tab (spec §7.2): lifetime cards + charged/discharged bars from battery counters."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from ...core.energy import EnergyBar, add_months, bars, bars_in_range, lifetime
from ...i18n import fmt_kwh, tr
from ..charts import BarChart
from ..theme import COLORS
from ..widgets import Card, Segmented, label

MONTH_KEYS = ("month.1", "month.2", "month.3", "month.4", "month.5", "month.6",
              "month.7", "month.8", "month.9", "month.10", "month.11", "month.12")
DAYS_SHOWN = 14
MONTHS_SHOWN = 12


class EnergyTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.offset = 0
        root = QVBoxLayout(self)

        cards = QGridLayout()
        self.c_charged = Card(tr("energy.charged"))
        self.c_discharged = Card(tr("energy.discharged"))
        self.c_cycles = Card(tr("energy.cycles"))
        self.c_eff = Card(tr("energy.efficiency"))
        cards.addWidget(self.c_charged, 0, 0)
        cards.addWidget(self.c_discharged, 0, 1)
        cards.addWidget(self.c_cycles, 1, 0)
        cards.addWidget(self.c_eff, 1, 1)
        root.addLayout(cards)

        controls = QHBoxLayout()
        self.period = Segmented([("day", tr("energy.day")), ("month", tr("energy.month")), ("year", tr("energy.year"))])
        self.period.changed.connect(self._period_changed)
        self.prev = QToolButton()
        self.prev.setText("◀")
        self.next = QToolButton()
        self.next.setText("▶")
        self.range = label("", "muted")
        self.prev.clicked.connect(lambda: self._shift(1))
        self.next.clicked.connect(lambda: self._shift(-1))
        controls.addWidget(self.period, 1)
        controls.addWidget(self.prev)
        controls.addWidget(self.range)
        controls.addWidget(self.next)
        root.addLayout(controls)

        self.chart = BarChart()
        root.addWidget(self.chart, 1)
        legend = (f'<span style="color:{COLORS["charging"]}">■</span> {tr("energy.legend_charged")} &nbsp; '
                  f'<span style="color:{COLORS["discharging"]}">■</span> {tr("energy.legend_discharged")} &nbsp; '
                  f'▨ {tr("energy.legend_combined")}')
        root.addWidget(label(legend, "muted", 0.9, wrap=True))
        self.footer = label("", "muted", 0.85, wrap=True)
        root.addWidget(self.footer)

    def _period_changed(self, _key: str) -> None:
        self.offset = 0
        self.refresh()

    def _shift(self, delta: int) -> None:
        self.offset = max(0, self.offset + delta)
        self.refresh()

    def window(self, period: str, today: date) -> tuple[date, date]:
        if period == "day":
            last = today - timedelta(days=DAYS_SHOWN * self.offset)
            return last - timedelta(days=DAYS_SHOWN - 1), last
        if period == "month":
            last_month = add_months(today, -MONTHS_SHOWN * self.offset)
            first = add_months(last_month, -(MONTHS_SHOWN - 1))
            return first, add_months(last_month, 1) - timedelta(days=1)
        return date(1970, 1, 1), today

    @staticmethod
    def bar_label(bar: EnergyBar, period: str) -> str:
        if period == "day":
            return f"{bar.first.day}–{bar.last.day}" if bar.combined else str(bar.first.day)
        if period == "month":
            first = tr(MONTH_KEYS[bar.first.month - 1])
            return f"{first}–{tr(MONTH_KEYS[bar.last.month - 1])}" if bar.combined else first
        return f"{bar.first.year}–{bar.last.year}" if bar.combined else str(bar.first.year)

    @staticmethod
    def bar_tip(bar: EnergyBar) -> str:
        span = f"{bar.first:%d.%m.%Y}" + (f" – {bar.last:%d.%m.%Y}" if bar.last != bar.first else "")
        tip = tr("energy.tip", label=span, charged=fmt_kwh(bar.charged_wh), discharged=fmt_kwh(bar.discharged_wh))
        return tip + ("\n" + tr("energy.tip_combined") if bar.combined else "")

    def refresh(self) -> None:
        readings = self.monitor.counter_readings()
        state = self.monitor.state
        rated = state.snapshot.rated_wh if state.snapshot is not None else None
        life = lifetime(readings[-1] if readings else None, rated)
        if life is None:
            for card in (self.c_charged, self.c_discharged, self.c_cycles, self.c_eff):
                card.set("—")
        else:
            self.c_charged.set(tr("unit.kwh", v=fmt_kwh(life.charged_wh)))
            self.c_discharged.set(tr("unit.kwh", v=fmt_kwh(life.discharged_wh)))
            cycles = f"{life.cycles:.1f}" if life.cycles is not None else "—"
            sub = tr("energy.cycles_sub", discharged=fmt_kwh(life.discharged_wh), rated=fmt_kwh(rated)) if rated else ""
            self.c_cycles.set(cycles, sub)
            eff = f"{life.efficiency * 100:.0f} %" if life.efficiency is not None else "—"
            self.c_eff.set(eff, tr("energy.efficiency_sub"))
        self.c_eff.setVisible(state.counters_verified)

        period = self.period.value()
        first, last = self.window(period, date.today())
        all_bars = bars(readings, period)
        shown = bars_in_range(all_bars, first, last)
        self.chart.set_bars(shown, [self.bar_label(b, period) for b in shown], [self.bar_tip(b) for b in shown])
        if period == "day":
            self.range.setText(f"{first:%d.%m} – {last:%d.%m.%Y}")
        elif period == "month":
            self.range.setText(f"{first:%m.%Y} – {last:%m.%Y}")
        else:
            self.range.setText(tr("energy.all_time"))
        has_older = period != "year" and bool(all_bars) and all_bars[0].first < first
        self.prev.setEnabled(has_older)
        self.next.setEnabled(period != "year" and self.offset > 0)
        if not readings:
            self.footer.setText(tr("energy.no_data"))
        else:
            self.footer.setText("" if state.counters_verified else tr("energy.unit_pending"))
