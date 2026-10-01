"""A local UDP server that behaves like a Marstek battery's Local API (tests only)."""
import json
import socket
import threading
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / "fixtures" / "probe-2026-10-01.json"
SRC = "VenusE 3.0-0123456789ab"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeBattery:
    """Replies to JSON-RPC requests with fixture results.

    Per-method behaviour via `mode[method]`: "ok" (default), "timeout" (no reply),
    "garbage" (non-JSON), "wrong_id" (reply with another id), "error" (JSON-RPC error).
    Edit `results[method]` to change returned values.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.results = {m: r["result"] for m, r in load_fixture().items()}
        self.mode: dict[str, str] = {}
        self.received: list[dict] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(0.2)
        self.host, self.port = self.sock.getsockname()
        # Like the real device, report our own address in GetDevice.
        self.results["Marstek.GetDevice"] = dict(self.results["Marstek.GetDevice"], ip=self.host)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> "FakeBattery":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self.sock.close()

    def __enter__(self) -> "FakeBattery":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def methods_received(self) -> list[str]:
        return [r.get("method") for r in self.received]

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                req = json.loads(data)
            except ValueError:
                continue
            self.received.append(req)
            method = req.get("method")
            mode = self.mode.get(method, "ok")
            if mode == "timeout":
                continue
            if mode == "garbage":
                self.sock.sendto(b"\x00not json", addr)
                continue
            rid = req.get("id")
            if method not in self.results:
                reply = {"id": rid, "src": SRC, "error": {"code": -32601, "message": "Method not found"}}
            elif mode == "error":
                reply = {"id": rid, "src": SRC, "error": {"code": -32603, "message": "Internal error"}}
            else:
                if mode == "wrong_id":
                    rid = (rid or 0) + 1000
                reply = {"id": rid, "src": SRC, "result": self.results[method]}
            self.sock.sendto(json.dumps(reply).encode(), addr)
