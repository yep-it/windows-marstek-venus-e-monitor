import time

import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.core.events import Event
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage
from marstek_monitor.ui import theme
from marstek_monitor.ui.tabs.energy import EnergyTab
from marstek_monitor.ui.tabs.events import EventsTab
from marstek_monitor.ui.tabs.live import LiveTab
from marstek_monitor.ui.tabs.sessions import SessionsTab

DAY = 86400


@pytest.fixture
def monitor(qapp, tmp_path):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)
    m = Monitor(settings_mod.defaults(), Storage(tmp_path / "h.db"), clock=lambda: time.time() - 3600)
    yield m
    m.close()


def poll(ts, soc=80, power=0.0):
    s = Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, rated_wh=5120.0, stored_wh=5120 * soc / 100)
    return PollResult(ts=ts, snapshot=s, online=True)


def event(ts, rule_id, priority, title, kind="notification"):
    return Event(ts=ts, kind=kind, rule_id=rule_id, priority=priority, title_key=title, body_key="", params={"pct": 40})


def add_counters(storage, now):
    for ts, cin, cout in ((now - 3 * DAY, 1000, 500), (now - 3 * DAY + 600, 1500, 900),
                          (now - 600, 9196, 3329), (now, 9300, 3400)):
        storage.add_counter(ts, cin, cout, force=True)


def test_energy_tab_lifetime_and_bars(qtbot, monitor):
    now = time.time()
    add_counters(monitor.storage, now)
    monitor.handle(poll(now))
    tab = EnergyTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.c_charged.value.text() == "9.3 kWh"
    assert tab.c_cycles.value.text() == "0.7"
    assert tab.c_eff.isHidden()
    assert len(tab.chart._bars) >= 1
    assert "not verified" in tab.footer.text()


def test_energy_tab_shows_efficiency_when_verified(qtbot, monitor):
    monitor.settings["advanced"]["counters_verified"] = True
    monitor.apply_settings(monitor.settings)
    now = time.time()
    add_counters(monitor.storage, now)
    monitor.handle(poll(now))
    tab = EnergyTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert not tab.c_eff.isHidden()
    assert tab.c_eff.value.text() == "37 %"
    assert tab.footer.text() == ""


def test_live_tab_uses_samples_of_this_run(qtbot, monitor):
    now = time.time()
    for i, soc in enumerate((80, 81, 82)):
        monitor.handle(poll(now - 300 + i * 60, soc=soc, power=900))
    tab = LiveTab(monitor, lambda: monitor.settings)
    qtbot.addWidget(tab)
    tab.refresh()
    assert len(tab.chart._samples) == 3


def test_sessions_tab_lists_and_filters(qtbot, monitor):
    now = time.time()
    monitor.storage.save_session(Session(kind="charge", start_ts=now - 7200, start_soc=20, end_ts=now - 3600,
                                         end_soc=100, energy_wh=4000, avg_power_w=4000))
    monitor.storage.save_session(Session(kind="discharge", start_ts=now - 1800, start_soc=100, end_ts=now - 600,
                                         end_soc=80, energy_wh=1000, avg_power_w=3000, cause="outage"))
    tab = SessionsTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.card_count() == 2
    assert tab.typical.value.text() == "≈ 1 h 0 min"
    assert tab.longest.value.text() == "20 min"
    tab.kind.set_value("outage")
    tab.refresh()
    assert tab.card_count() == 1


def test_events_tab_filters_and_search(qtbot, monitor):
    now = time.time()
    monitor.emit([event(now - 30, "offline", "critical", "n.offline.title"),
                  event(now - 20, "soc_below", "normal", "n.soc_below.title"),
                  event(now - 10, "system", "normal", "sys.db_error", kind="system")], bypass_quiet=True)
    tab = EventsTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.row_count() == 3
    tab.filter.set_value("critical")
    tab.refresh()
    assert tab.row_count() == 1
    tab.filter.set_value("all")
    tab.search.setText("below")
    assert tab.row_count() == 1
