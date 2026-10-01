"""Human-readable text for the UI, the tray tooltip and Telegram (no widgets)."""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from .core.estimates import CHARGING, DISCHARGING, direction
from .core.events import Event
from .core.monitor import LiveState
from .core.sessions import FLAG_ENDED_WHILE_OFF, FLAG_STARTED_BEFORE_APP, Session
from .core.snapshot import Snapshot
from .i18n import fmt_duration, fmt_energy, fmt_kw, fmt_kwh, fmt_power, tr

DEVICE_NAME = "Marstek Venus E"
TOOLTIP_MAX = 127
ERROR_TILE_KEYS = {"sys.port_in_use", "sys.network_error", "sys.unexpected_error"}
DELIVERY_SYMBOL = {"pending": "…", "sent": "✓", "held": "🌙", "retrying": "⟳", "failed": "✕"}
RULE_ICON = {
    "soc_below": "🪫", "soc_reached": "🔋", "temperature": "🌡", "blocked": "⛔", "offline": "📶",
    "grid": "⚡", "backup_left": "⏳", "charge_session": "🔋", "discharge_session": "🔌",
    "firmware": "⬆", "monitor": "▶", "test": "🔔", "system": "⚙",
}
CAUSE_KEYS = {
    "other": "sess.cause.other", "outage": "sess.cause.outage",
    "after_outage": "sess.cause.after_outage", "after_full_discharge": "sess.cause.after_full_discharge",
}
QUALITY_KEYS = {
    "complete": "sess.q.complete", "started_before_app": "sess.q.started_before_app",
    "gap": "sess.q.gap", "ended_while_off": "sess.q.ended_while_off",
}


def hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def hms(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def day_label(ts: float, now: float) -> str:
    d = datetime.fromtimestamp(ts).date()
    today = datetime.fromtimestamp(now).date()
    if d == today:
        return tr("day.today", date=f"{d:%d.%m}")
    if d == today - timedelta(days=1):
        return tr("day.yesterday", date=f"{d:%d.%m}")
    return f"{d:%d.%m.%Y}"


def _soc(value: int | None, prefix: str = "") -> str:
    return "?" if value is None else f"{prefix}{value}"


def _kind(state: LiveState) -> str:
    if not state.online:
        return "offline"
    if state.snapshot is None:
        return "unknown"
    return direction(state.snapshot.power_w) or "idle"


def tile(state: LiveState) -> tuple[str, int | None]:
    """Tray icon state: (kind, charge level %). kind: error | offline | unknown | charging | outage | normal."""
    if state.error_key in ERROR_TILE_KEYS:
        return "error", None
    if not state.online:
        return "offline", None
    s = state.snapshot
    if s is None or s.soc_pct is None:
        return "unknown", None
    if direction(s.power_w) == CHARGING:
        return "charging", s.soc_pct
    return ("outage" if state.grid_state == "lost" else "normal"), s.soc_pct


def state_line(state: LiveState) -> tuple[str, str]:
    kind = _kind(state)
    s = state.snapshot
    if kind == "offline":
        return tr("state.offline"), "red"
    if kind == "unknown":
        return tr("state.unknown"), "idle"
    if kind == CHARGING:
        return tr("state.charging", power=fmt_power(s.power_w)), "charging"
    if kind == DISCHARGING:
        return tr("state.discharging", power=fmt_power(s.power_w)), "discharging"
    return tr("state.idle"), "text"


def energy_line(state: LiveState) -> str:
    s = state.snapshot
    if s is None:
        return ""
    parts = []
    if s.stored_wh is not None and s.rated_wh:
        parts.append(tr("now.stored", stored=fmt_kwh(s.stored_wh, 2), rated=fmt_kwh(s.rated_wh, 2)))
    if state.minutes_to_full is not None:
        parts.append(tr("est.full", time=fmt_duration(state.minutes_to_full * 60)))
    elif s.soc_pct == 100:
        parts.append(tr("now.full"))
    return " · ".join(parts)


def time_left_line(state: LiveState) -> str:
    if state.minutes_left is None:
        return ""
    return tr("est.left", time=fmt_duration(state.minutes_left * 60))


def grid_line(state: LiveState, now: float) -> tuple[str, str]:
    if state.grid_state == "ok":
        return tr("grid.ok"), "charging"
    if state.grid_state == "lost":
        since = state.grid_since or now
        return tr("grid.lost", since=hm(since), duration=fmt_duration(now - since)), "discharging"
    return tr("grid.unknown"), "idle"


def banners(state: LiveState, settings: dict, now: float) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if state.error_key:
        out.append(("orange", tr(state.error_key, **state.error_params)))
    if not state.history_ok:
        out.append(("orange", tr("sys.db_error")))
    if not state.online:
        out.append(("red", tr("banner.offline")))
    s = state.snapshot if state.online else None
    if s is not None:
        if s.discharge_allowed is False:
            out.append(("red", tr("banner.discharge_blocked")))
        if s.charge_allowed is False:
            out.append(("orange", tr("banner.charge_blocked")))
        limits = settings["notifications"]["temperature"]
        if s.temp_c is not None and (s.temp_c > limits["high"] or s.temp_c < limits["low"]):
            out.append(("red", tr("banner.temperature", temp=round(s.temp_c))))
    if state.grid_state == "lost":
        since = state.grid_since or now
        out.append(("orange", tr("banner.outage", since=hm(since), duration=fmt_duration(now - since))))
    return out


def detail_tiles(state: LiveState, settings: dict) -> list[tuple[str, str, str | None]]:
    """(title, value, color key or None) for the Now tab tiles; temperature first."""
    s = state.snapshot

    def allowed(value: bool | None) -> tuple[str, str | None]:
        if value is None:
            return "—", None
        return (tr("tile.allowed"), None) if value else (tr("tile.blocked"), "red")

    temp, temp_color = "—", None
    if s is not None and s.temp_c is not None:
        temp = tr("details.temp", temp=round(s.temp_c))
        limits = settings["notifications"]["temperature"]
        if s.temp_c > limits["high"] or s.temp_c < limits["low"]:
            temp_color = "red"
    charge, charge_color = allowed(s.charge_allowed if s is not None else None)
    discharge, discharge_color = allowed(s.discharge_allowed if s is not None else None)
    fw = s.fw_version if s is not None and s.fw_version is not None else (state.device.ver if state.device else None)
    backup = "—" if s is None else fmt_power(s.offgrid_w or 0.0)
    return [
        (tr("tile.temperature"), temp, temp_color),
        (tr("tile.backup_load"), backup, None),
        (tr("tile.charging"), charge, charge_color),
        (tr("tile.discharging"), discharge, discharge_color),
        (tr("tile.firmware"), "—" if fw is None else str(fw), None),
    ]


def footer(state: LiveState, now: float) -> tuple[str, str]:
    device = state.device
    ip = (state.snapshot.ip if state.snapshot is not None else None) or (device.ip if device else "")
    left = " · ".join(x for x in ((device.device if device else ""), ip) if x)
    if state.last_update_ts is None:
        return left, tr("footer.waiting")
    ago = int(max(0, now - state.last_update_ts))
    return left, tr("footer.updated", time=hms(state.last_update_ts), ago=ago)


def tooltip(state: LiveState, now: float) -> str:
    parts = [DEVICE_NAME]
    if state.error_key:
        parts.append(tr("tip.error"))
    elif not state.online:
        parts.append(tr("tip.offline"))
    elif state.snapshot is not None:
        if state.snapshot.soc_pct is not None:
            parts.append(f"{state.snapshot.soc_pct}%")
        parts.append(state_line(state)[0])
        if state.grid_state == "ok":
            parts.append(tr("tip.grid_ok"))
        elif state.grid_state == "lost":
            parts.append(tr("tip.on_battery"))
    if state.last_update_ts is not None:
        parts.append(hm(state.last_update_ts))
    text = " · ".join(parts)
    return text if len(text) <= TOOLTIP_MAX else text[: TOOLTIP_MAX - 1] + "…"


def current_session_line(session: Session, now: float) -> str:
    approx = FLAG_STARTED_BEFORE_APP in session.flags
    le = "≤ " if approx else ""
    ge = "≥ " if approx else ""
    key = "sess.current_charge" if session.kind == "charge" else "sess.current_discharge"
    return tr(key, time=le + hm(session.start_ts), from_soc=_soc(session.start_soc, le),
              to_soc=_soc(session.last_soc), duration=ge + fmt_duration(now - session.start_ts),
              energy=ge + fmt_energy(session.energy_so_far()))


def session_title(session: Session) -> str:
    kind = tr("sess.kind.charge") if session.kind == "charge" else tr("sess.kind.discharge")
    return f"{kind} · {tr(CAUSE_KEYS.get(session.cause, 'sess.cause.other'))}"


def session_quality(session: Session) -> tuple[str, bool]:
    quality = session.quality
    return tr(QUALITY_KEYS[quality]), quality != "complete"


def session_summary(session: Session) -> str:
    start_unknown = FLAG_STARTED_BEFORE_APP in session.flags
    partial = start_unknown or FLAG_ENDED_WHILE_OFF in session.flags
    le = "≤ " if start_unknown else ""
    ge = "≥ " if partial else ""
    end_ts = session.end_ts if session.end_ts is not None else session.last_ts
    end_soc = session.end_soc if session.end_soc is not None else session.last_soc
    energy = session.energy_wh if session.energy_wh is not None else session.energy_so_far()
    return tr("sess.summary", start=le + hm(session.start_ts), end=hm(end_ts),
              from_soc=_soc(session.start_soc, le), to_soc=_soc(end_soc),
              duration=ge + fmt_duration(session.duration_s), energy=ge + fmt_energy(energy))


def session_detail(session: Session) -> str:
    parts = []
    if session.avg_power_w is not None:
        key = "sess.avg_charge" if session.kind == "charge" else "sess.avg_load"
        parts.append(tr(key, power=fmt_kw(session.avg_power_w)))
    if session.quality != "complete" and session.quality != "gap":
        parts.append(tr("sess.minimums"))
    if session.is_open:
        parts.append(tr("sess.ongoing"))
    return " · ".join(parts)


def render_event(e: Event) -> tuple[str, str]:
    params = {}
    for key, value in e.params.items():
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if key.endswith("_s") and is_number:
            params[key[:-2]] = fmt_duration(value)
        elif key.endswith("_wh") and is_number:
            params[key[:-3]] = fmt_energy(value)
        else:
            params[key] = value
    title = tr(e.title_key, **params)
    body = tr(e.body_key, **params) if e.body_key else ""
    return title, body


CRITICAL_MARK = "🔴"
NORMAL_MARK = "🔵"


def decorated_title(e: Event, title: str) -> str:
    """Desktop toast title: a red dot for critical, a blue dot for normal notifications."""
    return f"{CRITICAL_MARK if e.priority == 'critical' else NORMAL_MARK} {title}"


def telegram_message(e: Event) -> tuple[str, bool]:
    """(HTML text, silent). Critical: bold CRITICAL and a sound; normal: delivered silently."""
    title, body = render_event(e)
    if e.priority == "critical":
        head = f"{CRITICAL_MARK} <b>CRITICAL</b> · {html.escape(title)}"
    else:
        head = f"{NORMAL_MARK} {html.escape(title)}"
    lines = [head] + ([html.escape(body)] if body else [])
    return "\n".join(lines), e.priority != "critical"


def delivery_text(e: Event) -> str:
    parts = []
    for channel, symbol in (("desktop", "🖥"), ("telegram", "✈")):
        status = getattr(e, channel)
        if status != "off":
            parts.append(f"{symbol} {DELIVERY_SYMBOL.get(status, status)}")
    return " · ".join(parts)


def event_icon(e: Event) -> str:
    return RULE_ICON.get(e.rule_id, "•")


def telegram_status(state: LiveState, now: float) -> str:
    s = state.snapshot
    if s is None:
        lines = [tr("tg.no_data")]
    else:
        lines = [tr("tg.header", soc=_soc(s.soc_pct), stored=fmt_kwh(s.stored_wh, 2), rated=fmt_kwh(s.rated_wh, 2))]
    text, _ = state_line(state)
    extra = ""
    if state.minutes_to_full is not None:
        extra = tr("est.full", time=fmt_duration(state.minutes_to_full * 60))
    elif state.minutes_left is not None:
        extra = time_left_line(state)
    lines.append(f"{text} · {extra}" if extra else text)
    lines.append(grid_line(state, now)[0])
    if state.last_update_ts is not None:
        lines.append(tr("tg.updated", time=hms(state.last_update_ts)))
    return "\n".join(lines)


def live_tip(s: Snapshot) -> str:
    d = direction(s.power_w)
    if d == CHARGING:
        text = tr("state.charging", power=fmt_power(s.power_w))
    elif d == DISCHARGING:
        text = tr("state.discharging", power=fmt_power(s.power_w))
    else:
        text = tr("state.idle")
    return tr("live.tip", time=hm(s.ts), soc=_soc(s.soc_pct), state=text)
