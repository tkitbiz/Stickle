"""Shortcuts registered with Windows (RegisterHotKey).

Registered for the thread rather than a window: Windows posts WM_HOTKEY to
the app's message queue, where a native event filter sees it. Pressing one
lets the app bring a window to the front, as the user asked for it.
"""

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import override

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication

from stickle.platform.hotkeys import Combo

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
MOD_NOREPEAT = 0x4000  # held down, it counts once
VK_F1 = 0x70


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def virtual_key(key: str) -> int:
    """Windows' key code for one of stickle.platform.hotkeys.KEYS."""
    if key.startswith("F") and len(key) > 1:
        return VK_F1 + int(key[1:]) - 1
    return ord(key)  # letters and digits are their own upper-case character


def modifier_flags(combo: Combo) -> int:
    flags = MOD_NOREPEAT
    for on, flag in zip(combo.modifiers, (MOD_CONTROL, MOD_ALT, MOD_SHIFT, MOD_WIN), strict=True):
        if on:
            flags |= flag
    return flags


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, pressed: Callable[[int], object]) -> None:
        super().__init__()
        self._pressed = pressed

    @override
    def nativeEventFilter(
        self, eventType: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> object:
        name = eventType.data() if isinstance(eventType, QByteArray) else bytes(eventType)
        if name == b"windows_generic_MSG":
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and not msg.hwnd:
                self._pressed(int(msg.wParam))
                return True, 0
        return False, 0


class WindowsHotkeys:
    def __init__(self, pressed: Callable[[int], object]) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._register = user32.RegisterHotKey
        self._register.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self._register.restype = wintypes.BOOL
        self._unregister = user32.UnregisterHotKey
        self._unregister.argtypes = [wintypes.HWND, ctypes.c_int]
        self._unregister.restype = wintypes.BOOL
        app = QCoreApplication.instance()
        if app is None:
            raise OSError("no application to hear the shortcuts")
        self._filter = _HotkeyFilter(pressed)
        app.installNativeEventFilter(self._filter)
        self._registered: set[int] = set()

    def register(self, number: int, combo: Combo) -> bool:
        self.unregister(number)
        if not self._register(None, number, modifier_flags(combo), virtual_key(combo.key)):
            return False  # ERROR_HOTKEY_ALREADY_REGISTERED: another application has it
        self._registered.add(number)
        return True

    def unregister(self, number: int) -> None:
        if number in self._registered:
            self._unregister(None, number)
            self._registered.discard(number)
