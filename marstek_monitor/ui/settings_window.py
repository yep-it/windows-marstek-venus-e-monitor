"""Settings window: General · Notifications · Telegram · Appearance · Advanced (spec §7.3).

Works on a copy of the settings; Save emits the validated dict, Cancel discards.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QTime, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
    QScrollArea, QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTimeEdit, QToolButton, QVBoxLayout, QWidget,
)

from .. import paths
from ..i18n import tr
from ..settings import MAX_SOC_LEVELS, validate
from . import window_state
from .theme import base_point_size
from .widgets import clear_layout, label

REPEAT_CHOICES = (0, 15, 30, 60, 120)
NEW_LEVEL = {"enabled": True, "pct": 30, "priority": "normal", "desktop": True, "telegram": False, "repeat_min": 0}
GROUPS = (
    ("group.battery", ("soc_below", "soc_reached")),
    ("group.grid", ("grid", "backup_left")),
    ("group.sessions", ("charge_session", "discharge_session")),
    ("group.problems", ("offline", "blocked", "temperature")),
    ("group.system", ("firmware", "monitor")),
)
RULE_LABELS = {
    "soc_below": "rule.soc_below", "soc_reached": "rule.soc_reached", "grid": "rule.grid",
    "backup_left": "rule.backup_left", "charge_session": "rule.charge_session",
    "discharge_session": "rule.discharge_session", "offline": "rule.offline", "blocked": "rule.blocked",
    "temperature": "rule.temperature", "firmware": "rule.firmware", "monitor": "rule.monitor",
}
RULE_HELP = {
    "soc_below": "help.rule.soc_below", "soc_reached": "help.rule.soc_reached", "grid": "help.rule.grid",
    "backup_left": "help.rule.backup_left", "charge_session": "help.rule.charge_session",
    "discharge_session": "help.rule.discharge_session", "offline": "help.rule.offline", "blocked": "help.rule.blocked",
    "temperature": "help.rule.temperature", "firmware": "help.rule.firmware", "monitor": "help.rule.monitor",
}
EXPERIMENTAL = {"grid", "backup_left"}
CRITICAL_RULES = {"grid", "backup_left", "offline", "blocked", "temperature"}


def _spin(lo: int, hi: int, value: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setValue(int(value))
    box.setSuffix(suffix)
    return box


def _combo(options: list[tuple[str, object]], value: object) -> QComboBox:
    box = QComboBox()
    for text, data in options:
        box.addItem(text, data)
    box.setCurrentIndex(max(0, box.findData(value)))
    return box


def _repeat_combo(value: int) -> QComboBox:
    options = [(tr("settings.repeat_off") if m == 0 else tr("settings.repeat_min", n=m), m) for m in REPEAT_CHOICES]
    return _combo(options, value)


def _help(form: QFormLayout, field, key: str) -> None:
    """Hover explanation on a form row: its label and its field(s)."""
    tip = tr(key)
    row_label = form.labelForField(field)
    if row_label is not None:
        row_label.setToolTip(tip)
    if isinstance(field, QWidget):
        field.setToolTip(tip)
    else:
        for i in range(field.count()):
            widget = field.itemAt(i).widget()
            if widget is not None:
                widget.setToolTip(tip)


def _select(box: QComboBox, value: object) -> None:
    box.setCurrentIndex(max(0, box.findData(value)))


class _Row:
    """Widgets of one notification row."""

    def __init__(self, rule: str, cfg: dict, index: int | None = None):
        self.rule, self.index, self.cfg = rule, index, dict(cfg)
        self.enabled = QCheckBox()
        self.enabled.setChecked(cfg["enabled"])
        self.desktop = self._check(cfg, "desktop")
        self.telegram = self._check(cfg, "telegram")
        self.repeat = _repeat_combo(cfg["repeat_min"]) if "repeat_min" in cfg else None
        self.pct = self.priority = self.minutes = self.high = self.low = None
        if rule == "soc_below":
            self.pct = _spin(1, 99, cfg["pct"], " %")
            self.priority = _combo([(tr("priority.normal"), "normal"), (tr("priority.critical"), "critical")],
                                   cfg["priority"])
        elif rule == "soc_reached":
            self.pct = _spin(50, 100, cfg["pct"], " %")
        elif rule == "backup_left":
            self.minutes = _spin(5, 600, cfg["minutes"], " min")
        elif rule == "temperature":
            self.high = _spin(20, 80, cfg["high"], " °C")
            self.low = _spin(-20, 20, cfg["low"], " °C")
        self.test_button = QPushButton(tr("settings.test"))
        self.test_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.test_button.setToolTip(tr("help.test"))
        self.name_label: QLabel | None = None
        for widget, key in ((self.desktop, "help.col_desktop"), (self.telegram, "help.col_telegram"),
                            (self.repeat, "help.col_repeat"), (self.priority, "help.priority")):
            if widget is not None:
                widget.setToolTip(tr(key))

    @staticmethod
    def _check(cfg: dict, key: str) -> QCheckBox | None:
        if key not in cfg:
            return None
        box = QCheckBox()
        box.setChecked(cfg[key])
        return box

    def threshold_widget(self) -> QWidget | None:
        parts = [w for w in (self.pct, self.priority, self.minutes, self.high, self.low) if w is not None]
        if not parts:
            return None
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        for widget in parts:
            layout.addWidget(widget)
        return host

    def widgets(self) -> list[QWidget]:
        candidates = (self.enabled, self.desktop, self.telegram, self.repeat, self.pct, self.priority,
                      self.minutes, self.high, self.low, self.test_button)
        return [w for w in candidates if w is not None]

    def collect(self) -> dict:
        out = dict(self.cfg)
        out["enabled"] = self.enabled.isChecked()
        if self.desktop is not None:
            out["desktop"] = self.desktop.isChecked()
        if self.telegram is not None:
            out["telegram"] = self.telegram.isChecked()
        if self.repeat is not None:
            out["repeat_min"] = self.repeat.currentData()
        if self.pct is not None:
            out["pct"] = self.pct.value()
        if self.priority is not None:
            out["priority"] = self.priority.currentData()
        if self.minutes is not None:
            out["minutes"] = self.minutes.value()
        if self.high is not None:
            out["high"] = self.high.value()
        if self.low is not None:
            out["low"] = self.low.value()
        return out


class GeneralPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.language = _combo([("English", "en"), ("Українська", "uk")], "en")
        self.autostart = QCheckBox(tr("settings.autostart"))
        self.shortcut = QCheckBox(tr("settings.shortcut"))
        self.ip = QLineEdit()
        self.port = _spin(1, 65535, 30000)
        rediscover = QPushButton(tr("settings.rediscover"))
        rediscover.clicked.connect(lambda: window.rediscover.emit())
        battery = QHBoxLayout()
        battery.addWidget(self.ip, 1)
        battery.addWidget(QLabel(":"))
        battery.addWidget(self.port)
        battery.addWidget(rediscover)
        self.poll = _spin(60, 3600, 60, " s")
        self.offline = _spin(1, 20, 3, tr("settings.polls_suffix"))
        form.addRow(tr("settings.language"), self.language)
        form.addRow("", self.autostart)
        form.addRow("", self.shortcut)
        form.addRow(tr("settings.battery"), battery)
        form.addRow(tr("settings.poll"), self.poll)
        form.addRow("", label(tr("settings.poll_warning"), "muted", 0.9, wrap=True))
        form.addRow(tr("settings.offline_after"), self.offline)
        for field, key in ((self.language, "help.language"), (self.autostart, "help.autostart"),
                           (self.shortcut, "help.shortcut"), (battery, "help.battery"), (self.poll, "help.poll"),
                           (self.offline, "help.offline_after")):
            _help(form, field, key)

    def load(self, d: dict) -> None:
        _select(self.language, d["general"]["language"])
        self.autostart.setChecked(d["general"]["autostart"])
        self.shortcut.setChecked(d["general"]["start_menu_shortcut"])
        self.ip.setText(d["device"]["ip"])
        self.port.setValue(d["device"]["port"])
        self.poll.setValue(d["general"]["poll_seconds"])
        self.offline.setValue(d["general"]["offline_after_polls"])

    def collect(self, d: dict) -> None:
        d["general"].update(language=self.language.currentData(), autostart=self.autostart.isChecked(),
                            start_menu_shortcut=self.shortcut.isChecked(), poll_seconds=self.poll.value(),
                            offline_after_polls=self.offline.value())
        d["device"].update(ip=self.ip.text().strip(), port=self.port.value())


class NotificationsPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        self.window = window
        root = QVBoxLayout(self)
        quiet = QHBoxLayout()
        self.q_enabled = QCheckBox(tr("settings.quiet"))
        self.q_from = QTimeEdit()
        self.q_from.setDisplayFormat("HH:mm")
        self.q_to = QTimeEdit()
        self.q_to.setDisplayFormat("HH:mm")
        self.q_bypass = QCheckBox(tr("settings.critical_bypass"))
        self.q_silence = QCheckBox(tr("settings.silence_telegram"))
        for widget in (self.q_enabled, self.q_from, label(tr("settings.quiet_to")), self.q_to):
            quiet.addWidget(widget)
        quiet.addSpacing(12)
        quiet.addWidget(self.q_bypass)
        quiet.addWidget(self.q_silence)
        quiet.addStretch(1)
        root.addLayout(quiet)
        for widget, key in ((self.q_enabled, "help.quiet"), (self.q_from, "help.quiet"), (self.q_to, "help.quiet"),
                            (self.q_bypass, "help.critical_bypass"), (self.q_silence, "help.silence_telegram")):
            widget.setToolTip(tr(key))
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setColumnStretch(1, 1)
        root.addWidget(host)
        root.addStretch(1)
        self._work: dict = {}
        self._rows: list[_Row] = []
        self._outage_enabled = False

    def rows_for(self, rule: str) -> list[_Row]:
        return [row for row in self._rows if row.rule == rule]

    def load(self, d: dict) -> None:
        q = d["quiet_hours"]
        self.q_enabled.setChecked(q["enabled"])
        self.q_from.setTime(QTime.fromString(q["from"], "HH:mm"))
        self.q_to.setTime(QTime.fromString(q["to"], "HH:mm"))
        self.q_bypass.setChecked(q["critical_bypass"])
        self.q_silence.setChecked(q["silence_telegram"])
        self._work = copy.deepcopy(d["notifications"])
        self._outage_enabled = d["advanced"]["outage_detection"]
        self._rebuild()

    def _sync(self) -> None:
        for row in self._rows:
            if row.index is None:
                self._work[row.rule] = row.collect()
            else:
                self._work["soc_below"][row.index] = row.collect()

    def _rebuild(self) -> None:
        clear_layout(self.grid)
        self._rows = []
        headers = ((tr("col.on"), ""), (tr("col.notification"), ""), (tr("col.threshold"), "help.col_threshold"),
                   ("🖥", "help.col_desktop"), ("✈", "help.col_telegram"), (tr("col.repeat"), "help.col_repeat"), ("", ""))
        for column, (text, help_key) in enumerate(headers):
            header = label(text, "card-title", 0.8)
            if help_key:
                header.setToolTip(tr(help_key))
            self.grid.addWidget(header, 0, column)
        r = 1
        for group_key, rules in GROUPS:
            self.grid.addWidget(label(tr(group_key).upper(), "card-title", 0.8), r, 0, 1, 7)
            r += 1
            for rule in rules:
                if rule == "soc_below":
                    levels = self._work["soc_below"]
                    for i, level in enumerate(levels):
                        r = self._add_row(_Row(rule, level, i), r, removable=i > 0)
                    if len(levels) < MAX_SOC_LEVELS:
                        add = QPushButton(tr("settings.add_level"))
                        add.clicked.connect(self._add_level)
                        self.grid.addWidget(add, r, 1)
                        r += 1
                else:
                    r = self._add_row(_Row(rule, self._work[rule]), r)
            if group_key == "group.grid" and not self._outage_enabled:
                self.grid.addWidget(label(tr("settings.experimental_hint"), "muted", 0.85, wrap=True), r, 1, 1, 6)
                r += 1

    def _add_row(self, row: _Row, r: int, removable: bool = False) -> int:
        self._rows.append(row)
        name = QWidget()
        name_layout = QHBoxLayout(name)
        name_layout.setContentsMargins(0, 0, 0, 0)
        row.name_label = QLabel(tr(RULE_LABELS[row.rule]))
        row.name_label.setToolTip(tr(RULE_HELP[row.rule]))
        name_layout.addWidget(row.name_label)
        if row.rule in EXPERIMENTAL:
            name_layout.addWidget(label(tr("badge.experimental"), "badge-warn", 0.8))
        elif row.rule in CRITICAL_RULES:
            name_layout.addWidget(label(tr("badge.critical"), "badge-critical", 0.8))
        name_layout.addStretch(1)
        self.grid.addWidget(row.enabled, r, 0)
        self.grid.addWidget(name, r, 1)
        threshold = row.threshold_widget()
        if threshold is not None:
            self.grid.addWidget(threshold, r, 2)
        if row.desktop is not None:
            self.grid.addWidget(row.desktop, r, 3)
        if row.telegram is not None:
            self.grid.addWidget(row.telegram, r, 4)
        if row.repeat is not None:
            self.grid.addWidget(row.repeat, r, 5)
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        row.test_button.clicked.connect(lambda _=False, rw=row: self.window.test_notification.emit(rw.rule, rw.collect()))
        actions_layout.addWidget(row.test_button)
        if removable:
            remove = QToolButton()
            remove.setText("✕")
            remove.setToolTip(tr("settings.remove_level"))
            remove.clicked.connect(lambda _=False, i=row.index: self._remove_level(i))
            actions_layout.addWidget(remove)
        self.grid.addWidget(actions, r, 6)
        if row.rule in EXPERIMENTAL and not self._outage_enabled:
            for widget in row.widgets():
                widget.setEnabled(False)
        return r + 1

    def _add_level(self) -> None:
        self._sync()
        if len(self._work["soc_below"]) < MAX_SOC_LEVELS:
            self._work["soc_below"].append(dict(NEW_LEVEL))
            self._rebuild()

    def _remove_level(self, index: int) -> None:
        self._sync()
        if len(self._work["soc_below"]) > 1:
            del self._work["soc_below"][index]
            self._rebuild()

    def collect(self, d: dict) -> None:
        self._sync()
        d["notifications"] = copy.deepcopy(self._work)
        d["quiet_hours"].update(enabled=self.q_enabled.isChecked(), critical_bypass=self.q_bypass.isChecked(),
                                silence_telegram=self.q_silence.isChecked(),
                                **{"from": self.q_from.time().toString("HH:mm"),
                                   "to": self.q_to.time().toString("HH:mm")})


class TelegramPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.enabled = QCheckBox(tr("settings.tg_enabled"))
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        reveal = QToolButton()
        reveal.setText("👁")
        reveal.setCheckable(True)
        reveal.toggled.connect(lambda on: self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        token_row = QHBoxLayout()
        token_row.addWidget(self.token, 1)
        token_row.addWidget(reveal)
        self.chat = QLineEdit()
        detect = QPushButton(tr("settings.tg_detect"))
        detect.clicked.connect(lambda: window.detect_chat.emit(self.token.text().strip()))
        chat_row = QHBoxLayout()
        chat_row.addWidget(self.chat, 1)
        chat_row.addWidget(detect)
        self.user = QLineEdit()
        self.answer = QCheckBox(tr("settings.tg_answer"))
        test = QPushButton(tr("settings.tg_test"))
        test.clicked.connect(lambda: window.send_test.emit(self.values()))
        self.status = label("", "muted", 0.9, wrap=True)
        self.user_warning = label(tr("settings.tg_user_missing"), "banner-orange", 0.9, wrap=True)
        self.steps = label(tr("settings.tg_steps"), None, 0.95, wrap=True)
        self.command_info = label(tr("settings.tg_command_info"), "muted", 0.95, wrap=True)
        self.user.textChanged.connect(lambda _text: self._update_warning())
        self.answer.toggled.connect(lambda _on: self._update_warning())
        form.addRow("", self.steps)
        form.addRow("", self.enabled)
        form.addRow(tr("settings.tg_token"), token_row)
        form.addRow(tr("settings.tg_chat"), chat_row)
        form.addRow(tr("settings.tg_user"), self.user)
        form.addRow("", self.answer)
        form.addRow("", self.user_warning)
        form.addRow("", test)
        form.addRow("", self.status)
        form.addRow("", self.command_info)
        for field, key in ((self.enabled, "help.tg_enabled"), (token_row, "help.tg_token"), (chat_row, "help.tg_chat"),
                           (self.user, "help.tg_user"), (self.answer, "help.tg_answer")):
            _help(form, field, key)

    def _update_warning(self) -> None:
        self.user_warning.setVisible(self.answer.isChecked() and not self.user.text().strip())

    def values(self) -> dict:
        return {"enabled": self.enabled.isChecked(), "bot_token": self.token.text().strip(),
                "chat_id": self.chat.text().strip(), "user_id": self.user.text().strip(),
                "answer_command": self.answer.isChecked()}

    def load(self, d: dict) -> None:
        tg = d["telegram"]
        self.enabled.setChecked(tg["enabled"])
        self.token.setText(tg["bot_token"])
        self.chat.setText(tg["chat_id"])
        self.user.setText(tg["user_id"])
        self.answer.setChecked(tg["answer_command"])
        self._update_warning()

    def collect(self, d: dict) -> None:
        d["telegram"].update(self.values())


class AppearancePage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(100, 200)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.value = QLabel("100 %")
        row = QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.value)
        self.theme = _combo([(tr("theme.system"), "system"), (tr("theme.light"), "light"),
                             (tr("theme.dark"), "dark")], "system")
        self.preview = QLabel(f"87%  {tr('state.charging', power='1 450 W')}")
        self.slider.valueChanged.connect(self._update_preview)
        form.addRow(tr("settings.font"), row)
        form.addRow(tr("settings.theme"), self.theme)
        form.addRow(tr("settings.preview"), self.preview)
        for field, key in ((row, "help.font"), (self.theme, "help.theme"), (self.preview, "help.preview")):
            _help(form, field, key)

    def _update_preview(self, value: int) -> None:
        self.value.setText(f"{value} %")
        font = QFont(self.preview.font())
        font.setPointSizeF(base_point_size() * value / 100 * 1.6)
        font.setBold(True)
        self.preview.setFont(font)

    def load(self, d: dict) -> None:
        self.slider.setValue(round(d["appearance"]["font_scale"] * 100))
        self._update_preview(self.slider.value())
        _select(self.theme, d["appearance"]["theme"])

    def collect(self, d: dict) -> None:
        d["appearance"].update(font_scale=self.slider.value() / 100, theme=self.theme.currentData())


class AdvancedPage(QWidget):
    def __init__(self, window: "SettingsWindow"):
        super().__init__()
        form = QFormLayout(self)
        self.power_sign = _combo([(tr("power.plus"), "plus_is_charging"), (tr("power.minus"), "minus_is_charging")],
                                 "plus_is_charging")
        self.counter_unit = _combo([("Wh", "Wh"), ("0.1 Wh", "0.1Wh"), ("0.01 kWh", "0.01kWh"), ("kWh", "kWh")], "Wh")
        self.verified = QCheckBox(tr("settings.counters_verified"))
        self.outage = QCheckBox(tr("settings.outage_detection"))
        self.rearm_pct = _spin(0, 20, 2, " %")
        self.rearm_c = _spin(0, 20, 2, " °C")
        self.reserve = _spin(0, 50, 12, " %")
        self.efficiency = _spin(50, 100, 93, " %")
        self.retention = _spin(1, 365, 30, tr("settings.days_suffix"))
        self.log_level = _combo([(x, x) for x in ("DEBUG", "INFO", "WARNING", "ERROR")], "INFO")
        self.record_raw = QCheckBox(tr("settings.record_raw"))
        folder = QPushButton(tr("settings.open_folder"))
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir()))))
        form.addRow(tr("settings.power_sign"), self.power_sign)
        form.addRow(tr("settings.counter_unit"), self.counter_unit)
        form.addRow("", self.verified)
        form.addRow("", self.outage)
        form.addRow(tr("settings.rearm_pct"), self.rearm_pct)
        form.addRow(tr("settings.rearm_c"), self.rearm_c)
        form.addRow(tr("settings.reserve"), self.reserve)
        form.addRow(tr("settings.efficiency"), self.efficiency)
        form.addRow(tr("settings.retention"), self.retention)
        form.addRow(tr("settings.log_level"), self.log_level)
        form.addRow("", self.record_raw)
        form.addRow("", folder)
        for field, key in ((self.power_sign, "help.power_sign"), (self.counter_unit, "help.counter_unit"),
                           (self.verified, "help.counters_verified"), (self.outage, "help.outage_detection"),
                           (self.rearm_pct, "help.rearm_pct"), (self.rearm_c, "help.rearm_c"),
                           (self.reserve, "help.reserve"), (self.efficiency, "help.efficiency"), (self.retention, "help.retention"),
                           (self.log_level, "help.log_level"), (self.record_raw, "help.record_raw"),
                           (folder, "help.open_folder")):
            _help(form, field, key)

    def load(self, d: dict) -> None:
        a = d["advanced"]
        _select(self.power_sign, a["power_sign"])
        _select(self.counter_unit, a["counter_unit"])
        self.verified.setChecked(a["counters_verified"])
        self.outage.setChecked(a["outage_detection"])
        self.rearm_pct.setValue(a["rearm_pct"])
        self.rearm_c.setValue(a["rearm_c"])
        self.reserve.setValue(a["reserve_soc_pct"])
        self.efficiency.setValue(a["inverter_efficiency_pct"])
        self.retention.setValue(a["samples_retention_days"])
        _select(self.log_level, a["log_level"])
        self.record_raw.setChecked(a["record_raw"])

    def collect(self, d: dict) -> None:
        d["advanced"].update(
            power_sign=self.power_sign.currentData(), counter_unit=self.counter_unit.currentData(),
            counters_verified=self.verified.isChecked(), outage_detection=self.outage.isChecked(),
            rearm_pct=self.rearm_pct.value(), rearm_c=self.rearm_c.value(), reserve_soc_pct=self.reserve.value(),
            inverter_efficiency_pct=self.efficiency.value(),
            samples_retention_days=self.retention.value(), log_level=self.log_level.currentData(),
            record_raw=self.record_raw.isChecked(),
        )


class SettingsWindow(QWidget):
    saved = Signal(object)
    rediscover = Signal()
    test_notification = Signal(str, object)
    detect_chat = Signal(str)
    send_test = Signal(object)

    def __init__(self, data: dict, icon: QIcon | None = None, delete_on_close: bool = True, notice: str = ""):
        super().__init__()
        self.setWindowTitle(tr("app.settings_title"))
        if icon is not None:
            self.setWindowIcon(icon)
        if delete_on_close:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._data = copy.deepcopy(data)

        self.general = GeneralPage(self)
        self.notifications = NotificationsPage(self)
        self.telegram = TelegramPage(self)
        self.appearance = AppearancePage(self)
        self.advanced = AdvancedPage(self)
        self.pages = (self.general, self.notifications, self.telegram, self.appearance, self.advanced)
        titles = (tr("settings.page.general"), tr("settings.page.notifications"), tr("settings.page.telegram"),
                  tr("settings.page.appearance"), tr("settings.page.advanced"))

        self.side = QListWidget()
        self.side.setFixedWidth(190)
        self.stack = QStackedWidget()
        for title, page in zip(titles, self.pages):
            self.side.addItem(title)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
        self.side.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.side.setCurrentRow(0)

        cancel = QPushButton(tr("settings.cancel"))
        cancel.clicked.connect(self.close)
        self.save_button = QPushButton(tr("settings.save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)

        body = QHBoxLayout()
        body.addWidget(self.side)
        body.addWidget(self.stack, 1)
        root = QVBoxLayout(self)
        self.notice_label = label(notice, "banner-orange", wrap=True) if notice else None
        if self.notice_label is not None:  # e.g. "UDP port 30000 is used by another program"
            root.addWidget(self.notice_label)
        root.addLayout(body, 1)
        root.addLayout(buttons)

        for page in self.pages:
            page.load(self._data)
        window_state.restore(self, "settings", *window_state.SETTINGS_DEFAULT)

    def closeEvent(self, event) -> None:
        window_state.save(self, "settings")
        super().closeEvent(event)

    def collect(self) -> dict:
        data = copy.deepcopy(self._data)
        for page in self.pages:
            page.collect(data)
        return validate(data)

    def _save(self) -> None:
        self.saved.emit(self.collect())
        self.close()

    def set_telegram_status(self, text: str) -> None:
        self.telegram.status.setText(text)

    def set_detected(self, chat_id: str, user_id: str) -> None:
        self.telegram.chat.setText(chat_id)
        self.telegram.user.setText(user_id)
