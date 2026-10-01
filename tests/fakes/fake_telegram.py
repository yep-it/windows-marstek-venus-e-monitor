"""Minimal Telegram Bot API server for tests: records requests, replies from a script."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeTelegram:
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.responses: dict[str, list[tuple[int, dict]]] = {}
        self.updates: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeTelegram":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "FakeTelegram":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def queue(self, method: str, status: int, body: dict) -> None:
        self.responses.setdefault(method, []).append((status, body))

    def calls(self, method: str) -> list[dict]:
        return [payload for m, payload in self.requests if m == method]

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                method = self.path.rsplit("/", 1)[-1]
                fake.requests.append((method, payload))
                queued = fake.responses.get(method)
                if queued:
                    status, body = queued.pop(0)
                elif method == "getUpdates":
                    offset = payload.get("offset") or 0
                    items = [u for u in fake.updates if u["update_id"] >= offset]
                    if not items:
                        time.sleep(min(payload.get("timeout", 0), 0.2))
                    status, body = 200, {"ok": True, "result": items}
                else:
                    status, body = 200, {"ok": True, "result": True}
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler
