import time

import pytest
from PySide6.QtGui import QColor, QPalette

from marstek_monitor.core.monitor import LiveState
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.ui import theme
from marstek_monitor.ui.tray import Tray, fill_color, make_battery_icon, make_icon, render_battery, render_tile
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


YELLOW = "#ffd33d"


def colors_in(pixmap):
    image = pixmap.toImage()
    found = {}
    for x in range(image.width()):
        for y in range(image.height()):
            c = QColor(image.pixelColor(x, y))
            if c.alpha() == 255:
                found[c.name()] = found.get(c.name(), 0) + 1
    return found


def test_fill_color_by_level():
    assert fill_color(100) == fill_color(41) == "#2ea043"
    assert fill_color(40) == fill_color(20) == "#f0883e"
    assert fill_color(19) == fill_color(0) == "#e5534b"


def test_battery_fill_follows_the_level(light):
    full = render_battery("normal", 100, 32).toImage()
    low = render_battery("normal", 10, 32).toImage()
    assert QColor(full.pixelColor(16, 12)).name() == "#2ea043"   # upper body is filled when full
    assert QColor(low.pixelColor(16, 12)).alpha() == 0          # ...and empty when nearly empty
    assert QColor(low.pixelColor(16, 28)).name() == "#e5534b"   # red fill at the bottom


def yellowish(pixmap):
    image = pixmap.toImage()
    count = 0
    for x in range(image.width()):
        for y in range(image.height()):
            c = image.pixelColor(x, y)
            if c.alpha() > 200 and c.red() > 200 and c.green() > 150 and c.blue() < 120:
                count += 1
    return count


def test_charging_shows_a_bolt(light):
    assert yellowish(render_battery("charging", 50, 32)) > 10
    assert yellowish(render_battery("normal", 50, 32)) == 0


def test_offline_and_error_have_no_fill(light):
    for kind in ("offline", "error", "unknown"):
        found = colors_in(render_battery(kind, None, 32))
        assert found.get("#2ea043", 0) == 0 and found.get(YELLOW, 0) == 0
    assert colors_in(render_battery("error", None, 32)).get("#e5534b", 0) > 10


def test_battery_icon_sizes(light):
    sizes = {s.width() for s in make_battery_icon("normal", 50).availableSizes()}
    assert {16, 24, 32} <= sizes


def test_bolt_leaves_the_fill_visible_beside_it(light):
    image = render_battery("charging", 100, 32).toImage()
    y = 18  # middle of the body
    assert QColor(image.pixelColor(10, y)).name() == "#2ea043"   # left of the bolt
    assert QColor(image.pixelColor(22, y)).name() == "#2ea043"   # right of the bolt


def test_outline_is_thin_compared_to_the_fill(light):
    found = colors_in(render_battery("normal", 100, 32))
    assert found.get("#2ea043", 0) > 2 * found.get("#ffffff", 0)


def test_outage_has_a_red_outline_and_keeps_the_fill(light):
    image = render_battery("outage", 100, 32).toImage()
    assert QColor(image.pixelColor(16, 12)).name() == "#2ea043"  # the charge level stays visible
    found = colors_in(render_battery("outage", 100, 32))
    assert found.get("#e5534b", 0) > 10 and found.get("#ffffff", 0) == 0  # red outline instead of white
