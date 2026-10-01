"""Telegram Bot API over HTTPS with stdlib urllib (spec §6.8).

TelegramService runs a sender thread (queue, retries with backoff, 429 retry_after,
401 = invalid token) and, when enabled, a listener thread answering /marstek only to
the owner's user ID. Both threads are daemons; stop() never blocks on a long poll.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from ..i18n import tr

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, status: int | None, description: str = "", retry_after: float | None = None):
        super().__init__(f"{status}: {description}")
        self.status = status
        self.description = description
        self.retry_after = retry_after


class TelegramApi:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org", timeout: float = 15.0):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, payload: dict, timeout: float | None = None) -> Any:
        request = urllib.request.Request(
            f"{self.base_url}/bot{self.token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except ValueError:
                body = {}
            params = body.get("parameters") or {}
            raise TelegramError(exc.code, body.get("description", ""), params.get("retry_after")) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise TelegramError(None, str(exc)) from exc
        if not body.get("ok"):
            raise TelegramError(body.get("error_code"), body.get("description", ""))
        return body.get("result")

    def send_message(self, chat_id, text: str, silent: bool = False, html: bool = False) -> None:
        payload: dict = {"chat_id": chat_id, "text": text}
        if html:
            payload["parse_mode"] = "HTML"
        if silent:
            payload["disable_notification"] = True  # arrives without a sound on the phone
        self._call("sendMessage", payload)

    def get_updates(self, offset: int | None, timeout_s: int) -> list[dict]:
        payload: dict = {"timeout": timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload, timeout=timeout_s + 10) or []

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        self._call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})


def detect_ids(api: TelegramApi) -> tuple[str, str] | None:
    """(chat ID, sender's user ID) of the latest message sent to the bot (Settings → Detect)."""
    for update in reversed(api.get_updates(None, 0)):
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if "id" in chat:
            sender = (message.get("from") or {}).get("id", chat["id"])
            return str(chat["id"]), str(sender)
    return None


class TelegramService:
    BACKOFF = (5.0, 30.0, 120.0)

    def __init__(self, api: TelegramApi, chat_id: str, user_id: str, answer_command: bool,
                 status_provider: Callable[[], str],
                 on_delivery: Callable[[int | None, str], None],
                 on_problem: Callable[[str, dict], None],
                 on_command: Callable[[], None] = lambda: None,
                 backoff: tuple[float, ...] = BACKOFF, poll_timeout_s: int = 50):
        self.api = api
        self.chat_id = chat_id
        self.user_id = user_id
        self.status_provider = status_provider
        self.on_delivery = on_delivery
        self.on_problem = on_problem
        self.on_command = on_command
        self.backoff = backoff
        self.poll_timeout_s = poll_timeout_s
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._sender = threading.Thread(target=self._send_loop, name="telegram-send", daemon=True)
        self._listener = None
        if answer_command and user_id:
            self._listener = threading.Thread(target=self._listen_loop, name="telegram-listen", daemon=True)

    def start(self) -> None:
        self._sender.start()
        if self._listener is not None:
            self._listener.start()

    def send(self, text: str, event_id: int | None = None, silent: bool = False, html: bool = False) -> None:
        self._queue.put((text, event_id, silent, html))

    def flush(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return self._queue.unfinished_tasks == 0

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self._sender.join(timeout)

    # -- sender ------------------------------------------------------------

    def _send_loop(self) -> None:
        while not self._stop.is_set():
            try:
                text, event_id, silent, html = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._deliver(text, event_id, silent, html)
            finally:
                self._queue.task_done()

    def _deliver(self, text: str, event_id: int | None, silent: bool = False, html: bool = False) -> None:
        attempts = 0
        while True:
            try:
                self.api.send_message(self.chat_id, text, silent=silent, html=html)
                self.on_delivery(event_id, "sent")
                return
            except TelegramError as exc:
                if exc.status == 401:
                    self.on_problem("sys.telegram_invalid_token", {})
                    self.on_delivery(event_id, "failed")
                    return
                if attempts >= len(self.backoff):
                    log.warning("Telegram message failed after %d attempts: %s", attempts + 1, exc)
                    self.on_delivery(event_id, "failed")
                    return
                if exc.status == 429 and exc.retry_after is not None:
                    delay = float(exc.retry_after)
                else:
                    delay = self.backoff[attempts]
                attempts += 1
                self.on_delivery(event_id, "retrying")
                if self._stop.wait(delay):
                    self.on_delivery(event_id, "failed")
                    return

    # -- listener ----------------------------------------------------------

    def _listen_loop(self) -> None:
        try:
            self.api.set_my_commands([("marstek", tr("tg.command_desc"))])
        except TelegramError as exc:
            log.warning("setMyCommands failed: %s", exc)
        offset: int | None = None
        while not self._stop.is_set():
            try:
                updates = self.api.get_updates(offset, self.poll_timeout_s)
            except TelegramError as exc:
                if exc.status == 401:
                    self.on_problem("sys.telegram_invalid_token", {})
                    return  # retrying cannot help; Settings shows the problem
                if self._stop.wait(5):
                    return
                continue
            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                self._handle_update(update)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        if not (text == "/marstek" or text.startswith(("/marstek@", "/marstek "))):
            return
        sender = (message.get("from") or {}).get("id")
        if str(sender) != str(self.user_id):
            self.on_problem("sys.telegram_ignored", {"user": sender})
            return
        chat = (message.get("chat") or {}).get("id", self.chat_id)
        try:
            self.api.send_message(chat, self.status_provider())
            self.on_command()
        except TelegramError as exc:
            log.warning("Could not answer /marstek: %s", exc)
