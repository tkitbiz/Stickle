"""Where a note goes on screen, remembered per monitor rather than per desktop.

Monitors are numbered: the main (primary) monitor is 1, the others follow
from left to right, then top to bottom, so the numbers stay put as long as
the monitors stay where they are. A note remembers the number of its
monitor, that monitor's name as a hint (a model or connector name, never a
serial number), and where it sits on it as fractions of the monitor, so a
change of resolution or scaling leaves it in the same place.

Each note has a main place, on its own monitor, and a spare place for when
that monitor is not connected: then it is shown on monitor 1. Moving a note
while it is in its spare place changes only the spare place, so it goes
back to its own monitor when that returns. Whatever is remembered, a note
is always put entirely inside a monitor's work area.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

MAIN = "main"
SPARE = "spare"
MIN_WIDTH = 120
MIN_HEIGHT = 60
MAX_SIZE = 20_000
TITLE_BAR = 28  # where a note is held: which monitor it is on follows this


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def distance(self, x: float, y: float) -> float:
        dx = max(self.x - x, 0, x - self.right)
        dy = max(self.y - y, 0, y - self.bottom)
        return math.hypot(dx, dy)


@dataclass(frozen=True)
class Monitor:
    name: str  # a hint to find the same monitor again; may be empty
    geometry: Rect
    available: Rect  # without taskbars and docks
    primary: bool = False


@dataclass(frozen=True)
class Place:
    """Where a note sits: on monitor number `monitor`, as fractions of it."""

    monitor: int
    name: str
    rel_x: float
    rel_y: float
    width: int
    height: int
    # The names of every monitor connected at the time: seeing any of them
    # again means the same computer, where the note's own monitor is missing.
    setup: tuple[str, ...] = ()

    def is_valid(self) -> bool:
        return (
            self.monitor >= 1
            and all(math.isfinite(v) and -1 <= v <= 2 for v in (self.rel_x, self.rel_y))
            and MIN_WIDTH <= self.width <= MAX_SIZE
            and MIN_HEIGHT <= self.height <= MAX_SIZE
        )


def numbered(monitors: Sequence[Monitor]) -> list[Monitor]:
    """Monitors in number order: the main one first, then left to right, top to bottom."""
    primary = [m for m in monitors if m.primary][:1] or list(monitors[:1])
    others = sorted(
        (m for m in monitors if m not in primary), key=lambda m: (m.geometry.x, m.geometry.y)
    )
    return primary + others


def monitor_at(window: Rect, monitors: Sequence[Monitor]) -> tuple[int, Monitor]:
    """The monitor a note is on (by its title bar), with its number."""
    ordered = numbered(monitors)
    x, y = window.x + window.width / 2, window.y + min(TITLE_BAR, window.height) / 2
    for number, monitor in enumerate(ordered, 1):
        if monitor.geometry.contains(x, y):
            return number, monitor
    number, monitor = min(enumerate(ordered, 1), key=lambda item: item[1].geometry.distance(x, y))
    return number, monitor


def place_of(window: Rect, monitors: Sequence[Monitor]) -> Place:
    number, monitor = monitor_at(window, monitors)
    area = monitor.geometry
    return Place(
        monitor=number,
        name=monitor.name,
        rel_x=(window.x - area.x) / area.width,
        rel_y=(window.y - area.y) / area.height,
        width=window.width,
        height=window.height,
        setup=tuple(m.name for m in numbered(monitors)),
    )


def find_monitor(place: Place, monitors: Sequence[Monitor]) -> Monitor | None:
    """The monitor a place belongs to, or None if it is not connected.

    By name when exactly one connected monitor has it. On the same computer
    (a monitor of the remembered setup is here) a name not found means its
    monitor is missing: going by number would put it on whichever monitor
    moved up into that number. On another computer, by number.
    """
    ordered = numbered(monitors)
    named = [m for m in ordered if place.name and m.name == place.name]
    if len(named) == 1:
        return named[0]
    same_computer = any(m.name and m.name in place.setup for m in ordered)
    if same_computer and place.name and not named:
        return None
    if 1 <= place.monitor <= len(ordered):
        return ordered[place.monitor - 1]
    return None


def fit(window: Rect, area: Rect) -> Rect:
    """window moved (and shrunk if need be) to lie entirely inside area."""
    width = max(min(window.width, area.width), min(MIN_WIDTH, area.width))
    height = max(min(window.height, area.height), min(MIN_HEIGHT, area.height))
    x = min(max(window.x, area.x), area.right - width)
    y = min(max(window.y, area.y), area.bottom - height)
    return Rect(x, y, width, height)


def on_monitor(place: Place, monitor: Monitor) -> Rect:
    area = monitor.geometry
    window = Rect(
        area.x + round(place.rel_x * area.width),
        area.y + round(place.rel_y * area.height),
        place.width,
        place.height,
    )
    return fit(window, monitor.available)


@dataclass(frozen=True)
class Placement:
    window: Rect
    own_monitor: bool  # False: shown in its spare place, its monitor is missing


def restore(places: dict[str, Place], monitors: Sequence[Monitor]) -> Placement | None:
    """Where to show a note now, or None if nothing valid is remembered."""
    main, spare = places.get(MAIN), places.get(SPARE)
    if main is not None and (monitor := find_monitor(main, monitors)) is not None:
        return Placement(on_monitor(main, monitor), own_monitor=True)
    fallback = spare or main
    if fallback is None:
        return None
    first = numbered(monitors)[0]
    return Placement(on_monitor(fallback, first), own_monitor=False)


def remember(
    places: dict[str, Place], window: Rect, monitors: Sequence[Monitor], own_monitor: bool
) -> dict[str, Place]:
    """The places after the note was moved or resized to window.

    On its own monitor (or with nothing remembered yet) the main place
    follows; in the spare place only the spare place does. Both keep the
    same size.
    """
    place = place_of(window, monitors)
    slot = MAIN if own_monitor or MAIN not in places else SPARE
    updated = {
        key: replace(value, width=place.width, height=place.height) for key, value in places.items()
    }
    updated[slot] = place
    return updated
