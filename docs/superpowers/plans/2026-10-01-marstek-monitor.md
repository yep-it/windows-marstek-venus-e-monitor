# Marstek Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only Windows tray application (`MarstekMonitor.exe`) that monitors a Marstek Venus E 3.0 battery over its Local API. It shows the state in the tray and a status window, keeps local session and energy history, and sends desktop and Telegram notifications.

**Architecture:** A single Python 3.13 process using PySide6.
- A background poller thread talks UDP JSON-RPC to the battery through a client with a hard read-only allowlist.
- Every poll result goes through a Qt-free pipeline (`core/monitor.py`) on the main thread: normalization → SQLite storage → session detection → outage heuristic → rules engine → quiet-hours routing.
- The UI (tray, status window, settings) and the notifiers (desktop toast, Telegram worker thread) only consume the pipeline's `LiveState` and `Event`s.

**Tech Stack:** Python 3.13, PySide6 ≥ 6.7 (Widgets, Network), stdlib `sqlite3` / `socket` / `urllib` / `winreg` / `ctypes`, pytest + pytest-qt, PyInstaller ≥ 6.10.

**Spec:** `docs/superpowers/specs/2026-10-01-marstek-tray-design.md`

## Global Constraints

- Python 3.13 on Windows 11. The only runtime dependency is `PySide6>=6.7`. HTTP uses stdlib `urllib`. Dev-only: `pytest>=8`, `pytest-qt>=4.4`, `pyinstaller>=6.10`.
- **Read-only:** the only API methods ever sent are `Marstek.GetDevice`, `Wifi.GetStatus`, `Bat.GetStatus`, `ES.GetStatus`, `EM.GetStatus`. `ES.GetMode` is excluded, and no `Set*`/`Reset*`/`DOD.*`/`Led.*`/`Ble.*` command may appear in source.
- **The battery operating mode is not polled, shown, or used anywhere.**
- Poll interval: minimum **60 s**, default 60 s. Queries within a cycle are about 1 s apart. Timeout 5 s, 1 retry.
- The UDP client binds to local port **= device port** (default `30000`). `device.local_port` overrides this (used by tests).
- All stored timestamps are **UTC epoch seconds** (`float`). Local time is used only for display, day buckets and quiet hours.
- Data folder: `%APPDATA%\MarstekMonitor\` (`settings.json`, `history.db`, `logs\`). The env var `MARSTEK_MONITOR_HOME` overrides it (tests).
- Colors: charging `#2ea043`, discharging `#f0883e`, idle/offline `#8b949e`, red `#e5534b`, blue `#1f6feb`.
- Status window title `Marstek Venus E — Monitor`. The tray tooltip always starts with `Marstek Venus E` and is ≤ 127 characters.
- Every user-visible string goes through `i18n.tr()` with entries in both `en.json` and `uk.json`.
- Packaged exe `MarstekMonitor.exe` (PyInstaller one-folder) with FileDescription/ProductName `Marstek Monitor`.
- Exit from the tray stops everything. A hard limit of **5 s** applies, then `os._exit(0)`.
- **Settings added beyond the spec's example** (all in the schema, all defaulted):
  - `device.local_port` (null)
  - `general.start_menu_shortcut` (true)
  - `advanced.outage_detection` (false; gates the experimental grid features, spec V3)
  - `advanced.counters_verified` (false; hides round-trip efficiency and shows "unit check pending", spec V1/V2)

  Out-of-range numbers are **clamped**; wrong types fall back to defaults.

## Review Focus

1. **PC wakes from sleep:** Wi-Fi needs 10–30 s to reconnect, so the first polls after a resume fail. Expected: no "Battery not responding" alarm unless 3 *further* polls fail. Test: Task 10 `test_failures_right_after_resume_do_not_alarm`.
2. **Battery gets a new IP from DHCP:** expected: after 3 failed polls the app rediscovers the battery by BLE MAC, keeps polling the new IP, and the IP is saved to settings. Tests: Task 10 `test_rediscovers_new_ip_by_ble_mac`, Task 21 `test_device_change_is_persisted`.
3. **No internet / Telegram unreachable at startup:** expected: the app starts and polls normally; queued Telegram messages end as "failed" without blocking the UI. Test: Task 14 `test_unreachable_server_fails_without_blocking`.
4. **Ukrainian UI:** longer strings must not break the ≤127-character tooltip, and Cyrillic must be sent to Telegram as UTF-8. Tests: Task 13 `test_tooltip_limit_in_ukrainian`, Task 14 `test_cyrillic_text_is_sent_as_utf8`.
5. **Incomplete Telegram setup** (enabled but token or chat ID empty): expected: no crash, nothing sent, a clear status. Test: Task 21 `test_telegram_config_problem`.

---

## File Structure

```
pyproject.toml                      project metadata, deps, pytest config
README.md                           how to run, build, verify
docs/verification-checklist.md      manual read-only checks V1–V5
marstek_monitor/
  __init__.py                       APP_NAME, __version__
  __main__.py                       `python -m marstek_monitor`
  main.py                           argument parsing, QApplication, single instance
  app.py                            Qt glue: poller thread, tray, windows, notifiers, exit
  paths.py                          data/settings/db/log locations
  logging_setup.py                  rotating app.log + raw-response recorder
  settings.py                       defaults, validation, load/save (plain dicts)
  present.py                        text for UI, tooltip and Telegram (no widgets)
  api/client.py                     UDP JSON-RPC client, allowlist, discovery
  core/snapshot.py                  Snapshot + normalize()
  core/estimates.py                 direction, time to full / time left
  core/outage.py                    experimental outage heuristic
  core/sessions.py                  Session + SessionDetector + summaries
  core/energy.py                    period bars + lifetime from counters
  core/events.py                    Event dataclass
  core/storage.py                   SQLite persistence
  core/rules.py                     RulesEngine + quiet-hours route()
  core/poller.py                    Poller (one cycle, no Qt) + PollResult
  core/poller_thread.py             QThread loop around Poller
  core/monitor.py                   pipeline + LiveState + history accessors
  notify/telegram.py                TelegramApi, TelegramService, detect_chat_id
  notify/desktop.py                 DesktopNotifier (tray toasts)
  i18n/__init__.py, en.json, uk.json
  platform/single_instance.py       named mutex + local socket wake-up
  platform/autostart.py             HKCU Run value
  platform/shortcut.py              Start menu .lnk
  ui/theme.py                       palette, stylesheet, font scale
  ui/widgets.py                     Card, Segmented, scaled_font, clear_layout
  ui/tray.py                        tile icon, tooltip, Tray
  ui/charts.py                      BarChart, LiveChart (QPainter)
  ui/status_window.py               window with 5 tabs
  ui/tabs/now.py, energy.py, live.py, sessions.py, events.py
  ui/settings_window.py             sidebar settings with 5 pages
tests/                              pytest suite (fakes/ and fixtures/ inside)
packaging/                          launcher.py, make_icon.py, version_info.txt, MarstekMonitor.spec, build.ps1
```

All commands below are run from the repository root `D:\PROJECTS\personal\marstek` in **Git Bash**.
`PY` means `.venv/Scripts/python`.

---

### Task 1: Project scaffold, paths, logging

**Files:**
- Create: `pyproject.toml`, `marstek_monitor/__init__.py`, `marstek_monitor/paths.py`, `marstek_monitor/logging_setup.py`
- Create: `marstek_monitor/api/__init__.py`, `marstek_monitor/core/__init__.py`, `marstek_monitor/notify/__init__.py`, `marstek_monitor/platform/__init__.py`, `marstek_monitor/ui/__init__.py`, `marstek_monitor/ui/tabs/__init__.py` (all empty)
- Create: `tests/__init__.py`, `tests/fakes/__init__.py` (empty), `tests/conftest.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Produces:
  - `paths.data_dir() -> Path`, `paths.settings_path() -> Path`, `paths.db_path() -> Path`, `paths.logs_dir() -> Path`
  - `logging_setup.setup_logging(level: str) -> None`
  - `logging_setup.RawRecorder` (callable, `__call__(record: dict) -> None`)
  - pytest fixture `app_home`

- [ ] **Step 1: Create the project file and venv**

`pyproject.toml`:

```toml
[project]
name = "marstek-monitor"
version = "0.1.0"
description = "Read-only Windows tray monitor for Marstek Venus E batteries (Local API)"
requires-python = ">=3.13"
dependencies = ["PySide6>=6.7"]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-qt>=4.4", "pyinstaller>=6.10"]

[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["marstek_monitor*"]

[tool.setuptools.package-data]
marstek_monitor = ["i18n/*.json"]

[tool.pytest.ini_options]
testpaths = ["tests"]
qt_api = "pyside6"
```

`marstek_monitor/__init__.py`:

```python
"""Marstek Monitor: read-only tray monitor for Marstek Venus E batteries."""

APP_NAME = "Marstek Monitor"
__version__ = "0.1.0"
```

Create the empty `__init__.py` files listed above, then run:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -e ".[dev]"
```

Expected: installs PySide6, pytest, pytest-qt, pyinstaller without errors.

- [ ] **Step 2: Write the failing test**

`tests/conftest.py`:

```python
import pytest


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    """Point the app's data folder at a temporary directory."""
    home = tmp_path / "home"
    monkeypatch.setenv("MARSTEK_MONITOR_HOME", str(home))
    return home
```

`tests/test_paths.py`:

```python
import json
import logging
import time

from marstek_monitor import paths
from marstek_monitor.logging_setup import RawRecorder, setup_logging


def _close_root_handlers():
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


def test_data_dir_uses_override(app_home):
    assert paths.data_dir() == app_home
    assert app_home.is_dir()


def test_files_live_in_data_dir(app_home):
    assert paths.settings_path() == app_home / "settings.json"
    assert paths.db_path() == app_home / "history.db"
    assert paths.logs_dir() == app_home / "logs"
    assert (app_home / "logs").is_dir()


def test_setup_logging_writes_app_log(app_home):
    setup_logging("INFO")
    logging.getLogger("test").info("hello log")
    for handler in logging.getLogger().handlers:
        handler.flush()
    text = (app_home / "logs" / "app.log").read_text(encoding="utf-8")
    _close_root_handlers()
    assert "hello log" in text


def test_raw_recorder_appends_json_lines(app_home):
    recorder = RawRecorder()
    recorder({"method": "Bat.GetStatus", "response": {"id": 1}})
    recorder({"method": "ES.GetStatus", "response": {"id": 2}})
    day = time.strftime("%Y%m%d")
    lines = (app_home / "logs" / f"raw-{day}.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["method"] for line in lines] == ["Bat.GetStatus", "ES.GetStatus"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.paths'`

- [ ] **Step 4: Implement**

`marstek_monitor/paths.py`:

```python
"""Filesystem locations used by the app."""
import os
from pathlib import Path

APP_DIR_NAME = "MarstekMonitor"


def data_dir() -> Path:
    override = os.environ.get("MARSTEK_MONITOR_HOME")
    base = Path(override) if override else Path(os.environ["APPDATA"]) / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_path() -> Path:
    return data_dir() / "settings.json"


def db_path() -> Path:
    return data_dir() / "history.db"


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path
```

`marstek_monitor/logging_setup.py`:

```python
"""Rotating application log and the optional raw-response recorder."""
import json
import logging
import threading
import time
from logging.handlers import RotatingFileHandler

from . import paths


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    handler = RotatingFileHandler(
        paths.logs_dir() / "app.log", maxBytes=1_000_000, backupCount=4, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


class RawRecorder:
    """Appends every raw API response to logs/raw-YYYYMMDD.jsonl ("Record raw data")."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __call__(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        path = paths.logs_dir() / f"raw-{time.strftime('%Y%m%d')}.jsonl"
        with self._lock, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_paths.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml marstek_monitor tests
git commit -m "feat: project scaffold with data paths and logging"
```

---

### Task 2: Read-only API client, fake battery, read-only guard

**Files:**
- Create: `marstek_monitor/api/client.py`
- Create: `tests/fixtures/probe-2026-10-01.json`, `tests/fakes/fake_battery.py`, `tests/fakes/net.py`
- Test: `tests/test_client.py`, `tests/test_readonly_guard.py`

**Interfaces:**
- Produces (in `marstek_monitor.api.client`):
  - `ALLOWED_METHODS: frozenset[str]`
  - exceptions `ForbiddenMethodError`, `ApiError(code, message)` (attrs `.code`, `.message`), `ApiTimeout`, `PortInUseError`, `ClientStopped`
  - `@dataclass(frozen=True) DeviceInfo(device: str, ver: int | None, ble_mac: str, wifi_mac: str, ip: str)` with `DeviceInfo.from_result(result: dict, fallback_ip: str)`
  - `local_ip_for(target_ip: str) -> str`, `broadcast_addresses(local_ip: str) -> list[str]`
  - `MarstekClient(local_ip: str, local_port: int, device_port: int, timeout: float = 5.0, retries: int = 1, raw_recorder: Callable[[dict], None] | None = None)` with:
    - `.open()`, `.close()`, `.stop()`
    - `.call(ip: str, method: str, params: dict | None = None) -> dict`
    - `.discover(addresses: list[str], wait: float = 3.0) -> list[DeviceInfo]`
    - attribute `.local_ip`
- Produces (tests): `tests.fakes.fake_battery.FakeBattery(host="127.0.0.1", port=0)` with `.start()`, `.stop()`, context manager, `.port`, `.host`, `.results: dict[str, dict]`, `.mode: dict[str, str]` (values `ok|timeout|garbage|wrong_id|error`), `.received: list[dict]`; `tests.fakes.net.free_udp_port() -> int`.

- [ ] **Step 1: Add the captured probe responses as a fixture**

`tests/fixtures/probe-2026-10-01.json` (real responses from the owner's battery, captured 2026-10-01):

```json
{
  "Marstek.GetDevice": {"id": 1, "src": "VenusE 3.0-0123456789ab", "result": {"device": "VenusE 3.0", "ver": 144, "ble_mac": "0123456789ab", "wifi_mac": "a1b2c3d4e5f6", "wifi_name": "HomeWiFi", "ip": "192.168.1.20"}},
  "Wifi.GetStatus": {"id": 2, "src": "VenusE 3.0-0123456789ab", "result": {"id": 0, "wifi_mac": "a1b2c3d4e5f6", "ssid": "HomeWiFi", "rssi": -49, "sta_ip": "192.168.1.20", "sta_gate": "192.168.1.1", "sta_mask": "255.255.255.0", "sta_dns": "192.168.1.1"}},
  "Bat.GetStatus": {"id": 4, "src": "VenusE 3.0-0123456789ab", "result": {"id": 0, "soc": 100, "charg_flag": true, "dischrg_flag": true, "bat_temp": 24.0, "bat_capacity": 5120.0, "rated_capacity": 5120.0}},
  "ES.GetStatus": {"id": 5, "src": "VenusE 3.0-0123456789ab", "result": {"id": 0, "bat_soc": 100, "bat_cap": 5120, "pv_power": 0, "ongrid_power": 0, "offgrid_power": 0, "total_pv_energy": 0, "total_grid_output_energy": 3329, "total_grid_input_energy": 9196, "total_load_energy": 0}},
  "EM.GetStatus": {"id": 7, "src": "VenusE 3.0-0123456789ab", "result": {"id": 0, "ct_state": 0, "a_power": 0, "b_power": 0, "c_power": 0, "total_power": 0, "input_energy": 0, "output_energy": 0}}
}
```

- [ ] **Step 2: Write the fake battery and network helper**

`tests/fakes/net.py`:

```python
import socket


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port
```

`tests/fakes/fake_battery.py`:

```python
"""A local UDP server that behaves like a Marstek battery's Local API (tests only)."""
import json
import socket
import threading
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "probe-2026-10-01.json"
SRC = "VenusE 3.0-0123456789ab"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeBattery:
    """Replies to JSON-RPC requests with fixture results.

    Per-method behaviour via `mode[method]`: "ok" (default), "timeout" (no reply),
    "garbage" (non-JSON), "wrong_id" (reply with another id), "error" (JSON-RPC error).
    Edit `results[method]` to change returned values.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.results = {m: r["result"] for m, r in load_fixture().items()}
        self.mode: dict[str, str] = {}
        self.received: list[dict] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(0.2)
        self.host, self.port = self.sock.getsockname()
        # Like the real device, report our own address in GetDevice.
        self.results["Marstek.GetDevice"] = dict(self.results["Marstek.GetDevice"], ip=self.host)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "FakeBattery":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self.sock.close()

    def __enter__(self) -> "FakeBattery":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def methods_received(self) -> list[str]:
        return [r.get("method") for r in self.received]

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                req = json.loads(data)
            except ValueError:
                continue
            self.received.append(req)
            method = req.get("method")
            mode = self.mode.get(method, "ok")
            if mode == "timeout":
                continue
            if mode == "garbage":
                self.sock.sendto(b"\x00not json", addr)
                continue
            rid = req.get("id")
            if method not in self.results:
                reply = {"id": rid, "src": SRC, "error": {"code": -32601, "message": "Method not found"}}
            elif mode == "error":
                reply = {"id": rid, "src": SRC, "error": {"code": -32603, "message": "Internal error"}}
            else:
                if mode == "wrong_id":
                    rid = (rid or 0) + 1000
                reply = {"id": rid, "src": SRC, "result": self.results[method]}
            self.sock.sendto(json.dumps(reply).encode(), addr)
```

- [ ] **Step 3: Write the failing tests**

`tests/test_client.py`:

```python
import socket
import threading
import time

import pytest

from marstek_monitor.api.client import (
    ALLOWED_METHODS,
    ApiError,
    ApiTimeout,
    ClientStopped,
    ForbiddenMethodError,
    MarstekClient,
    PortInUseError,
    broadcast_addresses,
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
```

`tests/test_readonly_guard.py`:

```python
"""Fails if any string shaped like an API method name outside the allowlist appears in source."""
import ast
import re
from pathlib import Path

from marstek_monitor.api.client import ALLOWED_METHODS

PACKAGE = Path(__file__).parent.parent / "marstek_monitor"
METHOD_SHAPE = re.compile(r"^[A-Z][A-Za-z]*\.[A-Z][A-Za-z]*$")


def test_no_non_allowlisted_method_names_in_source():
    offenders = []
    for py in PACKAGE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and METHOD_SHAPE.match(node.value)
                and node.value not in ALLOWED_METHODS
            ):
                offenders.append(f"{py.relative_to(PACKAGE)}:{node.lineno}: {node.value}")
    assert offenders == []
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_client.py tests/test_readonly_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.api.client'`

- [ ] **Step 5: Implement the client**

`marstek_monitor/api/client.py`:

```python
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
from dataclasses import dataclass
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
            ip=str(result.get("ip") or fallback_ip),
        )


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
                info = DeviceInfo.from_result(msg["result"], fallback_ip=addr[0])
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
        except OSError:
            if self._stop.is_set():
                raise ClientStopped()
            raise
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_client.py tests/test_readonly_guard.py -v`
Expected: 20 passed

- [ ] **Step 7: Commit**

```bash
git add marstek_monitor/api tests
git commit -m "feat: read-only UDP client with allowlist, fake battery and source guard"
```

---

### Task 3: Settings (defaults, validation, load/save)

**Files:**
- Create: `marstek_monitor/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces:
  - `settings.SCHEMA = 1`, `settings.MIN_POLL_SECONDS = 60`, `settings.MAX_SOC_LEVELS = 3`
  - `settings.DEFAULTS: dict`, `settings.defaults() -> dict`, `settings.validate(data) -> dict`
  - `settings.load(path: Path) -> tuple[dict, str | None]`: the second value is the warning i18n key `"sys.settings_broken"` or `None`
  - `settings.save(path: Path, data: dict) -> None`
- Settings shape used by all later tasks (key names exact):
  - `device`: `ble_mac`, `ip`, `port`, `local_port`
  - `general`: `language`, `autostart`, `poll_seconds`, `offline_after_polls`, `start_menu_shortcut`
  - `appearance`: `font_scale`, `theme`
  - `quiet_hours`: `enabled`, `from`, `to`, `critical_bypass`, `silence_telegram`
  - `notifications`:
    - `soc_below`: list of `{enabled, pct, priority, desktop, telegram, repeat_min}`
    - `soc_reached`: `{enabled, pct, desktop, telegram, repeat_min}`
    - `grid`: `{enabled, desktop, telegram, repeat_min}`
    - `backup_left`: `{enabled, minutes, desktop, telegram, repeat_min}`
    - `charge_session` / `discharge_session`: `{enabled, desktop, telegram}`
    - `offline`: `{enabled, desktop, telegram, repeat_min}`
    - `blocked`: `{enabled, desktop, telegram, repeat_min}`
    - `temperature`: `{enabled, high, low, desktop, telegram, repeat_min}`
    - `firmware`: `{enabled, desktop, telegram}`
    - `monitor`: `{enabled, telegram}`
  - `telegram`: `enabled`, `bot_token`, `chat_id`, `user_id`, `answer_command`
  - `advanced`: `power_sign`, `counter_unit`, `counters_verified`, `outage_detection`, `rearm_pct`, `rearm_c`, `reserve_soc_pct`, `samples_retention_days`, `log_level`, `record_raw`

- [ ] **Step 1: Write the failing tests**

`tests/test_settings.py`:

```python
import json

from marstek_monitor import settings


def test_missing_file_gives_defaults(tmp_path):
    data, warning = settings.load(tmp_path / "settings.json")
    assert warning is None
    assert data == settings.defaults()
    assert data["general"]["poll_seconds"] == 60
    assert data["device"]["port"] == 30000


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    data = settings.defaults()
    data["telegram"]["bot_token"] = "123:abc"
    data["general"]["language"] = "uk"
    settings.save(path, data)
    loaded, warning = settings.load(path)
    assert warning is None
    assert loaded == data


def test_unknown_keys_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    raw = settings.defaults()
    raw["future_section"] = {"x": 1}
    raw["general"]["future_flag"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    loaded, _ = settings.load(path)
    assert loaded["future_section"] == {"x": 1}
    assert loaded["general"]["future_flag"] is True


def test_wrong_types_fall_back_to_defaults():
    data = settings.validate({"general": {"language": "de", "autostart": "yes"}, "quiet_hours": {"from": "25:00"}})
    assert data["general"]["language"] == "en"
    assert data["general"]["autostart"] is False
    assert data["quiet_hours"]["from"] == "23:00"


def test_numbers_are_clamped():
    data = settings.validate({"general": {"poll_seconds": 10}, "appearance": {"font_scale": 5}})
    assert data["general"]["poll_seconds"] == settings.MIN_POLL_SECONDS
    assert data["appearance"]["font_scale"] == 2.0


def test_soc_levels_are_limited_and_completed():
    levels = [{"pct": 50}, {"pct": 30}, {"pct": 20}, {"pct": 10}]
    data = settings.validate({"notifications": {"soc_below": levels}})
    below = data["notifications"]["soc_below"]
    assert [lvl["pct"] for lvl in below] == [50, 30, 20]
    assert below[0]["enabled"] is True and below[0]["priority"] == "normal"


def test_empty_soc_levels_fall_back_to_defaults():
    data = settings.validate({"notifications": {"soc_below": []}})
    assert [lvl["pct"] for lvl in data["notifications"]["soc_below"]] == [40, 20]


def test_telegram_ids_accept_numbers():
    data = settings.validate({"telegram": {"chat_id": 123456789, "user_id": " 42 "}})
    assert data["telegram"]["chat_id"] == "123456789"
    assert data["telegram"]["user_id"] == "42"


def test_broken_file_is_renamed_and_defaults_loaded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    data, warning = settings.load(path)
    assert warning == "sys.settings_broken"
    assert data == settings.defaults()
    assert not path.exists()
    assert len(list(tmp_path.glob("settings.broken-*.json"))) == 1


def test_defaults_are_independent_copies():
    a = settings.defaults()
    a["notifications"]["soc_below"][0]["pct"] = 99
    assert settings.defaults()["notifications"]["soc_below"][0]["pct"] == 40
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: FAIL with `ImportError: cannot import name 'settings'`

- [ ] **Step 3: Implement**

`marstek_monitor/settings.py`:

```python
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

log = logging.getLogger(__name__)

SCHEMA = 1
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
    "advanced": {"power_sign": "plus_is_charging", "counter_unit": "Wh", "counters_verified": False,
                 "outage_detection": False, "rearm_pct": 2, "rearm_c": 2, "reserve_soc_pct": 12,
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
    "device.ip": text,
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


def validate(data: Any) -> dict:
    result = _merge(DEFAULTS, data if isinstance(data, dict) else {}, "")
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_settings.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/settings.py tests/test_settings.py
git commit -m "feat: settings with defaults, validation and safe load/save"
```

---

### Task 4: Snapshot and normalization

**Files:**
- Create: `marstek_monitor/core/snapshot.py`
- Test: `tests/test_snapshot.py`

**Interfaces:**
- Produces:
  - `COUNTER_UNITS: dict[str, float]`
  - `@dataclass(frozen=True) NormalizeConfig(power_sign: str = "plus_is_charging", counter_unit: str = "Wh")`
  - `@dataclass(frozen=True) Snapshot`:
    - `ts: float`, `responded: bool`
    - `soc_pct: int | None`, `stored_wh`, `rated_wh`, `temp_c`
    - `power_w` (+ = charging), `ongrid_w`, `offgrid_w`
    - `charge_allowed: bool | None`, `discharge_allowed: bool | None`
    - `counter_in_wh`, `counter_out_wh`
    - `rssi_dbm: int | None`, `fw_version: int | None`, `ip: str | None`
    - `failed_methods: tuple[str, ...]`

    All numeric fields not given types above are `float | None`, and everything except `ts` / `responded` defaults to `None` (or `()`).
  - `normalize(ts: float, raw: dict[str, dict | None], cfg: NormalizeConfig, fw_version: int | None = None, ip: str | None = None, failed: tuple[str, ...] = ()) -> Snapshot`
  - `snapshot_to_dict(s: Snapshot) -> dict`, `snapshot_from_dict(d: dict) -> Snapshot`

- [ ] **Step 1: Write the failing tests**

`tests/test_snapshot.py`:

```python
from marstek_monitor.core.snapshot import (
    NormalizeConfig,
    Snapshot,
    normalize,
    snapshot_from_dict,
    snapshot_to_dict,
)
from tests.fakes.fake_battery import load_fixture

FIX = {m: r["result"] for m, r in load_fixture().items()}
CFG = NormalizeConfig()


def raw(**overrides):
    data = {"Bat.GetStatus": dict(FIX["Bat.GetStatus"]), "ES.GetStatus": dict(FIX["ES.GetStatus"]),
            "Wifi.GetStatus": dict(FIX["Wifi.GetStatus"])}
    for method, values in overrides.items():
        key = method.replace("_", ".", 1)
        data[key] = None if values is None else {**(data.get(key) or {}), **values}
    return data


def test_probe_fixture_normalizes():
    s = normalize(1000.0, raw(), CFG, fw_version=144, ip="192.168.1.20")
    assert s.responded is True
    assert s.soc_pct == 100
    assert s.stored_wh == 5120.0 and s.rated_wh == 5120.0
    assert s.temp_c == 24.0
    assert s.power_w == 0.0
    assert s.counter_in_wh == 9196.0 and s.counter_out_wh == 3329.0
    assert s.charge_allowed is True and s.discharge_allowed is True
    assert s.rssi_dbm == -49
    assert s.fw_version == 144 and s.ip == "192.168.1.20"


def test_power_sign_can_be_inverted():
    data = raw(ES_GetStatus={"ongrid_power": 800})
    assert normalize(0, data, CFG).power_w == 800
    assert normalize(0, data, NormalizeConfig(power_sign="minus_is_charging")).power_w == -800


def test_bat_power_is_preferred_over_ongrid():
    data = raw(ES_GetStatus={"ongrid_power": 800, "bat_power": -300})
    assert normalize(0, data, CFG).power_w == -300


def test_counter_units():
    data = raw(ES_GetStatus={"total_grid_input_energy": 50})
    assert normalize(0, data, NormalizeConfig(counter_unit="0.01kWh")).counter_in_wh == 500.0
    assert normalize(0, data, NormalizeConfig(counter_unit="0.1Wh")).counter_in_wh == 5.0
    assert normalize(0, data, NormalizeConfig(counter_unit="kWh")).counter_in_wh == 50000.0


def test_temperature_times_ten_bug_is_corrected():
    assert normalize(0, raw(Bat_GetStatus={"bat_temp": 245}), CFG).temp_c == 24.5
    assert normalize(0, raw(Bat_GetStatus={"bat_temp": 2000}), CFG).temp_c is None


def test_invalid_soc_falls_back_to_es_status():
    s = normalize(0, raw(Bat_GetStatus={"soc": 150}, ES_GetStatus={"bat_soc": 77}), CFG)
    assert s.soc_pct == 77


def test_soc_as_string():
    assert normalize(0, raw(Bat_GetStatus={"soc": "90"}), CFG).soc_pct == 90


def test_stored_energy_is_derived_when_missing():
    s = normalize(0, raw(Bat_GetStatus={"bat_capacity": None, "soc": 50}), CFG)
    assert s.stored_wh == 2560.0


def test_nothing_answered():
    s = normalize(0, {"Bat.GetStatus": None, "ES.GetStatus": None}, CFG, failed=("Bat.GetStatus", "ES.GetStatus"))
    assert s.responded is False
    assert s.soc_pct is None
    assert s.failed_methods == ("Bat.GetStatus", "ES.GetStatus")


def test_dict_roundtrip():
    s = normalize(5.0, raw(), CFG, fw_version=144, failed=("Wifi.GetStatus",))
    assert snapshot_from_dict(snapshot_to_dict(s)) == s
    assert isinstance(snapshot_from_dict({"ts": 1.0, "responded": True, "extra": 1}), Snapshot)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.snapshot'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/snapshot.py`:

```python
"""One poll's data, normalized. All firmware quirks are handled here (spec §4, §6.2)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

COUNTER_UNITS = {"Wh": 1.0, "0.1Wh": 0.1, "0.01kWh": 10.0, "kWh": 1000.0}


@dataclass(frozen=True)
class NormalizeConfig:
    power_sign: str = "plus_is_charging"   # spec V1: which sign of the power field means charging
    counter_unit: str = "Wh"               # spec V2: unit of the lifetime energy counters


@dataclass(frozen=True)
class Snapshot:
    ts: float
    responded: bool
    soc_pct: int | None = None
    stored_wh: float | None = None
    rated_wh: float | None = None
    temp_c: float | None = None
    power_w: float | None = None      # + = charging, - = discharging (after sign mapping)
    ongrid_w: float | None = None
    offgrid_w: float | None = None
    charge_allowed: bool | None = None
    discharge_allowed: bool | None = None
    counter_in_wh: float | None = None
    counter_out_wh: float | None = None
    rssi_dbm: int | None = None
    fw_version: int | None = None
    ip: str | None = None
    failed_methods: tuple[str, ...] = ()


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _soc(value: Any) -> int | None:
    n = _num(value)
    if n is None or not 0 <= n <= 100:
        return None
    return int(round(n))


def _temp(value: Any) -> float | None:
    n = _num(value)
    if n is None:
        return None
    if n > 100:  # known firmware bug: temperature reported x10
        n = n / 10
    if n > 100 or n < -40:
        return None
    return n


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def normalize(
    ts: float,
    raw: dict[str, dict | None],
    cfg: NormalizeConfig,
    fw_version: int | None = None,
    ip: str | None = None,
    failed: tuple[str, ...] = (),
) -> Snapshot:
    bat = raw.get("Bat.GetStatus") or {}
    es = raw.get("ES.GetStatus") or {}
    wifi = raw.get("Wifi.GetStatus") or {}

    soc = _soc(bat.get("soc"))
    if soc is None:
        soc = _soc(es.get("bat_soc"))
    rated = _num(bat.get("rated_capacity")) or _num(es.get("bat_cap"))
    stored = _num(bat.get("bat_capacity"))
    if stored is None and soc is not None and rated:
        stored = rated * soc / 100

    ongrid = _num(es.get("ongrid_power"))
    offgrid = _num(es.get("offgrid_power"))
    raw_power = _num(es.get("bat_power"))
    if raw_power is None:
        raw_power = ongrid
    power = None
    if raw_power is not None:
        power = raw_power if cfg.power_sign == "plus_is_charging" else -raw_power

    unit = COUNTER_UNITS.get(cfg.counter_unit, 1.0)
    counter_in = _num(es.get("total_grid_input_energy"))
    counter_out = _num(es.get("total_grid_output_energy"))
    rssi = _num(wifi.get("rssi"))

    return Snapshot(
        ts=ts,
        responded=bool(bat or es),
        soc_pct=soc,
        stored_wh=stored,
        rated_wh=rated,
        temp_c=_temp(bat.get("bat_temp")),
        power_w=power,
        ongrid_w=ongrid,
        offgrid_w=offgrid,
        charge_allowed=_flag(bat.get("charg_flag")),
        discharge_allowed=_flag(bat.get("dischrg_flag")),
        counter_in_wh=None if counter_in is None else counter_in * unit,
        counter_out_wh=None if counter_out is None else counter_out * unit,
        rssi_dbm=None if rssi is None else int(rssi),
        fw_version=fw_version,
        ip=ip,
        failed_methods=tuple(failed),
    )


def snapshot_to_dict(s: Snapshot) -> dict:
    data = asdict(s)
    data["failed_methods"] = list(s.failed_methods)
    return data


def snapshot_from_dict(data: dict) -> Snapshot:
    known = {f.name for f in fields(Snapshot)}
    clean = {k: v for k, v in data.items() if k in known}
    clean["failed_methods"] = tuple(clean.get("failed_methods", ()))
    return Snapshot(**clean)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_snapshot.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/snapshot.py tests/test_snapshot.py
git commit -m "feat: snapshot normalization with sign, unit and sanity handling"
```

---

### Task 5: Estimates and the experimental outage detector

**Files:**
- Create: `marstek_monitor/core/estimates.py`, `marstek_monitor/core/outage.py`
- Test: `tests/test_estimates_outage.py`

**Interfaces:**
- Consumes: `Snapshot` (Task 4).
- Produces:
  - `estimates.IDLE_W = 30.0`, constants `CHARGING = "charging"`, `DISCHARGING = "discharging"`, `IDLE = "idle"`
  - `estimates.direction(power_w: float | None) -> str | None`
  - `estimates.minutes_to_full(s: Snapshot) -> float | None`
  - `estimates.minutes_left(s: Snapshot, reserve_soc_pct: float) -> float | None`
  - `outage.OutageDetector(enabled: bool)` with:
    - attributes `enabled`, `state` (`"unknown" | "ok" | "lost"`), `since: float | None`, `last_end_ts: float | None`, `last_duration_s: float | None`
    - `update(s: Snapshot) -> str | None` (`"lost" | "restored" | None`)

- [ ] **Step 1: Write the failing tests**

`tests/test_estimates_outage.py`:

```python
import pytest

from marstek_monitor.core.estimates import direction, minutes_left, minutes_to_full
from marstek_monitor.core.outage import OutageDetector
from marstek_monitor.core.snapshot import Snapshot


def snap(ts=0.0, power=None, stored=None, rated=5120.0, ongrid=None, offgrid=None):
    return Snapshot(ts=ts, responded=True, power_w=power, stored_wh=stored, rated_wh=rated,
                    ongrid_w=ongrid, offgrid_w=offgrid)


@pytest.mark.parametrize("power,expected", [(None, None), (0, "idle"), (30, "idle"), (-30, "idle"),
                                            (31, "charging"), (-31, "discharging")])
def test_direction(power, expected):
    assert direction(power) == expected


def test_minutes_to_full():
    assert minutes_to_full(snap(power=1000, stored=4120)) == pytest.approx(60.0)
    assert minutes_to_full(snap(power=0, stored=4120)) is None
    assert minutes_to_full(snap(power=-500, stored=4120)) is None


def test_minutes_left_respects_reserve():
    # reserve 12% of 5120 = 614.4 Wh; usable = 2560 - 614.4 = 1945.6 Wh at 1000 W
    assert minutes_left(snap(power=-1000, stored=2560), 12) == pytest.approx(116.736)
    assert minutes_left(snap(power=500, stored=2560), 12) is None
    assert minutes_left(snap(power=-1000, stored=300), 12) == 0.0


def test_disabled_detector_stays_unknown():
    d = OutageDetector(enabled=False)
    assert d.update(snap(ongrid=0, offgrid=500)) is None
    assert d.state == "unknown"


def test_outage_needs_two_samples_and_restores():
    d = OutageDetector(enabled=True)
    assert d.state == "ok"
    assert d.update(snap(ts=0, ongrid=0, offgrid=500)) is None
    assert d.update(snap(ts=60, ongrid=0, offgrid=500)) == "lost"
    assert d.state == "lost" and d.since == 60
    assert d.update(snap(ts=120, ongrid=0, offgrid=480)) is None
    assert d.update(snap(ts=180, ongrid=900, offgrid=480)) is None
    assert d.update(snap(ts=240, ongrid=900, offgrid=480)) == "restored"
    assert d.state == "ok" and d.last_end_ts == 240 and d.last_duration_s == 180


def test_single_glitch_does_not_trigger():
    d = OutageDetector(enabled=True)
    d.update(snap(ts=0, ongrid=0, offgrid=500))
    assert d.update(snap(ts=60, ongrid=900, offgrid=500)) is None
    assert d.update(snap(ts=120, ongrid=0, offgrid=500)) is None
    assert d.state == "ok"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_estimates_outage.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`marstek_monitor/core/estimates.py`:

```python
"""Power direction and time estimates (spec §6.7 'Time estimates')."""
from __future__ import annotations

from .snapshot import Snapshot

IDLE_W = 30.0
CHARGING, DISCHARGING, IDLE = "charging", "discharging", "idle"


def direction(power_w: float | None) -> str | None:
    if power_w is None:
        return None
    if power_w > IDLE_W:
        return CHARGING
    if power_w < -IDLE_W:
        return DISCHARGING
    return IDLE


def minutes_to_full(s: Snapshot) -> float | None:
    if s.power_w is None or s.power_w <= IDLE_W or s.stored_wh is None or not s.rated_wh:
        return None
    remaining = max(0.0, s.rated_wh - s.stored_wh)
    return remaining / s.power_w * 60


def minutes_left(s: Snapshot, reserve_soc_pct: float) -> float | None:
    if s.power_w is None or s.power_w >= -IDLE_W or s.stored_wh is None or not s.rated_wh:
        return None
    reserve_wh = s.rated_wh * reserve_soc_pct / 100
    usable = max(0.0, s.stored_wh - reserve_wh)
    return usable / -s.power_w * 60
```

`marstek_monitor/core/outage.py`:

```python
"""EXPERIMENTAL grid-outage heuristic (spec V3: the real signature is not verified yet).

Heuristic: the grid counts as lost when the battery feeds the off-grid (backup) output
(offgrid > 30 W) while the grid side carries ~no power (|ongrid| <= 5 W) for two
consecutive samples; it counts as restored after two samples with |ongrid| > 5 W.
Disabled by default via settings `advanced.outage_detection`.
"""
from __future__ import annotations

from .snapshot import Snapshot

OFFGRID_MIN_W = 30.0
ONGRID_MAX_W = 5.0
CONFIRM_SAMPLES = 2


class OutageDetector:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.state = "ok" if enabled else "unknown"
        self.since: float | None = None
        self.last_end_ts: float | None = None
        self.last_duration_s: float | None = None
        self._streak = 0

    def update(self, s: Snapshot) -> str | None:
        if not self.enabled or not s.responded or s.ongrid_w is None:
            return None
        looks_lost = (s.offgrid_w or 0.0) > OFFGRID_MIN_W and abs(s.ongrid_w) <= ONGRID_MAX_W
        wanted = "lost" if looks_lost else "ok"
        if wanted == self.state:
            self._streak = 0
            return None
        self._streak += 1
        if self._streak < CONFIRM_SAMPLES:
            return None
        self._streak = 0
        if wanted == "lost":
            self.state, self.since = "lost", s.ts
            return "lost"
        self.last_duration_s = s.ts - self.since if self.since is not None else None
        self.state, self.since, self.last_end_ts = "ok", s.ts, s.ts
        return "restored"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_estimates_outage.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/estimates.py marstek_monitor/core/outage.py tests/test_estimates_outage.py
git commit -m "feat: time estimates and experimental outage heuristic"
```

---
### Task 6: Charge/discharge session detection

**Files:**
- Create: `marstek_monitor/core/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Consumes:
  - `Snapshot` (Task 4)
  - `estimates.direction`, `CHARGING`, `DISCHARGING`, `IDLE` (Task 5)
- Produces:
  - constants `FLAG_STARTED_BEFORE_APP = "started_before_app"`, `FLAG_GAP = "gap"`, `FLAG_ENDED_WHILE_OFF = "ended_while_off"`, `AFTER_OUTAGE_WINDOW_S = 1800`
  - `@dataclass Session` with fields:
    - `kind: str` (`"charge" | "discharge"`), `start_ts: float`, `start_soc: int | None`
    - `cause: str = "other"` (`other | outage | after_outage | after_full_discharge`)
    - `flags: set[str]`
    - `end_ts: float | None = None`, `end_soc: int | None = None`
    - `energy_wh: float | None = None`, `avg_power_w: float | None = None`
    - `last_ts: float = 0.0`, `last_soc: int | None = None`, `last_counter: float | None = None`
    - `counter_wh: float | None = None`, `integrated_wh: float = 0.0`
    - `id: int | None = None`

    Session properties and methods:
    - `is_open`, `duration_s`, `quality` (`complete | started_before_app | ended_while_off | gap`)
    - `energy_so_far() -> float`
    - `to_dict() -> dict`, `Session.from_dict(d) -> Session`
  - `SessionDetector(reserve_soc_pct: float)` with:
    - attributes `.current: Session | None`, `.reserve`
    - `.restore(s: Session)`, `.mark_gap()`
    - `.update(s: Snapshot, outage_active: bool = False, last_outage_end_ts: float | None = None) -> list[Session]` (returns the sessions that finished)
  - `typical_full_charge_s(sessions: list[Session]) -> float | None`, `longest_backup(sessions: list[Session]) -> Session | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_sessions.py`:

```python
import pytest

from marstek_monitor.core.sessions import (
    FLAG_GAP,
    Session,
    SessionDetector,
    longest_backup,
    typical_full_charge_s,
)
from marstek_monitor.core.snapshot import Snapshot


def snap(ts, soc, power, cin=None, cout=None):
    return Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, counter_in_wh=cin, counter_out_wh=cout)


def feed(detector, samples, **kwargs):
    finished = []
    for s in samples:
        finished += detector.update(s, **kwargs)
    return finished


def test_idle_only_creates_no_session():
    d = SessionDetector(12)
    assert feed(d, [snap(t * 60, 50, 0) for t in range(5)]) == []
    assert d.current is None


def test_complete_charge_session():
    d = SessionDetector(12)
    done = feed(d, [
        snap(0, 40, 0),
        snap(60, 41, 1000, cin=100), snap(120, 42, 1000, cin=120), snap(180, 43, 1000, cin=140),
        snap(240, 43, 0), snap(300, 43, 0),
    ])
    assert len(done) == 1
    s = done[0]
    assert (s.kind, s.start_ts, s.end_ts, s.start_soc, s.end_soc) == ("charge", 60, 240, 41, 43)
    assert s.energy_wh == 40
    assert s.duration_s == 180
    assert s.avg_power_w == pytest.approx(800)
    assert s.quality == "complete"
    assert s.cause == "other"


def test_single_blip_does_not_start_a_session():
    d = SessionDetector(12)
    assert feed(d, [snap(0, 40, 0), snap(60, 40, 900), snap(120, 40, 0), snap(180, 40, 0)]) == []
    assert d.current is None


def test_session_already_running_at_app_start_is_flagged():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 50, 900), snap(60, 51, 900), snap(120, 51, 0), snap(180, 51, 0)])
    assert done[0].quality == "started_before_app"
    assert done[0].start_ts == 0


def test_charge_ends_at_full_and_no_new_session_at_100():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 97, 0), snap(60, 98, 900), snap(120, 99, 900), snap(180, 100, 900),
                    snap(240, 100, 200), snap(300, 100, 200)])
    assert len(done) == 1
    assert done[0].end_ts == 180 and done[0].end_soc == 100
    assert d.current is None


def test_gap_marks_session():
    d = SessionDetector(12)
    feed(d, [snap(0, 40, 0), snap(60, 41, 900), snap(120, 42, 900)])
    d.mark_gap()
    done = feed(d, [snap(400, 45, 900), snap(460, 45, 0), snap(520, 45, 0)])
    assert done[0].quality == FLAG_GAP


def test_session_that_ended_while_app_was_off():
    d1 = SessionDetector(12)
    feed(d1, [snap(0, 40, 0), snap(60, 41, 900), snap(120, 42, 900)])
    open_session = d1.current
    d2 = SessionDetector(12)
    d2.restore(open_session)
    done = d2.update(snap(1000, 80, 0))
    assert len(done) == 1
    assert done[0].quality == "ended_while_off"
    assert done[0].end_ts == 120 and done[0].end_soc == 42


def test_energy_falls_back_to_power_integration():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 40, 0), snap(60, 41, 1200), snap(120, 42, 1200), snap(180, 43, 1200),
                    snap(240, 43, 0), snap(300, 43, 0)])
    assert done[0].energy_wh == pytest.approx(40)


def test_counter_reset_is_never_negative():
    d = SessionDetector(12)
    feed(d, [snap(0, 40, 0), snap(60, 41, 900, cin=100), snap(120, 42, 900, cin=120),
             snap(180, 43, 900, cin=5), snap(240, 44, 900, cin=25)])
    assert d.current.energy_so_far() == 40


def test_discharge_during_outage():
    d = SessionDetector(12)
    feed(d, [snap(0, 100, 0), snap(60, 99, -800), snap(120, 98, -800)], outage_active=True)
    assert d.current.kind == "discharge" and d.current.cause == "outage"


def test_charge_right_after_outage():
    d = SessionDetector(12)
    feed(d, [snap(60, 30, 0), snap(120, 31, 900), snap(180, 32, 900)], last_outage_end_ts=0)
    assert d.current.cause == "after_outage"


def test_charge_after_full_discharge():
    d = SessionDetector(12)
    feed(d, [snap(0, 13, 0), snap(60, 13, 900), snap(120, 14, 900)])
    assert d.current.cause == "after_full_discharge"


def test_soc_trend_is_used_when_power_is_missing():
    d = SessionDetector(12)
    feed(d, [snap(0, 50, None), snap(60, 50, None), snap(120, 51, None), snap(180, 52, None)])
    assert d.current is not None
    assert d.current.kind == "charge" and d.current.start_ts == 120


def test_opposite_direction_ends_and_starts_sessions():
    d = SessionDetector(12)
    done = feed(d, [snap(0, 50, 0), snap(60, 51, 900), snap(120, 52, 900),
                    snap(180, 52, -700), snap(240, 51, -700)])
    assert [s.kind for s in done] == ["charge"]
    assert done[0].end_ts == 180
    assert d.current.kind == "discharge" and d.current.start_ts == 180


def test_summaries():
    charges = [
        Session(kind="charge", start_ts=0, start_soc=20, end_ts=9600, end_soc=100),
        Session(kind="charge", start_ts=10000, start_soc=50, end_ts=14000, end_soc=90),
    ]
    discharges = [
        Session(kind="discharge", start_ts=20000, start_soc=100, end_ts=23600, end_soc=60),
        Session(kind="discharge", start_ts=30000, start_soc=100, end_ts=37200, end_soc=20),
        Session(kind="discharge", start_ts=40000, start_soc=100, end_ts=49000, end_soc=10, flags={FLAG_GAP}),
    ]
    assert typical_full_charge_s(charges + discharges) == pytest.approx(8800)
    assert longest_backup(charges + discharges).start_ts == 30000
    assert typical_full_charge_s([]) is None
    assert longest_backup([]) is None


def test_session_dict_roundtrip():
    s = Session(kind="discharge", start_ts=5, start_soc=90, cause="outage", flags={"gap"}, end_ts=50, id=3)
    assert Session.from_dict(s.to_dict()) == s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_sessions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.sessions'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/sessions.py`:

```python
"""Charge/discharge session detection from successive snapshots (spec §6.5, pure logic)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from .estimates import CHARGING, DISCHARGING, IDLE, direction as power_direction
from .snapshot import Snapshot

FLAG_STARTED_BEFORE_APP = "started_before_app"
FLAG_GAP = "gap"
FLAG_ENDED_WHILE_OFF = "ended_while_off"
QUALITY_ORDER = (FLAG_STARTED_BEFORE_APP, FLAG_ENDED_WHILE_OFF, FLAG_GAP)
AFTER_OUTAGE_WINDOW_S = 1800
INTEGRATION_MAX_DT_S = 600
KIND_OF = {CHARGING: "charge", DISCHARGING: "discharge"}


@dataclass
class Session:
    kind: str
    start_ts: float
    start_soc: int | None
    cause: str = "other"
    flags: set[str] = field(default_factory=set)
    end_ts: float | None = None
    end_soc: int | None = None
    energy_wh: float | None = None
    avg_power_w: float | None = None
    last_ts: float = 0.0
    last_soc: int | None = None
    last_counter: float | None = None
    counter_wh: float | None = None
    integrated_wh: float = 0.0
    id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.end_ts is None

    @property
    def duration_s(self) -> float:
        end = self.end_ts if self.end_ts is not None else self.last_ts
        return max(0.0, end - self.start_ts)

    @property
    def quality(self) -> str:
        for flag in QUALITY_ORDER:
            if flag in self.flags:
                return flag
        return "complete"

    def energy_so_far(self) -> float:
        return self.counter_wh if self.counter_wh is not None else self.integrated_wh

    def to_dict(self) -> dict:
        data = asdict(self)
        data["flags"] = sorted(self.flags)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        clean["flags"] = set(clean.get("flags") or ())
        return cls(**clean)


class SessionDetector:
    def __init__(self, reserve_soc_pct: float):
        self.reserve = reserve_soc_pct
        self.current: Session | None = None
        self._pending: tuple[str, Snapshot, bool] | None = None
        self._end_streak: list[tuple[str, Snapshot]] = []
        self._soc_hist: list[int] = []
        self._fresh = True      # no sample seen since app start or the last gap
        self._resumed = False   # current session was restored or survived a gap

    def restore(self, session: Session) -> None:
        self.current = session
        self._resumed = True

    def mark_gap(self) -> None:
        self._fresh = True
        self._pending = None
        self._end_streak = []
        self._soc_hist = []
        if self.current is not None:
            self.current.flags.add(FLAG_GAP)
            self._resumed = True

    def update(self, s: Snapshot, outage_active: bool = False,
               last_outage_end_ts: float | None = None) -> list[Session]:
        if not s.responded:
            return []
        d = self._direction(s)
        finished: list[Session] = []
        cur = self.current
        if cur is not None:
            wanted = CHARGING if cur.kind == "charge" else DISCHARGING
            if self._resumed and self._fresh and d != wanted:
                cur.flags.add(FLAG_ENDED_WHILE_OFF)
                finished.append(self._finish(cur, cur.last_ts, cur.last_soc))
            elif d == wanted:
                self._end_streak = []
                self._accumulate(cur, s)
                if cur.kind == "charge" and s.soc_pct is not None and s.soc_pct >= 100:
                    finished.append(self._finish(cur, s.ts, s.soc_pct))
            else:
                self._end_streak.append((d, s))
                if len(self._end_streak) >= 2:
                    first_dir, first = self._end_streak[0]
                    end_soc = first.soc_pct if first.soc_pct is not None else cur.last_soc
                    finished.append(self._finish(cur, first.ts, end_soc))
                    if first_dir in KIND_OF:
                        self._pending = (first_dir, first, False)

        if self.current is None:
            full = d == CHARGING and s.soc_pct is not None and s.soc_pct >= 100
            if d in KIND_OF and not full:
                if self._pending is not None and self._pending[0] == d:
                    _, first, first_fresh = self._pending
                    self.current = self._start(d, first, first_fresh, outage_active, last_outage_end_ts)
                    self._accumulate(self.current, s)
                    self._pending = None
                    self._resumed = False
                else:
                    self._pending = (d, s, self._fresh)
            else:
                self._pending = None
        self._fresh = False
        return finished

    # -- internals ---------------------------------------------------------

    def _direction(self, s: Snapshot) -> str:
        if s.soc_pct is not None:
            self._soc_hist = (self._soc_hist + [s.soc_pct])[-3:]
        d = power_direction(s.power_w)
        if d is not None:
            return d
        if len(self._soc_hist) == 3:
            diff = self._soc_hist[-1] - self._soc_hist[0]
            if diff > 0:
                return CHARGING
            if diff < 0:
                return DISCHARGING
        return IDLE

    def _start(self, d: str, first: Snapshot, fresh: bool, outage_active: bool,
               last_outage_end_ts: float | None) -> Session:
        kind = KIND_OF[d]
        if kind == "discharge" and outage_active:
            cause = "outage"
        elif (kind == "charge" and last_outage_end_ts is not None
              and 0 <= first.ts - last_outage_end_ts <= AFTER_OUTAGE_WINDOW_S):
            cause = "after_outage"
        elif kind == "charge" and first.soc_pct is not None and first.soc_pct <= self.reserve + 2:
            cause = "after_full_discharge"
        else:
            cause = "other"
        session = Session(kind=kind, start_ts=first.ts, start_soc=first.soc_pct, cause=cause,
                          last_ts=first.ts, last_soc=first.soc_pct)
        if fresh:
            session.flags.add(FLAG_STARTED_BEFORE_APP)
        self._accumulate(session, first, integrate=False)
        return session

    @staticmethod
    def _accumulate(session: Session, s: Snapshot, integrate: bool = True) -> None:
        counter = s.counter_in_wh if session.kind == "charge" else s.counter_out_wh
        if counter is not None:
            if session.last_counter is not None and counter >= session.last_counter:
                session.counter_wh = (session.counter_wh or 0.0) + (counter - session.last_counter)
            elif session.counter_wh is None:
                session.counter_wh = 0.0
            session.last_counter = counter  # a lower value means a counter reset: rebase
        if integrate and s.power_w is not None:
            dt = min(max(0.0, s.ts - session.last_ts), INTEGRATION_MAX_DT_S)
            session.integrated_wh += abs(s.power_w) * dt / 3600
        session.last_ts = s.ts
        if s.soc_pct is not None:
            session.last_soc = s.soc_pct

    def _finish(self, session: Session, end_ts: float, end_soc: int | None) -> Session:
        session.end_ts = end_ts
        session.end_soc = end_soc
        session.energy_wh = session.energy_so_far()
        hours = session.duration_s / 3600
        session.avg_power_w = session.energy_wh / hours if hours > 0 else None
        self.current = None
        self._end_streak = []
        self._resumed = False
        return session


def typical_full_charge_s(sessions: list[Session]) -> float | None:
    """Average of the last 5 complete charge sessions, scaled to 20 → 100 %."""
    complete = [
        s for s in sorted(sessions, key=lambda x: x.start_ts)
        if s.kind == "charge" and not s.is_open and s.quality == "complete"
        and s.start_soc is not None and s.end_soc is not None and s.end_soc > s.start_soc
    ][-5:]
    if not complete:
        return None
    seconds_per_pct = [s.duration_s / (s.end_soc - s.start_soc) for s in complete]
    return sum(seconds_per_pct) / len(seconds_per_pct) * 80


def longest_backup(sessions: list[Session]) -> Session | None:
    complete = [s for s in sessions if s.kind == "discharge" and not s.is_open and s.quality == "complete"]
    return max(complete, key=lambda s: s.duration_s, default=None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_sessions.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/sessions.py tests/test_sessions.py
git commit -m "feat: charge/discharge session detection with quality flags"
```

---

### Task 7: Energy per day/month/year from lifetime counters

**Files:**
- Create: `marstek_monitor/core/energy.py`
- Test: `tests/test_energy.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) CounterReading(ts: float, in_wh: float, out_wh: float)`
  - `@dataclass(frozen=True) EnergyBar(first: date, last: date, charged_wh: float, discharged_wh: float, combined: bool)`
  - `@dataclass(frozen=True) Lifetime(charged_wh: float, discharged_wh: float, cycles: float | None, efficiency: float | None)`
  - `COMBINE_GAP_S = 3600`
  - `bars(readings: list[CounterReading], period: str, tz: tzinfo | None = None) -> list[EnergyBar]`, where `period` is `"day" | "month" | "year"` and `tz=None` means system local time
  - `bars_in_range(bars: list[EnergyBar], first: date, last: date) -> list[EnergyBar]`
  - `lifetime(latest: CounterReading | None, rated_wh: float | None) -> Lifetime | None`
  - `add_months(d: date, n: int) -> date` (first day of the shifted month)

- [ ] **Step 1: Write the failing tests**

`tests/test_energy.py`:

```python
from datetime import date, datetime, timedelta, timezone

import pytest

from marstek_monitor.core.energy import CounterReading, add_months, bars, bars_in_range, lifetime

UTC = timezone.utc


def ts(y, m, d, h=0, mi=0, tz=UTC):
    return datetime(y, m, d, h, mi, tzinfo=tz).timestamp()


def r(t, cin, cout):
    return CounterReading(t, cin, cout)


def test_same_day_sums():
    result = bars([r(ts(2026, 10, 1, 8), 1000, 500), r(ts(2026, 10, 1, 12), 1600, 500),
                   r(ts(2026, 10, 1, 20), 1600, 1100)], "day", UTC)
    assert len(result) == 1
    b = result[0]
    assert (b.first, b.last, b.charged_wh, b.discharged_wh, b.combined) == (
        date(2026, 10, 1), date(2026, 10, 1), 600, 600, False)


def test_counter_reset_never_negative():
    result = bars([r(ts(2026, 10, 1, 8), 1000, 500), r(ts(2026, 10, 1, 9), 10, 5),
                   r(ts(2026, 10, 1, 10), 110, 55)], "day", UTC)
    assert (result[0].charged_wh, result[0].discharged_wh) == (100, 50)


def test_short_gap_across_midnight_is_split_proportionally():
    result = bars([r(ts(2026, 10, 1, 23, 50), 1000, 0), r(ts(2026, 10, 2, 0, 10), 1200, 0)], "day", UTC)
    assert [(b.first, b.charged_wh) for b in result] == [
        (date(2026, 10, 1), pytest.approx(100)), (date(2026, 10, 2), pytest.approx(100))]


def test_long_gap_combines_days_into_one_bar():
    result = bars([
        r(ts(2026, 10, 1, 20), 1000, 0), r(ts(2026, 10, 1, 22), 1100, 0),
        r(ts(2026, 10, 4, 9), 1900, 300), r(ts(2026, 10, 4, 12), 2000, 300),
    ], "day", UTC)
    assert len(result) == 1
    b = result[0]
    assert (b.first, b.last, b.charged_wh, b.discharged_wh, b.combined) == (
        date(2026, 10, 1), date(2026, 10, 4), 1000, 300, True)


def test_monthly_bars():
    result = bars([r(ts(2026, 9, 30, 23, 50), 0, 0), r(ts(2026, 10, 1, 0, 10), 200, 0),
                   r(ts(2026, 10, 15), 500, 100)], "month", UTC)
    assert [(b.first, b.last) for b in result] == [
        (date(2026, 9, 1), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 31))]
    assert result[0].charged_wh == pytest.approx(100)
    assert result[1].charged_wh == pytest.approx(400) and result[1].discharged_wh == 100


def test_yearly_bars():
    result = bars([r(ts(2026, 1, 5), 0, 0), r(ts(2026, 6, 5), 700, 600)], "year", UTC)
    assert [(b.first, b.last, b.charged_wh) for b in result] == [(date(2026, 1, 1), date(2026, 12, 31), 700)]


def test_local_timezone_is_used_for_day_boundaries():
    kyiv_summer = timezone(timedelta(hours=3))
    result = bars([r(ts(2026, 10, 1, 20, 50), 0, 0), r(ts(2026, 10, 1, 21, 10), 200, 0)], "day", kyiv_summer)
    assert [b.first for b in result] == [date(2026, 10, 1), date(2026, 10, 2)]


def test_fewer_than_two_readings():
    assert bars([], "day", UTC) == []
    assert bars([r(0, 1, 1)], "day", UTC) == []


def test_bars_in_range():
    result = bars([
        r(ts(2026, 10, 1, 23, 50), 0, 0), r(ts(2026, 10, 2, 0, 10), 20, 0), r(ts(2026, 10, 2, 9), 30, 0),
    ], "day", UTC)
    assert len(result) == 2
    assert [b.first for b in bars_in_range(result, date(2026, 10, 2), date(2026, 10, 2))] == [date(2026, 10, 2)]


def test_lifetime():
    life = lifetime(r(0, 10000, 9000), 5120)
    assert life.cycles == pytest.approx(9000 / 5120)
    assert life.efficiency == pytest.approx(0.9)
    assert lifetime(None, 5120) is None
    empty = lifetime(r(0, 0, 0), None)
    assert empty.cycles is None and empty.efficiency is None


def test_add_months():
    assert add_months(date(2026, 10, 17), -11) == date(2025, 11, 1)
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_energy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.energy'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/energy.py`:

```python
"""Energy per day/month/year from the battery's lifetime counters (spec §6.6, pure logic).

Energy between two counter readings is attributed to the period both readings fall in.
Readings that straddle a period boundary within COMBINE_GAP_S are split in proportion
to time. Longer gaps (PC off) merge all periods they span into one combined bar, which
keeps totals exact while the per-period split is unknown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, tzinfo

COMBINE_GAP_S = 3600.0


@dataclass(frozen=True)
class CounterReading:
    ts: float
    in_wh: float
    out_wh: float


@dataclass(frozen=True)
class EnergyBar:
    first: date
    last: date
    charged_wh: float
    discharged_wh: float
    combined: bool


@dataclass(frozen=True)
class Lifetime:
    charged_wh: float
    discharged_wh: float
    cycles: float | None
    efficiency: float | None


def add_months(d: date, n: int) -> date:
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)


def _local_date(ts: float, tz: tzinfo | None) -> date:
    return datetime.fromtimestamp(ts, tz).date()


def _key(d: date, period: str) -> date:
    if period == "day":
        return d
    if period == "month":
        return d.replace(day=1)
    return date(d.year, 1, 1)


def _next_key(k: date, period: str) -> date:
    if period == "day":
        return k + timedelta(days=1)
    if period == "month":
        return add_months(k, 1)
    return date(k.year + 1, 1, 1)


def _last_day(k: date, period: str) -> date:
    return k if period == "day" else _next_key(k, period) - timedelta(days=1)


def _start_ts(k: date, tz: tzinfo | None) -> float:
    return datetime.combine(k, dtime.min, tzinfo=tz).timestamp()


def bars(readings: list[CounterReading], period: str, tz: tzinfo | None = None) -> list[EnergyBar]:
    rs = sorted(readings, key=lambda x: x.ts)
    if len(rs) < 2:
        return []
    totals: dict[date, list[float]] = {}
    merges: list[tuple[date, date]] = []

    def add(k: date, din: float, dout: float) -> None:
        t = totals.setdefault(k, [0.0, 0.0])
        t[0] += din
        t[1] += dout

    for a, b in zip(rs, rs[1:]):
        din = max(0.0, b.in_wh - a.in_wh)
        dout = max(0.0, b.out_wh - a.out_wh)
        ka = _key(_local_date(a.ts, tz), period)
        kb = _key(_local_date(b.ts, tz), period)
        if ka == kb:
            add(ka, din, dout)
        elif b.ts - a.ts <= COMBINE_GAP_S and _next_key(ka, period) == kb:
            frac = (_start_ts(kb, tz) - a.ts) / (b.ts - a.ts)
            frac = min(1.0, max(0.0, frac))
            add(ka, din * frac, dout * frac)
            add(kb, din * (1 - frac), dout * (1 - frac))
        else:
            add(ka, din, dout)
            add(kb, 0.0, 0.0)
            merges.append((ka, kb))

    keys: list[date] = []
    k = _key(_local_date(rs[0].ts, tz), period)
    last_key = _key(_local_date(rs[-1].ts, tz), period)
    while k <= last_key:
        keys.append(k)
        k = _next_key(k, period)

    joined: set[date] = set()  # keys merged with their successor
    for ka, kb in merges:
        k = ka
        while k < kb:
            joined.add(k)
            k = _next_key(k, period)

    out: list[EnergyBar] = []
    group: list[date] = []
    for k in keys:
        group.append(k)
        if k in joined:
            continue
        charged = sum(totals.get(g, [0.0, 0.0])[0] for g in group)
        discharged = sum(totals.get(g, [0.0, 0.0])[1] for g in group)
        out.append(EnergyBar(group[0], _last_day(group[-1], period), charged, discharged, len(group) > 1))
        group = []
    return out


def bars_in_range(items: list[EnergyBar], first: date, last: date) -> list[EnergyBar]:
    return [b for b in items if b.last >= first and b.first <= last]


def lifetime(latest: CounterReading | None, rated_wh: float | None) -> Lifetime | None:
    if latest is None:
        return None
    cycles = latest.out_wh / rated_wh if rated_wh else None
    efficiency = latest.out_wh / latest.in_wh if latest.in_wh > 0 else None
    return Lifetime(latest.in_wh, latest.out_wh, cycles, efficiency)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_energy.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/energy.py tests/test_energy.py
git commit -m "feat: energy bars from lifetime counters with gap-combined bars"
```

---

### Task 8: Events and SQLite storage

**Files:**
- Create: `marstek_monitor/core/events.py`, `marstek_monitor/core/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes:
  - `Snapshot`, `snapshot_to_dict`, `snapshot_from_dict` (Task 4)
  - `Session` (Task 6)
  - `CounterReading` (Task 7)
- Produces:
  - `@dataclass Event` with fields:
    - `ts: float`
    - `kind: str` (`"notification" | "system"`)
    - `rule_id: str`
    - `priority: str` (`"normal" | "critical"`)
    - `title_key: str`, `body_key: str`, `params: dict`
    - `desktop: str = "off"`: one of `off | pending | sent | held | failed`
    - `telegram: str = "off"`: one of `off | pending | sent | retrying | held | failed`
    - `id: int | None = None`
  - `Storage(path: str | Path)` with:
    - `add_sample(s)`, `samples_since(ts) -> list[Snapshot]`
    - `add_counter(ts, in_wh, out_wh, force=False) -> bool`, `counters(since=None) -> list[CounterReading]`, `last_counter() -> CounterReading | None`
    - `save_session(s) -> int` (sets `s.id`), `sessions(since=None) -> list[Session]` (oldest first), `open_session() -> Session | None`
    - `add_event(e) -> int`, `set_delivery(event_id, channel, status)`, `events(limit=500) -> list[Event]` (newest first)
    - `purge(now, samples_days)`
    - `get_meta(key, default=None)`, `set_meta(key, value)`
    - `close()`
  - constants `COUNTER_MIN_INTERVAL_S = 600`, `EVENTS_RETENTION_DAYS = 90`

- [ ] **Step 1: Write the failing tests**

`tests/test_storage.py`:

```python
import pytest

from marstek_monitor.core.events import Event
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage

DAY = 86400


@pytest.fixture
def db(tmp_path):
    storage = Storage(tmp_path / "history.db")
    yield storage
    storage.close()


def event(ts=0.0, **kw):
    base = dict(ts=ts, kind="notification", rule_id="soc_below", priority="normal",
                title_key="n.soc_below.title", body_key="n.soc_below.body", params={"pct": 40, "soc": 39},
                desktop="pending", telegram="off")
    base.update(kw)
    return Event(**base)


def test_sample_roundtrip(db):
    s = Snapshot(ts=10.0, responded=True, soc_pct=55, power_w=-300.0, failed_methods=("Wifi.GetStatus",))
    db.add_sample(s)
    assert db.samples_since(0) == [s]
    assert db.samples_since(11) == []


def test_counter_throttle_and_force(db):
    assert db.add_counter(0, 100, 50) is True
    assert db.add_counter(300, 110, 50) is False
    assert db.add_counter(700, 120, 50) is True
    assert db.add_counter(800, 130, 50, force=True) is True
    assert [c.ts for c in db.counters()] == [0, 700, 800]
    assert db.last_counter().in_wh == 130


def test_session_insert_update_and_open(db):
    s = Session(kind="charge", start_ts=10, start_soc=40, flags={"gap"})
    sid = db.save_session(s)
    assert s.id == sid
    assert db.open_session() == s
    s.end_ts, s.end_soc = 100, 80
    db.save_session(s)
    assert db.open_session() is None
    stored = db.sessions()
    assert len(stored) == 1 and stored[0].end_ts == 100 and stored[0].flags == {"gap"}


def test_events_and_delivery(db):
    first = db.add_event(event(ts=1))
    db.add_event(event(ts=2, rule_id="offline"))
    db.set_delivery(first, "telegram", "sent")
    items = db.events()
    assert [e.rule_id for e in items] == ["offline", "soc_below"]
    assert items[1].telegram == "sent" and items[1].params == {"pct": 40, "soc": 39}
    with pytest.raises(ValueError):
        db.set_delivery(first, "email", "sent")


def test_purge(db):
    now = 1000 * DAY
    db.add_sample(Snapshot(ts=now - 40 * DAY, responded=True))
    db.add_sample(Snapshot(ts=now - 1 * DAY, responded=True))
    db.add_event(event(ts=now - 100 * DAY))
    db.add_event(event(ts=now - 1 * DAY))
    db.purge(now, samples_days=30)
    assert len(db.samples_since(0)) == 1
    assert len(db.events()) == 1


def test_meta(db):
    assert db.get_meta("fw_version") is None
    assert db.get_meta("fw_version", "x") == "x"
    db.set_meta("fw_version", "144")
    assert db.get_meta("fw_version") == "144"


def test_reopen_keeps_data(tmp_path):
    path = tmp_path / "history.db"
    first = Storage(path)
    first.add_counter(0, 1, 2)
    first.close()
    second = Storage(path)
    assert len(second.counters()) == 1
    second.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.events'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/events.py`:

```python
"""Notification and system events (stored in the Events tab and delivered to channels)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    ts: float
    kind: str                 # "notification" | "system"
    rule_id: str
    priority: str             # "normal" | "critical"
    title_key: str
    body_key: str
    params: dict = field(default_factory=dict)
    desktop: str = "off"      # off | pending | sent | held | failed
    telegram: str = "off"     # off | pending | sent | retrying | held | failed
    id: int | None = None
```

`marstek_monitor/core/storage.py`:

```python
"""SQLite persistence. All timestamps are UTC epoch seconds (spec §6.4)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .energy import CounterReading
from .events import Event
from .sessions import Session
from .snapshot import Snapshot, snapshot_from_dict, snapshot_to_dict

SCHEMA_VERSION = 1
COUNTER_MIN_INTERVAL_S = 600
EVENTS_RETENTION_DAYS = 90
DAY_S = 86400

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS counters (id INTEGER PRIMARY KEY, ts REAL NOT NULL,
    in_wh REAL NOT NULL, out_wh REAL NOT NULL);
CREATE INDEX IF NOT EXISTS counters_ts ON counters(ts);
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
    start_ts REAL NOT NULL, end_ts REAL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions(start_ts);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
    rule_id TEXT NOT NULL, priority TEXT NOT NULL, title_key TEXT NOT NULL, body_key TEXT NOT NULL,
    params TEXT NOT NULL, desktop TEXT NOT NULL, telegram TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        self.conn.close()

    # samples
    def add_sample(self, s: Snapshot) -> None:
        self.conn.execute("INSERT INTO samples(ts, data) VALUES (?, ?)", (s.ts, json.dumps(snapshot_to_dict(s))))
        self.conn.commit()

    def samples_since(self, ts: float) -> list[Snapshot]:
        rows = self.conn.execute("SELECT data FROM samples WHERE ts >= ? ORDER BY ts", (ts,))
        return [snapshot_from_dict(json.loads(row["data"])) for row in rows]

    # counters
    def add_counter(self, ts: float, in_wh: float, out_wh: float, force: bool = False) -> bool:
        last = self.last_counter()
        if not force and last is not None and ts - last.ts < COUNTER_MIN_INTERVAL_S:
            return False
        self.conn.execute("INSERT INTO counters(ts, in_wh, out_wh) VALUES (?, ?, ?)", (ts, in_wh, out_wh))
        self.conn.commit()
        return True

    def counters(self, since: float | None = None) -> list[CounterReading]:
        rows = self.conn.execute("SELECT ts, in_wh, out_wh FROM counters WHERE ts >= ? ORDER BY ts",
                                 (since if since is not None else -1e18,))
        return [CounterReading(row["ts"], row["in_wh"], row["out_wh"]) for row in rows]

    def last_counter(self) -> CounterReading | None:
        row = self.conn.execute("SELECT ts, in_wh, out_wh FROM counters ORDER BY ts DESC LIMIT 1").fetchone()
        return CounterReading(row["ts"], row["in_wh"], row["out_wh"]) if row else None

    # sessions
    def save_session(self, s: Session) -> int:
        data = json.dumps(s.to_dict())
        if s.id is None:
            cur = self.conn.execute("INSERT INTO sessions(kind, start_ts, end_ts, data) VALUES (?, ?, ?, ?)",
                                    (s.kind, s.start_ts, s.end_ts, data))
            s.id = cur.lastrowid
            self.conn.execute("UPDATE sessions SET data = ? WHERE id = ?", (json.dumps(s.to_dict()), s.id))
        else:
            self.conn.execute("UPDATE sessions SET kind = ?, start_ts = ?, end_ts = ?, data = ? WHERE id = ?",
                              (s.kind, s.start_ts, s.end_ts, data, s.id))
        self.conn.commit()
        return s.id

    def sessions(self, since: float | None = None) -> list[Session]:
        rows = self.conn.execute("SELECT id, data FROM sessions WHERE start_ts >= ? ORDER BY start_ts",
                                 (since if since is not None else -1e18,))
        return [self._session(row) for row in rows]

    def open_session(self) -> Session | None:
        row = self.conn.execute(
            "SELECT id, data FROM sessions WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1").fetchone()
        return self._session(row) if row else None

    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        s = Session.from_dict(json.loads(row["data"]))
        s.id = row["id"]
        return s

    # events
    def add_event(self, e: Event) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(ts, kind, rule_id, priority, title_key, body_key, params, desktop, telegram)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.ts, e.kind, e.rule_id, e.priority, e.title_key, e.body_key,
             json.dumps(e.params, ensure_ascii=False), e.desktop, e.telegram))
        self.conn.commit()
        return cur.lastrowid

    def set_delivery(self, event_id: int, channel: str, status: str) -> None:
        if channel not in ("desktop", "telegram"):
            raise ValueError(f"unknown channel {channel!r}")
        self.conn.execute(f"UPDATE events SET {channel} = ? WHERE id = ?", (status, event_id))
        self.conn.commit()

    def events(self, limit: int = 500) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
        return [
            Event(ts=row["ts"], kind=row["kind"], rule_id=row["rule_id"], priority=row["priority"],
                  title_key=row["title_key"], body_key=row["body_key"], params=json.loads(row["params"]),
                  desktop=row["desktop"], telegram=row["telegram"], id=row["id"])
            for row in rows
        ]

    # maintenance
    def purge(self, now: float, samples_days: int) -> None:
        self.conn.execute("DELETE FROM samples WHERE ts < ?", (now - samples_days * DAY_S,))
        self.conn.execute("DELETE FROM events WHERE ts < ?", (now - EVENTS_RETENTION_DAYS * DAY_S,))
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                          (key, value))
        self.conn.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_storage.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/events.py marstek_monitor/core/storage.py tests/test_storage.py
git commit -m "feat: SQLite storage for samples, counters, sessions, events"
```

---
### Task 9: Rules engine and quiet-hours routing

**Files:**
- Create: `marstek_monitor/core/rules.py`
- Test: `tests/test_rules.py`

**Interfaces:**
- Consumes:
  - `Event` (Task 8)
  - `Session` (Task 6)
  - `Snapshot` (Task 4)
  - settings shape (Task 3)
- Produces:
  - `@dataclass RuleContext` with fields:
    - `now: float`, `snapshot: Snapshot | None`, `online: bool`
    - `grid_event: str | None = None`, `grid_state: str = "unknown"`
    - `minutes_left: float | None = None`, `outage_duration_s: float | None = None`
    - `finished_sessions: list[Session] = []`
    - `fw_change: tuple[int | None, int] | None = None`
    - `offline_polls: int = 3`
  - `RulesEngine(settings: dict)` with:
    - attribute `.settings` (reassignable)
    - `.evaluate(ctx) -> list[Event]`
    - `.monitor_event(now: float, started: bool) -> Event | None`
    - `.test_event(now: float, desktop: bool, telegram: bool) -> Event`
  - `in_quiet_hours(qh: dict, local_minutes: int) -> bool`, `route(e: Event, qh: dict, local_minutes: int) -> Event`
- Event keys produced (used by i18n in Task 12). Each is an `.title`/`.body` pair unless noted:
  - `n.soc_below`, `n.soc_reached`
  - `n.temp_high`, `n.temp_low` (the body key is `n.temp.body`)
  - `n.blocked_charge`, `n.blocked_discharge`
  - `n.offline`, `n.online`
  - `n.grid_lost`, `n.grid_restored`, `n.backup_left`
  - `n.charge_session.title`, `n.discharge_session.title` (the body key is `n.session.body`)
  - `n.firmware`, `n.monitor_started`, `n.monitor_stopped`, `n.test`

- [ ] **Step 1: Write the failing tests**

`tests/test_rules.py`:

```python
from marstek_monitor import settings as settings_mod
from marstek_monitor.core.rules import RuleContext, RulesEngine, in_quiet_hours, route
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot

MIN = 60


def snap(soc=60, temp=25.0, charge=True, discharge=True):
    return Snapshot(ts=0, responded=True, soc_pct=soc, temp_c=temp, charge_allowed=charge, discharge_allowed=discharge)


def engine(**changes):
    cfg = settings_mod.defaults()
    for path, value in changes.items():
        section, key = path.split("__")
        cfg["notifications"][section][key] = value
    return RulesEngine(cfg)


def run(eng, now, s, online=True, **kw):
    return eng.evaluate(RuleContext(now=now, snapshot=s, online=online, **kw))


def keys(events):
    return [e.title_key for e in events]


def test_soc_below_fires_once_per_crossing():
    eng = engine()
    assert run(eng, 0, snap(soc=45)) == []
    events = run(eng, 60, snap(soc=39))
    assert keys(events) == ["n.soc_below.title"]
    assert events[0].params == {"pct": 40, "soc": 39}
    assert (events[0].priority, events[0].desktop, events[0].telegram) == ("normal", "pending", "off")
    assert run(eng, 120, snap(soc=38)) == []


def test_soc_below_rearms_after_margin():
    eng = engine()
    run(eng, 0, snap(soc=39))
    assert run(eng, 60, snap(soc=41)) == []
    assert run(eng, 120, snap(soc=39)) == []
    assert run(eng, 180, snap(soc=42)) == []
    assert keys(run(eng, 240, snap(soc=39))) == ["n.soc_below.title"]


def test_critical_level_goes_to_telegram_and_repeats():
    eng = engine()
    events = run(eng, 0, snap(soc=19))
    assert [(e.params["pct"], e.priority, e.telegram) for e in events] == [
        (40, "normal", "off"), (20, "critical", "pending")]
    assert run(eng, 29 * MIN, snap(soc=19)) == []
    again = run(eng, 30 * MIN, snap(soc=19))
    assert [e.params["pct"] for e in again] == [20]


def test_disabled_level_does_not_fire():
    eng = engine()
    eng.settings["notifications"]["soc_below"][0]["enabled"] = False
    assert [e.params["pct"] for e in run(eng, 0, snap(soc=30))] == []


def test_soc_reached():
    eng = engine()
    assert run(eng, 0, snap(soc=99)) == []
    assert keys(run(eng, 60, snap(soc=100))) == ["n.soc_reached.title"]
    assert run(eng, 120, snap(soc=99)) == []
    assert run(eng, 180, snap(soc=98)) == []
    assert keys(run(eng, 240, snap(soc=100))) == ["n.soc_reached.title"]


def test_temperature_high_and_low():
    eng = engine()
    high = run(eng, 0, snap(temp=46.4))
    assert keys(high) == ["n.temp_high.title"] and high[0].params == {"temp": 46, "limit": 45}
    assert keys(run(eng, 60, snap(temp=4.0))) == ["n.temp_low.title"]


def test_discharge_blocked_repeats_hourly_and_rearms():
    eng = engine()
    events = run(eng, 0, snap(discharge=False))
    assert keys(events) == ["n.blocked_discharge.title"] and events[0].priority == "critical"
    assert run(eng, 59 * MIN, snap(discharge=False)) == []
    assert keys(run(eng, 60 * MIN, snap(discharge=False))) == ["n.blocked_discharge.title"]
    assert run(eng, 61 * MIN, snap(discharge=True)) == []
    assert keys(run(eng, 62 * MIN, snap(discharge=False))) == ["n.blocked_discharge.title"]


def test_offline_then_back_online():
    eng = engine()
    offline = run(eng, 100, None, online=False, offline_polls=3)
    assert keys(offline) == ["n.offline.title"] and offline[0].params == {"polls": 3}
    assert run(eng, 160, None, online=False) == []
    back = run(eng, 700, snap(), online=True)
    assert keys(back) == ["n.online.title"] and back[0].params == {"duration_s": 600}


def test_stale_snapshot_is_ignored_while_offline():
    eng = engine()
    assert keys(run(eng, 0, snap(soc=10), online=False)) == ["n.offline.title"]


def test_grid_events_only_when_enabled():
    eng = engine()
    assert run(eng, 0, snap(), grid_event="lost") == []
    eng.settings["notifications"]["grid"]["enabled"] = True
    assert keys(run(eng, 0, snap(soc=90), grid_event="lost")) == ["n.grid_lost.title"]
    restored = run(eng, 60, snap(), grid_event="restored", outage_duration_s=3600)
    assert keys(restored) == ["n.grid_restored.title"] and restored[0].params == {"outage_s": 3600}


def test_backup_time_left():
    eng = engine()
    eng.settings["notifications"]["backup_left"]["enabled"] = True
    assert keys(run(eng, 0, snap(soc=50), grid_state="lost", minutes_left=20)) == ["n.backup_left.title"]
    assert run(eng, 60, snap(soc=50), grid_state="lost", minutes_left=25) == []
    assert run(eng, 120, snap(soc=50), grid_state="lost", minutes_left=34) == []
    assert keys(run(eng, 180, snap(soc=50), grid_state="lost", minutes_left=20)) == ["n.backup_left.title"]


def test_finished_sessions():
    eng = engine()
    charge = Session(kind="charge", start_ts=0, start_soc=20, end_ts=3600, end_soc=100, energy_wh=4000)
    discharge = Session(kind="discharge", start_ts=0, start_soc=100, end_ts=1800, end_soc=70, energy_wh=1500)
    events = run(eng, 0, snap(), finished_sessions=[charge, discharge])
    assert keys(events) == ["n.charge_session.title", "n.discharge_session.title"]
    assert events[0].params == {"from_soc": 20, "to_soc": 100, "duration_s": 3600, "energy_wh": 4000}
    assert (events[0].telegram, events[1].telegram) == ("off", "pending")


def test_firmware_change():
    events = run(engine(), 0, snap(), fw_change=(144, 150))
    assert keys(events) == ["n.firmware.title"] and events[0].params == {"old": 144, "new": 150}


def test_monitor_event_is_telegram_only():
    eng = engine()
    e = eng.monitor_event(0, started=True)
    assert (e.title_key, e.desktop, e.telegram) == ("n.monitor_started.title", "off", "pending")
    eng.settings["notifications"]["monitor"]["enabled"] = False
    assert eng.monitor_event(0, started=False) is None


def test_test_event():
    e = engine().test_event(0, desktop=True, telegram=False)
    assert (e.title_key, e.desktop, e.telegram) == ("n.test.title", "pending", "off")


def test_in_quiet_hours():
    qh = {"enabled": True, "from": "23:00", "to": "07:00"}
    assert in_quiet_hours(qh, 23 * 60) and in_quiet_hours(qh, 6 * 60 + 59)
    assert not in_quiet_hours(qh, 7 * 60) and not in_quiet_hours(qh, 12 * 60)
    day = {"enabled": True, "from": "13:00", "to": "15:00"}
    assert in_quiet_hours(day, 14 * 60) and not in_quiet_hours(day, 16 * 60)


def test_route():
    qh = {"enabled": True, "from": "23:00", "to": "07:00", "critical_bypass": True, "silence_telegram": False}
    normal = engine().test_event(0, desktop=True, telegram=True)
    held = route(normal, qh, 23 * 60 + 30)
    assert (held.desktop, held.telegram) == ("held", "pending")
    assert route(normal, qh, 12 * 60) == normal
    assert route(normal, dict(qh, silence_telegram=True), 0).telegram == "held"
    critical = RulesEngine(settings_mod.defaults()).evaluate(
        RuleContext(now=0, snapshot=snap(discharge=False), online=True))[0]
    assert route(critical, qh, 0).desktop == "pending"
    assert route(critical, dict(qh, critical_bypass=False), 0).desktop == "held"
    assert route(normal, dict(qh, enabled=False), 0) == normal
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.rules'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/rules.py`:

```python
"""Notification rules (spec §6.7) and quiet-hours routing. Pure logic, no Qt.

Every threshold rule fires once when its condition becomes true, re-arms only after
the value moves back past the threshold by the re-arm margin, and can repeat as a
reminder every `repeat_min` minutes while the condition lasts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .events import Event
from .sessions import Session
from .snapshot import Snapshot

BLOCKED_KEYS = {
    "charge": ("n.blocked_charge.title", "n.blocked_charge.body"),
    "discharge": ("n.blocked_discharge.title", "n.blocked_discharge.body"),
}


class _Latch:
    def __init__(self) -> None:
        self.fired = False
        self.last = 0.0

    def reset(self) -> None:
        self.fired = False

    def step(self, active: bool, rearmed: bool, now: float, repeat_min: int) -> bool:
        if self.fired:
            if rearmed:
                self.fired = False
                return False
            if active and repeat_min > 0 and now - self.last >= repeat_min * 60:
                self.last = now
                return True
            return False
        if active:
            self.fired = True
            self.last = now
            return True
        return False


@dataclass
class RuleContext:
    now: float
    snapshot: Snapshot | None
    online: bool
    grid_event: str | None = None
    grid_state: str = "unknown"
    minutes_left: float | None = None
    outage_duration_s: float | None = None
    finished_sessions: list[Session] = field(default_factory=list)
    fw_change: tuple[int | None, int] | None = None
    offline_polls: int = 3


class RulesEngine:
    def __init__(self, settings: dict):
        self.settings = settings
        self._latches: dict[str, _Latch] = {}
        self._offline_since: float | None = None

    def _latch(self, key: str) -> _Latch:
        return self._latches.setdefault(key, _Latch())

    @staticmethod
    def _event(now: float, rule_id: str, priority: str, title_key: str, body_key: str,
               params: dict, cfg: dict) -> Event:
        return Event(ts=now, kind="notification", rule_id=rule_id, priority=priority,
                     title_key=title_key, body_key=body_key, params=params,
                     desktop="pending" if cfg.get("desktop") else "off",
                     telegram="pending" if cfg.get("telegram") else "off")

    def evaluate(self, ctx: RuleContext) -> list[Event]:
        n = self.settings["notifications"]
        out: list[Event] = []
        s = ctx.snapshot if ctx.online else None
        if s is not None:
            out += self._battery_rules(s, ctx.now, n, self.settings["advanced"])
        out += self._offline_rule(ctx, n["offline"])
        out += self._grid_rules(ctx, n)
        out += self._session_rules(ctx, n)
        fw = n["firmware"]
        if ctx.fw_change and fw["enabled"]:
            out.append(self._event(ctx.now, "firmware", "normal", "n.firmware.title", "n.firmware.body",
                                   {"old": ctx.fw_change[0], "new": ctx.fw_change[1]}, fw))
        return out

    def _battery_rules(self, s: Snapshot, now: float, n: dict, adv: dict) -> list[Event]:
        out: list[Event] = []
        if s.soc_pct is not None:
            for i, level in enumerate(n["soc_below"]):
                latch = self._latch(f"soc_below.{i}")
                if not level["enabled"]:
                    latch.reset()
                    continue
                active = s.soc_pct < level["pct"]
                rearmed = s.soc_pct >= level["pct"] + adv["rearm_pct"]
                if latch.step(active, rearmed, now, level["repeat_min"]):
                    out.append(self._event(now, "soc_below", level["priority"], "n.soc_below.title",
                                           "n.soc_below.body", {"pct": level["pct"], "soc": s.soc_pct}, level))
            reached = n["soc_reached"]
            latch = self._latch("soc_reached")
            if reached["enabled"]:
                if latch.step(s.soc_pct >= reached["pct"], s.soc_pct <= reached["pct"] - adv["rearm_pct"],
                              now, reached["repeat_min"]):
                    out.append(self._event(now, "soc_reached", "normal", "n.soc_reached.title",
                                           "n.soc_reached.body", {"pct": reached["pct"], "soc": s.soc_pct}, reached))
            else:
                latch.reset()

        temp = n["temperature"]
        high, low = self._latch("temp_high"), self._latch("temp_low")
        if not temp["enabled"]:
            high.reset()
            low.reset()
        elif s.temp_c is not None:
            if high.step(s.temp_c > temp["high"], s.temp_c <= temp["high"] - adv["rearm_c"], now, temp["repeat_min"]):
                out.append(self._event(now, "temperature", "critical", "n.temp_high.title", "n.temp.body",
                                       {"temp": round(s.temp_c), "limit": temp["high"]}, temp))
            if low.step(s.temp_c < temp["low"], s.temp_c >= temp["low"] + adv["rearm_c"], now, temp["repeat_min"]):
                out.append(self._event(now, "temperature", "critical", "n.temp_low.title", "n.temp.body",
                                       {"temp": round(s.temp_c), "limit": temp["low"]}, temp))

        blocked = n["blocked"]
        for which, value in (("charge", s.charge_allowed), ("discharge", s.discharge_allowed)):
            latch = self._latch(f"blocked.{which}")
            if not blocked["enabled"]:
                latch.reset()
                continue
            if value is None:
                continue
            if latch.step(value is False, value is True, now, blocked["repeat_min"]):
                title, body = BLOCKED_KEYS[which]
                out.append(self._event(now, "blocked", "critical", title, body, {}, blocked))
        return out

    def _offline_rule(self, ctx: RuleContext, cfg: dict) -> list[Event]:
        latch = self._latch("offline")
        if not ctx.online:
            if self._offline_since is None:
                self._offline_since = ctx.now
            if cfg["enabled"] and latch.step(True, False, ctx.now, cfg["repeat_min"]):
                return [self._event(ctx.now, "offline", "critical", "n.offline.title", "n.offline.body",
                                    {"polls": ctx.offline_polls}, cfg)]
            return []
        was_fired, since = latch.fired, self._offline_since
        latch.reset()
        self._offline_since = None
        if was_fired and cfg["enabled"] and since is not None:
            return [self._event(ctx.now, "offline", "normal", "n.online.title", "n.online.body",
                                {"duration_s": ctx.now - since}, cfg)]
        return []

    def _grid_rules(self, ctx: RuleContext, n: dict) -> list[Event]:
        out: list[Event] = []
        soc = ctx.snapshot.soc_pct if ctx.snapshot is not None and ctx.online else None
        grid = n["grid"]
        if grid["enabled"] and ctx.grid_event == "lost":
            out.append(self._event(ctx.now, "grid", "critical", "n.grid_lost.title", "n.grid_lost.body",
                                   {"soc": soc if soc is not None else "?"}, grid))
        if grid["enabled"] and ctx.grid_event == "restored":
            out.append(self._event(ctx.now, "grid", "critical", "n.grid_restored.title", "n.grid_restored.body",
                                   {"outage_s": ctx.outage_duration_s or 0}, grid))
        backup = n["backup_left"]
        latch = self._latch("backup_left")
        if not backup["enabled"]:
            latch.reset()
            return out
        lost = ctx.grid_state == "lost"
        left = ctx.minutes_left
        active = lost and left is not None and left < backup["minutes"]
        rearmed = (not lost) or (left is not None and left >= backup["minutes"] * 1.1)
        if latch.step(active, rearmed, ctx.now, backup["repeat_min"]):
            out.append(self._event(ctx.now, "backup_left", "critical", "n.backup_left.title", "n.backup_left.body",
                                   {"left_s": left * 60, "soc": soc if soc is not None else "?"}, backup))
        return out

    def _session_rules(self, ctx: RuleContext, n: dict) -> list[Event]:
        out: list[Event] = []
        for session in ctx.finished_sessions:
            is_charge = session.kind == "charge"
            cfg = n["charge_session"] if is_charge else n["discharge_session"]
            if not cfg["enabled"]:
                continue
            title = "n.charge_session.title" if is_charge else "n.discharge_session.title"
            params = {
                "from_soc": session.start_soc if session.start_soc is not None else "?",
                "to_soc": session.end_soc if session.end_soc is not None else "?",
                "duration_s": session.duration_s,
                "energy_wh": session.energy_wh or 0,
            }
            out.append(self._event(ctx.now, "charge_session" if is_charge else "discharge_session",
                                   "normal", title, "n.session.body", params, cfg))
        return out

    def monitor_event(self, now: float, started: bool) -> Event | None:
        cfg = self.settings["notifications"]["monitor"]
        if not cfg["enabled"] or not cfg["telegram"]:
            return None
        title = "n.monitor_started.title" if started else "n.monitor_stopped.title"
        body = "n.monitor_started.body" if started else "n.monitor_stopped.body"
        return Event(ts=now, kind="notification", rule_id="monitor", priority="normal",
                     title_key=title, body_key=body, params={}, desktop="off", telegram="pending")

    def test_event(self, now: float, desktop: bool, telegram: bool) -> Event:
        return Event(ts=now, kind="notification", rule_id="test", priority="normal",
                     title_key="n.test.title", body_key="n.test.body", params={},
                     desktop="pending" if desktop else "off", telegram="pending" if telegram else "off")


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def in_quiet_hours(qh: dict, local_minutes: int) -> bool:
    start, end = _minutes(qh["from"]), _minutes(qh["to"])
    if start == end:
        return False
    if start < end:
        return start <= local_minutes < end
    return local_minutes >= start or local_minutes < end


def route(e: Event, qh: dict, local_minutes: int) -> Event:
    """Apply quiet hours: hold normal desktop notifications (and Telegram if configured)."""
    if not qh.get("enabled") or not in_quiet_hours(qh, local_minutes):
        return e
    if e.priority == "critical" and qh.get("critical_bypass", True):
        return e
    desktop = "held" if e.desktop == "pending" else e.desktop
    telegram = "held" if e.telegram == "pending" and qh.get("silence_telegram") else e.telegram
    return replace(e, desktop=desktop, telegram=telegram)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_rules.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/rules.py tests/test_rules.py
git commit -m "feat: notification rules with re-arm, reminders and quiet hours"
```

---

### Task 10: Poller and poller thread

**Files:**
- Create: `marstek_monitor/core/poller.py`, `marstek_monitor/core/poller_thread.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes:
  - `MarstekClient`, `DeviceInfo`, `ApiTimeout`, `ApiError`, `PortInUseError`, `ClientStopped`, `local_ip_for`, `broadcast_addresses` (Task 2)
  - `normalize`, `NormalizeConfig`, `Snapshot` (Task 4)
- Produces:
  - `@dataclass PollerConfig` with fields:
    - `ip: str`, `port: int`, `ble_mac: str = ""`
    - `local_port: int | None = None`, `local_ip: str | None = None`
    - `poll_seconds: int = 60`, `offline_after_polls: int = 3`
    - `normalize: NormalizeConfig`
    - `query_spacing_s: float = 1.0`, `timeout_s: float = 5.0`, `discovery_wait_s: float = 3.0`
    - `broadcast: tuple[str, ...] | None = None`
  - `@dataclass PollResult(ts: float, snapshot: Snapshot | None, online: bool, gap: tuple[float, float] | None = None, device: DeviceInfo | None = None, error_key: str | None = None, error_params: dict = {})`
  - `Poller(cfg, client_factory=MarstekClient, clock=time.time, raw_recorder=None)` with:
    - `.cycle() -> PollResult`, `.request_discovery()`, `.stop()`, `.close()`
    - attributes `.ip`, `.ble_mac`, `.device`
    - property `.online`
  - `poller_thread.PollerThread(poller: Poller, interval_s: float)` (a `QThread`) with:
    - signal `result(object)`
    - `.stop()`, `.wake()`
- Error keys emitted: `sys.port_in_use` (params `port`), `sys.network_error` (params `error`), `sys.firewall_hint`.

- [ ] **Step 1: Write the failing tests**

`tests/test_poller.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_poller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.poller'`

- [ ] **Step 3: Implement the poller**

`marstek_monitor/core/poller.py`:

```python
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
        except OSError as exc:
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
```

`marstek_monitor/core/poller_thread.py`:

```python
"""QThread loop around Poller: one cycle, emit, wait (interruptible)."""
from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from ..api.client import ClientStopped
from .poller import Poller

log = logging.getLogger(__name__)


class PollerThread(QThread):
    result = Signal(object)

    def __init__(self, poller: Poller, interval_s: float, parent=None):
        super().__init__(parent)
        self.poller = poller
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    r = self.poller.cycle()
                except ClientStopped:
                    break
                except Exception:
                    log.exception("Poll cycle failed")
                    r = None
                if r is not None and not self._stop.is_set():
                    self.result.emit(r)
                remaining = max(1.0, self.interval_s - (time.monotonic() - started))
                self._wake.wait(remaining)
                self._wake.clear()
        finally:
            self.poller.close()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self.poller.stop()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_poller.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/core/poller.py marstek_monitor/core/poller_thread.py tests/test_poller.py
git commit -m "feat: poller with offline detection, sleep gaps, rediscovery"
```

---

### Task 11: Monitor pipeline and LiveState

**Files:**
- Create: `marstek_monitor/core/monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes:
  - `PollResult` (Task 10)
  - `Storage` (Task 8)
  - `SessionDetector`, `Session` (Task 6)
  - `OutageDetector` (Task 5)
  - `minutes_to_full`, `minutes_left` (Task 5)
  - `RulesEngine`, `RuleContext`, `route` (Task 9)
  - `Event` (Task 8)
  - `CounterReading` (Task 7)
  - `DeviceInfo` (Task 2)
- Produces:
  - `@dataclass LiveState` with fields:
    - `snapshot: Snapshot | None = None`, `online: bool = True`, `device: DeviceInfo | None = None`
    - `grid_state: str = "unknown"`, `grid_since: float | None = None`
    - `current_session: Session | None = None`
    - `minutes_to_full: float | None = None`, `minutes_left: float | None = None`
    - `last_update_ts: float | None = None`
    - `error_key: str | None = None`, `error_params: dict = {}`
    - `history_ok: bool = True`, `counters_verified: bool = False`
  - `Monitor(settings: dict, storage: Storage | None, clock=time.time)` with:
    - attributes `.state`, `.settings`, `.storage`, `.app_start_ts`, `.outage_marks: list[float]`, `.rules`
    - pipeline and events:
      - `.handle(r: PollResult) -> list[Event]`
      - `.emit(events: list[Event], bypass_quiet: bool = False) -> list[Event]`
      - `.system_event(key: str, params: dict | None = None, desktop: bool = False) -> Event`
      - `.record_delivery(event_id: int | None, channel: str, status: str)`
      - `.apply_settings(settings)`
    - history accessors: `.samples_since(ts) -> list[Snapshot]`, `.counter_readings() -> list[CounterReading]`, `.session_list(since=None) -> list[Session]`, `.event_list(limit=500) -> list[Event]`
    - maintenance: `.purge()`, `.close()`

- [ ] **Step 1: Write the failing tests**

`tests/test_monitor.py`:

```python
import sqlite3

import pytest

from marstek_monitor import settings as settings_mod
from marstek_monitor.api.client import DeviceInfo
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage

DEVICE = DeviceInfo("VenusE 3.0", 144, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")
NOON = 1_790_000_000.0  # any fixed time; tests that care about local time set quiet hours to all day


def poll(ts, soc=60, power=0.0, online=True, cin=None, cout=None, device=DEVICE, **kw):
    s = Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, stored_wh=5120 * soc / 100, rated_wh=5120.0,
                 counter_in_wh=cin, counter_out_wh=cout, charge_allowed=True, discharge_allowed=True, temp_c=25.0)
    return PollResult(ts=ts, snapshot=s, online=online, device=device, **kw)


@pytest.fixture
def storage(tmp_path):
    db = Storage(tmp_path / "history.db")
    yield db
    db.close()


@pytest.fixture
def cfg():
    return settings_mod.defaults()


def test_state_is_updated(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    m.handle(poll(NOON, soc=50, power=1000))
    st = m.state
    assert st.snapshot.soc_pct == 50 and st.online and st.device == DEVICE
    assert st.minutes_to_full == pytest.approx(2560 / 1000 * 60)
    assert st.minutes_left is None and st.last_update_ts == NOON


def test_samples_and_counters_are_stored(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    m.handle(poll(NOON, cin=100, cout=50))
    m.handle(poll(NOON + 60, cin=110, cout=50))
    assert len(m.samples_since(0)) == 2
    assert len(m.counter_readings()) == 1  # throttled to one per 10 minutes


def test_finished_session_is_stored_and_notified(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = []
    for i, (soc, power) in enumerate([(40, 0), (41, 900), (42, 900), (43, 900), (43, 0), (43, 0)]):
        events += m.handle(poll(NOON + i * 60, soc=soc, power=power, cin=100 + i * 20))
    assert [e.rule_id for e in events] == ["charge_session"]
    assert events[0].id is not None
    stored = m.session_list()
    assert len(stored) == 1 and stored[0].end_ts is not None


def test_open_session_is_restored_after_restart(cfg, storage):
    m1 = Monitor(cfg, storage, clock=lambda: NOON)
    for i, power in enumerate([0, 900, 900]):
        m1.handle(poll(NOON + i * 60, soc=40 + i, power=power))
    m2 = Monitor(cfg, storage, clock=lambda: NOON + 600)
    assert m2.state.current_session is not None
    assert m2.state.current_session.id == m1.state.current_session.id


def test_error_is_reported_once_and_cleared(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    err = PollResult(ts=NOON, snapshot=None, online=True, error_key="sys.port_in_use", error_params={"port": 30000})
    first = m.handle(err)
    assert [e.title_key for e in first] == ["sys.port_in_use"] and first[0].kind == "system"
    assert m.handle(err) == []
    m.handle(poll(NOON + 60))
    assert m.state.error_key is None


def test_telegram_channel_off_when_telegram_disabled(cfg, storage):
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = m.handle(poll(NOON, soc=19))
    assert {e.telegram for e in events} == {"off"}
    cfg2 = settings_mod.defaults()
    cfg2["telegram"]["enabled"] = True
    m2 = Monitor(cfg2, storage, clock=lambda: NOON)
    events2 = m2.handle(poll(NOON, soc=19))
    assert [e.telegram for e in events2] == ["off", "pending"]


def test_quiet_hours_hold_normal_desktop_notifications(cfg, storage):
    cfg["quiet_hours"].update({"enabled": True, "from": "00:00", "to": "23:59"})
    m = Monitor(cfg, storage, clock=lambda: NOON)
    events = m.handle(poll(NOON, soc=39))
    assert [e.desktop for e in events] == ["held"]
    assert m.event_list()[0].desktop == "held"


def test_db_error_continues_without_history(cfg, tmp_path):
    class BrokenStorage(Storage):
        def add_sample(self, s):
            raise sqlite3.OperationalError("disk I/O error")

    broken = BrokenStorage(tmp_path / "broken.db")
    m = Monitor(cfg, broken, clock=lambda: NOON)
    events = m.handle(poll(NOON))
    assert "sys.db_error" in [e.title_key for e in events]
    assert m.state.history_ok is False and m.storage is None
    assert m.handle(poll(NOON + 60)) == []
    assert m.samples_since(0) == []
    broken.close()


def test_firmware_change_event(cfg, storage):
    Monitor(cfg, storage, clock=lambda: NOON).handle(poll(NOON))
    newer = DeviceInfo("VenusE 3.0", 150, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")
    events = Monitor(cfg, storage, clock=lambda: NOON).handle(poll(NOON + 60, device=newer))
    assert [e.title_key for e in events] == ["n.firmware.title"]


def test_without_storage_accessors_are_empty(cfg):
    m = Monitor(cfg, None, clock=lambda: NOON)
    m.handle(poll(NOON))
    assert m.samples_since(0) == [] and m.event_list() == [] and m.session_list() == []
    assert m.counter_readings() == []


def test_emit_stores_and_bypasses_quiet_hours(cfg, storage):
    cfg["quiet_hours"].update({"enabled": True, "from": "00:00", "to": "23:59"})
    m = Monitor(cfg, storage, clock=lambda: NOON)
    [e] = m.emit([m.rules.test_event(NOON, desktop=True, telegram=False)], bypass_quiet=True)
    assert e.id is not None and e.desktop == "pending"
    m.record_delivery(e.id, "desktop", "sent")
    assert m.event_list()[0].desktop == "sent"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_monitor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.core.monitor'`

- [ ] **Step 3: Implement**

`marstek_monitor/core/monitor.py`:

```python
"""The per-poll pipeline (spec §5 data flow): storage, sessions, outage, rules, routing.

Runs on the Qt main thread but has no Qt dependency. A database error never stops
monitoring: history is switched off and a system event is emitted once.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable

from ..api.client import DeviceInfo
from .energy import CounterReading
from .estimates import minutes_left, minutes_to_full
from .events import Event
from .outage import OutageDetector
from .poller import PollResult
from .rules import RuleContext, RulesEngine, route
from .sessions import Session, SessionDetector
from .snapshot import Snapshot
from .storage import Storage

log = logging.getLogger(__name__)


@dataclass
class LiveState:
    snapshot: Snapshot | None = None
    online: bool = True
    device: DeviceInfo | None = None
    grid_state: str = "unknown"
    grid_since: float | None = None
    current_session: Session | None = None
    minutes_to_full: float | None = None
    minutes_left: float | None = None
    last_update_ts: float | None = None
    error_key: str | None = None
    error_params: dict = field(default_factory=dict)
    history_ok: bool = True
    counters_verified: bool = False


def _local_minutes(ts: float) -> int:
    d = datetime.fromtimestamp(ts)
    return d.hour * 60 + d.minute


class Monitor:
    def __init__(self, settings: dict, storage: Storage | None, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.app_start_ts = clock()
        self.storage = storage
        self.state = LiveState()
        self.outage_marks: list[float] = []
        self._db_failed = False
        self.settings = settings
        self.detector = SessionDetector(settings["advanced"]["reserve_soc_pct"])
        self.outage = OutageDetector(settings["advanced"]["outage_detection"])
        self.rules = RulesEngine(settings)
        self.apply_settings(settings)
        fw = self._db(lambda st: st.get_meta("fw_version"))
        self._fw_known: int | None = int(fw) if fw else None
        open_session = self._db(lambda st: st.open_session())
        if open_session is not None:
            self.detector.restore(open_session)
            self.state.current_session = open_session

    def apply_settings(self, settings: dict) -> None:
        self.settings = settings
        self.rules.settings = settings
        self.detector.reserve = settings["advanced"]["reserve_soc_pct"]
        enabled = settings["advanced"]["outage_detection"]
        if enabled != self.outage.enabled:
            self.outage = OutageDetector(enabled)
        self.state.counters_verified = settings["advanced"]["counters_verified"]
        self.state.grid_state = self.outage.state
        self.state.grid_since = self.outage.since

    def _db(self, fn: Callable[[Storage], Any], default: Any = None) -> Any:
        if self.storage is None:
            return default
        try:
            return fn(self.storage)
        except sqlite3.Error:
            log.exception("History database error; continuing without history")
            self.storage = None
            self.state.history_ok = False
            self._db_failed = True
            return default

    def handle(self, r: PollResult) -> list[Event]:
        now = r.ts
        events: list[Event] = []
        if r.error_key != self.state.error_key:
            self.state.error_key = r.error_key
            self.state.error_params = dict(r.error_params)
            if r.error_key:
                events.append(self._system(now, r.error_key, r.error_params))

        if r.gap is not None:
            self.detector.mark_gap()
            if self.detector.current is not None:
                current = self.detector.current
                self._db(lambda st: st.save_session(current))

        fw_change = None
        if r.device is not None:
            self.state.device = r.device
            ver = r.device.ver
            if ver is not None and ver != self._fw_known:
                if self._fw_known is not None:
                    fw_change = (self._fw_known, ver)
                self._fw_known = ver
                self._db(lambda st: st.set_meta("fw_version", str(ver)))

        s = r.snapshot if r.snapshot is not None and r.snapshot.responded else None
        finished: list[Session] = []
        grid_event = None
        if s is not None:
            self._db(lambda st: st.add_sample(s))
            if s.counter_in_wh is not None and s.counter_out_wh is not None:
                self._db(lambda st: st.add_counter(s.ts, s.counter_in_wh, s.counter_out_wh, force=r.gap is not None))
            grid_event = self.outage.update(s)
            if grid_event == "lost":
                self.outage_marks.append(s.ts)
            finished = self.detector.update(s, outage_active=self.outage.state == "lost",
                                            last_outage_end_ts=self.outage.last_end_ts)
            for session in finished:
                self._db(lambda st, x=session: st.save_session(x))
            if self.detector.current is not None:
                current = self.detector.current
                self._db(lambda st: st.save_session(current))
            self.state.snapshot = s
            self.state.last_update_ts = s.ts

        self.state.online = r.online
        self.state.current_session = self.detector.current
        self.state.grid_state = self.outage.state
        self.state.grid_since = self.outage.since
        live = self.state.snapshot if r.online else None
        reserve = self.settings["advanced"]["reserve_soc_pct"]
        self.state.minutes_to_full = minutes_to_full(live) if live else None
        self.state.minutes_left = minutes_left(live, reserve) if live else None

        ctx = RuleContext(
            now=now, snapshot=s, online=r.online, grid_event=grid_event, grid_state=self.state.grid_state,
            minutes_left=self.state.minutes_left, outage_duration_s=self.outage.last_duration_s,
            finished_sessions=finished, fw_change=fw_change,
            offline_polls=self.settings["general"]["offline_after_polls"],
        )
        events += self.rules.evaluate(ctx)
        if self._db_failed:
            self._db_failed = False
            events.append(self._system(now, "sys.db_error", {}))
        return self.emit(events)

    def emit(self, events: list[Event], bypass_quiet: bool = False) -> list[Event]:
        """Finalize events: Telegram off if disabled, quiet hours, store (sets e.id)."""
        telegram_on = self.settings["telegram"]["enabled"]
        out: list[Event] = []
        for e in events:
            if not telegram_on and e.telegram == "pending":
                e = replace(e, telegram="off")
            if not bypass_quiet:
                e = route(e, self.settings["quiet_hours"], _local_minutes(e.ts))
            e.id = self._db(lambda st, x=e: st.add_event(x))
            out.append(e)
        return out

    @staticmethod
    def _system(now: float, key: str, params: dict, desktop: bool = False) -> Event:
        return Event(ts=now, kind="system", rule_id="system", priority="normal", title_key=key,
                     body_key="", params=dict(params), desktop="pending" if desktop else "off")

    def system_event(self, key: str, params: dict | None = None, desktop: bool = False) -> Event:
        return self.emit([self._system(self.clock(), key, params or {}, desktop)], bypass_quiet=True)[0]

    def record_delivery(self, event_id: int | None, channel: str, status: str) -> None:
        if event_id is not None:
            self._db(lambda st: st.set_delivery(event_id, channel, status))

    # history accessors (empty when history is unavailable)
    def samples_since(self, ts: float) -> list[Snapshot]:
        return self._db(lambda st: st.samples_since(ts), [])

    def counter_readings(self) -> list[CounterReading]:
        return self._db(lambda st: st.counters(), [])

    def session_list(self, since: float | None = None) -> list[Session]:
        return self._db(lambda st: st.sessions(since), [])

    def event_list(self, limit: int = 500) -> list[Event]:
        return self._db(lambda st: st.events(limit), [])

    def purge(self) -> None:
        days = self.settings["advanced"]["samples_retention_days"]
        self._db(lambda st: st.purge(self.clock(), days))

    def close(self) -> None:
        if self.detector.current is not None:
            current = self.detector.current
            self._db(lambda st: st.save_session(current))
        if self.storage is not None:
            self.storage.close()
            self.storage = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_monitor.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the whole suite and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests pass

```bash
git add marstek_monitor/core/monitor.py tests/test_monitor.py
git commit -m "feat: monitor pipeline tying storage, sessions, outage and rules"
```

---
### Task 12: Internationalization (English + Ukrainian)

**Files:**
- Create: `marstek_monitor/i18n/__init__.py`, `marstek_monitor/i18n/en.json`, `marstek_monitor/i18n/uk.json`
- Test: `tests/test_i18n.py`

**Interfaces:**
- Produces:
  - `i18n.SUPPORTED = ("en", "uk")`
  - `i18n.set_language(lang: str)`, `i18n.language() -> str`
  - `i18n.tr(key: str, **params) -> str`: falls back to English, then to the key itself
  - formatting helpers:
    - `i18n.fmt_duration(seconds: float | None) -> str`
    - `i18n.fmt_kwh(wh: float | None) -> str` (number only, e.g. `"4.5"` / `"4,5"`)
    - `i18n.fmt_kw(w: float | None) -> str` (e.g. `"1.70 kW"`)
    - `i18n.fmt_power(w: float | None) -> str` (e.g. `"1 450 W"`)
- Keys used by later tasks are all defined below. Brand strings (`Marstek Venus E`, `Marstek Monitor`) are the same in both languages.

- [ ] **Step 1: Write the failing tests**

`tests/test_i18n.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_i18n.py -v`
Expected: FAIL with `ImportError: cannot import name 'i18n'`

- [ ] **Step 3: Implement the module**

`marstek_monitor/i18n/__init__.py`:

```python
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


def fmt_kwh(wh: float | None) -> str:
    return "—" if wh is None else _decimal(f"{wh / 1000:.1f}")


def fmt_kw(w: float | None) -> str:
    return "—" if w is None else tr("unit.kw", v=_decimal(f"{abs(w) / 1000:.2f}"))


def fmt_power(w: float | None) -> str:
    if w is None:
        return "—"
    return tr("unit.w", v=f"{abs(w):,.0f}".replace(",", " "))
```

- [ ] **Step 4: Add the string tables**

`marstek_monitor/i18n/en.json`:

```json
{
  "app.window_title": "Marstek Venus E — Monitor",
  "app.settings_title": "Marstek Venus E — Settings",
  "tray.open": "Open monitor",
  "tray.settings": "Settings",
  "tray.exit": "Exit",
  "tab.now": "Now",
  "tab.energy": "Energy",
  "tab.live": "Live",
  "tab.sessions": "Sessions",
  "tab.events": "Events",

  "state.offline": "Battery not responding",
  "state.unknown": "Waiting for data…",
  "state.charging": "↓ Charging · {power}",
  "state.discharging": "↑ Supplying · {power}",
  "state.idle": "Idle",
  "now.stored": "{stored} of {rated} kWh",
  "now.full": "full",
  "now.current_session": "Current session",
  "now.no_session": "No charging or discharging right now",
  "now.details": "Device details",
  "est.full": "full in ≈ {time}",
  "est.left": "≈ {time} left at this load",
  "grid.ok": "● Grid connected",
  "grid.lost": "⚡ Grid outage since {since} ({duration})",
  "grid.unknown": "Grid state unknown",
  "banner.offline": "Battery not responding — check that it is powered and connected to Wi-Fi",
  "banner.discharge_blocked": "Discharging is blocked by the battery — backup will NOT work during an outage",
  "banner.charge_blocked": "Charging is blocked by the battery",
  "banner.temperature": "Battery temperature {temp} °C is outside the safe range",
  "banner.outage": "Grid outage — running on battery since {since} ({duration})",
  "details.charge": "Charge {v}",
  "details.discharge": "Discharge {v}",
  "details.temp": "{temp} °C",
  "details.wifi": "Wi-Fi {rssi} dBm",
  "details.fw": "fw {fw}",
  "footer.updated": "Updated {time} ({ago} s ago)",
  "footer.waiting": "Waiting for the first reading…",

  "sess.current_charge": "Charging since {time} · {from_soc}% → {to_soc}% · {duration} · {energy} kWh",
  "sess.current_discharge": "Supplying since {time} · {from_soc}% → {to_soc}% · {duration} · {energy} kWh",
  "sess.kind.charge": "↓ Charging",
  "sess.kind.discharge": "↑ On battery",
  "sess.cause.other": "other",
  "sess.cause.outage": "outage",
  "sess.cause.after_outage": "after outage",
  "sess.cause.after_full_discharge": "after full discharge",
  "sess.q.complete": "✓ complete",
  "sess.q.started_before_app": "⚠ started before the app",
  "sess.q.gap": "⚠ gap in data",
  "sess.q.ended_while_off": "⚠ ended while the app was off",
  "sess.summary": "{start} – {end} · {from_soc}% → {to_soc}% · {duration} · {energy} kWh",
  "sess.avg_charge": "avg {power}",
  "sess.avg_load": "avg load {power}",
  "sess.minimums": "not fully observed — values are minimums",
  "sess.ongoing": "ongoing",

  "tip.error": "error — open the monitor",
  "tip.offline": "offline",
  "tip.grid_ok": "Grid OK",
  "tip.on_battery": "On battery",
  "tg.header": "🔋 Marstek Venus E — {soc}% ({stored} of {rated} kWh)",
  "tg.no_data": "🔋 Marstek Venus E — no data yet",
  "tg.updated": "Updated {time}",
  "tg.command_desc": "Battery status",
  "day.today": "Today · {date}",
  "day.yesterday": "Yesterday · {date}",
  "dur.hm": "{h} h {m} min",
  "dur.m": "{m} min",
  "unit.w": "{v} W",
  "unit.kw": "{v} kW",
  "unit.kwh": "{v} kWh",
  "num.decimal": ".",

  "n.soc_below.title": "Battery below {pct}%",
  "n.soc_below.body": "Charge level is {soc}%.",
  "n.soc_reached.title": "Battery reached {pct}%",
  "n.soc_reached.body": "Charge level is {soc}%.",
  "n.temp_high.title": "Battery temperature high",
  "n.temp_low.title": "Battery temperature low",
  "n.temp.body": "{temp} °C (limit {limit} °C).",
  "n.blocked_charge.title": "Charging is blocked by the battery",
  "n.blocked_charge.body": "The battery does not accept charging right now.",
  "n.blocked_discharge.title": "Discharging is blocked by the battery",
  "n.blocked_discharge.body": "Backup will NOT work during an outage.",
  "n.offline.title": "Battery not responding",
  "n.offline.body": "No reply for {polls} polls in a row.",
  "n.online.title": "Battery back online",
  "n.online.body": "It was unreachable for {duration}.",
  "n.grid_lost.title": "Grid outage — running on battery",
  "n.grid_lost.body": "Charge level {soc}%.",
  "n.grid_restored.title": "Grid restored",
  "n.grid_restored.body": "The outage lasted {outage}.",
  "n.backup_left.title": "Backup running low",
  "n.backup_left.body": "≈ {left} left at the current load ({soc}%).",
  "n.charge_session.title": "Charge session finished",
  "n.discharge_session.title": "Discharge session finished",
  "n.session.body": "{from_soc}% → {to_soc}% in {duration} · {energy} kWh",
  "n.firmware.title": "Battery firmware changed",
  "n.firmware.body": "Version {old} → {new}.",
  "n.monitor_started.title": "Marstek Monitor started",
  "n.monitor_started.body": "Monitoring your battery.",
  "n.monitor_stopped.title": "Marstek Monitor stopped",
  "n.monitor_stopped.body": "No notifications until the app runs again.",
  "n.test.title": "Test notification",
  "n.test.body": "This is how Marstek Monitor notifications look.",

  "sys.port_in_use": "UDP port {port} is used by another program",
  "sys.network_error": "Network error: {error}",
  "sys.firewall_hint": "No reply from the battery. Check its IP address, and that Windows Firewall allows incoming UDP for Marstek Monitor.",
  "sys.settings_broken": "The settings file was damaged. Defaults were loaded.",
  "sys.db_error": "History database error — continuing without history.",
  "sys.unexpected_error": "Unexpected error — see the log file.",
  "sys.telegram_invalid_token": "Telegram rejected the bot token.",
  "sys.telegram_ignored": "Ignored a Telegram message from user {user}.",
  "sys.telegram_command": "Answered /marstek in Telegram.",

  "energy.charged": "Charged (lifetime)",
  "energy.discharged": "Discharged (lifetime)",
  "energy.cycles": "Full cycles",
  "energy.cycles_sub": "{discharged} ÷ {rated} kWh",
  "energy.efficiency": "Round-trip efficiency",
  "energy.efficiency_sub": "discharged ÷ charged",
  "energy.day": "Day",
  "energy.month": "Month",
  "energy.year": "Year",
  "energy.all_time": "All years",
  "energy.legend_charged": "Charged, kWh",
  "energy.legend_discharged": "Discharged, kWh",
  "energy.legend_combined": "Combined — the PC was off; total exact, split unknown",
  "energy.tip": "{label}: charged {charged} kWh, discharged {discharged} kWh",
  "energy.tip_combined": "Combined bar: the PC was off during this period.",
  "energy.unit_pending": "Counter units are not verified yet (see Advanced settings).",
  "energy.no_data": "No counter readings yet.",
  "month.1": "Jan", "month.2": "Feb", "month.3": "Mar", "month.4": "Apr", "month.5": "May", "month.6": "Jun",
  "month.7": "Jul", "month.8": "Aug", "month.9": "Sep", "month.10": "Oct", "month.11": "Nov", "month.12": "Dec",

  "live.1h": "1 h",
  "live.3h": "3 h",
  "live.6h": "6 h",
  "live.all": "Since start",
  "live.running_since": "App running since {time}",
  "live.legend": "Blue line: SOC % (left axis) · green: charging · orange: supplying (right axis) · grey: no data",
  "live.no_data": "no data",
  "live.tip": "{time} · SOC {soc}% · {state}",

  "sessions.typical": "Typical full charge",
  "sessions.typical_sub": "20 → 100 %, average of the last 5",
  "sessions.longest": "Longest backup",
  "sessions.longest_sub": "{from_soc}% → {to_soc}% · {date}",
  "sessions.all": "All",
  "sessions.charging": "Charging",
  "sessions.discharging": "Discharging",
  "sessions.outages": "Outages only",
  "sessions.p7": "Last 7 days",
  "sessions.p30": "Last 30 days",
  "sessions.p90": "Last 90 days",
  "sessions.pall": "All time",
  "sessions.empty": "No sessions in this period.",
  "sessions.count": "{n} sessions",

  "events.all": "All",
  "events.critical": "Critical",
  "events.notifications": "Notifications",
  "events.system": "System",
  "events.search": "Search…",
  "events.empty": "No events.",
  "events.legend": "🖥 desktop · ✈ Telegram · ✓ sent · 🌙 quiet hours · ⟳ retried · ✕ failed",

  "badge.critical": "critical",
  "badge.experimental": "experimental",
  "priority.normal": "normal",
  "priority.critical": "critical",

  "settings.page.general": "General",
  "settings.page.notifications": "Notifications",
  "settings.page.telegram": "Telegram",
  "settings.page.appearance": "Appearance",
  "settings.page.advanced": "Advanced",
  "settings.save": "Save",
  "settings.cancel": "Cancel",
  "settings.language": "Language",
  "settings.autostart": "Start with Windows",
  "settings.shortcut": "Start menu shortcut",
  "settings.battery": "Battery",
  "settings.rediscover": "Rediscover",
  "settings.poll": "Poll every",
  "settings.poll_warning": "Minimum 60 s — faster polling can make the battery unstable.",
  "settings.offline_after": "Offline after",
  "settings.polls_suffix": " polls",
  "settings.quiet": "Quiet hours",
  "settings.quiet_to": "to",
  "settings.critical_bypass": "critical always get through",
  "settings.silence_telegram": "also silence Telegram",
  "settings.add_level": "+ add level",
  "settings.remove_level": "Remove this level",
  "settings.test": "Test",
  "settings.repeat_off": "off",
  "settings.repeat_min": "{n} min",
  "settings.experimental_hint": "Turn on “Outage detection (experimental)” in Advanced to use these.",
  "col.on": "On",
  "col.notification": "Notification",
  "col.threshold": "Threshold",
  "col.repeat": "Repeat",
  "group.battery": "Battery level",
  "group.grid": "Grid & backup",
  "group.sessions": "Sessions",
  "group.problems": "Problems",
  "group.system": "System",
  "rule.soc_below": "SOC below",
  "rule.soc_reached": "SOC reached",
  "rule.grid": "Grid lost / restored",
  "rule.backup_left": "Backup time left below",
  "rule.charge_session": "Charge session finished",
  "rule.discharge_session": "Discharge session finished",
  "rule.offline": "Battery not responding / back online",
  "rule.blocked": "Charging / discharging blocked",
  "rule.temperature": "Temperature above / below",
  "rule.firmware": "Firmware version changed",
  "rule.monitor": "Monitor started / stopped (Telegram only)",
  "settings.tg_enabled": "Enabled",
  "settings.tg_token": "Bot token",
  "settings.tg_chat": "Chat ID",
  "settings.tg_detect": "Detect",
  "settings.tg_user": "Your user ID",
  "settings.tg_answer": "Answer /marstek (only to your user ID)",
  "settings.tg_test": "Send test message",
  "settings.tg_hint": "Detect: send any message to your bot, then click Detect.",
  "settings.tg_status_ok": "Test message sent ✓",
  "settings.tg_status_failed": "Failed: {error}",
  "settings.tg_detect_none": "No messages found — send a message to your bot first.",
  "settings.tg_detected": "Chat ID detected ✓",
  "settings.tg_missing": "Enter the bot token and chat ID first.",
  "settings.font": "Font size",
  "settings.theme": "Theme",
  "settings.preview": "Preview",
  "theme.system": "Follow Windows",
  "theme.light": "Light",
  "theme.dark": "Dark",
  "settings.power_sign": "Power sign",
  "power.plus": "+ means charging",
  "power.minus": "− means charging",
  "settings.counter_unit": "Counter unit",
  "settings.counters_verified": "Counter units verified (show efficiency)",
  "settings.outage_detection": "Outage detection (experimental)",
  "settings.rearm_pct": "Re-arm margin (SOC)",
  "settings.rearm_c": "Re-arm margin (temperature)",
  "settings.reserve": "Reserve SOC for “time left”",
  "settings.retention": "Keep samples for",
  "settings.days_suffix": " days",
  "settings.log_level": "Log level",
  "settings.record_raw": "Record raw data",
  "settings.open_folder": "Open data folder"
}
```

`marstek_monitor/i18n/uk.json`:

```json
{
  "app.window_title": "Marstek Venus E — Монітор",
  "app.settings_title": "Marstek Venus E — Налаштування",
  "tray.open": "Відкрити монітор",
  "tray.settings": "Налаштування",
  "tray.exit": "Вийти",
  "tab.now": "Зараз",
  "tab.energy": "Енергія",
  "tab.live": "Наживо",
  "tab.sessions": "Сесії",
  "tab.events": "Події",

  "state.offline": "Батарея не відповідає",
  "state.unknown": "Очікування даних…",
  "state.charging": "↓ Заряджання · {power}",
  "state.discharging": "↑ Живлення від батареї · {power}",
  "state.idle": "Очікування",
  "now.stored": "{stored} з {rated} кВт·год",
  "now.full": "повна",
  "now.current_session": "Поточна сесія",
  "now.no_session": "Зараз немає заряджання чи розряджання",
  "now.details": "Деталі пристрою",
  "est.full": "повна через ≈ {time}",
  "est.left": "≈ {time} за поточного навантаження",
  "grid.ok": "● Мережа підключена",
  "grid.lost": "⚡ Відключення мережі з {since} ({duration})",
  "grid.unknown": "Стан мережі невідомий",
  "banner.offline": "Батарея не відповідає — перевірте живлення та підключення до Wi-Fi",
  "banner.discharge_blocked": "Розряджання заблоковане батареєю — резервне живлення НЕ спрацює під час відключення",
  "banner.charge_blocked": "Заряджання заблоковане батареєю",
  "banner.temperature": "Температура батареї {temp} °C поза безпечним діапазоном",
  "banner.outage": "Відключення мережі — живлення від батареї з {since} ({duration})",
  "details.charge": "Заряд {v}",
  "details.discharge": "Розряд {v}",
  "details.temp": "{temp} °C",
  "details.wifi": "Wi-Fi {rssi} дБм",
  "details.fw": "прошивка {fw}",
  "footer.updated": "Оновлено {time} ({ago} с тому)",
  "footer.waiting": "Очікування першого зчитування…",

  "sess.current_charge": "Заряджання з {time} · {from_soc}% → {to_soc}% · {duration} · {energy} кВт·год",
  "sess.current_discharge": "Живлення від батареї з {time} · {from_soc}% → {to_soc}% · {duration} · {energy} кВт·год",
  "sess.kind.charge": "↓ Заряджання",
  "sess.kind.discharge": "↑ Від батареї",
  "sess.cause.other": "інше",
  "sess.cause.outage": "відключення",
  "sess.cause.after_outage": "після відключення",
  "sess.cause.after_full_discharge": "після повного розряду",
  "sess.q.complete": "✓ повна",
  "sess.q.started_before_app": "⚠ почалася до запуску програми",
  "sess.q.gap": "⚠ пропуск у даних",
  "sess.q.ended_while_off": "⚠ завершилася, коли програма не працювала",
  "sess.summary": "{start} – {end} · {from_soc}% → {to_soc}% · {duration} · {energy} кВт·год",
  "sess.avg_charge": "сер. {power}",
  "sess.avg_load": "сер. навантаження {power}",
  "sess.minimums": "спостерігалася не повністю — значення мінімальні",
  "sess.ongoing": "триває",

  "tip.error": "помилка — відкрийте монітор",
  "tip.offline": "не на зв'язку",
  "tip.grid_ok": "Мережа OK",
  "tip.on_battery": "Від батареї",
  "tg.header": "🔋 Marstek Venus E — {soc}% ({stored} з {rated} кВт·год)",
  "tg.no_data": "🔋 Marstek Venus E — даних ще немає",
  "tg.updated": "Оновлено {time}",
  "tg.command_desc": "Стан батареї",
  "day.today": "Сьогодні · {date}",
  "day.yesterday": "Вчора · {date}",
  "dur.hm": "{h} год {m} хв",
  "dur.m": "{m} хв",
  "unit.w": "{v} Вт",
  "unit.kw": "{v} кВт",
  "unit.kwh": "{v} кВт·год",
  "num.decimal": ",",

  "n.soc_below.title": "Заряд батареї нижче {pct}%",
  "n.soc_below.body": "Рівень заряду {soc}%.",
  "n.soc_reached.title": "Заряд батареї досяг {pct}%",
  "n.soc_reached.body": "Рівень заряду {soc}%.",
  "n.temp_high.title": "Висока температура батареї",
  "n.temp_low.title": "Низька температура батареї",
  "n.temp.body": "{temp} °C (межа {limit} °C).",
  "n.blocked_charge.title": "Заряджання заблоковане батареєю",
  "n.blocked_charge.body": "Батарея зараз не приймає заряд.",
  "n.blocked_discharge.title": "Розряджання заблоковане батареєю",
  "n.blocked_discharge.body": "Резервне живлення НЕ спрацює під час відключення.",
  "n.offline.title": "Батарея не відповідає",
  "n.offline.body": "Немає відповіді {polls} опитувань поспіль.",
  "n.online.title": "Батарея знову на зв'язку",
  "n.online.body": "Вона була недоступна {duration}.",
  "n.grid_lost.title": "Відключення мережі — живлення від батареї",
  "n.grid_lost.body": "Рівень заряду {soc}%.",
  "n.grid_restored.title": "Мережу відновлено",
  "n.grid_restored.body": "Відключення тривало {outage}.",
  "n.backup_left.title": "Резерв закінчується",
  "n.backup_left.body": "≈ {left} за поточного навантаження ({soc}%).",
  "n.charge_session.title": "Сесію заряджання завершено",
  "n.discharge_session.title": "Сесію розряджання завершено",
  "n.session.body": "{from_soc}% → {to_soc}% за {duration} · {energy} кВт·год",
  "n.firmware.title": "Прошивку батареї змінено",
  "n.firmware.body": "Версія {old} → {new}.",
  "n.monitor_started.title": "Marstek Monitor запущено",
  "n.monitor_started.body": "Батарея під наглядом.",
  "n.monitor_stopped.title": "Marstek Monitor зупинено",
  "n.monitor_stopped.body": "Сповіщень не буде, доки програму не запустять знову.",
  "n.test.title": "Тестове сповіщення",
  "n.test.body": "Так виглядають сповіщення Marstek Monitor.",

  "sys.port_in_use": "UDP-порт {port} зайнятий іншою програмою",
  "sys.network_error": "Помилка мережі: {error}",
  "sys.firewall_hint": "Батарея не відповідає. Перевірте її IP-адресу та чи дозволяє брандмауер Windows вхідний UDP для Marstek Monitor.",
  "sys.settings_broken": "Файл налаштувань пошкоджено. Завантажено типові значення.",
  "sys.db_error": "Помилка бази історії — робота продовжується без історії.",
  "sys.unexpected_error": "Неочікувана помилка — див. файл журналу.",
  "sys.telegram_invalid_token": "Telegram відхилив токен бота.",
  "sys.telegram_ignored": "Проігноровано повідомлення Telegram від користувача {user}.",
  "sys.telegram_command": "Відповідь на /marstek у Telegram надіслано.",

  "energy.charged": "Заряджено (за весь час)",
  "energy.discharged": "Розряджено (за весь час)",
  "energy.cycles": "Повні цикли",
  "energy.cycles_sub": "{discharged} ÷ {rated} кВт·год",
  "energy.efficiency": "ККД заряд-розряд",
  "energy.efficiency_sub": "розряджено ÷ заряджено",
  "energy.day": "День",
  "energy.month": "Місяць",
  "energy.year": "Рік",
  "energy.all_time": "Усі роки",
  "energy.legend_charged": "Заряджено, кВт·год",
  "energy.legend_discharged": "Розряджено, кВт·год",
  "energy.legend_combined": "Об'єднано — ПК був вимкнений; сума точна, розподіл невідомий",
  "energy.tip": "{label}: заряджено {charged} кВт·год, розряджено {discharged} кВт·год",
  "energy.tip_combined": "Об'єднаний стовпчик: ПК був вимкнений у цей період.",
  "energy.unit_pending": "Одиниці лічильників ще не перевірено (див. розширені налаштування).",
  "energy.no_data": "Показів лічильників ще немає.",
  "month.1": "Січ", "month.2": "Лют", "month.3": "Бер", "month.4": "Кві", "month.5": "Тра", "month.6": "Чер",
  "month.7": "Лип", "month.8": "Сер", "month.9": "Вер", "month.10": "Жов", "month.11": "Лис", "month.12": "Гру",

  "live.1h": "1 год",
  "live.3h": "3 год",
  "live.6h": "6 год",
  "live.all": "Від запуску",
  "live.running_since": "Програма працює з {time}",
  "live.legend": "Синя лінія: заряд % (ліва вісь) · зелене: заряджання · помаранчеве: живлення від батареї (права вісь) · сіре: немає даних",
  "live.no_data": "немає даних",
  "live.tip": "{time} · заряд {soc}% · {state}",

  "sessions.typical": "Типове повне заряджання",
  "sessions.typical_sub": "20 → 100 %, середнє з останніх 5",
  "sessions.longest": "Найдовший резерв",
  "sessions.longest_sub": "{from_soc}% → {to_soc}% · {date}",
  "sessions.all": "Усі",
  "sessions.charging": "Заряджання",
  "sessions.discharging": "Розряджання",
  "sessions.outages": "Лише відключення",
  "sessions.p7": "Останні 7 днів",
  "sessions.p30": "Останні 30 днів",
  "sessions.p90": "Останні 90 днів",
  "sessions.pall": "За весь час",
  "sessions.empty": "Немає сесій за цей період.",
  "sessions.count": "Сесій: {n}",

  "events.all": "Усі",
  "events.critical": "Критичні",
  "events.notifications": "Сповіщення",
  "events.system": "Системні",
  "events.search": "Пошук…",
  "events.empty": "Подій немає.",
  "events.legend": "🖥 робочий стіл · ✈ Telegram · ✓ надіслано · 🌙 тихі години · ⟳ повтор · ✕ помилка",

  "badge.critical": "критичне",
  "badge.experimental": "експериментальне",
  "priority.normal": "звичайне",
  "priority.critical": "критичне",

  "settings.page.general": "Загальні",
  "settings.page.notifications": "Сповіщення",
  "settings.page.telegram": "Telegram",
  "settings.page.appearance": "Вигляд",
  "settings.page.advanced": "Розширені",
  "settings.save": "Зберегти",
  "settings.cancel": "Скасувати",
  "settings.language": "Мова",
  "settings.autostart": "Запускати разом з Windows",
  "settings.shortcut": "Ярлик у меню «Пуск»",
  "settings.battery": "Батарея",
  "settings.rediscover": "Знайти знову",
  "settings.poll": "Опитувати кожні",
  "settings.poll_warning": "Мінімум 60 с — частіше опитування може зробити роботу батареї нестабільною.",
  "settings.offline_after": "Не на зв'язку після",
  "settings.polls_suffix": " опитувань",
  "settings.quiet": "Тихі години",
  "settings.quiet_to": "до",
  "settings.critical_bypass": "критичні завжди надходять",
  "settings.silence_telegram": "також вимикати Telegram",
  "settings.add_level": "+ додати рівень",
  "settings.remove_level": "Видалити цей рівень",
  "settings.test": "Тест",
  "settings.repeat_off": "вимк.",
  "settings.repeat_min": "{n} хв",
  "settings.experimental_hint": "Увімкніть «Виявлення відключень (експериментально)» у розширених налаштуваннях, щоб користуватися цим.",
  "col.on": "Увімк.",
  "col.notification": "Сповіщення",
  "col.threshold": "Поріг",
  "col.repeat": "Повтор",
  "group.battery": "Рівень заряду",
  "group.grid": "Мережа та резерв",
  "group.sessions": "Сесії",
  "group.problems": "Проблеми",
  "group.system": "Система",
  "rule.soc_below": "Заряд нижче",
  "rule.soc_reached": "Заряд досяг",
  "rule.grid": "Мережу втрачено / відновлено",
  "rule.backup_left": "Залишок резерву менше",
  "rule.charge_session": "Сесію заряджання завершено",
  "rule.discharge_session": "Сесію розряджання завершено",
  "rule.offline": "Батарея не відповідає / знову на зв'язку",
  "rule.blocked": "Заряджання / розряджання заблоковане",
  "rule.temperature": "Температура вище / нижче",
  "rule.firmware": "Версію прошивки змінено",
  "rule.monitor": "Монітор запущено / зупинено (лише Telegram)",
  "settings.tg_enabled": "Увімкнено",
  "settings.tg_token": "Токен бота",
  "settings.tg_chat": "ID чату",
  "settings.tg_detect": "Визначити",
  "settings.tg_user": "Ваш ID користувача",
  "settings.tg_answer": "Відповідати на /marstek (лише вашому ID)",
  "settings.tg_test": "Надіслати тестове повідомлення",
  "settings.tg_hint": "Визначити: надішліть будь-яке повідомлення своєму боту, потім натисніть «Визначити».",
  "settings.tg_status_ok": "Тестове повідомлення надіслано ✓",
  "settings.tg_status_failed": "Помилка: {error}",
  "settings.tg_detect_none": "Повідомлень не знайдено — спершу напишіть своєму боту.",
  "settings.tg_detected": "ID чату визначено ✓",
  "settings.tg_missing": "Спершу введіть токен бота та ID чату.",
  "settings.font": "Розмір шрифту",
  "settings.theme": "Тема",
  "settings.preview": "Попередній перегляд",
  "theme.system": "Як у Windows",
  "theme.light": "Світла",
  "theme.dark": "Темна",
  "settings.power_sign": "Знак потужності",
  "power.plus": "+ означає заряджання",
  "power.minus": "− означає заряджання",
  "settings.counter_unit": "Одиниця лічильників",
  "settings.counters_verified": "Одиниці лічильників перевірено (показувати ККД)",
  "settings.outage_detection": "Виявлення відключень (експериментально)",
  "settings.rearm_pct": "Запас повторного спрацювання (заряд)",
  "settings.rearm_c": "Запас повторного спрацювання (температура)",
  "settings.reserve": "Резервний заряд для «залишку часу»",
  "settings.retention": "Зберігати вимірювання",
  "settings.days_suffix": " днів",
  "settings.log_level": "Рівень журналу",
  "settings.record_raw": "Записувати сирі дані",
  "settings.open_folder": "Відкрити папку даних"
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_i18n.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add marstek_monitor/i18n tests/test_i18n.py
git commit -m "feat: English and Ukrainian string tables with formatting helpers"
```

---

### Task 13: Presentation text (UI, tooltip, Telegram)

**Files:**
- Create: `marstek_monitor/present.py`
- Test: `tests/test_present.py`

**Interfaces:**
- Consumes:
  - `LiveState` (Task 11), `Event` (Task 8), `Session` + flags (Task 6)
  - `direction`, `CHARGING`, `DISCHARGING` (Task 5)
  - i18n (Task 12)
- Produces (all return `str` unless noted):
  - constants `DEVICE_NAME = "Marstek Venus E"`, `TOOLTIP_MAX = 127`
  - time and date: `hm(ts)`, `hms(ts)`, `day_label(ts, now)`
  - tray: `tile(state) -> tuple[str | None, str]` (label, color key in `ui.theme.COLORS`), `tooltip(state, now)`
  - Now tab:
    - `state_line(state) -> tuple[str, str]` (text, color key)
    - `energy_line(state)`, `time_left_line(state)`
    - `grid_line(state, now) -> tuple[str, str]`
    - `banners(state, settings, now) -> list[tuple[str, str]]` (level `"red" | "orange"`, text)
    - `details_line(state)`, `footer(state, now) -> tuple[str, str]`
  - sessions: `current_session_line(session, now)`, `session_title(session)`, `session_quality(session) -> tuple[str, bool]`, `session_summary(session)`, `session_detail(session)`
  - events: `render_event(e) -> tuple[str, str]`, `delivery_text(e)`, `event_icon(e)`
  - Telegram and charts: `telegram_status(state, now)`, `live_tip(s)`

- [ ] **Step 1: Write the failing tests**

`tests/test_present.py`:

```python
import time

import pytest

from marstek_monitor import i18n, present, settings as settings_mod
from marstek_monitor.api.client import DeviceInfo
from marstek_monitor.core.events import Event
from marstek_monitor.core.monitor import LiveState
from marstek_monitor.core.sessions import FLAG_STARTED_BEFORE_APP, Session
from marstek_monitor.core.snapshot import Snapshot

NOW = time.time()
DEVICE = DeviceInfo("VenusE 3.0", 144, "0123456789ab", "a1b2c3d4e5f6", "192.168.1.20")


@pytest.fixture(autouse=True)
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def state(**kw):
    snap_kw = {k: kw.pop(k) for k in list(kw) if k in ("soc_pct", "power_w", "charge_allowed", "discharge_allowed", "temp_c")}
    s = Snapshot(ts=NOW, responded=True, stored_wh=4450.0, rated_wh=5120.0, ip="192.168.1.20", rssi_dbm=-49,
                 fw_version=144, **{"soc_pct": 87, "power_w": 1450.0, "charge_allowed": True,
                                    "discharge_allowed": True, "temp_c": 24.0, **snap_kw})
    base = dict(snapshot=s, online=True, device=DEVICE, last_update_ts=NOW - 12.4, minutes_to_full=25.0)
    base.update(kw)
    return LiveState(**base)


def test_tile():
    assert present.tile(state()) == ("87", "charging")
    assert present.tile(state(power_w=-800.0)) == ("87", "discharging")
    assert present.tile(state(power_w=0.0)) == ("87", "idle")
    assert present.tile(state(online=False)) == (None, "offline")
    assert present.tile(LiveState()) == ("--", "idle")
    assert present.tile(state(error_key="sys.port_in_use")) == ("!", "red")


def test_tooltip():
    tip = present.tooltip(state(grid_state="ok"), NOW)
    assert tip.startswith("Marstek Venus E")
    assert "87%" in tip and "1 450 W" in tip and "Grid OK" in tip
    assert len(tip) <= present.TOOLTIP_MAX
    assert present.tooltip(state(online=False), NOW).startswith("Marstek Venus E · offline")


def test_tooltip_limit_in_ukrainian():
    i18n.set_language("uk")
    for st in (state(grid_state="lost", power_w=-2500.0), state(error_key="sys.firewall_hint"), state(online=False)):
        tip = present.tooltip(st, NOW)
        assert tip.startswith("Marstek Venus E") and len(tip) <= present.TOOLTIP_MAX


def test_state_and_energy_lines():
    assert present.state_line(state()) == ("↓ Charging · 1 450 W", "charging")
    assert present.state_line(state(online=False))[1] == "red"
    assert present.energy_line(state()) == "4.5 of 5.1 kWh · full in ≈ 25 min"
    assert present.time_left_line(state(minutes_left=190.0)) == "≈ 3 h 10 min left at this load"
    assert present.time_left_line(state()) == ""


def test_grid_line():
    assert present.grid_line(state(grid_state="ok"), NOW) == ("● Grid connected", "charging")
    text, color = present.grid_line(state(grid_state="lost", grid_since=NOW - 3600), NOW)
    assert "1 h 0 min" in text and color == "discharging"
    assert present.grid_line(state(), NOW)[0] == "Grid state unknown"


def test_banners():
    cfg = settings_mod.defaults()
    assert present.banners(state(), cfg, NOW) == []
    levels = [lvl for lvl, _ in present.banners(state(discharge_allowed=False, temp_c=50.0), cfg, NOW)]
    assert levels == ["red", "red"]
    assert present.banners(state(online=False), cfg, NOW)[0][0] == "red"
    outage = present.banners(state(grid_state="lost", grid_since=NOW - 60), cfg, NOW)
    assert outage[0][0] == "orange" and "Grid outage" in outage[0][1]


def test_details_and_footer():
    assert present.details_line(state()) == "Charge ✓ · Discharge ✓ · 24 °C · Wi-Fi -49 dBm · fw 144"
    left, right = present.footer(state(), NOW)
    assert left == "VenusE 3.0 · 192.168.1.20" and "(12 s ago)" in right


def test_session_texts():
    s = Session(kind="charge", start_ts=NOW - 3600, start_soc=41, end_ts=NOW, end_soc=87,
                energy_wh=2300, avg_power_w=2300)
    assert present.session_summary(s).endswith("41% → 87% · 1 h 0 min · 2.3 kWh")
    assert present.session_title(s) == "↓ Charging · other"
    assert present.session_quality(s) == ("✓ complete", False)
    assert present.session_detail(s) == "avg 2.30 kW"
    partial = Session(kind="charge", start_ts=NOW - 600, start_soc=55, end_ts=NOW, end_soc=100,
                      energy_wh=500, avg_power_w=3000, flags={FLAG_STARTED_BEFORE_APP})
    text = present.session_summary(partial)
    assert text.startswith("≤ ") and "≤ 55%" in text and "≥ 10 min" in text and "≥ 0.5 kWh" in text
    assert present.session_quality(partial)[1] is True


def test_current_session_line():
    s = Session(kind="discharge", start_ts=NOW - 600, start_soc=100, last_ts=NOW, last_soc=90, counter_wh=500)
    assert present.current_session_line(s, NOW).endswith("100% → 90% · 10 min · 0.5 kWh")


def test_render_event_formats_durations_and_energy():
    e = Event(ts=NOW, kind="notification", rule_id="charge_session", priority="normal",
              title_key="n.charge_session.title", body_key="n.session.body",
              params={"from_soc": 20, "to_soc": 100, "duration_s": 9600, "energy_wh": 4100})
    assert present.render_event(e) == ("Charge session finished", "20% → 100% in 2 h 40 min · 4.1 kWh")
    system = Event(ts=NOW, kind="system", rule_id="system", priority="normal",
                   title_key="sys.port_in_use", body_key="", params={"port": 30000})
    assert present.render_event(system) == ("UDP port 30000 is used by another program", "")


def test_delivery_text_and_icon():
    e = Event(ts=NOW, kind="notification", rule_id="offline", priority="critical", title_key="n.offline.title",
              body_key="n.offline.body", params={}, desktop="held", telegram="retrying")
    assert present.delivery_text(e) == "🖥 🌙 · ✈ ⟳"
    assert present.event_icon(e) == "📶"


def test_telegram_status():
    text = present.telegram_status(state(grid_state="ok"), NOW)
    lines = text.splitlines()
    assert lines[0] == "🔋 Marstek Venus E — 87% (4.5 of 5.1 kWh)"
    assert lines[1] == "↓ Charging · 1 450 W · full in ≈ 25 min"
    assert lines[2] == "● Grid connected"
    assert lines[3].startswith("Updated ")
    assert present.telegram_status(LiveState(), NOW).startswith("🔋 Marstek Venus E — no data yet")


def test_day_label():
    assert present.day_label(NOW, NOW).startswith("Today")
    assert present.day_label(NOW - 86400, NOW).startswith("Yesterday")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_present.py -v`
Expected: FAIL with `ImportError: cannot import name 'present'`

- [ ] **Step 3: Implement**

`marstek_monitor/present.py`:

```python
"""Human-readable text for the UI, the tray tooltip and Telegram (no widgets)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .core.estimates import CHARGING, DISCHARGING, direction
from .core.events import Event
from .core.monitor import LiveState
from .core.sessions import FLAG_ENDED_WHILE_OFF, FLAG_STARTED_BEFORE_APP, Session
from .core.snapshot import Snapshot
from .i18n import fmt_duration, fmt_kw, fmt_kwh, fmt_power, tr

DEVICE_NAME = "Marstek Venus E"
TOOLTIP_MAX = 127
ERROR_TILE_KEYS = {"sys.port_in_use", "sys.network_error", "sys.unexpected_error"}
DELIVERY_SYMBOL = {"pending": "…", "sent": "✓", "held": "🌙", "retrying": "⟳", "failed": "✕"}
RULE_ICON = {
    "soc_below": "🪫", "soc_reached": "🔋", "temperature": "🌡", "blocked": "⛔", "offline": "📶",
    "grid": "⚡", "backup_left": "⏳", "charge_session": "🔋", "discharge_session": "🔌",
    "firmware": "⬆", "monitor": "▶", "test": "🔔", "system": "⚙",
}
CAUSE_KEYS = {
    "other": "sess.cause.other", "outage": "sess.cause.outage",
    "after_outage": "sess.cause.after_outage", "after_full_discharge": "sess.cause.after_full_discharge",
}
QUALITY_KEYS = {
    "complete": "sess.q.complete", "started_before_app": "sess.q.started_before_app",
    "gap": "sess.q.gap", "ended_while_off": "sess.q.ended_while_off",
}


def hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def hms(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def day_label(ts: float, now: float) -> str:
    d = datetime.fromtimestamp(ts).date()
    today = datetime.fromtimestamp(now).date()
    if d == today:
        return tr("day.today", date=f"{d:%d.%m}")
    if d == today - timedelta(days=1):
        return tr("day.yesterday", date=f"{d:%d.%m}")
    return f"{d:%d.%m.%Y}"


def _soc(value: int | None, prefix: str = "") -> str:
    return "?" if value is None else f"{prefix}{value}"


def _kind(state: LiveState) -> str:
    if not state.online:
        return "offline"
    if state.snapshot is None:
        return "unknown"
    return direction(state.snapshot.power_w) or "idle"


def tile(state: LiveState) -> tuple[str | None, str]:
    if state.error_key in ERROR_TILE_KEYS:
        return "!", "red"
    if not state.online:
        return None, "offline"
    s = state.snapshot
    if s is None or s.soc_pct is None:
        return "--", "idle"
    return str(s.soc_pct), direction(s.power_w) or "idle"


def state_line(state: LiveState) -> tuple[str, str]:
    kind = _kind(state)
    s = state.snapshot
    if kind == "offline":
        return tr("state.offline"), "red"
    if kind == "unknown":
        return tr("state.unknown"), "idle"
    if kind == CHARGING:
        return tr("state.charging", power=fmt_power(s.power_w)), "charging"
    if kind == DISCHARGING:
        return tr("state.discharging", power=fmt_power(s.power_w)), "discharging"
    return tr("state.idle"), "idle"


def energy_line(state: LiveState) -> str:
    s = state.snapshot
    if s is None:
        return ""
    parts = []
    if s.stored_wh is not None and s.rated_wh:
        parts.append(tr("now.stored", stored=fmt_kwh(s.stored_wh), rated=fmt_kwh(s.rated_wh)))
    if state.minutes_to_full is not None:
        parts.append(tr("est.full", time=fmt_duration(state.minutes_to_full * 60)))
    elif s.soc_pct == 100:
        parts.append(tr("now.full"))
    return " · ".join(parts)


def time_left_line(state: LiveState) -> str:
    if state.minutes_left is None:
        return ""
    return tr("est.left", time=fmt_duration(state.minutes_left * 60))


def grid_line(state: LiveState, now: float) -> tuple[str, str]:
    if state.grid_state == "ok":
        return tr("grid.ok"), "charging"
    if state.grid_state == "lost":
        since = state.grid_since or now
        return tr("grid.lost", since=hm(since), duration=fmt_duration(now - since)), "discharging"
    return tr("grid.unknown"), "idle"


def banners(state: LiveState, settings: dict, now: float) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if state.error_key:
        out.append(("orange", tr(state.error_key, **state.error_params)))
    if not state.history_ok:
        out.append(("orange", tr("sys.db_error")))
    if not state.online:
        out.append(("red", tr("banner.offline")))
    s = state.snapshot if state.online else None
    if s is not None:
        if s.discharge_allowed is False:
            out.append(("red", tr("banner.discharge_blocked")))
        if s.charge_allowed is False:
            out.append(("orange", tr("banner.charge_blocked")))
        limits = settings["notifications"]["temperature"]
        if s.temp_c is not None and (s.temp_c > limits["high"] or s.temp_c < limits["low"]):
            out.append(("red", tr("banner.temperature", temp=round(s.temp_c))))
    if state.grid_state == "lost":
        since = state.grid_since or now
        out.append(("orange", tr("banner.outage", since=hm(since), duration=fmt_duration(now - since))))
    return out


def details_line(state: LiveState) -> str:
    s = state.snapshot
    if s is None:
        return "—"

    def mark(value: bool | None) -> str:
        return "✓" if value else ("✕" if value is False else "?")

    parts = [tr("details.charge", v=mark(s.charge_allowed)), tr("details.discharge", v=mark(s.discharge_allowed))]
    if s.temp_c is not None:
        parts.append(tr("details.temp", temp=round(s.temp_c)))
    if s.rssi_dbm is not None:
        parts.append(tr("details.wifi", rssi=s.rssi_dbm))
    if s.fw_version is not None:
        parts.append(tr("details.fw", fw=s.fw_version))
    return " · ".join(parts)


def footer(state: LiveState, now: float) -> tuple[str, str]:
    device = state.device
    ip = (state.snapshot.ip if state.snapshot is not None else None) or (device.ip if device else "")
    left = " · ".join(x for x in ((device.device if device else ""), ip) if x)
    if state.last_update_ts is None:
        return left, tr("footer.waiting")
    ago = int(max(0, now - state.last_update_ts))
    return left, tr("footer.updated", time=hms(state.last_update_ts), ago=ago)


def tooltip(state: LiveState, now: float) -> str:
    parts = [DEVICE_NAME]
    if state.error_key:
        parts.append(tr("tip.error"))
    elif not state.online:
        parts.append(tr("tip.offline"))
    elif state.snapshot is not None:
        if state.snapshot.soc_pct is not None:
            parts.append(f"{state.snapshot.soc_pct}%")
        parts.append(state_line(state)[0])
        if state.grid_state == "ok":
            parts.append(tr("tip.grid_ok"))
        elif state.grid_state == "lost":
            parts.append(tr("tip.on_battery"))
    if state.last_update_ts is not None:
        parts.append(hm(state.last_update_ts))
    text = " · ".join(parts)
    return text if len(text) <= TOOLTIP_MAX else text[: TOOLTIP_MAX - 1] + "…"


def current_session_line(session: Session, now: float) -> str:
    approx = FLAG_STARTED_BEFORE_APP in session.flags
    le = "≤ " if approx else ""
    ge = "≥ " if approx else ""
    key = "sess.current_charge" if session.kind == "charge" else "sess.current_discharge"
    return tr(key, time=le + hm(session.start_ts), from_soc=_soc(session.start_soc, le),
              to_soc=_soc(session.last_soc), duration=ge + fmt_duration(now - session.start_ts),
              energy=ge + fmt_kwh(session.energy_so_far()))


def session_title(session: Session) -> str:
    kind = tr("sess.kind.charge") if session.kind == "charge" else tr("sess.kind.discharge")
    return f"{kind} · {tr(CAUSE_KEYS.get(session.cause, 'sess.cause.other'))}"


def session_quality(session: Session) -> tuple[str, bool]:
    quality = session.quality
    return tr(QUALITY_KEYS[quality]), quality != "complete"


def session_summary(session: Session) -> str:
    start_unknown = FLAG_STARTED_BEFORE_APP in session.flags
    partial = start_unknown or FLAG_ENDED_WHILE_OFF in session.flags
    le = "≤ " if start_unknown else ""
    ge = "≥ " if partial else ""
    end_ts = session.end_ts if session.end_ts is not None else session.last_ts
    end_soc = session.end_soc if session.end_soc is not None else session.last_soc
    energy = session.energy_wh if session.energy_wh is not None else session.energy_so_far()
    return tr("sess.summary", start=le + hm(session.start_ts), end=hm(end_ts),
              from_soc=_soc(session.start_soc, le), to_soc=_soc(end_soc),
              duration=ge + fmt_duration(session.duration_s), energy=ge + fmt_kwh(energy))


def session_detail(session: Session) -> str:
    parts = []
    if session.avg_power_w is not None:
        key = "sess.avg_charge" if session.kind == "charge" else "sess.avg_load"
        parts.append(tr(key, power=fmt_kw(session.avg_power_w)))
    if session.quality != "complete" and session.quality != "gap":
        parts.append(tr("sess.minimums"))
    if session.is_open:
        parts.append(tr("sess.ongoing"))
    return " · ".join(parts)


def render_event(e: Event) -> tuple[str, str]:
    params = {}
    for key, value in e.params.items():
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if key.endswith("_s") and is_number:
            params[key[:-2]] = fmt_duration(value)
        elif key.endswith("_wh") and is_number:
            params[key[:-3]] = fmt_kwh(value)
        else:
            params[key] = value
    title = tr(e.title_key, **params)
    body = tr(e.body_key, **params) if e.body_key else ""
    return title, body


def delivery_text(e: Event) -> str:
    parts = []
    for channel, symbol in (("desktop", "🖥"), ("telegram", "✈")):
        status = getattr(e, channel)
        if status != "off":
            parts.append(f"{symbol} {DELIVERY_SYMBOL.get(status, status)}")
    return " · ".join(parts)


def event_icon(e: Event) -> str:
    return RULE_ICON.get(e.rule_id, "•")


def telegram_status(state: LiveState, now: float) -> str:
    s = state.snapshot
    if s is None:
        lines = [tr("tg.no_data")]
    else:
        lines = [tr("tg.header", soc=_soc(s.soc_pct), stored=fmt_kwh(s.stored_wh), rated=fmt_kwh(s.rated_wh))]
    text, _ = state_line(state)
    extra = ""
    if state.minutes_to_full is not None:
        extra = tr("est.full", time=fmt_duration(state.minutes_to_full * 60))
    elif state.minutes_left is not None:
        extra = time_left_line(state)
    lines.append(f"{text} · {extra}" if extra else text)
    lines.append(grid_line(state, now)[0])
    if state.last_update_ts is not None:
        lines.append(tr("tg.updated", time=hms(state.last_update_ts)))
    return "\n".join(lines)


def live_tip(s: Snapshot) -> str:
    d = direction(s.power_w)
    if d == CHARGING:
        text = tr("state.charging", power=fmt_power(s.power_w))
    elif d == DISCHARGING:
        text = tr("state.discharging", power=fmt_power(s.power_w))
    else:
        text = tr("state.idle")
    return tr("live.tip", time=hm(s.ts), soc=_soc(s.soc_pct), state=text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_present.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/present.py tests/test_present.py
git commit -m "feat: presentation text for tray, windows and Telegram"
```

---

### Task 14: Telegram API, service and chat-ID detection

**Files:**
- Create: `marstek_monitor/notify/telegram.py`
- Create: `tests/fakes/fake_telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Consumes: `i18n.tr` (Task 12).
- Produces:
  - `TelegramError(status: int | None, description: str = "", retry_after: float | None = None)`
  - `TelegramApi(token: str, base_url: str = "https://api.telegram.org", timeout: float = 15.0)` with:
    - `.send_message(chat_id, text)`
    - `.get_updates(offset: int | None, timeout_s: int) -> list[dict]`
    - `.set_my_commands(commands: list[tuple[str, str]])`
  - `detect_chat_id(api: TelegramApi) -> str | None`
  - `TelegramService(api, chat_id, user_id, answer_command, status_provider, on_delivery, on_problem, on_command=lambda: None, backoff=(5.0, 30.0, 120.0), poll_timeout_s=50)` with:
    - callbacks `status_provider() -> str`, `on_delivery(event_id: int | None, status: str)`, `on_problem(key: str, params: dict)`, `on_command()`
    - methods `.start()`, `.send(text, event_id=None)`, `.flush(timeout) -> bool`, `.stop(timeout=1.0)`
  - Delivery statuses reported: `retrying`, `sent`, `failed`. Problem keys: `sys.telegram_invalid_token`, `sys.telegram_ignored` (params `{"user": id}`).

- [ ] **Step 1: Write the fake Bot API server**

`tests/fakes/fake_telegram.py`:

```python
"""Minimal Telegram Bot API server for tests: records requests, replies from a script."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTelegram:
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.responses: dict[str, list[tuple[int, dict]]] = {}
        self.updates: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeTelegram":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "FakeTelegram":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def queue(self, method: str, status: int, body: dict) -> None:
        self.responses.setdefault(method, []).append((status, body))

    def calls(self, method: str) -> list[dict]:
        return [payload for m, payload in self.requests if m == method]

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                fake.requests.append((method, payload))
                queued = fake.responses.get(method)
                if queued:
                    status, body = queued.pop(0)
                elif method == "getUpdates":
                    offset = payload.get("offset") or 0
                    items = [u for u in fake.updates if u["update_id"] >= offset]
                    if not items:
                        time.sleep(min(payload.get("timeout", 0), 0.2))
                    status, body = 200, {"ok": True, "result": items}
                else:
                    status, body = 200, {"ok": True, "result": True}
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler
```

- [ ] **Step 2: Write the failing tests**

`tests/test_telegram.py`:

```python
import time

import pytest

from marstek_monitor.notify.telegram import TelegramApi, TelegramService, detect_chat_id
from tests.fakes.fake_telegram import FakeTelegram

ERROR_500 = {"ok": False, "error_code": 500, "description": "Internal Server Error"}


@pytest.fixture
def fake():
    with FakeTelegram() as server:
        yield server


class Recorder:
    def __init__(self):
        self.deliveries, self.problems, self.commands = [], [], []


def make(base_url, answer=False, backoff=(0, 0, 0)):
    rec = Recorder()
    svc = TelegramService(
        TelegramApi("TOKEN", base_url=base_url), chat_id="100", user_id="42", answer_command=answer,
        status_provider=lambda: "STATUS",
        on_delivery=lambda eid, status: rec.deliveries.append((eid, status)),
        on_problem=lambda key, params: rec.problems.append((key, params)),
        on_command=lambda: rec.commands.append(1),
        backoff=backoff, poll_timeout_s=1,
    )
    svc.start()
    return svc, rec


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_send_message_success(fake):
    svc, rec = make(fake.url)
    svc.send("hello", 7)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(7, "sent")]
    assert fake.calls("sendMessage") == [{"chat_id": "100", "text": "hello"}]


def test_retries_then_succeeds(fake):
    fake.queue("sendMessage", 500, ERROR_500)
    fake.queue("sendMessage", 500, ERROR_500)
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying"), (1, "retrying"), (1, "sent")]


def test_429_retry_after_is_honoured(fake):
    fake.queue("sendMessage", 429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                    "parameters": {"retry_after": 0}})
    svc, rec = make(fake.url, backoff=(100, 100, 100))
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying"), (1, "sent")]


def test_401_marks_token_invalid(fake):
    fake.queue("sendMessage", 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "failed")]
    assert rec.problems == [("sys.telegram_invalid_token", {})]


def test_gives_up_after_three_retries(fake):
    for _ in range(4):
        fake.queue("sendMessage", 500, ERROR_500)
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying")] * 3 + [(1, "failed")]
    assert len(fake.calls("sendMessage")) == 4


def test_unreachable_server_fails_without_blocking():
    svc, rec = make("http://127.0.0.1:9")
    started = time.monotonic()
    svc.send("x", 1)
    assert time.monotonic() - started < 0.1
    assert svc.flush(20)  # Windows needs ~2 s per refused localhost connect
    svc.stop()
    assert rec.deliveries[-1] == (1, "failed")


def test_cyrillic_text_is_sent_as_utf8(fake):
    svc, _ = make(fake.url)
    svc.send("Заряд батареї нижче 40%", 1)
    assert svc.flush(3)
    svc.stop()
    assert fake.calls("sendMessage")[0]["text"] == "Заряд батареї нижче 40%"


def test_marstek_command_only_from_owner(fake):
    fake.updates = [
        {"update_id": 1, "message": {"text": "/marstek", "from": {"id": 42}, "chat": {"id": 100}}},
        {"update_id": 2, "message": {"text": "/marstek", "from": {"id": 7}, "chat": {"id": 555}}},
        {"update_id": 3, "message": {"text": "hello", "from": {"id": 42}, "chat": {"id": 100}}},
    ]
    svc, rec = make(fake.url, answer=True)
    assert wait_for(lambda: len(fake.calls("sendMessage")) >= 1 and rec.problems)
    svc.stop()
    assert fake.calls("sendMessage") == [{"chat_id": 100, "text": "STATUS"}]
    assert rec.problems == [("sys.telegram_ignored", {"user": 7})]
    assert rec.commands == [1]
    assert fake.calls("setMyCommands")[0]["commands"][0]["command"] == "marstek"


def test_detect_chat_id(fake):
    api = TelegramApi("TOKEN", base_url=fake.url)
    assert detect_chat_id(api) is None
    fake.updates = [{"update_id": 5, "message": {"chat": {"id": 111}}},
                    {"update_id": 6, "message": {"chat": {"id": 222}}}]
    assert detect_chat_id(api) == "222"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_telegram.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.notify.telegram'`

- [ ] **Step 4: Implement**

`marstek_monitor/notify/telegram.py`:

```python
"""Telegram Bot API over HTTPS with stdlib urllib (spec §6.8).

TelegramService runs a sender thread (queue, retries with backoff, 429 retry_after,
401 = invalid token) and, when enabled, a listener thread answering /marstek only to
the owner's user ID. Both threads are daemons; stop() never blocks on a long poll.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from ..i18n import tr

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, status: int | None, description: str = "", retry_after: float | None = None):
        super().__init__(f"{status}: {description}")
        self.status = status
        self.description = description
        self.retry_after = retry_after


class TelegramApi:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org", timeout: float = 15.0):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, payload: dict, timeout: float | None = None) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/bot{self.token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except ValueError:
                body = {}
            params = body.get("parameters") or {}
            raise TelegramError(exc.code, body.get("description", ""), params.get("retry_after")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TelegramError(None, str(exc)) from exc
        if not body.get("ok"):
            raise TelegramError(body.get("error_code"), body.get("description", ""))
        return body.get("result")

    def send_message(self, chat_id, text: str) -> None:
        self._call("sendMessage", {"chat_id": chat_id, "text": text})

    def get_updates(self, offset: int | None, timeout_s: int) -> list[dict]:
        payload: dict = {"timeout": timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, timeout=timeout_s + 10) or []

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        self._call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})


def detect_chat_id(api: TelegramApi) -> str | None:
    """Chat ID of the latest message sent to the bot (used by Settings → Detect)."""
    for update in reversed(api.get_updates(None, 0)):
        chat = (update.get("message") or {}).get("chat") or {}
        if "id" in chat:
            return str(chat["id"])
    return None


class TelegramService:
    BACKOFF = (5.0, 30.0, 120.0)

    def __init__(self, api: TelegramApi, chat_id: str, user_id: str, answer_command: bool,
                 status_provider: Callable[[], str],
                 on_delivery: Callable[[int | None, str], None],
                 on_problem: Callable[[str, dict], None],
                 on_command: Callable[[], None] = lambda: None,
                 backoff: tuple[float, ...] = BACKOFF, poll_timeout_s: int = 50):
        self.api = api
        self.chat_id = chat_id
        self.user_id = user_id
        self.status_provider = status_provider
        self.on_delivery = on_delivery
        self.on_problem = on_problem
        self.on_command = on_command
        self.backoff = backoff
        self.poll_timeout_s = poll_timeout_s
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._sender = threading.Thread(target=self._send_loop, name="telegram-send", daemon=True)
        self._listener = None
        if answer_command and user_id:
            self._listener = threading.Thread(target=self._listen_loop, name="telegram-listen", daemon=True)

    def start(self) -> None:
        self._sender.start()
        if self._listener is not None:
            self._listener.start()

    def send(self, text: str, event_id: int | None = None) -> None:
        self._queue.put((text, event_id))

    def flush(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return self._queue.unfinished_tasks == 0

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self._sender.join(timeout)

    # -- sender ------------------------------------------------------------

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                text, event_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._deliver(text, event_id)
            finally:
                self._queue.task_done()

    def _deliver(self, text: str, event_id: int | None) -> None:
        attempts = 0
        while True:
            try:
                self.api.send_message(self.chat_id, text)
                self.on_delivery(event_id, "sent")
                return
            except TelegramError as exc:
                if exc.status == 401:
                    self.on_problem("sys.telegram_invalid_token", {})
                    self.on_delivery(event_id, "failed")
                    return
                if attempts >= len(self.backoff):
                    log.warning("Telegram message failed after %d attempts: %s", attempts + 1, exc)
                    self.on_delivery(event_id, "failed")
                    return
                if exc.status == 429 and exc.retry_after is not None:
                    delay = float(exc.retry_after)
                else:
                    delay = self.backoff[attempts]
                attempts += 1
                self.on_delivery(event_id, "retrying")
                if self._stop.wait(delay):
                    self.on_delivery(event_id, "failed")
                    return

    # -- listener ----------------------------------------------------------

    def _listen_loop(self) -> None:
        try:
            self.api.set_my_commands([("marstek", tr("tg.command_desc"))])
        except TelegramError as exc:
            log.warning("setMyCommands failed: %s", exc)
        offset: int | None = None
        while not self._stop.is_set():
            try:
                updates = self.api.get_updates(offset, self.poll_timeout_s)
            except TelegramError as exc:
                if exc.status == 401:
                    self.on_problem("sys.telegram_invalid_token", {})
                if self._stop.wait(5):
                    return
                continue
            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                self._handle_update(update)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        if not (text == "/marstek" or text.startswith(("/marstek@", "/marstek "))):
            return
        sender = (message.get("from") or {}).get("id")
        if str(sender) != str(self.user_id):
            self.on_problem("sys.telegram_ignored", {"user": sender})
            return
        chat = (message.get("chat") or {}).get("id", self.chat_id)
        try:
            self.api.send_message(chat, self.status_provider())
            self.on_command()
        except TelegramError as exc:
            log.warning("Could not answer /marstek: %s", exc)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_telegram.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**

```bash
git add marstek_monitor/notify/telegram.py tests/fakes/fake_telegram.py tests/test_telegram.py
git commit -m "feat: Telegram sender with retries and owner-only /marstek command"
```

---

### Task 15: Windows platform helpers (single instance, autostart, Start menu)

**Files:**
- Create: `marstek_monitor/platform/single_instance.py`, `marstek_monitor/platform/autostart.py`, `marstek_monitor/platform/shortcut.py`
- Test: `tests/test_platform.py`

**Interfaces:**
- Produces:
  - `SingleInstance(suffix: str = "")` (a `QObject`) with:
    - signal `activated`
    - `.acquire() -> bool`: `False` when another copy runs, which is then woken
    - `.release()`
  - `autostart.RUN_KEY`, `autostart.VALUE_NAME = "MarstekMonitor"`
  - `autostart.launch_command() -> str`
  - `autostart.is_enabled(key_path=RUN_KEY) -> bool`, `autostart.set_enabled(enabled: bool, key_path=RUN_KEY)`
  - `shortcut.shortcut_path() -> Path`
  - `shortcut.create_shortcut(lnk: Path, target: Path, working_dir: Path) -> bool`, `shortcut.remove_shortcut(lnk: Path)`
  - `shortcut.sync(enabled: bool)`: acts only in the packaged exe (`sys.frozen`)

- [ ] **Step 1: Write the failing tests**

`tests/test_platform.py`:

```python
import sys
import uuid
import winreg
from pathlib import Path

from marstek_monitor.platform import autostart, shortcut
from marstek_monitor.platform.single_instance import SingleInstance

TEST_KEY = r"Software\MarstekMonitorTests\Run"


def test_second_instance_is_refused_and_wakes_the_first(qtbot):
    suffix = f"test-{uuid.uuid4().hex}"
    first = SingleInstance(suffix)
    assert first.acquire() is True
    second = SingleInstance(suffix)
    try:
        with qtbot.waitSignal(first.activated, timeout=3000):
            assert second.acquire() is False
    finally:
        first.release()
    third = SingleInstance(suffix)
    assert third.acquire() is True
    third.release()


def test_autostart_roundtrip():
    try:
        assert autostart.is_enabled(TEST_KEY) is False
        autostart.set_enabled(True, TEST_KEY)
        assert autostart.is_enabled(TEST_KEY) is True
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEST_KEY) as key:
            value, _ = winreg.QueryValueEx(key, autostart.VALUE_NAME)
        assert value == autostart.launch_command()
        autostart.set_enabled(False, TEST_KEY)
        assert autostart.is_enabled(TEST_KEY) is False
        autostart.set_enabled(False, TEST_KEY)  # removing twice is fine
    finally:
        for path in (TEST_KEY, r"Software\MarstekMonitorTests"):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass


def test_launch_command_from_source():
    assert autostart.launch_command().endswith('" -m marstek_monitor')


def test_create_and_remove_shortcut(tmp_path):
    lnk = tmp_path / "Marstek Monitor.lnk"
    assert shortcut.create_shortcut(lnk, Path(sys.executable), tmp_path) is True
    assert lnk.exists()
    shortcut.remove_shortcut(lnk)
    assert not lnk.exists()


def test_sync_does_nothing_when_not_frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    shortcut.sync(True)
    assert not shortcut.shortcut_path().exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_platform.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.platform.autostart'`

- [ ] **Step 3: Implement**

`marstek_monitor/platform/single_instance.py`:

```python
"""Only one running copy (spec §8): a named mutex, plus a local socket that wakes the running copy."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, suffix: str = "", parent=None):
        super().__init__(parent)
        tag = f".{suffix}" if suffix else ""
        self.mutex_name = f"Local\\MarstekMonitor{tag}"
        self.server_name = f"MarstekMonitor{tag}"
        self._mutex = None
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, self.mutex_name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            if handle:
                _kernel32.CloseHandle(handle)
            self._notify_running()
            return False
        self._mutex = handle
        QLocalServer.removeServer(self.server_name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(self.server_name)
        return True

    def _on_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            self._server.nextPendingConnection().disconnectFromServer()
        self.activated.emit()

    def _notify_running(self) -> None:
        sock = QLocalSocket()
        sock.connectToServer(self.server_name)
        if sock.waitForConnected(1000):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._mutex:
            _kernel32.CloseHandle(self._mutex)
            self._mutex = None
```

`marstek_monitor/platform/autostart.py`:

```python
"""'Start with Windows' through the per-user Run key (spec §10)."""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "MarstekMonitor"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" -m marstek_monitor'


def is_enabled(key_path: str = RUN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool, key_path: str = RUN_KEY) -> None:
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
```

`marstek_monitor/platform/shortcut.py`:

```python
"""Start menu shortcut (spec §10.1), created with PowerShell's WScript.Shell (no extra dependency)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
CREATE_NO_WINDOW = 0x08000000


def shortcut_path() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Marstek Monitor.lnk"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(lnk: Path, target: Path, working_dir: Path) -> bool:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(str(lnk))}); "
        f"$s.TargetPath = {_ps_quote(str(target))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(working_dir))}; "
        "$s.Save()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=30,
    )
    if result.returncode != 0:
        log.warning("Creating the Start menu shortcut failed: %s", result.stderr.strip())
    return result.returncode == 0 and lnk.exists()


def remove_shortcut(lnk: Path) -> None:
    lnk.unlink(missing_ok=True)


def sync(enabled: bool) -> None:
    """Create or remove the Start menu shortcut. Only the packaged exe gets one."""
    if not getattr(sys, "frozen", False):
        return
    lnk = shortcut_path()
    exe = Path(sys.executable)
    if enabled and not lnk.exists():
        create_shortcut(lnk, exe, exe.parent)
    elif not enabled and lnk.exists():
        remove_shortcut(lnk)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_platform.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/platform tests/test_platform.py
git commit -m "feat: single instance, autostart and Start menu shortcut helpers"
```

---
### Task 16: Theme, shared widgets and the tray icon

**Files:**
- Create: `marstek_monitor/ui/theme.py`, `marstek_monitor/ui/widgets.py`, `marstek_monitor/ui/tray.py`
- Test: `tests/test_ui_basics.py`

**Interfaces:**
- Consumes: `present.tile`, `present.tooltip`, `present.DEVICE_NAME` (Task 13); `i18n.tr` (Task 12); `LiveState` (Task 11).
- Produces:
  - `theme.COLORS: dict[str, str]`, with keys `charging`, `discharging`, `idle`, `offline`, `red`, `orange`, `blue`
  - `theme.is_dark(theme: str) -> bool`, `theme.palette(dark: bool) -> QPalette`, `theme.stylesheet(dark: bool) -> str`
  - `theme.apply(app, theme: str, font_scale: float)`, `theme.base_point_size() -> float`
  - `widgets.scaled_font(factor, bold=False) -> QFont`, `widgets.clear_layout(layout)`, `widgets.label(text="", role=None, factor=1.0, bold=False, wrap=False) -> QLabel`
  - `widgets.Card(title)`: `.title`, `.value`, `.sub` labels; `.set(value, sub="")`; `.set_accent(color | None)`
  - `widgets.Segmented(options: list[tuple[key, text]])`: signal `changed(str)`; `.value() -> str`; `.set_value(key)`
  - `tray.render_tile(label: str | None, color: str, size: int) -> QPixmap`, `tray.make_icon(label, color) -> QIcon`
  - `tray.Tray` (`QObject`):
    - signals `open_requested`, `settings_requested`, `exit_requested`
    - attribute `.icon: QSystemTrayIcon`
    - methods `.show()`, `.hide()`, `.retranslate()`, `.update_state(state, now)`
- Stylesheet roles (set with `widget.setProperty("role", ...)`): `card`, `card-title`, `muted`, `banner-red`, `banner-orange`, `seg`, `badge-critical`, `badge-warn`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ui_basics.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_ui_basics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.ui.theme'`

- [ ] **Step 3: Implement the theme**

`marstek_monitor/ui/theme.py`:

```python
"""Palette, stylesheet and font scaling (spec §7.4)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "charging": "#2ea043",
    "discharging": "#f0883e",
    "idle": "#8b949e",
    "offline": "#8b949e",
    "red": "#e5534b",
    "orange": "#f0883e",
    "blue": "#1f6feb",
}
_base_point_size: float | None = None


def is_dark(theme: str) -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    app = QApplication.instance()
    return app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def palette(dark: bool) -> QPalette:
    if dark:
        window, base, text, button, mid = "#202124", "#2b2c2f", "#e8eaed", "#303134", "#5f6368"
    else:
        window, base, text, button, mid = "#f7f7f8", "#ffffff", "#1b1b1b", "#eeeeee", "#9aa0a6"
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: window, QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: button, QPalette.ColorRole.Button: button,
        QPalette.ColorRole.WindowText: text, QPalette.ColorRole.Text: text,
        QPalette.ColorRole.ButtonText: text, QPalette.ColorRole.ToolTipBase: base,
        QPalette.ColorRole.ToolTipText: text, QPalette.ColorRole.PlaceholderText: mid,
        QPalette.ColorRole.Mid: mid, QPalette.ColorRole.Highlight: COLORS["blue"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(mid))
    return p


def stylesheet(dark: bool) -> str:
    muted = "#9aa0a6" if dark else "#5f6368"
    red_bg, red_fg = ("#5c1d1d", "#ffd7d5") if dark else ("#fde2e1", "#8b1a14")
    orange_bg, orange_fg = ("#4d3316", "#ffe2c7") if dark else ("#fff0dd", "#7a3d00")
    return f"""
QFrame[role="card"] {{ background: rgba(128, 128, 128, 0.14); border-radius: 8px; }}
QLabel[role="muted"], QLabel[role="card-title"] {{ color: {muted}; }}
QLabel[role="banner-red"] {{ background: {red_bg}; color: {red_fg}; border: 1px solid #e5534b;
    border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
QLabel[role="banner-orange"] {{ background: {orange_bg}; color: {orange_fg}; border: 1px solid #f0883e;
    border-radius: 8px; padding: 8px 12px; font-weight: 600; }}
QLabel[role="badge-critical"] {{ background: {red_bg}; color: {red_fg}; border-radius: 8px; padding: 0 6px; }}
QLabel[role="badge-warn"] {{ background: {orange_bg}; color: {orange_fg}; border-radius: 8px; padding: 0 6px; }}
QPushButton[role="seg"] {{ border: none; border-radius: 12px; padding: 4px 12px;
    background: rgba(128, 128, 128, 0.18); }}
QPushButton[role="seg"]:checked {{ background: #1f6feb; color: white; }}
"""


def apply(app: QApplication, theme: str, font_scale: float) -> None:
    global _base_point_size
    if _base_point_size is None:
        size = app.font().pointSizeF()
        _base_point_size = size if size > 0 else 9.0
    dark = is_dark(theme)
    app.setStyle("Fusion")
    app.setPalette(palette(dark))
    font = app.font()
    font.setPointSizeF(_base_point_size * font_scale)
    app.setFont(font)
    app.setStyleSheet(stylesheet(dark))


def base_point_size() -> float:
    return _base_point_size or 9.0
```

- [ ] **Step 4: Implement the shared widgets**

`marstek_monitor/ui/widgets.py`:

```python
"""Small building blocks shared by the windows."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton, QVBoxLayout, QWidget,
)


def scaled_font(factor: float, bold: bool = False) -> QFont:
    font = QFont(QApplication.font())
    size = font.pointSizeF() if font.pointSizeF() > 0 else 9.0
    font.setPointSizeF(max(6.0, size * factor))
    font.setBold(bold)
    return font


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def label(text: str = "", role: str | None = None, factor: float = 1.0, bold: bool = False,
          wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    if factor != 1.0 or bold:
        widget.setFont(scaled_font(factor, bold))
    widget.setWordWrap(wrap)
    return widget


class Card(QFrame):
    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        self.title = label(title.upper(), "card-title", 0.8)
        self.value = label("—", None, 1.3, True, wrap=True)
        self.sub = label("", "muted", 0.85, wrap=True)
        self.sub.hide()
        for widget in (self.title, self.value, self.sub):
            layout.addWidget(widget)

    def set(self, value: str, sub: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))

    def set_accent(self, color: str | None) -> None:
        self.setStyleSheet(f'QFrame[role="card"] {{ border-left: 4px solid {color}; }}' if color else "")


class Segmented(QWidget):
    """A row of exclusive pill buttons."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self._keys: list[str] = []
        for i, (key, text) in enumerate(options):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("role", "seg")
            button.setChecked(i == 0)
            self.group.addButton(button, i)
            layout.addWidget(button)
            self._keys.append(key)
        layout.addStretch(1)
        self.group.idClicked.connect(lambda i: self.changed.emit(self._keys[i]))

    def value(self) -> str:
        return self._keys[self.group.checkedId()]

    def set_value(self, key: str) -> None:
        self.group.button(self._keys.index(key)).setChecked(True)
```

- [ ] **Step 5: Implement the tray**

`marstek_monitor/ui/tray.py`:

```python
"""Tray icon: a rounded tile with the SOC number, colored by state (spec §7.1, option B)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.monitor import LiveState
from ..i18n import tr
from ..present import DEVICE_NAME, tile, tooltip
from .theme import COLORS

ICON_SIZES = (16, 20, 24, 32, 48, 64)


def render_tile(label: str | None, color: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    radius = size * 0.19
    p.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)
    if label is None:
        pen = QPen(QColor("white"))
        pen.setWidthF(max(1.5, size * 0.12))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        m = size * 0.3
        p.drawLine(QPointF(m, m), QPointF(size - m, size - m))
        p.drawLine(QPointF(size - m, m), QPointF(m, size - m))
    else:
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(max(6, int(size * (0.62 if len(label) <= 2 else 0.46))))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return pixmap


def make_icon(label: str | None, color: str) -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_tile(label, color, size))
    return icon


class Tray(QObject):
    open_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(make_icon("--", COLORS["idle"]))
        self.menu = QMenu()
        self._open = QAction(self.menu)
        self._settings = QAction(self.menu)
        self._exit = QAction(self.menu)
        self._open.triggered.connect(lambda: self.open_requested.emit())
        self._settings.triggered.connect(lambda: self.settings_requested.emit())
        self._exit.triggered.connect(lambda: self.exit_requested.emit())
        self.menu.addAction(self._open)
        self.menu.addAction(self._settings)
        self.menu.addSeparator()
        self.menu.addAction(self._exit)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.setToolTip(DEVICE_NAME)
        self._last_tile: tuple[str | None, str] | None = None
        self.retranslate()

    def retranslate(self) -> None:
        self._open.setText(tr("tray.open"))
        self._settings.setText(tr("tray.settings"))
        self._exit.setText(tr("tray.exit"))

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()

    def update_state(self, state: LiveState, now: float) -> None:
        current = tile(state)
        if current != self._last_tile:
            label, color_key = current
            self.icon.setIcon(make_icon(label, COLORS[color_key]))
            self._last_tile = current
        self.icon.setToolTip(tooltip(state, now))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_ui_basics.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add marstek_monitor/ui/theme.py marstek_monitor/ui/widgets.py marstek_monitor/ui/tray.py tests/test_ui_basics.py
git commit -m "feat: theme, shared widgets and SOC tile tray icon"
```

---

### Task 17: Charts (energy bars and live SOC/power)

**Files:**
- Create: `marstek_monitor/ui/charts.py`
- Test: `tests/test_charts.py`

**Interfaces:**
- Consumes: `EnergyBar` (Task 7), `Snapshot` (Task 4), `theme.COLORS` (Task 16), `i18n.tr` (Task 12).
- Produces:
  - `nice_max(value: float) -> float`
  - `split_segments(samples: list[Snapshot], gap_s: float) -> list[list[Snapshot]]`
  - `BarChart(QWidget)`:
    - `.set_bars(bars: list[EnergyBar], labels: list[str], tips: list[str])`
    - `.plot_rect() -> QRectF`, `.slot_at(x: float) -> int | None`
    - attribute `._bars`
  - `LiveChart(QWidget)`:
    - `.set_data(samples, t0: float, t1: float, outage_marks: list[float], gap_s: float, tip_fn: Callable[[Snapshot], str])`
    - attribute `._samples`

- [ ] **Step 1: Write the failing tests**

`tests/test_charts.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.ui.charts'`

- [ ] **Step 3: Implement**

`marstek_monitor/ui/charts.py`:

```python
"""Hand-painted charts that inherit the app font and palette (spec §7.2 Energy / Live)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

from ..core.energy import EnergyBar
from ..core.snapshot import Snapshot
from ..i18n import tr
from .theme import COLORS


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * magnitude >= value:
            return step * magnitude
    return 10 * magnitude


def split_segments(samples: list[Snapshot], gap_s: float) -> list[list[Snapshot]]:
    segments: list[list[Snapshot]] = []
    current: list[Snapshot] = []
    for s in samples:
        if current and s.ts - current[-1].ts > gap_s:
            segments.append(current)
            current = []
        current.append(s)
    if current:
        segments.append(current)
    return segments


def _colors(widget: QWidget) -> tuple[QColor, QColor, QColor]:
    text = widget.palette().color(QPalette.ColorRole.WindowText)
    muted = QColor(text)
    muted.setAlpha(160)
    grid = QColor(text)
    grid.setAlpha(35)
    return text, muted, grid


class BarChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._bars: list[EnergyBar] = []
        self._labels: list[str] = []
        self._tips: list[str] = []

    def set_bars(self, bars: list[EnergyBar], labels: list[str], tips: list[str]) -> None:
        self._bars, self._labels, self._tips = list(bars), list(labels), list(tips)
        self.update()

    def plot_rect(self) -> QRectF:
        fm = self.fontMetrics()
        left = fm.horizontalAdvance("00.0") + 10
        bottom = fm.height() + 8
        return QRectF(left, 10, max(1.0, self.width() - left - 8), max(1.0, self.height() - bottom - 10))

    def slot_at(self, x: float) -> int | None:
        r = self.plot_rect()
        n = len(self._bars)
        if n == 0 or not (r.left() <= x <= r.right()):
            return None
        return min(n - 1, int((x - r.left()) / (r.width() / n)))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        _, muted, grid = _colors(self)
        fm = self.fontMetrics()
        r = self.plot_rect()
        top = nice_max(max((max(b.charged_wh, b.discharged_wh) for b in self._bars), default=0.0) / 1000)
        for i in range(5):
            value = top * i / 4
            y = r.bottom() - value / top * r.height()
            p.setPen(grid)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(0, y - fm.height() / 2, r.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{value:g}")
        n = len(self._bars)
        if n:
            slot = r.width() / n
            width = slot * 0.34
            hatch = QBrush(QColor(255, 255, 255, 120), Qt.BrushStyle.BDiagPattern)
            for i, bar in enumerate(self._bars):
                x0 = r.left() + i * slot + slot * 0.14
                for j, (wh, color) in enumerate(((bar.charged_wh, COLORS["charging"]),
                                                 (bar.discharged_wh, COLORS["discharging"]))):
                    height = wh / 1000 / top * r.height()
                    rect = QRectF(x0 + j * (width + 2), r.bottom() - height, width, height)
                    p.fillRect(rect, QColor(color))
                    if bar.combined:
                        p.fillRect(rect, hatch)
                p.setPen(muted)
                text = self._labels[i] if i < len(self._labels) else ""
                p.drawText(QRectF(r.left() + i * slot, r.bottom() + 4, slot, fm.height()),
                           Qt.AlignmentFlag.AlignCenter, text)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        i = self.slot_at(event.position().x())
        if i is not None and i < len(self._tips):
            QToolTip.showText(event.globalPosition().toPoint(), self._tips[i], self)
        else:
            QToolTip.hideText()


class LiveChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self._samples: list[Snapshot] = []
        self._t0, self._t1 = 0.0, 1.0
        self._marks: list[float] = []
        self._gap_s = 180.0
        self._tip_fn: Callable[[Snapshot], str] | None = None

    def set_data(self, samples: list[Snapshot], t0: float, t1: float, outage_marks: list[float],
                 gap_s: float, tip_fn: Callable[[Snapshot], str]) -> None:
        self._t0, self._t1 = t0, max(t1, t0 + 1)
        self._samples = [s for s in samples if self._t0 <= s.ts <= self._t1]
        self._marks = [m for m in outage_marks if self._t0 <= m <= self._t1]
        self._gap_s = gap_s
        self._tip_fn = tip_fn
        self.update()

    def plot_rect(self) -> QRectF:
        fm = self.fontMetrics()
        left = fm.horizontalAdvance("100%") + 10
        right = fm.horizontalAdvance("-2.5 kW") + 10
        bottom = fm.height() + 8
        return QRectF(left, 8, max(1.0, self.width() - left - right), max(1.0, self.height() - bottom - 8))

    def _x(self, r: QRectF, ts: float) -> float:
        return r.left() + (ts - self._t0) / (self._t1 - self._t0) * r.width()

    def _pmax(self) -> float:
        peak = max((abs(s.power_w) for s in self._samples if s.power_w is not None), default=0.0)
        return nice_max(max(2000.0, peak) / 1000) * 1000

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text, muted, grid = _colors(self)
        fm = self.fontMetrics()
        r = self.plot_rect()
        mid = r.center().y()
        pmax = self._pmax()

        def y_power(w: float) -> float:
            return mid - w / pmax * (r.height() / 2)

        def y_soc(soc: float) -> float:
            return r.bottom() - soc / 100 * r.height()

        for w in (-pmax, -pmax / 2, 0.0, pmax / 2, pmax):
            y = y_power(w)
            p.setPen(muted if w == 0 else grid)
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(muted)
            p.drawText(QRectF(r.right() + 4, y - fm.height() / 2, 200, fm.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       "0" if w == 0 else f"{w / 1000:+g} kW")
        p.setPen(QColor(COLORS["blue"]))
        for soc in (0, 50, 100):
            y = y_soc(soc)
            p.drawText(QRectF(0, y - fm.height() / 2, r.left() - 6, fm.height()),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{soc}%")

        segments = split_segments(self._samples, self._gap_s)
        shade = QColor(text)
        shade.setAlpha(22)
        for a, b in zip(segments, segments[1:]):
            x0, x1 = self._x(r, a[-1].ts), self._x(r, b[0].ts)
            p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), shade)
            p.setPen(muted)
            p.drawText(QRectF(x0, r.top(), x1 - x0, fm.height() + 4), Qt.AlignmentFlag.AlignCenter,
                       tr("live.no_data"))
        for segment in segments:
            for sign, color in ((1, COLORS["charging"]), (-1, COLORS["discharging"])):
                points = [(self._x(r, s.ts), y_power(sign * max(0.0, sign * (s.power_w or 0.0))))
                          for s in segment]
                if len(points) < 2:
                    continue
                path = QPainterPath(QPointF(points[0][0], mid))
                for x, y in points:
                    path.lineTo(x, y)
                path.lineTo(points[-1][0], mid)
                path.closeSubpath()
                fill = QColor(color)
                fill.setAlpha(90)
                p.fillPath(path, fill)
            line = QPolygonF([QPointF(self._x(r, s.ts), y_soc(s.soc_pct)) for s in segment if s.soc_pct is not None])
            if line.size() >= 2:
                pen = QPen(QColor(COLORS["blue"]))
                pen.setWidthF(2.2)
                p.setPen(pen)
                p.drawPolyline(line)
        dash = QPen(QColor(COLORS["discharging"]))
        dash.setStyle(Qt.PenStyle.DashLine)
        p.setPen(dash)
        for mark in self._marks:
            x = self._x(r, mark)
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setPen(muted)
        for i in range(4):
            ts = self._t0 + (self._t1 - self._t0) * i / 3
            x = self._x(r, ts)
            p.drawText(QRectF(x - 40, r.bottom() + 4, 80, fm.height()), Qt.AlignmentFlag.AlignCenter,
                       datetime.fromtimestamp(ts).strftime("%H:%M"))
        p.end()

    def mouseMoveEvent(self, event) -> None:
        if not self._samples or self._tip_fn is None:
            return
        r = self.plot_rect()
        ts = self._t0 + (event.position().x() - r.left()) / r.width() * (self._t1 - self._t0)
        nearest = min(self._samples, key=lambda s: abs(s.ts - ts))
        QToolTip.showText(event.globalPosition().toPoint(), self._tip_fn(nearest), self)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_charts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/ui/charts.py tests/test_charts.py
git commit -m "feat: energy bar chart and live SOC/power chart"
```

---

### Task 18: Status window and the Now tab

**Files:**
- Create: `marstek_monitor/ui/status_window.py`, `marstek_monitor/ui/tabs/now.py`
- Create (stubs filled in Task 19): `marstek_monitor/ui/tabs/energy.py`, `live.py`, `sessions.py`, `events.py`. Each starts as a minimal `QWidget` with `refresh()`.
- Test: `tests/test_status_window.py`

**Interfaces:**
- Consumes:
  - `Monitor` (`.state`, `.settings`) (Task 11)
  - `present.*` (Task 13)
  - `theme.COLORS`, `widgets` (Task 16)
- Produces:
  - `StatusWindow(monitor, get_settings: Callable[[], dict], icon: QIcon | None = None)` with:
    - `TAB_KEYS = ("now", "energy", "live", "sessions", "events")`
    - attributes `.now`, `.energy`, `.live`, `.sessions`, `.events`, `.tabs`
    - methods `.show_tab(key)`, `.current_tab() -> str`, `.refresh()`, `.on_update()`

    Closing the window hides it.
  - `NowTab(monitor, get_settings)` with:
    - `.render()` (alias `.refresh()`)
    - attributes `.soc`, `.state`, `.left`, `.energy`, `.bar`, `.grid`, `.session`, `.details`, `.banners` (a `QVBoxLayout`)
  - tab classes with exact constructor signatures (completed in Task 19): `EnergyTab(monitor)`, `LiveTab(monitor, get_settings)`, `SessionsTab(monitor)`, `EventsTab(monitor)`

- [ ] **Step 1: Create the tab stubs**

These four placeholder widgets let the window import its tabs now; Task 19 replaces them.

`marstek_monitor/ui/tabs/energy.py`:

```python
"""Energy tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class EnergyTab(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor

    def refresh(self) -> None:
        pass
```

`marstek_monitor/ui/tabs/live.py`:

```python
"""Live tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class LiveTab(QWidget):
    def __init__(self, monitor, get_settings, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings

    def refresh(self) -> None:
        pass
```

`marstek_monitor/ui/tabs/sessions.py`:

```python
"""Sessions tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class SessionsTab(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor

    def refresh(self) -> None:
        pass
```

`marstek_monitor/ui/tabs/events.py`:

```python
"""Events tab (completed in Task 19)."""
from PySide6.QtWidgets import QWidget


class EventsTab(QWidget):
    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor

    def refresh(self) -> None:
        pass
```

- [ ] **Step 2: Write the failing tests**

`tests/test_status_window.py`:

```python
import time

import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.ui import theme
from marstek_monitor.ui.status_window import StatusWindow


def poll(soc=87, power=1450.0, **kw):
    now = time.time()
    s = Snapshot(ts=now, responded=True, soc_pct=soc, power_w=power, stored_wh=5120 * soc / 100,
                 rated_wh=5120.0, charge_allowed=kw.pop("charge_allowed", True),
                 discharge_allowed=kw.pop("discharge_allowed", True), temp_c=24.0, ip="192.168.1.20")
    return PollResult(ts=now, snapshot=s, online=kw.pop("online", True))


@pytest.fixture
def monitor(qapp):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)
    return Monitor(settings_mod.defaults(), None)


def window(qtbot, monitor):
    win = StatusWindow(monitor, lambda: monitor.settings)
    qtbot.addWidget(win)
    return win


def test_now_tab_shows_state(qtbot, monitor):
    monitor.handle(poll())
    win = window(qtbot, monitor)
    win.show_tab("now")
    assert win.windowTitle() == "Marstek Venus E — Monitor"
    assert win.now.soc.text() == "87%"
    assert win.now.state.text() == "↓ Charging · 1 450 W"
    assert win.now.banners.count() == 0
    assert win.now.bar.value() == 87


def test_blocked_discharge_shows_a_red_banner(qtbot, monitor):
    monitor.handle(poll(discharge_allowed=False))
    win = window(qtbot, monitor)
    win.now.render()
    assert win.now.banners.count() == 1
    assert win.now.banners.itemAt(0).widget().property("role") == "banner-red"


def test_offline_shows_placeholder_soc(qtbot, monitor):
    monitor.handle(poll(online=False))
    win = window(qtbot, monitor)
    win.now.render()
    assert win.now.soc.text() == "--%"


def test_close_hides_the_window(qtbot, monitor):
    win = window(qtbot, monitor)
    win.show()
    win.close()
    assert not win.isVisible()
    win.show_tab("events")
    assert win.isVisible() and win.current_tab() == "events"


def test_font_scale_enlarges_text(qtbot, qapp, monitor):
    small = window(qtbot, monitor).now.soc.font().pointSizeF()
    theme.apply(qapp, "light", 1.5)
    try:
        large = window(qtbot, monitor).now.soc.font().pointSizeF()
    finally:
        theme.apply(qapp, "light", 1.0)
    assert large == pytest.approx(small * 1.5, rel=0.05)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_status_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.ui.status_window'`

- [ ] **Step 4: Implement the Now tab**

`marstek_monitor/ui/tabs/now.py`:

```python
"""Now tab (spec §7.2): banners, grid line, big SOC, current session, device details."""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QProgressBar, QToolButton, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import (
    banners, current_session_line, details_line, energy_line, footer, grid_line, state_line, time_left_line,
)
from ..theme import COLORS
from ..widgets import Card, clear_layout, label


class NowTab(QWidget):
    def __init__(self, monitor, get_settings: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.banners = QVBoxLayout()
        root.addLayout(self.banners)
        self.grid = label("", None, 1.05)
        root.addWidget(self.grid)

        hero = QHBoxLayout()
        hero.setSpacing(18)
        self.soc = label("--%", None, 4.2, True)
        column = QVBoxLayout()
        column.setSpacing(4)
        self.state = label("", None, 1.6, True)
        self.left = label("", None, 1.35, True)
        self.energy = label("", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)
        for widget in (self.state, self.left, self.energy, self.bar):
            column.addWidget(widget)
        hero.addWidget(self.soc)
        hero.addLayout(column, 1)
        root.addLayout(hero)

        self.session = Card(tr("now.current_session"))
        root.addWidget(self.session)

        self.details_button = QToolButton()
        self.details_button.setText(tr("now.details"))
        self.details_button.setCheckable(True)
        self.details_button.setAutoRaise(True)
        self.details_button.setArrowType(Qt.ArrowType.RightArrow)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.details_button.toggled.connect(self._toggle_details)
        self.details = label("", "muted", 0.95, wrap=True)
        self.details.hide()
        root.addWidget(self.details_button)
        root.addWidget(self.details)
        root.addStretch(1)

        bottom = QHBoxLayout()
        self.footer_left = label("", "muted", 0.85)
        self.footer_right = label("", "muted", 0.85)
        bottom.addWidget(self.footer_left)
        bottom.addStretch(1)
        bottom.addWidget(self.footer_right)
        root.addLayout(bottom)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.render)
        self._timer.start(1000)
        self.render()

    def _toggle_details(self, on: bool) -> None:
        self.details.setVisible(on)
        self.details_button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def refresh(self) -> None:
        self.render()

    def render(self) -> None:
        state = self.monitor.state
        now = time.time()

        clear_layout(self.banners)
        for level, text in banners(state, self.get_settings(), now):
            self.banners.addWidget(label(text, f"banner-{level}", wrap=True))

        grid_text, grid_color = grid_line(state, now)
        self.grid.setText(grid_text)
        self.grid.setStyleSheet(f"color: {COLORS[grid_color]};")

        s = state.snapshot
        soc = s.soc_pct if s is not None and state.online else None
        self.soc.setText(f"{soc}%" if soc is not None else "--%")
        text, color = state_line(state)
        self.state.setText(text)
        self.state.setStyleSheet(f"color: {COLORS[color]};")
        left = time_left_line(state)
        self.left.setText(left)
        self.left.setVisible(bool(left))
        self.energy.setText(energy_line(state))
        self.bar.setValue(soc or 0)
        self.bar.setStyleSheet(
            "QProgressBar { border: none; border-radius: 7px; background: rgba(128, 128, 128, 0.25); }"
            f"QProgressBar::chunk {{ border-radius: 7px; background: {COLORS[color]}; }}"
        )

        session = state.current_session
        if session is not None and session.is_open:
            self.session.set(current_session_line(session, now))
            self.session.set_accent(COLORS["charging" if session.kind == "charge" else "discharging"])
        else:
            self.session.set(tr("now.no_session"))
            self.session.set_accent(None)

        self.details.setText(details_line(state))
        left_text, right_text = footer(state, now)
        self.footer_left.setText(left_text)
        self.footer_right.setText(right_text)
```

- [ ] **Step 5: Implement the window**

`marstek_monitor/ui/status_window.py`:

```python
"""Status window with the Now · Energy · Live · Sessions · Events tabs (spec §7.2)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from ..i18n import tr
from .tabs.energy import EnergyTab
from .tabs.events import EventsTab
from .tabs.live import LiveTab
from .tabs.now import NowTab
from .tabs.sessions import SessionsTab


class StatusWindow(QWidget):
    TAB_KEYS = ("now", "energy", "live", "sessions", "events")

    def __init__(self, monitor, get_settings: Callable[[], dict], icon: QIcon | None = None):
        super().__init__()
        self.setWindowTitle(tr("app.window_title"))
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(780, 660)
        self.now = NowTab(monitor, get_settings)
        self.energy = EnergyTab(monitor)
        self.live = LiveTab(monitor, get_settings)
        self.sessions = SessionsTab(monitor)
        self.events = EventsTab(monitor)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.now, tr("tab.now"))
        self.tabs.addTab(self.energy, tr("tab.energy"))
        self.tabs.addTab(self.live, tr("tab.live"))
        self.tabs.addTab(self.sessions, tr("tab.sessions"))
        self.tabs.addTab(self.events, tr("tab.events"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())

    def current_tab(self) -> str:
        return self.TAB_KEYS[self.tabs.currentIndex()]

    def show_tab(self, key: str) -> None:
        self.tabs.setCurrentIndex(self.TAB_KEYS.index(key))
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh(self) -> None:
        widget = self.tabs.currentWidget()
        if hasattr(widget, "refresh"):
            widget.refresh()

    def on_update(self) -> None:
        if self.isVisible():
            self.refresh()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_status_window.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add marstek_monitor/ui/status_window.py marstek_monitor/ui/tabs tests/test_status_window.py
git commit -m "feat: status window with the Now tab"
```

---

### Task 19: Energy, Live, Sessions and Events tabs

**Files:**
- Modify (replace the stubs): `marstek_monitor/ui/tabs/energy.py`, `live.py`, `sessions.py`, `events.py`
- Test: `tests/test_tabs.py`

**Interfaces:**
- Consumes:
  - `Monitor` accessors `counter_readings()`, `samples_since(ts)`, `session_list()`, `event_list(limit)`, plus `.state`, `.app_start_ts`, `.outage_marks` (Task 11)
  - `bars`, `bars_in_range`, `lifetime`, `add_months` (Task 7)
  - `typical_full_charge_s`, `longest_backup` (Task 6)
  - `BarChart`, `LiveChart` (Task 17)
  - `present.*` (Task 13)
- Produces:
  - `EnergyTab` attributes `.c_charged`, `.c_discharged`, `.c_cycles`, `.c_eff` (`Card`), `.period` (`Segmented`), `.chart`, `.footer`, `.offset`; method `.refresh()`
  - `LiveTab` attributes `.range` (`Segmented`), `.chart`; method `.refresh()`
  - `SessionsTab` attributes `.typical`, `.longest` (`Card`), `.kind` (`Segmented`), `.period` (`QComboBox`); methods `.refresh()`, `.card_count() -> int`
  - `EventsTab` attributes `.filter` (`Segmented`), `.search` (`QLineEdit`); methods `.refresh()`, `.row_count() -> int`

- [ ] **Step 1: Write the failing tests**

`tests/test_tabs.py`:

```python
import time

import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.core.events import Event
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.core.poller import PollResult
from marstek_monitor.core.sessions import Session
from marstek_monitor.core.snapshot import Snapshot
from marstek_monitor.core.storage import Storage
from marstek_monitor.ui import theme
from marstek_monitor.ui.tabs.energy import EnergyTab
from marstek_monitor.ui.tabs.events import EventsTab
from marstek_monitor.ui.tabs.live import LiveTab
from marstek_monitor.ui.tabs.sessions import SessionsTab

DAY = 86400


@pytest.fixture
def monitor(qapp, tmp_path):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)
    m = Monitor(settings_mod.defaults(), Storage(tmp_path / "h.db"), clock=lambda: time.time() - 3600)
    yield m
    m.close()


def poll(ts, soc=80, power=0.0):
    s = Snapshot(ts=ts, responded=True, soc_pct=soc, power_w=power, rated_wh=5120.0, stored_wh=5120 * soc / 100)
    return PollResult(ts=ts, snapshot=s, online=True)


def event(ts, rule_id, priority, title, kind="notification"):
    return Event(ts=ts, kind=kind, rule_id=rule_id, priority=priority, title_key=title, body_key="", params={"pct": 40})


def add_counters(storage, now):
    for ts, cin, cout in ((now - 3 * DAY, 1000, 500), (now - 3 * DAY + 600, 1500, 900),
                          (now - 600, 9196, 3329), (now, 9300, 3400)):
        storage.add_counter(ts, cin, cout, force=True)


def test_energy_tab_lifetime_and_bars(qtbot, monitor):
    now = time.time()
    add_counters(monitor.storage, now)
    monitor.handle(poll(now))
    tab = EnergyTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.c_charged.value.text() == "9.3 kWh"
    assert tab.c_cycles.value.text() == "0.7"
    assert tab.c_eff.isHidden()
    assert len(tab.chart._bars) >= 1
    assert "not verified" in tab.footer.text()


def test_energy_tab_shows_efficiency_when_verified(qtbot, monitor):
    monitor.settings["advanced"]["counters_verified"] = True
    monitor.apply_settings(monitor.settings)
    now = time.time()
    add_counters(monitor.storage, now)
    monitor.handle(poll(now))
    tab = EnergyTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert not tab.c_eff.isHidden()
    assert tab.c_eff.value.text() == "37 %"
    assert tab.footer.text() == ""


def test_live_tab_uses_samples_of_this_run(qtbot, monitor):
    now = time.time()
    for i, soc in enumerate((80, 81, 82)):
        monitor.handle(poll(now - 300 + i * 60, soc=soc, power=900))
    tab = LiveTab(monitor, lambda: monitor.settings)
    qtbot.addWidget(tab)
    tab.refresh()
    assert len(tab.chart._samples) == 3


def test_sessions_tab_lists_and_filters(qtbot, monitor):
    now = time.time()
    monitor.storage.save_session(Session(kind="charge", start_ts=now - 7200, start_soc=20, end_ts=now - 3600,
                                         end_soc=100, energy_wh=4000, avg_power_w=4000))
    monitor.storage.save_session(Session(kind="discharge", start_ts=now - 1800, start_soc=100, end_ts=now - 600,
                                         end_soc=80, energy_wh=1000, avg_power_w=3000, cause="outage"))
    tab = SessionsTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.card_count() == 2
    assert tab.typical.value.text() == "≈ 1 h 0 min"
    assert tab.longest.value.text() == "20 min"
    tab.kind.set_value("outage")
    tab.refresh()
    assert tab.card_count() == 1


def test_events_tab_filters_and_search(qtbot, monitor):
    now = time.time()
    monitor.emit([event(now - 30, "offline", "critical", "n.offline.title"),
                  event(now - 20, "soc_below", "normal", "n.soc_below.title"),
                  event(now - 10, "system", "normal", "sys.db_error", kind="system")], bypass_quiet=True)
    tab = EventsTab(monitor)
    qtbot.addWidget(tab)
    tab.refresh()
    assert tab.row_count() == 3
    tab.filter.set_value("critical")
    tab.refresh()
    assert tab.row_count() == 1
    tab.filter.set_value("all")
    tab.search.setText("below")
    assert tab.row_count() == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_tabs.py -v`
Expected: FAIL with `AttributeError: 'EnergyTab' object has no attribute 'c_charged'`

- [ ] **Step 3: Implement the Energy tab**

`marstek_monitor/ui/tabs/energy.py`:

```python
"""Energy tab (spec §7.2): lifetime cards + charged/discharged bars from battery counters."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QToolButton, QVBoxLayout, QWidget

from ...core.energy import EnergyBar, add_months, bars, bars_in_range, lifetime
from ...i18n import fmt_kwh, tr
from ..charts import BarChart
from ..theme import COLORS
from ..widgets import Card, Segmented, label

MONTH_KEYS = ("month.1", "month.2", "month.3", "month.4", "month.5", "month.6",
              "month.7", "month.8", "month.9", "month.10", "month.11", "month.12")
DAYS_SHOWN = 14
MONTHS_SHOWN = 12


class EnergyTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.offset = 0
        root = QVBoxLayout(self)

        cards = QGridLayout()
        self.c_charged = Card(tr("energy.charged"))
        self.c_discharged = Card(tr("energy.discharged"))
        self.c_cycles = Card(tr("energy.cycles"))
        self.c_eff = Card(tr("energy.efficiency"))
        cards.addWidget(self.c_charged, 0, 0)
        cards.addWidget(self.c_discharged, 0, 1)
        cards.addWidget(self.c_cycles, 1, 0)
        cards.addWidget(self.c_eff, 1, 1)
        root.addLayout(cards)

        controls = QHBoxLayout()
        self.period = Segmented([("day", tr("energy.day")), ("month", tr("energy.month")), ("year", tr("energy.year"))])
        self.period.changed.connect(self._period_changed)
        self.prev = QToolButton()
        self.prev.setText("◀")
        self.next = QToolButton()
        self.next.setText("▶")
        self.range = label("", "muted")
        self.prev.clicked.connect(lambda: self._shift(1))
        self.next.clicked.connect(lambda: self._shift(-1))
        controls.addWidget(self.period, 1)
        controls.addWidget(self.prev)
        controls.addWidget(self.range)
        controls.addWidget(self.next)
        root.addLayout(controls)

        self.chart = BarChart()
        root.addWidget(self.chart, 1)
        legend = (f'<span style="color:{COLORS["charging"]}">■</span> {tr("energy.legend_charged")} &nbsp; '
                  f'<span style="color:{COLORS["discharging"]}">■</span> {tr("energy.legend_discharged")} &nbsp; '
                  f'▨ {tr("energy.legend_combined")}')
        root.addWidget(label(legend, "muted", 0.9, wrap=True))
        self.footer = label("", "muted", 0.85, wrap=True)
        root.addWidget(self.footer)

    def _period_changed(self, _key: str) -> None:
        self.offset = 0
        self.refresh()

    def _shift(self, delta: int) -> None:
        self.offset = max(0, self.offset + delta)
        self.refresh()

    def window(self, period: str, today: date) -> tuple[date, date]:
        if period == "day":
            last = today - timedelta(days=DAYS_SHOWN * self.offset)
            return last - timedelta(days=DAYS_SHOWN - 1), last
        if period == "month":
            last_month = add_months(today, -MONTHS_SHOWN * self.offset)
            first = add_months(last_month, -(MONTHS_SHOWN - 1))
            return first, add_months(last_month, 1) - timedelta(days=1)
        return date(1970, 1, 1), today

    @staticmethod
    def bar_label(bar: EnergyBar, period: str) -> str:
        if period == "day":
            return f"{bar.first.day}–{bar.last.day}" if bar.combined else str(bar.first.day)
        if period == "month":
            first = tr(MONTH_KEYS[bar.first.month - 1])
            return f"{first}–{tr(MONTH_KEYS[bar.last.month - 1])}" if bar.combined else first
        return f"{bar.first.year}–{bar.last.year}" if bar.combined else str(bar.first.year)

    @staticmethod
    def bar_tip(bar: EnergyBar) -> str:
        span = f"{bar.first:%d.%m.%Y}" + (f" – {bar.last:%d.%m.%Y}" if bar.last != bar.first else "")
        tip = tr("energy.tip", label=span, charged=fmt_kwh(bar.charged_wh), discharged=fmt_kwh(bar.discharged_wh))
        return tip + ("\n" + tr("energy.tip_combined") if bar.combined else "")

    def refresh(self) -> None:
        readings = self.monitor.counter_readings()
        state = self.monitor.state
        rated = state.snapshot.rated_wh if state.snapshot is not None else None
        life = lifetime(readings[-1] if readings else None, rated)
        if life is None:
            for card in (self.c_charged, self.c_discharged, self.c_cycles, self.c_eff):
                card.set("—")
        else:
            self.c_charged.set(tr("unit.kwh", v=fmt_kwh(life.charged_wh)))
            self.c_discharged.set(tr("unit.kwh", v=fmt_kwh(life.discharged_wh)))
            cycles = f"{life.cycles:.1f}" if life.cycles is not None else "—"
            sub = tr("energy.cycles_sub", discharged=fmt_kwh(life.discharged_wh), rated=fmt_kwh(rated)) if rated else ""
            self.c_cycles.set(cycles, sub)
            eff = f"{life.efficiency * 100:.0f} %" if life.efficiency is not None else "—"
            self.c_eff.set(eff, tr("energy.efficiency_sub"))
        self.c_eff.setVisible(state.counters_verified)

        period = self.period.value()
        first, last = self.window(period, date.today())
        all_bars = bars(readings, period)
        shown = bars_in_range(all_bars, first, last)
        self.chart.set_bars(shown, [self.bar_label(b, period) for b in shown], [self.bar_tip(b) for b in shown])
        if period == "day":
            self.range.setText(f"{first:%d.%m} – {last:%d.%m.%Y}")
        elif period == "month":
            self.range.setText(f"{first:%m.%Y} – {last:%m.%Y}")
        else:
            self.range.setText(tr("energy.all_time"))
        has_older = period != "year" and bool(all_bars) and all_bars[0].first < first
        self.prev.setEnabled(has_older)
        self.next.setEnabled(period != "year" and self.offset > 0)
        if not readings:
            self.footer.setText(tr("energy.no_data"))
        else:
            self.footer.setText("" if state.counters_verified else tr("energy.unit_pending"))
```

- [ ] **Step 4: Implement the Live tab**

`marstek_monitor/ui/tabs/live.py`:

```python
"""Live tab (spec §7.2): SOC and power of the current app run."""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import hm, live_tip
from ..charts import LiveChart
from ..widgets import Segmented, label

RANGES = {"1h": 3600, "3h": 3 * 3600, "6h": 6 * 3600, "all": None}


class LiveTab(QWidget):
    def __init__(self, monitor, get_settings: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        self.get_settings = get_settings
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.range = Segmented([("1h", tr("live.1h")), ("3h", tr("live.3h")), ("6h", tr("live.6h")),
                                ("all", tr("live.all"))])
        self.range.set_value("6h")
        self.range.changed.connect(lambda _key: self.refresh())
        self.since = label("", "muted")
        top.addWidget(self.range, 1)
        top.addWidget(self.since)
        root.addLayout(top)
        self.chart = LiveChart()
        root.addWidget(self.chart, 1)
        root.addWidget(label(tr("live.legend"), "muted", 0.9, wrap=True))

    def refresh(self) -> None:
        now = time.time()
        start = self.monitor.app_start_ts
        window = RANGES[self.range.value()]
        t0 = start if window is None else max(start, now - window)
        samples = [s for s in self.monitor.samples_since(t0) if s.responded]
        gap_s = 3 * self.get_settings()["general"]["poll_seconds"]
        self.chart.set_data(samples, t0, now, self.monitor.outage_marks, gap_s, live_tip)
        self.since.setText(tr("live.running_since", time=hm(start)))
```

- [ ] **Step 5: Implement the Sessions tab**

`marstek_monitor/ui/tabs/sessions.py`:

```python
"""Sessions tab (spec §7.2): summary cards, filters, cards grouped by day."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ...core.sessions import Session, longest_backup, typical_full_charge_s
from ...i18n import fmt_duration, tr
from ...present import day_label, session_detail, session_quality, session_summary, session_title
from ..theme import COLORS
from ..widgets import Card, Segmented, clear_layout, label

MAX_CARDS = 200


class SessionsTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        root = QVBoxLayout(self)

        summary = QGridLayout()
        self.typical = Card(tr("sessions.typical"))
        self.longest = Card(tr("sessions.longest"))
        summary.addWidget(self.typical, 0, 0)
        summary.addWidget(self.longest, 0, 1)
        root.addLayout(summary)

        filters = QHBoxLayout()
        self.kind = Segmented([("all", tr("sessions.all")), ("charge", tr("sessions.charging")),
                               ("discharge", tr("sessions.discharging")), ("outage", tr("sessions.outages"))])
        self.kind.changed.connect(lambda _key: self.refresh())
        self.period = QComboBox()
        for text, days in ((tr("sessions.p7"), 7), (tr("sessions.p30"), 30), (tr("sessions.p90"), 90),
                           (tr("sessions.pall"), 0)):
            self.period.addItem(text, days)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(lambda _index: self.refresh())
        filters.addWidget(self.kind, 1)
        filters.addWidget(self.period)
        root.addLayout(filters)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setSpacing(8)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.count = label("", "muted", 0.85)
        root.addWidget(self.count)

    def card_count(self) -> int:
        count = 0
        for i in range(self.list.count()):
            widget = self.list.itemAt(i).widget()
            if widget is not None and widget.property("role") == "card":
                count += 1
        return count

    def refresh(self) -> None:
        now = time.time()
        sessions = self.monitor.session_list()
        typical = typical_full_charge_s(sessions)
        self.typical.set("≈ " + fmt_duration(typical) if typical else "—", tr("sessions.typical_sub"))
        longest = longest_backup(sessions)
        if longest is None:
            self.longest.set("—")
        else:
            self.longest.set(fmt_duration(longest.duration_s), tr(
                "sessions.longest_sub", from_soc=longest.start_soc, to_soc=longest.end_soc,
                date=f"{datetime.fromtimestamp(longest.start_ts):%d.%m}"))

        days = self.period.currentData()
        since = now - days * 86400 if days else None
        kind = self.kind.value()
        items = [s for s in sessions if since is None or s.start_ts >= since]
        if kind in ("charge", "discharge"):
            items = [s for s in items if s.kind == kind]
        elif kind == "outage":
            items = [s for s in items if s.cause == "outage"]
        items = sorted(items, key=lambda s: s.start_ts, reverse=True)[:MAX_CARDS]

        clear_layout(self.list)
        if not items:
            self.list.addWidget(label(tr("sessions.empty"), "muted"))
        current_day = None
        for session in items:
            day = day_label(session.start_ts, now)
            if day != current_day:
                self.list.addWidget(label(day.upper(), "card-title", 0.8))
                current_day = day
            self.list.addWidget(self._card(session))
        self.list.addStretch(1)
        self.count.setText(tr("sessions.count", n=len(items)))

    @staticmethod
    def _card(session: Session) -> QFrame:
        card = QFrame()
        card.setProperty("role", "card")
        color = COLORS["charging"] if session.kind == "charge" else COLORS["discharging"]
        card.setStyleSheet(f'QFrame[role="card"] {{ border-left: 4px solid {color}; }}')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 8, 12, 8)
        head = QHBoxLayout()
        head.addWidget(label(session_title(session).upper(), "card-title", 0.8))
        quality, warn = session_quality(session)
        head.addWidget(label(quality, "badge-warn" if warn else "muted", 0.8))
        head.addStretch(1)
        layout.addLayout(head)
        layout.addWidget(label(session_summary(session), None, 1.1, True, wrap=True))
        detail = session_detail(session)
        if detail:
            layout.addWidget(label(detail, "muted", 0.85, wrap=True))
        return card
```

- [ ] **Step 6: Implement the Events tab**

`marstek_monitor/ui/tabs/events.py`:

```python
"""Events tab (spec §7.2): history with per-channel delivery status, filters and search."""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from ...i18n import tr
from ...present import day_label, delivery_text, event_icon, hm, render_event
from ..widgets import Segmented, clear_layout, label

MAX_EVENTS = 500


class EventsTab(QWidget):
    def __init__(self, monitor, parent: QWidget | None = None):
        super().__init__(parent)
        self.monitor = monitor
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = Segmented([("all", tr("events.all")), ("critical", tr("events.critical")),
                                 ("notification", tr("events.notifications")), ("system", tr("events.system"))])
        self.filter.changed.connect(lambda _key: self.refresh())
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("events.search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self.refresh())
        top.addWidget(self.filter, 1)
        top.addWidget(self.search)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setSpacing(2)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        root.addWidget(label(tr("events.legend"), "muted", 0.85, wrap=True))

    def row_count(self) -> int:
        count = 0
        for i in range(self.list.count()):
            widget = self.list.itemAt(i).widget()
            if widget is not None and widget.property("role") == "event-row":
                count += 1
        return count

    def refresh(self) -> None:
        now = time.time()
        mode = self.filter.value()
        query = self.search.text().strip().lower()
        rows = []
        for e in self.monitor.event_list(MAX_EVENTS):
            if mode == "critical" and e.priority != "critical":
                continue
            if mode in ("notification", "system") and e.kind != mode:
                continue
            title, body = render_event(e)
            if query and query not in f"{title} {body}".lower():
                continue
            rows.append((e, title, body))

        clear_layout(self.list)
        if not rows:
            self.list.addWidget(label(tr("events.empty"), "muted"))
        current_day = None
        for e, title, body in rows:
            day = day_label(e.ts, now)
            if day != current_day:
                self.list.addWidget(label(day.upper(), "card-title", 0.8))
                current_day = day
            self.list.addWidget(self._row(e, title, body))
        self.list.addStretch(1)

    @staticmethod
    def _row(e, title: str, body: str) -> QFrame:
        row = QFrame()
        row.setProperty("role", "event-row")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.addWidget(label(hm(e.ts), "muted", 0.9))
        layout.addWidget(label(event_icon(e)))
        badge = f' <span style="color:#e5534b">[{html.escape(tr("badge.critical"))}]</span>' \
            if e.priority == "critical" else ""
        text = QLabel(f"<b>{html.escape(title)}</b>{badge}"
                      + (f"<br><span style='color:gray'>{html.escape(body)}</span>" if body else ""))
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        layout.addWidget(label(delivery_text(e), "muted", 0.9))
        return row
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_tabs.py tests/test_status_window.py -v`
Expected: 10 passed

- [ ] **Step 8: Commit**

```bash
git add marstek_monitor/ui/tabs tests/test_tabs.py
git commit -m "feat: energy, live, sessions and events tabs"
```

---

### Task 20: Settings window

**Files:**
- Create: `marstek_monitor/ui/settings_window.py`
- Test: `tests/test_settings_window.py`

**Interfaces:**
- Consumes:
  - `settings.validate`, `settings.MAX_SOC_LEVELS` (Task 3)
  - `paths.data_dir` (Task 1)
  - `theme.base_point_size` (Task 16)
  - `widgets` (Task 16)
- Produces:
  - `SettingsWindow(data: dict, icon: QIcon | None = None, delete_on_close: bool = True, notice: str = "")` (a non-empty `notice` is shown as an orange banner on top; attribute `.notice_label`) with signals:
    - `saved(object)`: the validated settings dict
    - `rediscover()`
    - `test_notification(str, object)`: rule id and that row's config
    - `detect_chat(str)`: the token
    - `send_test(object)`: the Telegram values dict
  - methods `.collect() -> dict`, `.set_telegram_status(text)`, `.set_chat_id(chat_id)`
  - attributes `.general`, `.notifications`, `.telegram`, `.appearance`, `.advanced`, `.save_button`
  - `NotificationsPage.rows_for(rule_id) -> list[_Row]`, `._add_level()`, `._remove_level(index)`
  - `_Row` attributes `.enabled`, `.desktop`, `.telegram`, `.repeat`, `.pct`, `.priority`, `.minutes`, `.high`, `.low`, `.test_button`

- [ ] **Step 1: Write the failing tests**

`tests/test_settings_window.py`:

```python
import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.ui import theme
from marstek_monitor.ui.settings_window import SettingsWindow


@pytest.fixture(autouse=True)
def setup(qapp):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)


def make(qtbot, data=None):
    win = SettingsWindow(data or settings_mod.defaults(), delete_on_close=False)
    qtbot.addWidget(win)
    return win


def test_defaults_roundtrip(qtbot):
    data = settings_mod.defaults()
    assert make(qtbot, data).collect() == settings_mod.validate(data)


def test_add_and_remove_soc_levels(qtbot):
    win = make(qtbot)
    page = win.notifications
    page._add_level()
    assert len(win.collect()["notifications"]["soc_below"]) == 3
    page._add_level()
    assert len(win.collect()["notifications"]["soc_below"]) == 3
    page._remove_level(2)
    assert len(win.collect()["notifications"]["soc_below"]) == 2


def test_edits_are_collected(qtbot):
    win = make(qtbot)
    win.general.poll.setValue(120)
    win.appearance.slider.setValue(150)
    win.telegram.token.setText(" 123:abc ")
    win.notifications.q_enabled.setChecked(True)
    win.notifications.rows_for("soc_below")[0].pct.setValue(35)
    win.notifications.rows_for("temperature")[0].high.setValue(50)
    data = win.collect()
    assert data["general"]["poll_seconds"] == 120
    assert data["appearance"]["font_scale"] == 1.5
    assert data["telegram"]["bot_token"] == "123:abc"
    assert data["quiet_hours"]["enabled"] is True
    assert data["notifications"]["soc_below"][0]["pct"] == 35
    assert data["notifications"]["temperature"]["high"] == 50


def test_save_emits_validated_settings(qtbot):
    win = make(qtbot)
    with qtbot.waitSignal(win.saved) as blocker:
        win.save_button.click()
    assert blocker.args[0]["schema"] == settings_mod.SCHEMA


def test_experimental_rows_need_outage_detection(qtbot):
    assert not make(qtbot).notifications.rows_for("grid")[0].enabled.isEnabled()
    data = settings_mod.defaults()
    data["advanced"]["outage_detection"] = True
    assert make(qtbot, data).notifications.rows_for("grid")[0].enabled.isEnabled()


def test_notice_banner(qtbot):
    win = SettingsWindow(settings_mod.defaults(), delete_on_close=False,
                         notice="UDP port 30000 is used by another program")
    qtbot.addWidget(win)
    assert win.notice_label.text() == "UDP port 30000 is used by another program"
    assert make(qtbot).notice_label is None


def test_test_button_emits_rule(qtbot):
    win = make(qtbot)
    row = win.notifications.rows_for("soc_reached")[0]
    with qtbot.waitSignal(win.test_notification) as blocker:
        row.test_button.click()
    assert blocker.args[0] == "soc_reached" and blocker.args[1]["pct"] == 100
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_settings_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'marstek_monitor.ui.settings_window'`

- [ ] **Step 3: Implement**

`marstek_monitor/ui/settings_window.py`:

```python
"""Settings window: General · Notifications · Telegram · Appearance · Advanced (spec §7.3).

Works on a copy of the settings; Save emits the validated dict, Cancel discards.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QTime, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
    QScrollArea, QSlider, QSpinBox, QStackedWidget, QTimeEdit, QToolButton, QVBoxLayout, QWidget,
)

from .. import paths
from ..i18n import tr
from ..settings import MAX_SOC_LEVELS, validate
from .theme import base_point_size
from .widgets import clear_layout, label

REPEAT_CHOICES = (0, 15, 30, 60, 120)
NEW_LEVEL = {"enabled": True, "pct": 30, "priority": "normal", "desktop": True, "telegram": False, "repeat_min": 0}
GROUPS = (
    ("group.battery", ("soc_below", "soc_reached")),
    ("group.grid", ("grid", "backup_left")),
    ("group.sessions", ("charge_session", "discharge_session")),
    ("group.problems", ("offline", "blocked", "temperature")),
    ("group.system", ("firmware", "monitor")),
)
RULE_LABELS = {
    "soc_below": "rule.soc_below", "soc_reached": "rule.soc_reached", "grid": "rule.grid",
    "backup_left": "rule.backup_left", "charge_session": "rule.charge_session",
    "discharge_session": "rule.discharge_session", "offline": "rule.offline", "blocked": "rule.blocked",
    "temperature": "rule.temperature", "firmware": "rule.firmware", "monitor": "rule.monitor",
}
EXPERIMENTAL = {"grid", "backup_left"}
CRITICAL_RULES = {"grid", "backup_left", "offline", "blocked", "temperature"}


def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setValue(int(value))
    box.setSuffix(suffix)
    return box


def _combo(options: list[tuple[str, object]], value: object) -> QComboBox:
    box = QComboBox()
    for text, data in options:
        box.addItem(text, data)
    box.setCurrentIndex(max(0, box.findData(value)))
    return box


def _repeat_combo(value: int) -> QComboBox:
    options = [(tr("settings.repeat_off") if m == 0 else tr("settings.repeat_min", n=m), m) for m in REPEAT_CHOICES]
    return _combo(options, value)


def _select(box: QComboBox, value: object) -> None:
    box.setCurrentIndex(max(0, box.findData(value)))


class _Row:
    """Widgets of one notification row."""

    def __init__(self, rule: str, cfg: dict, index: int | None = None):
        self.rule, self.index, self.cfg = rule, index, dict(cfg)
        self.enabled = QCheckBox()
        self.enabled.setChecked(cfg["enabled"])
        self.desktop = self._check(cfg, "desktop")
        self.telegram = self._check(cfg, "telegram")
        self.repeat = _repeat_combo(cfg["repeat_min"]) if "repeat_min" in cfg else None
        self.pct = self.priority = self.minutes = self.high = self.low = None
        if rule == "soc_below":
            self.pct = _spin(1, 99, cfg["pct"], " %")
            self.priority = _combo([(tr("priority.normal"), "normal"), (tr("priority.critical"), "critical")],
                                   cfg["priority"])
        elif rule == "soc_reached":
            self.pct = _spin(50, 100, cfg["pct"], " %")
        elif rule == "backup_left":
            self.minutes = _spin(5, 600, cfg["minutes"], " min")
        elif rule == "temperature":
            self.high = _spin(20, 80, cfg["high"], " °C")
            self.low = _spin(-20, 20, cfg["low"], " °C")
        self.test_button = QPushButton(tr("settings.test"))

    @staticmethod
    def _check(cfg: dict, key: str) -> QCheckBox | None:
        if key not in cfg:
            return None
        box = QCheckBox()
        box.setChecked(cfg[key])
        return box

    def threshold_widget(self) -> QWidget | None:
        parts = [w for w in (self.pct, self.priority, self.minutes, self.high, self.low) if w is not None]
        if not parts:
            return None
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in parts:
            layout.addWidget(widget)
        return host

    def widgets(self) -> list[QWidget]:
        candidates = (self.enabled, self.desktop, self.telegram, self.repeat, self.pct, self.priority,
                      self.minutes, self.high, self.low, self.test_button)
        return [w for w in candidates if w is not None]

    def collect(self) -> dict:
        out = dict(self.cfg)
        out["enabled"] = self.enabled.isChecked()
        if self.desktop is not None:
            out["desktop"] = self.desktop.isChecked()
        if self.telegram is not None:
            out["telegram"] = self.telegram.isChecked()
        if self.repeat is not None:
            out["repeat_min"] = self.repeat.currentData()
        if self.pct is not None:
            out["pct"] = self.pct.value()
        if self.priority is not None:
            out["priority"] = self.priority.currentData()
        if self.minutes is not None:
            out["minutes"] = self.minutes.value()
        if self.high is not None:
            out["high"] = self.high.value()
        if self.low is not None:
            out["low"] = self.low.value()
        return out


class GeneralPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.language = _combo([("English", "en"), ("Українська", "uk")], "en")
        self.autostart = QCheckBox(tr("settings.autostart"))
        self.shortcut = QCheckBox(tr("settings.shortcut"))
        self.ip = QLineEdit()
        self.port = _spin(1, 65535, 30000)
        rediscover = QPushButton(tr("settings.rediscover"))
        rediscover.clicked.connect(lambda: window.rediscover.emit())
        battery = QHBoxLayout()
        battery.addWidget(self.ip, 1)
        battery.addWidget(QLabel(":"))
        battery.addWidget(self.port)
        battery.addWidget(rediscover)
        self.poll = _spin(60, 3600, 60, " s")
        self.offline = _spin(1, 20, 3, tr("settings.polls_suffix"))
        form.addRow(tr("settings.language"), self.language)
        form.addRow("", self.autostart)
        form.addRow("", self.shortcut)
        form.addRow(tr("settings.battery"), battery)
        form.addRow(tr("settings.poll"), self.poll)
        form.addRow("", label(tr("settings.poll_warning"), "muted", 0.9, wrap=True))
        form.addRow(tr("settings.offline_after"), self.offline)

    def load(self, d: dict) -> None:
        _select(self.language, d["general"]["language"])
        self.autostart.setChecked(d["general"]["autostart"])
        self.shortcut.setChecked(d["general"]["start_menu_shortcut"])
        self.ip.setText(d["device"]["ip"])
        self.port.setValue(d["device"]["port"])
        self.poll.setValue(d["general"]["poll_seconds"])
        self.offline.setValue(d["general"]["offline_after_polls"])

    def collect(self, d: dict) -> None:
        d["general"].update(language=self.language.currentData(), autostart=self.autostart.isChecked(),
                            start_menu_shortcut=self.shortcut.isChecked(), poll_seconds=self.poll.value(),
                            offline_after_polls=self.offline.value())
        d["device"].update(ip=self.ip.text().strip(), port=self.port.value())


class NotificationsPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        self.window = window
        root = QVBoxLayout(self)
        quiet = QHBoxLayout()
        self.q_enabled = QCheckBox(tr("settings.quiet"))
        self.q_from = QTimeEdit()
        self.q_from.setDisplayFormat("HH:mm")
        self.q_to = QTimeEdit()
        self.q_to.setDisplayFormat("HH:mm")
        self.q_bypass = QCheckBox(tr("settings.critical_bypass"))
        self.q_silence = QCheckBox(tr("settings.silence_telegram"))
        for widget in (self.q_enabled, self.q_from, label(tr("settings.quiet_to")), self.q_to):
            quiet.addWidget(widget)
        quiet.addSpacing(12)
        quiet.addWidget(self.q_bypass)
        quiet.addWidget(self.q_silence)
        quiet.addStretch(1)
        root.addLayout(quiet)
        host = QWidget()
        self.grid = QGridLayout(host)
        root.addWidget(host)
        root.addStretch(1)
        self._work: dict = {}
        self._rows: list[_Row] = []
        self._outage_enabled = False

    def rows_for(self, rule: str) -> list[_Row]:
        return [row for row in self._rows if row.rule == rule]

    def load(self, d: dict) -> None:
        q = d["quiet_hours"]
        self.q_enabled.setChecked(q["enabled"])
        self.q_from.setTime(QTime.fromString(q["from"], "HH:mm"))
        self.q_to.setTime(QTime.fromString(q["to"], "HH:mm"))
        self.q_bypass.setChecked(q["critical_bypass"])
        self.q_silence.setChecked(q["silence_telegram"])
        self._work = copy.deepcopy(d["notifications"])
        self._outage_enabled = d["advanced"]["outage_detection"]
        self._rebuild()

    def _sync(self) -> None:
        for row in self._rows:
            if row.index is None:
                self._work[row.rule] = row.collect()
            else:
                self._work["soc_below"][row.index] = row.collect()

    def _rebuild(self) -> None:
        clear_layout(self.grid)
        self._rows = []
        headers = (tr("col.on"), tr("col.notification"), tr("col.threshold"), "🖥", "✈", tr("col.repeat"), "")
        for column, text in enumerate(headers):
            self.grid.addWidget(label(text, "card-title", 0.8), 0, column)
        r = 1
        for group_key, rules in GROUPS:
            self.grid.addWidget(label(tr(group_key).upper(), "card-title", 0.8), r, 0, 1, 7)
            r += 1
            for rule in rules:
                if rule == "soc_below":
                    levels = self._work["soc_below"]
                    for i, level in enumerate(levels):
                        r = self._add_row(_Row(rule, level, i), r, removable=i > 0)
                    if len(levels) < MAX_SOC_LEVELS:
                        add = QPushButton(tr("settings.add_level"))
                        add.clicked.connect(self._add_level)
                        self.grid.addWidget(add, r, 1)
                        r += 1
                else:
                    r = self._add_row(_Row(rule, self._work[rule]), r)
            if group_key == "group.grid" and not self._outage_enabled:
                self.grid.addWidget(label(tr("settings.experimental_hint"), "muted", 0.85, wrap=True), r, 1, 1, 6)
                r += 1

    def _add_row(self, row: _Row, r: int, removable: bool = False) -> int:
        self._rows.append(row)
        name = QWidget()
        name_layout = QHBoxLayout(name)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(QLabel(tr(RULE_LABELS[row.rule])))
        if row.rule in EXPERIMENTAL:
            name_layout.addWidget(label(tr("badge.experimental"), "badge-warn", 0.8))
        elif row.rule in CRITICAL_RULES:
            name_layout.addWidget(label(tr("badge.critical"), "badge-critical", 0.8))
        name_layout.addStretch(1)
        self.grid.addWidget(row.enabled, r, 0)
        self.grid.addWidget(name, r, 1)
        threshold = row.threshold_widget()
        if threshold is not None:
            self.grid.addWidget(threshold, r, 2)
        if row.desktop is not None:
            self.grid.addWidget(row.desktop, r, 3)
        if row.telegram is not None:
            self.grid.addWidget(row.telegram, r, 4)
        if row.repeat is not None:
            self.grid.addWidget(row.repeat, r, 5)
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        row.test_button.clicked.connect(lambda _=False, rw=row: self.window.test_notification.emit(rw.rule, rw.collect()))
        actions_layout.addWidget(row.test_button)
        if removable:
            remove = QToolButton()
            remove.setText("✕")
            remove.setToolTip(tr("settings.remove_level"))
            remove.clicked.connect(lambda _=False, i=row.index: self._remove_level(i))
            actions_layout.addWidget(remove)
        self.grid.addWidget(actions, r, 6)
        if row.rule in EXPERIMENTAL and not self._outage_enabled:
            for widget in row.widgets():
                widget.setEnabled(False)
        return r + 1

    def _add_level(self) -> None:
        self._sync()
        if len(self._work["soc_below"]) < MAX_SOC_LEVELS:
            self._work["soc_below"].append(dict(NEW_LEVEL))
            self._rebuild()

    def _remove_level(self, index: int) -> None:
        self._sync()
        if len(self._work["soc_below"]) > 1:
            del self._work["soc_below"][index]
            self._rebuild()

    def collect(self, d: dict) -> None:
        self._sync()
        d["notifications"] = copy.deepcopy(self._work)
        d["quiet_hours"].update(enabled=self.q_enabled.isChecked(), critical_bypass=self.q_bypass.isChecked(),
                                silence_telegram=self.q_silence.isChecked(),
                                **{"from": self.q_from.time().toString("HH:mm"),
                                   "to": self.q_to.time().toString("HH:mm")})


class TelegramPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.enabled = QCheckBox(tr("settings.tg_enabled"))
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        reveal = QToolButton()
        reveal.setText("👁")
        reveal.setCheckable(True)
        reveal.toggled.connect(lambda on: self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        token_row = QHBoxLayout()
        token_row.addWidget(self.token, 1)
        token_row.addWidget(reveal)
        self.chat = QLineEdit()
        detect = QPushButton(tr("settings.tg_detect"))
        detect.clicked.connect(lambda: window.detect_chat.emit(self.token.text().strip()))
        chat_row = QHBoxLayout()
        chat_row.addWidget(self.chat, 1)
        chat_row.addWidget(detect)
        self.user = QLineEdit()
        self.answer = QCheckBox(tr("settings.tg_answer"))
        test = QPushButton(tr("settings.tg_test"))
        test.clicked.connect(lambda: window.send_test.emit(self.values()))
        self.status = label("", "muted", 0.9, wrap=True)
        form.addRow("", self.enabled)
        form.addRow(tr("settings.tg_token"), token_row)
        form.addRow(tr("settings.tg_chat"), chat_row)
        form.addRow(tr("settings.tg_user"), self.user)
        form.addRow("", self.answer)
        form.addRow("", test)
        form.addRow("", self.status)
        form.addRow("", label(tr("settings.tg_hint"), "muted", 0.85, wrap=True))

    def values(self) -> dict:
        return {"enabled": self.enabled.isChecked(), "bot_token": self.token.text().strip(),
                "chat_id": self.chat.text().strip(), "user_id": self.user.text().strip(),
                "answer_command": self.answer.isChecked()}

    def load(self, d: dict) -> None:
        tg = d["telegram"]
        self.enabled.setChecked(tg["enabled"])
        self.token.setText(tg["bot_token"])
        self.chat.setText(tg["chat_id"])
        self.user.setText(tg["user_id"])
        self.answer.setChecked(tg["answer_command"])

    def collect(self, d: dict) -> None:
        d["telegram"].update(self.values())


class AppearancePage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(100, 200)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.value = QLabel("100 %")
        row = QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        self.theme = _combo([(tr("theme.system"), "system"), (tr("theme.light"), "light"),
                             (tr("theme.dark"), "dark")], "system")
        self.preview = QLabel(f"87%  {tr('state.charging', power='1 450 W')}")
        self.slider.valueChanged.connect(self._update_preview)
        form.addRow(tr("settings.font"), row)
        form.addRow(tr("settings.theme"), self.theme)
        form.addRow(tr("settings.preview"), self.preview)

    def _update_preview(self, value: int) -> None:
        self.value.setText(f"{value} %")
        font = QFont(self.preview.font())
        font.setPointSizeF(base_point_size() * value / 100 * 1.6)
        font.setBold(True)
        self.preview.setFont(font)

    def load(self, d: dict) -> None:
        self.slider.setValue(round(d["appearance"]["font_scale"] * 100))
        self._update_preview(self.slider.value())
        _select(self.theme, d["appearance"]["theme"])

    def collect(self, d: dict) -> None:
        d["appearance"].update(font_scale=self.slider.value() / 100, theme=self.theme.currentData())


class AdvancedPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.power_sign = _combo([(tr("power.plus"), "plus_is_charging"), (tr("power.minus"), "minus_is_charging")],
                                 "plus_is_charging")
        self.counter_unit = _combo([("Wh", "Wh"), ("0.1 Wh", "0.1Wh"), ("0.01 kWh", "0.01kWh"), ("kWh", "kWh")], "Wh")
        self.verified = QCheckBox(tr("settings.counters_verified"))
        self.outage = QCheckBox(tr("settings.outage_detection"))
        self.rearm_pct = _spin(0, 20, 2, " %")
        self.rearm_c = _spin(0, 20, 2, " °C")
        self.reserve = _spin(0, 50, 12, " %")
        self.retention = _spin(1, 365, 30, tr("settings.days_suffix"))
        self.log_level = _combo([(x, x) for x in ("DEBUG", "INFO", "WARNING", "ERROR")], "INFO")
        self.record_raw = QCheckBox(tr("settings.record_raw"))
        folder = QPushButton(tr("settings.open_folder"))
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir()))))
        form.addRow(tr("settings.power_sign"), self.power_sign)
        form.addRow(tr("settings.counter_unit"), self.counter_unit)
        form.addRow("", self.verified)
        form.addRow("", self.outage)
        form.addRow(tr("settings.rearm_pct"), self.rearm_pct)
        form.addRow(tr("settings.rearm_c"), self.rearm_c)
        form.addRow(tr("settings.reserve"), self.reserve)
        form.addRow(tr("settings.retention"), self.retention)
        form.addRow(tr("settings.log_level"), self.log_level)
        form.addRow("", self.record_raw)
        form.addRow("", folder)

    def load(self, d: dict) -> None:
        a = d["advanced"]
        _select(self.power_sign, a["power_sign"])
        _select(self.counter_unit, a["counter_unit"])
        self.verified.setChecked(a["counters_verified"])
        self.outage.setChecked(a["outage_detection"])
        self.rearm_pct.setValue(a["rearm_pct"])
        self.rearm_c.setValue(a["rearm_c"])
        self.reserve.setValue(a["reserve_soc_pct"])
        self.retention.setValue(a["samples_retention_days"])
        _select(self.log_level, a["log_level"])
        self.record_raw.setChecked(a["record_raw"])

    def collect(self, d: dict) -> None:
        d["advanced"].update(
            power_sign=self.power_sign.currentData(), counter_unit=self.counter_unit.currentData(),
            counters_verified=self.verified.isChecked(), outage_detection=self.outage.isChecked(),
            rearm_pct=self.rearm_pct.value(), rearm_c=self.rearm_c.value(), reserve_soc_pct=self.reserve.value(),
            samples_retention_days=self.retention.value(), log_level=self.log_level.currentData(),
            record_raw=self.record_raw.isChecked(),
        )


class SettingsWindow(QWidget):
    saved = Signal(object)
    rediscover = Signal()
    test_notification = Signal(str, object)
    detect_chat = Signal(str)
    send_test = Signal(object)

    def __init__(self, data: dict, icon: QIcon | None = None, delete_on_close: bool = True, notice: str = ""):
        super().__init__()
        self.setWindowTitle(tr("app.settings_title"))
        if icon is not None:
            self.setWindowIcon(icon)
        if delete_on_close:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(940, 660)
        self._data = copy.deepcopy(data)

        self.general = GeneralPage(self)
        self.notifications = NotificationsPage(self)
        self.telegram = TelegramPage(self)
        self.appearance = AppearancePage(self)
        self.advanced = AdvancedPage(self)
        self.pages = (self.general, self.notifications, self.telegram, self.appearance, self.advanced)
        titles = (tr("settings.page.general"), tr("settings.page.notifications"), tr("settings.page.telegram"),
                  tr("settings.page.appearance"), tr("settings.page.advanced"))

        self.side = QListWidget()
        self.side.setFixedWidth(190)
        self.stack = QStackedWidget()
        for title, page in zip(titles, self.pages):
            self.side.addItem(title)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.side.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.side.setCurrentRow(0)

        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(self.close)
        self.save_button = QPushButton(tr("settings.save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)

        body = QHBoxLayout()
        body.addWidget(self.side)
        body.addWidget(self.stack, 1)
        root = QVBoxLayout(self)
        self.notice_label = label(notice, "banner-orange", wrap=True) if notice else None
        if self.notice_label is not None:  # e.g. "UDP port 30000 is used by another program"
            root.addWidget(self.notice_label)
        root.addLayout(body, 1)
        root.addLayout(buttons)

        for page in self.pages:
            page.load(self._data)

    def collect(self) -> dict:
        data = copy.deepcopy(self._data)
        for page in self.pages:
            page.collect(data)
        return validate(data)

    def _save(self) -> None:
        self.saved.emit(self.collect())
        self.close()

    def set_telegram_status(self, text: str) -> None:
        self.telegram.status.setText(text)

    def set_chat_id(self, chat_id: str) -> None:
        self.telegram.chat.setText(chat_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_settings_window.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add marstek_monitor/ui/settings_window.py tests/test_settings_window.py
git commit -m "feat: settings window with notifications, Telegram and appearance pages"
```

---
### Task 21: App wiring, desktop notifier, entry point, clean exit

**Files:**
- Create: `marstek_monitor/notify/desktop.py`, `marstek_monitor/app.py`, `marstek_monitor/main.py`, `marstek_monitor/__main__.py`
- Test: `tests/test_app.py`, `tests/test_i18n_coverage.py`, `tests/test_exit.py`

**Interfaces:**
- Consumes everything above. The exact names used here are:
  - **storage and pipeline:**
    - `settings_mod.load/save` (Task 3)
    - `Storage` (Task 8)
    - `Monitor` with `.handle`, `.emit`, `.system_event`, `.record_delivery`, `.apply_settings`, `.purge`, `.close`, `.rules.monitor_event`, `.rules.test_event`, `.state` (Task 11)
  - **polling:**
    - `Poller`, `PollerConfig` (Task 10)
    - `PollerThread(poller, interval_s)` with `.result`, `.stop()`, `.wake()`, `.poller` (Task 10)
  - **Telegram:** `TelegramApi`, `TelegramService`, `TelegramError`, `detect_chat_id` (Task 14)
  - **platform:** `SingleInstance` with `.activated`, `.release()` (Task 15); `autostart.set_enabled`, `shortcut.sync` (Task 15)
  - **UI:**
    - `Tray` with `.open_requested`, `.settings_requested`, `.exit_requested`, `.update_state`, `.retranslate`, `.icon` (Task 16)
    - `make_icon` (Task 16)
    - `StatusWindow` with `.show_tab`, `.current_tab`, `.on_update`, `.refresh` (Task 18)
    - `SettingsWindow` with `saved`, `rediscover`, `test_notification`, `detect_chat`, `send_test`, `.set_telegram_status`, `.set_chat_id`, and the `notice=` argument (Task 20)
  - **text:** `present.render_event`, `present.telegram_status` (Task 13)
- Produces:
  - `notify.desktop.DesktopNotifier(icon: QSystemTrayIcon, open_tab: Callable[[str], None])` with `.show(title, body, critical, tab) -> bool`
  - module-level helpers in `app.py`:
    - `poller_config(settings) -> PollerConfig`
    - `poller_key(settings) -> str`
    - `telegram_config_problem(tg: dict) -> str | None`
    - `apply_device_change(settings, ip, ble_mac) -> bool`
    - `tab_for(e: Event) -> str`
  - `App(qapp, instance, exit_after: float | None = None)` with `.exit()`, `.show_unexpected_error()`
  - `main.main(argv=None) -> int`; command line `python -m marstek_monitor [--exit-after SECONDS]` (the flag is hidden and used by tests)
- Environment variables honoured (tests):
  - `MARSTEK_MONITOR_HOME` (Task 1)
  - `MARSTEK_MONITOR_INSTANCE`: suffix for the single-instance names
  - `MARSTEK_MONITOR_NO_PLATFORM=1`: skip the autostart and Start-menu sync

- [ ] **Step 1: Write the failing tests**

`tests/test_app.py`:

```python
from marstek_monitor import settings as settings_mod
from marstek_monitor.app import apply_device_change, poller_config, poller_key, tab_for, telegram_config_problem
from marstek_monitor.core.events import Event


def test_poller_config_from_settings():
    cfg = settings_mod.defaults()
    cfg["device"].update(ip="192.168.1.20", ble_mac="0123456789ab", local_port=40000)
    cfg["advanced"]["counter_unit"] = "0.01kWh"
    pc = poller_config(cfg)
    assert (pc.ip, pc.port, pc.ble_mac, pc.local_port, pc.poll_seconds, pc.offline_after_polls) == (
        "192.168.1.20", 30000, "0123456789ab", 40000, 60, 3)
    assert pc.normalize.counter_unit == "0.01kWh"


def test_poller_key_changes_only_for_poller_settings():
    a = settings_mod.defaults()
    b = settings_mod.defaults()
    b["appearance"]["font_scale"] = 1.5
    assert poller_key(a) == poller_key(b)
    b["general"]["poll_seconds"] = 120
    assert poller_key(a) != poller_key(b)


def test_telegram_config_problem():
    tg = settings_mod.defaults()["telegram"]
    assert telegram_config_problem(tg) is None
    tg["enabled"] = True
    assert telegram_config_problem(tg) == "settings.tg_missing"
    tg.update(bot_token="123:abc", chat_id="")
    assert telegram_config_problem(tg) == "settings.tg_missing"
    tg["chat_id"] = "100"
    assert telegram_config_problem(tg) is None


def test_device_change_is_persisted():
    cfg = settings_mod.defaults()
    assert apply_device_change(cfg, "192.168.1.77", "0123456789ab") is True
    assert cfg["device"]["ip"] == "192.168.1.77" and cfg["device"]["ble_mac"] == "0123456789ab"
    assert apply_device_change(cfg, "192.168.1.77", "0123456789ab") is False
    assert apply_device_change(cfg, None, "") is False


def test_tab_for():
    def e(rule_id, kind="notification"):
        return Event(ts=0, kind=kind, rule_id=rule_id, priority="normal", title_key="x", body_key="")
    assert tab_for(e("charge_session")) == "sessions"
    assert tab_for(e("system", kind="system")) == "events"
    assert tab_for(e("soc_below")) == "now"
```

`tests/test_i18n_coverage.py`:

```python
"""Every i18n key that appears as a string literal in the source exists in en.json."""
import ast
import json
from pathlib import Path

from marstek_monitor import i18n

PACKAGE = Path(i18n.__file__).parent.parent
EN = json.loads((Path(i18n.__file__).parent / "en.json").read_text(encoding="utf-8"))
PREFIXES = ("app.", "tray.", "tab.", "state.", "now.", "est.", "grid.", "banner.", "details.", "footer.",
            "sess.", "sessions.", "tip.", "tg.", "day.", "dur.", "unit.", "num.", "n.", "sys.", "energy.",
            "month.", "live.", "events.", "settings.", "col.", "group.", "rule.", "badge.", "priority.",
            "theme.", "power.")
FILE_SUFFIXES = (".json", ".db", ".log", ".jsonl", ".lnk", ".exe", ".tmp")


def referenced_keys():
    for py in PACKAGE.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        # fragments of f-strings (e.g. f"settings.broken-{ts}.json") are not i18n keys
        fragments = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in fragments:
                value = node.value
                if value.startswith(PREFIXES) and " " not in value and not value.endswith(FILE_SUFFIXES):
                    yield f"{py.relative_to(PACKAGE)}", value


def test_all_referenced_keys_exist():
    missing = sorted({f"{where}: {key}" for where, key in referenced_keys() if key not in EN})
    assert missing == []
```

`tests/test_exit.py`:

```python
"""Exit from the tray stops the whole process quickly and frees the UDP port (spec §10.1)."""
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from marstek_monitor import settings as settings_mod
from tests.fakes.fake_battery import FakeBattery
from tests.fakes.net import free_udp_port

REPO = Path(__file__).parent.parent
EXIT_AFTER_S = 4


def test_exit_stops_process_and_frees_port(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    local_port = free_udp_port()
    with FakeBattery() as battery:
        cfg = settings_mod.defaults()
        cfg["device"].update(ip="127.0.0.1", port=battery.port, local_port=local_port)
        (home / "settings.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = dict(os.environ, MARSTEK_MONITOR_HOME=str(home), MARSTEK_MONITOR_INSTANCE=f"test-{uuid.uuid4().hex}",
                   MARSTEK_MONITOR_NO_PLATFORM="1", QT_QPA_PLATFORM="offscreen")
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, "-m", "marstek_monitor", "--exit-after", str(EXIT_AFTER_S)],
                                env=env, cwd=REPO)
        try:
            code = proc.wait(timeout=40)
        finally:
            if proc.poll() is None:
                proc.kill()
        elapsed = time.monotonic() - started
        assert code == 0
        assert elapsed < EXIT_AFTER_S + 6 + 10  # exit trigger + 6 s budget + generous startup margin
        assert "Bat.GetStatus" in battery.methods_received()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", local_port))  # raises if the app still held the port
    sock.close()
    assert "Marstek Monitor starting" in (home / "logs" / "app.log").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_app.py tests/test_i18n_coverage.py tests/test_exit.py -v`
Expected: FAIL. `test_app.py` errors with `ModuleNotFoundError: No module named 'marstek_monitor.app'`, and `test_exit.py` fails because `python -m marstek_monitor` has no `__main__`. `test_i18n_coverage.py` should already pass; if it does not, add the missing keys it lists to both JSON files.

- [ ] **Step 3: Implement the desktop notifier**

`marstek_monitor/notify/desktop.py`:

```python
"""Desktop notifications as Windows toasts through the tray icon (spec §6.8)."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import QSystemTrayIcon

log = logging.getLogger(__name__)
TOAST_MS = 10_000


class DesktopNotifier:
    def __init__(self, icon: QSystemTrayIcon, open_tab: Callable[[str], None]):
        self.icon = icon
        self._tab = "now"
        icon.messageClicked.connect(lambda: open_tab(self._tab))

    def show(self, title: str, body: str, critical: bool, tab: str) -> bool:
        self._tab = tab
        if not QSystemTrayIcon.isSystemTrayAvailable() or not self.icon.isVisible():
            log.info("Desktop notification not shown (no system tray): %s", title)
            return False
        kind = QSystemTrayIcon.MessageIcon.Critical if critical else QSystemTrayIcon.MessageIcon.Information
        self.icon.showMessage(title, body, kind, TOAST_MS)
        return True
```

- [ ] **Step 4: Implement the app**

`marstek_monitor/app.py`:

```python
"""Qt glue (spec §5, §10.1): poller thread → monitor pipeline → tray, windows and notifiers."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import i18n, paths, settings as settings_mod
from .core.events import Event
from .core.monitor import Monitor
from .core.poller import Poller, PollerConfig, PollResult
from .core.poller_thread import PollerThread
from .core.snapshot import NormalizeConfig
from .core.storage import Storage
from .logging_setup import RawRecorder, setup_logging
from .notify.desktop import DesktopNotifier
from .notify.telegram import TelegramApi, TelegramError, TelegramService, detect_chat_id
from .platform import autostart, shortcut
from .present import render_event, telegram_status
from .ui import theme
from .ui.settings_window import SettingsWindow
from .ui.status_window import StatusWindow
from .ui.tray import Tray, make_icon

log = logging.getLogger(__name__)
EXIT_HARD_LIMIT_S = 5.0
PURGE_INTERVAL_MS = 3_600_000


def poller_config(s: dict) -> PollerConfig:
    return PollerConfig(
        ip=s["device"]["ip"], port=s["device"]["port"], ble_mac=s["device"]["ble_mac"],
        local_port=s["device"]["local_port"], poll_seconds=s["general"]["poll_seconds"],
        offline_after_polls=s["general"]["offline_after_polls"],
        normalize=NormalizeConfig(s["advanced"]["power_sign"], s["advanced"]["counter_unit"]),
    )


def poller_key(s: dict) -> str:
    return json.dumps([s["device"], s["general"]["poll_seconds"], s["general"]["offline_after_polls"],
                       s["advanced"]["power_sign"], s["advanced"]["counter_unit"], s["advanced"]["record_raw"]],
                      sort_keys=True)


def telegram_config_problem(tg: dict) -> str | None:
    if tg["enabled"] and (not tg["bot_token"] or not tg["chat_id"]):
        return "settings.tg_missing"
    return None


def apply_device_change(settings: dict, ip: str | None, ble_mac: str | None) -> bool:
    device = settings["device"]
    changed = False
    if ip and ip != device["ip"]:
        device["ip"] = ip
        changed = True
    if ble_mac and ble_mac != device["ble_mac"]:
        device["ble_mac"] = ble_mac
        changed = True
    return changed


def tab_for(e: Event) -> str:
    if e.rule_id in ("charge_session", "discharge_session"):
        return "sessions"
    return "events" if e.kind == "system" else "now"


class Bridge(QObject):
    """Carries callbacks from worker threads to the Qt main thread."""

    delivery = Signal(object, str)
    problem = Signal(str, object)
    command = Signal()
    settings_status = Signal(str)
    chat_detected = Signal(str)


class App(QObject):
    def __init__(self, qapp, instance, exit_after: float | None = None):
        super().__init__()
        self.qapp = qapp
        self.instance = instance
        self._exiting = False
        self.settings, warning = settings_mod.load(paths.settings_path())
        setup_logging(self.settings["advanced"]["log_level"])
        log.info("Marstek Monitor starting")
        i18n.set_language(self.settings["general"]["language"])
        theme.apply(qapp, self.settings["appearance"]["theme"], self.settings["appearance"]["font_scale"])

        storage = None
        try:
            storage = Storage(paths.db_path())
        except sqlite3.Error:
            log.exception("Cannot open the history database")
        self.monitor = Monitor(self.settings, storage)
        if storage is None:
            self.monitor.state.history_ok = False

        self.bridge = Bridge()
        self.bridge.delivery.connect(self._on_delivery)
        self.bridge.problem.connect(self._on_problem)
        self.bridge.command.connect(lambda: self.monitor.system_event("sys.telegram_command"))
        self.bridge.settings_status.connect(self._on_settings_status)
        self.bridge.chat_detected.connect(self._on_chat_detected)

        self.app_icon = make_icon("M", theme.COLORS["charging"])
        self.tray = Tray()
        self.tray.open_requested.connect(lambda: self.open_status("now"))
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.exit_requested.connect(self.exit)
        self.tray.show()
        self.desktop = DesktopNotifier(self.tray.icon, self.open_status)
        self.status = self._make_status_window()
        self.settings_win: SettingsWindow | None = None
        self.instance.activated.connect(lambda: self.open_status(self.status.current_tab()))

        self._status_text = telegram_status(self.monitor.state, time.time())
        self.telegram: TelegramService | None = None
        self._start_telegram()
        self.poller_thread: PollerThread | None = None
        self._start_poller()

        if warning:
            self.dispatch([self.monitor.system_event(warning, desktop=True)])
        started = self.monitor.rules.monitor_event(time.time(), started=True)
        if started is not None:
            self.dispatch(self.monitor.emit([started], bypass_quiet=True))
        self._sync_platform()
        self.monitor.purge()
        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self.monitor.purge)
        self._purge_timer.start(PURGE_INTERVAL_MS)
        self.tray.update_state(self.monitor.state, time.time())
        if exit_after is not None:
            QTimer.singleShot(int(exit_after * 1000), self.exit)

    # -- components ----------------------------------------------------------

    def _make_status_window(self) -> StatusWindow:
        return StatusWindow(self.monitor, lambda: self.settings, icon=self.app_icon)

    def _start_poller(self) -> None:
        recorder = RawRecorder() if self.settings["advanced"]["record_raw"] else None
        poller = Poller(poller_config(self.settings), raw_recorder=recorder)
        self.poller_thread = PollerThread(poller, self.settings["general"]["poll_seconds"])
        self.poller_thread.result.connect(self._on_result)
        self.poller_thread.start()

    def _stop_poller(self, wait_ms: int = 4000) -> None:
        if self.poller_thread is not None:
            self.poller_thread.stop()
            self.poller_thread.wait(wait_ms)
            self.poller_thread = None

    def _start_telegram(self) -> None:
        tg = self.settings["telegram"]
        problem = telegram_config_problem(tg)
        if not tg["enabled"] or problem:
            if problem:
                log.warning("Telegram is enabled but not configured (%s)", problem)
            return
        self.telegram = TelegramService(
            TelegramApi(tg["bot_token"]), chat_id=tg["chat_id"], user_id=tg["user_id"],
            answer_command=tg["answer_command"], status_provider=lambda: self._status_text,
            on_delivery=self.bridge.delivery.emit, on_problem=self.bridge.problem.emit,
            on_command=self.bridge.command.emit,
        )
        self.telegram.start()

    def _stop_telegram(self, flush_s: float = 0.0) -> None:
        if self.telegram is not None:
            if flush_s:
                self.telegram.flush(flush_s)
            self.telegram.stop()
            self.telegram = None

    def _sync_platform(self) -> None:
        if os.environ.get("MARSTEK_MONITOR_NO_PLATFORM"):
            return
        general = self.settings["general"]
        try:
            autostart.set_enabled(general["autostart"])
        except OSError:
            log.exception("Updating autostart failed")
        try:
            shortcut.sync(general["start_menu_shortcut"])
        except (OSError, subprocess.SubprocessError):
            log.exception("Updating the Start menu shortcut failed")

    # -- data flow -------------------------------------------------------------

    def _on_result(self, r: PollResult) -> None:
        if self._exiting:
            return
        events = self.monitor.handle(r)
        poller = self.poller_thread.poller if self.poller_thread is not None else None
        if poller is not None and apply_device_change(self.settings, poller.ip, poller.ble_mac):
            settings_mod.save(paths.settings_path(), self.settings)
        now = time.time()
        self._status_text = telegram_status(self.monitor.state, now)
        self.tray.update_state(self.monitor.state, now)
        self.status.on_update()
        self.dispatch(events)

    def dispatch(self, events: list[Event]) -> None:
        for e in events:
            title, body = render_event(e)
            if e.desktop == "pending":
                shown = self.desktop.show(title, body, e.priority == "critical", tab_for(e))
                self.monitor.record_delivery(e.id, "desktop", "sent" if shown else "failed")
            if e.telegram == "pending":
                if self.telegram is not None:
                    self.telegram.send(f"{title}\n{body}".strip(), e.id)
                else:
                    self.monitor.record_delivery(e.id, "telegram", "failed")
        if events and self.status.isVisible():
            self.status.refresh()

    def _on_delivery(self, event_id, status: str) -> None:
        self.monitor.record_delivery(event_id, "telegram", status)

    def _on_problem(self, key: str, params) -> None:
        self.monitor.system_event(key, params or {})
        if key == "sys.telegram_invalid_token" and self.settings_win is not None:
            self.settings_win.set_telegram_status(i18n.tr(key))
        if self.status.isVisible():
            self.status.refresh()

    def show_unexpected_error(self) -> None:
        self.monitor.state.error_key = "sys.unexpected_error"
        self.monitor.state.error_params = {}
        self.tray.update_state(self.monitor.state, time.time())

    # -- windows ---------------------------------------------------------------

    def open_status(self, tab: str = "now") -> None:
        self.status.show_tab(tab)

    def open_settings(self) -> None:
        if self.settings_win is not None:
            self.settings_win.showNormal()
            self.settings_win.raise_()
            self.settings_win.activateWindow()
            return
        state = self.monitor.state
        notice = i18n.tr(state.error_key, **state.error_params) if state.error_key else ""
        win = SettingsWindow(self.settings, icon=self.app_icon, notice=notice)
        win.saved.connect(self._on_settings_saved)
        win.rediscover.connect(self._rediscover)
        win.test_notification.connect(self._on_test_notification)
        win.detect_chat.connect(self._detect_chat)
        win.send_test.connect(self._send_telegram_test)
        win.destroyed.connect(self._on_settings_closed)
        self.settings_win = win
        win.show()

    def _on_settings_closed(self, *_args) -> None:
        self.settings_win = None

    def _on_settings_saved(self, new: dict) -> None:
        old = self.settings
        self.settings = new
        settings_mod.save(paths.settings_path(), new)
        setup_logging(new["advanced"]["log_level"])
        i18n.set_language(new["general"]["language"])
        theme.apply(self.qapp, new["appearance"]["theme"], new["appearance"]["font_scale"])
        self.monitor.apply_settings(new)
        if poller_key(old) != poller_key(new):
            self._stop_poller()
            self._start_poller()
        if old["telegram"] != new["telegram"]:
            self._stop_telegram()
            self._start_telegram()
        self._sync_platform()
        self.tray.retranslate()
        visible, tab = self.status.isVisible(), self.status.current_tab()
        self.status.hide()
        self.status.deleteLater()
        self.status = self._make_status_window()
        if visible:
            self.status.show_tab(tab)
        self.tray.update_state(self.monitor.state, time.time())

    def _rediscover(self) -> None:
        if self.poller_thread is not None:
            self.poller_thread.poller.request_discovery()
            self.poller_thread.wake()

    def _on_test_notification(self, _rule: str, cfg) -> None:
        e = self.monitor.rules.test_event(time.time(), desktop=bool(cfg.get("desktop")),
                                          telegram=bool(cfg.get("telegram")))
        self.dispatch(self.monitor.emit([e], bypass_quiet=True))

    def _detect_chat(self, token: str) -> None:
        if not token:
            self._on_settings_status(i18n.tr("settings.tg_missing"))
            return

        def work() -> None:
            try:
                self.bridge.chat_detected.emit(detect_chat_id(TelegramApi(token)) or "")
            except TelegramError as exc:
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_failed",
                                                         error=exc.description or exc.status))

        threading.Thread(target=work, name="telegram-detect", daemon=True).start()

    def _send_telegram_test(self, values: dict) -> None:
        if not values["bot_token"] or not values["chat_id"]:
            self._on_settings_status(i18n.tr("settings.tg_missing"))
            return
        text = f"{i18n.tr('n.test.title')}\n{i18n.tr('n.test.body')}"

        def work() -> None:
            try:
                TelegramApi(values["bot_token"]).send_message(values["chat_id"], text)
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_ok"))
            except TelegramError as exc:
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_failed",
                                                         error=exc.description or exc.status))

        threading.Thread(target=work, name="telegram-test", daemon=True).start()

    def _on_settings_status(self, text: str) -> None:
        if self.settings_win is not None:
            self.settings_win.set_telegram_status(text)

    def _on_chat_detected(self, chat_id: str) -> None:
        if self.settings_win is None:
            return
        if chat_id:
            self.settings_win.set_chat_id(chat_id)
            self.settings_win.set_telegram_status(i18n.tr("settings.tg_detected"))
        else:
            self.settings_win.set_telegram_status(i18n.tr("settings.tg_detect_none"))

    # -- exit ------------------------------------------------------------------

    def exit(self) -> None:
        """Stop everything (spec §10.1); a watchdog ends the process after 5 s regardless."""
        if self._exiting:
            return
        self._exiting = True
        log.info("Exiting")
        watchdog = threading.Timer(EXIT_HARD_LIMIT_S, lambda: os._exit(0))
        watchdog.daemon = True
        watchdog.start()
        self._stop_poller(wait_ms=3000)                      # 1. poller thread (also frees the UDP port)
        stopped = self.monitor.rules.monitor_event(time.time(), started=False)
        if stopped is not None and self.telegram is not None:  # 2. "Monitor stopped", max 3 s
            [event] = self.monitor.emit([stopped], bypass_quiet=True)
            title, body = render_event(event)
            self.telegram.send(f"{title}\n{body}", event.id)
            self._stop_telegram(flush_s=3.0)
        else:
            self._stop_telegram()                             # 3. long poll is a daemon thread
        self.monitor.close()                                  # 4. database
        self.instance.release()                               # 5. single-instance mutex
        self.tray.hide()                                      # 6. tray icon
        if self.settings_win is not None:
            self.settings_win.close()
        self.qapp.quit()                                      # 7. end the event loop → process exits
```

- [ ] **Step 5: Implement the entry point**

`marstek_monitor/main.py`:

```python
"""Entry point: python -m marstek_monitor (or MarstekMonitor.exe)."""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
import threading

from PySide6.QtWidgets import QApplication

from . import APP_NAME
from .platform.single_instance import SingleInstance

log = logging.getLogger("marstek_monitor")


def _set_app_user_model_id() -> None:
    try:  # groups toasts and the taskbar entry under "MarstekMonitor"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MarstekMonitor")
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="marstek_monitor")
    parser.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _set_app_user_model_id()
    qapp = QApplication(sys.argv[:1])
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(os.environ.get("MARSTEK_MONITOR_INSTANCE", ""))
    if not instance.acquire():
        return 0

    from .app import App  # imported late so a second copy exits fast

    app = App(qapp, instance, exit_after=args.exit_after)

    def excepthook(exc_type, exc, tb) -> None:
        log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
        app.show_unexpected_error()

    def thread_excepthook(hook_args) -> None:
        log.critical("Unhandled exception in thread %s", hook_args.thread.name if hook_args.thread else "?",
                     exc_info=(hook_args.exc_type, hook_args.exc_value, hook_args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook
    return qapp.exec()
```

`marstek_monitor/__main__.py`:

```python
from .main import main

raise SystemExit(main())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_app.py tests/test_i18n_coverage.py tests/test_exit.py -v`
Expected: 7 passed

- [ ] **Step 7: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests pass (about 200)

- [ ] **Step 8: Smoke-run against the real battery (read-only)**

Run: `.venv/Scripts/python -m marstek_monitor`
Expected:
- A grey `--` tile appears in the tray, then within about 10 s turns into the SOC number (`100` when full).
- Hovering shows `Marstek Venus E · 100% · …`.
- Left-click opens the status window.
- Windows may ask once whether Python may receive UDP on private networks; allow it.
- Tray → Exit removes the icon, and `Get-Process python` no longer lists the app.
- `%APPDATA%\MarstekMonitor\logs\app.log` contains `Marstek Monitor starting`.

- [ ] **Step 9: Commit**

```bash
git add marstek_monitor/notify/desktop.py marstek_monitor/app.py marstek_monitor/main.py marstek_monitor/__main__.py tests/test_app.py tests/test_i18n_coverage.py tests/test_exit.py
git commit -m "feat: app wiring, entry point and clean exit"
```

---

### Task 22: Packaging as MarstekMonitor.exe, README, verification checklist

**Files:**
- Create: `packaging/launcher.py`, `packaging/make_icon.py`, `packaging/version_info.txt`, `packaging/MarstekMonitor.spec`, `packaging/build.ps1`
- Create: `README.md`, `docs/verification-checklist.md`

**Interfaces:**
- Consumes: `marstek_monitor.main.main` (Task 21), `ui.tray.render_tile` (Task 16).
- Produces: `dist/MarstekMonitor/MarstekMonitor.exe` (not committed), `packaging/icon.ico` (committed).

- [ ] **Step 1: Create the packaging files**

`packaging/launcher.py`:

```python
"""PyInstaller entry point for MarstekMonitor.exe."""
from marstek_monitor.main import main

raise SystemExit(main())
```

`packaging/make_icon.py`:

```python
"""Render packaging/icon.ico (green tile with "M") with the app's own tile renderer."""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv[:1])  # noqa: F841 - QPixmap needs an application object
    from marstek_monitor.ui.tray import render_tile

    out = Path(__file__).with_name("icon.ico")
    if not render_tile("M", "#2ea043", 256).toImage().save(str(out), "ICO"):
        raise SystemExit("Could not write icon.ico (Qt ICO image plugin missing)")
    print(f"written {out}")


if __name__ == "__main__":
    main()
```

`packaging/version_info.txt`:

```
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(0, 1, 0, 0),
    prodvers=(0, 1, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Personal'),
        StringStruct('FileDescription', 'Marstek Monitor'),
        StringStruct('FileVersion', '0.1.0'),
        StringStruct('InternalName', 'MarstekMonitor'),
        StringStruct('OriginalFilename', 'MarstekMonitor.exe'),
        StringStruct('ProductName', 'Marstek Monitor'),
        StringStruct('ProductVersion', '0.1.0')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
```

`packaging/MarstekMonitor.spec`:

```python
# PyInstaller spec: one-folder build of MarstekMonitor.exe (design spec §10).
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "marstek_monitor" / "i18n" / "*.json"), "marstek_monitor/i18n")],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MarstekMonitor",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MarstekMonitor")
```

`packaging/build.ps1`:

```powershell
# Builds dist\MarstekMonitor\MarstekMonitor.exe (run from any folder).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
.\.venv\Scripts\python packaging\make_icon.py
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\MarstekMonitor.spec
Write-Host "Built: dist\MarstekMonitor\MarstekMonitor.exe"
```

- [ ] **Step 2: Build**

Run (PowerShell): `powershell -ExecutionPolicy Bypass -File packaging\build.ps1`
Expected: ends with `Built: dist\MarstekMonitor\MarstekMonitor.exe`, and `packaging\icon.ico` exists.

- [ ] **Step 3: Verify the exe in Task Manager terms**

Run `dist\MarstekMonitor\MarstekMonitor.exe`, wait about 10 s, then in PowerShell:
`Get-Process MarstekMonitor | Select-Object Name, Description, Path`
Expected: one process with `Name` `MarstekMonitor` and `Description` `Marstek Monitor`. In Task Manager it shows as **Marstek Monitor** with the green "M" icon.

Then:
- Tray → Exit, then run `Get-Process MarstekMonitor`. Expected: no process (error "Cannot find a process").
- Start the exe twice quickly. Expected: still one process, and the second launch brings the status window to the front.
- After the first exe run, `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Marstek Monitor.lnk` exists.

- [ ] **Step 4: Write the README**

`README.md`:

````markdown
# Marstek Monitor

Read-only Windows tray monitor for a **Marstek Venus E 3.0** battery, using its Local API
(JSON over UDP on the home network). It shows the charge level in the tray, has a status
window (Now · Energy · Live · Sessions · Events), and sends desktop and Telegram notifications.

**It never changes any battery setting.** Only these read commands are ever sent:
`Marstek.GetDevice`, `Wifi.GetStatus`, `Bat.GetStatus`, `ES.GetStatus`, `EM.GetStatus`.

## Requirements

- Windows 11, Python 3.13 (for running from source)
- Local API enabled in the Marstek app (default UDP port 30000), with the PC on the same network

## Run from source

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m marstek_monitor
```

On the first run Windows may ask whether the app may receive UDP on private networks. Allow it,
otherwise the battery's replies are blocked.

## Build the exe

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The result is `dist\MarstekMonitor\MarstekMonitor.exe` (one folder, about 100 MB). Copy the whole folder.

## Data

`%APPDATA%\MarstekMonitor\`: `settings.json`, `history.db`, and `logs\app.log`. With
*Advanced → Record raw data* switched on, every raw response is also saved to `logs\raw-YYYYMMDD.jsonl`.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

## Open questions

Some values still need a read-only check on the real battery (power sign, counter units,
how an outage looks). See `docs/verification-checklist.md`.
````

- [ ] **Step 5: Write the verification checklist**

`docs/verification-checklist.md`:

```markdown
# Real-device verification (read-only)

These checks settle the open questions V1–V5 from the design spec. None of them changes a battery
setting. Before you start, turn on **Settings → Advanced → Record raw data** and click **Save**.
The raw responses go to `%APPDATA%\MarstekMonitor\logs\raw-YYYYMMDD.jsonl`.

## V1: Power sign (while charging)

1. Wait until the battery is charging. In UPS mode the Marstek app shows a charge power of 1000 W.
2. Open the monitor's **Now** tab.
   - If it shows **↓ Charging · ≈1 000 W**, the default is right.
   - If it shows **↑ Supplying**, set **Advanced → Power sign → − means charging** and click **Save**.
3. Repeat while the battery is supplying power, to confirm the opposite direction.

## V2: Counter units

1. Compare **Energy → Charged / Discharged (lifetime)** with the totals in the Marstek app.
2. If they differ by a factor of 10, 100 or 1000, pick the matching **Advanced → Counter unit**.
3. When the numbers match, tick **Counter units verified**. This shows the efficiency card and
   removes the "not verified" note.

## V3 + V5: What a grid outage looks like

1. Make sure something is plugged into the battery's backup (off-grid) socket.
2. Switch off the battery's grid supply for 1–2 minutes (breaker or plug), then switch it back on.
3. Keep the raw log for that time window. The question is: which of `ongrid_power` and
   `offgrid_power` change, and how?
4. Turn on **Advanced → Outage detection (experimental)** only after the heuristic in
   `core/outage.py` has been confirmed against the recording or adjusted to match it.

## V4: Mode (answered)

The API reports `"Manual"` while the Marstek app shows UPS, so the app does not use the mode at all.
```

- [ ] **Step 6: Run the whole suite once more and commit**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests pass

```bash
git add packaging README.md docs/verification-checklist.md
git commit -m "build: PyInstaller one-folder exe, README and verification checklist"
```
