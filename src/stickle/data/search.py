"""Full-text search that works for Korean.

Korean attaches particles to words (회의록을, 회의록에서), so word-based
indexes miss matches. A trigram index finds any substring instead. Terms
shorter than three characters cannot use the trigram index; LIKE on the same
table still answers them, by scanning, which is fast at note-collection sizes.
"""

import apsw

SCHEMA = """
-- seq is the index's link to the note. An explicit INTEGER PRIMARY KEY, because
-- implicit rowids may be renumbered by VACUUM, which would scramble the index.
CREATE TABLE IF NOT EXISTS notes (
    seq INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    -- NUL ends strings inside SQLite's text functions, which would hide the rest of
    -- the note from search. It is never meaningful in a note, so it is refused here;
    -- the editor and importers remove it before saving.
    body TEXT NOT NULL CHECK (instr(body, char(0)) = 0)
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    body, tokenize = 'trigram', content = 'notes', content_rowid = 'seq'
);
-- Keep the index in step with the notes, whoever changes them.
CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, body) VALUES (new.seq, new.body);
END;
CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.seq, old.body);
END;
CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE OF body ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, body) VALUES ('delete', old.seq, old.body);
    INSERT INTO notes_fts(rowid, body) VALUES (new.seq, new.body);
END;
"""


def create_schema(connection: apsw.Connection) -> None:
    with connection:
        connection.execute(SCHEMA)


def search(connection: apsw.Connection, term: str) -> list[str]:
    """Ids of notes containing term, in no particular order.

    ASCII letters ignore case; other scripts match case exactly (é is not É).
    Korean has no case. Accented languages would need a case-folded column.
    """
    if not term or "\x00" in term:  # notes never contain NUL (see the schema)
        return []
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = connection.execute(
        "SELECT notes.id FROM notes_fts JOIN notes ON notes.seq = notes_fts.rowid"
        " WHERE notes_fts.body LIKE ? ESCAPE '\\'",
        (f"%{escaped}%",),
    )
    return [str(row[0]) for row in rows]
