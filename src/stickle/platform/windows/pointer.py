"""Whether the main mouse button is held, as Windows sees it right now."""

import ctypes
import sys

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

SM_SWAPBUTTON = 23  # buttons swapped for the left hand: the main one is the right
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

_user32 = ctypes.windll.user32
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short


def main_button_down() -> bool:
    key = VK_RBUTTON if _user32.GetSystemMetrics(SM_SWAPBUTTON) else VK_LBUTTON
    return bool(_user32.GetAsyncKeyState(key) & 0x8000)
