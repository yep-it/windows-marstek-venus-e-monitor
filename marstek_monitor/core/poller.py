"""One poll cycle against the battery (spec §6.3). No Qt; the loop lives in poller_thread.py."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from ..api.client import (
    ApiError,
    ApiTimeout,
    ClientStopped,
    DeviceInfo,
    MarstekClient,
    PortInUseError,
    broadcast_addresses,
    local_ip_for,
)
from .snapshot import NormalizeConfig, Snapshot, normalize

log = logging.getLogger(__name__)

STATUS_METHODS = ("Bat.GetStatus", "ES.GetStatus")


@dataclass
class PollerConfig:
    ip: str
    port: int
    ble_mac: str = ""
    local_port: int | None = None
    local_ip: str | None = None
    poll_seconds: int = 60
    offline_after_polls: int = 3
    normalize: NormalizeConfig = field(default_factory=NormalizeConfig)
    query_spacing_s: float = 1.0
    timeout_s: float = 5.0
    discovery_wait_s: float = 3.0
    broadcast: tuple[str, ...] | None = None


@dataclass
class PollResult:
    ts: float
    snapshot: Snapshot | None
    online: bool
    gap: tuple[float, float] | None = None
    device: DeviceInfo | None = None
    error_key: str | None = None
    error_params: dict = field(default_factory=dict)


class Poller:
    WIFI_EVERY = 10
    DEVICE_EVERY = 60

    def __init__(self, cfg: PollerConfig, client_factory: Callable[..., MarstekClient] = MarstekClient,
                 clock: Callable[[], float] = time.time, raw_recorder: Callable[[dict], None] | None = None):
        self.cfg = cfg
        self._factory = client_factory
        self._clock = clock
        self._raw = raw_recorder
        self.ip: str | None = cfg.ip or None
        self.ble_mac = cfg.ble_mac
        self.device: DeviceInfo | None = None
        self._client = None
        self._cycle = 0
        self._failures = 0
        self._last_ts: float | None = None
        self._ever_replied = False
        self._discover_requested = False
        self._stop = threading.Event()

    @property
    def online(self) -> bool:
        return self._failures < self.cfg.offline_after_polls

    def request_discovery(self) -> None:
        self._discover_requested = True

    def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            self._client.stop()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def cycle(self) -> PollResult:
        try:
            result = self._cycle_once()
        except ClientStopped:
            raise
        except Exception:
            log.exception("Poll cycle failed")
            self._failures += 1
            result = PollResult(ts=self._clock(), snapshot=None, online=self.online, device=self.device)
        if not self.online:
            self.close()  # reopen next cycle with a freshly chosen local interface
        return result

    def _cycle_once(self) -> PollResult:
        now = self._clock()
        gap = None
        if self._last_ts is not None and now - self._last_ts > 3 * self.cfg.poll_seconds:
            gap = (self._last_ts, now)
            if self.online:
                self._failures = 0  # failures before the sleep don't count
        self._last_ts = now

        try:
            client = self._ensure_client()
        except PortInUseError:
            port = self.cfg.local_port or self.cfg.port
            return PollResult(ts=now, snapshot=None, online=self.online, gap=gap, device=self.device,
                              error_key="sys.port_in_use", error_params={"port": port})
        except OSError as exc:
            log.warning("Cannot open the UDP socket: %s", exc)
            return PollResult(ts=now, snapshot=None, online=self.online, gap=gap, device=self.device,
                              error_key="sys.network_error", error_params={"error": str(exc)})

        if self._discover_requested or self.ip is None or not self.online:
            self._discover_requested = False
            self._discover(client)
        elif self.device is None or self._cycle % self.DEVICE_EVERY == 0:
            self._read_device(client)

        raw: dict[str, dict | None] = {}
        failed: list[str] = []
        methods = list(STATUS_METHODS)
        if self._cycle % self.WIFI_EVERY == 0:
            methods.append("Wifi.GetStatus")
        if self.ip:
            for i, method in enumerate(methods):
                if i and self._stop.wait(self.cfg.query_spacing_s):
                    break
                try:
                    raw[method] = client.call(self.ip, method)
                except (ApiTimeout, ApiError) as exc:
                    failed.append(method)
                    log.info("%s failed: %s", method, exc)

        responded = any(raw.get(m) for m in STATUS_METHODS)
        if responded:
            self._failures = 0
            self._ever_replied = True
        elif gap is None:
            self._failures += 1
        self._cycle += 1

        snapshot = normalize(now, raw, self.cfg.normalize,
                             fw_version=self.device.ver if self.device else None,
                             ip=self.ip, failed=tuple(failed))
        error_key = "sys.firewall_hint" if not self._ever_replied and not self.online else None
        return PollResult(ts=now, snapshot=snapshot, online=self.online, gap=gap,
                          device=self.device, error_key=error_key)

    def _ensure_client(self):
        if self._client is None:
            local_ip = self.cfg.local_ip or local_ip_for(self.ip or "8.8.8.8")
            client = self._factory(local_ip=local_ip, local_port=self.cfg.local_port or self.cfg.port,
                                   device_port=self.cfg.port, timeout=self.cfg.timeout_s, retries=1,
                                   raw_recorder=self._raw)
            client.open()
            self._client = client
        return self._client

    def _discover(self, client) -> None:
        addresses = list(self.cfg.broadcast) if self.cfg.broadcast else broadcast_addresses(client.local_ip)
        try:
            found = client.discover(addresses, wait=self.cfg.discovery_wait_s)
        except (OSError, ApiTimeout) as exc:
            log.warning("Discovery failed: %s", exc)
            return
        match = None
        if self.ble_mac:
            match = next((d for d in found if d.ble_mac == self.ble_mac), None)
        elif found:
            match = found[0]
        if match is not None:
            if match.ip != self.ip:
                log.info("Battery found at %s", match.ip)
            self.device, self.ip, self.ble_mac = match, match.ip, match.ble_mac

    def _read_device(self, client) -> None:
        try:
            result = client.call(self.ip, "Marstek.GetDevice", {"ble_mac": "0"})
        except (ApiTimeout, ApiError):
            return
        self.device = DeviceInfo.from_result(result, fallback_ip=self.ip)
        if not self.ble_mac:
            self.ble_mac = self.device.ble_mac
