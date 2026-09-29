"""The shortcuts that work whichever application is in front: a new note, the
Stickle window, and every note out of sight for a while.

They do what the command line can ask for (see stickle.platform.instance).
The defaults can be changed, or turned off, on each computer. A shortcut the
system refuses (another application has it) is left unregistered and said
so in the Stickle window for as long as it lasts, never in a pop-up.
"""

import logging
from collections.abc import Callable
from enum import Enum

import apsw
from PySide6.QtCore import QObject, Signal

from stickle.data.settings import SHORTCUT_ACTIONS, SHORTCUTS, Settings
from stickle.platform.hotkeys import Combo, Hotkeys, system_hotkeys
from stickle.platform.instance import NEW_NOTE, SET_ASIDE, SHOW

log = logging.getLogger(__name__)

# Each action is also a request of stickle.platform.instance, under its setting key.
REQUESTS = {"new-note": NEW_NOTE, "show": SHOW, "hide-all": SET_ASIDE}
DEFAULTS = {"new-note": "Ctrl+Alt+N", "show": "Ctrl+Alt+S", "hide-all": "Ctrl+Alt+H"}
assert tuple(REQUESTS) == tuple(DEFAULTS) == SHORTCUT_ACTIONS


class State(Enum):
    ON = "on"
    OFF = "off"  # turned off by the user
    TAKEN = "taken"  # another application has it
    UNAVAILABLE = "unavailable"  # no way to register shortcuts here


class Refused(Enum):
    """Why a new combination was not taken."""

    NOT_A_SHORTCUT = "not a shortcut"  # without Ctrl, Alt or the Windows key, or not a key we know
    IN_USE_HERE = "in use here"  # another of Stickle's own shortcuts


class GlobalShortcuts(QObject):
    pressed = Signal(bytes)  # the request of stickle.platform.instance
    changed = Signal()  # a shortcut or its state changed

    def __init__(
        self,
        settings: Settings | None,
        make_hotkeys: Callable[[Callable[[int], object]], Hotkeys | None] = system_hotkeys,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._hotkeys = make_hotkeys(self._heard)
        self._states: dict[str, State] = {}
        for action in SHORTCUT_ACTIONS:
            self._register(action)

    @property
    def available(self) -> bool:
        return self._hotkeys is not None

    def combo(self, action: str) -> str:
        """The action's key combination ("Ctrl+Alt+N"), "" when turned off."""
        chosen = self._settings.get(SHORTCUTS) if self._settings else {}
        text = chosen.get(action, DEFAULTS[action])
        if text and Combo.parse(text) is None:
            return DEFAULTS[action]  # no longer understood (edited by hand): the default
        return text

    def state(self, action: str) -> State:
        return self._states[action]

    def change(self, action: str, text: str) -> Refused | None:
        """Use a new combination for the action ("" turns it off); None once done."""
        if text:
            combo = Combo.parse(text)
            if combo is None or not combo.usable:
                return Refused.NOT_A_SHORTCUT
            if any(
                self.combo(other) == combo.text for other in SHORTCUT_ACTIONS if other != action
            ):
                return Refused.IN_USE_HERE
            text = combo.text
        if self._settings is not None:
            chosen = dict(self._settings.get(SHORTCUTS))
            chosen[action] = text
            try:
                self._settings.set(SHORTCUTS, chosen)
            except apsw.Error as error:
                log.error("could not keep a shortcut: %s", type(error).__name__)
        self._register(action, text)
        self.changed.emit()
        return None

    def _register(self, action: str, text: str | None = None) -> None:
        number = SHORTCUT_ACTIONS.index(action) + 1
        text = self.combo(action) if text is None else text
        if self._hotkeys is None:
            self._states[action] = State.UNAVAILABLE
            return
        self._hotkeys.unregister(number)
        combo = Combo.parse(text) if text else None
        if combo is None:
            self._states[action] = State.OFF
        elif self._hotkeys.register(number, combo):
            self._states[action] = State.ON
        else:
            log.info("shortcut for %s is taken by another application", action)
            self._states[action] = State.TAKEN

    def _heard(self, number: int) -> None:
        if 1 <= number <= len(SHORTCUT_ACTIONS):
            self.pressed.emit(REQUESTS[SHORTCUT_ACTIONS[number - 1]])
