import socket

import pytest

from marstek_monitor.api.client import ApiTimeout, DeviceInfo
from marstek_monitor.core.poller import Poller, PollerConfig
from marstek_monitor.core.poller_thread import PollerThread
from tests.fakes.fake_battery import FakeBattery, load_fixture
from tests.fakes.net import free_udp_port

FIX = {m: r["result"] for m, r in load_fixture().items()}


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def battery():
    with FakeBattery() as fake:
        yield fake


def config(battery, **kw):
    base = dict(ip="127.0.0.1", port=battery.port, local_port=free_udp_port(), local_ip="127.0.0.1",
                query_spacing_s=0, timeout_s=0.3, discovery_wait_s=0.3, broadcast=("127.0.0.1",))
    base.update(kw)
    return PollerConfig(**base)


def make(battery, clock=None, **kw):
    return Poller(config(battery, **kw), clock=clock or Clock())


def test_cycle_reads_status_and_device(battery):
    p = make(battery)
    try:
        r = p.cycle()
    finally:
        p.close()
    assert r.online is True and r.error_key is None
    assert r.snapshot.soc_pct == 100 and r.snapshot.rssi_dbm == -49
    assert r.device.ble_mac == "0123456789ab" and r.snapshot.fw_version == 144
    assert battery.methods_received() == ["Marstek.GetDevice", "Bat.GetStatus", "ES.GetStatus", "Wifi.GetStatus"]


def test_wifi_only_every_tenth_cycle(battery):
    clock = Clock()
    p = make(battery, clock)
    try:
        for _ in range(11):
            p.cycle()
            clock.t += 60
    finally:
        p.close()
    assert battery.methods_received().count("Wifi.GetStatus") == 2


def test_goes_offline_after_three_failed_cycles(battery):
    clock = Clock()
    p = make(battery, clock)
    battery.mode.update({"Bat.GetStatus": "timeout", "ES.GetStatus": "timeout"})
    flags = []
    try:
        for _ in range(3):
            flags.append(p.cycle().online)
            clock.t += 60
    finally:
        p.close()
    assert flags == [True, True, False]


def test_failures_right_after_resume_do_not_alarm(battery):
    clock = Clock()
    p = make(battery, clock)
    try:
        assert p.cycle().online is True
        battery.mode.update({"Bat.GetStatus": "timeout", "ES.GetStatus": "timeout"})
        clock.t += 10_000  # the PC slept
        first = p.cycle()
        assert first.gap is not None and first.online is True
        flags = []
        for _ in range(3):
            clock.t += 60
            flags.append(p.cycle().online)
    finally:
        p.close()
    assert flags == [True, True, False]


def test_discovers_and_adopts_device_when_ip_unknown(battery):
    p = make(battery, ip="", ble_mac="")
    try:
        r = p.cycle()
    finally:
        p.close()
    assert p.ip == "127.0.0.1" and p.ble_mac == "0123456789ab"
    assert r.snapshot.soc_pct == 100


def test_port_in_use_is_reported(battery):
    cfg = config(battery)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", cfg.local_port))
    try:
        r = Poller(cfg, clock=Clock()).cycle()
    finally:
        blocker.close()
    assert r.error_key == "sys.port_in_use" and r.error_params == {"port": cfg.local_port}
    assert r.snapshot is None


def test_firewall_hint_when_battery_never_answers(battery):
    clock = Clock()
    for method in ("Marstek.GetDevice", "Bat.GetStatus", "ES.GetStatus", "Wifi.GetStatus"):
        battery.mode[method] = "timeout"
    p = make(battery, clock)
    results = []
    try:
        for _ in range(3):
            results.append(p.cycle())
            clock.t += 60
    finally:
        p.close()
    assert [r.error_key for r in results] == [None, None, "sys.firewall_hint"]


class ScriptedClient:
    """In-memory client: `devices` maps ip -> method results."""

    devices: dict[str, dict] = {}

    def __init__(self, **kwargs):
        self.local_ip = kwargs["local_ip"]

    def open(self):
        pass

    def close(self):
        pass

    def stop(self):
        pass

    def call(self, ip, method, params=None):
        if ip not in self.devices:
            raise ApiTimeout(method)
        return self.devices[ip][method]

    def discover(self, addresses, wait=3.0):
        return [DeviceInfo.from_result(dict(r["Marstek.GetDevice"], ip=ip), ip) for ip, r in self.devices.items()]


def test_rediscovers_new_ip_by_ble_mac():
    ScriptedClient.devices = {"192.168.1.77": FIX}
    clock = Clock()
    cfg = PollerConfig(ip="192.168.1.20", port=30000, ble_mac="0123456789ab", local_ip="192.168.1.10",
                       query_spacing_s=0, broadcast=("192.168.1.255",))
    p = Poller(cfg, client_factory=ScriptedClient, clock=clock)
    flags = []
    for _ in range(4):
        flags.append(p.cycle().online)
        clock.t += 60
    assert flags == [True, True, False, True]
    assert p.ip == "192.168.1.77"


def test_request_discovery_runs_discovery_next_cycle():
    ScriptedClient.devices = {"192.168.1.50": FIX}
    cfg = PollerConfig(ip="192.168.1.50", port=30000, local_ip="192.168.1.10", query_spacing_s=0)
    p = Poller(cfg, client_factory=ScriptedClient, clock=Clock())
    p.cycle()
    ScriptedClient.devices = {"192.168.1.51": FIX}
    p.request_discovery()
    p.cycle()
    assert p.ip == "192.168.1.51"


def test_thread_emits_results_and_stops_quickly(qtbot, battery):
    thread = PollerThread(make(battery), interval_s=60)
    with qtbot.waitSignal(thread.result, timeout=5000) as blocker:
        thread.start()
    assert blocker.args[0].snapshot.soc_pct == 100
    thread.stop()
    assert thread.wait(2000)
