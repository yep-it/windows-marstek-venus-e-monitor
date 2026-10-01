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
