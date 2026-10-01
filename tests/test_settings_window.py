import pytest

from marstek_monitor import i18n, settings as settings_mod
from marstek_monitor.ui import theme
from marstek_monitor.ui.settings_window import SettingsWindow


@pytest.fixture(autouse=True)
def setup(qapp):
    i18n.set_language("en")
    theme.apply(qapp, "light", 1.0)


def make(qtbot, data=None):
    win = SettingsWindow(data or settings_mod.defaults(), delete_on_close=False)
    qtbot.addWidget(win)
    return win


def test_defaults_roundtrip(qtbot):
    data = settings_mod.defaults()
    assert make(qtbot, data).collect() == settings_mod.validate(data)


def test_add_and_remove_soc_levels(qtbot):
    win = make(qtbot)
    page = win.notifications
    page._add_level()
    assert len(win.collect()["notifications"]["soc_below"]) == 3
    page._add_level()
    assert len(win.collect()["notifications"]["soc_below"]) == 3
    page._remove_level(2)
    assert len(win.collect()["notifications"]["soc_below"]) == 2


def test_edits_are_collected(qtbot):
    win = make(qtbot)
    win.general.poll.setValue(120)
    win.appearance.slider.setValue(150)
    win.telegram.token.setText(" 123:abc ")
    win.notifications.q_enabled.setChecked(True)
    win.notifications.rows_for("soc_below")[0].pct.setValue(35)
    win.notifications.rows_for("temperature")[0].high.setValue(50)
    data = win.collect()
    assert data["general"]["poll_seconds"] == 120
    assert data["appearance"]["font_scale"] == 1.5
    assert data["telegram"]["bot_token"] == "123:abc"
    assert data["quiet_hours"]["enabled"] is True
    assert data["notifications"]["soc_below"][0]["pct"] == 35
    assert data["notifications"]["temperature"]["high"] == 50


def test_save_emits_validated_settings(qtbot):
    win = make(qtbot)
    with qtbot.waitSignal(win.saved) as blocker:
        win.save_button.click()
    assert blocker.args[0]["schema"] == settings_mod.SCHEMA


def test_experimental_rows_need_outage_detection(qtbot):
    assert not make(qtbot).notifications.rows_for("grid")[0].enabled.isEnabled()
    data = settings_mod.defaults()
    data["advanced"]["outage_detection"] = True
    assert make(qtbot, data).notifications.rows_for("grid")[0].enabled.isEnabled()


def test_notice_banner(qtbot):
    win = SettingsWindow(settings_mod.defaults(), delete_on_close=False,
                         notice="UDP port 30000 is used by another program")
    qtbot.addWidget(win)
    assert win.notice_label.text() == "UDP port 30000 is used by another program"
    assert make(qtbot).notice_label is None


def test_test_button_emits_rule(qtbot):
    win = make(qtbot)
    row = win.notifications.rows_for("soc_reached")[0]
    with qtbot.waitSignal(win.test_notification) as blocker:
        row.test_button.click()
    assert blocker.args[0] == "soc_reached" and blocker.args[1]["pct"] == 100


def test_detect_fills_chat_and_user_id(qtbot):
    win = make(qtbot)
    win.set_detected("987654321", "987654321")
    assert win.telegram.chat.text() == "987654321" and win.telegram.user.text() == "987654321"


def test_missing_user_id_warning(qtbot):
    data = settings_mod.defaults()
    data["telegram"].update(enabled=True, answer_command=True, user_id="")
    win = make(qtbot, data)
    assert not win.telegram.user_warning.isHidden()
    win.telegram.user.setText("42")
    assert win.telegram.user_warning.isHidden()
    win.telegram.user.setText("")
    win.telegram.answer.setChecked(False)
    assert win.telegram.user_warning.isHidden()


def test_telegram_page_explains_setup_and_command(qtbot):
    page = make(qtbot).telegram
    assert "Detect" in page.steps.text() and "/marstek" in page.command_info.text()


def _form_rows(page):
    from PySide6.QtWidgets import QFormLayout
    form = page.layout()
    assert isinstance(form, QFormLayout)
    for row in range(form.rowCount()):
        label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
        if field_item is None:
            continue
        yield (label_item.widget() if label_item else None), (field_item.widget() or field_item.layout())


def test_every_setting_has_a_hover_explanation(qtbot):
    from PySide6.QtWidgets import QCheckBox, QLabel
    win = make(qtbot)
    for page in (win.general, win.telegram, win.appearance, win.advanced):
        for label_widget, field in _form_rows(page):
            if isinstance(label_widget, QLabel) and label_widget.text():
                assert label_widget.toolTip(), f"{type(page).__name__}: {label_widget.text()}"
            if isinstance(field, QCheckBox):
                assert field.toolTip(), f"{type(page).__name__}: {field.text()}"
    for row in win.notifications._rows:
        assert row.name_label.toolTip(), row.rule


def test_soc_and_reserve_are_explained_in_plain_words(qtbot):
    win = make(qtbot)
    soc_row = win.notifications.rows_for("soc_below")[0]
    assert soc_row.name_label.text() == "Charge level below"
    assert "State of Charge" in soc_row.name_label.toolTip()
    reserve_label = win.advanced.layout().labelForField(win.advanced.reserve)
    assert reserve_label.text() == "Reserve for “time left”"
    assert "12%" in reserve_label.toolTip()
