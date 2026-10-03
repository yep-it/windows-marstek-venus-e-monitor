import json

from marstek_monitor import settings


def test_missing_file_gives_defaults(tmp_path):
    data, warning = settings.load(tmp_path / "settings.json")
    assert warning is None
    assert data == settings.defaults()
    assert data["general"]["poll_seconds"] == 60
    assert data["device"]["port"] == 30000


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = settings.defaults()
    data["telegram"]["bot_token"] = "123:abc"
    data["general"]["language"] = "uk"
    settings.save(path, data)
    loaded, warning = settings.load(path)
    assert warning is None
    assert loaded == data


def test_unknown_keys_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    raw = settings.defaults()
    raw["future_section"] = {"x": 1}
    raw["general"]["future_flag"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded, _ = settings.load(path)
    assert loaded["future_section"] == {"x": 1}
    assert loaded["general"]["future_flag"] is True


def test_wrong_types_fall_back_to_defaults():
    data = settings.validate({"general": {"language": "de", "autostart": "yes"}, "quiet_hours": {"from": "25:00"}})
    assert data["general"]["language"] == "en"
    assert data["general"]["autostart"] is False
    assert data["quiet_hours"]["from"] == "23:00"


def test_battery_ip_loses_leading_zeros():
    data = settings.validate({"device": {"ip": "192.168.01.020"}})
    assert data["device"]["ip"] == "192.168.1.20"


def test_numbers_are_clamped():
    data = settings.validate({"general": {"poll_seconds": 10}, "appearance": {"font_scale": 5}})
    assert data["general"]["poll_seconds"] == settings.MIN_POLL_SECONDS
    assert data["appearance"]["font_scale"] == 2.0


def test_soc_levels_are_limited_and_completed():
    levels = [{"pct": 50}, {"pct": 30}, {"pct": 20}, {"pct": 10}]
    data = settings.validate({"notifications": {"soc_below": levels}})
    below = data["notifications"]["soc_below"]
    assert [lvl["pct"] for lvl in below] == [50, 30, 20]
    assert below[0]["enabled"] is True and below[0]["priority"] == "normal"


def test_empty_soc_levels_fall_back_to_defaults():
    data = settings.validate({"notifications": {"soc_below": []}})
    assert [lvl["pct"] for lvl in data["notifications"]["soc_below"]] == [40, 20]


def test_telegram_ids_accept_numbers():
    data = settings.validate({"telegram": {"chat_id": 123456789, "user_id": " 42 "}})
    assert data["telegram"]["chat_id"] == "123456789"
    assert data["telegram"]["user_id"] == "42"


def test_broken_file_is_renamed_and_defaults_loaded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    data, warning = settings.load(path)
    assert warning == "sys.settings_broken"
    assert data == settings.defaults()
    assert not path.exists()
    assert len(list(tmp_path.glob("settings.broken-*.json"))) == 1


def test_defaults_are_independent_copies():
    a = settings.defaults()
    a["notifications"]["soc_below"][0]["pct"] = 99
    assert settings.defaults()["notifications"]["soc_below"][0]["pct"] == 40


def test_old_default_power_sign_is_migrated_once():
    old_file = {"schema": 1, "advanced": {"power_sign": "plus_is_charging"}}
    assert settings.validate(old_file)["advanced"]["power_sign"] == "minus_is_charging"
    chosen_after_migration = {"schema": 2, "advanced": {"power_sign": "plus_is_charging"}}
    assert settings.validate(chosen_after_migration)["advanced"]["power_sign"] == "plus_is_charging"
    assert settings.defaults()["advanced"]["power_sign"] == "minus_is_charging"
