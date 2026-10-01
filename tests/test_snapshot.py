from marstek_monitor.core.snapshot import (
    NormalizeConfig,
    Snapshot,
    normalize,
    snapshot_from_dict,
    snapshot_to_dict,
)
from tests.fakes.fake_battery import load_fixture

FIX = {m: r["result"] for m, r in load_fixture().items()}
CFG = NormalizeConfig()


def raw(**overrides):
    data = {"Bat.GetStatus": dict(FIX["Bat.GetStatus"]), "ES.GetStatus": dict(FIX["ES.GetStatus"]),
            "Wifi.GetStatus": dict(FIX["Wifi.GetStatus"])}
    for method, values in overrides.items():
        key = method.replace("_", ".", 1)
        data[key] = None if values is None else {**(data.get(key) or {}), **values}
    return data


def test_probe_fixture_normalizes():
    s = normalize(1000.0, raw(), CFG, fw_version=144, ip="192.168.1.20")
    assert s.responded is True
    assert s.soc_pct == 100
    assert s.stored_wh == 5120.0 and s.rated_wh == 5120.0
    assert s.temp_c == 24.0
    assert s.power_w == 0.0
    assert s.counter_in_wh == 9196.0 and s.counter_out_wh == 3329.0
    assert s.charge_allowed is True and s.discharge_allowed is True
    assert s.rssi_dbm == -49
    assert s.fw_version == 144 and s.ip == "192.168.1.20"


def test_power_sign_can_be_inverted():
    data = raw(ES_GetStatus={"ongrid_power": 800})
    assert normalize(0, data, CFG).power_w == 800
    assert normalize(0, data, NormalizeConfig(power_sign="minus_is_charging")).power_w == -800


def test_bat_power_is_preferred_over_ongrid():
    data = raw(ES_GetStatus={"ongrid_power": 800, "bat_power": -300})
    assert normalize(0, data, CFG).power_w == -300


def test_counter_units():
    data = raw(ES_GetStatus={"total_grid_input_energy": 50})
    assert normalize(0, data, NormalizeConfig(counter_unit="0.01kWh")).counter_in_wh == 500.0
    assert normalize(0, data, NormalizeConfig(counter_unit="0.1Wh")).counter_in_wh == 5.0
    assert normalize(0, data, NormalizeConfig(counter_unit="kWh")).counter_in_wh == 50000.0


def test_temperature_times_ten_bug_is_corrected():
    assert normalize(0, raw(Bat_GetStatus={"bat_temp": 245}), CFG).temp_c == 24.5
    assert normalize(0, raw(Bat_GetStatus={"bat_temp": 2000}), CFG).temp_c is None


def test_invalid_soc_falls_back_to_es_status():
    s = normalize(0, raw(Bat_GetStatus={"soc": 150}, ES_GetStatus={"bat_soc": 77}), CFG)
    assert s.soc_pct == 77


def test_soc_as_string():
    assert normalize(0, raw(Bat_GetStatus={"soc": "90"}), CFG).soc_pct == 90


def test_stored_energy_is_derived_when_missing():
    s = normalize(0, raw(Bat_GetStatus={"bat_capacity": None, "soc": 50}), CFG)
    assert s.stored_wh == 2560.0


def test_nothing_answered():
    s = normalize(0, {"Bat.GetStatus": None, "ES.GetStatus": None}, CFG, failed=("Bat.GetStatus", "ES.GetStatus"))
    assert s.responded is False
    assert s.soc_pct is None
    assert s.failed_methods == ("Bat.GetStatus", "ES.GetStatus")


def test_dict_roundtrip():
    s = normalize(5.0, raw(), CFG, fw_version=144, failed=("Wifi.GetStatus",))
    assert snapshot_from_dict(snapshot_to_dict(s)) == s
    assert isinstance(snapshot_from_dict({"ts": 1.0, "responded": True, "extra": 1}), Snapshot)


def test_backup_output_counts_as_supplying():
    # Real reading 2026-10-01 14:54: the PC runs from the battery's backup socket.
    data = raw(ES_GetStatus={"ongrid_power": 0, "offgrid_power": 115})
    assert normalize(0, data, CFG).power_w == -115


def test_grid_exchange_still_uses_the_grid_side_power():
    data = raw(ES_GetStatus={"ongrid_power": 800, "offgrid_power": 0})
    assert normalize(0, data, CFG).power_w == 800


def test_small_backup_load_below_the_idle_band_is_ignored():
    data = raw(ES_GetStatus={"ongrid_power": 0, "offgrid_power": 20})
    assert normalize(0, data, CFG).power_w == 0
