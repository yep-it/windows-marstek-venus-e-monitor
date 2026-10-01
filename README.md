# Marstek Monitor

Read-only Windows tray monitor for a **Marstek Venus E 3.0** battery, using its Local API
(JSON over UDP on the home network). It shows the charge level in the tray, has a status
window (Now · Energy · Live · Sessions · Events), and sends desktop and Telegram notifications.

**It never changes any battery setting.** Only these read commands are ever sent:
`Marstek.GetDevice`, `Wifi.GetStatus`, `Bat.GetStatus`, `ES.GetStatus`, `EM.GetStatus`.

## Download

Get `MarstekMonitor-<version>-win64.zip` from the
[Releases](https://github.com/yep-it/windows-marstek-venus-e-monitor/releases) page, unzip it and
run `MarstekMonitor.exe`. The release notes explain the first start.

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

## Releasing a new version

1. Change `__version__` in `marstek_monitor/__init__.py`. This is the only place the version is
   written; the exe's file properties and the package take it from there.
2. Optionally describe the changes in `docs/releases/v<version>.md`.
3. Commit, then tag and push:
   ```bash
   git tag v0.2.0
   git push origin main v0.2.0
   ```
   GitHub Actions (`.github/workflows/release.yml`) runs the tests, builds the exe and publishes
   the release with the zip. The tag has to match `__version__`, otherwise nothing is published.

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
