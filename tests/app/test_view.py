"""On the desktop, the notes of one category only."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from pytestqt.qtbot import QtBot

from stickle.app.application import answer_request
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NO_CATEGORY, NoteManager
from stickle.app.stickle_window import StickleWindow
from stickle.app.tray import Tray
from stickle.core.labels import Category
from stickle.data.labels import LabelRepository
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store
from stickle.platform.instance import NEXT_VIEW

KEY = secrets.token_bytes(32)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


class App:
    def __init__(self, connection: apsw.Connection) -> None:
        self.notes = NoteRepository(connection)
        self.labels = LabelRepository(connection)
        self.manager = NoteManager(self.notes, idle_ms=10, max_ms=50, labels=self.labels)
        self.window = StickleWindow(self.manager, Translations(), lambda: None)
        self.work = self.labels.create_category("회사", "blue")
        self.home = self.labels.create_category("집", "green")

    def note(self, text: str, category: Category | None = None) -> NoteWindow:
        window = self.manager.new_note()
        window.editor.insertPlainText(text)
        self.manager.save(window)
        if category is not None:
            self.manager.set_category(window, category.id)
        return window

    def shown(self) -> list[str]:
        return sorted(w.text for w in self.manager.windows if w.isVisible())

    def close(self) -> None:
        for window in self.manager.windows:
            window.release()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def app(qtbot: QtBot, connection: apsw.Connection) -> Iterator[App]:
    app = App(connection)
    app.note("회의", app.work)
    app.note("보고서", app.work)
    app.note("장보기", app.home)
    app.note("아무거나")
    yield app
    app.close()


ALL = ["보고서", "아무거나", "장보기", "회의"]


def test_one_category_on_the_desktop_and_all_again(app: App) -> None:
    places = {w.text: w.pos() for w in app.manager.windows}

    app.manager.set_view(app.work.id)
    assert app.shown() == ["보고서", "회의"]
    assert app.window.view_status.isVisibleTo(app.window)
    assert "회사" in app.window.view_status.text()

    app.manager.set_view(None)
    assert app.shown() == ALL
    assert {w.text: w.pos() for w in app.manager.windows} == places
    assert not app.window.view_status.isVisibleTo(app.window)


def test_the_notes_with_no_category_can_be_viewed(app: App) -> None:
    app.manager.set_view(NO_CATEGORY)
    assert app.shown() == ["아무거나"]


def test_nothing_is_stored(app: App) -> None:
    app.manager.set_view(app.home.id)
    assert all(not note.hidden for note in app.notes.live())


def test_a_new_note_in_a_view_is_of_its_category(app: App) -> None:
    app.manager.set_view(app.work.id)
    window = app.manager.new_note()
    window.editor.insertPlainText("새 메모")
    app.manager.save(window)

    assert window.isVisible() and window.category == app.work
    stored = app.notes.get(window.note_id or "")
    assert stored is not None and stored.label == app.work.id


def test_the_next_view_goes_round_the_categories(app: App) -> None:
    app.manager.next_view()
    assert app.manager.view == app.work.id
    answer_request(NEXT_VIEW, app.manager, app.window)  # the shortcut, or --next-category
    assert app.manager.view == app.home.id
    app.manager.next_view()
    assert app.manager.view is None and app.shown() == ALL


def test_a_note_given_another_category_stays_until_the_view_changes(app: App) -> None:
    app.manager.set_view(app.work.id)
    meeting = next(w for w in app.manager.windows if w.text == "회의")
    app.manager.set_category(meeting, app.home.id)
    assert meeting.isVisible()

    app.manager.set_view(app.work.id)
    assert app.shown() == ["보고서"]


def test_a_note_opened_from_the_list_comes_in_sight(app: App) -> None:
    app.manager.set_view(app.work.id)
    shopping = next(w for w in app.manager.windows if w.text == "장보기")
    app.manager.open_note(shopping.note_id or "")
    assert shopping.isVisible()
    app.manager.set_view(None)
    assert app.shown() == ALL


def test_deleting_the_category_in_view_shows_every_note(app: App) -> None:
    app.manager.set_view(app.home.id)
    app.manager.remove_category(app.home.id, with_notes=False)
    assert app.manager.view is None and app.shown() == ALL


def test_set_aside_in_a_view_comes_back_in_it(app: App) -> None:
    app.manager.set_view(app.work.id)
    app.manager.switch_set_aside()
    assert app.shown() == []
    app.manager.switch_set_aside()
    assert app.shown() == ["보고서", "회의"]


def test_a_view_chosen_while_set_aside_keeps_them_aside(app: App) -> None:
    app.manager.switch_set_aside()
    app.manager.set_view(app.home.id)
    assert app.shown() == []
    app.manager.switch_set_aside()
    assert app.shown() == ["장보기"]


def test_the_stickle_window_and_the_tray_offer_the_views(qtbot: QtBot, app: App) -> None:
    box = app.window.view_box
    names = [box.itemText(i) for i in range(box.count())]
    assert names == ["All notes", "Notes with no category", "회사", "집"]
    box.setCurrentIndex(2)
    box.activated.emit(2)
    assert app.manager.view == app.work.id

    tray = Tray(lambda: None, lambda: None, Translations(), app.manager)
    assert tray.toolTip() == "Stickle: only “회사” on the desktop"
    tray.view_menu.aboutToShow.emit()
    checked = [a.text() for a in tray.view_menu.actions() if a.isChecked()]
    assert checked == ["회사"]
    app.window.all_notes_button.click()
    assert tray.toolTip() == "Stickle" and app.shown() == ALL
    tray.hide()
