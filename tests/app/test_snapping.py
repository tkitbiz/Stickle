"""Notes lined up where they are dropped, and moved together with Shift."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from stickle.app import note_window
from stickle.app.note_window import SETTLE_MS, NoteWindow
from stickle.app.notes import NoteManager
from stickle.core.snap import GAP
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(32)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


class App:
    def __init__(self, qtbot: QtBot, connection: apsw.Connection) -> None:
        self.qtbot = qtbot
        self.notes = NoteRepository(connection)
        self.layouts = LayoutRepository(connection)
        self.manager = NoteManager(self.notes, idle_ms=10, max_ms=50, layouts=self.layouts)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.origin = area.topLeft() + QPoint(200, 200)

    def note(self, text: str, x: int, y: int) -> NoteWindow:
        window = self.manager.new_note()
        window.editor.insertPlainText(text)
        self.manager.save(window)
        window.place(QRect(self.origin + QPoint(x, y), window.size()))
        self.qtbot.waitExposed(window)
        return window

    def drop(self, window: NoteWindow, at: QPoint, shift: bool = False, alt: bool = False) -> None:
        """As a drag by the title bar would: started, moved, let go, left alone."""
        window.title_bar.drag_started.emit(shift)
        before = window.pos()
        window.move(self.origin + at)
        if shift:
            # Each step says how far from the start, as the window's own pos() lags under X11.
            distance = window.pos() - before
            window.title_bar.dragged_by.emit(QPoint(distance.x() // 2, distance.y() // 2))
            window.title_bar.dragged_by.emit(distance)
        window.alt_at_drop = alt
        window.geometry_settled.emit()

    def close(self) -> None:
        for window in self.manager.windows:
            window.release()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def app(qtbot: QtBot, connection: apsw.Connection) -> Iterator[App]:
    app = App(qtbot, connection)
    yield app
    app.close()


def test_dropped_beside_a_note_it_lines_up(qtbot: QtBot, app: App) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", 600, 0)
    app.drop(b, QPoint(a.width() + 10, 5))

    target = a.pos() + QPoint(a.width() + GAP, 0)
    qtbot.waitUntil(lambda: b.pos() == target, timeout=1000)
    qtbot.waitUntil(lambda: not b.moved_by_user, timeout=1000)  # where it went is remembered


def test_held_still_in_the_middle_of_a_drag_it_is_not_dropped_yet(
    qtbot: QtBot, app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", 600, 0)
    held = [True]
    monkeypatch.setattr(note_window, "_main_button_down", lambda: held[0])
    b.title_bar.drag_started.emit(False)
    b.move(app.origin + QPoint(a.width() + 10, 5))
    qtbot.wait(SETTLE_MS + 300)
    assert b.dragging and b.pos() == app.origin + QPoint(a.width() + 10, 5)

    held[0] = False  # let go
    target = a.pos() + QPoint(a.width() + GAP, 0)
    qtbot.waitUntil(lambda: b.pos() == target, timeout=SETTLE_MS + 1000)


def test_far_from_everything_it_stays(qtbot: QtBot, app: App) -> None:
    app.note("a", 0, 0)
    b = app.note("b", 600, 0)
    app.drop(b, QPoint(700, 300))
    qtbot.wait(200)
    assert b.pos() == app.origin + QPoint(700, 300)


def test_alt_at_the_drop_leaves_it_where_it_is(qtbot: QtBot, app: App) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", 600, 0)
    app.drop(b, QPoint(a.width() + 10, 5), alt=True)
    qtbot.wait(200)
    assert b.pos() == app.origin + QPoint(a.width() + 10, 5)


def test_shift_moves_the_notes_beside_it_along(qtbot: QtBot, app: App) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", a.width() + GAP, 0)
    c = app.note("c", 0, a.height() + GAP)
    far = app.note("far", 900, 0)
    far_at = far.pos()
    shift = QPoint(40, 60)
    b_at, c_at = b.pos(), c.pos()

    app.drop(a, shift, shift=True)
    qtbot.wait(200)

    assert b.pos() == b_at + shift and c.pos() == c_at + shift
    assert far.pos() == far_at


def test_a_locked_note_is_not_taken_along(qtbot: QtBot, app: App) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", a.width() + GAP, 0)
    app.manager.set_locked(b, True)
    b_at = b.pos()
    app.drop(a, QPoint(30, 400), shift=True)
    qtbot.wait(200)
    assert b.pos() == b_at


def test_without_shift_only_the_note_moves(qtbot: QtBot, app: App) -> None:
    a = app.note("a", 0, 0)
    b = app.note("b", a.width() + GAP, 0)
    b_at = b.pos()
    app.drop(a, QPoint(30, 400))
    qtbot.wait(200)
    assert b.pos() == b_at
