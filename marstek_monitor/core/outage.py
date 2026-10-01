"""Grid-outage detection (spec V3, signature verified on the device 2026-10-01).

The grid counts as lost when the battery itself feeds the backup socket: a backup load,
no grid exchange, and the battery below full (a full battery with the same readings is grid
passthrough). Two consecutive samples are needed; restored after two samples without that.
The change is dated from the first of those samples.
An outage with nothing on the backup socket cannot be told apart from idle.
Disabled by default via settings `advanced.outage_detection`.
"""
from __future__ import annotations

from .snapshot import Snapshot, battery_full, supplies_backup

CONFIRM_SAMPLES = 2


class OutageDetector:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.state = "ok" if enabled else "unknown"
        self.since: float | None = None
        self.last_end_ts: float | None = None
        self.last_duration_s: float | None = None
        self._streak = 0
        self._streak_ts: float | None = None

    def update(self, s: Snapshot) -> str | None:
        if not self.enabled or not s.responded or s.ongrid_w is None:
            return None
        looks_lost = supplies_backup(s.ongrid_w, s.offgrid_w, battery_full(s.soc_pct, s.stored_wh, s.rated_wh))
        wanted = "lost" if looks_lost else "ok"
        if wanted == self.state:
            self._streak, self._streak_ts = 0, None
            return None
        if self._streak == 0:
            self._streak_ts = s.ts
        self._streak += 1
        if self._streak < CONFIRM_SAMPLES:
            return None
        changed_at = self._streak_ts
        self._streak, self._streak_ts = 0, None
        if wanted == "lost":
            self.state, self.since = "lost", changed_at
            return "lost"
        self.last_duration_s = changed_at - self.since if self.since is not None else None
        self.state, self.since, self.last_end_ts = "ok", changed_at, changed_at
        return "restored"
