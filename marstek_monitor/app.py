"""Qt glue (spec §5, §10.1): poller thread → monitor pipeline → tray, windows and notifiers."""
from __future__ import annotations

import copy
import json
import logging
import os
import sqlite3
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import i18n, paths, settings as settings_mod
from .core.events import Event
from .core.monitor import Monitor
from .core.poller import Poller, PollerConfig, PollResult
from .core.poller_thread import PollerThread
from .core.snapshot import NormalizeConfig
from .core.storage import Storage
from .logging_setup import RawRecorder, setup_logging
from .notify.desktop import DesktopNotifier
from .notify.telegram import TelegramApi, TelegramError, TelegramService, detect_ids
from .platform import autostart, shortcut
from .present import render_event, telegram_status
from .ui import theme
from .ui.settings_window import SettingsWindow
from .ui.status_window import StatusWindow
from .ui.tray import Tray, make_icon

log = logging.getLogger(__name__)
EXIT_HARD_LIMIT_S = 5.0
PURGE_INTERVAL_MS = 3_600_000


def poller_config(s: dict) -> PollerConfig:
    return PollerConfig(
        ip=s["device"]["ip"], port=s["device"]["port"], ble_mac=s["device"]["ble_mac"],
        local_port=s["device"]["local_port"], poll_seconds=s["general"]["poll_seconds"],
        offline_after_polls=s["general"]["offline_after_polls"],
        normalize=NormalizeConfig(s["advanced"]["power_sign"], s["advanced"]["counter_unit"]),
    )


def poller_key(s: dict) -> str:
    return json.dumps([s["device"], s["general"]["poll_seconds"], s["general"]["offline_after_polls"],
                       s["advanced"]["power_sign"], s["advanced"]["counter_unit"], s["advanced"]["record_raw"]],
                      sort_keys=True)


def telegram_config_problem(tg: dict) -> str | None:
    if tg["enabled"] and (not tg["bot_token"] or not tg["chat_id"]):
        return "settings.tg_missing"
    return None


def telegram_notice(settings: dict) -> str:
    tg = settings["telegram"]
    problem = telegram_config_problem(tg)
    if problem:
        return i18n.tr(problem)
    if tg["enabled"] and tg["answer_command"] and not tg["user_id"]:
        return i18n.tr("settings.tg_user_missing")
    return ""


def keep_live_device(new: dict, original: dict, live: dict) -> None:
    """Keep an IP/MAC rediscovered while Settings was open, unless the user edited it."""
    for key in ("ip", "ble_mac"):
        if new["device"][key] == original["device"][key]:
            new["device"][key] = live["device"][key]


def apply_device_change(settings: dict, ip: str | None, ble_mac: str | None) -> bool:
    device = settings["device"]
    changed = False
    if ip and ip != device["ip"]:
        device["ip"] = ip
        changed = True
    if ble_mac and ble_mac != device["ble_mac"]:
        device["ble_mac"] = ble_mac
        changed = True
    return changed


def tab_for(e: Event) -> str:
    if e.rule_id in ("charge_session", "discharge_session"):
        return "sessions"
    return "events" if e.kind == "system" else "now"


class Bridge(QObject):
    """Carries callbacks from worker threads to the Qt main thread."""

    delivery = Signal(object, str)
    problem = Signal(str, object)
    command = Signal()
    settings_status = Signal(str)
    chat_detected = Signal(str, str)


class App(QObject):
    def __init__(self, qapp, instance, exit_after: float | None = None):
        super().__init__()
        self.qapp = qapp
        self.instance = instance
        self._exiting = False
        self.settings, warning = settings_mod.load(paths.settings_path())
        setup_logging(self.settings["advanced"]["log_level"])
        log.info("Marstek Monitor starting")
        i18n.set_language(self.settings["general"]["language"])
        theme.apply(qapp, self.settings["appearance"]["theme"], self.settings["appearance"]["font_scale"])

        storage = None
        try:
            storage = Storage(paths.db_path())
        except sqlite3.Error:
            log.exception("Cannot open the history database")
        self.monitor = Monitor(self.settings, storage)
        if storage is None:
            self.monitor.state.history_ok = False

        self.bridge = Bridge()
        self.bridge.delivery.connect(self._on_delivery)
        self.bridge.problem.connect(self._on_problem)
        self.bridge.command.connect(lambda: self.monitor.system_event("sys.telegram_command"))
        self.bridge.settings_status.connect(self._on_settings_status)
        self.bridge.chat_detected.connect(self._on_chat_detected)

        self.app_icon = make_icon("M", theme.COLORS["charging"])
        self.tray = Tray()
        self.tray.open_requested.connect(lambda: self.open_status("now"))
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.exit_requested.connect(self.exit)
        self.tray.show()
        self.desktop = DesktopNotifier(self.tray.icon, self.open_status)
        self.status = self._make_status_window()
        self.settings_win: SettingsWindow | None = None
        self.instance.activated.connect(lambda: self.open_status(self.status.current_tab()))

        self._status_text = telegram_status(self.monitor.state, time.time())
        self.telegram: TelegramService | None = None
        self._start_telegram()
        self.poller_thread: PollerThread | None = None
        self._start_poller()

        if warning:
            self.dispatch([self.monitor.system_event(warning, desktop=True)])
        started = self.monitor.rules.monitor_event(time.time(), started=True)
        if started is not None:
            self.dispatch(self.monitor.emit([started], bypass_quiet=True))
        self._sync_platform()
        self.monitor.purge()
        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self.monitor.purge)
        self._purge_timer.start(PURGE_INTERVAL_MS)
        self.tray.update_state(self.monitor.state, time.time())
        if exit_after is not None:
            QTimer.singleShot(int(exit_after * 1000), self.exit)

    # -- components ----------------------------------------------------------

    def _make_status_window(self) -> StatusWindow:
        window = StatusWindow(self.monitor, lambda: self.settings, icon=self.app_icon)
        window.settings_requested.connect(self.open_settings)
        return window

    def _start_poller(self) -> None:
        recorder = RawRecorder() if self.settings["advanced"]["record_raw"] else None
        poller = Poller(poller_config(self.settings), raw_recorder=recorder)
        self.poller_thread = PollerThread(poller, self.settings["general"]["poll_seconds"])
        self.poller_thread.result.connect(self._on_result)
        self.poller_thread.start()

    def _stop_poller(self, wait_ms: int = 4000) -> None:
        if self.poller_thread is not None:
            self.poller_thread.stop()
            self.poller_thread.wait(wait_ms)
            self.poller_thread = None

    def _start_telegram(self) -> None:
        tg = self.settings["telegram"]
        problem = telegram_config_problem(tg)
        if not tg["enabled"] or problem:
            if problem:
                log.warning("Telegram is enabled but not configured (%s)", problem)
                self.monitor.system_event(problem)
            return
        self.telegram = TelegramService(
            TelegramApi(tg["bot_token"]), chat_id=tg["chat_id"], user_id=tg["user_id"],
            answer_command=tg["answer_command"], status_provider=lambda: self._status_text,
            on_delivery=self.bridge.delivery.emit, on_problem=self.bridge.problem.emit,
            on_command=self.bridge.command.emit,
        )
        self.telegram.start()

    def _stop_telegram(self, flush_s: float = 0.0) -> None:
        if self.telegram is not None:
            if flush_s:
                self.telegram.flush(flush_s)
            self.telegram.stop()
            self.telegram = None

    def _sync_platform(self) -> None:
        if os.environ.get("MARSTEK_MONITOR_NO_PLATFORM"):
            return
        general = self.settings["general"]
        try:
            autostart.set_enabled(general["autostart"])
        except OSError:
            log.exception("Updating autostart failed")
        try:
            shortcut.sync(general["start_menu_shortcut"])
        except (OSError, subprocess.SubprocessError):
            log.exception("Updating the Start menu shortcut failed")

    # -- data flow -------------------------------------------------------------

    def _on_result(self, r: PollResult) -> None:
        if self._exiting:
            return
        events = self.monitor.handle(r)
        poller = self.poller_thread.poller if self.poller_thread is not None else None
        if poller is not None and apply_device_change(self.settings, poller.ip, poller.ble_mac):
            settings_mod.save(paths.settings_path(), self.settings)
        now = time.time()
        self._status_text = telegram_status(self.monitor.state, now)
        self.tray.update_state(self.monitor.state, now)
        self.status.on_update()
        self.dispatch(events)

    def dispatch(self, events: list[Event]) -> None:
        for e in events:
            title, body = render_event(e)
            if e.desktop == "pending":
                shown = self.desktop.show(title, body, e.priority == "critical", tab_for(e))
                self.monitor.record_delivery(e.id, "desktop", "sent" if shown else "failed")
            if e.telegram == "pending":
                if self.telegram is not None:
                    self.telegram.send(f"{title}\n{body}".strip(), e.id)
                else:
                    self.monitor.record_delivery(e.id, "telegram", "failed")
        if events and self.status.isVisible():
            self.status.refresh()

    def _on_delivery(self, event_id, status: str) -> None:
        self.monitor.record_delivery(event_id, "telegram", status)

    def _on_problem(self, key: str, params) -> None:
        self.monitor.system_event(key, params or {})
        if key == "sys.telegram_invalid_token" and self.settings_win is not None:
            self.settings_win.set_telegram_status(i18n.tr(key))
        if self.status.isVisible():
            self.status.refresh()

    def show_unexpected_error(self) -> None:
        self.monitor.state.error_key = "sys.unexpected_error"
        self.monitor.state.error_params = {}
        self.tray.update_state(self.monitor.state, time.time())

    # -- windows ---------------------------------------------------------------

    def open_status(self, tab: str = "now") -> None:
        self.status.show_tab(tab)

    def open_settings(self) -> None:
        if self.settings_win is not None:
            self.settings_win.showNormal()
            self.settings_win.raise_()
            self.settings_win.activateWindow()
            return
        state = self.monitor.state
        notice = i18n.tr(state.error_key, **state.error_params) if state.error_key else ""
        self._settings_opened_with = copy.deepcopy(self.settings)
        win = SettingsWindow(self.settings, icon=self.app_icon, notice=notice)
        tg_notice = telegram_notice(self.settings)
        if tg_notice:
            win.set_telegram_status(tg_notice)
        win.saved.connect(self._on_settings_saved)
        win.rediscover.connect(self._rediscover)
        win.test_notification.connect(self._on_test_notification)
        win.detect_chat.connect(self._detect_chat)
        win.send_test.connect(self._send_telegram_test)
        win.destroyed.connect(self._on_settings_closed)
        self.settings_win = win
        win.show()

    def _on_settings_closed(self, *_args) -> None:
        self.settings_win = None

    def _on_settings_saved(self, new: dict) -> None:
        keep_live_device(new, self._settings_opened_with, self.settings)
        old = self.settings
        self.settings = new
        settings_mod.save(paths.settings_path(), new)
        setup_logging(new["advanced"]["log_level"])
        i18n.set_language(new["general"]["language"])
        theme.apply(self.qapp, new["appearance"]["theme"], new["appearance"]["font_scale"])
        self.monitor.apply_settings(new)
        if poller_key(old) != poller_key(new):
            self._stop_poller()
            self._start_poller()
        if old["telegram"] != new["telegram"]:
            self._stop_telegram()
            self._start_telegram()
        self._sync_platform()
        self.tray.retranslate()
        visible, tab = self.status.isVisible(), self.status.current_tab()
        self.status.hide()
        self.status.deleteLater()
        self.status = self._make_status_window()
        if visible:
            self.status.show_tab(tab)
        self.tray.update_state(self.monitor.state, time.time())

    def _rediscover(self) -> None:
        if self.poller_thread is not None:
            self.poller_thread.poller.request_discovery()
            self.poller_thread.wake()

    def _on_test_notification(self, _rule: str, cfg) -> None:
        e = self.monitor.rules.test_event(time.time(), desktop=bool(cfg.get("desktop")),
                                          telegram=bool(cfg.get("telegram")))
        self.dispatch(self.monitor.emit([e], bypass_quiet=True))

    def _detect_chat(self, token: str) -> None:
        if not token:
            self._on_settings_status(i18n.tr("settings.tg_missing"))
            return

        def work() -> None:
            try:
                ids = detect_ids(TelegramApi(token))
                self.bridge.chat_detected.emit(*(ids or ("", "")))
            except TelegramError as exc:
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_failed",
                                                         error=exc.description or exc.status))

        threading.Thread(target=work, name="telegram-detect", daemon=True).start()

    def _send_telegram_test(self, values: dict) -> None:
        if not values["bot_token"] or not values["chat_id"]:
            self._on_settings_status(i18n.tr("settings.tg_missing"))
            return
        text = f"{i18n.tr('n.test.title')}\n{i18n.tr('n.test.body')}"

        def work() -> None:
            try:
                TelegramApi(values["bot_token"]).send_message(values["chat_id"], text)
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_ok"))
            except TelegramError as exc:
                self.bridge.settings_status.emit(i18n.tr("settings.tg_status_failed",
                                                         error=exc.description or exc.status))

        threading.Thread(target=work, name="telegram-test", daemon=True).start()

    def _on_settings_status(self, text: str) -> None:
        if self.settings_win is not None:
            self.settings_win.set_telegram_status(text)

    def _on_chat_detected(self, chat_id: str, user_id: str) -> None:
        if self.settings_win is None:
            return
        if chat_id:
            self.settings_win.set_detected(chat_id, user_id)
            self.settings_win.set_telegram_status(i18n.tr("settings.tg_detected"))
        else:
            self.settings_win.set_telegram_status(i18n.tr("settings.tg_detect_none"))

    # -- exit ------------------------------------------------------------------

    def exit(self) -> None:
        """Stop everything (spec §10.1); a watchdog ends the process after 5 s regardless."""
        if self._exiting:
            return
        self._exiting = True
        log.info("Exiting")
        watchdog = threading.Timer(EXIT_HARD_LIMIT_S, lambda: os._exit(0))
        watchdog.daemon = True
        watchdog.start()
        self._stop_poller(wait_ms=3000)                      # 1. poller thread (also frees the UDP port)
        stopped = self.monitor.rules.monitor_event(time.time(), started=False)
        if stopped is not None and self.telegram is not None:  # 2. "Monitor stopped", max 3 s
            [event] = self.monitor.emit([stopped], bypass_quiet=True)
            title, body = render_event(event)
            self.telegram.send(f"{title}\n{body}", event.id)
            self._stop_telegram(flush_s=3.0)
        else:
            self._stop_telegram()                             # 3. long poll is a daemon thread
        if self.status.isVisible():
            self.status.remember_geometry()
        self.monitor.close()                                  # 4. database
        self.instance.release()                               # 5. single-instance mutex
        self.tray.hide()                                      # 6. tray icon
        if self.settings_win is not None:
            self.settings_win.close()
        self.qapp.quit()                                      # 7. end the event loop → process exits
