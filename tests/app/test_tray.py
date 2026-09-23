from pytestqt.qtbot import QtBot

from stickle.app.i18n import Translations
from stickle.app.tray import Tray


def test_menu_actions_call_their_handlers(translations: Translations) -> None:
    calls: list[str] = []
    tray = Tray(lambda: calls.append("new"), lambda: calls.append("quit"), translations)

    tray.new_note_action.trigger()
    tray.quit_action.trigger()

    assert calls == ["new", "quit"]


def test_tray_has_an_icon_and_a_menu(qtbot: QtBot, translations: Translations) -> None:
    tray = Tray(lambda: None, lambda: None, translations)

    assert not tray.icon().isNull()
    assert tray.contextMenu() is not None


def test_language_menu_switches_and_marks_the_choice(translations: Translations) -> None:
    tray = Tray(lambda: None, lambda: None, translations)

    tray.language_actions["ko"].trigger()

    assert translations.language == "ko"
    assert tray.language_actions["ko"].isChecked()
    assert not tray.language_actions["en"].isChecked()
