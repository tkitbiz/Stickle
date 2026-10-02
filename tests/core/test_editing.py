from hypothesis import given
from hypothesis import strategies as st

from stickle.core.editing import Change, on_close_bracket, on_enter, on_tab


def enter(line: str, before: list[str] | None = None, column: int | None = None) -> Change | None:
    return on_enter(before or [], line, len(line) if column is None else column)


# Enter


def test_enter_continues_a_list() -> None:
    assert enter("- 우유") == Change("- 우유\n- ", 7)
    assert enter("* a") == Change("* a\n* ", 6)
    assert enter("  - nested") == Change("  - nested\n  - ", 15)


def test_enter_gives_the_next_number() -> None:
    assert enter("3. 셋째") == Change("3. 셋째\n4. ", 9)
    assert enter("9) x") == Change("9) x\n10) ", 9)


def test_enter_gives_an_empty_checkbox() -> None:
    assert enter("- [ ] 우유").text == "- [ ] 우유\n- [ ] "  # pyright: ignore[reportOptionalMemberAccess]
    assert enter("- [x] 끝난 일").text == "- [x] 끝난 일\n- [ ] "  # pyright: ignore[reportOptionalMemberAccess]


def test_enter_within_an_item_moves_the_rest_to_a_new_one() -> None:
    assert enter("- 우유두부", column=4) == Change("- 우유\n- 두부", 7)


def test_enter_on_an_empty_item_ends_the_list() -> None:
    # A blank line after the list: a line right below an item would join it.
    assert enter("- ") == Change("\n", 1)
    assert enter("- [ ] ") == Change("\n", 1)
    assert enter("2. ") == Change("\n", 1)


def test_enter_on_an_empty_nested_item_moves_it_out() -> None:
    assert enter("  - [ ] ", ["- [ ] a"]) == Change("- [ ] ", 6)
    assert enter("     - ", ["1. a", "   - b"]) == Change("   - ", 5)


def test_enter_elsewhere_is_left_alone() -> None:
    assert enter("plain text") is None
    assert enter("-no space") is None
    assert enter("- item", column=0) is None  # before the marker: a line above
    assert enter("- item", ["```"]) is None  # in a code block
    assert enter("- item", ["```", "x", "```"]) is not None  # after one


# Tab


def test_tab_nests_under_the_item_above() -> None:
    assert on_tab(["- [ ] a"], "- [ ] b", 7, back=False) == Change("  - [ ] b", 9)
    assert on_tab(["1. a"], "2. b", 4, back=False) == Change("   2. b", 7)


def test_tab_goes_no_deeper_than_one_level_below_the_item_above() -> None:
    assert on_tab(["- a", "  - b"], "  - c", 5, back=False) == Change("    - c", 7)
    assert on_tab(["- a"], "  - b", 5, back=False) == Change("  - b", 5)  # already under a
    assert on_tab([], "- first", 7, back=False) == Change("- first", 7)


def test_shift_tab_moves_out_to_the_parent() -> None:
    assert on_tab(["- a", "  - b"], "    - c", 7, back=True) == Change("  - c", 5)
    assert on_tab(["- a"], "  - b", 0, back=True) == Change("- b", 0)
    assert on_tab([], "- a", 3, back=True) == Change("- a", 3)


def test_tab_elsewhere_is_left_alone() -> None:
    assert on_tab([], "plain", 2, back=False) is None
    assert on_tab(["```"], "- a", 3, back=False) is None


# "[]"


def test_brackets_make_a_checkbox() -> None:
    assert on_close_bracket([], "- [", 3) == Change("- [ ] ", 6)
    assert on_close_bracket([], "[", 1) == Change("- [ ] ", 6)
    assert on_close_bracket([], "  [", 3) == Change("  - [ ] ", 8)
    assert on_close_bracket([], "1. [우유", 4) == Change("1. [ ] 우유", 7)


def test_brackets_elsewhere_are_left_alone() -> None:
    assert on_close_bracket([], "see [", 5) is None  # a link, perhaps
    assert on_close_bracket([], "- [ ] [", 7) is None  # a checkbox already
    assert on_close_bracket(["```"], "[", 1) is None
    assert on_close_bracket([], "- x", 3) is None


# Whatever the line, only it changes, and nothing typed before the cursor is lost.

lines = st.text(alphabet=st.sampled_from(list("- *1.)[]x 우a\t")), max_size=20)


@given(lines, st.lists(lines, max_size=4), st.data())
def test_the_text_before_the_cursor_is_kept(
    line: str, before: list[str], data: st.DataObject
) -> None:
    column = data.draw(st.integers(0, len(line)))
    change = on_enter(before, line, column)
    if change is not None and "\n" in change.text:
        assert change.text.split("\n")[0] == line[:column].rstrip(" ")
        assert change.text.endswith(line[column:].lstrip(" "))
    for back in (False, True):
        tabbed = on_tab(before, line, column, back)
        if tabbed is not None:
            assert tabbed.text.lstrip(" \t") == line.lstrip(" \t")
            assert 0 <= tabbed.cursor <= len(tabbed.text)
    if change is not None:
        assert 0 <= change.cursor <= len(change.text)


def test_an_item_moved_out_is_numbered_on_from_the_outer_list() -> None:
    assert enter("   3. ", ["1. a", "   2. b"]) == Change("2. ", 3)
