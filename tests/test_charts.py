from datetime import date

from marstek_monitor.core.energy import EnergyBar
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.ui.charts import BarChart, LiveChart, nice_max, split_segments


def snap(ts, soc=50, power=0.0):
    return Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power)


def test_nice_max():
    assert nice_max(0) == 1.0
    assert nice_max(3.2) == 5
    assert nice_max(0.46) == 0.5
    assert nice_max(12) == 20


def test_split_segments():
    samples = [snap(0), snap(60), snap(120), snap(1000), snap(1060)]
    assert [len(seg) for seg in split_segments(samples, 180)] == [3, 2]
    assert split_segments([], 180) == []


def test_bar_chart_hit_testing_and_paint(qtbot):
    chart = BarChart()
    qtbot.addWidget(chart)
    chart.resize(400, 240)
    bars = [EnergyBar(date(2026, 10, d), date(2026, 10, d), 1000.0 * d, 500.0, d == 3) for d in range(1, 5)]
    chart.set_bars(bars, ["1", "2", "3", "4"], ["t1", "t2", "t3", "t4"])
    r = chart.plot_rect()
    assert chart.slot_at(r.left() + 1) == 0
    assert chart.slot_at(r.right() - 1) == 3
    assert chart.slot_at(0) is None
    assert not chart.grab().isNull()


def test_live_chart_paints_with_gaps(qtbot):
    chart = LiveChart()
    qtbot.addWidget(chart)
    chart.resize(500, 260)
    samples = [snap(0, 90, -800), snap(60, 89, -800), snap(900, 88, 1200), snap(960, 90, 1200)]
    chart.set_data(samples, 0, 1000, [30], 180, lambda s: f"{s.soc_pct}")
    assert len(chart._samples) == 4
    assert not chart.grab().isNull()
