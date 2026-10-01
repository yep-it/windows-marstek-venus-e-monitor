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


def minutes_left(s: Snapshot, reserve_soc_pct: float) -> float | None:
    if s.power_w is None or s.power_w >= -IDLE_W or s.stored_wh is None or not s.rated_wh:
        return None
    reserve_wh = s.rated_wh * reserve_soc_pct / 100
    usable = max(0.0, s.stored_wh - reserve_wh)
    return usable / -s.power_w * 60
