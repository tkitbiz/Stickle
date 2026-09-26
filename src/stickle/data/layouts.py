"""Where each note was on screen, in the note_layouts table.

A note has up to two rows: its main place and its spare place (see
stickle.core.layout). config_key holds which one, and monitor_key, as JSON,
the monitor's number and name and the names of the monitors connected then.
Rows that do not make sense (edited by hand, written by a broken version)
are ignored on reading.
"""

import json
from typing import cast

import apsw

from stickle.core.clock import Clock, utc_now
from stickle.core.layout import MAIN, SPARE, Place


def _monitor_key(place: Place) -> str:
    return json.dumps(
        {"number": place.monitor, "name": place.name, "setup": list(place.setup)},
        ensure_ascii=False,
    )


def _place(
    monitor_key: object, rel_x: object, rel_y: object, width: object, height: object
) -> Place | None:
    try:
        decoded: object = json.loads(str(monitor_key))
    except ValueError:
        return None
    if not isinstance(decoded, dict):
        return None
    monitor = cast(dict[str, object], decoded)
    number, name, setup = monitor.get("number"), monitor.get("name"), monitor.get("setup")
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or not isinstance(name, str)
        or not isinstance(setup, list)
    ):
        return None
    names = [item for item in cast(list[object], setup) if isinstance(item, str)]
    numbers = (rel_x, rel_y, width, height)
    if len(names) != len(cast(list[object], setup)) or not all(
        isinstance(value, int | float) for value in numbers
    ):
        return None
    place = Place(
        monitor=number,
        name=name,
        rel_x=float(cast(float, rel_x)),
        rel_y=float(cast(float, rel_y)),
        width=int(cast(float, width)),
        height=int(cast(float, height)),
        setup=tuple(names),
    )
    return place if place.is_valid() else None


class LayoutRepository:
    def __init__(self, connection: apsw.Connection, clock: Clock = utc_now) -> None:
        self._db = connection
        self._clock = clock

    def places(self, note_id: str) -> dict[str, Place]:
        rows = self._db.execute(
            "SELECT config_key, monitor_key, rel_x, rel_y, width, height FROM note_layouts"
            " WHERE note_id = ?",
            (note_id,),
        ).fetchall()
        found: dict[str, Place] = {}
        for slot, *values in rows:
            if slot in (MAIN, SPARE) and (place := _place(*values)) is not None:
                found[str(slot)] = place
        return found

    def save(self, note_id: str, places: dict[str, Place]) -> None:
        now = self._clock()
        with self._db:
            for slot, place in places.items():
                self._db.execute(
                    "INSERT INTO note_layouts (note_id, config_key, monitor_key, rel_x, rel_y,"
                    " width, height, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (note_id, config_key) DO UPDATE SET"
                    " monitor_key = excluded.monitor_key, rel_x = excluded.rel_x,"
                    " rel_y = excluded.rel_y, width = excluded.width, height = excluded.height,"
                    " updated_at = excluded.updated_at",
                    (
                        note_id,
                        slot,
                        _monitor_key(place),
                        place.rel_x,
                        place.rel_y,
                        place.width,
                        place.height,
                        now,
                    ),
                )
