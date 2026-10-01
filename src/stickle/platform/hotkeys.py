"""Keyboard shortcuts that work whichever application is in front.

Windows registers them with the system (RegisterHotKey); an X11 session
grabs them from the X server; under Wayland the desktop keeps them, through
its portal (see Portal). Elsewhere (macOS for now), or where the portal is
missing, there is no way here, and Stickle says so: its command line
(--new-note and the like) can be given a shortcut in the desktop's own
keyboard settings.
"""

import logging
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

LETTERS = [chr(code) for code in range(ord("A"), ord("Z") + 1)]
DIGITS = [str(digit) for digit in range(10)]
FUNCTION_KEYS = [f"F{number}" for number in range(1, 13)]
KEYS = (*LETTERS, *DIGITS, *FUNCTION_KEYS)
MODIFIERS = ("Ctrl", "Alt", "Shift", "Meta")  # as Qt writes them (Meta: the Windows key)


@dataclass(frozen=True)
class Combo:
    """A key with modifiers, as Qt writes it portably ("Ctrl+Alt+N")."""

    key: str  # one of KEYS
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False

    @classmethod
    def parse(cls, text: str) -> Combo | None:
        """None unless text is modifiers then one of KEYS, each once."""
        *modifiers, key = text.split("+") if text else [""]
        if key.upper() not in KEYS or len(set(modifiers)) != len(modifiers):
            return None
        if any(modifier not in MODIFIERS for modifier in modifiers):
            return None
        return cls(
            key.upper(),
            ctrl="Ctrl" in modifiers,
            alt="Alt" in modifiers,
            shift="Shift" in modifiers,
            meta="Meta" in modifiers,
        )

    @property
    def text(self) -> str:
        held = [name for name, on in zip(MODIFIERS, self.modifiers, strict=True) if on]
        return "+".join([*held, self.key])

    @property
    def modifiers(self) -> tuple[bool, bool, bool, bool]:
        return (self.ctrl, self.alt, self.shift, self.meta)

    @property
    def portal_trigger(self) -> str:
        """As the desktop portal suggests a shortcut ("CTRL+ALT+n": XDG shortcut names)."""
        names = ("CTRL", "ALT", "SHIFT", "LOGO")
        held = [name for name, on in zip(names, self.modifiers, strict=True) if on]
        return "+".join([*held, self.key.lower() if len(self.key) == 1 else self.key])

    @property
    def usable(self) -> bool:
        """Held with Ctrl, Alt or the Windows key: without one, typing would set it off."""
        return self.ctrl or self.alt or self.meta


class Hotkeys(Protocol):
    """Shortcuts registered with the system, each under a number of the caller's."""

    def register(self, number: int, combo: Combo) -> bool:
        """False if the system refused it (another application has it)."""
        ...

    def unregister(self, number: int) -> None: ...


def x11_session(environment: Mapping[str, str]) -> bool:
    """An X11 desktop session, where no Wayland compositor stands in between."""
    session = environment.get("XDG_SESSION_TYPE", "")
    if session:
        return session == "x11"
    return bool(environment.get("DISPLAY")) and not environment.get("WAYLAND_DISPLAY")


class Portal(QObject):
    """Shortcuts the desktop keeps: offered once, answered later, changed in its settings.

    bind() offers them; bound then says which keys each got (the desktop's
    own words, "" for none), again whenever its settings change them, or
    failed says the desktop cannot keep them. activated gives an id per press.
    """

    activated = Signal(str)
    bound = Signal(dict)
    failed = Signal()

    def bind(self, shortcuts: list[tuple[str, str, str]], parent_window: str = "") -> None:
        """(id, description, suggested keys as Combo.portal_trigger writes them, or "").
        parent_window ("x11:<id>", or "" for none) is the window the desktop's
        question belongs to, so that it comes up over it."""
        raise NotImplementedError

    def configure(self) -> bool:
        """Open the desktop's page for these shortcuts; False where it has none."""
        raise NotImplementedError


def desktop_portal(app_id: str) -> Portal | None:
    """Where the system gives no way to register shortcuts but a Linux desktop
    may through its portal (Wayland): the portal's session, or None."""
    if not sys.platform.startswith("linux") or x11_session(os.environ):
        return None
    try:
        from stickle.platform.linux.portal_shortcuts import PortalShortcuts

        return PortalShortcuts(app_id)
    except (OSError, ValueError, KeyError) as error:  # no session bus to be had
        log.warning("the desktop portal cannot be reached: %s", type(error).__name__)
        return None


def system_hotkeys(pressed: Callable[[int], object]) -> Hotkeys | None:
    """The system's way to register shortcuts here, or None if there is none.

    pressed gets the number a shortcut was registered under.
    """
    try:
        if sys.platform == "win32":
            from stickle.platform.windows.hotkeys import WindowsHotkeys

            return WindowsHotkeys(pressed)
        if sys.platform.startswith("linux") and x11_session(os.environ):
            # Under Wayland, Stickle runs through XWayland, whose grabs only see
            # keys pressed in other X11 applications.
            from stickle.platform.linux.hotkeys import X11Hotkeys

            return X11Hotkeys(pressed)
    except (OSError, AttributeError) as error:
        log.warning("shortcuts cannot be registered: %s", type(error).__name__)
    return None
