"""UI strings (spec §6.10): one JSON table per language, English fallback."""
from __future__ import annotations

import json
from importlib import resources

SUPPORTED = ("en", "uk")
_language = "en"
_tables: dict[str, dict[str, str]] = {}


def _table(lang: str) -> dict[str, str]:
    if lang not in _tables:
        text = resources.files(__name__).joinpath(f"{lang}.json").read_text(encoding="utf-8")
        _tables[lang] = json.loads(text)
    return _tables[lang]


def set_language(lang: str) -> None:
    global _language
    _language = lang if lang in SUPPORTED else "en"


def language() -> str:
    return _language


def tr(key: str, **params) -> str:
    text = _table(_language).get(key) or _table("en").get(key) or key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes = max(0, int(round(seconds / 60)))
    hours, minutes = divmod(minutes, 60)
    return tr("dur.hm", h=hours, m=minutes) if hours else tr("dur.m", m=minutes)


def _decimal(text: str) -> str:
    return text.replace(".", tr("num.decimal"))


def fmt_kwh(wh: float | None, digits: int = 1) -> str:
    return "—" if wh is None else _decimal(f"{wh / 1000:.{digits}f}")


def fmt_kw(w: float | None) -> str:
    return "—" if w is None else tr("unit.kw", v=_decimal(f"{abs(w) / 1000:.2f}"))


def fmt_power(w: float | None) -> str:
    if w is None:
        return "—"
    return tr("unit.w", v=f"{abs(w):,.0f}".replace(",", " "))
