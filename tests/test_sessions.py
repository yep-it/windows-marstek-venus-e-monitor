import pytest

from marstek_monitor.core.sessions import (
    FLAG_GAP,
    Session,
    SessionDetector,
    longest_backup,
    typical_full_charge_s,
)
from marstek_monitor.core.snapshot import Snapshot


def snap(ts, soc, power, cin=None, cout=None):
    return Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, counter_in_wh=cin, counter_out_wh=cout)


def feed(detector, samples, **kwargs):
    finished = []
    for s in samples:
        finished += detector.update(s, **kwargs)
    return finished


def test_idle_only_creates_no_session():
    d = SessionDetector(12)
    assert feed(d, [snap(t * 60, 50, 0) for t in range(5)]) == []
    assert d.current is None


def test_complete_charge_session():
    d = SessionDetector(12)
    done = feed(d, [
        snap(0, 40, 0),
        snap(60, 41, 1000, cin=100), snap(120, 42, 1000, cin=120), snap(180, 43, 1000, cin=140),
        snap(240, 43, 0), snap(300, 43, 0),
    ])
    assert len(done) == 1
    s = done[0]
    assert (s.kind, s.start_ts, s.end_ts, s.start_soc, s.end_soc) == ("charge", 60, 240, 41, 43)
    assert s.energy_wh == 40
    assert s.duration_s == 180
    assert s.avg_power_w == pytest.approx(800)
    assert s.quality == "complete"
    assert s.cause == "other"


def test_single_blip_does_not_start_a_session():
    d = SessionDetector(12)
    assert feed(d, [snap(0, 40, 0), snap(60, 40, 900), snap(120, 40, 0), snap(180, 40, 0)]) == []
    assert d.current is None


def test_session_already_running_at_app_start_is_flagged():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 50, 900), snap(60, 51, 900), snap(120, 51, 0), snap(180, 51, 0)])
    assert done[0].quality == "started_before_app"
    assert done[0].start_ts == 0


def test_charge_ends_at_full_and_no_new_session_at_100():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 97, 0), snap(60, 98, 900), snap(120, 99, 900), snap(180, 100, 900),
                    snap(240, 100, 200), snap(300, 100, 200)])
    assert len(done) == 1
    assert done[0].end_ts == 180 and done[0].end_soc == 100
    assert d.current is None


def test_gap_marks_session():
    d = SessionDetector(12)
    feed(d, [snap(0, 40, 0), snap(60, 41, 900), snap(120, 42, 900)])
    d.mark_gap()
    done = feed(d, [snap(400, 45, 900), snap(460, 45, 0), snap(520, 45, 0)])
    assert done[0].quality == FLAG_GAP


def test_session_that_ended_while_app_was_off():
    d1 = SessionDetector(12)
    feed(d1, [snap(0, 40, 0), snap(60, 41, 900), snap(120, 42, 900)])
    open_session = d1.current
    d2 = SessionDetector(12)
    d2.restore(open_session)
    done = d2.update(snap(1000, 80, 0))
    assert len(done) == 1
    assert done[0].quality == "ended_while_off"
    assert done[0].end_ts == 120 and done[0].end_soc == 42


def test_energy_falls_back_to_power_integration():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 40, 0), snap(60, 41, 1200), snap(120, 42, 1200), snap(180, 43, 1200),
                    snap(240, 43, 0), snap(300, 43, 0)])
    assert done[0].energy_wh == pytest.approx(40)


def test_counter_reset_is_never_negative():
    d = SessionDetector(12)
    feed(d, [snap(0, 40, 0), snap(60, 41, 900, cin=100), snap(120, 42, 900, cin=120),
             snap(180, 43, 900, cin=5), snap(240, 44, 900, cin=25)])
    assert d.current.energy_so_far() == 40


def test_discharge_during_outage():
    d = SessionDetector(12)
    feed(d, [snap(0, 100, 0), snap(60, 99, -800), snap(120, 98, -800)], outage_active=True)
    assert d.current.kind == "discharge" and d.current.cause == "outage"


def test_charge_right_after_outage():
    d = SessionDetector(12)
    feed(d, [snap(60, 30, 0), snap(120, 31, 900), snap(180, 32, 900)], last_outage_end_ts=0)
    assert d.current.cause == "after_outage"


def test_charge_after_full_discharge():
    d = SessionDetector(12)
    feed(d, [snap(0, 13, 0), snap(60, 13, 900), snap(120, 14, 900)])
    assert d.current.cause == "after_full_discharge"


def test_soc_trend_is_used_when_power_is_missing():
    d = SessionDetector(12)
    feed(d, [snap(0, 50, None), snap(60, 50, None), snap(120, 51, None), snap(180, 52, None)])
    assert d.current is not None
    assert d.current.kind == "charge" and d.current.start_ts == 120


def test_opposite_direction_ends_and_starts_sessions():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 50, 0), snap(60, 51, 900), snap(120, 52, 900),
                    snap(180, 52, -700), snap(240, 51, -700)])
    assert [s.kind for s in done] == ["charge"]
    assert done[0].end_ts == 180
    assert d.current.kind == "discharge" and d.current.start_ts == 180


def test_summaries():
    charges = [
        Session(kind="charge", start_ts=0, start_soc=20, end_ts=9600, end_soc=100),
        Session(kind="charge", start_ts=10000, start_soc=50, end_ts=14000, end_soc=90),
    ]
    discharges = [
        Session(kind="discharge", start_ts=20000, start_soc=100, end_ts=23600, end_soc=60),
        Session(kind="discharge", start_ts=30000, start_soc=100, end_ts=37200, end_soc=20),
        Session(kind="discharge", start_ts=40000, start_soc=100, end_ts=49000, end_soc=10, flags={FLAG_GAP}),
    ]
    assert typical_full_charge_s(charges + discharges) == pytest.approx(8800)
    assert longest_backup(charges + discharges).start_ts == 30000
    assert typical_full_charge_s([]) is None
    assert longest_backup([]) is None


def test_session_dict_roundtrip():
    s = Session(kind="discharge", start_ts=5, start_soc=90, cause="outage", flags={"gap"}, end_ts=50, id=3)
    assert Session.from_dict(s.to_dict()) == s


def test_flat_counter_falls_back_to_power_integration():
    # The output counter does not count the backup socket, so it stays flat while discharging.
    d = SessionDetector(12)
    done = feed(d, [snap(0, 99, 0, cout=3329), snap(60, 99, -120, cout=3329), snap(120, 98, -120, cout=3329),
                    snap(180, 98, -120, cout=3329), snap(240, 98, 0, cout=3329), snap(300, 98, 0, cout=3329)])
    assert done[0].energy_wh == pytest.approx(4)  # 120 W for 2 minutes
