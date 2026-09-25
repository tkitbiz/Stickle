import secrets
import tempfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path

import apsw
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stickle.data.database import KEY_BYTES, WrongKeyError, open_database
from stickle.data.schema import open_store
from stickle.data.search import search

KEY = secrets.token_bytes(KEY_BYTES)


def add(connection: apsw.Connection, note_id: str, body: str) -> None:
    """A note with a fixed id, so the search scenarios can name it."""
    with connection:
        connection.execute(
            "INSERT INTO notes (id, body, color, created_at, updated_at, content_hash,"
            " change_seq) VALUES (?, ?, 'yellow', '', '', '', 0)",
            (note_id, body),
        )


def bodies(connection: apsw.Connection) -> dict[str, str]:
    return {str(i): str(b) for i, b in connection.execute("SELECT id, body FROM notes")}


def plaintext_on_disk(folder: Path, words: list[str]) -> list[str]:
    """Words whose UTF-8 bytes appear in any file of the folder (database, WAL, ...)."""
    return [
        f"{path.name}: {word}"
        for path in folder.iterdir()
        for word in words
        if word.encode() in path.read_bytes()
    ]


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def db(folder: Path) -> Iterator[apsw.Connection]:
    connection = open_store(folder / "notes.db", KEY)
    yield connection
    connection.close()


# Invariant 1: without the key the file does not open.


def test_wrong_key_is_rejected(folder: Path, db: apsw.Connection) -> None:
    add(db, "a", "회의록을 내일까지 작성")
    db.close()

    with pytest.raises(WrongKeyError):
        open_database(folder / "notes.db", secrets.token_bytes(KEY_BYTES))


def test_opening_without_a_key_reads_nothing(folder: Path, db: apsw.Connection) -> None:
    add(db, "a", "회의록을 내일까지 작성")
    db.close()

    plain = apsw.Connection(str(folder / "notes.db"))
    with pytest.raises(apsw.NotADBError):
        plain.execute("SELECT count(*) FROM sqlite_schema").fetchall()
    plain.close()


def test_key_must_be_32_bytes(folder: Path) -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        open_database(folder / "notes.db", b"short")


# Invariant 2: nothing readable on disk, including the write-ahead log.


def test_no_plaintext_on_disk_while_open_or_after_close(folder: Path, db: apsw.Connection) -> None:
    words = ["회의록을", "내일까지", "MILK", "이모지"]
    add(db, "a", "회의록을 내일까지 작성")
    add(db, "b", "Buy MILK 이모지 😀")
    assert search(db, "회의록") == ["a"]  # the search index has been written too

    wal = folder / "notes.db-wal"
    assert wal.exists() and wal.stat().st_size > 0, "the check must cover the WAL"
    assert plaintext_on_disk(folder, words) == []
    db.close()
    assert plaintext_on_disk(folder, words) == []


def test_uses_write_ahead_logging(db: apsw.Connection) -> None:
    assert db.pragma("journal_mode") == "wal"


# Invariant 3: what is stored comes back unchanged.


def test_round_trip_after_reopening(folder: Path, db: apsw.Connection) -> None:
    notes = {"a": "회의록을 내일까지 작성", "b": "이모지 😀 와\n여러 줄", "c": ""}
    for note_id, body in notes.items():
        add(db, note_id, body)
    db.close()

    reopened = open_database(folder / "notes.db", KEY)
    assert bodies(reopened) == notes
    reopened.close()


# Agreed search scenarios.


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("회의록", ["a"]),  # a particle attached does not matter
        ("회의", ["a"]),  # two characters: below the trigram length
        ("록", ["a"]),  # one character
        ("작성", ["a"]),
        ("milk", ["b"]),  # ASCII ignores case
        ("없는말", []),
        ("", []),
        ("%", []),  # LIKE wildcards are matched literally
        ("_", []),
    ],
)
def test_search_scenarios(db: apsw.Connection, term: str, expected: list[str]) -> None:
    add(db, "a", "회의록을 내일까지 작성")
    add(db, "b", "Buy MILK")

    assert sorted(search(db, term)) == expected


def test_deleted_note_is_no_longer_found(db: apsw.Connection) -> None:
    add(db, "a", "회의록을 내일까지 작성")
    with db:
        db.execute("DELETE FROM notes WHERE id = 'a'")

    assert search(db, "회의록") == []
    assert search(db, "회의") == []


def test_edited_note_is_found_by_new_text_only(db: apsw.Connection) -> None:
    add(db, "a", "회의록을 내일까지 작성")
    with db:
        db.execute("UPDATE notes SET body = '장보기 목록' WHERE id = 'a'")

    assert search(db, "회의록") == []
    assert search(db, "장보기") == ["a"]


def test_index_survives_compaction(db: apsw.Connection) -> None:
    for i in range(20):
        add(db, f"n{i}", f"메모 {i}")
    with db:
        db.execute("DELETE FROM notes WHERE id IN ('n0', 'n1', 'n2')")
    db.execute("VACUUM")

    assert search(db, "메모 1") == [f"n{i}" for i in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19)]


def test_nul_is_refused_in_notes_and_matches_nothing(db: apsw.Connection) -> None:
    # Hypothesis found that NUL cut both the stored text and the search pattern.
    with pytest.raises(apsw.ConstraintError):
        add(db, "a", "before\x00after")
    add(db, "b", "plain")
    assert search(db, "\x00") == []


# Properties over arbitrary text (without NUL, which notes cannot contain).

PROPERTY = settings(max_examples=60, deadline=None)
# Valid UTF-8 (no lone surrogates, which Python cannot even encode) without NUL.
NOTE_CHARS = st.characters(codec="utf-8", exclude_characters="\x00")
NOTE_TEXT = st.text(alphabet=NOTE_CHARS)


@contextmanager
def fresh_database() -> Generator[tuple[apsw.Connection, Path]]:
    """A new database in its own folder, closed before the folder goes, even on failure.

    (On Windows an open database file would block the folder's removal and hide the
    real failure behind a PermissionError.)
    """
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        connection = open_store(folder / "notes.db", KEY)
        try:
            yield connection, folder
        finally:
            connection.close()


@PROPERTY
@given(NOTE_TEXT)
def test_any_text_round_trips(body: str) -> None:
    with fresh_database() as (connection, folder):
        add(connection, "a", body)
        connection.close()
        reopened = open_database(folder / "notes.db", KEY)
        try:
            assert bodies(reopened) == {"a": body}
        finally:
            reopened.close()


@PROPERTY
@given(st.text(alphabet=NOTE_CHARS, min_size=1), st.data())
def test_every_substring_finds_its_note(body: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(body) - 1))
    end = data.draw(st.integers(start + 1, len(body)))
    with fresh_database() as (connection, _):
        add(connection, "a", body)
        add(connection, "b", "unrelated")
        assert "a" in search(connection, body[start:end])


@PROPERTY
@given(st.text(alphabet=NOTE_CHARS, min_size=8).filter(lambda text: len(text.encode()) >= 16))
def test_no_text_is_readable_on_disk(body: str) -> None:
    with fresh_database() as (connection, folder):
        add(connection, "a", body)
        assert plaintext_on_disk(folder, [body]) == []


def ascii_fold(text: str) -> str:
    return "".join(c.lower() if c.isascii() else c for c in text)


@PROPERTY
@given(st.text(alphabet=NOTE_CHARS, max_size=30), st.text(min_size=1, max_size=5))
def test_search_returns_exactly_the_notes_containing_the_term(body: str, term: str) -> None:
    with fresh_database() as (connection, _):
        add(connection, "a", body)
        found = "a" in search(connection, term)
    assert found == (ascii_fold(term) in ascii_fold(body))
