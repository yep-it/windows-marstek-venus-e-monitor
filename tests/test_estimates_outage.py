import pytest

from marstek_monitor.core.estimates import direction, minutes_left, minutes_to_full
from marstek_monitor.core.outage import OutageDetector
from marstek_monitor.core.snapshot import Snapshot


def snap(ts=0.0, power=None, stored=None, rated=5120.0, ongrid=None, offgrid=None):
    return Snapshot(ts=ts, responded=True, power_w=power, stored_wh=stored, rated_wh=rated,
                    ongrid_w=ongrid, offgrid_w=offgrid)


@pytest.mark.parametrize("power,expected", [(None, None), (0, "idle"), (30, "idle"), (-30, "idle"),
                                            (31, "charging"), (-31, "discharging")])
def test_direction(power, expected):
    assert direction(power) == expected


def test_minutes_to_full():
    assert minutes_to_full(snap(power=1000, stored=4120)) == pytest.approx(60.0)
    assert minutes_to_full(snap(power=0, stored=4120)) is None
    assert minutes_to_full(snap(power=-500, stored=4120)) is None


def test_minutes_left_respects_reserve():
    # reserve 12% of 5120 = 614.4 Wh; usable = 2560 - 614.4 = 1945.6 Wh at 1000 W
    assert minutes_left(snap(power=-1000, stored=2560), 12) == pytest.approx(116.736)
    assert minutes_left(snap(power=500, stored=2560), 12) is None
    assert minutes_left(snap(power=-1000, stored=300), 12) == 0.0


def test_disabled_detector_stays_unknown():
    d = OutageDetector(enabled=False)
    assert d.update(snap(ongrid=0, offgrid=500)) is None
    assert d.state == "unknown"


def test_outage_needs_two_samples_and_restores():
    d = OutageDetector(enabled=True)
    assert d.state == "ok"
    assert d.update(snap(ts=0, ongrid=0, offgrid=500)) is None
    assert d.update(snap(ts=60, ongrid=0, offgrid=500)) == "lost"
    assert d.state == "lost" and d.since == 0  # the first matching sample
    assert d.update(snap(ts=120, ongrid=0, offgrid=480)) is None
    assert d.update(snap(ts=180, ongrid=900, offgrid=480)) is None
    assert d.update(snap(ts=240, ongrid=900, offgrid=480)) == "restored"
    assert d.state == "ok" and d.last_end_ts == 180 and d.last_duration_s == 180


def test_single_glitch_does_not_trigger():
    d = OutageDetector(enabled=True)
    d.update(snap(ts=0, ongrid=0, offgrid=500))
    assert d.update(snap(ts=60, ongrid=900, offgrid=500)) is None
    assert d.update(snap(ts=120, ongrid=0, offgrid=500)) is None
    assert d.state == "ok"


def full(ts, offgrid):
    return Snapshot(ts=ts, responded=True, soc_pct=100, stored_wh=5120.0, rated_wh=5120.0, ongrid_w=0.0,
                    offgrid_w=offgrid)


def test_full_battery_with_backup_load_is_not_an_outage():
    d = OutageDetector(enabled=True)
    assert d.update(full(0, 95)) is None
    assert d.update(full(60, 95)) is None
    assert d.state == "ok"


def test_outage_is_detected_once_the_battery_drops_below_full():
    d = OutageDetector(enabled=True)
    d.update(full(0, 95))
    below = Snapshot(ts=60, responded=True, soc_pct=99, stored_wh=5115.0, rated_wh=5120.0, ongrid_w=0.0, offgrid_w=95)
    d.update(below)
    assert d.update(Snapshot(ts=120, responded=True, soc_pct=99, stored_wh=5110.0, rated_wh=5120.0,
                             ongrid_w=0.0, offgrid_w=95)) == "lost"


def test_outage_start_is_the_first_sample_that_looked_lost():
    # Real 2026-10-01: Supplying first seen 15:39:54, outage confirmed 15:40:54 -> the outage started 15:39:54.
    d = OutageDetector(enabled=True)
    d.update(full(0, 77))
    d.update(Snapshot(ts=60, responded=True, soc_pct=99, stored_wh=5114.0, rated_wh=5120.0, ongrid_w=0.0, offgrid_w=110))
    d.update(Snapshot(ts=120, responded=True, soc_pct=99, stored_wh=5114.0, rated_wh=5120.0, ongrid_w=0.0, offgrid_w=84))
    assert d.state == "lost" and d.since == 60


def test_glitch_does_not_move_the_outage_start():
    d = OutageDetector(enabled=True)
    d.update(snap(ts=0, ongrid=0, offgrid=500))
    d.update(snap(ts=60, ongrid=900, offgrid=500))
    d.update(snap(ts=120, ongrid=0, offgrid=500))
    d.update(snap(ts=180, ongrid=0, offgrid=500))
    assert d.state == "lost" and d.since == 120
