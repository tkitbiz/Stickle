"""Keeping a window above others on Windows, by its place in the stacking order alone.

Changing Qt's stay-on-top flag on a window that is shown restyles it, and a
see-through window (a note, for its round corners) then lost what was drawn
in it on some systems: a note became its pin icon alone. Moving the window
into or out of the topmost band touches nothing but the order.
"""

import ctypes
import sys
from ctypes import wintypes

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

_set_window_pos = ctypes.windll.user32.SetWindowPos
_set_window_pos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]  # fmt: skip
_set_window_pos.restype = wintypes.BOOL


def set_topmost(window: int, on_top: bool) -> bool:
    """Put a window in the topmost band or take it out; False if Windows refused."""
    after = HWND_TOPMOST if on_top else HWND_NOTOPMOST
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    return bool(_set_window_pos(window, after, 0, 0, 0, 0, flags))
