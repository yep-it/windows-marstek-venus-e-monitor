import socket
import threading
import time

import pytest

from marstek_monitor.api.client import (
    ALLOWED_METHODS,
    ApiError,
    ApiTimeout,
    ClientStopped,
    DeviceInfo,
    ForbiddenMethodError,
    MarstekClient,
    PortInUseError,
    broadcast_addresses,
    clean_ip,
)
from tests.fakes.fake_battery import FakeBattery
from tests.fakes.net import free_udp_port


@pytest.fixture
def battery():
    with FakeBattery() as fake:
        yield fake


@pytest.fixture
def client(battery):
    c = MarstekClient("127.0.0.1", free_udp_port(), battery.port, timeout=0.4, retries=1)
    c.open()
    yield c
    c.close()


@pytest.mark.parametrize(
    "method",
    ["ES.SetMode", "DOD.SET", "Reset.Factory", "Led.Ctrl", "Ble.Adv", "Set.Ver", "ES.GetMode", "BLE.GetStatus"],
)
def test_non_allowlisted_method_is_refused_before_sending(client, battery, method):
    with pytest.raises(ForbiddenMethodError):
        client.call("127.0.0.1", method)
    time.sleep(0.3)
    assert battery.received == []


def test_allowlist_contains_only_getters():
    assert ALLOWED_METHODS == {
        "Marstek.GetDevice", "Wifi.GetStatus", "Bat.GetStatus", "ES.GetStatus", "EM.GetStatus",
    }


def test_call_returns_result(client):
    result = client.call("127.0.0.1", "Bat.GetStatus")
    assert result["soc"] == 100
    assert result["rated_capacity"] == 5120.0


def test_timeout_retries_once_then_raises(client, battery):
    battery.mode["Bat.GetStatus"] = "timeout"
    with pytest.raises(ApiTimeout):
        client.call("127.0.0.1", "Bat.GetStatus")
    assert battery.methods_received().count("Bat.GetStatus") == 2


@pytest.mark.parametrize("mode", ["garbage", "wrong_id"])
def test_garbage_and_wrong_id_are_ignored(client, battery, mode):
    battery.mode["ES.GetStatus"] = mode
    with pytest.raises(ApiTimeout):
        client.call("127.0.0.1", "ES.GetStatus")


def test_error_response_raises_api_error(client, battery):
    battery.mode["Wifi.GetStatus"] = "error"
    with pytest.raises(ApiError) as info:
        client.call("127.0.0.1", "Wifi.GetStatus")
    assert info.value.code == -32603


def test_discover_finds_device(client):
    found = client.discover(["127.0.0.1"], wait=0.5)
    assert len(found) == 1
    assert found[0].ble_mac == "0123456789ab"
    assert found[0].ip == "127.0.0.1"
    assert found[0].ver == 144


def test_discover_uses_the_sender_address_not_the_reported_one(client, battery):
    # The real battery (VenusE 3.0, fw 144, on a LAN cable) reported its address with zero-padded parts.
    battery.results["Marstek.GetDevice"]["ip"] = "192.168.01.020"
    found = client.discover(["127.0.0.1"], wait=0.5)
    assert found[0].ip == "127.0.0.1"


def test_device_info_drops_leading_zeros_from_the_reported_ip():
    info = DeviceInfo.from_result({"ip": "192.168.01.020"}, fallback_ip="10.0.0.1")
    assert info.ip == "192.168.1.20"


@pytest.mark.parametrize("value, expected", [
    ("192.168.01.020", "192.168.1.20"),
    (" 192.168.1.20 ", "192.168.1.20"),
    ("010.001.000.007", "10.1.0.7"),
    ("", ""),
    ("battery.local", "battery.local"),
    ("192.168.1.256", "192.168.1.256"),
])
def test_clean_ip(value, expected):
    assert clean_ip(value) == expected


def test_port_in_use_is_reported(battery):
    port = free_udp_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", port))
    try:
        with pytest.raises(PortInUseError):
            MarstekClient("127.0.0.1", port, battery.port).open()
    finally:
        blocker.close()


def test_raw_recorder_receives_responses(battery):
    records = []
    c = MarstekClient("127.0.0.1", free_udp_port(), battery.port, timeout=0.4, raw_recorder=records.append)
    c.open()
    try:
        c.call("127.0.0.1", "Bat.GetStatus")
    finally:
        c.close()
    assert records[0]["method"] == "Bat.GetStatus"
    assert records[0]["response"]["result"]["soc"] == 100


def test_stop_interrupts_a_waiting_call(client, battery):
    client.timeout = 5.0
    battery.mode["Bat.GetStatus"] = "timeout"
    threading.Timer(0.3, client.stop).start()
    started = time.monotonic()
    with pytest.raises(ClientStopped):
        client.call("127.0.0.1", "Bat.GetStatus")
    assert time.monotonic() - started < 1.5


def test_broadcast_addresses():
    assert broadcast_addresses("192.168.1.10") == ["192.168.1.255", "255.255.255.255"]
    assert broadcast_addresses("127.0.0.1") == ["255.255.255.255"]


class _ResettingSocket:
    """Wraps a real socket; recvfrom fails like WSAENETRESET after a network change."""

    def __init__(self, sock):
        self._sock = sock

    def sendto(self, data, addr):
        return self._sock.sendto(data, addr)

    def recvfrom(self, size):
        raise OSError(10052, "network dropped the connection on reset")

    def close(self):
        self._sock.close()


def test_unexpected_socket_error_becomes_a_timeout(client):
    client._sock = _ResettingSocket(client._sock)
    with pytest.raises(ApiTimeout):
        client.call("127.0.0.1", "Bat.GetStatus")
