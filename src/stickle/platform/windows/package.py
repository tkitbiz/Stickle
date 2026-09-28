"""Whether Stickle runs as an installed package (MSIX, from the Microsoft Store)."""

import ctypes
import sys
from ctypes import wintypes

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

APPMODEL_ERROR_NO_PACKAGE = 15700


def is_packaged() -> bool:
    """True when the process has a package identity; a folder from a zip has none."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_name = kernel32.GetCurrentPackageFullName
    get_name.argtypes = [ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
    get_name.restype = wintypes.LONG
    length = wintypes.UINT(0)
    # Asked with no room for the name: a packaged process answers "buffer too small".
    return get_name(ctypes.byref(length), None) != APPMODEL_ERROR_NO_PACKAGE
