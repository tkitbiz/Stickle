"""Storing where notes are on screen."""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest

from stickle.core.layout import MAIN, SPARE, Place
from stickle.data.database import KEY_BYTES
from stickle.data.layouts import LayoutRepository
from stickle.data.schema import open_store

KEY = secrets.token_bytes(KEY_BYTES)
PLACE = Place(2, "DELL U2720Q: HDMI-1", 0.25, 0.5, 260, 240, ("ELDTV", "DELL U2720Q: HDMI-1"))


@pytest.fixture
def db(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


def test_places_are_stored_and_read_back(db: apsw.Connection) -> None:
    layouts = LayoutRepository(db)
    spare = Place(1, "ELDTV", 0.1, 0.1, 260, 240, ("ELDTV",))

    layouts.save("note", {MAIN: PLACE, SPARE: spare})

    assert layouts.places("note") == {MAIN: PLACE, SPARE: spare}
    assert layouts.places("other") == {}


def test_saving_again_replaces_the_place(db: apsw.Connection) -> None:
    layouts = LayoutRepository(db)
    layouts.save("note", {MAIN: PLACE})
    moved = Place(1, "ELDTV", 0.7, 0.2, 300, 200, ("ELDTV",))

    layouts.save("note", {MAIN: moved})

    assert layouts.places("note") == {MAIN: moved}


@pytest.mark.parametrize(
    ("monitor_key", "values"),
    [
        ("not json", (0.1, 0.1, 260, 240)),
        ('{"number": "2", "name": "", "setup": []}', (0.1, 0.1, 260, 240)),
        ('{"number": true, "name": "", "setup": []}', (0.1, 0.1, 260, 240)),
        ('{"number": 1, "name": "", "setup": [3]}', (0.1, 0.1, 260, 240)),
        ('{"number": 1, "name": "", "setup": []}', (0.1, 0.1, -20, 240)),
        ('{"number": 1, "name": "", "setup": []}', ("x", 0.1, 260, 240)),
        ('{"number": 1, "name": "", "setup": []}', (1e308 * 10, 0.1, 260, 240)),
    ],
)
def test_rows_that_make_no_sense_are_ignored(
    db: apsw.Connection, monitor_key: str, values: tuple[object, ...]
) -> None:
    db.execute(
        "INSERT INTO note_layouts VALUES ('note', 'main', ?, ?, ?, ?, ?, '2026-09-26')",
        (monitor_key, *values),  # pyright: ignore[reportArgumentType]
    )

    assert LayoutRepository(db).places("note") == {}


def test_unknown_kinds_of_place_are_ignored(db: apsw.Connection) -> None:
    layouts = LayoutRepository(db)
    layouts.save("note", {MAIN: PLACE})
    db.execute("UPDATE note_layouts SET config_key = 'from-a-newer-version'")

    assert layouts.places("note") == {}
