import pytest


@pytest.fixture
def app_home(tmp_path, monkeypatch):
    """Point the app's data folder at a temporary directory."""
    home = tmp_path / "home"
    monkeypatch.setenv("MARSTEK_MONITOR_HOME", str(home))
    return home
