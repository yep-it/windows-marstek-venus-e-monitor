"""Notification rules (spec §6.7) and quiet-hours routing. Pure logic, no Qt.

Every threshold rule fires once when its condition becomes true, re-arms only after
the value moves back past the threshold by the re-arm margin, and can repeat as a
reminder every `repeat_min` minutes while the condition lasts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .events import Event
from .sessions import Session
from .snapshot import Snapshot

BLOCKED_KEYS = {
    "charge": ("n.blocked_charge.title", "n.blocked_charge.body"),
    "discharge": ("n.blocked_discharge.title", "n.blocked_discharge.body"),
}


class _Latch:
    def __init__(self) -> None:
        self.fired = False
        self.last = 0.0

    def reset(self) -> None:
        self.fired = False

    def step(self, active: bool, rearmed: bool, now: float, repeat_min: int) -> bool:
        if self.fired:
            if rearmed:
                self.fired = False
                return False
            if active and repeat_min > 0 and now - self.last >= repeat_min * 60:
                self.last = now
                return True
            return False
        if active:
            self.fired = True
            self.last = now
            return True
        return False


@dataclass
class RuleContext:
    now: float
    snapshot: Snapshot | None
    online: bool
    grid_event: str | None = None
    grid_state: str = "unknown"
    minutes_left: float | None = None
    outage_duration_s: float | None = None
    finished_sessions: list[Session] = field(default_factory=list)
    fw_change: tuple[int | None, int] | None = None
    offline_polls: int = 3


class RulesEngine:
    def __init__(self, settings: dict):
        self.settings = settings
        self._latches: dict[str, _Latch] = {}
        self._offline_since: float | None = None

    def _latch(self, key: str) -> _Latch:
        return self._latches.setdefault(key, _Latch())

    @staticmethod
    def _event(now: float, rule_id: str, priority: str, title_key: str, body_key: str,
               params: dict, cfg: dict) -> Event:
        return Event(ts=now, kind="notification", rule_id=rule_id, priority=priority,
                     title_key=title_key, body_key=body_key, params=params,
                     desktop="pending" if cfg.get("desktop") else "off",
                     telegram="pending" if cfg.get("telegram") else "off")

    def evaluate(self, ctx: RuleContext) -> list[Event]:
        n = self.settings["notifications"]
        out: list[Event] = []
        s = ctx.snapshot if ctx.online else None
        if s is not None:
            out += self._battery_rules(s, ctx.now, n, self.settings["advanced"])
        out += self._offline_rule(ctx, n["offline"])
        out += self._grid_rules(ctx, n)
        out += self._session_rules(ctx, n)
        fw = n["firmware"]
        if ctx.fw_change and fw["enabled"]:
            out.append(self._event(ctx.now, "firmware", "normal", "n.firmware.title", "n.firmware.body",
                                   {"old": ctx.fw_change[0], "new": ctx.fw_change[1]}, fw))
        return out

    def _battery_rules(self, s: Snapshot, now: float, n: dict, adv: dict) -> list[Event]:
        out: list[Event] = []
        if s.soc_pct is not None:
            for i, level in enumerate(n["soc_below"]):
                latch = self._latch(f"soc_below.{i}")
                if not level["enabled"]:
                    latch.reset()
                    continue
                active = s.soc_pct < level["pct"]
                rearmed = s.soc_pct >= level["pct"] + adv["rearm_pct"]
                if latch.step(active, rearmed, now, level["repeat_min"]):
                    out.append(self._event(now, "soc_below", level["priority"], "n.soc_below.title",
                                           "n.soc_below.body", {"pct": level["pct"], "soc": s.soc_pct}, level))
            reached = n["soc_reached"]
            latch = self._latch("soc_reached")
            if reached["enabled"]:
                if latch.step(s.soc_pct >= reached["pct"], s.soc_pct <= reached["pct"] - adv["rearm_pct"],
                              now, reached["repeat_min"]):
                    out.append(self._event(now, "soc_reached", "normal", "n.soc_reached.title",
                                           "n.soc_reached.body", {"pct": reached["pct"], "soc": s.soc_pct}, reached))
            else:
                latch.reset()

        temp = n["temperature"]
        high, low = self._latch("temp_high"), self._latch("temp_low")
        if not temp["enabled"]:
            high.reset()
            low.reset()
        elif s.temp_c is not None:
            if high.step(s.temp_c > temp["high"], s.temp_c <= temp["high"] - adv["rearm_c"], now, temp["repeat_min"]):
                out.append(self._event(now, "temperature", "critical", "n.temp_high.title", "n.temp.body",
                                       {"temp": round(s.temp_c), "limit": temp["high"]}, temp))
            if low.step(s.temp_c < temp["low"], s.temp_c >= temp["low"] + adv["rearm_c"], now, temp["repeat_min"]):
                out.append(self._event(now, "temperature", "critical", "n.temp_low.title", "n.temp.body",
                                       {"temp": round(s.temp_c), "limit": temp["low"]}, temp))

        blocked = n["blocked"]
        for which, value in (("charge", s.charge_allowed), ("discharge", s.discharge_allowed)):
            latch = self._latch(f"blocked.{which}")
            if not blocked["enabled"]:
                latch.reset()
                continue
            if value is None:
                continue
            if latch.step(value is False, value is True, now, blocked["repeat_min"]):
                title, body = BLOCKED_KEYS[which]
                out.append(self._event(now, "blocked", "critical", title, body, {}, blocked))
        return out

    def _offline_rule(self, ctx: RuleContext, cfg: dict) -> list[Event]:
        latch = self._latch("offline")
        if not ctx.online:
            if self._offline_since is None:
                self._offline_since = ctx.now
            if cfg["enabled"] and latch.step(True, False, ctx.now, cfg["repeat_min"]):
                return [self._event(ctx.now, "offline", "critical", "n.offline.title", "n.offline.body",
                                    {"polls": ctx.offline_polls}, cfg)]
            return []
        was_fired, since = latch.fired, self._offline_since
        latch.reset()
        self._offline_since = None
        if was_fired and cfg["enabled"] and since is not None:
            return [self._event(ctx.now, "offline", "normal", "n.online.title", "n.online.body",
                                {"duration_s": ctx.now - since}, cfg)]
        return []

    def _grid_rules(self, ctx: RuleContext, n: dict) -> list[Event]:
        out: list[Event] = []
        soc = ctx.snapshot.soc_pct if ctx.snapshot is not None and ctx.online else None
        grid = n["grid"]
        if grid["enabled"] and ctx.grid_event == "lost":
            out.append(self._event(ctx.now, "grid", "critical", "n.grid_lost.title", "n.grid_lost.body",
                                   {"soc": soc if soc is not None else "?"}, grid))
        if grid["enabled"] and ctx.grid_event == "restored":
            out.append(self._event(ctx.now, "grid", "critical", "n.grid_restored.title", "n.grid_restored.body",
                                   {"outage_s": ctx.outage_duration_s or 0}, grid))
        backup = n["backup_left"]
        latch = self._latch("backup_left")
        if not backup["enabled"]:
            latch.reset()
            return out
        lost = ctx.grid_state == "lost"
        left = ctx.minutes_left
        active = lost and left is not None and left < backup["minutes"]
        rearmed = (not lost) or (left is not None and left >= backup["minutes"] * 1.1)
        if latch.step(active, rearmed, ctx.now, backup["repeat_min"]):
            out.append(self._event(ctx.now, "backup_left", "critical", "n.backup_left.title", "n.backup_left.body",
                                   {"left_s": left * 60, "soc": soc if soc is not None else "?"}, backup))
        return out

    def _session_rules(self, ctx: RuleContext, n: dict) -> list[Event]:
        out: list[Event] = []
        for session in ctx.finished_sessions:
            is_charge = session.kind == "charge"
            cfg = n["charge_session"] if is_charge else n["discharge_session"]
            if not cfg["enabled"]:
                continue
            title = "n.charge_session.title" if is_charge else "n.discharge_session.title"
            params = {
                "from_soc": session.start_soc if session.start_soc is not None else "?",
                "to_soc": session.end_soc if session.end_soc is not None else "?",
                "duration_s": session.duration_s,
                "energy_wh": session.energy_wh or 0,
            }
            out.append(self._event(ctx.now, "charge_session" if is_charge else "discharge_session",
                                   "normal", title, "n.session.body", params, cfg))
        return out

    def monitor_event(self, now: float, started: bool) -> Event | None:
        cfg = self.settings["notifications"]["monitor"]
        if not cfg["enabled"] or not cfg["telegram"]:
            return None
        title = "n.monitor_started.title" if started else "n.monitor_stopped.title"
        body = "n.monitor_started.body" if started else "n.monitor_stopped.body"
        return Event(ts=now, kind="notification", rule_id="monitor", priority="normal",
                     title_key=title, body_key=body, params={}, desktop="off", telegram="pending")

    def test_event(self, now: float, desktop: bool, telegram: bool) -> Event:
        return Event(ts=now, kind="notification", rule_id="test", priority="normal",
                     title_key="n.test.title", body_key="n.test.body", params={},
                     desktop="pending" if desktop else "off", telegram="pending" if telegram else "off")


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def in_quiet_hours(qh: dict, local_minutes: int) -> bool:
    start, end = _minutes(qh["from"]), _minutes(qh["to"])
    if start == end:
        return False
    if start < end:
        return start <= local_minutes < end
    return local_minutes >= start or local_minutes < end


def route(e: Event, qh: dict, local_minutes: int) -> Event:
    """Apply quiet hours: hold normal desktop notifications (and Telegram if configured)."""
    if not qh.get("enabled") or not in_quiet_hours(qh, local_minutes):
        return e
    if e.priority == "critical" and qh.get("critical_bypass", True):
        return e
    desktop = "held" if e.desktop == "pending" else e.desktop
    telegram = "held" if e.telegram == "pending" and qh.get("silence_telegram") else e.telegram
    return replace(e, desktop=desktop, telegram=telegram)
