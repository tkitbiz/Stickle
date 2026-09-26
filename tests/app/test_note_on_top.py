"""Keeping a note above other windows, with the pin in its title bar."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.app.tray import Tray
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
    manager = NoteManager(NoteRepository(connection))
    yield manager
    for window in manager.windows:
        window.release()


def stored_note(manager: NoteManager) -> NoteWindow:
    window = manager.new_note()
    window.editor.insertPlainText("핀 시험")
    manager.save(window)
    return window


def on_top_flag(window: NoteWindow) -> bool:
    return bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def test_new_notes_stay_on_top_and_show_a_solid_pin(manager: NoteManager) -> None:
    window = manager.new_note()

    assert on_top_flag(window)
    assert window.title_bar.pin_button.isChecked()
    assert window.on_top_action.isChecked()


def test_the_pin_turns_it_off_and_on_and_it_is_stored(
    manager: NoteManager, connection: apsw.Connection
) -> None:
    window = stored_note(manager)
    geometry = window.geometry()
    notes = NoteRepository(connection)

    window.title_bar.pin_button.click()

    assert not on_top_flag(window)
    assert window.isVisible()
    assert window.geometry() == geometry
    assert not window.on_top_action.isChecked()
    note = notes.get(window.note_id or "")
    assert note is not None and not note.always_on_top

    window.title_bar.pin_button.click()

    assert on_top_flag(window)
    note = notes.get(window.note_id or "")
    assert note is not None and note.always_on_top


def test_the_pin_changes_the_window_without_remaking_it(manager: NoteManager) -> None:
    # Remaking the native window hides and shows it again: the note blinks.
    window = stored_note(manager)
    native = window.windowHandle()
    hidden: list[bool] = []

    def visible_changed(visible: bool) -> None:
        hidden.append(not visible)

    native.visibleChanged.connect(visible_changed)

    window.title_bar.pin_button.click()

    assert window.windowHandle() is native
    assert not on_top_flag(window)
    assert not native.flags() & Qt.WindowType.WindowStaysOnTopHint
    assert not any(hidden)

    window.title_bar.pin_button.click()

    assert window.windowHandle() is native
    assert native.flags() & Qt.WindowType.WindowStaysOnTopHint
    assert not any(hidden)


def test_the_menu_does_the_same_as_the_pin(manager: NoteManager) -> None:
    window = stored_note(manager)

    window.on_top_action.trigger()

    assert not on_top_flag(window)
    assert not window.title_bar.pin_button.isChecked()


def test_a_note_not_on_top_opens_that_way(qtbot: QtBot, connection: apsw.Connection) -> None:
    notes = NoteRepository(connection)
    note = notes.create("아래에 있는 메모")
    notes.set_always_on_top(note.id, False)

    manager = NoteManager(notes)
    manager.open_stored()
    (window,) = manager.windows

    assert not on_top_flag(window)
    assert not window.title_bar.pin_button.isChecked()
    window.release()


def test_a_new_note_unpinned_before_it_has_text_is_stored_unpinned(
    manager: NoteManager, connection: apsw.Connection
) -> None:
    window = manager.new_note()
    window.title_bar.pin_button.click()

    window.editor.insertPlainText("나중에")
    manager.save(window)

    note = NoteRepository(connection).get(window.note_id or "")
    assert note is not None and not note.always_on_top


def test_unpinning_leaves_the_text_alone(manager: NoteManager) -> None:
    window = stored_note(manager)
    changes: list[None] = []
    window.text_changed.connect(lambda: changes.append(None))

    window.title_bar.pin_button.click()
    window.title_bar.pin_button.click()

    assert window.text == "핀 시험"
    assert changes == []


def test_a_setting_that_cannot_be_stored_leaves_the_pin_as_it_was(
    manager: NoteManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = stored_note(manager)

    def fail(self: NoteRepository, note_id: str, on_top: bool) -> None:
        raise apsw.FullError("database or disk is full")

    monkeypatch.setattr(NoteRepository, "set_always_on_top", fail)
    window.title_bar.pin_button.click()

    assert on_top_flag(window)
    assert window.title_bar.pin_button.isChecked()
    assert window.on_top_action.isChecked()


def test_the_pin_has_a_name_and_says_what_it_does(manager: NoteManager) -> None:
    window = manager.new_note()

    assert window.title_bar.pin_button.accessibleName() == "Always on top"
    assert window.title_bar.pin_button.toolTip() == "Always on top"


def test_bring_all_notes_to_front_raises_every_note(
    manager: NoteManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = stored_note(manager), stored_note(manager)
    first.title_bar.pin_button.click()
    raised: list[NoteWindow] = []

    def record_raise(self: NoteWindow) -> None:
        raised.append(self)

    monkeypatch.setattr(NoteWindow, "raise_", record_raise)
    tray = Tray(lambda: None, lambda: None, Translations(), manager)

    tray.raise_action.trigger()

    assert set(raised) == {first, second}
    assert tray.raise_action.text() == "Bring all notes to front"
