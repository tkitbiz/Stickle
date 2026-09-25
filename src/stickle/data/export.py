"""Copy notes out as Markdown files, from a database of any version.

This is the way out when the app cannot use a database (an update failed, or
it was saved by a newer version): it reads only the note id and text, which
every version has, and never changes the database. Each note becomes one
file named after its first line; deleted notes go into a "deleted" folder.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import apsw

from stickle.core.clock import Clock, utc_now
from stickle.data.database import open_database
from stickle.data.schema import first_line

# Not allowed in file names on Windows (the strictest of the three systems).
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
NAME_LENGTH = 50


class ExportError(Exception):
    """The database has no notes this app can read."""


@dataclass(frozen=True)
class ExportResult:
    folder: Path
    notes: int
    deleted: int


def file_stem(body: str, note_id: str) -> str:
    title = " ".join(_UNSAFE.sub(" ", first_line(body)).split())[:NAME_LENGTH]
    title = title.rstrip(". ") or "note"
    # Part of the id keeps names unique and never a reserved name such as CON.
    suffix = _UNSAFE.sub("", note_id)[:8]
    return f"{title} ({suffix})" if suffix else title


def _rows(connection: apsw.Connection) -> list[tuple[str, str, bool]]:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(notes)")}
    if not {"id", "body"} <= columns:
        raise ExportError("no notes table")
    deleted = "deleted_at IS NOT NULL" if "deleted_at" in columns else "0"
    query = f"SELECT id, body, {deleted} FROM notes"
    return [(str(i), str(b), bool(d)) for i, b, d in connection.execute(query)]


def _free(path: Path) -> Path:
    candidate, number = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} {number}{path.suffix}")
        number += 1
    return candidate


def export_markdown(
    database: Path, key: bytes, target: Path, clock: Clock = utc_now
) -> ExportResult:
    """Write every note into a new folder inside target; nothing is overwritten."""
    connection = open_database(database, key)
    try:
        rows = _rows(connection)
    finally:
        connection.close()
    stamp = clock()[:19].replace(":", "").replace("-", "")
    folder = _free(target / f"Stickle notes {stamp}")
    folder.mkdir(parents=True)
    deleted_count = 0
    for note_id, body, deleted in rows:
        place = folder / "deleted" if deleted else folder
        place.mkdir(exist_ok=True)
        path = _free(place / f"{file_stem(body, note_id)}.md")
        # newline="" keeps the text exactly as stored.
        with path.open("x", encoding="utf-8", newline="") as file:
            file.write(body)
        deleted_count += deleted
    return ExportResult(folder, len(rows) - deleted_count, deleted_count)
