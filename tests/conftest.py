import pytest


@pytest.fixture(autouse=True)
def app_home(tmp_path, monkeypatch):
    """Every test gets its own data folder, so nothing touches the real %APPDATA%\MarstekMonitor."""
    home = tmp_path / "home"
    monkeypatch.setenv("MARSTEK_MONITOR_HOME", str(home))
    return home
