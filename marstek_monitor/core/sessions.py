"""Charge/discharge session detection from successive snapshots (spec §6.5, pure logic)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from .estimates import CHARGING, DISCHARGING, IDLE, direction as power_direction
from .snapshot import Snapshot

FLAG_STARTED_BEFORE_APP = "started_before_app"
FLAG_GAP = "gap"
FLAG_ENDED_WHILE_OFF = "ended_while_off"
QUALITY_ORDER = (FLAG_STARTED_BEFORE_APP, FLAG_ENDED_WHILE_OFF, FLAG_GAP)
AFTER_OUTAGE_WINDOW_S = 1800
INTEGRATION_MAX_DT_S = 600
KIND_OF = {CHARGING: "charge", DISCHARGING: "discharge"}


@dataclass
class Session:
    kind: str
    start_ts: float
    start_soc: int | None
    cause: str = "other"
    flags: set[str] = field(default_factory=set)
    end_ts: float | None = None
    end_soc: int | None = None
    energy_wh: float | None = None
    avg_power_w: float | None = None
    last_ts: float = 0.0
    last_soc: int | None = None
    last_counter: float | None = None
    counter_wh: float | None = None
    integrated_wh: float = 0.0
    id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.end_ts is None

    @property
    def duration_s(self) -> float:
        end = self.end_ts if self.end_ts is not None else self.last_ts
        return max(0.0, end - self.start_ts)

    @property
    def quality(self) -> str:
        for flag in QUALITY_ORDER:
            if flag in self.flags:
                return flag
        return "complete"

    def energy_so_far(self) -> float:
        # The output counter does not count the backup socket; a flat counter means "use power x time".
        return self.counter_wh if self.counter_wh else self.integrated_wh

    def to_dict(self) -> dict:
        data = asdict(self)
        data["flags"] = sorted(self.flags)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        clean["flags"] = set(clean.get("flags") or ())
        return cls(**clean)


class SessionDetector:
    def __init__(self, reserve_soc_pct: float):
        self.reserve = reserve_soc_pct
        self.current: Session | None = None
        self._pending: tuple[str, Snapshot, bool] | None = None
        self._end_streak: list[tuple[str, Snapshot]] = []
        self._soc_hist: list[int] = []
        self._fresh = True      # no sample seen since app start or the last gap
        self._resumed = False   # current session was restored or survived a gap

    def restore(self, session: Session) -> None:
        self.current = session
        self._resumed = True

    def mark_gap(self) -> None:
        self._fresh = True
        self._pending = None
        self._end_streak = []
        self._soc_hist = []
        if self.current is not None:
            self.current.flags.add(FLAG_GAP)
            self._resumed = True

    def update(self, s: Snapshot, outage_active: bool = False,
               last_outage_end_ts: float | None = None) -> list[Session]:
        if not s.responded:
            return []
        d = self._direction(s)
        finished: list[Session] = []
        cur = self.current
        if cur is not None:
            wanted = CHARGING if cur.kind == "charge" else DISCHARGING
            if self._resumed and self._fresh and d != wanted:
                cur.flags.add(FLAG_ENDED_WHILE_OFF)
                finished.append(self._finish(cur, cur.last_ts, cur.last_soc))
            elif d == wanted:
                self._end_streak = []
                self._accumulate(cur, s)
                if cur.kind == "charge" and s.soc_pct is not None and s.soc_pct >= 100:
                    finished.append(self._finish(cur, s.ts, s.soc_pct))
            else:
                self._end_streak.append((d, s))
                if len(self._end_streak) >= 2:
                    first_dir, first = self._end_streak[0]
                    end_soc = first.soc_pct if first.soc_pct is not None else cur.last_soc
                    finished.append(self._finish(cur, first.ts, end_soc))
                    if first_dir in KIND_OF:
                        self._pending = (first_dir, first, False)

        if self.current is None:
            full = d == CHARGING and s.soc_pct is not None and s.soc_pct >= 100
            if d in KIND_OF and not full:
                if self._pending is not None and self._pending[0] == d:
                    _, first, first_fresh = self._pending
                    self.current = self._start(d, first, first_fresh, outage_active, last_outage_end_ts)
                    self._accumulate(self.current, s)
                    self._pending = None
                    self._resumed = False
                else:
                    self._pending = (d, s, self._fresh)
            else:
                self._pending = None
        self._fresh = False
        return finished

    # -- internals ---------------------------------------------------------

    def _direction(self, s: Snapshot) -> str:
        if s.soc_pct is not None:
            self._soc_hist = (self._soc_hist + [s.soc_pct])[-3:]
        d = power_direction(s.power_w)
        if d is not None:
            return d
        if len(self._soc_hist) == 3:
            diff = self._soc_hist[-1] - self._soc_hist[0]
            if diff > 0:
                return CHARGING
            if diff < 0:
                return DISCHARGING
        return IDLE

    def _start(self, d: str, first: Snapshot, fresh: bool, outage_active: bool,
               last_outage_end_ts: float | None) -> Session:
        kind = KIND_OF[d]
        if kind == "discharge" and outage_active:
            cause = "outage"
        elif (kind == "charge" and last_outage_end_ts is not None
              and 0 <= first.ts - last_outage_end_ts <= AFTER_OUTAGE_WINDOW_S):
            cause = "after_outage"
        elif kind == "charge" and first.soc_pct is not None and first.soc_pct <= self.reserve + 2:
            cause = "after_full_discharge"
        else:
            cause = "other"
        session = Session(kind=kind, start_ts=first.ts, start_soc=first.soc_pct, cause=cause,
                          last_ts=first.ts, last_soc=first.soc_pct)
        if fresh:
            session.flags.add(FLAG_STARTED_BEFORE_APP)
        self._accumulate(session, first, integrate=False)
        return session

    @staticmethod
    def _accumulate(session: Session, s: Snapshot, integrate: bool = True) -> None:
        counter = s.counter_in_wh if session.kind == "charge" else s.counter_out_wh
        if counter is not None:
            if session.last_counter is not None and counter >= session.last_counter:
                session.counter_wh = (session.counter_wh or 0.0) + (counter - session.last_counter)
            elif session.counter_wh is None:
                session.counter_wh = 0.0
            session.last_counter = counter  # a lower value means a counter reset: rebase
        if integrate and s.power_w is not None:
            dt = min(max(0.0, s.ts - session.last_ts), INTEGRATION_MAX_DT_S)
            session.integrated_wh += abs(s.power_w) * dt / 3600
        session.last_ts = s.ts
        if s.soc_pct is not None:
            session.last_soc = s.soc_pct

    def _finish(self, session: Session, end_ts: float, end_soc: int | None) -> Session:
        session.end_ts = end_ts
        session.end_soc = end_soc
        session.energy_wh = session.energy_so_far()
        hours = session.duration_s / 3600
        session.avg_power_w = session.energy_wh / hours if hours > 0 else None
        self.current = None
        self._end_streak = []
        self._resumed = False
        return session


def typical_full_charge_s(sessions: list[Session]) -> float | None:
    """Average of the last 5 complete charge sessions, scaled to 20 → 100 %."""
    complete = [
        s for s in sorted(sessions, key=lambda x: x.start_ts)
        if s.kind == "charge" and not s.is_open and s.quality == "complete"
        and s.start_soc is not None and s.end_soc is not None and s.end_soc > s.start_soc
    ][-5:]
    if not complete:
        return None
    seconds_per_pct = [s.duration_s / (s.end_soc - s.start_soc) for s in complete]
    return sum(seconds_per_pct) / len(seconds_per_pct) * 80


def longest_backup(sessions: list[Session]) -> Session | None:
    complete = [s for s in sessions if s.kind == "discharge" and not s.is_open and s.quality == "complete"]
    return max(complete, key=lambda s: s.duration_s, default=None)
