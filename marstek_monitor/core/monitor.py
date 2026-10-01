"""The per-poll pipeline (spec §5 data flow): storage, sessions, outage, rules, routing.

Runs on the Qt main thread but has no Qt dependency. A database error never stops
monitoring: history is switched off and a system event is emitted once.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable

from ..api.client import DeviceInfo
from .energy import CounterReading
from .estimates import minutes_left, minutes_to_full
from .events import Event
from .outage import OutageDetector
from .poller import PollResult
from .rules import RuleContext, RulesEngine, route
from .sessions import Session, SessionDetector
from .snapshot import COUNTER_UNITS, Snapshot
from .storage import Storage

log = logging.getLogger(__name__)


@dataclass
class LiveState:
    snapshot: Snapshot | None = None
    online: bool = True
    device: DeviceInfo | None = None
    grid_state: str = "unknown"
    grid_since: float | None = None
    current_session: Session | None = None
    minutes_to_full: float | None = None
    minutes_left: float | None = None
    last_update_ts: float | None = None
    error_key: str | None = None
    error_params: dict = field(default_factory=dict)
    history_ok: bool = True
    counters_verified: bool = False


def _local_minutes(ts: float) -> int:
    d = datetime.fromtimestamp(ts)
    return d.hour * 60 + d.minute


class Monitor:
    def __init__(self, settings: dict, storage: Storage | None, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.app_start_ts = clock()
        self.storage = storage
        self.state = LiveState()
        self.outage_marks: list[float] = []
        self._db_failed = False
        self.settings = settings
        self.detector = SessionDetector(settings["advanced"]["reserve_soc_pct"])
        self.outage = OutageDetector(settings["advanced"]["outage_detection"])
        self.rules = RulesEngine(settings)
        self.apply_settings(settings)
        fw = self._db(lambda st: st.get_meta("fw_version"))
        self._fw_known: int | None = int(fw) if fw else None
        open_session = self._db(lambda st: st.open_session())
        if open_session is not None:
            self.detector.restore(open_session)
            self.state.current_session = open_session

    def apply_settings(self, settings: dict) -> None:
        old_unit = self.settings["advanced"]["counter_unit"]
        new_unit = settings["advanced"]["counter_unit"]
        if old_unit != new_unit:
            self._rescale_counters(COUNTER_UNITS.get(new_unit, 1.0) / COUNTER_UNITS.get(old_unit, 1.0))
        self.settings = settings
        self.rules.settings = settings
        self.detector.reserve = settings["advanced"]["reserve_soc_pct"]
        enabled = settings["advanced"]["outage_detection"]
        if enabled != self.outage.enabled:
            self.outage = OutageDetector(enabled)
        self.state.counters_verified = settings["advanced"]["counters_verified"]
        self.state.grid_state = self.outage.state
        self.state.grid_since = self.outage.since

    def _rescale_counters(self, factor: float) -> None:
        """Counters are stored in Wh of the old unit; convert history so no bogus jump appears."""
        self._db(lambda st: st.rescale_counters(factor))
        current = self.detector.current
        if current is not None:
            if current.last_counter is not None:
                current.last_counter *= factor
            if current.counter_wh is not None:
                current.counter_wh *= factor

    def _db(self, fn: Callable[[Storage], Any], default: Any = None) -> Any:
        if self.storage is None:
            return default
        try:
            return fn(self.storage)
        except sqlite3.Error:
            log.exception("History database error; continuing without history")
            self.storage = None
            self.state.history_ok = False
            self._db_failed = True
            return default

    def handle(self, r: PollResult) -> list[Event]:
        now = r.ts
        events: list[Event] = []
        if r.error_key != self.state.error_key:
            self.state.error_key = r.error_key
            self.state.error_params = dict(r.error_params)
            if r.error_key:
                events.append(self._system(now, r.error_key, r.error_params))

        if r.gap is not None:
            self.detector.mark_gap()
            if self.detector.current is not None:
                current = self.detector.current
                self._db(lambda st: st.save_session(current))

        fw_change = None
        if r.device is not None:
            self.state.device = r.device
            ver = r.device.ver
            if ver is not None and ver != self._fw_known:
                if self._fw_known is not None:
                    fw_change = (self._fw_known, ver)
                self._fw_known = ver
                self._db(lambda st: st.set_meta("fw_version", str(ver)))

        s = r.snapshot if r.snapshot is not None and r.snapshot.responded else None
        finished: list[Session] = []
        grid_event = None
        if s is not None:
            self._db(lambda st: st.add_sample(s))
            if s.counter_in_wh is not None and s.counter_out_wh is not None:
                self._db(lambda st: st.add_counter(s.ts, s.counter_in_wh, s.counter_out_wh, force=r.gap is not None))
            current = self.detector.current
            if (r.gap is None and current is not None
                    and s.ts - current.last_ts > 3 * self.settings["general"]["poll_seconds"]):
                self.detector.mark_gap()  # e.g. a session restored after the app was off
            grid_event = self.outage.update(s)
            if grid_event == "lost":
                self.outage_marks.append(s.ts)
            finished = self.detector.update(s, outage_active=self.outage.state == "lost",
                                            last_outage_end_ts=self.outage.last_end_ts)
            for session in finished:
                self._db(lambda st, x=session: st.save_session(x))
            if self.detector.current is not None:
                current = self.detector.current
                self._db(lambda st: st.save_session(current))
            self.state.snapshot = s
            self.state.last_update_ts = s.ts

        self.state.online = r.online
        self.state.current_session = self.detector.current
        self.state.grid_state = self.outage.state
        self.state.grid_since = self.outage.since
        live = self.state.snapshot if r.online else None
        reserve = self.settings["advanced"]["reserve_soc_pct"]
        self.state.minutes_to_full = minutes_to_full(live) if live else None
        self.state.minutes_left = minutes_left(live, reserve) if live else None

        ctx = RuleContext(
            now=now, snapshot=s, online=r.online, grid_event=grid_event, grid_state=self.state.grid_state,
            minutes_left=self.state.minutes_left, outage_duration_s=self.outage.last_duration_s,
            finished_sessions=finished, fw_change=fw_change,
            offline_polls=self.settings["general"]["offline_after_polls"],
        )
        events += self.rules.evaluate(ctx)
        if self._db_failed:
            self._db_failed = False
            events.append(self._system(now, "sys.db_error", {}))
        return self.emit(events)

    def emit(self, events: list[Event], bypass_quiet: bool = False) -> list[Event]:
        """Finalize events: Telegram off if disabled, quiet hours, store (sets e.id)."""
        telegram_on = self.settings["telegram"]["enabled"]
        out: list[Event] = []
        for e in events:
            if not telegram_on and e.telegram == "pending":
                e = replace(e, telegram="off")
            if not bypass_quiet:
                e = route(e, self.settings["quiet_hours"], _local_minutes(e.ts))
            e.id = self._db(lambda st, x=e: st.add_event(x))
            out.append(e)
        return out

    @staticmethod
    def _system(now: float, key: str, params: dict, desktop: bool = False) -> Event:
        return Event(ts=now, kind="system", rule_id="system", priority="normal", title_key=key,
                     body_key="", params=dict(params), desktop="pending" if desktop else "off")

    def system_event(self, key: str, params: dict | None = None, desktop: bool = False) -> Event:
        return self.emit([self._system(self.clock(), key, params or {}, desktop)], bypass_quiet=True)[0]

    def record_delivery(self, event_id: int | None, channel: str, status: str) -> None:
        if event_id is not None:
            self._db(lambda st: st.set_delivery(event_id, channel, status))

    # history accessors (empty when history is unavailable)
    def samples_since(self, ts: float) -> list[Snapshot]:
        return self._db(lambda st: st.samples_since(ts), [])

    def counter_readings(self) -> list[CounterReading]:
        return self._db(lambda st: st.counters(), [])

    def session_list(self, since: float | None = None) -> list[Session]:
        return self._db(lambda st: st.sessions(since), [])

    def event_list(self, limit: int = 500) -> list[Event]:
        return self._db(lambda st: st.events(limit), [])

    def purge(self) -> None:
        days = self.settings["advanced"]["samples_retention_days"]
        self._db(lambda st: st.purge(self.clock(), days))

    def close(self) -> None:
        if self.detector.current is not None:
            current = self.detector.current
            self._db(lambda st: st.save_session(current))
        if self.storage is not None:
            self.storage.close()
            self.storage = None
