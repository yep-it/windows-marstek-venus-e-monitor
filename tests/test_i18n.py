import json
import string
from pathlib import Path

import pytest

from marstek_monitor import i18n

I18N_DIR = Path(i18n.__file__).parent


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def load(lang):
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def placeholders(text):
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_languages_have_the_same_keys():
    assert set(load("en")) == set(load("uk"))


def test_placeholders_match_between_languages():
    en, uk = load("en"), load("uk")
    mismatched = [k for k in en if placeholders(en[k]) != placeholders(uk[k])]
    assert mismatched == []


def test_tr_formats_and_falls_back():
    assert i18n.tr("n.soc_below.title", pct=40) == "Battery below 40%"
    assert i18n.tr("no.such.key") == "no.such.key"
    assert i18n.tr("n.soc_below.title") == "Battery below {pct}%"
    assert i18n.tr("n.soc_below.title", wrong=1) == "Battery below {pct}%"


def test_unknown_language_falls_back_to_english():
    i18n.set_language("de")
    assert i18n.language() == "en"


def test_ukrainian():
    i18n.set_language("uk")
    assert i18n.tr("tab.now") == "Зараз"
    assert i18n.fmt_duration(125 * 60) == "2 год 5 хв"
    assert i18n.fmt_kwh(4450) == "4,5"


def test_formatters():
    assert i18n.fmt_duration(None) == "—"
    assert i18n.fmt_duration(0) == "0 min"
    assert i18n.fmt_duration(125 * 60) == "2 h 5 min"
    assert i18n.fmt_duration(59) == "1 min"
    assert i18n.fmt_kwh(4450) == "4.5"
    assert i18n.fmt_kwh(None) == "—"
    assert i18n.fmt_power(1450) == "1 450 W"
    assert i18n.fmt_power(-850.4) == "850 W"
    assert i18n.fmt_kw(1700) == "1.70 kW"
