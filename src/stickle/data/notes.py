"""Reading and changing notes in the local database.

Nothing is ever removed: deleting only marks a note (kept 365 days), and
every change stamps the note with this device's next change number, which
never goes backwards even if the clock does.
"""

import uuid

import apsw

from stickle.core.clock import Clock, utc_now
from stickle.core.note import DEFAULT_COLOR, Note, content_hash

COLUMNS = (
    "id, body, color, hidden, always_on_top, created_at, updated_at, content_hash, deleted_at,"
    " change_seq, opacity, status, label, locked, collapsed, auto_height, zoom, sleep_until,"
    " style_id"
)


class NoteNotFoundError(KeyError):
    pass


class NoteDeletedError(ValueError):
    """Deleted notes can only be restored."""


def _note(row: apsw.SQLiteValues) -> Note:
    (
        note_id,
        body,
        color,
        hidden,
        on_top,
        created,
        updated,
        digest,
        deleted,
        seq,
        opacity,
        status,
        label,
        locked,
        collapsed,
        auto_height,
        zoom,
        sleep_until,
        style_id,
    ) = row
    return Note(
        id=str(note_id),
        body=str(body),
        color=str(color),
        hidden=bool(hidden),
        always_on_top=bool(on_top),
        created_at=str(created),
        updated_at=str(updated),
        content_hash=str(digest),
        deleted_at=None if deleted is None else str(deleted),
        change_seq=int(seq),  # pyright: ignore[reportArgumentType]
        opacity=float(opacity),  # pyright: ignore[reportArgumentType]
        status=str(status),
        label=None if label is None else str(label),
        locked=bool(locked),
        collapsed=bool(collapsed),
        auto_height=bool(auto_height),
        zoom=float(zoom),  # pyright: ignore[reportArgumentType]
        sleep_until=None if sleep_until is None else str(sleep_until),
        style_id=None if style_id is None else str(style_id),
    )


class NoteRepository:
    def __init__(self, connection: apsw.Connection, clock: Clock = utc_now) -> None:
        self._db = connection
        self._clock = clock

    def _next_seq(self) -> int:
        row = self._db.execute(
            "UPDATE local_counters SET value = value + 1 WHERE key = 'change_seq' RETURNING value"
        ).fetchall()
        return int(row[0][0])  # pyright: ignore[reportArgumentType]

    def get(self, note_id: str) -> Note | None:
        rows = self._db.execute(f"SELECT {COLUMNS} FROM notes WHERE id = ?", (note_id,)).fetchall()
        return _note(rows[0]) if rows else None

    def _require(self, note_id: str) -> Note:
        note = self.get(note_id)
        if note is None:
            raise NoteNotFoundError(note_id)
        return note

    def create(self, body: str = "", color: str = DEFAULT_COLOR) -> Note:
        note_id = str(uuid.uuid4())
        now = self._clock()
        with self._db:
            self._db.execute(
                "INSERT INTO notes (id, body, color, created_at, updated_at, content_hash,"
                " change_seq) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, body, color, now, now, content_hash(body), self._next_seq()),
            )
        return self._require(note_id)

    def _change(self, note_id: str, assignments: dict[str, object]) -> Note:
        with self._db:
            self._require(note_id)
            columns = ", ".join(f"{name} = ?" for name in assignments)
            self._db.execute(
                f"UPDATE notes SET {columns}, updated_at = ?, change_seq = ? WHERE id = ?",
                (*assignments.values(), self._clock(), self._next_seq(), note_id),  # pyright: ignore[reportArgumentType]
            )
        return self._require(note_id)

    def _require_live(self, note_id: str) -> Note:
        note = self._require(note_id)
        if note.deleted:
            raise NoteDeletedError(note_id)
        return note

    def update_body(self, note_id: str, body: str) -> Note:
        note = self._require_live(note_id)
        if body == note.body:
            return note  # nothing changed: no new change number
        return self._change(note_id, {"body": body, "content_hash": content_hash(body)})

    def set_color(self, note_id: str, color: str) -> Note:
        """color is a palette key; the colours drawn are worked out from it."""
        note = self._require_live(note_id)
        if note.color == color:
            return note
        return self._change(note_id, {"color": color})

    def set_hidden(self, note_id: str, hidden: bool) -> Note:
        note = self._require_live(note_id)
        if note.hidden == hidden:
            return note
        return self._change(note_id, {"hidden": int(hidden)})

    def delete(self, note_id: str) -> Note:
        self._require_live(note_id)
        return self._change(note_id, {"deleted_at": self._clock()})

    def restore(self, note_id: str) -> Note:
        note = self._require(note_id)
        if not note.deleted:
            return note
        return self._change(note_id, {"deleted_at": None})

    def _list(self, where: str, order: str) -> list[Note]:
        rows = self._db.execute(f"SELECT {COLUMNS} FROM notes WHERE {where} ORDER BY {order}")
        return [_note(row) for row in rows]

    def visible(self) -> list[Note]:
        return self._list("deleted_at IS NULL AND hidden = 0", "created_at, seq")

    def hidden(self) -> list[Note]:
        """Most recently changed first."""
        return self._list("deleted_at IS NULL AND hidden = 1", "change_seq DESC")

    def last_deleted(self) -> Note | None:
        notes = self._list("deleted_at IS NOT NULL", "change_seq DESC LIMIT 1")
        return notes[0] if notes else None

    def all(self) -> list[Note]:
        """Every note, deleted ones included (export, tests)."""
        return self._list("1", "seq")
