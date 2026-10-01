"""Power direction and time estimates (spec §6.7 'Time estimates')."""
from __future__ import annotations

from .snapshot import Snapshot

IDLE_W = 30.0
CHARGING, DISCHARGING, IDLE = "charging", "discharging", "idle"


def direction(power_w: float | None) -> str | None:
    if power_w is None:
        return None
    if power_w > IDLE_W:
        return CHARGING
    if power_w < -IDLE_W:
        return DISCHARGING
    return IDLE


def minutes_to_full(s: Snapshot) -> float | None:
    if s.power_w is None or s.power_w <= IDLE_W or s.stored_wh is None or not s.rated_wh:
        return None
    remaining = max(0.0, s.rated_wh - s.stored_wh)
    return remaining / s.power_w * 60


def minutes_left(s: Snapshot, reserve_soc_pct: float, efficiency: float = 1.0) -> float | None:
    """Time until the reserve at the current load. The load is measured on the output side, so the
    battery loses load / efficiency (inverter losses and the battery's own consumption)."""
    if s.power_w is None or s.power_w >= -IDLE_W or s.stored_wh is None or not s.rated_wh:
        return None
    reserve_wh = s.rated_wh * reserve_soc_pct / 100
    usable = max(0.0, s.stored_wh - reserve_wh)
    return usable / (-s.power_w / efficiency) * 60


class DrainTracker:
    """Measures the real efficiency while the battery supplies power: the output load compared
    with how fast the stored energy actually falls.

    The device reports the stored energy in steps of about 5 Wh (verified 2026-10-01), so the drop
    is measured between the moments the value changes, over at least MIN_SPAN_S.
    """

    MIN_SPAN_S = 30 * 60
    WINDOW_S = 2 * 3600
    MAX_GAP_S = 10 * 60
    MIN_EFFICIENCY = 0.5

    def __init__(self) -> None:
        self._samples: list[Snapshot] = []

    def reset(self) -> None:
        self._samples = []

    def add(self, s: Snapshot) -> None:
        if direction(s.power_w) != DISCHARGING or s.stored_wh is None:
            self.reset()
            return
        if self._samples and s.ts - self._samples[-1].ts > self.MAX_GAP_S:
            self.reset()
        self._samples.append(s)
        while self._samples and s.ts - self._samples[0].ts > self.WINDOW_S:
            self._samples.pop(0)

    def efficiency(self) -> float | None:
        samples = self._samples
        edges = [i for i in range(1, len(samples)) if samples[i].stored_wh != samples[i - 1].stored_wh]
        if len(edges) < 2:
            return None
        first, last = edges[0], edges[-1]
        span_s = samples[last].ts - samples[first].ts
        drop_wh = samples[first].stored_wh - samples[last].stored_wh
        if span_s < self.MIN_SPAN_S or drop_wh <= 0:
            return None
        drain_w = drop_wh / span_s * 3600
        loads = [-x.power_w for x in samples[first:last]]
        load_w = sum(loads) / len(loads)
        return max(self.MIN_EFFICIENCY, min(1.0, load_w / drain_w))
