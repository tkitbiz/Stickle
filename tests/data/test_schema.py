import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest

from stickle.data import schema
from stickle.data.database import KEY_BYTES, open_database
from stickle.data.notes import NoteRepository
from stickle.data.schema import (
    BACKUPS_KEPT,
    V1,
    MigrationError,
    NewerSchemaError,
    backup,
    open_store,
    schema_version,
)

KEY = secrets.token_bytes(KEY_BYTES)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "notes.db"


def ticking_clock() -> Iterator[str]:
    for second in range(60):
        yield f"2026-09-26T10:00:{second:02d}.000Z"
    raise AssertionError("clock ran out")


def make_v1(path: Path, bodies: list[str]) -> list[str]:
    connection = open_store(path, KEY)
    ids = [NoteRepository(connection).create(body).id for body in bodies]
    connection.close()
    return ids


def bodies(path: Path) -> dict[str, str]:
    connection = open_database(path, KEY)
    try:
        return {note.id: note.body for note in NoteRepository(connection).all()}
    finally:
        connection.close()


def version_of(path: Path) -> int:
    connection = open_database(path, KEY)
    try:
        return schema_version(connection)
    finally:
        connection.close()


def leftovers(path: Path) -> list[str]:
    return sorted(p.name for p in path.parent.glob("*.migrating*"))


def backups(path: Path) -> list[Path]:
    return sorted((path.parent / "backups").glob("*.db"))


def test_new_database_reaches_the_latest_version_without_a_backup(path: Path) -> None:
    connection = open_store(path, KEY)
    assert schema_version(connection) == schema.latest_version()
    connection.close()
    assert backups(path) == []
    assert leftovers(path) == []


def test_opening_the_latest_version_changes_nothing(path: Path) -> None:
    ids = make_v1(path, ["회의록", "장보기"])
    connection = open_store(path, KEY)
    connection.close()
    assert set(bodies(path)) == set(ids)
    assert backups(path) == []


def test_upgrade_keeps_notes_and_leaves_a_backup(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_v1(path, ["회의록을 내일까지", "😀 여러\n줄"])
    before = bodies(path)
    monkeypatch.setattr(schema, "MIGRATIONS", [V1, "ALTER TABLE notes ADD COLUMN extra TEXT"])

    connection = open_store(path, KEY)
    assert schema_version(connection) == 2
    connection.close()

    assert bodies(path) == before
    assert len(backups(path)) == 1
    assert version_of(backups(path)[0]) == 1  # the backup still opens with the old app
    assert leftovers(path) == []


def test_failed_step_stays_at_the_last_good_version(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_v1(path, ["회의록"])
    before = bodies(path)
    broken = "ALTER TABLE notes ADD COLUMN extra TEXT; SELECT no_such_function();"
    monkeypatch.setattr(schema, "MIGRATIONS", [V1, broken])

    with pytest.raises(MigrationError):
        open_store(path, KEY)

    assert version_of(path) == 1
    assert bodies(path) == before
    assert leftovers(path) == []


def test_fixed_app_continues_from_the_last_good_version(
    path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_v1(path, ["회의록"])
    before = bodies(path)
    monkeypatch.setattr(schema, "MIGRATIONS", [V1, "SELECT no_such_function();"])
    with pytest.raises(MigrationError):
        open_store(path, KEY)

    monkeypatch.setattr(schema, "MIGRATIONS", [V1, "ALTER TABLE notes ADD COLUMN extra TEXT"])
    connection = open_store(path, KEY)
    assert schema_version(connection) == 2
    connection.close()
    assert bodies(path) == before


def test_migration_that_loses_notes_is_refused(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_v1(path, ["회의록", "장보기"])
    before = bodies(path)
    monkeypatch.setattr(schema, "MIGRATIONS", [V1, "DELETE FROM notes WHERE body = '장보기'"])

    with pytest.raises(MigrationError):
        open_store(path, KEY)

    assert version_of(path) == 1
    assert bodies(path) == before


def test_migration_that_alters_text_is_refused(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_v1(path, ["회의록"])
    monkeypatch.setattr(schema, "MIGRATIONS", [V1, "UPDATE notes SET body = trim(body, '록')"])

    with pytest.raises(MigrationError):
        open_store(path, KEY)
    assert list(bodies(path).values()) == ["회의록"]


def test_several_steps_run_in_order(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_v1(path, ["회의록"])
    steps = [
        V1,
        "CREATE TABLE step2 (n INTEGER)",
        "INSERT INTO step2 VALUES (3)",  # fails unless step 2 ran first
    ]
    monkeypatch.setattr(schema, "MIGRATIONS", steps)

    connection = open_store(path, KEY)
    assert schema_version(connection) == 3
    assert connection.execute("SELECT n FROM step2").fetchall() == [(3,)]
    connection.close()
    assert len(backups(path)) == 1  # one backup per upgrade, not per step


def test_newer_database_is_refused_and_left_untouched(path: Path) -> None:
    make_v1(path, ["회의록"])
    connection = open_database(path, KEY)
    connection.pragma("user_version", 99)
    connection.close()
    data = path.read_bytes()

    with pytest.raises(NewerSchemaError):
        open_store(path, KEY)
    assert path.read_bytes() == data
    assert backups(path) == []


def test_only_the_newest_backups_are_kept(path: Path) -> None:
    make_v1(path, ["회의록"])
    clock = ticking_clock()
    made = [backup(path, 1, lambda: next(clock)) for _ in range(BACKUPS_KEPT + 2)]

    assert backups(path) == made[-BACKUPS_KEPT:]


def test_backup_is_encrypted_and_opens_with_the_same_key(path: Path) -> None:
    make_v1(path, ["회의록을 내일까지"])
    copy = backup(path, 1)

    assert "회의록".encode() not in copy.read_bytes()
    plain = apsw.Connection(str(copy))
    with pytest.raises(apsw.NotADBError):
        plain.execute("SELECT count(*) FROM sqlite_schema").fetchall()
    plain.close()
    assert list(bodies(copy).values()) == ["회의록을 내일까지"]
