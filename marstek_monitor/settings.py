"""Settings as plain nested dicts: defaults, validation, JSON load/save.

Unknown keys are preserved. Wrong types fall back to the default; out-of-range
numbers are clamped.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable

from .api.client import clean_ip

log = logging.getLogger(__name__)

SCHEMA = 2
MIN_POLL_SECONDS = 60
MAX_SOC_LEVELS = 3


def _level(pct: int, priority: str, telegram: bool, repeat_min: int) -> dict:
    return {"enabled": True, "pct": pct, "priority": priority, "desktop": True,
            "telegram": telegram, "repeat_min": repeat_min}


DEFAULTS: dict[str, Any] = {
    "schema": SCHEMA,
    "device": {"ble_mac": "", "ip": "", "port": 30000, "local_port": None},
    "general": {"language": "en", "autostart": False, "poll_seconds": 60,
                "offline_after_polls": 3, "start_menu_shortcut": True},
    "appearance": {"font_scale": 1.0, "theme": "system"},
    "quiet_hours": {"enabled": False, "from": "23:00", "to": "07:00",
                    "critical_bypass": True, "silence_telegram": False},
    "notifications": {
        "soc_below": [_level(40, "normal", False, 0), _level(20, "critical", True, 30)],
        "soc_reached": {"enabled": True, "pct": 100, "desktop": True, "telegram": False, "repeat_min": 0},
        "grid": {"enabled": False, "desktop": True, "telegram": True, "repeat_min": 0},
        "backup_left": {"enabled": False, "minutes": 30, "desktop": True, "telegram": True, "repeat_min": 0},
        "charge_session": {"enabled": True, "desktop": True, "telegram": False},
        "discharge_session": {"enabled": True, "desktop": True, "telegram": True},
        "offline": {"enabled": True, "desktop": True, "telegram": True, "repeat_min": 60},
        "blocked": {"enabled": True, "desktop": True, "telegram": True, "repeat_min": 60},
        "temperature": {"enabled": True, "high": 45, "low": 5, "desktop": True, "telegram": True,
                        "repeat_min": 0},
        "firmware": {"enabled": True, "desktop": True, "telegram": False},
        "monitor": {"enabled": True, "telegram": True},
    },
    "telegram": {"enabled": False, "bot_token": "", "chat_id": "", "user_id": "", "answer_command": True},
    "advanced": {"power_sign": "minus_is_charging", "counter_unit": "Wh", "counters_verified": False,
                 "outage_detection": False, "rearm_pct": 2, "rearm_c": 2, "reserve_soc_pct": 12,
                 "inverter_efficiency_pct": 93,
                 "samples_retention_days": 30, "log_level": "INFO", "record_raw": False},
}

Validator = Callable[[Any], Any]


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def int_range(lo: int, hi: int) -> Validator:
    def check(value: Any) -> int:
        if not _is_num(value):
            raise ValueError("not a number")
        return int(min(hi, max(lo, round(value))))
    return check


def float_range(lo: float, hi: float) -> Validator:
    def check(value: Any) -> float:
        if not _is_num(value):
            raise ValueError("not a number")
        return float(min(hi, max(lo, value)))
    return check


def choice(*options: Any) -> Validator:
    def check(value: Any) -> Any:
        if value not in options:
            raise ValueError(f"{value!r} not in {options}")
        return value
    return check


def boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("not a bool")
    return value


def text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("not a string")
    return value.strip()


def hhmm(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("not HH:MM")
    return value


def optional_port(value: Any) -> int | None:
    return None if value is None else int_range(1, 65535)(value)


def id_text(value: Any) -> str:
    if _is_num(value):
        return str(int(value))
    return text(value)


def same_number(value: Any) -> Any:
    if not _is_num(value):
        raise ValueError("not a number")
    return value


VALIDATORS: dict[str, Validator] = {
    "device.ble_mac": text,
    "device.ip": lambda value: clean_ip(text(value)),
    "device.port": int_range(1, 65535),
    "device.local_port": optional_port,
    "general.language": choice("en", "uk"),
    "general.poll_seconds": int_range(MIN_POLL_SECONDS, 3600),
    "general.offline_after_polls": int_range(1, 20),
    "appearance.font_scale": float_range(1.0, 2.0),
    "appearance.theme": choice("system", "light", "dark"),
    "quiet_hours.from": hhmm,
    "quiet_hours.to": hhmm,
    "notifications.soc_below[].pct": int_range(1, 99),
    "notifications.soc_below[].priority": choice("normal", "critical"),
    "notifications.soc_reached.pct": int_range(50, 100),
    "notifications.backup_left.minutes": int_range(5, 600),
    "notifications.temperature.high": int_range(20, 80),
    "notifications.temperature.low": int_range(-20, 20),
    "telegram.chat_id": id_text,
    "telegram.user_id": id_text,
    "advanced.power_sign": choice("plus_is_charging", "minus_is_charging"),
    "advanced.counter_unit": choice("Wh", "0.1Wh", "0.01kWh", "kWh"),
    "advanced.rearm_pct": int_range(0, 20),
    "advanced.rearm_c": int_range(0, 20),
    "advanced.reserve_soc_pct": int_range(0, 50),
    "advanced.inverter_efficiency_pct": int_range(50, 100),
    "advanced.samples_retention_days": int_range(1, 365),
    "advanced.log_level": choice("DEBUG", "INFO", "WARNING", "ERROR"),
}
SUFFIX_VALIDATORS: dict[str, Validator] = {".repeat_min": int_range(0, 1440)}


def _validator_for(path: str, default: Any) -> Validator:
    if path in VALIDATORS:
        return VALIDATORS[path]
    for suffix, validator in SUFFIX_VALIDATORS.items():
        if path.endswith(suffix):
            return validator
    if isinstance(default, bool):
        return boolean
    if isinstance(default, str):
        return text
    if _is_num(default):
        return same_number
    return lambda value: value


def _merge(default: Any, value: Any, path: str) -> Any:
    if isinstance(default, dict):
        result = dict(value) if isinstance(value, dict) else {}
        for key, default_value in default.items():
            sub = f"{path}.{key}" if path else key
            result[key] = _merge(default_value, result[key], sub) if key in result else copy.deepcopy(default_value)
        return result
    if isinstance(default, list):
        if not isinstance(value, list) or not default:
            return copy.deepcopy(default)
        template = default[0]
        items = [_merge(template, item, path + "[]") for item in value[:MAX_SOC_LEVELS] if isinstance(item, dict)]
        return items or copy.deepcopy(default)
    try:
        return _validator_for(path, default)(value)
    except (ValueError, TypeError) as exc:
        log.warning("Invalid setting %s=%r (%s); using default", path, value, exc)
        return copy.deepcopy(default)


def defaults() -> dict:
    return copy.deepcopy(DEFAULTS)


def _migrate(data: dict) -> dict:
    """Schema 1 -> 2: the power sign default was a guess; the device showed that negative means charging.
    A schema-1 file still holding the old default gets the verified value; later explicit choices are kept."""
    schema = data.get("schema", 1)
    advanced = data.get("advanced")
    if (isinstance(schema, int) and schema < 2 and isinstance(advanced, dict)
            and advanced.get("power_sign") == "plus_is_charging"):
        data = copy.deepcopy(data)
        data["advanced"]["power_sign"] = "minus_is_charging"
    return data


def validate(data: Any) -> dict:
    result = _merge(DEFAULTS, _migrate(data) if isinstance(data, dict) else {}, "")
    result["schema"] = SCHEMA
    return result


def load(path: Path) -> tuple[dict, str | None]:
    if not path.exists():
        return defaults(), None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("settings root is not an object")
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        broken = path.with_name(f"settings.broken-{time.strftime('%Y%m%d-%H%M%S')}.json")
        log.error("Settings file is damaged (%s); moved to %s", exc, broken.name)
        try:
            path.replace(broken)
        except OSError:
            log.exception("Could not move the damaged settings file")
        return defaults(), "sys.settings_broken"
    return validate(data), None


def save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
