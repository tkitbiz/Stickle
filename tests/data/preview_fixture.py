"""A database as the 0.1.2 preview writes it, kept to prove later versions open it.

make() wrote fixtures/preview-0.1.2.db once, with the storage code of that
release (schema version 1). The file is never changed afterwards: tests work
on a copy. To see how it was made, or to make a like one for a later release:

    uv run python tests/data/preview_fixture.py <path>

The notes are made up, and the key is a test key.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from stickle.core.layout import MAIN, SPARE, Place
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store
from stickle.data.settings import (
    DEFAULT_NOTE_COLOR,
    RECOVERY_KEY_KEPT,
    THIS_DEVICE,
    USAGE,
    Settings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "preview-0.1.2.db"
KEY = bytes(range(32))  # a test key, for this made-up database only
SCHEMA_VERSION = 1


def clock() -> str:
    return "2026-09-28T12:00:00.000Z"


@dataclass(frozen=True)
class Expected:
    body: str
    color: str = "yellow"
    hidden: bool = False
    always_on_top: bool = True
    collapsed: bool = False
    deleted: bool = False


LONG = "회의록\n" + "\n".join(f"{n}. 안건 {n}: 다음 주까지 정리하기" for n in range(1, 41))

NOTES = [
    Expected(LONG),
    Expected(
        "# 할 일\n- [ ] 장보기\n- [x] ==우유== 사기\n\n\n"
        "빈 줄 둘 다음 줄\n**굵게** *기울임* ~~취소~~",
        color="mint",
    ),
    Expected("Plain English note, pin off", color="blue", always_on_top=False),
    Expected("접어 둔 메모\n둘째 줄", color="pink", collapsed=True),
    Expected("숨긴 메모", color="lavender", hidden=True),
    Expected("지운 메모 — 휴지통에서 되살릴 수 있어야 함", color="coral", deleted=True),
]

PLACES = {
    MAIN: Place(
        monitor=1, name="DELL U2720Q", rel_x=0.1, rel_y=0.2, width=260, height=400,
        setup=("DELL U2720Q", "Built-in Retina"),
    ),
    SPARE: Place(monitor=1, name="Built-in Retina", rel_x=0.05, rel_y=0.05, width=260, height=240),
}  # fmt: skip
PLACED = 0  # the note NOTES[0] was placed on screen

DEFAULT_COLOR_SET = "mint"


def make(path: Path) -> None:
    connection = open_store(path, KEY, clock)
    notes = NoteRepository(connection, clock)
    for index, expected in enumerate(NOTES):
        note = notes.create(expected.body, expected.color)
        if not expected.always_on_top:
            notes.set_always_on_top(note.id, False)
        if expected.collapsed:
            notes.set_collapsed(note.id, True)
        if expected.hidden:
            notes.set_hidden(note.id, True)
        if expected.deleted:
            notes.delete(note.id)
        if index == PLACED:
            LayoutRepository(connection, clock).save(note.id, PLACES)
    settings = Settings(connection, clock)
    settings.set(DEFAULT_NOTE_COLOR, DEFAULT_COLOR_SET)
    settings.set(RECOVERY_KEY_KEPT, True)
    settings.set(USAGE, THIS_DEVICE)
    connection.pragma("wal_checkpoint", "TRUNCATE")
    connection.close()


if __name__ == "__main__":
    make(Path(sys.argv[1]))
