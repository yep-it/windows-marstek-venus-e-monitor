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
