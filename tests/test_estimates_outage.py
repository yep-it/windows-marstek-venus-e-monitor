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
    assert d.state == "lost" and d.since == 60
    assert d.update(snap(ts=120, ongrid=0, offgrid=480)) is None
    assert d.update(snap(ts=180, ongrid=900, offgrid=480)) is None
    assert d.update(snap(ts=240, ongrid=900, offgrid=480)) == "restored"
    assert d.state == "ok" and d.last_end_ts == 240 and d.last_duration_s == 180


def test_single_glitch_does_not_trigger():
    d = OutageDetector(enabled=True)
    d.update(snap(ts=0, ongrid=0, offgrid=500))
    assert d.update(snap(ts=60, ongrid=900, offgrid=500)) is None
    assert d.update(snap(ts=120, ongrid=0, offgrid=500)) is None
    assert d.state == "ok"
