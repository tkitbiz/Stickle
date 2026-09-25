"""The local database layout and how it is upgraded.

Each schema version is reached in its own step. A step is applied to a copy
of the database, the copy is checked (SQLite integrity, every note and its
text still there, search index consistent), and only then does it replace
the original. A failed step leaves the database at the last good version,
so a fixed app can continue from there. Before upgrading, a backup copy is
kept (the newest few): restoring it is the way back to an older app, which
refuses a database newer than itself.
"""

import hashlib
import shutil
from pathlib import Path

import apsw

from stickle.core.clock import Clock, utc_now
from stickle.data.database import open_database

V1 = """
-- seq is the search index's link to the note. An explicit INTEGER PRIMARY KEY,
-- because implicit rowids may be renumbered by VACUUM, which would scramble the index.
CREATE TABLE notes (
    seq INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    -- NUL ends strings inside SQLite's text functions, which would hide the rest of
    -- the note from search. It is never meaningful in a note, so it is refused here;
    -- the editor and importers remove it before saving.
    body TEXT NOT NULL CHECK (instr(body, char(0)) = 0),
    color TEXT NOT NULL,
    opacity REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    label TEXT,
    always_on_top INTEGER NOT NULL DEFAULT 1,
    locked INTEGER NOT NULL DEFAULT 0,
    collapsed INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    auto_height INTEGER NOT NULL DEFAULT 0,
    zoom REAL NOT NULL DEFAULT 1.0,
    sleep_until TEXT,
    style_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    deleted_at TEXT,
    change_seq INTEGER NOT NULL
);
CREATE VIRTUAL TABLE notes_fts USING fts5(
    body, tokenize = 'trigram', content = 'notes', content_rowid = 'seq'
);
-- Keep the index in step with the notes, whoever changes them.
CREATE TRIGGER notes_fts_insert AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, body) VALUES (new.seq, new.body);
END;
CREATE TRIGGER notes_fts_delete AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.seq, old.body);
END;
CREATE TRIGGER notes_fts_update AFTER UPDATE OF body ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.seq, old.body);
    INSERT INTO notes_fts(rowid, body) VALUES (new.seq, new.body);
END;

-- Window position per monitor configuration, as fractions of the monitor.
CREATE TABLE note_layouts (
    note_id TEXT NOT NULL,
    config_key TEXT NOT NULL,
    monitor_key TEXT NOT NULL,
    rel_x REAL NOT NULL,
    rel_y REAL NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (note_id, config_key)
);

-- Settings for this device only (language, autostart, ...).
CREATE TABLE device_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Settings that will follow the user to every device once sync exists.
CREATE TABLE shared_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);
-- Counters of this device, such as the change sequence.
CREATE TABLE local_counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT INTO local_counters (key, value) VALUES ('change_seq', 0);
"""

# MIGRATIONS[n] brings the database from version n to version n + 1.
MIGRATIONS: list[str] = [V1]
BACKUPS_KEPT = 3


class NewerSchemaError(Exception):
    """The database was written by a newer version of the app."""


class MigrationError(Exception):
    """A step failed; the database stays at the last good version."""


def latest_version() -> int:
    return len(MIGRATIONS)


def schema_version(connection: apsw.Connection) -> int:
    return int(connection.pragma("user_version"))


def open_store(path: Path, key: bytes, clock: Clock = utc_now) -> apsw.Connection:
    """Open the database at the current schema version, upgrading it if needed."""
    connection = open_database(path, key)
    version = schema_version(connection)
    if version > latest_version():
        connection.close()
        raise NewerSchemaError(f"database version {version}, app knows {latest_version()}")
    if version == latest_version():
        return connection
    connection.pragma("wal_checkpoint", "TRUNCATE")
    connection.close()
    if version > 0:  # a new, empty database has nothing to keep
        backup(path, version, clock)
    for target in range(version + 1, latest_version() + 1):
        _migrate_step(path, key, target)
    return open_database(path, key)


def backup(path: Path, version: int, clock: Clock = utc_now) -> Path:
    """Copy the (encrypted) database aside, keeping the newest few copies."""
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    # The time comes first so that names sort oldest to newest. (File times would not
    # do: copies can keep the original's time.)
    stamp = clock().replace(":", "").replace("-", "")
    target = folder / f"{path.stem}-{stamp}-v{version}.db"
    shutil.copyfile(path, target)
    copies = sorted(folder.glob(f"{path.stem}-*-v*.db"))
    for old in copies[:-BACKUPS_KEPT]:
        old.unlink()
    return target


def _sidecars(path: Path) -> list[Path]:
    return [path.with_name(path.name + suffix) for suffix in ("-wal", "-shm")]


def _remove(path: Path) -> None:
    for file in [path, *_sidecars(path)]:
        file.unlink(missing_ok=True)


def _notes_fingerprint(connection: apsw.Connection) -> tuple[int, str] | None:
    tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_schema")}
    if "notes" not in tables:
        return None
    digest = hashlib.sha256()
    count = 0
    for note_id, body in connection.execute("SELECT id, body FROM notes ORDER BY id"):
        digest.update(f"{note_id}\0{body}\0".encode())
        count += 1
    return count, digest.hexdigest()


def _verify(connection: apsw.Connection, before: tuple[int, str] | None) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchall()
    if result != [("ok",)]:
        raise MigrationError(f"integrity check failed: {result[:3]}")
    if before is not None and _notes_fingerprint(connection) != before:
        raise MigrationError("notes changed during the migration")
    # Raises if the search index no longer matches the notes.
    connection.execute("INSERT INTO notes_fts(notes_fts) VALUES ('integrity-check')")


def _migrate_step(path: Path, key: bytes, target: int) -> None:
    work = path.with_name(path.name + ".migrating")
    _remove(work)
    shutil.copy2(path, work)
    try:
        connection = open_database(work, key)
        try:
            before = _notes_fingerprint(connection)
            with connection:
                connection.execute(MIGRATIONS[target - 1])
                connection.pragma("user_version", target)
            _verify(connection, before)
            connection.pragma("wal_checkpoint", "TRUNCATE")
        finally:
            connection.close()
    except Exception as error:
        _remove(work)
        raise MigrationError(f"upgrade to version {target} failed") from error
    # The original was checkpointed and closed: its sidecar files are empty, and a
    # stale write-ahead log must not be replayed onto the new file.
    for sidecar in _sidecars(path):
        sidecar.unlink(missing_ok=True)
    work.replace(path)
