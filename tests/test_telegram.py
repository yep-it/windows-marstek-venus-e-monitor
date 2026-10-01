import time

import pytest

from marstek_monitor.notify.telegram import TelegramApi, TelegramService, detect_ids
from tests.fakes.fake_telegram import FakeTelegram

ERROR_500 = {"ok": False, "error_code": 500, "description": "Internal Server Error"}


@pytest.fixture
def fake():
    with FakeTelegram() as server:
        yield server


class Recorder:
    def __init__(self):
        self.deliveries, self.problems, self.commands = [], [], []


def make(base_url, answer=False, backoff=(0, 0, 0)):
    rec = Recorder()
    svc = TelegramService(
        TelegramApi("TOKEN", base_url=base_url), chat_id="100", user_id="42", answer_command=answer,
        status_provider=lambda: "STATUS",
        on_delivery=lambda eid, status: rec.deliveries.append((eid, status)),
        on_problem=lambda key, params: rec.problems.append((key, params)),
        on_command=lambda: rec.commands.append(1),
        backoff=backoff, poll_timeout_s=1,
    )
    svc.start()
    return svc, rec


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_send_message_success(fake):
    svc, rec = make(fake.url)
    svc.send("hello", 7)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(7, "sent")]
    assert fake.calls("sendMessage") == [{"chat_id": "100", "text": "hello"}]


def test_retries_then_succeeds(fake):
    fake.queue("sendMessage", 500, ERROR_500)
    fake.queue("sendMessage", 500, ERROR_500)
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying"), (1, "retrying"), (1, "sent")]


def test_429_retry_after_is_honoured(fake):
    fake.queue("sendMessage", 429, {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                    "parameters": {"retry_after": 0}})
    svc, rec = make(fake.url, backoff=(100, 100, 100))
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying"), (1, "sent")]


def test_401_marks_token_invalid(fake):
    fake.queue("sendMessage", 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "failed")]
    assert rec.problems == [("sys.telegram_invalid_token", {})]


def test_gives_up_after_three_retries(fake):
    for _ in range(4):
        fake.queue("sendMessage", 500, ERROR_500)
    svc, rec = make(fake.url)
    svc.send("x", 1)
    assert svc.flush(3)
    svc.stop()
    assert rec.deliveries == [(1, "retrying")] * 3 + [(1, "failed")]
    assert len(fake.calls("sendMessage")) == 4


def test_unreachable_server_fails_without_blocking():
    svc, rec = make("http://127.0.0.1:9")
    started = time.monotonic()
    svc.send("x", 1)
    assert time.monotonic() - started < 0.1
    assert svc.flush(20)  # Windows needs ~2 s per refused localhost connect
    svc.stop()
    assert rec.deliveries[-1] == (1, "failed")


def test_cyrillic_text_is_sent_as_utf8(fake):
    svc, _ = make(fake.url)
    svc.send("Заряд батареї нижче 40%", 1)
    assert svc.flush(3)
    svc.stop()
    assert fake.calls("sendMessage")[0]["text"] == "Заряд батареї нижче 40%"


def test_marstek_command_only_from_owner(fake):
    fake.updates = [
        {"update_id": 1, "message": {"text": "/marstek", "from": {"id": 42}, "chat": {"id": 100}}},
        {"update_id": 2, "message": {"text": "/marstek", "from": {"id": 7}, "chat": {"id": 555}}},
        {"update_id": 3, "message": {"text": "hello", "from": {"id": 42}, "chat": {"id": 100}}},
    ]
    svc, rec = make(fake.url, answer=True)
    assert wait_for(lambda: len(fake.calls("sendMessage")) >= 1 and rec.problems)
    svc.stop()
    assert fake.calls("sendMessage") == [{"chat_id": 100, "text": "STATUS"}]
    assert rec.problems == [("sys.telegram_ignored", {"user": 7})]
    assert rec.commands == [1]
    assert fake.calls("setMyCommands")[0]["commands"][0]["command"] == "marstek"


def test_detect_ids_returns_chat_and_user(fake):
    api = TelegramApi("TOKEN", base_url=fake.url)
    assert detect_ids(api) is None
    fake.updates = [{"update_id": 5, "message": {"chat": {"id": 111}, "from": {"id": 7}}},
                    {"update_id": 6, "message": {"chat": {"id": 222}, "from": {"id": 42}}}]
    assert detect_ids(api) == ("222", "42")


def test_invalid_token_stops_the_listener_after_one_report(fake):
    for _ in range(5):
        fake.queue("getUpdates", 401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
    svc, rec = make(fake.url, answer=True)
    assert wait_for(lambda: rec.problems)
    assert wait_for(lambda: not svc._listener.is_alive(), timeout=2)
    svc.stop()
    assert rec.problems == [("sys.telegram_invalid_token", {})]


def test_silent_and_html_options_reach_the_api(fake):
    svc, _ = make(fake.url)
    svc.send("<b>CRITICAL</b>", 1, silent=False, html=True)
    svc.send("normal", 2, silent=True)
    assert svc.flush(3)
    svc.stop()
    first, second = fake.calls("sendMessage")
    assert first == {"chat_id": "100", "text": "<b>CRITICAL</b>", "parse_mode": "HTML"}
    assert second == {"chat_id": "100", "text": "normal", "disable_notification": True}
