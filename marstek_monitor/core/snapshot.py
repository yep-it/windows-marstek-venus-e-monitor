"""One poll's data, normalized. All firmware quirks are handled here (spec §4, §6.2)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

COUNTER_UNITS = {"Wh": 1.0, "0.1Wh": 0.1, "0.01kWh": 10.0, "kWh": 1000.0}
BACKUP_MIN_W = 30.0   # backup-socket load that counts as the battery supplying power
GRID_IDLE_W = 5.0     # grid-side power this small means "no grid exchange"


@dataclass(frozen=True)
class NormalizeConfig:
    # spec V1, verified 2026-10-01: ongrid_power is negative while the battery charges from the grid
    power_sign: str = "minus_is_charging"
    counter_unit: str = "Wh"               # spec V2: unit of the lifetime energy counters


@dataclass(frozen=True)
class Snapshot:
    ts: float
    responded: bool
    soc_pct: int | None = None
    stored_wh: float | None = None
    rated_wh: float | None = None
    temp_c: float | None = None
    power_w: float | None = None      # + = charging, - = discharging (after sign mapping)
    ongrid_w: float | None = None
    offgrid_w: float | None = None
    charge_allowed: bool | None = None
    discharge_allowed: bool | None = None
    counter_in_wh: float | None = None
    counter_out_wh: float | None = None
    rssi_dbm: int | None = None
    fw_version: int | None = None
    ip: str | None = None
    failed_methods: tuple[str, ...] = ()


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _soc(value: Any) -> int | None:
    n = _num(value)
    if n is None or not 0 <= n <= 100:
        return None
    return int(round(n))


def _temp(value: Any) -> float | None:
    n = _num(value)
    if n is None:
        return None
    if n > 100:  # known firmware bug: temperature reported x10
        n = n / 10
    if n > 100 or n < -40:
        return None
    return n


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def normalize(
    ts: float,
    raw: dict[str, dict | None],
    cfg: NormalizeConfig,
    fw_version: int | None = None,
    ip: str | None = None,
    failed: tuple[str, ...] = (),
) -> Snapshot:
    bat = raw.get("Bat.GetStatus") or {}
    es = raw.get("ES.GetStatus") or {}
    wifi = raw.get("Wifi.GetStatus") or {}

    soc = _soc(bat.get("soc"))
    if soc is None:
        soc = _soc(es.get("bat_soc"))
    rated = _num(bat.get("rated_capacity")) or _num(es.get("bat_cap"))
    stored = _num(bat.get("bat_capacity"))
    if stored is None and soc is not None and rated:
        stored = rated * soc / 100

    ongrid = _num(es.get("ongrid_power"))
    offgrid = _num(es.get("offgrid_power"))
    raw_power = _num(es.get("bat_power"))
    if raw_power is None:
        raw_power = ongrid
    power = None
    if raw_power is not None:
        power = raw_power if cfg.power_sign == "plus_is_charging" else -raw_power
    if (es.get("bat_power") is None and offgrid is not None and offgrid > BACKUP_MIN_W
            and (ongrid is None or abs(ongrid) <= GRID_IDLE_W)):
        # Verified 2026-10-01: a load on the backup socket shows only in offgrid_power
        # (ongrid_power stays 0) while the stored energy falls, so the battery supplies it.
        power = -offgrid

    unit = COUNTER_UNITS.get(cfg.counter_unit, 1.0)
    counter_in = _num(es.get("total_grid_input_energy"))
    counter_out = _num(es.get("total_grid_output_energy"))
    rssi = _num(wifi.get("rssi"))

    return Snapshot(
        ts=ts,
        responded=bool(bat or es),
        soc_pct=soc,
        stored_wh=stored,
        rated_wh=rated,
        temp_c=_temp(bat.get("bat_temp")),
        power_w=power,
        ongrid_w=ongrid,
        offgrid_w=offgrid,
        charge_allowed=_flag(bat.get("charg_flag")),
        discharge_allowed=_flag(bat.get("dischrg_flag")),
        counter_in_wh=None if counter_in is None else counter_in * unit,
        counter_out_wh=None if counter_out is None else counter_out * unit,
        rssi_dbm=None if rssi is None else int(rssi),
        fw_version=fw_version,
        ip=ip,
        failed_methods=tuple(failed),
    )


def snapshot_to_dict(s: Snapshot) -> dict:
    data = asdict(s)
    data["failed_methods"] = list(s.failed_methods)
    return data


def snapshot_from_dict(data: dict) -> Snapshot:
    known = {f.name for f in fields(Snapshot)}
    clean = {k: v for k, v in data.items() if k in known}
    clean["failed_methods"] = tuple(clean.get("failed_methods", ()))
    return Snapshot(**clean)
