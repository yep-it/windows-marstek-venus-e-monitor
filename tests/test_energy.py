from datetime import date, datetime, timedelta, timezone

import pytest

from marstek_monitor.core.energy import CounterReading, add_months, bars, bars_in_range, lifetime

UTC = timezone.utc


def ts(y, m, d, h=0, mi=0, tz=UTC):
    return datetime(y, m, d, h, mi, tzinfo=tz).timestamp()


def r(t, cin, cout):
    return CounterReading(t, cin, cout)


def test_same_day_sums():
    result = bars([r(ts(2026, 10, 1, 8), 1000, 500), r(ts(2026, 10, 1, 12), 1600, 500),
                   r(ts(2026, 10, 1, 20), 1600, 1100)], "day", UTC)
    assert len(result) == 1
    b = result[0]
    assert (b.first, b.last, b.charged_wh, b.discharged_wh, b.combined) == (
        date(2026, 10, 1), date(2026, 10, 1), 600, 600, False)


def test_counter_reset_never_negative():
    result = bars([r(ts(2026, 10, 1, 8), 1000, 500), r(ts(2026, 10, 1, 9), 10, 5),
                   r(ts(2026, 10, 1, 10), 110, 55)], "day", UTC)
    assert (result[0].charged_wh, result[0].discharged_wh) == (100, 50)


def test_short_gap_across_midnight_is_split_proportionally():
    result = bars([r(ts(2026, 10, 1, 23, 50), 1000, 0), r(ts(2026, 10, 2, 0, 10), 1200, 0)], "day", UTC)
    assert [(b.first, b.charged_wh) for b in result] == [
        (date(2026, 10, 1), pytest.approx(100)), (date(2026, 10, 2), pytest.approx(100))]


def test_long_gap_combines_days_into_one_bar():
    result = bars([
        r(ts(2026, 10, 1, 20), 1000, 0), r(ts(2026, 10, 1, 22), 1100, 0),
        r(ts(2026, 10, 4, 9), 1900, 300), r(ts(2026, 10, 4, 12), 2000, 300),
    ], "day", UTC)
    assert len(result) == 1
    b = result[0]
    assert (b.first, b.last, b.charged_wh, b.discharged_wh, b.combined) == (
        date(2026, 10, 1), date(2026, 10, 4), 1000, 300, True)


def test_monthly_bars():
    result = bars([r(ts(2026, 9, 30, 23, 50), 0, 0), r(ts(2026, 10, 1, 0, 10), 200, 0),
                   r(ts(2026, 10, 15), 500, 100)], "month", UTC)
    assert [(b.first, b.last) for b in result] == [
        (date(2026, 9, 1), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 31))]
    assert result[0].charged_wh == pytest.approx(100)
    assert result[1].charged_wh == pytest.approx(400) and result[1].discharged_wh == 100


def test_yearly_bars():
    result = bars([r(ts(2026, 1, 5), 0, 0), r(ts(2026, 6, 5), 700, 600)], "year", UTC)
    assert [(b.first, b.last, b.charged_wh) for b in result] == [(date(2026, 1, 1), date(2026, 12, 31), 700)]


def test_local_timezone_is_used_for_day_boundaries():
    kyiv_summer = timezone(timedelta(hours=3))
    result = bars([r(ts(2026, 10, 1, 20, 50), 0, 0), r(ts(2026, 10, 1, 21, 10), 200, 0)], "day", kyiv_summer)
    assert [b.first for b in result] == [date(2026, 10, 1), date(2026, 10, 2)]


def test_fewer_than_two_readings():
    assert bars([], "day", UTC) == []
    assert bars([r(0, 1, 1)], "day", UTC) == []


def test_bars_in_range():
    result = bars([
        r(ts(2026, 10, 1, 23, 50), 0, 0), r(ts(2026, 10, 2, 0, 10), 20, 0), r(ts(2026, 10, 2, 9), 30, 0),
    ], "day", UTC)
    assert len(result) == 2
    assert [b.first for b in bars_in_range(result, date(2026, 10, 2), date(2026, 10, 2))] == [date(2026, 10, 2)]


def test_lifetime():
    life = lifetime(r(0, 10000, 9000), 5120)
    assert life.cycles == pytest.approx(9000 / 5120)
    assert life.efficiency == pytest.approx(0.9)
    assert lifetime(None, 5120) is None
    empty = lifetime(r(0, 0, 0), None)
    assert empty.cycles is None and empty.efficiency is None


def test_add_months():
    assert add_months(date(2026, 10, 17), -11) == date(2025, 11, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_pc_off_every_night_keeps_separate_day_bars():
    readings = []
    for d in range(1, 6):
        readings += [r(ts(2026, 9, d, 8), d * 1000, 0), r(ts(2026, 9, d, 22), d * 1000 + 500, 0)]
    result = bars(readings, "day", UTC)
    assert len(result) == 5 and not any(b.combined for b in result)
    assert sum(b.charged_wh for b in result) == pytest.approx(readings[-1].in_wh - readings[0].in_wh)
