import time

import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.ui import theme
from marstek_monitor.ui.status_window import StatusWindow


def poll(soc=87, power=1450.0, **kw):
    now = time.time()
    s = Snapshot(ts=now, responded=True, soc_pct=soc, power_w=power, stored_wh=5120 * soc / 100,
                 rated_wh=5120.0, charge_allowed=kw.pop("charge_allowed", True),
                 discharge_allowed=kw.pop("discharge_allowed", True), temp_c=24.0, ip="192.168.1.20")
    return PollResult(ts=now, snapshot=s, online=kw.pop("online", True))


@pytest.fixture
def monitor(qapp):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)
    return Monitor(settings_mod.defaults(), None)


def window(qtbot, monitor):
    win = StatusWindow(monitor, lambda: monitor.settings)
    qtbot.addWidget(win)
    return win


def test_now_tab_shows_state(qtbot, monitor):
    monitor.handle(poll())
    win = window(qtbot, monitor)
    win.show_tab("now")
    assert win.windowTitle() == "Marstek Venus E — Monitor"
    assert win.now.soc.text() == "87%"
    assert win.now.state.text() == "↓ Charging · 1 450 W"
    assert win.now.banners.count() == 0
    assert win.now.bar.value() == 87


def test_device_details_are_always_visible_tiles(qtbot, monitor):
    monitor.handle(poll())
    win = window(qtbot, monitor)
    win.show_tab("now")
    assert [t.title.text() for t in win.now.tiles] == ["TEMPERATURE", "BACKUP LOAD", "CHARGING", "DISCHARGING", "FIRMWARE"]
    assert all(t.isVisible() for t in win.now.tiles)
    assert win.now.tiles[0].value.text() == "24 °C"
    assert not hasattr(win.now, "details_button")


def test_idle_and_energy_lines_use_the_main_text_color(qtbot, monitor):
    monitor.handle(poll(soc=100, power=0.0))
    win = window(qtbot, monitor)
    win.now.render()
    assert win.now.state.text() == "Idle" and "color" not in win.now.state.styleSheet()
    assert win.now.energy.property("role") is None
    assert win.now.energy.font().pointSizeF() > win.font().pointSizeF() * 1.2


def test_blocked_discharge_shows_a_red_banner(qtbot, monitor):
    monitor.handle(poll(discharge_allowed=False))
    win = window(qtbot, monitor)
    win.now.render()
    assert win.now.banners.count() == 1
    assert win.now.banners.itemAt(0).widget().property("role") == "banner-red"


def test_offline_shows_placeholder_soc(qtbot, monitor):
    monitor.handle(poll(online=False))
    win = window(qtbot, monitor)
    win.now.render()
    assert win.now.soc.text() == "--%"


def test_close_hides_the_window(qtbot, monitor):
    win = window(qtbot, monitor)
    win.show()
    win.close()
    assert not win.isVisible()
    win.show_tab("events")
    assert win.isVisible() and win.current_tab() == "events"


def test_font_scale_enlarges_text(qtbot, qapp, monitor):
    small = window(qtbot, monitor).now.soc.font().pointSizeF()
    theme.apply(qapp, "light", 1.5)
    try:
        large = window(qtbot, monitor).now.soc.font().pointSizeF()
    finally:
        theme.apply(qapp, "light", 1.0)
    assert large == pytest.approx(small * 1.5, rel=0.05)


def test_settings_button_requests_settings(qtbot, monitor):
    win = window(qtbot, monitor)
    with qtbot.waitSignal(win.settings_requested):
        win.settings_button.click()
    assert win.settings_button.text() == "⚙ Settings"
