from hypothesis import given
from hypothesis import strategies as st

from stickle.core.layout import Rect
from stickle.core.snap import GAP, SNAP_DISTANCE, snapped, together

SCREEN = Rect(0, 0, 1920, 1040)
A = Rect(100, 100, 260, 300)


def test_a_note_dropped_near_another_goes_beside_it_tops_in_line() -> None:
    dropped = Rect(A.right + 10, A.y + 5, 260, 200)
    assert snapped(dropped, [A], [SCREEN]) == Rect(A.right + GAP, A.y, 260, 200)


def test_on_the_left_and_below_too() -> None:
    left = Rect(A.x - 260 - 2, A.y + 40, 260, 200)
    assert snapped(left, [A], [SCREEN]).x == A.x - GAP - 260
    below = Rect(A.x + 4, A.bottom + 15, 200, 100)
    assert snapped(below, [A], [SCREEN]) == Rect(A.x, A.bottom + GAP, 200, 100)


def test_a_note_dropped_near_the_edge_of_the_screen_goes_to_it() -> None:
    dropped = Rect(8, 500, 260, 200)
    assert snapped(dropped, [], [SCREEN]) == Rect(0, 500, 260, 200)
    corner = Rect(SCREEN.right - 260 - 5, SCREEN.bottom - 200 - 9, 260, 200)
    assert snapped(corner, [], [SCREEN]) == Rect(SCREEN.right - 260, SCREEN.bottom - 200, 260, 200)


def test_far_from_everything_it_stays() -> None:
    dropped = Rect(800, 500, 260, 200)
    assert snapped(dropped, [A], [SCREEN]) == dropped


def test_a_note_far_below_is_not_pulled_sideways() -> None:
    # In line with A's right edge, but 400 px below it: not near it at all.
    dropped = Rect(A.right + 8, A.bottom + 400, 260, 200)
    assert snapped(dropped, [A], [SCREEN]).x == dropped.x


def test_notes_side_by_side_move_together_and_on_down_the_chain() -> None:
    b = Rect(A.right + GAP, A.y, 260, 300)
    c = Rect(b.x, b.bottom + GAP, 260, 100)
    d = Rect(1500, 700, 260, 200)  # on its own
    notes = {"a": A, "b": b, "c": c, "d": d}
    assert together("a", notes) == {"a", "b", "c"}
    assert together("d", notes) == {"d"}


def test_corner_to_corner_is_not_together() -> None:
    diagonal = Rect(A.right + GAP, A.bottom + GAP, 100, 100)
    assert together("a", {"a": A, "x": diagonal}) == {"a"}


rects = st.builds(
    Rect,
    st.integers(-200, 2000),
    st.integers(-200, 1200),
    st.integers(60, 600),
    st.integers(22, 600),
)


@given(rects, st.lists(rects, max_size=6))
def test_snapping_moves_a_note_little_and_keeps_its_size(window: Rect, others: list[Rect]) -> None:
    result = snapped(window, others, [SCREEN])
    assert (result.width, result.height) == (window.width, window.height)
    assert abs(result.x - window.x) <= SNAP_DISTANCE
    assert abs(result.y - window.y) <= SNAP_DISTANCE
