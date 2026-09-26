"""Keeping notes out of the taskbar under X11 without tying them together.

Qt turns a tool window into a window transient for the application's group,
and window managers such as GNOME's Mutter lift every such window to the
highest layer any of them is in: one note kept above other windows would keep
all notes above them. So under X11 notes are ordinary windows, and this
module asks the window manager to leave them out of the taskbar, the window
switcher and the pager, as tool windows are, through the window's
_NET_WM_STATE. Set before the window is mapped, the state is read when the
window manager takes the window; Qt keeps states it does not manage itself.

This talks to the X server through its own libxcb connection (the library Qt
itself uses on X11), so it needs nothing beyond what is already loaded.
"""

import ctypes
import logging

log = logging.getLogger(__name__)

ATOM = 4  # a predefined atom (XA_ATOM): the type of an atom list
PROP_MODE_REPLACE = 0
SKIP_STATES = (b"_NET_WM_STATE_SKIP_TASKBAR", b"_NET_WM_STATE_SKIP_PAGER")


class _Cookie(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint)]


class _InternAtomReply(ctypes.Structure):
    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("pad0", ctypes.c_uint8),
        ("sequence", ctypes.c_uint16),
        ("length", ctypes.c_uint32),
        ("atom", ctypes.c_uint32),
    ]


class _GetPropertyReply(ctypes.Structure):
    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("format", ctypes.c_uint8),
        ("sequence", ctypes.c_uint16),
        ("length", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytes_after", ctypes.c_uint32),
        ("value_len", ctypes.c_uint32),
        ("pad0", ctypes.c_uint8 * 12),
    ]


class _ScreenIterator(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_uint32)),  # xcb_screen_t, whose first field is root
        ("rem", ctypes.c_int),
        ("index", ctypes.c_int),
    ]


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("format", ctypes.c_uint8),
        ("sequence", ctypes.c_uint16),
        ("window", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("data", ctypes.c_uint32 * 5),
    ]


CLIENT_MESSAGE = 33
STATE_ADD = 1
SOURCE_APPLICATION = 1
# SubstructureNotify | SubstructureRedirect: how EWMH requests reach the window manager.
TO_WINDOW_MANAGER = (1 << 19) | (1 << 20)


class _Xcb:
    def __init__(self) -> None:
        xcb = ctypes.CDLL("libxcb.so.1")
        libc = ctypes.CDLL(None)
        pointer, cookie = ctypes.c_void_p, _Cookie
        xcb.xcb_connect.restype = pointer
        xcb.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        xcb.xcb_connection_has_error.restype = ctypes.c_int
        xcb.xcb_connection_has_error.argtypes = [pointer]
        xcb.xcb_intern_atom.restype = cookie
        xcb.xcb_intern_atom.argtypes = [pointer, ctypes.c_uint8, ctypes.c_uint16, ctypes.c_char_p]
        xcb.xcb_intern_atom_reply.restype = ctypes.POINTER(_InternAtomReply)
        xcb.xcb_intern_atom_reply.argtypes = [pointer, cookie, pointer]
        xcb.xcb_get_property.restype = cookie
        xcb.xcb_get_property.argtypes = [
            pointer, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ]  # fmt: skip
        xcb.xcb_get_property_reply.restype = ctypes.POINTER(_GetPropertyReply)
        xcb.xcb_get_property_reply.argtypes = [pointer, cookie, pointer]
        xcb.xcb_get_property_value.restype = ctypes.POINTER(ctypes.c_uint32)
        xcb.xcb_get_property_value.argtypes = [ctypes.POINTER(_GetPropertyReply)]
        xcb.xcb_change_property.restype = cookie
        xcb.xcb_change_property.argtypes = [
            pointer, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint32, pointer,
        ]  # fmt: skip
        xcb.xcb_send_event.restype = cookie
        xcb.xcb_send_event.argtypes = [
            pointer,
            ctypes.c_uint8,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        xcb.xcb_get_setup.restype = pointer
        xcb.xcb_get_setup.argtypes = [pointer]
        xcb.xcb_setup_roots_iterator.restype = _ScreenIterator
        xcb.xcb_setup_roots_iterator.argtypes = [pointer]
        xcb.xcb_flush.restype = ctypes.c_int
        xcb.xcb_flush.argtypes = [pointer]
        libc.free.argtypes = [pointer]
        screen = ctypes.c_int(0)
        connection = xcb.xcb_connect(None, ctypes.byref(screen))
        if not connection or xcb.xcb_connection_has_error(connection):
            raise OSError("cannot connect to the X server")
        self._xcb = xcb
        self._free = libc.free
        self._connection = connection
        screens = xcb.xcb_setup_roots_iterator(xcb.xcb_get_setup(connection))
        if screens.rem <= screen.value:
            raise OSError("no such screen")
        # Screens vary in size, so step through them with the library, not by index.
        xcb.xcb_screen_next.restype = None
        xcb.xcb_screen_next.argtypes = [ctypes.POINTER(_ScreenIterator)]
        for _ in range(screen.value):
            xcb.xcb_screen_next(ctypes.byref(screens))
        self.root = int(screens.data[0])
        self.state = self._atom(b"_NET_WM_STATE")
        self.skip = [self._atom(name) for name in SKIP_STATES]

    def _atom(self, name: bytes) -> int:
        cookie = self._xcb.xcb_intern_atom(self._connection, 0, len(name), name)
        reply = self._xcb.xcb_intern_atom_reply(self._connection, cookie, None)
        if not reply:
            raise OSError("the X server did not answer")
        try:
            return int(reply.contents.atom)
        finally:
            self._free(reply)

    def atoms(self, window: int, prop: int) -> list[int]:
        cookie = self._xcb.xcb_get_property(self._connection, 0, window, prop, ATOM, 0, 1024)
        reply = self._xcb.xcb_get_property_reply(self._connection, cookie, None)
        if not reply:
            return []
        try:
            if reply.contents.format != 32:
                return []
            values = self._xcb.xcb_get_property_value(reply)
            return [int(values[i]) for i in range(reply.contents.value_len)]
        finally:
            self._free(reply)

    def set_atoms(self, window: int, prop: int, atoms: list[int]) -> None:
        values = (ctypes.c_uint32 * len(atoms))(*atoms)
        self._xcb.xcb_change_property(
            self._connection, PROP_MODE_REPLACE, window, prop, ATOM, 32, len(atoms), values
        )
        self._xcb.xcb_flush(self._connection)

    def ask_window_manager(self, window: int, atoms: list[int]) -> None:
        """The way to change the state of a window that is already mapped."""
        message = _ClientMessage(CLIENT_MESSAGE, 32, 0, window, self.state)
        first, second = [*atoms, 0][:2]  # one message changes at most two states
        message.data[:] = [STATE_ADD, first, second, SOURCE_APPLICATION, 0]
        self._xcb.xcb_send_event(
            self._connection, 0, self.root, TO_WINDOW_MANAGER, ctypes.byref(message)
        )
        self._xcb.xcb_flush(self._connection)


_xcb: _Xcb | None = None
_unavailable = False


def keep_off_taskbar(window: int, mapped: bool) -> None:
    """Leave an X11 window out of the taskbar and switchers.

    Called just before the window is mapped (the state is then read with the
    window) and again once it is (the window manager may have read it too
    early, so it is asked outright).
    """
    global _xcb, _unavailable
    if _unavailable:
        return
    try:
        if _xcb is None:
            _xcb = _Xcb()
        states = _xcb.atoms(window, _xcb.state)
        missing = [atom for atom in _xcb.skip if atom not in states]
        if missing and mapped:
            _xcb.ask_window_manager(window, missing)
        elif missing:
            _xcb.set_atoms(window, _xcb.state, states + missing)
    except (OSError, AttributeError) as error:
        _unavailable = True  # the notes then show in the taskbar: a nuisance, not a failure
        log.warning("cannot reach the X server directly: %s", type(error).__name__)
