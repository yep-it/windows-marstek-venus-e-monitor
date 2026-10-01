from marstek_monitor import settings as settings_mod
from marstek_monitor import i18n
from marstek_monitor.app import (
    apply_device_change, keep_live_device, poller_config, poller_key, tab_for, telegram_config_problem, telegram_notice,
)
from marstek_monitor.core.events import Event


def test_poller_config_from_settings():
    cfg = settings_mod.defaults()
    cfg["device"].update(ip="192.168.1.20", ble_mac="0123456789ab", local_port=40000)
    cfg["advanced"]["counter_unit"] = "0.01kWh"
    pc = poller_config(cfg)
    assert (pc.ip, pc.port, pc.ble_mac, pc.local_port, pc.poll_seconds, pc.offline_after_polls) == (
        "192.168.1.20", 30000, "0123456789ab", 40000, 60, 3)
    assert pc.normalize.counter_unit == "0.01kWh"


def test_poller_key_changes_only_for_poller_settings():
    a = settings_mod.defaults()
    b = settings_mod.defaults()
    b["appearance"]["font_scale"] = 1.5
    assert poller_key(a) == poller_key(b)
    b["general"]["poll_seconds"] = 120
    assert poller_key(a) != poller_key(b)


def test_telegram_config_problem():
    tg = settings_mod.defaults()["telegram"]
    assert telegram_config_problem(tg) is None
    tg["enabled"] = True
    assert telegram_config_problem(tg) == "settings.tg_missing"
    tg.update(bot_token="123:abc", chat_id="")
    assert telegram_config_problem(tg) == "settings.tg_missing"
    tg["chat_id"] = "100"
    assert telegram_config_problem(tg) is None


def test_device_change_is_persisted():
    cfg = settings_mod.defaults()
    assert apply_device_change(cfg, "192.168.1.77", "0123456789ab") is True
    assert cfg["device"]["ip"] == "192.168.1.77" and cfg["device"]["ble_mac"] == "0123456789ab"
    assert apply_device_change(cfg, "192.168.1.77", "0123456789ab") is False
    assert apply_device_change(cfg, None, "") is False


def test_tab_for():
    def e(rule_id, kind="notification"):
        return Event(ts=0, kind=kind, rule_id=rule_id, priority="normal", title_key="x", body_key="")
    assert tab_for(e("charge_session")) == "sessions"
    assert tab_for(e("system", kind="system")) == "events"
    assert tab_for(e("soc_below")) == "now"


def test_telegram_notice_explains_incomplete_setup():
    i18n.set_language("en")
    cfg = settings_mod.defaults()
    assert telegram_notice(cfg) == ""
    cfg["telegram"]["enabled"] = True
    assert telegram_notice(cfg) == "Enter the bot token and chat ID first."


def test_saving_settings_keeps_a_rediscovered_ip():
    original = settings_mod.defaults()
    original["device"].update(ip="192.168.1.20", ble_mac="0123456789ab")
    live = settings_mod.defaults()
    live["device"].update(ip="192.168.1.77", ble_mac="0123456789ab")   # rediscovered while the window was open
    new = settings_mod.defaults()
    new["device"].update(ip="192.168.1.20", ble_mac="0123456789ab")    # user did not touch the IP field
    keep_live_device(new, original, live)
    assert new["device"]["ip"] == "192.168.1.77"
    edited = settings_mod.defaults()
    edited["device"].update(ip="192.168.1.99", ble_mac="0123456789ab")  # user typed a new IP
    keep_live_device(edited, original, live)
    assert edited["device"]["ip"] == "192.168.1.99"


def test_telegram_notice_for_missing_user_id():
    i18n.set_language("en")
    cfg = settings_mod.defaults()
    cfg["telegram"].update(enabled=True, bot_token="1:a", chat_id="5", user_id="", answer_command=True)
    assert "user ID" in telegram_notice(cfg)
    cfg["telegram"]["user_id"] = "5"
    assert telegram_notice(cfg) == ""
