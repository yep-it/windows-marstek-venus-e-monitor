"""Renders the documentation screenshots into docs/images/<lang>/.

Uses a copy of your real history (%APPDATA%\\MarstekMonitor\\history.db) so the pictures show real
data, but never talks to the battery and never touches your settings or history:
  * the database is copied with SQLite's backup API (the original is only read),
  * the battery's IP address is replaced with 192.168.1.10, Telegram IDs with 987654321
    and the bot token with a dummy (it is shown masked anyway),
  * the script stops if any of the original values is still found in the copy.

    .venv/Scripts/python tools/make_screenshots.py [--outage-start HH:MM]

--outage-start: the time the current grid outage began. The app does not keep the outage
state across restarts, so the script replays the readings since then to show the outage
as an app that ran all the time would.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_HOME = Path(os.environ["APPDATA"]) / "MarstekMonitor"
WORK = Path(tempfile.mkdtemp(prefix="marstek-shots-"))
os.environ["MARSTEK_MONITOR_HOME"] = str(WORK)  # window_state and logs go to the temp folder
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from marstek_monitor import i18n, settings as settings_mod  # noqa: E402
from marstek_monitor.api.client import DeviceInfo  # noqa: E402
from marstek_monitor.core.estimates import DrainTracker, minutes_left, minutes_to_full  # noqa: E402
from marstek_monitor.core.monitor import Monitor  # noqa: E402
from marstek_monitor.core.outage import OutageDetector  # noqa: E402
from marstek_monitor.core.storage import Storage  # noqa: E402
from marstek_monitor.ui import theme  # noqa: E402
from marstek_monitor.ui.settings_window import SettingsWindow  # noqa: E402
from marstek_monitor.ui.status_window import StatusWindow  # noqa: E402
from marstek_monitor.ui.tray import make_icon, render_battery  # noqa: E402

DEMO_IP = "192.168.1.10"
DEMO_ID = "987654321"
DEMO_TOKEN = "1234567890:AAEXAMPLEexampleEXAMPLEexampleEXAMP"


def copy_history(dst: Path) -> None:
    src = sqlite3.connect(f"file:{REAL_HOME / 'history.db'}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    src.backup(out)
    src.close()
    out.close()


def private_values(real: dict) -> list[str]:
    values = [real["device"]["ip"], real["device"]["ble_mac"], real["telegram"]["bot_token"],
              real["telegram"]["chat_id"], real["telegram"]["user_id"]]
    return [v for v in values if v and len(v) >= 5]


def sanitize_db(path: Path, real_ip: str) -> None:
    db = sqlite3.connect(path)
    ip_re = re.compile(re.escape(real_ip)) if real_ip else None
    rows = db.execute("select id, data from samples").fetchall()
    for row_id, data in rows:
        d = json.loads(data)
        if d.get("ip"):
            d["ip"] = DEMO_IP
        db.execute("update samples set data=? where id=?", (json.dumps(d), row_id))
    for row_id, params in db.execute("select id, params from events").fetchall():
        p = json.loads(params or "{}")
        for key in ("user", "chat", "chat_id", "user_id", "ip"):
            if key in p:
                p[key] = DEMO_IP if key == "ip" else DEMO_ID
        text = json.dumps(p)
        if ip_re:
            text = ip_re.sub(DEMO_IP, text)
        db.execute("update events set params=? where id=?", (text, row_id))
    db.commit()
    db.execute("vacuum")
    db.close()


def check_clean(path: Path, secrets: list[str]) -> None:
    blob = path.read_bytes()
    for value in secrets:
        if value.encode() in blob or value.lower().encode() in blob:
            raise SystemExit(f"a private value is still in {path.name}; nothing was rendered")


def demo_settings(real: dict, lang: str) -> dict:
    s = json.loads(json.dumps(real))
    s["device"].update(ip=DEMO_IP, ble_mac="")
    s["telegram"].update(bot_token=DEMO_TOKEN if s["telegram"]["bot_token"] else "",
                         chat_id=DEMO_ID if s["telegram"]["chat_id"] else "",
                         user_id=DEMO_ID if s["telegram"]["user_id"] else "")
    s["general"]["language"] = lang
    return s


def build_monitor(s: dict, db: Path, outage_start: float | None) -> Monitor:
    monitor = Monitor(s, Storage(db))
    samples = [x for x in monitor.samples_since(time.time() - 24 * 3600) if x.responded]
    if not samples:
        raise SystemExit("no readings in the last 24 hours")
    first_today = samples[0].ts
    replay_from = outage_start if outage_start is not None else samples[-1].ts - DrainTracker.WINDOW_S
    outage, drain = OutageDetector(s["advanced"]["outage_detection"]), DrainTracker()
    for x in samples:
        if x.ts >= replay_from:
            if outage.update(x) == "lost":
                monitor.outage_marks.append(x.ts)
            drain.add(x)
    monitor.outage, monitor.drain = outage, drain
    last = samples[-1]
    state = monitor.state
    state.snapshot, state.online, state.last_update_ts = last, True, last.ts
    state.device = DeviceInfo(device="VenusE 3.0", ver=last.fw_version, ble_mac="", wifi_mac="", ip=DEMO_IP)
    state.grid_state, state.grid_since = outage.state, outage.since
    efficiency = drain.efficiency() or s["advanced"]["inverter_efficiency_pct"] / 100
    state.minutes_left = minutes_left(last, s["advanced"]["reserve_soc_pct"], efficiency)
    state.minutes_to_full = minutes_to_full(last)
    state.counters_verified = s["advanced"]["counters_verified"]
    monitor.app_start_ts = first_today
    return monitor


def save(widget, path: Path, app: QApplication) -> None:
    for _ in range(5):  # a plain processEvents() leaves deleteLater() widgets painted over the new ones
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        time.sleep(0.05)
    widget.grab().save(str(path))
    print("  ", path.relative_to(ROOT))


def render_tray_icons(out: Path) -> None:
    for name, kind, level in (("tray-normal", "normal", 80), ("tray-charging", "charging", 60),
                              ("tray-outage", "outage", 85), ("tray-low", "normal", 15),
                              ("tray-offline", "offline", None), ("tray-error", "error", None)):
        render_battery(kind, level, 64).save(str(out / f"{name}.png"))
    print("   tray icons ->", out.relative_to(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outage-start", help="HH:MM today")
    args = parser.parse_args()
    outage_start = None
    if args.outage_start:
        h, m = map(int, args.outage_start.split(":"))
        outage_start = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp()

    real, _ = settings_mod.load(REAL_HOME / "settings.json")
    secrets = private_values(real)
    db = WORK / "history.db"
    copy_history(db)
    sanitize_db(db, real["device"]["ip"])
    check_clean(db, secrets)

    app = QApplication(sys.argv[:1])
    images = ROOT / "docs" / "images"
    render_tray_icons(images)
    for lang in ("en", "uk"):
        out = images / lang
        out.mkdir(parents=True, exist_ok=True)
        s = demo_settings(real, lang)
        if any(v in json.dumps(s) for v in secrets):
            raise SystemExit("a private value is still in the demo settings; nothing was rendered")
        i18n.set_language(lang)
        theme.apply(app, s["appearance"]["theme"], s["appearance"]["font_scale"])
        monitor = build_monitor(s, db, outage_start)
        icon = make_icon("M", theme.COLORS["charging"])

        status = StatusWindow(monitor, lambda s=s: s, icon=icon)
        status.resize(900, 720)
        status.show()
        for key in StatusWindow.TAB_KEYS:
            status.show_tab(key)
            save(status, out / f"status-{key}.png", app)
        status.hide()

        win = SettingsWindow(s, icon=icon, delete_on_close=False)
        win.show()
        pages = (("general", 380), ("notifications", 830), ("telegram", 470), ("appearance", 260), ("advanced", 520))
        for row, (name, height) in enumerate(pages):  # window height fitted to each page, without empty space
            win.side.setCurrentRow(row)
            win.resize(1150, height)
            save(win, out / f"settings-{name}.png", app)
        win.hide()
        monitor.close()
    print("done; temporary copy in", WORK)


if __name__ == "__main__":
    main()
