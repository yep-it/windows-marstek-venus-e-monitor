import sqlite3

import pytest

from marstek_monitor import settings as settings_mod
from marstek_monitor.api.client import DeviceInfo
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage

DEVICE = DeviceInfo("VenusE 3.0", 144, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")
NOON = 1_790_000_000.0  # any fixed time; tests that care about local time set quiet hours to all day


def poll(ts, soc=60, power=0.0, online=True, cin=None, cout=None, device=DEVICE, **kw):
    s = Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, stored_wh=5120 * soc / 100, rated_wh=5120.0,
                 counter_in_wh=cin, counter_out_wh=cout, charge_allowed=True, discharge_allowed=True, temp_c=25.0)
    return PollResult(ts=ts, snapshot=s, online=online, device=device, **kw)


@pytest.fixture
def storage(tmp_path):
    db = Storage(tmp_path / "history.db")
    yield db
    db.close()


@pytest.fixture
def cfg():
    return settings_mod.defaults()


def test_state_is_updated(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    m.handle(poll(NOON, soc=50, power=1000))
    st = m.state
    assert st.snapshot.soc_pct == 50 and st.online and st.device == DEVICE
    assert st.minutes_to_full == pytest.approx(2560 / 1000 * 60)
    assert st.minutes_left is None and st.last_update_ts == NOON


def test_samples_and_counters_are_stored(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    m.handle(poll(NOON, cin=100, cout=50))
    m.handle(poll(NOON + 60, cin=110, cout=50))
    assert len(m.samples_since(0)) == 2
    assert len(m.counter_readings()) == 1  # throttled to one per 10 minutes


def test_finished_session_is_stored_and_notified(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = []
    for i, (soc, power) in enumerate([(40, 0), (41, 900), (42, 900), (43, 900), (43, 0), (43, 0)]):
        events += m.handle(poll(NOON + i * 60, soc=soc, power=power, cin=100 + i * 20))
    assert [e.rule_id for e in events] == ["charge_session"]
    assert events[0].id is not None
    stored = m.session_list()
    assert len(stored) == 1 and stored[0].end_ts is not None


def test_open_session_is_restored_after_restart(cfg, storage):
    m1 = Monitor(cfg, storage, clock=lambda: NOON)
    for i, power in enumerate([0, 900, 900]):
        m1.handle(poll(NOON + i * 60, soc=40 + i, power=power))
    m2 = Monitor(cfg, storage, clock=lambda: NOON + 600)
    assert m2.state.current_session is not None
    assert m2.state.current_session.id == m1.state.current_session.id


def test_error_is_reported_once_and_cleared(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    err = PollResult(ts=NOON, snapshot=None, online=True, error_key="sys.port_in_use", error_params={"port": 30000})
    first = m.handle(err)
    assert [e.title_key for e in first] == ["sys.port_in_use"] and first[0].kind == "system"
    assert m.handle(err) == []
    m.handle(poll(NOON + 60))
    assert m.state.error_key is None


def test_telegram_channel_off_when_telegram_disabled(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = m.handle(poll(NOON, soc=19))
    assert {e.telegram for e in events} == {"off"}
    cfg2 = settings_mod.defaults()
    cfg2["telegram"]["enabled"] = True
    m2 = Monitor(cfg2, storage, clock=lambda: NOON)
    events2 = m2.handle(poll(NOON, soc=19))
    assert [e.telegram for e in events2] == ["off", "pending"]


def test_quiet_hours_hold_normal_desktop_notifications(cfg, storage):
    cfg["quiet_hours"].update({"enabled": True, "from": "00:00", "to": "23:59"})
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = m.handle(poll(NOON, soc=39))
    assert [e.desktop for e in events] == ["held"]
    assert m.event_list()[0].desktop == "held"


def test_db_error_continues_without_history(cfg, tmp_path):
    class BrokenStorage(Storage):
        def add_sample(self, s):
            raise sqlite3.OperationalError("disk I/O error")

    broken = BrokenStorage(tmp_path / "broken.db")
    m = Monitor(cfg, broken, clock=lambda: NOON)
    events = m.handle(poll(NOON))
    assert "sys.db_error" in [e.title_key for e in events]
    assert m.state.history_ok is False and m.storage is None
    assert m.handle(poll(NOON + 60)) == []
    assert m.samples_since(0) == []
    broken.close()


def test_firmware_change_event(cfg, storage):
    Monitor(cfg, storage, clock=lambda: NOON).handle(poll(NOON))
    newer = DeviceInfo("VenusE 3.0", 150, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")
    events = Monitor(cfg, storage, clock=lambda: NOON).handle(poll(NOON + 60, device=newer))
    assert [e.title_key for e in events] == ["n.firmware.title"]


def test_without_storage_accessors_are_empty(cfg):
    m = Monitor(cfg, None, clock=lambda: NOON)
    m.handle(poll(NOON))
    assert m.samples_since(0) == [] and m.event_list() == [] and m.session_list() == []
    assert m.counter_readings() == []


def test_emit_stores_and_bypasses_quiet_hours(cfg, storage):
    cfg["quiet_hours"].update({"enabled": True, "from": "00:00", "to": "23:59"})
    m = Monitor(cfg, storage, clock=lambda: NOON)
    [e] = m.emit([m.rules.test_event(NOON, desktop=True, telegram=False)], bypass_quiet=True)
    assert e.id is not None and e.desktop == "pending"
    m.record_delivery(e.id, "desktop", "sent")
    assert m.event_list()[0].desktop == "sent"


def test_restored_session_after_long_downtime_is_not_complete(cfg, storage):
    m1 = Monitor(cfg, storage, clock=lambda: NOON)
    for i, power in enumerate([0, -900, -900]):
        m1.handle(poll(NOON + i * 60, soc=90 - i, power=power, cout=100 + i * 20))
    later = NOON + 50_000  # the app was off for ~14 h, the battery is discharging again
    m2 = Monitor(cfg, storage, clock=lambda: later)
    for i, power in enumerate([-900, -900, 0, 0]):
        m2.handle(poll(later + i * 60, soc=60 - i, power=power, cout=500 + i * 20))
    finished = [s for s in m2.session_list() if s.end_ts is not None]
    assert len(finished) == 1 and finished[0].quality != "complete"


def test_counter_unit_change_rescales_history(cfg, storage):
    import copy
    m = Monitor(cfg, storage, clock=lambda: NOON)
    m.handle(poll(NOON, cin=9196, cout=3329))
    changed = copy.deepcopy(cfg)
    changed["advanced"]["counter_unit"] = "0.01kWh"
    m.apply_settings(changed)
    reading = m.counter_readings()[0]
    assert (reading.in_wh, reading.out_wh) == (91960, 33290)
