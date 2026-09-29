"""Reading and changing notes in the local database.

Deleting only marks a note, which then sits in the trash (kept 365 days).
A note is removed only when emptied from the trash, and then a deletion
record takes its place. Every change stamps the note with this device's
next change number, which never goes backwards even if the clock does.
"""

import uuid

import apsw

from stickle.core.clock import Clock, days_before, utc_now
from stickle.core.note import DEFAULT_COLOR, Note, content_hash
from stickle.data.search import search

COLUMNS = (
    "id, body, color, hidden, always_on_top, created_at, updated_at, content_hash, deleted_at,"
    " change_seq, opacity, status, label, locked, collapsed, auto_height, zoom, sleep_until,"
    " style_id"
)


class NoteNotFoundError(KeyError):
    pass


class NoteDeletedError(ValueError):
    """Deleted notes can only be restored."""


class NoteNotDeletedError(ValueError):
    """Only a note in the trash can be emptied from it."""


# Notes stay in the trash this long, and deletion records this long after emptying.
KEEP_DAYS = 365


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

    def set_always_on_top(self, note_id: str, on_top: bool) -> Note:
        note = self._require_live(note_id)
        if note.always_on_top == on_top:
            return note
        return self._change(note_id, {"always_on_top": int(on_top)})

    def set_opacity(self, note_id: str, opacity: float) -> Note:
        """How see-through the note is while another window is in use, 0.1 to 1.0."""
        if not 0.1 <= opacity <= 1.0:
            raise ValueError(f"opacity {opacity}")
        note = self._require_live(note_id)
        if note.opacity == opacity:
            return note
        return self._change(note_id, {"opacity": opacity})

    def set_locked(self, note_id: str, locked: bool) -> Note:
        """Kept where it is, as it is: moving, resizing and editing are refused."""
        note = self._require_live(note_id)
        if note.locked == locked:
            return note
        return self._change(note_id, {"locked": int(locked)})

    def set_collapsed(self, note_id: str, collapsed: bool) -> Note:
        """Folded to its title bar; its size is kept with its place (note_layouts)."""
        note = self._require_live(note_id)
        if note.collapsed == collapsed:
            return note
        return self._change(note_id, {"collapsed": int(collapsed)})

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

    def _list(self, where: str, order: str, params: tuple[str, ...] = ()) -> list[Note]:
        rows = self._db.execute(
            f"SELECT {COLUMNS} FROM notes WHERE {where} ORDER BY {order}", params
        )
        return [_note(row) for row in rows]

    def visible(self) -> list[Note]:
        return self._list("deleted_at IS NULL AND hidden = 0", "created_at, seq")

    def hidden(self) -> list[Note]:
        """Most recently changed first."""
        return self._list("deleted_at IS NULL AND hidden = 1", "change_seq DESC")

    def deleted(self) -> list[Note]:
        """The trash: most recently deleted first."""
        return self._list("deleted_at IS NOT NULL", "deleted_at DESC, change_seq DESC")

    def purge(self, note_id: str) -> None:
        """Empty a deleted note from the trash for good: only a deletion record stays.

        The note, its places on screen and its search entry go, in one transaction.
        """
        with self._db:
            note = self._require(note_id)
            if note.deleted_at is None:
                raise NoteNotDeletedError(note_id)
            self._db.execute(
                "INSERT INTO deletion_records (note_id, deleted_at, purged_at) VALUES (?, ?, ?)"
                " ON CONFLICT (note_id) DO UPDATE SET deleted_at = excluded.deleted_at,"
                " purged_at = excluded.purged_at",
                (note_id, note.deleted_at, self._clock()),
            )
            self._db.execute("DELETE FROM note_layouts WHERE note_id = ?", (note_id,))
            self._db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def empty_trash(self) -> int:
        """Purge every deleted note, all or none; how many there were."""
        notes = self.deleted()
        with self._db:
            for note in notes:
                self.purge(note.id)
        return len(notes)

    def purge_expired(self, days: int = KEEP_DAYS) -> int:
        """Purge notes in the trash longer than days, and forget deletion records
        emptied longer ago than that; how many notes were purged."""
        cutoff = days_before(self._clock(), days)
        expired = self._list("deleted_at IS NOT NULL AND deleted_at < ?", "seq", (cutoff,))
        with self._db:
            for note in expired:
                self.purge(note.id)
            self._db.execute("DELETE FROM deletion_records WHERE purged_at < ?", (cutoff,))
        return len(expired)

    def deletion_records(self) -> list[tuple[str, str, str]]:
        """(note id, deleted at, emptied at) of notes emptied from the trash."""
        rows = self._db.execute(
            "SELECT note_id, deleted_at, purged_at FROM deletion_records ORDER BY purged_at"
        )
        return [(str(a), str(b), str(c)) for a, b, c in rows]

    def live(self) -> list[Note]:
        """Every note not deleted, shown or hidden; most recently changed first."""
        return self._list("deleted_at IS NULL", "change_seq DESC")

    def matching(self, term: str) -> set[str]:
        """Ids of notes whose text contains term, in the trash or not."""
        return set(search(self._db, term))

    def last_deleted(self) -> Note | None:
        notes = self._list("deleted_at IS NOT NULL", "change_seq DESC LIMIT 1")
        return notes[0] if notes else None

    def all(self) -> list[Note]:
        """Every note, deleted ones included (export, tests)."""
        return self._list("1", "seq")
