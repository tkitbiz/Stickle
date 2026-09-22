from pytestqt.qtbot import QtBot

from stickle.app.tray import Tray


def test_menu_actions_call_their_handlers(qtbot: QtBot) -> None:
    calls: list[str] = []
    tray = Tray(lambda: calls.append("new"), lambda: calls.append("quit"))

    tray.new_note_action.trigger()
    tray.quit_action.trigger()

    assert calls == ["new", "quit"]


def test_tray_has_an_icon_and_a_menu(qtbot: QtBot) -> None:
    tray = Tray(lambda: None, lambda: None)

    assert not tray.icon().isNull()
    assert tray.contextMenu() is not None
