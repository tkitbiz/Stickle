import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest

from stickle.core.labels import BUILT_IN_MARKS
from stickle.data.database import KEY_BYTES
from stickle.data.labels import CategoryNameError, LabelRepository
from stickle.data.notes import NoteDeletedError, NoteRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(KEY_BYTES)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


@pytest.fixture
def labels(db: apsw.Connection) -> LabelRepository:
    return LabelRepository(db)


@pytest.fixture
def notes(db: apsw.Connection) -> NoteRepository:
    return NoteRepository(db)


def test_a_new_database_has_the_built_in_marks_and_no_categories(labels: LabelRepository) -> None:
    assert [mark.id for mark in labels.marks()] == list(BUILT_IN_MARKS)
    assert all(mark.name is None for mark in labels.marks())  # shown in the chosen language
    assert labels.categories() == []


def test_categories_are_made_in_order(labels: LabelRepository) -> None:
    work = labels.create_category("  Work ", "blue")
    home = labels.create_category("Home", "green")

    assert work.name == "Work"
    assert [c.id for c in labels.categories()] == [work.id, home.id]
    assert labels.category(home.id) == home


@pytest.mark.parametrize("name", ["", "   ", "\n"])
def test_a_category_needs_a_name(labels: LabelRepository, name: str) -> None:
    with pytest.raises(CategoryNameError):
        labels.create_category(name, "blue")


def test_two_categories_cannot_share_a_name(labels: LabelRepository) -> None:
    labels.create_category("회사", "blue")
    with pytest.raises(CategoryNameError):
        labels.create_category("회사", "pink")
    labels.create_category("Work", "blue")
    with pytest.raises(CategoryNameError):
        labels.create_category("WORK", "pink")


def test_a_category_colour_is_a_palette_key(labels: LabelRepository) -> None:
    with pytest.raises(ValueError):
        labels.create_category("Work", "#123456")


def test_a_note_gets_a_category_and_loses_it(
    labels: LabelRepository, notes: NoteRepository
) -> None:
    work = labels.create_category("Work", "blue")
    note = notes.create("Plan", "pink")

    on = notes.set_category(note.id, work.id)
    off = notes.set_category(note.id, None)

    assert on.label == work.id and on.change_seq > note.change_seq
    assert off.label is None
    assert off.body == note.body and off.color == note.color


def test_an_unknown_category_is_refused(notes: NoteRepository) -> None:
    note = notes.create("Plan")
    with pytest.raises(KeyError):
        notes.set_category(note.id, "no-such-category")
    assert notes.get(note.id) == note


def test_marks_are_put_on_and_taken_off(notes: NoteRepository) -> None:
    note = notes.create("Plan")

    notes.set_mark(note.id, "urgent", True)
    marked = notes.set_mark(note.id, "todo", True)
    unmarked = notes.set_mark(note.id, "urgent", False)

    assert marked.marks == {"urgent", "todo"}
    assert unmarked.marks == {"todo"}
    assert unmarked.change_seq > marked.change_seq > note.change_seq
    assert notes.visible()[0].marks == {"todo"}


def test_marking_again_changes_nothing(notes: NoteRepository) -> None:
    note = notes.set_mark(notes.create("Plan").id, "todo", True)
    assert notes.set_mark(note.id, "todo", True) == note
    assert notes.set_mark(note.id, "urgent", False) == note


def test_an_unknown_mark_is_refused(notes: NoteRepository) -> None:
    note = notes.create("Plan")
    with pytest.raises(KeyError):
        notes.set_mark(note.id, "no-such-mark", True)
    assert notes.get(note.id) == note


def test_a_locked_note_still_takes_a_category_and_marks(
    labels: LabelRepository, notes: NoteRepository
) -> None:
    work = labels.create_category("Work", "blue")
    note = notes.set_locked(notes.create("Plan").id, True)
    notes.set_category(note.id, work.id)
    marked = notes.set_mark(note.id, "important", True)
    assert marked.label == work.id and marked.marks == {"important"} and marked.locked


def test_a_deleted_note_cannot_be_marked(notes: NoteRepository) -> None:
    note = notes.delete(notes.create("Plan").id)
    with pytest.raises(NoteDeletedError):
        notes.set_mark(note.id, "todo", True)


def test_marks_stay_in_the_trash_and_go_when_it_is_emptied(
    db: apsw.Connection, notes: NoteRepository
) -> None:
    note = notes.set_mark(notes.create("Plan").id, "todo", True)
    notes.delete(note.id)
    assert notes.deleted()[0].marks == {"todo"}

    notes.purge(note.id)

    assert db.execute("SELECT count(*) FROM note_marks").fetchall() == [(0,)]
