"""Full-text search that works for Korean.

Korean attaches particles to words (회의록을, 회의록에서), so word-based
indexes miss matches. A trigram index (see schema.py) finds any substring instead. Terms
shorter than three characters cannot use the trigram index; LIKE on the same
table still answers them, by scanning, which is fast at note-collection sizes.
"""

import apsw


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
