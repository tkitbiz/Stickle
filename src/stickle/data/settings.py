"""Settings, in two kinds.

Device settings belong to this computer only (autostart, ...; the language,
needed before the database opens, is in stickle.data.startup).
Shared settings will follow the user to every device once sync exists
(default colour, categories, ...); each records when and on which device it
last changed, so sync can later pick the newest per setting.

Every setting is declared once here, with its kind, default and allowed
values; reads and writes are checked against that declaration.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeGuard

import apsw

from stickle.core.clock import Clock, utc_now
from stickle.core.note import DEFAULT_COLOR

type Scope = Literal["device", "shared"]


@dataclass(frozen=True)
class Setting[T]:
    key: str
    scope: Scope
    default: T
    check: Callable[[object], TypeGuard[T]]


class InvalidSettingError(ValueError):
    pass


def _flag(value: object) -> TypeGuard[bool]:
    return isinstance(value, bool)


THIS_DEVICE = "this_device"
SEVERAL_DEVICES = "several_devices"


def _usage(value: object) -> TypeGuard[str | None]:
    return value in (None, THIS_DEVICE, SEVERAL_DEVICES)


def _color_key(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and value.isidentifier()


def _uuid_or_none(value: object) -> TypeGuard[str | None]:
    if value is None:
        return True
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


# The interface language is not here: it is needed before the database is
# open (see stickle.data.startup).
DEVICE_ID = Setting[str | None]("device_id", "device", None, _uuid_or_none)
DEFAULT_NOTE_COLOR = Setting[str]("default_color", "shared", DEFAULT_COLOR, _color_key)
# Asked once whether to add the AppImage to the application list (whatever the answer).
APP_MENU_ASKED = Setting[bool]("app_menu_asked", "device", False, _flag)
# Asked at first start: notes on this computer only, or on several (sync comes later).
USAGE = Setting[str | None]("usage", "device", None, _usage)
# The user said they kept the recovery key (Done, not Later).
RECOVERY_KEY_KEPT = Setting[bool]("recovery_key_kept", "device", False, _flag)
# Skipped at first start, the recovery key is offered once more, never again after.
RECOVERY_KEY_OFFERED_AGAIN = Setting[bool]("recovery_key_offered_again", "device", False, _flag)

SETTINGS: dict[str, Setting[object]] = {
    s.key: s  # pyright: ignore[reportAssignmentType]
    for s in (
        DEVICE_ID,
        DEFAULT_NOTE_COLOR,
        APP_MENU_ASKED,
        USAGE,
        RECOVERY_KEY_KEPT,
        RECOVERY_KEY_OFFERED_AGAIN,
    )
}


class Settings:
    def __init__(self, connection: apsw.Connection, clock: Clock = utc_now) -> None:
        self._db = connection
        self._clock = clock

    def get[T](self, setting: Setting[T]) -> T:
        table = "device_settings" if setting.scope == "device" else "shared_settings"
        rows = self._db.execute(
            f"SELECT value FROM {table} WHERE key = ?", (setting.key,)
        ).fetchall()
        if not rows:
            return setting.default
        value: object = json.loads(str(rows[0][0]))
        # A value that no longer fits (edited by hand, older app) falls back to the default.
        return value if setting.check(value) else setting.default

    def set[T](self, setting: Setting[T], value: T) -> None:
        if not setting.check(value):
            raise InvalidSettingError(f"{setting.key}: {value!r}")
        encoded = json.dumps(value)
        with self._db:
            if setting.scope == "device":
                self._db.execute(
                    "INSERT INTO device_settings (key, value) VALUES (?, ?)"
                    " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                    (setting.key, encoded),
                )
            else:
                self._db.execute(
                    "INSERT INTO shared_settings (key, value, updated_at, updated_by)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (key) DO UPDATE SET"
                    " value = excluded.value, updated_at = excluded.updated_at,"
                    " updated_by = excluded.updated_by",
                    (setting.key, encoded, self._clock(), self.device_id()),
                )

    def device_id(self) -> str:
        """This device's identity, created on first use."""
        current = self.get(DEVICE_ID)
        if current is None:
            current = str(uuid.uuid4())
            self.set(DEVICE_ID, current)
        return current
