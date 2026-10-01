"""Live tab (spec §7.2): SOC and power of the current app run."""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import hm, live_tip
from ..charts import LiveChart
from ..widgets import Segmented, label

RANGES = {"1h": 3600, "3h": 3 * 3600, "6h": 6 * 3600, "all": None}


class LiveTab(QWidget):
    def __init__(self, monitor, get_settings: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.range = Segmented([("1h", tr("live.1h")), ("3h", tr("live.3h")), ("6h", tr("live.6h")),
                                ("all", tr("live.all"))])
        self.range.set_value("6h")
        self.range.changed.connect(lambda _key: self.refresh())
        self.since = label("", "muted")
        top.addWidget(self.range, 1)
        top.addWidget(self.since)
        root.addLayout(top)
        self.chart = LiveChart()
        root.addWidget(self.chart, 1)
        root.addWidget(label(tr("live.legend"), "muted", 0.9, wrap=True))

    def refresh(self) -> None:
        now = time.time()
        start = self.monitor.app_start_ts
        window = RANGES[self.range.value()]
        t0 = start if window is None else max(start, now - window)
        samples = [s for s in self.monitor.samples_since(t0) if s.responded]
        gap_s = 3 * self.get_settings()["general"]["poll_seconds"]
        self.chart.set_data(samples, t0, now, self.monitor.outage_marks, gap_s, live_tip)
        self.since.setText(tr("live.running_since", time=hm(start)))
