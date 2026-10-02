"""Categories and marks: what a note is about, and how it is to be dealt with.

Both are independent of the note's colour. A note has at most one category
and any number of marks.
"""

from dataclasses import dataclass

# The marks every database starts with, in their order. Their names are
# translated where they are shown, until the user renames one.
BUILT_IN_MARKS = ("todo", "urgent", "important", "waiting")
# The icons a mark can have (each drawn by the app), the built-in marks' first.
MARK_ICONS = (
    *BUILT_IN_MARKS,
    "flag",
    "heart",
    "bulb",
    "person",
    "calendar",
    "home",
    "bookmark",
    "question",
)

NAME_LENGTH = 40


@dataclass(frozen=True)
class Category:
    id: str  # random UUID v4
    name: str
    color: str  # a palette key, for the dot beside the name
    position: int
    deleted_at: str | None = None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


@dataclass(frozen=True)
class Mark:
    id: str  # one of BUILT_IN_MARKS, or a random UUID v4
    name: str | None  # None: a built-in mark's own name, in the chosen language
    icon: str
    position: int
    deleted_at: str | None = None

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


def clean_name(name: str) -> str:
    """A category's or mark's name as kept: one line, no outer spaces, not too long."""
    return " ".join(name.split())[:NAME_LENGTH]
