"""Parsing notes: CommonMark, ==highlight==, task items, and finding a shown point in the text."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from markdown_it.tree import SyntaxTreeNode

from stickle.core.markdown import LINE_SEPARATOR, note_title, parse, source_position, task_box


def kinds(node: SyntaxTreeNode) -> list[str]:
    """Every node type, depth first."""
    found = [node.type]
    for child in node.children:
        found += kinds(child)
    return found


def texts(node: SyntaxTreeNode) -> str:
    if node.type == "text":
        return node.content
    return "".join(texts(child) for child in node.children)


def test_highlight_is_a_format_of_its_own() -> None:
    tree = parse("a ==marked **and bold**== b")

    assert kinds(tree).count("mark") == 1
    assert "strong" in kinds(tree)
    assert texts(tree) == "a marked and bold b"


def test_lone_or_spaced_equals_signs_stay_text() -> None:
    for text in ("a == b", "==open only", "x = 1", "==", "=single="):
        tree = parse(text)
        assert "mark" not in kinds(tree), text
        assert texts(tree) == text


def test_strikethrough_takes_two_tildes() -> None:
    tree = parse("사야 할 것 ~~우유~~ 빵")

    assert kinds(tree).count("s") == 1
    assert texts(tree) == "사야 할 것 우유 빵"
    for text in ("a ~ b", "~one~", "~~open only", "`~~code~~`"):
        assert "s" not in kinds(parse(text)), text


def test_highlight_next_to_korean() -> None:
    tree = parse("오늘==중요==합니다")

    assert "mark" in kinds(tree)
    assert texts(tree) == "오늘중요합니다"


def test_task_items_know_whether_they_are_checked() -> None:
    tree = parse("- [ ] to do\n- [x] done\n- [X] also done\n- plain")

    items = tree.children[0].children
    assert [item.meta.get("checked") for item in items] == [False, True, True, None]
    assert texts(items[0]) == "to do"
    assert texts(items[3]) == "plain"


def test_an_empty_task_item_is_still_a_task() -> None:
    item = parse("- [ ]").children[0].children[0]

    assert item.meta.get("checked") is False


def test_brackets_outside_a_list_are_text() -> None:
    tree = parse("[ ] not a task")

    assert texts(tree) == "[ ] not a task"


def test_html_is_shown_as_typed() -> None:
    tree = parse("<b>bold?</b> <script>x</script>")

    assert "html_inline" not in kinds(tree)
    assert "html_block" not in kinds(tree)
    assert texts(tree) == "<b>bold?</b> <script>x</script>"


def test_blocks_know_their_lines() -> None:
    tree = parse("# Title\n\nline one\nline two\n")

    heading, paragraph = tree.children
    assert heading.map == (0, 1)
    assert paragraph.map == (2, 4)


# Finding a point of the formatted note in the text


def test_point_after_bold_text_is_found_past_its_markup() -> None:
    source = "some **bold** words"
    # Shown as "some bold words", the point is just after "bold".
    position = source_position(source, 0, 0, "some bold", " words")

    assert source[:position] == "some **bold"


def test_point_is_found_in_its_own_block() -> None:
    source = "same\n\nsame"
    position = source_position(source, 2, 2, "sa", "me")

    assert position == len("same\n\nsa")


def test_point_in_a_repeated_word_takes_the_nearest() -> None:
    source = "ab ab ab ab"
    position = source_position(source, 0, 0, "ab ab ab", " ab")

    assert position == len("ab ab ab")


def test_shown_line_breaks_match_the_text() -> None:
    source = "first\nsecond line"
    position = source_position(source, 0, 1, f"first{LINE_SEPARATOR}sec", "ond line")

    assert position == len("first\nsec")


def test_empty_block_maps_to_its_line() -> None:
    source = "a\n\nb"

    assert source_position(source, 1, 1, "", "") == 2


@given(st.text(alphabet=st.characters(exclude_characters="\n" + LINE_SEPARATOR)), st.data())
def test_point_in_unformatted_text_is_exact(line: str, data: st.DataObject) -> None:
    split = data.draw(st.integers(0, len(line)))

    assert source_position(line, 0, 0, line[:split], line[split:]) == split


@given(st.text(), st.text(), st.text(), st.integers(0, 5), st.integers(0, 5))
def test_point_always_lies_within_the_block(
    source: str, before: str, after: str, first: int, extra: int
) -> None:
    lines = source.split("\n")
    first = min(first, len(lines) - 1)
    last = min(first + extra, len(lines) - 1)
    start = sum(len(line) + 1 for line in lines[:first])
    end = start + len("\n".join(lines[first : last + 1]))

    assert start <= source_position(source, first, last, before, after) <= end


# Toggling a task item's checkbox in the text


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- [ ] milk", (3, "x")),
        ("- [x] milk", (3, " ")),
        ("- [X] milk", (3, " ")),
        ("* [ ]", (3, "x")),
        ("  12. [x] nested", (7, " ")),
        ("3) [ ] ordered", (4, "x")),
        ("> - [ ] quoted", (5, "x")),
        ("> > + [x] twice quoted", (7, " ")),
    ],
)
def test_task_box_is_found(line: str, expected: tuple[int, str]) -> None:
    assert task_box(line) == expected


@pytest.mark.parametrize("line", ["plain [ ] text", "- [] no space", "-[ ] no gap", "- [y] other"])
def test_other_lines_have_no_box(line: str) -> None:
    assert task_box(line) is None


@given(
    st.sampled_from(["", "  ", "> ", "> > "]),
    st.sampled_from(["-", "*", "+", "1.", "10)"]),
    st.sampled_from([" ", "x", "X"]),
    st.text(),
)
def test_toggling_changes_one_character_and_twice_restores(
    prefix: str, marker: str, mark: str, rest: str
) -> None:
    line = f"{prefix}{marker} [{mark}] {rest}"
    column, replacement = task_box(line) or (-1, "")
    toggled = line[:column] + replacement + line[column + 1 :]

    assert column == line.index("[") + 1
    assert (replacement == " ") == (mark != " ")
    again = task_box(toggled)
    assert again is not None
    assert toggled[: again[0]] + again[1] + toggled[again[0] + 1 :] in (
        line,
        line.replace("[X]", "[x]"),
    )


# A note's title: its first line with text, without Markdown marks


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("# **Shopping**\nmilk", "Shopping"),
        ("\n\n  - [ ] buy *milk*", "buy milk"),
        ("---\n- [x]\n> ==important== [link](https://example.com) `code`", "important link code"),
        ("<b>raw</b> stays", "<b>raw</b> stays"),
        ("![a cat](cat.png)", "a cat"),
        ("  lots   of\tspace  ", "lots of space"),
        ("", ""),
        ("   \n\n", ""),
    ],
)
def test_note_title(text: str, title: str) -> None:
    assert note_title(text) == title


@given(st.text())
def test_a_title_is_one_line_of_text(text: str) -> None:
    title = note_title(text)

    assert "\n" not in title
    assert title == title.strip()
