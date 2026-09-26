"""Notice when Windows is about to sleep.

Windows sends WM_POWERBROADCAST with PBT_APMSUSPEND to every top-level
window just before it suspends. A native event filter sees it for the app's
windows; with several notes open it arrives once per window.
"""

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import override

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def is_suspend(message_address: int) -> bool:
    message = MSG.from_address(message_address)
    return message.message == WM_POWERBROADCAST and message.wParam == PBT_APMSUSPEND


class SleepFilter(QAbstractNativeEventFilter):
    def __init__(self, before_sleep: Callable[[], object]) -> None:
        super().__init__()
        self._before_sleep = before_sleep

    @override
    def nativeEventFilter(
        self, eventType: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> object:
        name = eventType.data() if isinstance(eventType, QByteArray) else bytes(eventType)
        if name == b"windows_generic_MSG" and is_suspend(int(message)):
            self._before_sleep()
        return False, 0
