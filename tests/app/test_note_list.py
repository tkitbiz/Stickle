"""The list of notes in the Stickle window."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from stickle.app.i18n import Translations
from stickle.app.note_list import ALL, HIDDEN, REFRESH_DELAY_MS, SHOWN
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.app.stickle_window import DEFAULT_SIZE, StickleWindow
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store
from stickle.data.settings import LIST_WINDOW_SIZE, Settings

KEY = secrets.token_bytes(32)


class App:
    def __init__(self, connection: apsw.Connection) -> None:
        self.notes = NoteRepository(connection)
        self.settings = Settings(connection)
        self.manager = NoteManager(self.notes, idle_ms=10, max_ms=50)
        self.window = StickleWindow(
            self.manager, Translations(), lambda: None, settings=self.settings
        )

    def rows(self) -> list[str]:
        rows = self.window.note_list.list
        return [rows.item(row).text() for row in range(rows.count())]

    def note(self, text: str) -> NoteWindow:
        window = self.manager.new_note()
        window.editor.insertPlainText(text)
        self.manager.save(window)
        return window

    def select(self, text: str) -> None:
        rows = self.window.note_list.list
        for row in range(rows.count()):
            if rows.item(row).text().startswith(text):
                rows.setCurrentRow(row)
                return
        raise AssertionError(f"{text!r} not listed in {self.rows()}")

    def show_only(self, which: str) -> None:
        box = self.window.note_list.filter_box
        box.setCurrentIndex(box.findData(which))

    def close(self) -> None:
        for note in self.manager.windows:
            note.release()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def app(qtbot: QtBot, connection: apsw.Connection) -> Iterator[App]:
    app = App(connection)
    yield app
    app.close()


def test_every_note_is_listed_latest_change_first_hidden_ones_marked(app: App) -> None:
    first = app.note("첫 메모")
    app.note("# 둘째 메모\n본문")
    app.manager.hide(first)
    app.window.open()

    assert app.rows() == ["첫 메모 · hidden", "둘째 메모"]


def test_notes_on_screen_or_hidden_can_be_shown_apart(app: App) -> None:
    app.manager.hide(app.note("숨긴 것"))
    app.note("보이는 것")
    app.window.open()

    app.show_only(SHOWN)
    assert app.rows() == ["보이는 것"]
    app.show_only(HIDDEN)
    assert app.rows() == ["숨긴 것 · hidden"]
    app.show_only(ALL)
    assert len(app.rows()) == 2


def test_enter_brings_a_note_forward_and_shows_a_hidden_one(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    fronted: list[str | None] = []

    def record(self: NoteWindow) -> None:
        fronted.append(self.note_id)

    monkeypatch.setattr(NoteWindow, "bring_to_front", record)
    shown = app.note("보이는 것")
    app.manager.hide(app.note("숨긴 것"))
    app.window.open()

    app.select("보이는 것")
    QTest.keyClick(app.window.note_list.list, Qt.Key.Key_Return)
    assert fronted == [shown.note_id]

    app.select("숨긴 것")
    QTest.keyClick(app.window.note_list.list, Qt.Key.Key_Return)
    assert len(app.manager.windows) == 2
    assert "숨긴 것" in app.rows()  # no longer marked hidden


def test_delete_key_deletes_the_selected_note_without_asking(app: App) -> None:
    keep = app.note("남길 것")
    app.note("지울 것")
    app.manager.hide(app.note("숨겨서 지울 것"))
    app.window.open()

    app.select("지울 것")
    QTest.keyClick(app.window.note_list.list, Qt.Key.Key_Delete)
    app.select("숨겨서 지울 것")
    QTest.keyClick(app.window.note_list.list, Qt.Key.Key_Delete)

    assert app.rows() == ["남길 것"]
    assert [w.note_id for w in app.manager.windows] == [keep.note_id]
    deleted = app.manager.last_deleted()
    assert deleted is not None and deleted.body == "숨겨서 지울 것"  # can be brought back


def test_the_context_menu_hides_shows_and_deletes(app: App) -> None:
    app.note("메모")
    app.window.open()
    rows = app.window.note_list.list

    def act(label: str) -> None:
        menu = app.window.note_list.menu_for(rows.currentItem())
        action = next(a for a in menu.actions() if a.text() == label)
        action.trigger()
        menu.close()

    app.select("메모")
    act("Hide")
    assert app.rows() == ["메모 · hidden"] and not app.manager.windows
    app.select("메모")
    act("Show")
    assert app.rows() == ["메모"] and len(app.manager.windows) == 1
    app.select("메모")
    act("Delete")
    assert app.rows() == ["No notes here"]


def test_the_list_follows_notes_made_and_changed_while_it_is_open(app: App, qtbot: QtBot) -> None:
    app.window.open()
    note = app.note("처음 제목")
    qtbot.wait(REFRESH_DELAY_MS + 100)
    assert app.rows() == ["처음 제목"]

    note.editor.selectAll()
    note.editor.insertPlainText("고친 제목")
    app.manager.save(note)
    qtbot.wait(REFRESH_DELAY_MS + 100)
    assert app.rows() == ["고친 제목"]


def test_the_list_has_the_keyboard_when_the_window_opens(app: App, qtbot: QtBot) -> None:
    app.note("메모")
    app.window.open()
    qtbot.waitExposed(app.window)

    assert app.window.note_list.list.hasFocus() or app.window.focusWidget() is (
        app.window.note_list.list
    )
    assert app.window.note_list.list.currentRow() == 0


def test_the_window_size_is_kept_on_this_computer(app: App, qtbot: QtBot) -> None:
    assert (app.window.width(), app.window.height()) == DEFAULT_SIZE
    app.window.open()
    qtbot.waitExposed(app.window)
    app.window.resize(520, 700)
    app.window.hide()

    assert app.settings.get(LIST_WINDOW_SIZE) == [520, 700]
    again = StickleWindow(app.manager, Translations(), lambda: None, settings=app.settings)
    assert (again.width(), again.height()) == (520, 700)
    again.deleteLater()
