"""EXPERIMENTAL grid-outage heuristic (spec V3: the real signature is not verified yet).

Heuristic: the grid counts as lost when the battery feeds the off-grid (backup) output
(offgrid > 30 W) while the grid side carries ~no power (|ongrid| <= 5 W) for two
consecutive samples; it counts as restored after two samples with |ongrid| > 5 W.
Disabled by default via settings `advanced.outage_detection`.
"""
from __future__ import annotations

from .snapshot import Snapshot

OFFGRID_MIN_W = 30.0
ONGRID_MAX_W = 5.0
CONFIRM_SAMPLES = 2


class OutageDetector:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.state = "ok" if enabled else "unknown"
        self.since: float | None = None
        self.last_end_ts: float | None = None
        self.last_duration_s: float | None = None
        self._streak = 0

    def update(self, s: Snapshot) -> str | None:
        if not self.enabled or not s.responded or s.ongrid_w is None:
            return None
        looks_lost = (s.offgrid_w or 0.0) > OFFGRID_MIN_W and abs(s.ongrid_w) <= ONGRID_MAX_W
        wanted = "lost" if looks_lost else "ok"
        if wanted == self.state:
            self._streak = 0
            return None
        self._streak += 1
        if self._streak < CONFIRM_SAMPLES:
            return None
        self._streak = 0
        if wanted == "lost":
            self.state, self.since = "lost", s.ts
            return "lost"
        self.last_duration_s = s.ts - self.since if self.since is not None else None
        self.state, self.since, self.last_end_ts = "ok", s.ts, s.ts
        return "restored"
