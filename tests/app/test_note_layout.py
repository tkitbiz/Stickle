"""Notes come back where they were, with their size; and stay on screen when monitors change."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from stickle.app.note_window import SETTLE_MS, NoteWindow
from stickle.app.notes import NoteManager
from stickle.core.layout import MAIN, Place
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)


class App:
    """One run of the app against a database."""

    def __init__(self, connection: apsw.Connection) -> None:
        self.notes = NoteRepository(connection)
        self.layouts = LayoutRepository(connection)
        self.manager = NoteManager(self.notes, layouts=self.layouts)

    def close(self) -> None:
        for window in self.manager.windows:
            window.release()


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


def stored_note(app: App, text: str = "여기에") -> NoteWindow:
    window = app.manager.new_note()
    window.editor.insertPlainText(text)
    app.manager.save(window)
    assert window.note_id is not None
    return window


def screen_area() -> QRect:
    return QGuiApplication.primaryScreen().availableGeometry()


def test_a_moved_and_resized_note_opens_there_again(
    qtbot: QtBot, app: App, connection: apsw.Connection
) -> None:
    window = stored_note(app)
    target = QRect(screen_area().topLeft() + QPoint(150, 90), QSize(300, 200))

    window.setGeometry(target)
    qtbot.waitUntil(lambda: app.layouts.places(window.note_id or "")[MAIN].width == 300)
    app.close()

    again = App(connection)
    again.manager.open_stored()
    assert [w.geometry() for w in again.manager.windows] == [target]
    again.close()


def test_nothing_is_stored_until_moving_stops(qtbot: QtBot, app: App) -> None:
    window = stored_note(app)
    note_id = window.note_id or ""
    before = app.layouts.places(note_id)

    window.move(window.pos() + QPoint(40, 0))
    qtbot.wait(SETTLE_MS // 2)
    window.move(window.pos() + QPoint(40, 0))
    qtbot.wait(SETTLE_MS // 2)
    assert app.layouts.places(note_id) == before

    qtbot.waitUntil(lambda: app.layouts.places(note_id) != before)


def test_hiding_right_after_moving_keeps_the_new_place(app: App) -> None:
    window = stored_note(app)
    note_id = window.note_id or ""
    target = window.pos() + QPoint(60, 40)

    window.move(target)
    app.manager.hide(window)  # before the move settled

    place = app.layouts.places(note_id)[MAIN]
    screen = QGuiApplication.primaryScreen().geometry()
    assert round(place.rel_x * screen.width()) + screen.x() == target.x()
    assert round(place.rel_y * screen.height()) + screen.y() == target.y()


def test_a_new_note_moved_before_it_has_text_keeps_that_place(app: App) -> None:
    window = app.manager.new_note()
    target = window.pos() + QPoint(70, 50)
    window.move(target)

    window.editor.insertPlainText("이제 저장")
    app.manager.save(window)

    places = app.layouts.places(window.note_id or "")
    screen = QGuiApplication.primaryScreen().geometry()
    assert round(places[MAIN].rel_x * screen.width()) + screen.x() == target.x()


def test_opening_a_note_where_it_was_stores_nothing_new(
    qtbot: QtBot, app: App, connection: apsw.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = stored_note(app)
    window.move(window.pos() + QPoint(30, 30))
    app.manager.save_layout(window)
    app.close()
    saves: list[str] = []
    original = LayoutRepository.save

    def counting_save(self: LayoutRepository, note_id: str, places: dict[str, Place]) -> None:
        saves.append(note_id)
        original(self, note_id, places)

    monkeypatch.setattr(LayoutRepository, "save", counting_save)

    again = App(connection)
    again.manager.open_stored()
    qtbot.wait(SETTLE_MS + 200)

    assert saves == []
    again.close()


def test_a_note_off_screen_is_brought_back_when_monitors_change(qtbot: QtBot, app: App) -> None:
    window = stored_note(app)
    remembered = window.geometry()
    app.manager.save_layout(window, force=True)

    window.move(-5000, -5000)  # as when its monitor was unplugged
    app.manager.place_all()

    assert window.geometry() == remembered


def test_a_note_never_stored_is_kept_on_screen_when_monitors_change(app: App) -> None:
    window = app.manager.new_note()
    window.move(-5000, -5000)

    app.manager.place_all()

    assert screen_area().contains(window.geometry())


def test_a_place_that_makes_no_sense_opens_the_note_as_new(
    connection: apsw.Connection, qtbot: QtBot
) -> None:
    notes = NoteRepository(connection)
    note = notes.create("이상한 위치")
    connection.execute(
        "INSERT INTO note_layouts VALUES (?, 'main', 'garbage', 0.5, 0.5, 260, 240, '2026')",
        (note.id,),
    )

    app = App(connection)
    app.manager.open_stored()

    assert screen_area().contains(app.manager.windows[0].geometry())
    app.close()


def test_every_place_the_app_restores_is_on_screen(connection: apsw.Connection) -> None:
    notes = NoteRepository(connection)
    layouts = LayoutRepository(connection)
    for rel in (-1.0, 0.0, 0.5, 0.99, 2.0):
        note = notes.create(f"at {rel}")
        layouts.save(note.id, {MAIN: Place(1, "", rel, rel, 5000, 5000)})

    app = App(connection)
    app.manager.open_stored()

    for window in app.manager.windows:
        assert screen_area().contains(window.geometry())
    app.close()
