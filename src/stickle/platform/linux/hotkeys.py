"""Shortcuts grabbed from the X server (an X11 session).

A passive grab on the root window sends the key to Stickle whichever window
has the keyboard. The grab is made on a connection of Stickle's own (libxcb,
as Qt uses), read whenever the X server writes to it. Caps Lock and Num Lock
change the modifiers a key arrives with, so each shortcut is grabbed with
and without them. A key held down repeats; the repeats are not counted.
"""

import ctypes
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QSocketNotifier

from stickle.platform.hotkeys import Combo

log = logging.getLogger(__name__)

# Alt is Mod1, Num Lock Mod2, the Windows (Super) key Mod4.
SHIFT, LOCK, CONTROL, MOD1, MOD2, MOD4 = 1, 2, 4, 8, 16, 64
LOCKS = (0, LOCK, MOD2, LOCK | MOD2)
KEY_PRESS = 2
GRAB_MODE_ASYNC = 1
XK_F1 = 0xFFBE
REPEAT_MS = 400  # a press this soon after the last of the same key: the key held down


def keysym(key: str) -> int:
    """The X keysym of one of stickle.platform.hotkeys.KEYS, unshifted."""
    if key.startswith("F") and len(key) > 1:
        return XK_F1 + int(key[1:]) - 1
    return ord(key.lower())  # Latin-1 keysyms are the characters themselves


def modifier_mask(combo: Combo) -> int:
    mask = 0
    for on, bit in zip(combo.modifiers, (CONTROL, MOD1, SHIFT, MOD4), strict=True):
        if on:
            mask |= bit
    return mask


class _Cookie(ctypes.Structure):
    _fields_ = [("sequence", ctypes.c_uint)]


class _Setup(ctypes.Structure):
    _fields_ = [
        ("status", ctypes.c_uint8),
        ("pad0", ctypes.c_uint8),
        ("protocol_major_version", ctypes.c_uint16),
        ("protocol_minor_version", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("release_number", ctypes.c_uint32),
        ("resource_id_base", ctypes.c_uint32),
        ("resource_id_mask", ctypes.c_uint32),
        ("motion_buffer_size", ctypes.c_uint32),
        ("vendor_len", ctypes.c_uint16),
        ("maximum_request_length", ctypes.c_uint16),
        ("roots_len", ctypes.c_uint8),
        ("pixmap_formats_len", ctypes.c_uint8),
        ("image_byte_order", ctypes.c_uint8),
        ("bitmap_format_bit_order", ctypes.c_uint8),
        ("bitmap_format_scanline_unit", ctypes.c_uint8),
        ("bitmap_format_scanline_pad", ctypes.c_uint8),
        ("min_keycode", ctypes.c_uint8),
        ("max_keycode", ctypes.c_uint8),
    ]


class _ScreenIterator(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.POINTER(ctypes.c_uint32)),  # xcb_screen_t, whose first field is root
        ("rem", ctypes.c_int),
        ("index", ctypes.c_int),
    ]


class _KeyboardMappingReply(ctypes.Structure):
    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("keysyms_per_keycode", ctypes.c_uint8),
        ("sequence", ctypes.c_uint16),
        ("length", ctypes.c_uint32),
    ]


class _KeyEvent(ctypes.Structure):
    _fields_ = [
        ("response_type", ctypes.c_uint8),
        ("detail", ctypes.c_uint8),  # the keycode
        ("sequence", ctypes.c_uint16),
        ("time", ctypes.c_uint32),
        ("root", ctypes.c_uint32),
        ("event", ctypes.c_uint32),
        ("child", ctypes.c_uint32),
        ("root_x", ctypes.c_int16),
        ("root_y", ctypes.c_int16),
        ("event_x", ctypes.c_int16),
        ("event_y", ctypes.c_int16),
        ("state", ctypes.c_uint16),
    ]


class X11Hotkeys(QObject):
    def __init__(self, pressed: Callable[[int], object]) -> None:
        super().__init__()
        xcb = ctypes.CDLL("libxcb.so.1")
        libc = ctypes.CDLL(None)
        pointer, cookie = ctypes.c_void_p, _Cookie
        xcb.xcb_connect.restype = pointer
        xcb.xcb_connect.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        xcb.xcb_connection_has_error.restype = ctypes.c_int
        xcb.xcb_connection_has_error.argtypes = [pointer]
        xcb.xcb_get_setup.restype = ctypes.POINTER(_Setup)
        xcb.xcb_get_setup.argtypes = [pointer]
        xcb.xcb_setup_roots_iterator.restype = _ScreenIterator
        xcb.xcb_setup_roots_iterator.argtypes = [ctypes.POINTER(_Setup)]
        xcb.xcb_screen_next.restype = None
        xcb.xcb_screen_next.argtypes = [ctypes.POINTER(_ScreenIterator)]
        xcb.xcb_get_keyboard_mapping.restype = cookie
        xcb.xcb_get_keyboard_mapping.argtypes = [pointer, ctypes.c_uint8, ctypes.c_uint8]
        xcb.xcb_get_keyboard_mapping_reply.restype = ctypes.POINTER(_KeyboardMappingReply)
        xcb.xcb_get_keyboard_mapping_reply.argtypes = [pointer, cookie, pointer]
        xcb.xcb_get_keyboard_mapping_keysyms.restype = ctypes.POINTER(ctypes.c_uint32)
        xcb.xcb_get_keyboard_mapping_keysyms.argtypes = [ctypes.POINTER(_KeyboardMappingReply)]
        xcb.xcb_get_keyboard_mapping_keysyms_length.restype = ctypes.c_int
        xcb.xcb_get_keyboard_mapping_keysyms_length.argtypes = [
            ctypes.POINTER(_KeyboardMappingReply)
        ]
        grab_arguments = [
            pointer, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint16,
            ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8,
        ]  # fmt: skip
        xcb.xcb_grab_key_checked.restype = cookie
        xcb.xcb_grab_key_checked.argtypes = grab_arguments
        xcb.xcb_ungrab_key.restype = cookie
        xcb.xcb_ungrab_key.argtypes = [pointer, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint16]
        xcb.xcb_request_check.restype = pointer
        xcb.xcb_request_check.argtypes = [pointer, cookie]
        xcb.xcb_get_file_descriptor.restype = ctypes.c_int
        xcb.xcb_get_file_descriptor.argtypes = [pointer]
        xcb.xcb_poll_for_event.restype = pointer
        xcb.xcb_poll_for_event.argtypes = [pointer]
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
        setup = xcb.xcb_get_setup(connection)
        screens = xcb.xcb_setup_roots_iterator(setup)
        if screens.rem <= screen.value:
            raise OSError("no such screen")
        for _ in range(screen.value):
            xcb.xcb_screen_next(ctypes.byref(screens))
        self._root = int(screens.data[0])
        self._keycodes = self._read_keycodes(setup.contents)
        self._pressed = pressed
        self._grabs: dict[int, tuple[int, int]] = {}  # number: (keycode, modifiers)
        self._last_press: tuple[int, int] = (0, 0)  # keycode, time
        self._notifier = QSocketNotifier(
            xcb.xcb_get_file_descriptor(connection), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._read_events)

    def _read_keycodes(self, setup: _Setup) -> dict[int, int]:
        """Keysym: the first keycode that types it unshifted (or shifted)."""
        first, count = setup.min_keycode, setup.max_keycode - setup.min_keycode + 1
        cookie = self._xcb.xcb_get_keyboard_mapping(self._connection, first, count)
        reply = self._xcb.xcb_get_keyboard_mapping_reply(self._connection, cookie, None)
        if not reply:
            raise OSError("the X server did not answer")
        try:
            per_key = reply.contents.keysyms_per_keycode
            symbols = self._xcb.xcb_get_keyboard_mapping_keysyms(reply)
            length = self._xcb.xcb_get_keyboard_mapping_keysyms_length(reply)
            keycodes: dict[int, int] = {}
            for index in range(length):
                if index % per_key < 2:  # the key's own two levels, not other groups
                    keycodes.setdefault(int(symbols[index]), first + index // per_key)
            return keycodes
        finally:
            self._free(reply)

    def register(self, number: int, combo: Combo) -> bool:
        self.unregister(number)
        keycode = self._keycodes.get(keysym(combo.key))
        if keycode is None:
            return False  # no such key on this keyboard
        modifiers = modifier_mask(combo)
        grabbed: list[int] = []
        for lock in LOCKS:
            cookie = self._xcb.xcb_grab_key_checked(
                self._connection, 1, self._root, modifiers | lock, keycode,
                GRAB_MODE_ASYNC, GRAB_MODE_ASYNC,
            )  # fmt: skip
            error = self._xcb.xcb_request_check(self._connection, cookie)
            if error:
                self._free(error)  # BadAccess: another application grabbed it
                for done in grabbed:
                    self._xcb.xcb_ungrab_key(self._connection, keycode, self._root, done)
                self._xcb.xcb_flush(self._connection)
                return False
            grabbed.append(modifiers | lock)
        self._grabs[number] = (keycode, modifiers)
        return True

    def unregister(self, number: int) -> None:
        grab = self._grabs.pop(number, None)
        if grab is None:
            return
        keycode, modifiers = grab
        for lock in LOCKS:
            self._xcb.xcb_ungrab_key(self._connection, keycode, self._root, modifiers | lock)
        self._xcb.xcb_flush(self._connection)

    def _read_events(self) -> None:
        while event := self._xcb.xcb_poll_for_event(self._connection):
            try:
                key = _KeyEvent.from_address(event)
                if key.response_type & 0x7F == KEY_PRESS:
                    self._key_pressed(key.detail, key.state & ~(LOCK | MOD2), key.time)
            finally:
                self._free(event)

    def _key_pressed(self, keycode: int, modifiers: int, time: int) -> None:
        last_keycode, last_time = self._last_press
        self._last_press = (keycode, time)
        if keycode == last_keycode and (time - last_time) & 0xFFFFFFFF < REPEAT_MS:
            return
        for number, grab in self._grabs.items():
            if grab == (keycode, modifiers):
                self._pressed(number)
                return
