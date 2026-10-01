import time

import pytest

from marstek_monitor import i18n, present, settings as settings_mod
from marstek_monitor.api.client import DeviceInfo
from marstek_monitor.core.events import Event
from marstek_monitor.core.monitor import LiveState
from marstek_monitor.core.sessions import FLAG_STARTED_BEFORE_APP, Session
from marstek_monitor.core.snapshot import Snapshot

NOW = time.time()
DEVICE = DeviceInfo("VenusE 3.0", 144, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def state(**kw):
    snap_kw = {k: kw.pop(k) for k in list(kw) if k in ("soc_pct", "power_w", "charge_allowed", "discharge_allowed", "temp_c")}
    s = Snapshot(ts=NOW, responded=True, stored_wh=4450.0, rated_wh=5120.0, ip="192.168.1.20", rssi_dbm=-49,
                 fw_version=144, **{"soc_pct": 87, "power_w": 1450.0, "charge_allowed": True,
                                    "discharge_allowed": True, "temp_c": 24.0, **snap_kw})
    base = dict(snapshot=s, online=True, device=DEVICE, last_update_ts=NOW - 12.4, minutes_to_full=25.0)
    base.update(kw)
    return LiveState(**base)


def test_tile():
    assert present.tile(state()) == ("charging", 87)
    assert present.tile(state(power_w=-800.0)) == ("normal", 87)
    assert present.tile(state(power_w=0.0)) == ("normal", 87)
    assert present.tile(state(online=False)) == ("offline", None)
    assert present.tile(LiveState()) == ("unknown", None)
    assert present.tile(state(error_key="sys.port_in_use")) == ("error", None)


def test_tooltip():
    tip = present.tooltip(state(grid_state="ok"), NOW)
    assert tip.startswith("Marstek Venus E")
    assert "87%" in tip and "1 450 W" in tip and "Grid OK" in tip
    assert len(tip) <= present.TOOLTIP_MAX
    assert present.tooltip(state(online=False), NOW).startswith("Marstek Venus E · offline")


def test_tooltip_limit_in_ukrainian():
    i18n.set_language("uk")
    for st in (state(grid_state="lost", power_w=-2500.0), state(error_key="sys.firewall_hint"), state(online=False)):
        tip = present.tooltip(st, NOW)
        assert tip.startswith("Marstek Venus E") and len(tip) <= present.TOOLTIP_MAX


def test_state_and_energy_lines():
    assert present.state_line(state()) == ("↓ Charging · 1 450 W", "charging")
    assert present.state_line(state(online=False))[1] == "red"
    assert present.energy_line(state()) == "4.45 of 5.12 kWh · full in ≈ 25 min"
    assert present.state_line(state(power_w=0.0)) == ("Idle", "text")
    assert present.time_left_line(state(minutes_left=190.0)) == "≈ 3 h 10 min left at this load"
    assert present.time_left_line(state()) == ""


def test_grid_line():
    assert present.grid_line(state(grid_state="ok"), NOW) == ("● Grid connected", "charging")
    text, color = present.grid_line(state(grid_state="lost", grid_since=NOW - 3600), NOW)
    assert "1 h 0 min" in text and color == "discharging"
    assert present.grid_line(state(), NOW)[0] == "Grid state unknown"


def test_banners():
    cfg = settings_mod.defaults()
    assert present.banners(state(), cfg, NOW) == []
    levels = [lvl for lvl, _ in present.banners(state(discharge_allowed=False, temp_c=50.0), cfg, NOW)]
    assert levels == ["red", "red"]
    assert present.banners(state(online=False), cfg, NOW)[0][0] == "red"
    outage = present.banners(state(grid_state="lost", grid_since=NOW - 60), cfg, NOW)
    assert outage[0][0] == "orange" and "Grid outage" in outage[0][1]


def test_detail_tiles():
    cfg = settings_mod.defaults()
    assert present.detail_tiles(state(), cfg) == [
        ("Temperature", "24 °C", None), ("Backup load", "0 W", None), ("Charging", "✓ allowed", None),
        ("Discharging", "✓ allowed", None), ("Firmware", "144", None)]
    hot = present.detail_tiles(state(temp_c=50.0, discharge_allowed=False), cfg)
    assert hot[0] == ("Temperature", "50 °C", "red")
    assert hot[3] == ("Discharging", "✕ blocked", "red")
    assert [v for _, v, _ in present.detail_tiles(LiveState(), cfg)] == ["—", "—", "—", "—", "—"]


def test_backup_load_tile_shows_the_backup_socket_watts():
    cfg = settings_mod.defaults()
    import dataclasses
    st = state()
    st.snapshot = dataclasses.replace(st.snapshot, offgrid_w=98.0)
    assert present.detail_tiles(st, cfg)[1] == ("Backup load", "98 W", None)


def test_footer():
    left, right = present.footer(state(), NOW)
    assert left == "VenusE 3.0 · 192.168.1.20" and "(12 s ago)" in right


def test_session_texts():
    s = Session(kind="charge", start_ts=NOW - 3600, start_soc=41, end_ts=NOW, end_soc=87,
                energy_wh=2300, avg_power_w=2300)
    assert present.session_summary(s).endswith("41% → 87% · 1 h 0 min · 2.3 kWh")
    assert present.session_title(s) == "↓ Charging · other"
    assert present.session_quality(s) == ("✓ complete", False)
    assert present.session_detail(s) == "avg 2.30 kW"
    partial = Session(kind="charge", start_ts=NOW - 600, start_soc=55, end_ts=NOW, end_soc=100,
                      energy_wh=500, avg_power_w=3000, flags={FLAG_STARTED_BEFORE_APP})
    text = present.session_summary(partial)
    assert text.startswith("≤ ") and "≤ 55%" in text and "≥ 10 min" in text and "≥ 500 Wh" in text
    assert present.session_quality(partial)[1] is True


def test_current_session_line():
    s = Session(kind="discharge", start_ts=NOW - 600, start_soc=100, last_ts=NOW, last_soc=90, counter_wh=500)
    assert present.current_session_line(s, NOW).endswith("100% → 90% · 10 min · 500 Wh")


def test_small_session_energy_is_shown_in_wh():
    # Real 2026-10-01: ~85 W for 3 min on backup showed "0.0 kWh".
    s = Session(kind="discharge", start_ts=NOW - 180, start_soc=99, last_ts=NOW, last_soc=99, integrated_wh=4.3)
    assert present.current_session_line(s, NOW).endswith("99% → 99% · 3 min · 4 Wh")


def test_render_event_formats_durations_and_energy():
    e = Event(ts=NOW, kind="notification", rule_id="charge_session", priority="normal",
              title_key="n.charge_session.title", body_key="n.session.body",
              params={"from_soc": 20, "to_soc": 100, "duration_s": 9600, "energy_wh": 4100})
    assert present.render_event(e) == ("Charge session finished", "20% → 100% in 2 h 40 min · 4.1 kWh")
    system = Event(ts=NOW, kind="system", rule_id="system", priority="normal",
                   title_key="sys.port_in_use", body_key="", params={"port": 30000})
    assert present.render_event(system) == ("UDP port 30000 is used by another program", "")


def test_delivery_text_and_icon():
    e = Event(ts=NOW, kind="notification", rule_id="offline", priority="critical", title_key="n.offline.title",
              body_key="n.offline.body", params={}, desktop="held", telegram="retrying")
    assert present.delivery_text(e) == "🖥 🌙 · ✈ ⟳"
    assert present.event_icon(e) == "📶"


def test_telegram_status():
    text = present.telegram_status(state(grid_state="ok"), NOW)
    lines = text.splitlines()
    assert lines[0] == "🔋 Marstek Venus E — 87% (4.45 of 5.12 kWh)"
    assert lines[1] == "↓ Charging · 1 450 W · full in ≈ 25 min"
    assert lines[2] == "● Grid connected"
    assert lines[3].startswith("Updated ")
    assert present.telegram_status(LiveState(), NOW).startswith("🔋 Marstek Venus E — no data yet")


def test_day_label():
    assert present.day_label(NOW, NOW).startswith("Today")
    assert present.day_label(NOW - 86400, NOW).startswith("Yesterday")


def _event(priority, title_key="n.offline.title", body_key="n.offline.body", params=None):
    return Event(ts=NOW, kind="notification", rule_id="offline", priority=priority, title_key=title_key,
                 body_key=body_key, params=params if params is not None else {"polls": 3})


def test_desktop_titles_show_priority():
    assert present.decorated_title(_event("critical"), "Battery not responding") == "🔴 Battery not responding"
    assert present.decorated_title(_event("normal"), "Battery reached 100%") == "🔵 Battery reached 100%"


def test_telegram_message_marks_critical_and_silences_normal():
    text, silent = present.telegram_message(_event("critical"))
    assert text.splitlines() == ["🔴 <b>CRITICAL</b> · Battery not responding", "No reply for 3 polls in a row."]
    assert silent is False
    text, silent = present.telegram_message(_event("normal", "n.soc_reached.title", "n.soc_reached.body",
                                                   {"pct": 100, "soc": 100}))
    assert text.splitlines() == ["🔵 Battery reached 100%", "Charge level is 100%."]
    assert silent is True


def test_telegram_message_escapes_html():
    e = Event(ts=NOW, kind="system", rule_id="system", priority="normal", title_key="sys.network_error",
              body_key="", params={"error": "<boom> & co"})
    assert present.telegram_message(e)[0] == "🔵 Network error: &lt;boom&gt; &amp; co"
