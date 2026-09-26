"""Choosing a note's colour: how it looks, where it is stored, and what new notes take."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.app.palette import color_name, qcolor
from stickle.core.colors import DEFAULT_COLOR, PALETTE, note_colors
from stickle.core.note import Note
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store
from stickle.data.settings import DEFAULT_NOTE_COLOR, Settings

KEY = secrets.token_bytes(32)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def manager(qtbot: QtBot, connection: apsw.Connection) -> Iterator[NoteManager]:
    manager = NoteManager(NoteRepository(connection), settings=Settings(connection))
    yield manager
    for window in manager.windows:
        window.release()


def stored_note(window: NoteWindow, connection: apsw.Connection) -> Note:
    assert window.note_id is not None
    note = NoteRepository(connection).get(window.note_id)
    assert note is not None
    return note


def pixel(window: NoteWindow, x: int, y: int) -> QColor:
    return window.grab().toImage().pixelColor(x, y)


def test_the_note_is_opaque_in_its_colours(qtbot: QtBot) -> None:
    window = NoteWindow(text="메모", color="sky")
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    colors = note_colors("sky")

    body = pixel(window, window.width() // 2, window.height() - 30)
    title = pixel(window, window.width() // 3, window.title_bar.height() // 2)

    assert body == qcolor(colors.background)
    assert body.alpha() == 255
    assert title == qcolor(colors.title_bar)
    window.release()


def test_choosing_a_colour_stores_it_and_new_notes_take_it(
    manager: NoteManager, connection: apsw.Connection
) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("하늘색으로")
    manager.save(window)

    window.color_actions["sky"].trigger()

    assert window.color == "sky"
    assert window.colors == note_colors("sky")
    assert window.color_actions["sky"].isChecked()
    assert stored_note(window, connection).color == "sky"
    assert stored_note(window, connection).body == "하늘색으로"
    assert Settings(connection).get(DEFAULT_NOTE_COLOR) == "sky"
    assert manager.new_note().color == "sky"


def test_a_new_note_keeps_its_colour_when_first_stored(
    manager: NoteManager, connection: apsw.Connection
) -> None:
    window = manager.new_note()
    window.color_actions["mint"].trigger()  # before there is any text

    window.editor.insertPlainText("민트")
    manager.save(window)

    assert stored_note(window, connection).color == "mint"


def test_colour_comes_back_after_a_restart(qtbot: QtBot, connection: apsw.Connection) -> None:
    repository = NoteRepository(connection)
    repository.create("분홍 메모", "pink")

    manager = NoteManager(repository, settings=Settings(connection))
    manager.open_stored()

    assert [window.color for window in manager.windows] == ["pink"]
    manager.windows[0].release()


def test_changing_colour_leaves_the_text_alone(manager: NoteManager) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("# 제목\n- [ ] 할 일")
    changes: list[None] = []
    window.text_changed.connect(lambda: changes.append(None))

    for key in PALETTE:
        window.color_actions[key].trigger()

    assert window.text == "# 제목\n- [ ] 할 일"
    assert changes == []


def test_an_unknown_colour_shows_the_default_and_is_kept(
    qtbot: QtBot, connection: apsw.Connection
) -> None:
    repository = NoteRepository(connection)
    note = repository.create("newer version", "teal2")
    manager = NoteManager(repository, settings=Settings(connection))
    manager.open_stored()
    window = manager.windows[0]

    assert window.colors == note_colors(DEFAULT_COLOR)
    assert not any(action.isChecked() for action in window.color_actions.values())
    window.editor.insertPlainText(" edited")
    manager.hide(window)

    stored = repository.get(note.id)
    assert stored is not None
    assert stored.color == "teal2"


def test_a_colour_that_cannot_be_stored_is_not_shown(
    manager: NoteManager, connection: apsw.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = manager.new_note()
    window.editor.insertPlainText("저장 실패")
    manager.save(window)

    def fail(self: NoteRepository, note_id: str, color: str) -> Note:
        raise apsw.FullError("database or disk is full")

    monkeypatch.setattr(NoteRepository, "set_color", fail)
    window.color_actions["coral"].trigger()

    assert window.color == DEFAULT_COLOR
    assert window.color_actions[DEFAULT_COLOR].isChecked()
    assert stored_note(window, connection).color == DEFAULT_COLOR


def test_colour_can_be_chosen_with_the_keyboard(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()

    window.open_menu()  # what F10 does (test_note_persistence)
    qtbot.waitUntil(window.menu.isVisible)
    QTest.keyClick(window.menu, Qt.Key.Key_Down)  # the first item: Color
    QTest.keyClick(window.menu, Qt.Key.Key_Right)  # into the colour menu, on its first colour
    qtbot.waitUntil(window.color_menu.isVisible)
    QTest.keyClick(window.color_menu, Qt.Key.Key_Down)
    QTest.keyClick(window.color_menu, Qt.Key.Key_Return)

    assert window.color == list(PALETTE)[1]


def test_right_clicking_the_title_bar_opens_the_menu(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    window.show()
    bar = window.title_bar
    point = QPoint(bar.width() // 3, bar.height() // 2)

    QApplication.sendEvent(
        bar, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, bar.mapToGlobal(point))
    )

    qtbot.waitUntil(window.menu.isVisible)
    window.menu.close()
    window.release()


def test_colour_names_are_translated(qtbot: QtBot, translations: Translations) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)

    translations.apply("ko")

    assert color_name("sky") == "하늘"
    assert window.color_actions["sky"].text() == "하늘"
    assert window.color_menu.title() == "색"
    assert all(action.text() for action in window.color_actions.values())
    window.release()
