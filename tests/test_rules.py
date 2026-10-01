from marstek_monitor import settings as settings_mod
from marstek_monitor.core.rules import RuleContext, RulesEngine, in_quiet_hours, route
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot

MIN = 60


def snap(soc=60, temp=25.0, charge=True, discharge=True):
    return Snapshot(ts=0, responded=True, soc_pct=soc, temp_c=temp, charge_allowed=charge, discharge_allowed=discharge)


def engine(**changes):
    cfg = settings_mod.defaults()
    for path, value in changes.items():
        section, key = path.split("__")
        cfg["notifications"][section][key] = value
    return RulesEngine(cfg)


def run(eng, now, s, online=True, **kw):
    return eng.evaluate(RuleContext(now=now, snapshot=s, online=online, **kw))


def keys(events):
    return [e.title_key for e in events]


def test_soc_below_fires_once_per_crossing():
    eng = engine()
    assert run(eng, 0, snap(soc=45)) == []
    events = run(eng, 60, snap(soc=39))
    assert keys(events) == ["n.soc_below.title"]
    assert events[0].params == {"pct": 40, "soc": 39}
    assert (events[0].priority, events[0].desktop, events[0].telegram) == ("normal", "pending", "off")
    assert run(eng, 120, snap(soc=38)) == []


def test_soc_below_rearms_after_margin():
    eng = engine()
    run(eng, 0, snap(soc=39))
    assert run(eng, 60, snap(soc=41)) == []
    assert run(eng, 120, snap(soc=39)) == []
    assert run(eng, 180, snap(soc=42)) == []
    assert keys(run(eng, 240, snap(soc=39))) == ["n.soc_below.title"]


def test_critical_level_goes_to_telegram_and_repeats():
    eng = engine()
    events = run(eng, 0, snap(soc=19))
    assert [(e.params["pct"], e.priority, e.telegram) for e in events] == [
        (40, "normal", "off"), (20, "critical", "pending")]
    assert run(eng, 29 * MIN, snap(soc=19)) == []
    again = run(eng, 30 * MIN, snap(soc=19))
    assert [e.params["pct"] for e in again] == [20]


def test_disabled_level_does_not_fire():
    eng = engine()
    eng.settings["notifications"]["soc_below"][0]["enabled"] = False
    assert [e.params["pct"] for e in run(eng, 0, snap(soc=30))] == []


def test_soc_reached():
    eng = engine()
    assert run(eng, 0, snap(soc=99)) == []
    assert keys(run(eng, 60, snap(soc=100))) == ["n.soc_reached.title"]
    assert run(eng, 120, snap(soc=99)) == []
    assert run(eng, 180, snap(soc=98)) == []
    assert keys(run(eng, 240, snap(soc=100))) == ["n.soc_reached.title"]


def test_temperature_high_and_low():
    eng = engine()
    high = run(eng, 0, snap(temp=46.4))
    assert keys(high) == ["n.temp_high.title"] and high[0].params == {"temp": 46, "limit": 45}
    assert keys(run(eng, 60, snap(temp=4.0))) == ["n.temp_low.title"]


def test_discharge_blocked_repeats_hourly_and_rearms():
    eng = engine()
    events = run(eng, 0, snap(discharge=False))
    assert keys(events) == ["n.blocked_discharge.title"] and events[0].priority == "critical"
    assert run(eng, 59 * MIN, snap(discharge=False)) == []
    assert keys(run(eng, 60 * MIN, snap(discharge=False))) == ["n.blocked_discharge.title"]
    assert run(eng, 61 * MIN, snap(discharge=True)) == []
    assert keys(run(eng, 62 * MIN, snap(discharge=False))) == ["n.blocked_discharge.title"]


def test_offline_then_back_online():
    eng = engine()
    offline = run(eng, 100, None, online=False, offline_polls=3)
    assert keys(offline) == ["n.offline.title"] and offline[0].params == {"polls": 3}
    assert run(eng, 160, None, online=False) == []
    back = run(eng, 700, snap(), online=True)
    assert keys(back) == ["n.online.title"] and back[0].params == {"duration_s": 600}


def test_stale_snapshot_is_ignored_while_offline():
    eng = engine()
    assert keys(run(eng, 0, snap(soc=10), online=False)) == ["n.offline.title"]


def test_grid_events_only_when_enabled():
    eng = engine()
    assert run(eng, 0, snap(), grid_event="lost") == []
    eng.settings["notifications"]["grid"]["enabled"] = True
    assert keys(run(eng, 0, snap(soc=90), grid_event="lost")) == ["n.grid_lost.title"]
    restored = run(eng, 60, snap(), grid_event="restored", outage_duration_s=3600)
    assert keys(restored) == ["n.grid_restored.title"] and restored[0].params == {"outage_s": 3600}


def test_backup_time_left():
    eng = engine()
    eng.settings["notifications"]["backup_left"]["enabled"] = True
    assert keys(run(eng, 0, snap(soc=50), grid_state="lost", minutes_left=20)) == ["n.backup_left.title"]
    assert run(eng, 60, snap(soc=50), grid_state="lost", minutes_left=25) == []
    assert run(eng, 120, snap(soc=50), grid_state="lost", minutes_left=34) == []
    assert keys(run(eng, 180, snap(soc=50), grid_state="lost", minutes_left=20)) == ["n.backup_left.title"]


def test_finished_sessions():
    eng = engine()
    charge = Session(kind="charge", start_ts=0, start_soc=20, end_ts=3600, end_soc=100, energy_wh=4000)
    discharge = Session(kind="discharge", start_ts=0, start_soc=100, end_ts=1800, end_soc=70, energy_wh=1500)
    events = run(eng, 0, snap(), finished_sessions=[charge, discharge])
    assert keys(events) == ["n.charge_session.title", "n.discharge_session.title"]
    assert events[0].params == {"from_soc": 20, "to_soc": 100, "duration_s": 3600, "energy_wh": 4000}
    assert (events[0].telegram, events[1].telegram) == ("off", "pending")


def test_firmware_change():
    events = run(engine(), 0, snap(), fw_change=(144, 150))
    assert keys(events) == ["n.firmware.title"] and events[0].params == {"old": 144, "new": 150}


def test_monitor_event_is_telegram_only():
    eng = engine()
    e = eng.monitor_event(0, started=True)
    assert (e.title_key, e.desktop, e.telegram) == ("n.monitor_started.title", "off", "pending")
    eng.settings["notifications"]["monitor"]["enabled"] = False
    assert eng.monitor_event(0, started=False) is None


def test_test_event():
    e = engine().test_event(0, desktop=True, telegram=False)
    assert (e.title_key, e.desktop, e.telegram) == ("n.test.title", "pending", "off")


def test_in_quiet_hours():
    qh = {"enabled": True, "from": "23:00", "to": "07:00"}
    assert in_quiet_hours(qh, 23 * 60) and in_quiet_hours(qh, 6 * 60 + 59)
    assert not in_quiet_hours(qh, 7 * 60) and not in_quiet_hours(qh, 12 * 60)
    day = {"enabled": True, "from": "13:00", "to": "15:00"}
    assert in_quiet_hours(day, 14 * 60) and not in_quiet_hours(day, 16 * 60)


def test_route():
    qh = {"enabled": True, "from": "23:00", "to": "07:00", "critical_bypass": True, "silence_telegram": False}
    normal = engine().test_event(0, desktop=True, telegram=True)
    held = route(normal, qh, 23 * 60 + 30)
    assert (held.desktop, held.telegram) == ("held", "pending")
    assert route(normal, qh, 12 * 60) == normal
    assert route(normal, dict(qh, silence_telegram=True), 0).telegram == "held"
    critical = RulesEngine(settings_mod.defaults()).evaluate(
        RuleContext(now=0, snapshot=snap(discharge=False), online=True))[0]
    assert route(critical, qh, 0).desktop == "pending"
    assert route(critical, dict(qh, critical_bypass=False), 0).desktop == "held"
    assert route(normal, dict(qh, enabled=False), 0) == normal
