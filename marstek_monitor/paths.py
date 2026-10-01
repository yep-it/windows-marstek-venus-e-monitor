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
