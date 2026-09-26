"""Windows shortcut files (.lnk), written and read through the Shell's own
IShellLink object, called with ctypes: no extra library, and no PowerShell
(scripts writing into the Startup folder are what antivirus products watch).
"""

import ctypes
import sys
import uuid
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

assert sys.platform == "win32"  # also tells the type checker the rest is Windows only

CLSID_SHELL_LINK = uuid.UUID("00021401-0000-0000-C000-000000000046")
IID_SHELL_LINK_W = uuid.UUID("000214F9-0000-0000-C000-000000000046")
IID_PERSIST_FILE = uuid.UUID("0000010B-0000-0000-C000-000000000046")
CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2
RPC_E_CHANGED_MODE = -2147417850
MAX_PATH_CHARS = 32768
# Positions in the objects' method tables (IUnknown's three come first).
QUERY_INTERFACE, RELEASE = 0, 2
GET_PATH, SET_DESCRIPTION, GET_WORKING_DIRECTORY, SET_WORKING_DIRECTORY = 3, 7, 8, 9
GET_ARGUMENTS, SET_ARGUMENTS, SET_ICON_LOCATION, SET_PATH = 10, 11, 17, 20
PERSIST_LOAD, PERSIST_SAVE = 5, 6
STGM_READ = 0

ole32 = ctypes.WinDLL("ole32")


class Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def of(cls, value: uuid.UUID) -> Guid:
        return cls.from_buffer_copy(value.bytes_le)


@dataclass(frozen=True)
class Shortcut:
    target: Path
    arguments: str = ""
    working_directory: Path | None = None
    description: str = ""


class _Com:
    """One COM interface pointer, with its methods called by table position."""

    def __init__(self, pointer: ctypes.c_void_p) -> None:
        self.pointer = pointer

    def call(self, index: int, *arguments: Any) -> int:
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        types = [ctypes.c_void_p, *(_ctype(argument) for argument in arguments)]
        function: Callable[..., int] = ctypes.WINFUNCTYPE(ctypes.HRESULT, *types)(table[index])
        return function(self.pointer, *arguments)

    def query(self, iid: uuid.UUID) -> _Com:
        other = ctypes.c_void_p()
        self.call(QUERY_INTERFACE, ctypes.byref(Guid.of(iid)), ctypes.byref(other))
        return _Com(other)

    def release(self) -> None:
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[RELEASE])(self.pointer)


def _ctype(argument: object) -> Any:
    if isinstance(argument, str):
        return ctypes.c_wchar_p
    if isinstance(argument, int):
        return ctypes.c_int
    return ctypes.c_void_p


def _shell_link() -> _Com:
    result = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    if result < 0 and result != RPC_E_CHANGED_MODE:  # already set up by Qt: fine
        raise OSError(f"COM could not start: {result:#x}")
    link = ctypes.c_void_p()
    result = ole32.CoCreateInstance(
        ctypes.byref(Guid.of(CLSID_SHELL_LINK)),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(Guid.of(IID_SHELL_LINK_W)),
        ctypes.byref(link),
    )
    if result < 0:
        raise OSError(f"cannot create a shortcut: {result:#x}")
    return _Com(link)


def write_shortcut(path: Path, shortcut: Shortcut) -> None:
    link = _shell_link()
    try:
        link.call(SET_PATH, str(shortcut.target))
        link.call(SET_ARGUMENTS, shortcut.arguments)
        link.call(SET_DESCRIPTION, shortcut.description)
        link.call(SET_ICON_LOCATION, str(shortcut.target), 0)
        if shortcut.working_directory is not None:
            link.call(SET_WORKING_DIRECTORY, str(shortcut.working_directory))
        persist = link.query(IID_PERSIST_FILE)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            result = persist.call(PERSIST_SAVE, str(path), 1)
            if result < 0:
                raise OSError(f"cannot save the shortcut: {result:#x}")
        finally:
            persist.release()
    finally:
        link.release()


def read_shortcut(path: Path) -> Shortcut:
    link = _shell_link()
    try:
        persist = link.query(IID_PERSIST_FILE)
        try:
            if persist.call(PERSIST_LOAD, str(path), STGM_READ) < 0:
                raise OSError("cannot read the shortcut")
        finally:
            persist.release()
        target = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        link.call(GET_PATH, ctypes.cast(target, ctypes.c_void_p), MAX_PATH_CHARS, None, 0)
        arguments = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        link.call(GET_ARGUMENTS, ctypes.cast(arguments, ctypes.c_void_p), MAX_PATH_CHARS)
        folder = ctypes.create_unicode_buffer(MAX_PATH_CHARS)
        link.call(GET_WORKING_DIRECTORY, ctypes.cast(folder, ctypes.c_void_p), MAX_PATH_CHARS)
        return Shortcut(
            target=Path(target.value),
            arguments=arguments.value,
            working_directory=Path(folder.value) if folder.value else None,
        )
    finally:
        link.release()
