import time

import pytest
from PySide6.QtGui import QColor, QPalette

from marstek_monitor.core.monitor import LiveState
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.ui import theme
from marstek_monitor.ui.tray import Tray, make_icon, render_tile
from marstek_monitor.ui.widgets import Card, Segmented


@pytest.fixture
def light(qapp):
    theme.apply(qapp, "light", 1.0)
    yield qapp
    theme.apply(qapp, "light", 1.0)


def test_dark_palette_and_font_scale(light):
    base = theme.base_point_size()
    theme.apply(light, "dark", 1.5)
    assert light.palette().color(QPalette.ColorRole.Window).name() == "#202124"
    assert light.font().pointSizeF() == pytest.approx(base * 1.5)


def test_tile_pixels(light):
    pm = render_tile("87", "#2ea043", 32)
    assert (pm.width(), pm.height()) == (32, 32)
    assert QColor(pm.toImage().pixel(16, 2)).name() == "#2ea043"
    offline = render_tile(None, "#8b949e", 16)
    assert QColor(offline.toImage().pixel(8, 1)).name() == "#8b949e"


def test_icon_has_several_sizes(light):
    sizes = {s.width() for s in make_icon("100", "#8b949e").availableSizes()}
    assert {16, 32, 64} <= sizes


def test_tray_tooltip_and_icon_update(light):
    tray = Tray()
    state = LiveState(snapshot=Snapshot(ts=time.time(), responded=True, soc_pct=64, power_w=-850.0),
                      last_update_ts=time.time())
    tray.update_state(state, time.time())
    assert tray.icon.toolTip().startswith("Marstek Venus E · 64%")


def test_card_and_segmented(qtbot, light):
    card = Card("Mode")
    qtbot.addWidget(card)
    card.set("42", "")
    assert card.value.text() == "42" and card.sub.isHidden()
    seg = Segmented([("a", "A"), ("b", "B")])
    qtbot.addWidget(seg)
    assert seg.value() == "a"
    with qtbot.waitSignal(seg.changed) as blocker:
        seg.group.button(1).click()
    assert blocker.args == ["b"] and seg.value() == "b"
