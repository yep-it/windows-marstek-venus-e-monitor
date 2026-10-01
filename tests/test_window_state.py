import json

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.core.monitor import Monitor
from marstek_monitor.ui import window_state
from marstek_monitor.ui.settings_window import SettingsWindow
from marstek_monitor.ui.status_window import StatusWindow


def widget(qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    return w


def screen():
    return QGuiApplication.primaryScreen().availableGeometry()


def on_screen_rect():
    s = screen()
    return QRect(s.left() + 40, s.top() + 50, min(640, s.width() - 80), min(480, s.height() - 100))


def test_geometry_is_saved_and_restored(qtbot):
    rect = on_screen_rect()
    first = widget(qtbot)
    first.setGeometry(rect)
    window_state.save(first, "status")
    second = widget(qtbot)
    window_state.restore(second, "status", 700, 500)
    assert second.geometry() == rect


def test_off_screen_position_falls_back_to_a_centered_default(qtbot, app_home):
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "window_state.json").write_text(json.dumps({"status": [-30000, -30000, 640, 480]}), encoding="utf-8")
    w = widget(qtbot)
    window_state.restore(w, "status", 700, 500)
    assert w.size() == QSize(min(700, screen().width()), min(500, screen().height()))
    assert screen().contains(w.geometry().center())


def test_default_size_never_exceeds_the_screen(qtbot):
    w = widget(qtbot)
    window_state.restore(w, "settings", 99_999, 99_999)
    assert w.width() <= screen().width() and w.height() <= screen().height()


def test_broken_state_file_is_ignored(qtbot, app_home):
    app_home.mkdir(parents=True, exist_ok=True)
    (app_home / "window_state.json").write_text("{ broken", encoding="utf-8")
    w = widget(qtbot)
    window_state.restore(w, "status", 700, 500)
    assert w.width() == min(700, screen().width())


def test_settings_window_remembers_its_geometry(qtbot):
    i18n.set_language("en")
    rect = on_screen_rect()
    win = SettingsWindow(settings_mod.defaults(), delete_on_close=False)
    qtbot.addWidget(win)
    win.setGeometry(rect)
    win.close()
    again = SettingsWindow(settings_mod.defaults(), delete_on_close=False)
    qtbot.addWidget(again)
    assert again.geometry() == rect


def test_status_window_remembers_its_geometry(qtbot):
    monitor = Monitor(settings_mod.defaults(), None)
    rect = on_screen_rect()
    win = StatusWindow(monitor, lambda: monitor.settings)
    qtbot.addWidget(win)
    win.setGeometry(rect)
    win.close()
    again = StatusWindow(monitor, lambda: monitor.settings)
    qtbot.addWidget(again)
    assert again.geometry() == rect


def test_settings_default_size_shows_the_whole_notifications_table(qtbot):
    win = SettingsWindow(settings_mod.defaults(), delete_on_close=False)
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)
    assert win.notifications.sizeHint().width() <= window_state.SETTINGS_DEFAULT[0] - win.side.width() - 60
