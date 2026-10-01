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
