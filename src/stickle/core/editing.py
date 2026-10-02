"""Help with lists while editing a note's Markdown: what a key does to its line.

Each function looks at the line the cursor is in (and the lines above it) and
returns the change to make, or None to let the key do what it always does.
They work on text, not on any editor, so every case can be tried in tests.

- Enter at the end of (or within) a list item starts another item like it:
  the next number, an empty checkbox for a checkbox. On an item with nothing
  in it, Enter moves it out a level, or ends the list at the outermost one,
  with a blank line after it.
- Tab and Shift+Tab move a list item in or out a level, by as much as Markdown
  needs to nest it under the item above.
- Enter after an opening code fence ("```", "```python") closes it below, unless
  a fence below already does.
- Typing "]" after "[" makes a checkbox: "- []" becomes "- [ ]", and "[]" at
  the start of a line becomes "- [ ] ".

Nothing happens inside a fenced code block.
"""

import re
from dataclasses import dataclass

ITEM = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|(?P<number>\d{1,9})(?P<delimiter>[.)]))"
    r"(?P<space> +|$)(?P<box>\[[ xX]\] ?)?"
)
FENCE = re.compile(r"^ {0,3}(```|~~~)")


@dataclass(frozen=True)
class Change:
    """The cursor's line replaced by text (which may hold a new line), and where
    the cursor goes, as an index into that text."""

    text: str
    cursor: int


@dataclass(frozen=True)
class Item:
    indent: str
    marker: str  # "-", or "3." with its number
    number: int | None
    delimiter: str
    space: str
    box: str  # "[ ] ", "[x] " or ""
    content: int  # where the item's text starts in the line

    @property
    def nesting(self) -> int:
        """How far in an item must be to sit under this one (its text's column,
        not counting a checkbox, which is part of the text for Markdown)."""
        return len(self.indent) + len(self.marker) + max(1, len(self.space))


def item(line: str) -> Item | None:
    match = ITEM.match(line)
    if match is None:
        return None
    number = match.group("number")
    space = match.group("space")
    box = match.group("box") or ""
    if box and not space:
        return None  # "-[ ]" is not a list item
    if box and not box.endswith(" "):
        box += " "  # "- [ ]" at the end of the line
    return Item(
        indent=match.group("indent"),
        marker=match.group("marker"),
        number=int(number) if number else None,
        delimiter=match.group("delimiter") or "",
        space=space,
        box=box,
        content=match.end(),
    )


def in_code_block(lines_before: list[str], line: str) -> bool:
    """Whether line, which follows lines_before, is in a fenced code block (or
    is one of its fences)."""
    if FENCE.match(line):
        return True
    return sum(1 for before in lines_before if FENCE.match(before)) % 2 == 1


def _next_marker(found: Item) -> str:
    if found.number is None:
        return found.marker
    return f"{found.number + 1}{found.delimiter}"


def _parent_indent(lines_before: list[str], indent: str) -> str:
    """The indent of the nearest list item above that holds an item this far in."""
    for line in reversed(lines_before):
        above = item(line)
        if above is not None and len(above.indent) < len(indent):
            return above.indent
    return ""


def on_enter(
    lines_before: list[str], line: str, column: int, lines_after: list[str] | None = None
) -> Change | None:
    """Enter with the cursor at column of line (lines_after: the lines below it)."""
    fence = FENCE.match(line)
    if fence is not None and column == len(line):
        opening = sum(1 for before in lines_before if FENCE.match(before)) % 2 == 0
        closed = any(FENCE.match(after) for after in lines_after or [])
        if opening and not closed:
            # Closed at once, so that the rest of the note is not taken for code.
            indent = line[: fence.start(1)]
            return Change(f"{line}\n\n{indent}{fence.group(1)}", len(line) + 1)
        return None
    found = item(line)
    if found is None or in_code_block(lines_before, line):
        return None
    if column < found.content:
        return None  # in the marker: an ordinary new line above the item
    if not line[found.content :].strip():
        if not found.space:
            return None  # "1." or "2026." alone: perhaps not a list at all, so kept
        if found.indent:
            # Out a level, as Shift+Tab would, numbered on from the list it joins.
            indent = _parent_indent(lines_before, found.indent)
            rest = line.lstrip(" \t")
            joined = next(
                (i for i in map(item, reversed(lines_before)) if i and i.indent == indent),
                None,
            )
            if found.number is not None and joined is not None and joined.number is not None:
                rest = f"{_next_marker(joined)}{line[len(found.indent) + len(found.marker) :]}"
            outdented = indent + rest
            return Change(outdented, len(outdented))
        # The list ends here, with a blank line after it: a line right below an
        # item would be read as more of that item.
        return Change("\n", 1)
    box = "[ ] " if found.box else ""
    space = found.space or " "
    prefix = f"{found.indent}{_next_marker(found)}{space}{box}"
    before, after = line[:column].rstrip(" "), line[column:].lstrip(" ")
    return Change(f"{before}\n{prefix}{after}", len(before) + 1 + len(prefix))


def on_tab(lines_before: list[str], line: str, column: int, back: bool) -> Change | None:
    """Tab (or Shift+Tab, back) on a list item: in or out a level. None for any
    other line, where the key does what it always does."""
    found = item(line)
    if found is None or in_code_block(lines_before, line):
        return None
    if back:
        new_indent = _parent_indent(lines_before, found.indent) if found.indent else ""
    else:
        sibling = next(
            (
                above
                for above in map(item, reversed(lines_before))
                if above is not None and len(above.indent) <= len(found.indent)
            ),
            None,
        )
        if sibling is None or len(sibling.indent) < len(found.indent):
            return Change(line, column)  # nothing above to go under: as it is
        new_indent = " " * sibling.nesting
    moved = new_indent + line[len(found.indent) :]
    return Change(moved, max(len(new_indent), column + len(new_indent) - len(found.indent)))


def on_close_bracket(lines_before: list[str], line: str, column: int) -> Change | None:
    """ "]" typed at column: a checkbox, where "[" was typed just before it."""
    if in_code_block(lines_before, line) or column == 0 or line[column - 1] != "[":
        return None
    before, after = line[: column - 1], line[column:]
    if not before.strip():
        prefix = f"{before}- [ ] "
    else:
        found = item(before + "x")
        if found is None or found.box or found.content != len(before):
            return None
        prefix = f"{before}[ ] "
    return Change(prefix + after.lstrip(" "), len(prefix))
