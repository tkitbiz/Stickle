"""Where notes go on screen: numbered monitors, a main place and a spare one."""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from stickle.core.layout import (
    MAIN,
    SPARE,
    Monitor,
    Place,
    Rect,
    fit,
    numbered,
    place_of,
    remember,
    restore,
)

TASKBAR = 40


def monitor(
    name: str, x: int, width: int = 1920, height: int = 1080, primary: bool = False
) -> Monitor:
    return Monitor(
        name=name,
        geometry=Rect(x, 0, width, height),
        available=Rect(x, 0, width, height - TASKBAR),
        primary=primary,
    )


def inside(window: Rect, area: Rect) -> bool:
    return (
        area.x <= window.x
        and area.y <= window.y
        and window.right <= area.right
        and window.bottom <= area.bottom
    )


NOTE = Rect(0, 0, 260, 240)


def at(x: int, y: int) -> Rect:
    return Rect(x, y, NOTE.width, NOTE.height)


# Numbering


@pytest.mark.parametrize(
    "arrangement",
    [
        [monitor("P", 0, primary=True), monitor("A", 1920), monitor("B", 3840)],  # main on the left
        [monitor("A", 0), monitor("P", 1920, primary=True), monitor("B", 3840)],  # in the middle
        [monitor("A", 0), monitor("B", 1920), monitor("P", 3840, primary=True)],  # on the right
    ],
)
def test_main_monitor_is_one_then_left_to_right(arrangement: list[Monitor]) -> None:
    assert [m.name for m in numbered(arrangement)] == ["P", "A", "B"]


def test_numbering_ignores_the_order_the_system_lists_them_in() -> None:
    listed = [monitor("B", 3840), monitor("P", 0, primary=True), monitor("A", 1920)]

    assert [m.name for m in numbered(listed)] == ["P", "A", "B"]


# Coming back to the same place


def test_same_place_after_reopening() -> None:
    screens = [monitor("P", 0, primary=True), monitor("A", 1920)]
    window = at(2500, 300)

    placement = restore(remember({}, window, screens, own_monitor=True), screens)

    assert placement is not None
    assert placement.window == window
    assert placement.own_monitor


def test_same_proportional_place_after_a_resolution_change() -> None:
    before = [monitor("P", 0, 1920, 1080, primary=True)]
    after = [monitor("P", 0, 3840, 2160, primary=True)]

    places = remember({}, at(960, 540), before, own_monitor=True)
    placement = restore(places, after)

    assert placement is not None
    assert (placement.window.x, placement.window.y) == (1920, 1080)


# A monitor goes missing, and comes back


def test_note_of_a_missing_monitor_shows_on_monitor_one_and_goes_back() -> None:
    both = [monitor("P", 0, primary=True), monitor("B", 1920)]
    alone = [monitor("P", 0, primary=True)]
    places = remember({}, at(2500, 300), both, own_monitor=True)

    shown = restore(places, alone)
    assert shown is not None
    assert not shown.own_monitor
    assert inside(shown.window, alone[0].available)

    back = restore(places, both)
    assert back is not None
    assert back.window == at(2500, 300)
    assert back.own_monitor


def test_moving_it_meanwhile_changes_only_the_spare_place() -> None:
    both = [monitor("P", 0, primary=True), monitor("B", 1920)]
    alone = [monitor("P", 0, primary=True)]
    places = remember({}, at(2500, 300), both, own_monitor=True)

    places = remember(places, at(100, 700), alone, own_monitor=False)

    spare = restore(places, alone)
    assert spare is not None
    assert (spare.window.x, spare.window.y) == (100, 700)
    back = restore(places, both)
    assert back is not None
    assert back.window == at(2500, 300)


def test_size_is_shared_by_both_places() -> None:
    both = [monitor("P", 0, primary=True), monitor("B", 1920)]
    alone = [monitor("P", 0, primary=True)]
    places = remember({}, at(2500, 300), both, own_monitor=True)

    places = remember(places, Rect(100, 700, 400, 300), alone, own_monitor=False)

    assert (places[MAIN].width, places[MAIN].height) == (400, 300)
    assert (places[SPARE].width, places[SPARE].height) == (400, 300)


def test_moving_to_another_monitor_while_all_are_there_moves_it_for_good() -> None:
    both = [monitor("P", 0, primary=True), monitor("B", 1920)]
    places = remember({}, at(2500, 300), both, own_monitor=True)

    places = remember(places, at(300, 300), both, own_monitor=True)

    assert places[MAIN].monitor == 1


def test_removing_the_middle_of_three_keeps_the_others_in_place() -> None:
    three = [monitor("P", 0, primary=True), monitor("A", 1920), monitor("B", 3840)]
    without_a = [monitor("P", 0, primary=True), monitor("B", 1920)]
    on_a = remember({}, at(2500, 300), three, own_monitor=True)
    on_b = remember({}, at(4500, 300), three, own_monitor=True)

    shown_b = restore(on_b, without_a)
    shown_a = restore(on_a, without_a)

    assert shown_b is not None and shown_b.own_monitor
    assert inside(shown_b.window, without_a[1].available)  # still on B, now number 2
    assert shown_a is not None and not shown_a.own_monitor  # A is gone: spare place


def test_changing_the_main_monitor_keeps_notes_on_their_monitor() -> None:
    before = [monitor("L", 0, primary=True), monitor("R", 1920)]
    after = [monitor("L", 0), monitor("R", 1920, primary=True)]
    places = remember({}, at(2500, 300), before, own_monitor=True)

    placement = restore(places, after)

    assert placement is not None
    assert placement.window == at(2500, 300)


def test_another_computer_with_as_many_monitors_uses_the_numbers() -> None:
    here = [monitor("DELL", 0, primary=True), monitor("LG", 1920)]
    there = [monitor("HP", 0, 2560, 1440, primary=True), monitor("ASUS", 2560, 2560, 1440)]
    places = remember({}, at(1920 + 960, 540), here, own_monitor=True)

    placement = restore(places, there)

    assert placement is not None
    assert placement.own_monitor
    assert (placement.window.x, placement.window.y) == (2560 + 1280, 720)


def test_twin_monitors_with_the_same_name_go_by_number() -> None:
    twins = [monitor("U2720Q", 0, primary=True), monitor("U2720Q", 1920)]
    places = remember({}, at(2500, 300), twins, own_monitor=True)

    placement = restore(places, twins)

    assert placement is not None
    assert placement.window == at(2500, 300)


# Always on screen


def test_a_note_off_the_edge_is_brought_inside_the_work_area() -> None:
    screen = monitor("P", 0, primary=True)
    places = {MAIN: Place(1, "P", 0.99, 0.99, 260, 240)}

    placement = restore(places, [screen])

    assert placement is not None
    assert inside(placement.window, screen.available)


def test_a_note_bigger_than_the_screen_is_shrunk() -> None:
    area = Rect(0, 0, 800, 560)

    assert inside(fit(Rect(-50, -50, 2000, 2000), area), area)


def test_nothing_remembered_means_nothing_to_restore() -> None:
    assert restore({}, [monitor("P", 0, primary=True)]) is None


@pytest.mark.parametrize(
    "place",
    [
        Place(0, "", 0.1, 0.1, 260, 240),
        Place(1, "", math.nan, 0.1, 260, 240),
        Place(1, "", 0.1, math.inf, 260, 240),
        Place(1, "", 0.1, 0.1, -5, 240),
        Place(1, "", 0.1, 0.1, 260, 10**9),
    ],
)
def test_nonsense_places_are_not_valid(place: Place) -> None:
    assert not place.is_valid()


def any_monitor(name: str, x: int, y: int, width: int, height: int, taskbar: int) -> Monitor:
    return Monitor(name, Rect(x, y, width, height), Rect(x, y, width, max(height - taskbar, 200)))


screens = st.lists(
    st.builds(
        any_monitor,
        st.sampled_from(["", "P", "A", "B"]),
        st.integers(-5000, 5000),
        st.integers(-3000, 3000),
        st.integers(640, 7680),
        st.integers(480, 4320),
        st.integers(0, 80),
    ),
    min_size=1,
    max_size=4,
)
places = st.builds(
    Place,
    st.integers(1, 5),
    st.sampled_from(["", "P", "A"]),
    st.floats(-1, 2),
    st.floats(-1, 2),
    st.integers(120, 3000),
    st.integers(60, 3000),
    st.lists(st.sampled_from(["", "P", "A", "C"]), max_size=3).map(tuple),
)


@given(screens, places, st.one_of(st.none(), places))
def test_a_restored_note_is_always_inside_a_monitor(
    monitors: list[Monitor], main: Place, spare: Place | None
) -> None:
    remembered = {MAIN: main} | ({SPARE: spare} if spare else {})

    placement = restore(remembered, monitors)

    assert placement is not None
    assert any(inside(placement.window, m.available) for m in monitors)


side_by_side = st.lists(
    st.tuples(st.integers(640, 7680), st.integers(480, 4320)), min_size=1, max_size=4
).map(
    lambda sizes: [
        monitor(f"M{i}", sum(w for w, _ in sizes[:i]), w, h, primary=i == 0)
        for i, (w, h) in enumerate(sizes)
    ]
)


@given(side_by_side, st.data())
def test_where_it_is_can_always_be_remembered_and_found_again(
    monitors: list[Monitor], data: st.DataObject
) -> None:
    area = data.draw(st.sampled_from(monitors)).available
    x = data.draw(st.integers(area.x, area.right - NOTE.width))
    y = data.draw(st.integers(area.y, area.bottom - NOTE.height))

    placement = restore(remember({}, at(x, y), monitors, own_monitor=True), monitors)

    assert placement is not None
    assert abs(placement.window.x - x) <= 1 and abs(placement.window.y - y) <= 1


def test_where_a_window_is_is_worked_out_from_its_title_bar() -> None:
    screens = [monitor("P", 0, primary=True), monitor("B", 1920)]
    # Mostly on B, but held by a title bar that is still on P.
    window = Rect(1900, 100, 400, 300)

    assert place_of(Rect(1700, 100, 400, 300), screens).monitor == 1
    assert place_of(window, screens).monitor == 2
