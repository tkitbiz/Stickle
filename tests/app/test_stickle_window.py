"""The Stickle window: the tray's actions in a window, and when it opens."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QSystemTrayIcon
from pytestqt.qtbot import QtBot

from stickle.app.application import connect_stickle_window, open_at_start
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.app.stickle_window import StickleWindow
from stickle.app.tray import Tray
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)


class App:
    def __init__(self, connection: apsw.Connection, tray: bool) -> None:
        self.notes = NoteRepository(connection)
        self.manager = NoteManager(self.notes)
        self.translations = Translations()
        self.quits: list[None] = []
        self.window = StickleWindow(self.manager, self.translations, self.quit)
        self.tray = Tray(self.manager.new_note, lambda: None, self.translations, self.manager)
        connect_stickle_window(self.window, self.manager, self.tray if tray else None, self.quit)

    def quit(self) -> None:
        self.quits.append(None)

    def close(self) -> None:
        for note in self.manager.windows:
            note.release()
        # Gone before the database closes: a later language switch reaches every window.
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def app(qtbot: QtBot, connection: apsw.Connection) -> Iterator[App]:
    app = App(connection, tray=True)
    yield app
    app.close()


@pytest.fixture
def trayless(qtbot: QtBot, connection: apsw.Connection) -> Iterator[App]:
    app = App(connection, tray=False)
    yield app
    app.close()


def hidden_note(app: App, text: str) -> str:
    note = app.notes.create(text)
    app.notes.set_hidden(note.id, True)
    return note.id


def listed(window: StickleWindow) -> list[str]:
    return [window.hidden_list.item(row).text() for row in range(window.hidden_list.count())]


def open_note(app: App, text: str) -> NoteWindow:
    window = app.manager.new_note()
    window.editor.insertPlainText(text)
    app.manager.save(window)
    return window


def test_hidden_notes_are_listed_by_title_and_come_back(app: App) -> None:
    hidden_note(app, "# **장보기**\n우유")
    note_id = hidden_note(app, "- [ ] 전화하기")
    app.window.open()

    assert listed(app.window) == ["전화하기", "장보기"]  # the most recently hidden first
    app.window.hidden_list.itemActivated.emit(app.window.hidden_list.item(0))

    assert [w.note_id for w in app.manager.windows] == [note_id]
    assert listed(app.window) == ["장보기"]


def test_with_nothing_hidden_the_list_says_so(app: App) -> None:
    app.window.open()

    assert listed(app.window) == ["No hidden notes"]
    assert not app.window.hidden_list.isEnabled()
    assert not app.window.show_all_button.isEnabled()


def test_the_buttons_do_what_the_tray_does(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    hidden_note(app, "하나")
    hidden_note(app, "둘")
    app.window.open()

    app.window.show_all_button.click()
    assert sorted(w.text for w in app.manager.windows) == ["둘", "하나"]

    app.manager.delete(app.manager.windows[0])
    assert app.window.restore_button.isEnabled()
    app.window.restore_button.click()
    assert len(app.manager.windows) == 2

    app.window.new_note_button.click()
    assert len(app.manager.windows) == 3

    raised: list[NoteWindow] = []

    def record_raise(self: NoteWindow) -> None:
        raised.append(self)

    monkeypatch.setattr(NoteWindow, "raise_", record_raise)
    app.window.raise_button.click()
    assert set(raised) == set(app.manager.windows)


def test_the_quit_button_quits(app: App) -> None:
    app.window.quit_button.click()

    assert app.quits == [None]


def test_the_language_can_be_chosen(app: App) -> None:
    box = app.window.language_box
    box.activated.emit(box.findData("en"))

    assert app.translations.language == "en"
    assert box.itemText(0) == "System language"
    app.translations.apply(None)


def test_everything_has_a_name_and_a_key(app: App) -> None:
    window = app.window
    assert window.hidden_list.accessibleName()
    assert window.language_box.accessibleName()
    assert window.hidden_label.buddy() is window.hidden_list
    assert window.language_label.buddy() is window.language_box
    assert "&" in window.hidden_label.text()


# When it opens


def test_starting_with_only_hidden_notes_opens_it(app: App) -> None:
    hidden_note(app, "숨긴 메모")

    open_at_start(app.manager, app.window, tray_available=True)

    assert app.manager.windows == ()
    assert app.window.isVisible()
    assert not app.window.notice.isVisible()


def test_starting_with_notes_to_show_does_not(app: App) -> None:
    app.notes.create("보이는 메모")

    open_at_start(app.manager, app.window, tray_available=True)

    assert len(app.manager.windows) == 1
    assert not app.window.isVisible()


def test_with_a_tray_hiding_the_last_note_leaves_it_closed(app: App) -> None:
    note = open_note(app, "마지막")

    app.manager.hide(note)

    assert not app.window.isVisible()
    assert app.quits == []


def test_clicking_the_tray_icon_opens_it(app: App) -> None:
    app.tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)

    assert app.window.isVisible()


def test_without_a_tray_hiding_the_last_note_opens_it_with_a_notice(trayless: App) -> None:
    note = open_note(trayless, "마지막")

    trayless.manager.hide(note)

    assert trayless.window.isVisible()
    assert trayless.window.notice.isVisible()
    assert listed(trayless.window) == ["마지막"]
    assert trayless.quits == []


def test_without_a_tray_closing_it_then_quits(trayless: App) -> None:
    trayless.manager.hide(open_note(trayless, "마지막"))

    trayless.window.close()

    assert trayless.quits == [None]


def test_without_a_tray_a_note_brought_back_keeps_stickle_running(trayless: App) -> None:
    trayless.manager.hide(open_note(trayless, "마지막"))

    trayless.window.hidden_list.itemActivated.emit(trayless.window.hidden_list.item(0))
    assert not trayless.window.notice.isVisible()
    trayless.window.close()

    assert trayless.quits == []
    assert len(trayless.manager.windows) == 1
