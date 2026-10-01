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
