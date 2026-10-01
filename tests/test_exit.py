"""Exit from the tray stops the whole process quickly and frees the UDP port (spec §10.1)."""
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

from marstek_monitor import settings as settings_mod
from tests.fakes.fake_battery import FakeBattery
from tests.fakes.net import free_udp_port

REPO = Path(__file__).parent.parent
EXIT_AFTER_S = 4


def test_exit_stops_process_and_frees_port(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    local_port = free_udp_port()
    with FakeBattery() as battery:
        cfg = settings_mod.defaults()
        cfg["device"].update(ip="127.0.0.1", port=battery.port, local_port=local_port)
        (home / "settings.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = dict(os.environ, MARSTEK_MONITOR_HOME=str(home), MARSTEK_MONITOR_INSTANCE=f"test-{uuid.uuid4().hex}",
                   MARSTEK_MONITOR_NO_PLATFORM="1", QT_QPA_PLATFORM="offscreen")
        started = time.monotonic()
        proc = subprocess.Popen([sys.executable, "-m", "marstek_monitor", "--exit-after", str(EXIT_AFTER_S)],
                                env=env, cwd=REPO)
        try:
            code = proc.wait(timeout=40)
        finally:
            if proc.poll() is None:
                proc.kill()
        elapsed = time.monotonic() - started
        assert code == 0
        assert elapsed < EXIT_AFTER_S + 6 + 10  # exit trigger + 6 s budget + generous startup margin
        assert "Bat.GetStatus" in battery.methods_received()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", local_port))  # raises if the app still held the port
    sock.close()
    assert "Marstek Monitor starting" in (home / "logs" / "app.log").read_text(encoding="utf-8")
