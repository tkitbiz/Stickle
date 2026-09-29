"""Moving, resizing and going from note to note without a mouse."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from stickle.app.i18n import Translations
from stickle.app.note_window import MOVE, RESIZE, NoteWindow
from stickle.app.notes import NoteManager
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def manager(qtbot: QtBot, connection: apsw.Connection) -> Iterator[NoteManager]:
    manager = NoteManager(NoteRepository(connection), layouts=LayoutRepository(connection))
    yield manager
    for window in manager.windows:
        window.release()


def note(qtbot: QtBot, manager: NoteManager, text: str = "메모") -> NoteWindow:
    window = manager.new_note()
    window.editor.insertPlainText(text)
    manager.save(window)
    qtbot.waitExposed(window)
    return window


def keys(window: NoteWindow, *pressed: Qt.Key, shift: bool = False) -> None:
    modifier = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    for key in pressed:
        QTest.keyClick(window, key, modifier)


def places(connection: apsw.Connection, window: NoteWindow) -> str:
    assert window.note_id is not None
    return repr(LayoutRepository(connection).places(window.note_id))


def test_the_arrow_keys_move_a_note_and_enter_keeps_it_there(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = note(qtbot, manager)
    start = window.pos()
    before = places(connection, window)

    window.move_action.trigger()
    assert window.keyboard_mode == MOVE
    keys(window, Qt.Key.Key_Right, Qt.Key.Key_Right, Qt.Key.Key_Right, Qt.Key.Key_Down)
    keys(window, Qt.Key.Key_Left, shift=True)  # a single pixel
    keys(window, Qt.Key.Key_Return)

    assert window.pos() == start + QPoint(29, 10)
    assert window.keyboard_mode is None
    assert places(connection, window) != before  # kept, as after a drag


def test_esc_puts_it_back_and_keeps_nothing(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = note(qtbot, manager)
    start = window.geometry()
    before = places(connection, window)

    window.move_action.trigger()
    keys(window, Qt.Key.Key_Down, Qt.Key.Key_Down)
    keys(window, Qt.Key.Key_Escape)
    qtbot.wait(700)  # longer than a move takes to be kept

    assert window.geometry() == start
    assert places(connection, window) == before


def test_the_arrow_keys_resize_a_note_but_not_below_a_usable_size(
    qtbot: QtBot, manager: NoteManager
) -> None:
    window = note(qtbot, manager)
    size = window.size()

    window.resize_action.trigger()
    assert window.keyboard_mode == RESIZE
    keys(window, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Down)
    assert window.size() == size + QSize(10, 20)
    for _ in range(80):
        keys(window, Qt.Key.Key_Left, Qt.Key.Key_Up)
    smallest = window.size()
    keys(window, Qt.Key.Key_Left, Qt.Key.Key_Up)
    keys(window, Qt.Key.Key_Return)

    assert window.size() == smallest  # stops where the note's buttons still fit
    assert smallest.width() >= window.title_bar.minimumSizeHint().width()
    assert smallest.height() > window.title_bar.height()


def test_while_moving_the_keys_do_not_reach_the_text(qtbot: QtBot, manager: NoteManager) -> None:
    window = note(qtbot, manager, "")
    window.edit()

    window.move_action.trigger()
    QTest.keyClicks(window, "abc")
    keys(window, Qt.Key.Key_Return)

    assert window.text == ""


def test_the_title_bar_says_how_while_it_lasts(qtbot: QtBot, manager: NoteManager) -> None:
    window = note(qtbot, manager)

    window.move_action.trigger()
    assert window.title_bar.title.isVisibleTo(window)
    assert "Enter" in window.title_bar._full_title  # pyright: ignore[reportPrivateUsage]
    keys(window, Qt.Key.Key_Escape)

    assert not window.title_bar.title.isVisibleTo(window)


def test_a_locked_note_cannot_be_moved_or_resized_with_the_keyboard(
    qtbot: QtBot, manager: NoteManager
) -> None:
    window = note(qtbot, manager)
    window.lock_action.trigger()

    assert not window.move_action.isEnabled()
    assert not window.resize_action.isEnabled()
    window.start_keyboard(MOVE)
    assert window.keyboard_mode is None


def test_ctrl_tab_goes_round_the_notes_on_screen(
    qtbot: QtBot, manager: NoteManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    fronted: list[str] = []

    def record(self: NoteWindow) -> None:
        fronted.append(self.text)

    first = note(qtbot, manager, "A")
    note(qtbot, manager, "B")
    manager.hide(note(qtbot, manager, "숨김"))
    note(qtbot, manager, "C")
    monkeypatch.setattr(NoteWindow, "bring_to_front", record)

    for window in (first, manager.windows[1], manager.windows[2]):
        window.switch_requested.emit(1)
    first.switch_requested.emit(-1)

    assert fronted == ["B", "C", "A", "C"]


def test_ctrl_tab_is_heard_while_typing(
    qtbot: QtBot, manager: NoteManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    fronted: list[str] = []

    def record(self: NoteWindow) -> None:
        fronted.append(self.text)

    first = note(qtbot, manager, "A")
    note(qtbot, manager, "B")
    monkeypatch.setattr(NoteWindow, "bring_to_front", record)
    first.activateWindow()
    first.edit()
    qtbot.waitActive(first)

    QTest.keySequence(first.windowHandle(), QKeySequence("Ctrl+Tab"))

    assert fronted == ["B"]
    assert first.text == "A"  # no tab typed


def test_the_new_menu_items_are_translated(qtbot: QtBot, translations: Translations) -> None:
    window = NoteWindow(text="메모")
    qtbot.addWidget(window)

    translations.apply("ko")

    assert window.move_action.text() == "방향키로 옮기기"
    assert window.resize_action.text() == "방향키로 크기 바꾸기"
    window.release()
