"""Energy per day/month/year from the battery's lifetime counters (spec §6.6, pure logic).

Energy between two counter readings is attributed to the period both readings fall in.
Readings in adjacent periods (e.g. the PC was off overnight) are split in proportion to
time. Gaps that leave at least one whole period without readings merge all periods they
span into one combined bar, which keeps totals exact while the per-period split is unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, tzinfo

@dataclass(frozen=True)
class CounterReading:
    ts: float
    in_wh: float
    out_wh: float


@dataclass(frozen=True)
class EnergyBar:
    first: date
    last: date
    charged_wh: float
    discharged_wh: float
    combined: bool


@dataclass(frozen=True)
class Lifetime:
    charged_wh: float
    discharged_wh: float
    cycles: float | None
    efficiency: float | None


def add_months(d: date, n: int) -> date:
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def _local_date(ts: float, tz: tzinfo | None) -> date:
    return datetime.fromtimestamp(ts, tz).date()


def _key(d: date, period: str) -> date:
    if period == "day":
        return d
    if period == "month":
        return d.replace(day=1)
    return date(d.year, 1, 1)


def _next_key(k: date, period: str) -> date:
    if period == "day":
        return k + timedelta(days=1)
    if period == "month":
        return add_months(k, 1)
    return date(k.year + 1, 1, 1)


def _last_day(k: date, period: str) -> date:
    return k if period == "day" else _next_key(k, period) - timedelta(days=1)


def _start_ts(k: date, tz: tzinfo | None) -> float:
    return datetime.combine(k, dtime.min, tzinfo=tz).timestamp()


def bars(readings: list[CounterReading], period: str, tz: tzinfo | None = None) -> list[EnergyBar]:
    rs = sorted(readings, key=lambda x: x.ts)
    if len(rs) < 2:
        return []
    totals: dict[date, list[float]] = {}
    merges: list[tuple[date, date]] = []

    def add(k: date, din: float, dout: float) -> None:
        t = totals.setdefault(k, [0.0, 0.0])
        t[0] += din
        t[1] += dout

    for a, b in zip(rs, rs[1:]):
        din = max(0.0, b.in_wh - a.in_wh)
        dout = max(0.0, b.out_wh - a.out_wh)
        ka = _key(_local_date(a.ts, tz), period)
        kb = _key(_local_date(b.ts, tz), period)
        if ka == kb:
            add(ka, din, dout)
        elif _next_key(ka, period) == kb:  # adjacent periods (e.g. PC off overnight): split by time
            frac = (_start_ts(kb, tz) - a.ts) / (b.ts - a.ts)
            frac = min(1.0, max(0.0, frac))
            add(ka, din * frac, dout * frac)
            add(kb, din * (1 - frac), dout * (1 - frac))
        else:
            add(ka, din, dout)
            add(kb, 0.0, 0.0)
            merges.append((ka, kb))

    keys: list[date] = []
    k = _key(_local_date(rs[0].ts, tz), period)
    last_key = _key(_local_date(rs[-1].ts, tz), period)
    while k <= last_key:
        keys.append(k)
        k = _next_key(k, period)

    joined: set[date] = set()  # keys merged with their successor
    for ka, kb in merges:
        k = ka
        while k < kb:
            joined.add(k)
            k = _next_key(k, period)

    out: list[EnergyBar] = []
    group: list[date] = []
    for k in keys:
        group.append(k)
        if k in joined:
            continue
        charged = sum(totals.get(g, [0.0, 0.0])[0] for g in group)
        discharged = sum(totals.get(g, [0.0, 0.0])[1] for g in group)
        out.append(EnergyBar(group[0], _last_day(group[-1], period), charged, discharged, len(group) > 1))
        group = []
    return out


def bars_in_range(items: list[EnergyBar], first: date, last: date) -> list[EnergyBar]:
    return [b for b in items if b.last >= first and b.first <= last]


def lifetime(latest: CounterReading | None, rated_wh: float | None) -> Lifetime | None:
    if latest is None:
        return None
    cycles = latest.out_wh / rated_wh if rated_wh else None
    efficiency = latest.out_wh / latest.in_wh if latest.in_wh > 0 else None
    return Lifetime(latest.in_wh, latest.out_wh, cycles, efficiency)
