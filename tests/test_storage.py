import pytest

from marstek_monitor.core.events import Event
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage

DAY = 86400


@pytest.fixture
def db(tmp_path):
    storage = Storage(tmp_path / "history.db")
    yield storage
    storage.close()


def event(ts=0.0, **kw):
    base = dict(ts=ts, kind="notification", rule_id="soc_below", priority="normal",
                title_key="n.soc_below.title", body_key="n.soc_below.body", params={"pct": 40, "soc": 39},
                desktop="pending", telegram="off")
    base.update(kw)
    return Event(**base)


def test_sample_roundtrip(db):
    s = Snapshot(ts=10.0, responded=True, soc_pct=55, power_w=-300.0, failed_methods=("Wifi.GetStatus",))
    db.add_sample(s)
    assert db.samples_since(0) == [s]
    assert db.samples_since(11) == []


def test_counter_throttle_and_force(db):
    assert db.add_counter(0, 100, 50) is True
    assert db.add_counter(300, 110, 50) is False
    assert db.add_counter(700, 120, 50) is True
    assert db.add_counter(800, 130, 50, force=True) is True
    assert [c.ts for c in db.counters()] == [0, 700, 800]
    assert db.last_counter().in_wh == 130


def test_session_insert_update_and_open(db):
    s = Session(kind="charge", start_ts=10, start_soc=40, flags={"gap"})
    sid = db.save_session(s)
    assert s.id == sid
    assert db.open_session() == s
    s.end_ts, s.end_soc = 100, 80
    db.save_session(s)
    assert db.open_session() is None
    stored = db.sessions()
    assert len(stored) == 1 and stored[0].end_ts == 100 and stored[0].flags == {"gap"}


def test_events_and_delivery(db):
    first = db.add_event(event(ts=1))
    db.add_event(event(ts=2, rule_id="offline"))
    db.set_delivery(first, "telegram", "sent")
    items = db.events()
    assert [e.rule_id for e in items] == ["offline", "soc_below"]
    assert items[1].telegram == "sent" and items[1].params == {"pct": 40, "soc": 39}
    with pytest.raises(ValueError):
        db.set_delivery(first, "email", "sent")


def test_purge(db):
    now = 1000 * DAY
    db.add_sample(Snapshot(ts=now - 40 * DAY, responded=True))
    db.add_sample(Snapshot(ts=now - 1 * DAY, responded=True))
    db.add_event(event(ts=now - 100 * DAY))
    db.add_event(event(ts=now - 1 * DAY))
    db.purge(now, samples_days=30)
    assert len(db.samples_since(0)) == 1
    assert len(db.events()) == 1


def test_meta(db):
    assert db.get_meta("fw_version") is None
    assert db.get_meta("fw_version", "x") == "x"
    db.set_meta("fw_version", "144")
    assert db.get_meta("fw_version") == "144"


def test_reopen_keeps_data(tmp_path):
    path = tmp_path / "history.db"
    first = Storage(path)
    first.add_counter(0, 1, 2)
    first.close()
    second = Storage(path)
    assert len(second.counters()) == 1
    second.close()
