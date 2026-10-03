"""Read-only client for the Marstek Local API (JSON-RPC over UDP).

The device answers to the *source port* of a request, so the socket binds to the
device's API port (see spec §3). Only the methods in ALLOWED_METHODS can ever be sent.
"""
from __future__ import annotations

import errno
import itertools
import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

log = logging.getLogger(__name__)

# The ONLY methods this app may ever send. Everything else is refused before sending.
ALLOWED_METHODS = frozenset({
    "Marstek.GetDevice",
    "Wifi.GetStatus",
    "Bat.GetStatus",
    "ES.GetStatus",
    "EM.GetStatus",
})

_PORT_IN_USE_CODES = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


class ForbiddenMethodError(Exception):
    pass


class ApiError(Exception):
    def __init__(self, code, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ApiTimeout(Exception):
    pass


class PortInUseError(Exception):
    pass


class ClientStopped(Exception):
    pass


@dataclass(frozen=True)
class DeviceInfo:
    device: str
    ver: int | None
    ble_mac: str
    wifi_mac: str
    ip: str

    @classmethod
    def from_result(cls, result: dict, fallback_ip: str) -> "DeviceInfo":
        ver = result.get("ver")
        return cls(
            device=str(result.get("device", "")),
            ver=int(ver) if isinstance(ver, (int, float)) and not isinstance(ver, bool) else None,
            ble_mac=str(result.get("ble_mac", "")),
            wifi_mac=str(result.get("wifi_mac", "")),
            ip=clean_ip(str(result.get("ip") or "")) or fallback_ip,
        )


def clean_ip(value: str) -> str:
    """Drop leading zeros ("192.168.01.020" -> "192.168.1.20"); Windows can't send to such an address.

    Anything that isn't four numbers 0-255 is returned unchanged (only stripped).
    """
    value = value.strip()
    parts = value.split(".")
    if len(parts) == 4 and all(p.isdigit() and int(p) <= 255 for p in parts):
        return ".".join(str(int(p)) for p in parts)
    return value


def local_ip_for(target_ip: str) -> str:
    """IP of the local interface that routes to target_ip (no packet is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target_ip, 9))
        return sock.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        sock.close()


def broadcast_addresses(local_ip: str) -> list[str]:
    """Subnet broadcast (assuming a /24 home network) plus the limited broadcast."""
    addresses = []
    parts = local_ip.split(".")
    if len(parts) == 4 and local_ip != "0.0.0.0" and not local_ip.startswith("127."):
        addresses.append(".".join(parts[:3] + ["255"]))
    addresses.append("255.255.255.255")
    return addresses


class MarstekClient:
    POLL_SLICE = 0.25  # seconds; keeps stop() responsive

    def __init__(
        self,
        local_ip: str,
        local_port: int,
        device_port: int,
        timeout: float = 5.0,
        retries: int = 1,
        raw_recorder: Callable[[dict], None] | None = None,
    ):
        self.local_ip = local_ip
        self.local_port = local_port
        self.device_port = device_port
        self.timeout = timeout
        self.retries = retries
        self.raw_recorder = raw_recorder
        self._ids = itertools.count(1)
        self._sock: socket.socket | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def open(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.bind((self.local_ip, self.local_port))
        except OSError as exc:
            sock.close()
            code = getattr(exc, "winerror", None) or exc.errno
            if code in _PORT_IN_USE_CODES:
                raise PortInUseError(f"UDP port {self.local_port} is used by another program") from exc
            raise
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            # Windows: don't turn ICMP "port unreachable" into errors on later reads.
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        sock.settimeout(self.POLL_SLICE)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def stop(self) -> None:
        self._stop.set()

    def call(self, ip: str, method: str, params: dict | None = None) -> dict:
        if method not in ALLOWED_METHODS:
            raise ForbiddenMethodError(f"{method} is not allowed (read-only client)")
        if params is None:
            params = {"id": 0}
        last_error: ApiTimeout | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._request(ip, method, params)
            except ApiTimeout as exc:
                last_error = exc
                log.info("%s timed out (attempt %d)", method, attempt + 1)
        assert last_error is not None
        raise last_error

    def discover(self, addresses: list[str], wait: float = 3.0) -> list[DeviceInfo]:
        sock = self._require_open()
        rid = next(self._ids)
        payload = json.dumps(
            {"id": rid, "method": "Marstek.GetDevice", "params": {"ble_mac": "0"}}
        ).encode()
        found: dict[str, DeviceInfo] = {}
        with self._lock:
            for address in addresses:
                try:
                    sock.sendto(payload, (address, self.device_port))
                except OSError as exc:
                    log.warning("Discovery send to %s failed: %s", address, exc)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                received = self._recv(sock)
                if received is None:
                    continue
                msg, addr = received
                if msg.get("id") != rid or not isinstance(msg.get("result"), dict):
                    continue
                self._record("Marstek.GetDevice", msg)
                # The address the reply came from, not the one it reports: on a LAN cable
                # the battery reported its address with zero-padded parts ("192.168.01.020").
                info = replace(DeviceInfo.from_result(msg["result"], fallback_ip=addr[0]), ip=addr[0])
                found[info.ble_mac or info.ip] = info
        return list(found.values())

    # -- internals ---------------------------------------------------------

    def _require_open(self) -> socket.socket:
        if self._sock is None:
            raise RuntimeError("client is not open")
        return self._sock

    def _request(self, ip: str, method: str, params: dict) -> dict:
        sock = self._require_open()
        rid = next(self._ids)
        payload = json.dumps({"id": rid, "method": method, "params": params}).encode()
        with self._lock:
            try:
                sock.sendto(payload, (ip, self.device_port))
            except OSError as exc:  # e.g. network unreachable while Wi-Fi reconnects
                raise ApiTimeout(f"{method}: send failed: {exc}") from exc
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                received = self._recv(sock)
                if received is None:
                    continue
                msg, _addr = received
                if msg.get("id") != rid or ("result" not in msg and "error" not in msg):
                    continue
                self._record(method, msg)
                if "error" in msg:
                    err = msg.get("error") or {}
                    raise ApiError(err.get("code"), str(err.get("message", "")))
                return msg["result"]
        raise ApiTimeout(f"{method}: no reply within {self.timeout}s")

    def _recv(self, sock: socket.socket) -> tuple[dict, tuple] | None:
        if self._stop.is_set():
            raise ClientStopped()
        try:
            data, addr = sock.recvfrom(65535)
        except (socket.timeout, ConnectionResetError):
            return None
        except OSError as exc:
            if self._stop.is_set():
                raise ClientStopped()
            raise ApiTimeout(f"socket error: {exc}") from exc
        try:
            msg = json.loads(data.decode("utf-8", errors="replace"))
        except ValueError:
            log.warning("Ignoring non-JSON datagram from %s", addr)
            return None
        return (msg, addr) if isinstance(msg, dict) else None

    def _record(self, method: str, msg: dict) -> None:
        if self.raw_recorder is not None:
            try:
                self.raw_recorder({"ts": time.time(), "method": method, "response": msg})
            except Exception:  # recording must never break polling
                log.exception("Raw recorder failed")
