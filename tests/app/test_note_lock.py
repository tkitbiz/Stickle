"""A locked note stays where it is, as it is: it can still be hidden, deleted and restyled."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot
from test_autosave import compose

from stickle.app.i18n import Translations
from stickle.app.note_list import NoteList
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.core.note import Note
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)
TASKS = "할 일\n- [ ] 우유\n"


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def manager(qtbot: QtBot, connection: apsw.Connection) -> Iterator[NoteManager]:
    manager = NoteManager(NoteRepository(connection))
    yield manager
    for window in manager.windows:
        window.release()


def stored(window: NoteWindow, connection: apsw.Connection) -> Note:
    assert window.note_id is not None
    note = NoteRepository(connection).get(window.note_id)
    assert note is not None
    return note


def locked_note(qtbot: QtBot, manager: NoteManager, text: str = TASKS) -> NoteWindow:
    window = manager.new_note()
    window.editor.insertPlainText(text)
    manager.save(window)
    qtbot.waitExposed(window)
    window.lock_action.trigger()
    return window


def drag_title_bar(qtbot: QtBot, window: NoteWindow) -> None:
    bar = window.title_bar
    start = QPoint(bar.width() // 3, bar.height() // 2)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 6):
        QTest.mouseMove(bar, start + QPoint(step * 12, step * 8))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    qtbot.wait(50)


def test_locking_is_stored_and_shown_in_the_title_bar(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = locked_note(qtbot, manager)

    assert stored(window, connection).locked
    assert window.lock_action.isChecked()
    assert window.title_bar.lock_button.isVisibleTo(window)
    assert window.title_bar.lock_button.accessibleName() == "Locked"


def test_a_locked_note_cannot_be_moved_or_resized(qtbot: QtBot, manager: NoteManager) -> None:
    window = locked_note(qtbot, manager)
    where = window.pos()

    drag_title_bar(qtbot, window)

    assert window.pos() == where
    assert not window.size_grip.isVisibleTo(window)


def test_an_unlocked_note_still_moves(qtbot: QtBot, manager: NoteManager) -> None:
    window = locked_note(qtbot, manager)
    window.lock_action.trigger()  # unlocked again
    where = window.pos()

    drag_title_bar(qtbot, window)

    assert window.pos() != where
    assert window.size_grip.isVisibleTo(window)


def test_a_locked_note_cannot_be_edited_nor_its_boxes_checked(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = locked_note(qtbot, manager)
    assert not window.editing

    window.view.edit_requested.emit(-1)  # a double-click, or Enter
    window.view.checkbox_clicked.emit(1)

    assert not window.editing
    assert window.editor.isReadOnly()
    assert window.text == TASKS
    manager.save(window)
    assert stored(window, connection).body == TASKS


def test_locking_while_typing_keeps_what_was_typed(
    qtbot: QtBot,
    manager: NoteManager,
    connection: apsw.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("안녕")
    manager.save(window)
    compose(window, "하")

    def commit() -> None:  # as an input method asked to commit does
        compose(window, "", commit="하")

    monkeypatch.setattr(window, "_request_commit", commit)
    monkeypatch.setattr(window.editor, "hasFocus", lambda: True)
    window.lock_action.trigger()

    assert stored(window, connection).body == "안녕하"
    assert not window.editing  # shown formatted, read only


def test_a_locked_note_can_still_be_restyled_hidden_deleted_and_restored(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = locked_note(qtbot, manager)
    note_id = str(window.note_id)

    window.color_actions["sky"].trigger()
    window.opacity_actions[0.8].trigger()
    window.on_top_action.trigger()
    manager.set_collapsed(window, True)
    manager.set_collapsed(window, False)
    assert not window.size_grip.isVisibleTo(window)  # unfolded, still locked
    note = stored(window, connection)
    assert (note.color, note.opacity, note.always_on_top) == ("sky", 0.8, False)

    manager.delete(window)
    manager.restore_note(note_id)

    again = manager.window_for(note_id)
    assert again is not None and again.locked
    assert again.text == TASKS


def test_unlocking_lets_it_be_edited_again(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    window = locked_note(qtbot, manager)
    window.lock_action.trigger()

    window.view.checkbox_clicked.emit(1)
    window.view.edit_requested.emit(-1)

    assert window.editing and not window.editor.isReadOnly()
    assert window.text == "할 일\n- [x] 우유\n"
    assert not stored(window, connection).locked


def test_it_stays_locked_when_opened_again(
    qtbot: QtBot, manager: NoteManager, connection: apsw.Connection
) -> None:
    locked_note(qtbot, manager)

    reopened = NoteManager(NoteRepository(connection))
    reopened.open_stored()

    assert reopened.windows[0].locked
    assert reopened.windows[0].title_bar.lock_button.isVisibleTo(reopened.windows[0])
    for window in reopened.windows:
        window.release()


def test_if_it_cannot_be_stored_the_note_stays_as_it_was(
    qtbot: QtBot, manager: NoteManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("메모")
    manager.save(window)

    def fail(*_: object) -> Note:
        raise apsw.FullError("database or disk is full")

    monkeypatch.setattr(NoteRepository, "set_locked", fail)
    window.lock_action.trigger()

    assert not window.locked
    assert not window.lock_action.isChecked()


def test_the_list_of_notes_says_which_are_locked(qtbot: QtBot, manager: NoteManager) -> None:
    locked_note(qtbot, manager, "잠근 메모")
    listed = NoteList(manager)
    qtbot.addWidget(listed)

    assert listed.list.item(0).text() == "잠근 메모 · locked"


def test_the_lock_is_translated(qtbot: QtBot, translations: Translations) -> None:
    window = NoteWindow(text="메모")
    qtbot.addWidget(window)

    translations.apply("ko")

    assert window.lock_action.text() == "메모 잠그기"
    assert window.title_bar.lock_button.accessibleName() == "잠김"
    assert "메뉴" in window.title_bar.lock_button.toolTip()
    window.release()
