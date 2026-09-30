# Marstek Monitor: Windows Tray App (Design Spec)

- **Date:** 2026-10-01
- **Status:** Draft, awaiting owner review
- **Target device:** Marstek Venus E 3.0 (2500 W / 5120 Wh), used as a **UPS**

---

## 1. Purpose

The official Marstek Android app does not cover the owner's needs. This project is a **read-only Windows
tray application**. It shows the battery's current state at a glance, sends desktop and Telegram
notifications about things that matter for UPS use, and keeps a small local history of charge and
discharge sessions and energy.

**Success criteria**

- The app runs quietly in the tray and is identifiable as "Marstek Monitor" in Task Manager.
- Values shown match the battery.
- Notifications arrive reliably, without spam (fire once per threshold crossing, optional reminders, quiet hours).
- The UI is readable, with an adjustable font size.
- **The app never changes any battery setting.**

## 2. Scope

### In scope (v1)

- Tray icon with SOC, a status window with 5 tabs (Now, Energy, Live, Sessions, Events), and a settings window.
- Desktop notifications and Telegram notifications, configurable per notification.
- Telegram `/marstek` read-only status command.
- Local history: samples, charge/discharge sessions, daily energy (from battery counters), events.
- English and Ukrainian UI.
- Packaged as `MarstekMonitor.exe` (PyInstaller, one-folder), optional start with Windows.

### Out of scope (explicit non-goals)

- **Any write/control command** to the battery (mode, power, schedules, DOD, LED, reset, version).
  Changing charge power was discussed and deliberately deferred.
- Wide statistics (temperature history, time-share, connection trends, backup event analytics). These move
  to a future **mobile app + always-on home collector** project.
- Modbus TCP access.
- Storing the Telegram token in Windows Credential Manager. Plain `settings.json` is accepted for now.
- Multiple batteries.

## 3. Device & API facts (verified 2026-10-01, read-only probe)

Protocol: **Marstek Device Open API Rev 3.1**, which is JSON-RPC-style over **UDP**. The owner enabled it in the Marstek app.

| Item | Value |
|---|---|
| Device | `VenusE 3.0`, firmware `ver: 144` |
| Address | `192.168.1.20`, UDP port `30000` |
| BLE MAC (stable identity) | `0123456789ab` |
| Response time | ~120–200 ms |

| Method | Result | Notes |
|---|---|---|
| `Marstek.GetDevice` (broadcast) | ✅ | discovery; returns `device`, `ver`, `ble_mac`, `wifi_mac`, `ip` |
| `Wifi.GetStatus` | ✅ | `rssi: -49` |
| `BLE.GetStatus` | ❌ timeout | not used by the app |
| `Bat.GetStatus` | ✅ | `soc`, `charg_flag`, `dischrg_flag`, `bat_temp`, `bat_capacity` (Wh stored), `rated_capacity` |
| `ES.GetStatus` | ✅ | `bat_soc`, `bat_cap`, `pv_power`, `ongrid_power`, `offgrid_power`, `total_grid_output_energy`, `total_grid_input_energy`, `total_load_energy`. **No `bat_power` field**, although the spec lists one |
| `ES.GetMode` | ✅ | `mode: "Manual"`, although the Marstek app shows UPS (see V4); `ongrid_power`, `offgrid_power`, `bat_soc`. **Not used by the app** |
| `EM.GetStatus` | ✅ | `ct_state: 0` (no CT meter connected) |

**Constraints learned (community reports + spec):**

- The client socket **must bind to the same local port as the device's API port**. The device replies to the source port.
- Polling faster than about **60 s** is reported to destabilize devices. The app enforces a minimum of 60 s.
- There is **no authentication** on the API. The app never exposes it beyond the LAN.
- Firmware quirks are reported: temperature ×10 on older battery-management firmware, energy counters in
  inconsistent units, and schedules that are write-only.
- System commands (`DOD.SET`, `Led.Ctrl`, …) need FW ≥ 150. Irrelevant, because this app writes nothing.

The captured responses are stored as test fixtures (`tests/fixtures/probe-2026-10-01.json`).

## 4. Open questions (need read-only verification on the real device)

These are isolated in configuration and normalization code so that answering them changes one place only.

| ID | Question | How to verify | Until verified |
|---|---|---|---|
| V1 | Which field carries battery charge/discharge power, and with which sign? (`ongrid_power`? `offgrid_power`?) | Record while charging and while discharging | Setting `advanced.power_sign`, default `+ = charging`; direction also inferred from SOC trend |
| V2 | Units of `total_grid_input_energy` / `total_grid_output_energy` (Wh vs 0.01 kWh vs 0.1 Wh) | Compare with totals in the Marstek app | Setting `advanced.counter_unit`, default `Wh`; Energy tab footer shows "unit check pending" |
| V3 | How does a grid outage appear in the data? | Switch off grid supply to the battery for 1–2 min while recording | "Grid lost/restored" and "Backup time left" notifications **off and marked experimental**; the Now tab's grid line shows "unknown" |
| V4 | ~~Does `ES.GetMode` report `"UPS"` in UPS mode?~~ **Answered 2026-10-01: no.** The Marstek app shows **UPS** (charge power 1000 W), but the API reports `"mode": "Manual"` (re-checked). | n/a | **Decision:** the app does not rely on the mode at all. It does not poll `ES.GetMode`, does not show the mode, and has no mode-related notifications. The UPS "Charge Power" setting is not exposed by any `Get*` method, so it cannot be displayed |
| V5 | Is the backup load visible (`offgrid_power`) so that "time left" can be computed? | Outage test (V3) | "Time left" hidden when not computable |

A **"Record raw data"** option (Advanced) writes every raw response to `logs/raw-YYYYMMDD.jsonl`. This supports
these checks and produces new test fixtures.

## 5. Architecture

A single Python 3.13 process using **PySide6 (Qt 6)**.

```
marstek_monitor/
  api/client.py          UDP JSON-RPC client, hard read-only allowlist, discovery
  core/snapshot.py       Snapshot dataclass + normalization (units, sign, sanity checks)
  core/poller.py         background poll loop (QThread), emits Snapshot / PollFailed
  core/sessions.py       charge/discharge session detector (pure logic)
  core/energy.py         daily/monthly/yearly energy from counter readings (pure logic)
  core/rules.py          notification rules engine (pure logic)
  core/storage.py        SQLite access (samples, counters, sessions, events)
  notify/desktop.py      desktop notifications via Qt tray messages
  notify/telegram.py     Telegram sender + /marstek listener (background thread)
  settings.py            settings model, defaults, validation, JSON load/save
  i18n/en.json, uk.json  UI strings
  ui/tray.py             tray icon rendering, tooltip, menu
  ui/status_window.py    tabs: Now, Energy, Live, Sessions, Events
  ui/settings_window.py  settings sidebar pages
  ui/theme.py            light/dark palette, font scaling
  platform/autostart.py  HKCU\Software\Microsoft\Windows\CurrentVersion\Run entry
  platform/single_instance.py
  main.py
tests/
packaging/MarstekMonitor.spec, version_info.txt, icon.ico
```

**Threads:**

- **Qt main thread:** all UI.
- **Poller thread:** network I/O to the battery.
- **Telegram thread:** sending queue plus `getUpdates` long polling.

They communicate only through Qt signals and a thread-safe queue. `core/sessions.py`, `core/energy.py`, `core/rules.py`
and normalization have no Qt, network or disk dependencies, so they can be unit-tested with plain data.

**Data flow per poll cycle:**

```
poller → client (Bat.GetStatus, ES.GetStatus [+ Wifi every 10th, GetDevice hourly])
       → Snapshot (normalized) → storage.samples
       → sessions.update() → storage.sessions
       → energy counter reading → storage.counters
       → rules.evaluate() → Events → storage.events → desktop / telegram dispatch
       → UI signal → tray icon + open windows refresh
```

## 6. Components

### 6.1 API client (`api/client.py`)

- **Allowlist:** `Marstek.GetDevice`, `Wifi.GetStatus`, `Bat.GetStatus`, `ES.GetStatus`, `EM.GetStatus`.
  (`ES.GetMode` is read-only but deliberately left out, see V4.)
  Any other method raises `ForbiddenMethodError` **before** anything is sent.
- The socket binds to `(<LAN interface IP>, <device port>)`, with `SO_BROADCAST` for discovery.
- **Request IDs** increase monotonically. A response is accepted only if `id` matches and it contains `result` or `error`.
- **Timeout** 5 s, 1 retry. Queries within a cycle are spaced ~1 s apart.
- **Discovery:** broadcast `Marstek.GetDevice` to the subnet broadcast address and `255.255.255.255`. The device is
  matched by `ble_mac` stored in settings; the first device found is adopted on first run.
- JSON-RPC `error` responses become `ApiError(code, message)`.

### 6.2 Snapshot & normalization (`core/snapshot.py`)

`Snapshot` fields:

- `ts_utc`
- `soc_pct`, `stored_wh`, `rated_wh`, `temp_c`
- `power_w` (+ = charging, after V1 mapping), `ongrid_w`, `offgrid_w`
- `charge_allowed`, `discharge_allowed`
- `counter_in_wh`, `counter_out_wh` (after V2 unit mapping)
- `rssi_dbm`
- `fw_version`, `ip`
- `failed_methods` (list)

Missing values are `None`.

**Sanity rules:**

- SOC outside 0–100 → `None`.
- `temp_c` > 100 → divide by 10 (known firmware bug); still > 100 → `None`.
- A counter lower than the previous reading → counter reset: store a new baseline and never produce negative energy.

### 6.3 Poller (`core/poller.py`)

- **Interval:** from settings (min 60 s, default 60 s).
- **Offline:** after `offline_after_polls` (default 3) consecutive fully failed cycles the battery is marked offline
  and discovery runs every cycle until it is found again.
- **Sleep/resume detection:** if wall-clock time since the last cycle is > 3 × interval, the poller records a
  **gap** and does **not** count missed cycles as failures.

### 6.4 Storage (`core/storage.py`)

SQLite in WAL mode at `%APPDATA%\MarstekMonitor\history.db`. All timestamps are UTC.

| Table | Content | Retention |
|---|---|---|
| `samples` | one row per poll (Snapshot fields + ok flag) | 30 days (setting) |
| `counters` | counter readings, at most one per 10 min, plus the first reading after each gap | forever (small) |
| `sessions` | detected sessions (see 6.5) | forever |
| `events` | notification and system events + per-channel delivery status | 90 days |
| `meta` | schema version, last known device info | n/a |

Wide per-minute history is not a goal (§2), so `samples` is capped at 30 days.

### 6.5 Sessions (`core/sessions.py`)

- **Direction** per sample: `charging` if `power_w` > +30 W, `discharging` if < −30 W, otherwise `idle`.
  If `power_w` is `None`, use the SOC trend over the last 3 samples.
- **Start:** 2 consecutive samples in the same non-idle direction.
- **End:** 2 consecutive samples of idle or opposite direction, or SOC reaches 100 % (charge).
- **Recorded fields:**
  - `kind` (charge/discharge)
  - `start_ts`, `end_ts`, `start_soc`, `end_soc`, `duration`
  - `energy_wh`: counter delta, falling back to ∫power·dt
  - `avg_power_w`
  - `cause`
  - `quality`
- **`cause`:**
  - discharge during a detected outage → `outage`
  - charge starting ≤ 30 min after an outage ended → `after_outage`
  - start SOC ≤ reserve SOC + 2 → `after_full_discharge`
  - otherwise `other`
- **`quality`:**
  - `complete`
  - `started_before_app`: start values are shown as ≤/≥ minimums
  - `gap`: > 3 missed cycles inside the session
  - `ended_while_off`
- **Summary cards:**
  - "Typical full charge": average duration of the last 5 complete charge sessions, scaled to 20→100 %.
  - "Longest backup": longest complete discharge session.

### 6.6 Energy (`core/energy.py`)

- Charged/discharged energy per period is the difference between counter readings at the period boundaries.
- If readings are missing across one or more whole days (PC off), the delta across the gap is shown as **one
  combined, hatched bar** spanning those days. Totals stay exact; the per-day split is unknown.
- Lifetime cards:
  - charged total, discharged total
  - equivalent full cycles = discharged ÷ rated capacity
  - round-trip efficiency = discharged ÷ charged
- **Round-trip efficiency is hidden until V1/V2 are verified**, because UPS passthrough may affect the counters.

### 6.7 Rules & notification catalogue (`core/rules.py`)

Each rule has:

- `enabled`
- `threshold(s)`, where applicable
- `desktop` / `telegram` flags
- `repeat_minutes` (0 = off)
- `priority` (normal/critical)

A rule **fires once per crossing** and re-arms after the value moves back past the threshold by the re-arm
margin (default 2 % / 2 °C).

| Rule | Default | Priority | Desktop | Telegram |
|---|---|---|---|---|
| SOC below (1–3 levels) | 40 % | normal | ✓ | – |
|  | 20 % | critical | ✓ | ✓ (repeat 30 min) |
| SOC reached | 100 % | normal | ✓ | – |
| Grid lost / restored *(experimental, V3)* | off | critical | ✓ | ✓ |
| Backup time left below *(experimental, V3/V5)* | off, 30 min | critical | ✓ | ✓ |
| Charge session finished | on | normal | ✓ | – |
| Discharge session finished | on | normal | ✓ | ✓ |
| Battery not responding / back online | after 3 polls | critical | ✓ | ✓ (repeat 60 min) |
| Charging / discharging blocked (`charg_flag`/`dischrg_flag` false) | on | critical | ✓ | ✓ (repeat 60 min) |
| Temperature above / below | 45 °C / 5 °C | critical | ✓ | ✓ |
| Firmware version changed | on | normal | ✓ | – |
| Monitor started / stopped | on | normal | – | ✓ (Telegram only) |

**Quiet hours** (default off, 23:00–07:00 when enabled):

- Hold **normal** desktop notifications.
- **Critical** notifications always get through (setting, default on).
- "Also silence Telegram": default off.
- Held notifications are recorded in Events as "held".

**Time estimates:**

- **Time to full** = (rated − stored) ÷ charging power.
- **Backup time left** = (stored − reserve) ÷ load.
- **Reserve** = `advanced.reserve_soc_pct` (default 12 %, matching the default DOD of 88 %).

### 6.8 Notifications (`notify/`)

- **Desktop:** `QSystemTrayIcon.showMessage` (a Windows toast). Clicking it opens the status window on the related tab.
- **Telegram** (Bot API over HTTPS, stdlib `urllib`):
  - **Sending:** `sendMessage` to `chat_id`. Non-blocking queue; 3 retries with backoff (5 s, 30 s, 120 s). HTTP 429
    honours `retry_after`. HTTP 401 marks the token invalid in Settings. The final failure is logged in Events.
  - **Listening:** `getUpdates` long polling (timeout 50 s) runs only when "Answer /marstek" is enabled. Only
    messages whose `from.id == user_id` are answered; others are ignored and logged. `setMyCommands` registers
    `/marstek`.
  - **`/marstek` reply:** SOC, stored kWh, power and direction, grid state, time to full/left, last update time.
  - **Detect chat ID:** calls `getUpdates` once and takes the chat id of the latest message.
  - **Monitor started / stopped:** sent on startup and on a clean exit (best-effort during Windows shutdown).

### 6.9 Settings (`settings.py`)

`%APPDATA%\MarstekMonitor\settings.json`, versioned schema. Unknown keys are preserved and invalid values
replaced with defaults. `notifications` holds one entry per rule in §6.7, keyed by rule id, with the fields listed
there. The example below shows only the SOC rules.

```json
{
  "schema": 1,
  "device": {"ble_mac": "0123456789ab", "ip": "192.168.1.20", "port": 30000},
  "general": {"language": "en", "autostart": false, "poll_seconds": 60, "offline_after_polls": 3},
  "appearance": {"font_scale": 1.0, "theme": "system"},
  "quiet_hours": {"enabled": false, "from": "23:00", "to": "07:00",
                  "critical_bypass": true, "silence_telegram": false},
  "notifications": {
    "soc_below": [{"enabled": true, "pct": 40, "priority": "normal", "desktop": true, "telegram": false, "repeat_min": 0},
                  {"enabled": true, "pct": 20, "priority": "critical", "desktop": true, "telegram": true, "repeat_min": 30}],
    "soc_reached": {"enabled": true, "pct": 100, "desktop": true, "telegram": false, "repeat_min": 0}
  },
  "telegram": {"enabled": false, "bot_token": "", "chat_id": "", "user_id": "", "answer_command": true},
  "advanced": {"power_sign": "plus_is_charging", "counter_unit": "Wh", "rearm_pct": 2, "rearm_c": 2,
               "reserve_soc_pct": 12, "samples_retention_days": 30, "log_level": "INFO",
               "record_raw": false}
}
```

### 6.10 i18n

JSON string tables `en` and `uk`, selected in Settings. They apply after pressing Save; no restart needed.

## 7. UI

The mockups were reviewed in the brainstorming companion and live under `.superpowers/brainstorm/` (not committed).

### 7.1 Tray icon (option **B**, chosen)

- A rounded **tile with the SOC number**, colored by state:
  - green `#2ea043`: charging
  - orange `#f0883e`: discharging
  - grey `#8b949e`: idle
- **Offline:** grey tile with a white ✕. **Unknown SOC:** `--`.
- "100" uses a smaller font to fit 16 px. Rendered with `QPainter` for 16/24/32 px (DPI-aware).
- **Tooltip** (≤127 characters) always starts with the name, e.g.
  `Marstek Venus E · 87% · ↓ Charging 1450 W · Grid OK · 14:32`
- **Left click:** open or focus the status window.
- **Right-click menu:** Open monitor · Settings · Exit.

### 7.2 Status window

- **Title:** "Marstek Venus E — Monitor"
- **Tab row:** Now · Energy · Live · Sessions · Events
- **The operating mode is not shown anywhere** (see §4, V4).

**Now:**

- **Problem banners** at the top, shown **only when something is wrong**:
  - red: backup at risk (discharging blocked, offline, temperature critical)
  - orange: grid outage / needs attention
- **Grid line:** "● Grid connected" / "⚡ outage since …" / "unknown" (until V3).
- **Hero:** big SOC %, state + power (e.g. "↓ Charging · 1 450 W"), stored/rated kWh, time to full **or**
  (during an outage) **"≈ time left at this load"** in the second-largest text, and a progress bar.
- **Current session card**, e.g. "Charging since 13:10 · 41% → 87% · 1 h 22 min · 2.3 kWh".
- **Collapsed "Device details":** charge/discharge allowed, temperature, Wi-Fi RSSI, firmware.
- **Footer:** model · IP · "Updated hh:mm:ss (n s ago)".

**Energy:** lifetime cards, then a charged vs discharged bar chart with Day / Month / Year and ◀ ▶ navigation.
Gap bars are hatched and labelled with the day range. Hovering a bar shows exact values.

**Live:** SOC line (left axis) over a charging/supplying power area (right axis) for 1 h / 3 h / 6 h / since start.
Only the current app run is shown. Gaps appear as "no data" and outages as a dashed marker. Hovering shows the values.

**Sessions:**

- Two summary cards: typical full charge, longest backup.
- Filters: All / Charging / Discharging / Outages only, plus a period (7 / 30 / 90 days / all).
- Cards grouped by day, newest first. Each card shows direction · cause · quality badge, the time range,
  SOC from → to, duration, energy, and average power.
- Partial sessions show ≤/≥ values and a ⚠ badge.

**Events:** a list grouped by day with time, icon, title, details, a critical badge, and per-channel delivery
status (🖥 / ✈ with ✓, ⟳ retried, 🌙 held, ✕ failed). Filters: All / Critical / Notifications / System, plus search.

### 7.3 Settings window

Sidebar: **General · Notifications · Telegram · Appearance · Advanced**. Buttons: Save / Cancel.

- **Notifications:** the quiet-hours bar, then one row per rule: on/off, threshold, 🖥, ✈, repeat, **Test**.
  Grouped as Battery level / Grid & backup / Sessions / Problems / System. "+ add level" allows up to 3 SOC-low levels.
- **Telegram:** enabled, bot token (masked with a reveal toggle), chat ID + **Detect**, user ID,
  "Answer /marstek (only to your user ID)", **Send test message** + last delivery status.
- **General:** language, start with Windows, battery IP:port + **Rediscover**, poll interval (min 60 s with a warning).
- **Appearance:** font size slider 100–200 % with a **live preview**, theme (Follow Windows / Light / Dark).
- **Advanced** (collapsed): power sign, counter unit, re-arm margins, reserve SOC, samples retention, log level,
  record raw data, open data folder.

### 7.4 Theme & scaling

- Qt Fusion style with a custom palette. Light and dark follow Windows (`QStyleHints.colorScheme`) unless overridden.
- One application font size multiplied by `font_scale`. All layouts use relative sizes; charts inherit the font and palette.

## 8. Error handling

| Situation | Behavior |
|---|---|
| Query timeout / partial failure | 1 retry; the snapshot keeps the successful fields; failed methods are logged |
| 3 fully failed cycles | offline state, notification, rediscovery by `ble_mac` each cycle |
| PC sleep / resume | recorded as a gap, no offline alarm |
| UDP port already bound | error state in tooltip, Events and Settings ("port 30000 is used by another program") |
| Second app instance | refused via a named mutex; the existing instance's window is focused |
| No discovery replies | hint: Windows Firewall may block inbound UDP for MarstekMonitor.exe |
| Implausible values / counter reset | see §6.2 sanity rules |
| Telegram failures | retries/backoff, 429 honoured, 401 flagged in Settings, final failure in Events |
| Messages from other Telegram users | ignored, logged |
| Corrupt `settings.json` | renamed to `settings.broken-<ts>.json`, defaults loaded, notification shown |
| DB error | continue without history, notice in UI, logged |
| Unhandled exception | logged via `sys.excepthook` / Qt message handler; tray shows error state; app keeps running |
| Logging | rotating file `%APPDATA%\MarstekMonitor\logs\app.log` (5 × 1 MB) |

## 9. Testing

1. **Unit tests (pytest):**
   - normalization (units, sign, sanity)
   - sessions (complete / started before app / gap / ended while off / cause classification)
   - energy (period deltas, gap-combined bars, counter reset)
   - rules (crossing, re-arm, repeat, quiet hours, critical bypass, per-channel flags)
   - settings (defaults, validation, unknown keys, broken file)
   - Telegram (message formatting, user-ID filter, retry/backoff and 429 handling against a fake HTTP server)
2. **Fake battery:** a local UDP server that replays `tests/fixtures/probe-2026-10-01.json` and can simulate timeouts,
   garbage, wrong IDs and JSON-RPC errors. It is used by client and poller tests.
3. **Read-only guard:**
   - a test asserts that every non-allowlisted method raises before sending
   - a test parses every source file (Python `ast`) and fails if any string literal shaped like an API method name
     (`^[A-Z][A-Za-z]*\.[A-Z][A-Za-z]*$`, e.g. `ES.SetMode`) is not in the allowlist
4. **UI smoke tests (pytest-qt):** windows open, tabs render with fixture data, font scale and theme switching apply.
5. **Manual real-device checklist:** V1–V5 from §4, using "Record raw data".

## 10. Packaging & runtime

- **PyInstaller, one-folder** build → `dist/MarstekMonitor/MarstekMonitor.exe`.
  - Version resource: ProductName and FileDescription "Marstek Monitor", plus a version number.
  - An app icon (static green tile with "M").
  - Task Manager then shows **"Marstek Monitor"** with its own icon.
- About 100 MB on disk because of Qt.
- **Autostart:** an HKCU `Run` value `MarstekMonitor` pointing to the exe. It is only written when the setting is enabled
  and removed when disabled.
- **Data folder:** `%APPDATA%\MarstekMonitor\` (settings.json, history.db, logs\).
- **Development:** `.venv` in the repo, `python -m marstek_monitor`.

**Dependencies:**

- runtime: `PySide6`
- dev: `pytest`, `pytest-qt`, `pyinstaller`
- HTTP: stdlib `urllib` (no extra dependency)

## 11. Future work (separate projects)

- Custom Android app plus an always-on home collector (Raspberry Pi / NAS) for complete history and wide statistics.
- Optional control features (charge power, mode) only after a verified, safe mechanism is found.
- Modbus TCP as a richer or more stable data source (V3 hardware supports it).
